// One x86 instruction -> up to 3 uops (plan/x86_core.md M2 subset, 32-bit
// code; prefixes 66 and CS/DS/ES/SS, no-ops in the flat model): ALU ops 00-3D, 80/81/83, INC/DEC 40-4F + FE/FF
// /0 /1, TEST 84/85/A8/A9/F6/F7 /0, NOT/NEG F6/F7 /2 /3, shifts and
// rotates C0/C1/D0-D3 (not RCL/RCR), MOV 88-8B/B0-BF/C6/C7 /0,
// SHLD/SHRD, MOVZX/MOVSX, SETcc, CMOVcc, CBW/CWDE/CWD/CDQ, XCHG, IMUL 0F AF/69/6B,
// MUL/IMUL/DIV/IDIV F6/F7 /4-/7 (x86_muldiv), LEA, PUSH
// r32/imm/r/m, POP r32, CALL rel32/r32, RET, LEAVE, JMP rel/r/m, Jcc
// rel8/rel32, NOP, HLT. Anything else is one K_ILL uop.
// 8/16-bit results merge into the old register (s1, or s3 for loads).
// Memory destinations: LD TMP; ALU TMP; ST TMP. Static prediction: direct
// JMP/CALL, backward Jcc and RET taken (redirect), the rest not taken; the
// RET target (uop[2].imm) is the return stack top, filled in by the core.
module x86_decode
    import x86_pkg::*;
(
    input  logic [8*15-1:0] bytes,
    input  logic [31:0]     eip,
    input  logic [3:0]      len,
    input  logic [3:0]      npfx,       // prefix bytes before the opcode
    input  logic            fault,      // predecode: #UD or > 15 bytes
    output logic            call,       // pushes next EIP on the return stack
    output logic            ret,        // pops it
    output uop_t [2:0]      uop,
    output logic [1:0]      n,          // valid uops: uop[0 .. n-1]
    output logic            redirect,   // frontend continues at target
    output logic [31:0]     target
);
    logic            p66;       // operand-size prefix
    logic            pbad;      // another prefix: K_ILL
    logic [8*15-1:0] ib;        // the instruction after the prefix

    function automatic logic [7:0] b(input int i);
        return i < 15 ? ib[8*i +: 8] : 8'h00;
    endfunction
    function automatic logic [31:0] sx8(input int i);
        return {{24{b(i) >= 8'h80}}, b(i)};
    endfunction
    function automatic logic [31:0] imm32_at(input int i);
        return {b(i + 3), b(i + 2), b(i + 1), b(i)};
    endfunction
    // immediate of operand size sz
    function automatic logic [31:0] imm_at(input int i, input logic [1:0] sz);
        return sz == SZ8 ? sx8(i) : sz == SZ16 ? {{16{b(i + 1) >= 8'h80}}, b(i + 1), b(i)} : imm32_at(i);
    endfunction

    logic [7:0]  op, op2, modrm, sib;
    logic [31:0] next_eip, disp, rel;
    logic        mem;
    int          mpos;       // ModRM position: 1, or 2 in the 0F map
    int          ipos;       // first byte after ModRM / SIB / displacement
    uop_t        u, mop;     // template, memory-access template
    aop_t        aop;
    logic [2:0]  reg_f, rm;
    logic [1:0]  wsz;        // size of the full-width opcodes: 16 / 32

    // general register r of size sz: index, AH..BH flag
    function automatic logic [3:0] gpr(input logic [2:0] r, input logic [1:0] sz);
        return sz == SZ8 ? {2'b00, r[1:0]} : {1'b0, r};
    endfunction
    function automatic logic ghi(input logic [2:0] r, input logic [1:0] sz);
        return sz == SZ8 && r[2];
    endfunction

    function automatic aop_t grp1(input logic [2:0] g);
        case (g)
            3'd0: return A_ADD;
            3'd1: return A_OR;
            3'd2: return A_ADC;
            3'd3: return A_SBB;
            3'd4: return A_AND;
            3'd5: return A_SUB;
            3'd6: return A_XOR;
            default: return A_CMP;
        endcase
    endfunction

    // shift / rotate count 0 and partial flag writes pass the old flags
    function automatic logic reads_flags(input aop_t a);
        return (a == A_ADC || a == A_SBB || a == A_INC || a == A_DEC || a == A_SHL || a == A_SHR
                || a == A_SAR || a == A_ROL || a == A_ROR || a == A_SHLD || a == A_SHRD || a == A_SETCC || a == A_CMOV);
    endfunction

    // d = f(src): d is read only to merge
    function automatic logic moves(input aop_t a);
        return (a == A_MOV || a == A_ZX8 || a == A_ZX16 || a == A_SX8 || a == A_SX16
                || a == A_SIGN || a == A_SETCC);
    endfunction

    function automatic logic writes_flags(input aop_t a);
        return !(moves(a) || a == A_NOT || a == A_CMOV);
    endfunction

    function automatic aop_t grp2(input logic [2:0] g);
        case (g)
            3'd0: return A_ROL;
            3'd1: return A_ROR;
            3'd5: return A_SHR;
            3'd7: return A_SAR;
            default: return A_SHL;   // 4 SHL, 6 SAL (2 RCL, 3 RCR: not decoded)
        endcase
    endfunction

    // ALU uop "d = d op src" of size sz (src = register s or immediate);
    // CMP/TEST do not write d
    function automatic uop_t alu(input aop_t a, input logic [1:0] sz,
                                 input logic [3:0] dr, input logic dh,
                                 input logic us, input logic [3:0] s, input logic sh,
                                 input logic [31:0] i);
        uop_t x = u;
        x.kind = K_ALU;
        x.aop = a;
        x.osz = sz;
        x.dst = dr;
        x.dhi = dh;
        x.wdst = !(a == A_CMP || a == A_TEST);
        x.s1 = dr;
        x.hi1 = dh;
        x.us1 = !moves(a) || sz != SZ32;
        x.s2 = s;
        x.hi2 = sh;
        x.us2 = us;
        x.imm = i;
        x.rflags = reads_flags(a);
        x.wflags = writes_flags(a);
        return x;
    endfunction

    // stack uops: ST [ESP-4] <- s (or i when !us), ESP += delta
    function automatic uop_t push_st(input logic us, input logic [3:0] s, input logic [31:0] i);
        uop_t x = u;
        x.kind = K_ST; x.eop = 1'b0;
        x.s1 = R_ESP; x.us1 = 1'b1; x.imm = -32'd4;
        x.s3 = s; x.us3 = us; x.imm2 = i;
        return x;
    endfunction
    function automatic uop_t esp_add(input logic [31:0] delta);
        uop_t x = u;
        x.kind = K_ALU; x.aop = A_LEA;
        x.dst = R_ESP; x.wdst = 1'b1;
        x.s1 = R_ESP; x.us1 = 1'b1; x.imm = delta;
        return x;
    endfunction
    function automatic uop_t jmp_ind(input logic [3:0] s);
        uop_t x = u;
        x.kind = K_BR; x.uncond = 1'b1; x.indirect = 1'b1;
        x.s1 = s; x.us1 = 1'b1;
        return x;
    endfunction
    function automatic uop_t load_tmp(input logic [1:0] sz);
        uop_t x = mop;
        x.kind = K_LD; x.dst = R_TMP; x.wdst = 1'b1; x.eop = 1'b0;
        x.osz = sz; x.lext = LX_ZERO;
        return x;
    endfunction

    // the three forms of an ALU instruction on ModRM: reg op= r/m, r/m op= reg
    // or r/m op= imm; dst_rm selects which side is written
    task automatic alu_modrm(input aop_t a, input logic [1:0] sz, input logic dst_rm,
                             input logic us, input logic [31:0] i,
                             output uop_t [2:0] uo, output logic [1:0] no);
        uop_t ld, st;
        logic [3:0] rg, rr;
        logic hg, hr;
        rg = gpr(reg_f, sz); hg = ghi(reg_f, sz);
        rr = gpr(rm, sz);    hr = ghi(rm, sz);
        uo = '0;
        ld = load_tmp(sz);
        st = mop; st.kind = K_ST; st.osz = sz; st.s3 = R_TMP; st.us3 = 1'b1;
        if (!mem) begin
            uo[0] = dst_rm ? alu(a, sz, rr, hr, us, rg, hg, i) : alu(a, sz, rg, hg, 1'b1, rr, hr, i);
            no = 2'd1;
        end else if (!dst_rm) begin
            if (a == A_MOV) begin
                uo[0] = ld; uo[0].eop = 1'b1;
                uo[0].dst = rg; uo[0].dhi = hg; uo[0].lext = LX_MERGE;
                uo[0].s3 = rg; uo[0].us3 = sz != SZ32;
                no = 2'd1;
            end else begin
                uo[0] = ld;
                uo[1] = alu(a, sz, rg, hg, 1'b1, R_TMP, 1'b0, i);
                no = 2'd2;
            end
        end else if (a == A_MOV) begin
            uo[0] = st; uo[0].s3 = rg; uo[0].hi3 = hg; uo[0].us3 = us; uo[0].imm2 = i;
            no = 2'd1;
        end else begin
            uo[0] = ld;
            uo[1] = alu(a, sz, R_TMP, 1'b0, us, rg, hg, i);
            no = 2'd2;
            if (a != A_CMP && a != A_TEST) begin
                uo[1].eop = 1'b0;
                uo[2] = st;
                no = 2'd3;
            end
        end
    endtask

    // shift / rotate r/m by CL (by_cl) or by cnt
    task automatic shift_rm(input aop_t a, input logic [1:0] sz, input logic by_cl,
                            input logic [31:0] cnt, output uop_t [2:0] uo, output logic [1:0] no);
        uo = '0;
        if (!mem) begin
            uo[0] = alu(a, sz, gpr(rm, sz), ghi(rm, sz), by_cl, 4'd1, 1'b0, cnt);
            no = 2'd1;
        end else begin
            uo[0] = load_tmp(sz);
            uo[1] = alu(a, sz, R_TMP, 1'b0, by_cl, 4'd1, 1'b0, cnt);
            uo[1].eop = 1'b0;
            uo[2] = mop; uo[2].kind = K_ST; uo[2].osz = sz; uo[2].s3 = R_TMP; uo[2].us3 = 1'b1;
            no = 2'd3;
        end
    endtask

    // x86_muldiv uop: a = s1, b = s2 (hi2) or imm, c = s3
    function automatic uop_t md(input aop_t a, input logic [1:0] sz, input logic [3:0] dr,
                                input logic [3:0] r1, input logic us2, input logic [3:0] r2,
                                input logic h2, input logic [31:0] i,
                                input logic [3:0] r3, input logic us3);
        uop_t x = u;
        x.kind = K_MD; x.aop = a; x.osz = sz;
        x.dst = dr; x.wdst = 1'b1;
        x.s1 = r1; x.us1 = 1'b1;
        x.s2 = r2; x.hi2 = h2; x.us2 = us2; x.imm = i;
        x.s3 = r3; x.us3 = us3;
        x.wflags = (a == A_MUL || a == A_IMUL || a == A_IMUL2);
        return x;
    endfunction

    // IMUL reg, r/m (* reg, or * imm when !by_reg)
    task automatic imul2(input logic by_reg, input logic [31:0] i,
                         output uop_t [2:0] uo, output logic [1:0] no);
        logic [3:0] rg;
        rg = gpr(reg_f, wsz);
        uo = '0;
        if (!mem) begin
            uo[0] = md(A_IMUL2, wsz, rg, gpr(rm, wsz), by_reg, rg, 1'b0, i, rg, wsz != SZ32);
            no = 2'd1;
        end else begin
            uo[0] = load_tmp(wsz);
            uo[1] = md(A_IMUL2, wsz, rg, R_TMP, by_reg, rg, 1'b0, i, rg, wsz != SZ32);
            no = 2'd2;
        end
    endtask

    // MUL / IMUL / DIV / IDIV r/m (F6/F7 /4../7): eDX:eAX or AX
    task automatic grp3_md(input logic [1:0] sz, output uop_t [2:0] uo, output logic [1:0] no);
        logic [3:0] sr;
        logic       sh, sgn, dv;
        int         k;
        sgn = reg_f[0];
        dv = reg_f[1];
        uo = '0;
        k = 0;
        sr = gpr(rm, sz);
        sh = ghi(rm, sz);
        if (mem) begin
            uo[0] = load_tmp(sz);
            sr = R_TMP;
            sh = 1'b0;
            k = 1;
        end
        if (sz == SZ8) begin   // AX = AL * src, or AL, AH = AX / src
            uo[k] = md(dv ? (sgn ? A_IDIV : A_DIV) : (sgn ? A_IMUL : A_MUL), SZ8, 4'd0, 4'd0,
                       1'b1, sr, sh, 32'd0, 4'd0, 1'b0);
            no = 2'(k + 1);
        end else if (!dv) begin   // EAX = low + flags (reads EDX: order); EDX = high (s1 = that EAX)
            uo[k] = md(sgn ? A_IMUL : A_MUL, sz, 4'd0, 4'd0, 1'b1, sr, 1'b0, 32'd0, 4'd2, 1'b1);
            uo[k + 1] = md(sgn ? A_IMULH : A_MULH, sz, 4'd2, 4'd0, 1'b0, 4'd0, 1'b0, 32'd0, 4'd2, 1'b1);
            no = 2'(k + 2);
        end else begin   // EAX = quotient; EDX = remainder (its s1 = that EAX: order)
            uo[k] = md(sgn ? A_IDIV : A_DIV, sz, 4'd0, 4'd0, 1'b1, sr, 1'b0, 32'd0, 4'd2, 1'b1);
            uo[k + 1] = md(sgn ? A_IDIVR : A_DIVR, sz, 4'd2, 4'd0, 1'b0, 4'd0, 1'b0, 32'd0, 4'd2, 1'b1);
            no = 2'(k + 2);
        end
        for (int j = 0; j < 2; j++) if (j < int'(no) - 1) uo[j].eop = 1'b0;
    endtask

    // XCHG r/m, reg: TMP <- reg; reg <- r/m; r/m <- TMP
    task automatic xchg(input logic [1:0] sz, input logic [2:0] r, input logic [2:0] m,
                        input logic m_mem, output uop_t [2:0] uo, output logic [1:0] no);
        uo = '0;
        no = 2'd3;
        if (!m_mem) begin
            uo[0] = alu(A_MOV, SZ32, R_TMP, 1'b0, 1'b1, gpr(r, sz), ghi(r, sz), 32'd0);
            uo[1] = alu(A_MOV, sz, gpr(r, sz), ghi(r, sz), 1'b1, gpr(m, sz), ghi(m, sz), 32'd0);
            uo[2] = alu(A_MOV, sz, gpr(m, sz), ghi(m, sz), 1'b1, R_TMP, 1'b0, 32'd0);
        end else begin
            uo[0] = load_tmp(sz);
            uo[1] = mop; uo[1].kind = K_ST; uo[1].osz = sz; uo[1].eop = 1'b0;
            uo[1].s3 = gpr(r, sz); uo[1].hi3 = ghi(r, sz); uo[1].us3 = 1'b1;
            uo[2] = alu(A_MOV, sz, gpr(r, sz), ghi(r, sz), 1'b1, R_TMP, 1'b0, 32'd0);
        end
        uo[0].eop = 1'b0;
        uo[1].eop = 1'b0;
    endtask

    // MOVZX / MOVSX reg, r/m (source size ssz)
    task automatic movx(input logic sx, input logic [1:0] ssz,
                        output uop_t [2:0] uo, output logic [1:0] no);
        uo = '0;
        no = 2'd1;
        if (!mem)
            uo[0] = alu(ssz == SZ8 ? (sx ? A_SX8 : A_ZX8) : (sx ? A_SX16 : A_ZX16), wsz,
                        gpr(reg_f, wsz), 1'b0, 1'b1, gpr(rm, ssz), ghi(rm, ssz), 32'd0);
        else if (wsz == SZ32) begin
            uo[0] = mop; uo[0].kind = K_LD;
            uo[0].dst = gpr(reg_f, SZ32); uo[0].wdst = 1'b1;
            uo[0].osz = ssz; uo[0].lext = sx ? LX_SIGN : LX_ZERO;
        end else begin   // 16-bit destination from memory: LD TMP; extend-merge
            uo[0] = load_tmp(ssz);
            uo[1] = alu(ssz == SZ8 ? (sx ? A_SX8 : A_ZX8) : (sx ? A_SX16 : A_ZX16), wsz,
                        gpr(reg_f, wsz), 1'b0, 1'b1, R_TMP, 1'b0, 32'd0);
            no = 2'd2;
        end
    endtask

    always_comb begin
        p66 = 1'b0;
        pbad = 1'b0;
        for (int i = 0; i < 14; i++)
            if (i < int'(npfx)) begin
                logic [7:0] x;
                x = bytes[8*i +: 8];
                p66 = p66 || x == 8'h66;
                pbad = pbad || !(x == 8'h66 || x == 8'h26 || x == 8'h2E || x == 8'h36 || x == 8'h3E);
            end
        ib = bytes >> (8 * npfx);
        wsz = p66 ? SZ16 : SZ32;
        op = b(0);
        op2 = b(1);
        mpos = op == 8'h0F ? 2 : 1;
        modrm = b(mpos);
        sib = b(mpos + 1);
        reg_f = modrm[5:3];
        rm = modrm[2:0];
        next_eip = eip + 32'(len);
        uop = '0;
        n = 2'd1;
        redirect = 1'b0;
        target = 32'd0;

        u = '0;
        u.eop = 1'b1;
        u.osz = SZ32;
        u.next_eip = next_eip;

        // ModRM memory operand, 32-bit addressing
        mem = modrm[7:6] != 2'b11;
        mop = u;
        ipos = mpos + 1;
        disp = 32'd0;
        if (mem) begin
            if (rm == 3'd4) begin
                ipos = mpos + 2;
                mop.scale = sib[7:6];
                mop.s2 = {1'b0, sib[5:3]};
                mop.us2 = sib[5:3] != 3'd4;
                mop.s1 = {1'b0, sib[2:0]};
                mop.us1 = !(sib[2:0] == 3'd5 && modrm[7:6] == 2'b00);
                if (sib[2:0] == 3'd5 && modrm[7:6] == 2'b00) begin
                    disp = imm32_at(mpos + 2);
                    ipos = mpos + 6;
                end
            end else begin
                mop.s1 = {1'b0, rm};
                mop.us1 = !(rm == 3'd5 && modrm[7:6] == 2'b00);
                if (rm == 3'd5 && modrm[7:6] == 2'b00) begin
                    disp = imm32_at(mpos + 1);
                    ipos = mpos + 5;
                end
            end
            if (modrm[7:6] == 2'b01) begin
                disp = sx8(ipos);
                ipos = ipos + 1;
            end else if (modrm[7:6] == 2'b10) begin
                disp = imm32_at(ipos);
                ipos = ipos + 4;
            end
        end
        mop.imm = disp;
        rel = op == 8'h0F ? imm32_at(2) : op[7:4] == 4'h7 || op == 8'hEB ? sx8(1) : imm32_at(1);
        aop = grp1(op[5:3]);

        uop[0] = u;
        uop[0].kind = K_ILL;
        casez (op)
            8'b00???000: alu_modrm(aop, SZ8, 1'b1, 1'b1, 32'd0, uop, n);
            8'b00???001: alu_modrm(aop, wsz, 1'b1, 1'b1, 32'd0, uop, n);
            8'b00???010: alu_modrm(aop, SZ8, 1'b0, 1'b1, 32'd0, uop, n);
            8'b00???011: alu_modrm(aop, wsz, 1'b0, 1'b1, 32'd0, uop, n);
            8'b00???100: uop[0] = alu(aop, SZ8, 4'd0, 1'b0, 1'b0, 4'd0, 1'b0, sx8(1));
            8'b00???101: uop[0] = alu(aop, wsz, 4'd0, 1'b0, 1'b0, 4'd0, 1'b0, imm_at(1, wsz));
            8'b01000???: uop[0] = alu(A_INC, wsz, {1'b0, op[2:0]}, 1'b0, 1'b0, 4'd0, 1'b0, 32'd0);
            8'b01001???: uop[0] = alu(A_DEC, wsz, {1'b0, op[2:0]}, 1'b0, 1'b0, 4'd0, 1'b0, 32'd0);
            8'b01010???: if (!p66) begin   // PUSH r32
                uop[0] = push_st(1'b1, {1'b0, op[2:0]}, 32'd0);
                uop[1] = esp_add(-32'd4);
                n = 2'd2;
            end
            8'b01011???: if (!p66) begin   // POP r32: LD; ESP += 4; (POP ESP: value wins)
                uop[0] = u; uop[0].kind = K_LD; uop[0].eop = 1'b0;
                uop[0].dst = op[2:0] == 3'd4 ? R_TMP : {1'b0, op[2:0]}; uop[0].wdst = 1'b1;
                uop[0].s1 = R_ESP; uop[0].us1 = 1'b1;
                uop[1] = esp_add(32'd4);
                n = 2'd2;
                if (op[2:0] == 3'd4) begin
                    uop[1].eop = 1'b0;
                    uop[2] = alu(A_MOV, SZ32, R_ESP, 1'b0, 1'b1, R_TMP, 1'b0, 32'd0);
                    n = 2'd3;
                end
            end
            8'h68, 8'h6A: if (!p66) begin   // PUSH imm32 / imm8
                uop[0] = push_st(1'b0, 4'd0, op[1] ? sx8(1) : imm32_at(1));
                uop[1] = esp_add(-32'd4);
                n = 2'd2;
            end
            8'b0111????, 8'hEB, 8'hE9: if (!p66) begin   // Jcc rel8, JMP rel8 / rel32
                uop[0] = u; uop[0].kind = K_BR;
                uop[0].cond = op[3:0];
                uop[0].uncond = op[7:4] != 4'h7;
                uop[0].rflags = op[7:4] == 4'h7;
                uop[0].imm = next_eip + rel;
                uop[0].pred_taken = uop[0].uncond || rel[31];
            end
            8'h0F: casez (op2)
                8'b1000????: if (!p66) begin   // Jcc rel32
                    uop[0] = u; uop[0].kind = K_BR;
                    uop[0].cond = op2[3:0];
                    uop[0].rflags = 1'b1;
                    uop[0].imm = next_eip + rel;
                    uop[0].pred_taken = rel[31];
                end
                8'b0100????: begin   // CMOVcc reg, r/m
                    alu_modrm(A_CMOV, wsz, 1'b0, 1'b1, 32'd0, uop, n);
                    for (int k = 0; k < 2; k++) uop[k].cond = op2[3:0];
                end
                8'b1001????: begin   // SETcc r/m8
                    if (!mem) uop[0] = alu(A_SETCC, SZ8, gpr(rm, SZ8), ghi(rm, SZ8), 1'b0, 4'd0, 1'b0, 32'd0);
                    else begin
                        uop[0] = alu(A_SETCC, SZ32, R_TMP, 1'b0, 1'b0, 4'd0, 1'b0, 32'd0);
                        uop[0].eop = 1'b0;
                        uop[1] = mop; uop[1].kind = K_ST; uop[1].osz = SZ8;
                        uop[1].s3 = R_TMP; uop[1].us3 = 1'b1;
                        n = 2'd2;
                    end
                    uop[0].cond = op2[3:0];
                end
                8'b1010?10?: begin   // A4/A5/AC/AD SHLD / SHRD r/m, reg (s3), imm8 / CL
                    shift_rm(op2[3] ? A_SHRD : A_SHLD, wsz, op2[0], op2[0] ? 32'd0 : sx8(ipos), uop, n);
                    for (int k = 0; k < 2; k++)
                        if (k == int'(mem)) begin
                            uop[k].s3 = gpr(reg_f, wsz);
                            uop[k].us3 = 1'b1;
                        end
                end
                8'hAF: imul2(1'b1, 32'd0, uop, n);
                8'hB6: movx(1'b0, SZ8, uop, n);
                8'hB7: movx(1'b0, SZ16, uop, n);
                8'hBE: movx(1'b1, SZ8, uop, n);
                8'hBF: movx(1'b1, SZ16, uop, n);
                default: ;
            endcase
            8'h69: imul2(1'b0, imm_at(ipos, wsz), uop, n);
            8'h6B: imul2(1'b0, sx8(ipos), uop, n);
            8'h80: alu_modrm(grp1(reg_f), SZ8, 1'b1, 1'b0, sx8(ipos), uop, n);
            8'h81: alu_modrm(grp1(reg_f), wsz, 1'b1, 1'b0, imm_at(ipos, wsz), uop, n);
            8'h83: alu_modrm(grp1(reg_f), wsz, 1'b1, 1'b0, sx8(ipos), uop, n);
            8'h84: alu_modrm(A_TEST, SZ8, 1'b1, 1'b1, 32'd0, uop, n);
            8'h85: alu_modrm(A_TEST, wsz, 1'b1, 1'b1, 32'd0, uop, n);
            8'h86: xchg(SZ8, reg_f, rm, mem, uop, n);
            8'h87: xchg(wsz, reg_f, rm, mem, uop, n);
            8'h88: alu_modrm(A_MOV, SZ8, 1'b1, 1'b1, 32'd0, uop, n);
            8'h89: alu_modrm(A_MOV, wsz, 1'b1, 1'b1, 32'd0, uop, n);
            8'h8A: alu_modrm(A_MOV, SZ8, 1'b0, 1'b1, 32'd0, uop, n);
            8'h8B: alu_modrm(A_MOV, wsz, 1'b0, 1'b1, 32'd0, uop, n);
            8'h8D: if (mem && !p66) begin
                uop[0] = mop; uop[0].kind = K_ALU; uop[0].aop = A_LEA;
                uop[0].dst = {1'b0, reg_f}; uop[0].wdst = 1'b1;
            end
            8'h90: uop[0].kind = K_ALU;   // NOP: A_ADD writing nothing
            8'h91, 8'h92, 8'h93, 8'h94, 8'h95, 8'h96, 8'h97:   // XCHG eAX, r
                xchg(wsz, 3'd0, op[2:0], 1'b0, uop, n);
            8'h98: uop[0] = p66 ? alu(A_SX8, SZ16, 4'd0, 1'b0, 1'b1, 4'd0, 1'b0, 32'd0)    // CBW
                                : alu(A_SX16, SZ32, 4'd0, 1'b0, 1'b1, 4'd0, 1'b0, 32'd0);  // CWDE
            8'h99: uop[0] = alu(A_SIGN, wsz, 4'd2, 1'b0, 1'b1, 4'd0, 1'b0, 32'd0);        // CWD / CDQ
            8'hA8: uop[0] = alu(A_TEST, SZ8, 4'd0, 1'b0, 1'b0, 4'd0, 1'b0, sx8(1));
            8'hA9: uop[0] = alu(A_TEST, wsz, 4'd0, 1'b0, 1'b0, 4'd0, 1'b0, imm_at(1, wsz));
            8'b10110???: uop[0] = alu(A_MOV, SZ8, gpr(op[2:0], SZ8), ghi(op[2:0], SZ8),
                                      1'b0, 4'd0, 1'b0, sx8(1));
            8'b10111???: uop[0] = alu(A_MOV, wsz, {1'b0, op[2:0]}, 1'b0, 1'b0, 4'd0, 1'b0, imm_at(1, wsz));
            8'hC3: if (!p66) begin   // RET: LD TMP <- [ESP]; ESP += 4; JMP TMP
                uop[0] = u; uop[0].kind = K_LD; uop[0].eop = 1'b0;
                uop[0].dst = R_TMP; uop[0].wdst = 1'b1;
                uop[0].s1 = R_ESP; uop[0].us1 = 1'b1;
                uop[1] = esp_add(32'd4); uop[1].eop = 1'b0;
                uop[2] = jmp_ind(R_TMP);
                uop[2].pred_taken = 1'b1;
                n = 2'd3;
            end
            8'hC0: if (reg_f != 3'd2 && reg_f != 3'd3) shift_rm(grp2(reg_f), SZ8, 1'b0, sx8(ipos), uop, n);
            8'hC1: if (reg_f != 3'd2 && reg_f != 3'd3) shift_rm(grp2(reg_f), wsz, 1'b0, sx8(ipos), uop, n);
            8'hD0: if (reg_f != 3'd2 && reg_f != 3'd3) shift_rm(grp2(reg_f), SZ8, 1'b0, 32'd1, uop, n);
            8'hD1: if (reg_f != 3'd2 && reg_f != 3'd3) shift_rm(grp2(reg_f), wsz, 1'b0, 32'd1, uop, n);
            8'hD2: if (reg_f != 3'd2 && reg_f != 3'd3) shift_rm(grp2(reg_f), SZ8, 1'b1, 32'd0, uop, n);
            8'hD3: if (reg_f != 3'd2 && reg_f != 3'd3) shift_rm(grp2(reg_f), wsz, 1'b1, 32'd0, uop, n);
            8'hC9: if (!p66) begin   // LEAVE: ESP <- EBP; EBP <- [ESP]; ESP += 4
                uop[0] = alu(A_MOV, SZ32, R_ESP, 1'b0, 1'b1, 4'd5, 1'b0, 32'd0);
                uop[0].eop = 1'b0;
                uop[1] = u; uop[1].kind = K_LD; uop[1].eop = 1'b0;
                uop[1].dst = 4'd5; uop[1].wdst = 1'b1;
                uop[1].s1 = R_ESP; uop[1].us1 = 1'b1;
                uop[2] = esp_add(32'd4);
                n = 2'd3;
            end
            8'hC6: if (reg_f == 3'd0) alu_modrm(A_MOV, SZ8, 1'b1, 1'b0, sx8(ipos), uop, n);
            8'hC7: if (reg_f == 3'd0) alu_modrm(A_MOV, wsz, 1'b1, 1'b0, imm_at(ipos, wsz), uop, n);
            8'hE8: if (!p66) begin   // CALL rel32: ST [ESP-4] <- next; ESP -= 4; JMP
                uop[0] = push_st(1'b0, 4'd0, next_eip);
                uop[1] = esp_add(-32'd4); uop[1].eop = 1'b0;
                uop[2] = u; uop[2].kind = K_BR; uop[2].uncond = 1'b1;
                uop[2].imm = next_eip + rel; uop[2].pred_taken = 1'b1;
                n = 2'd3;
            end
            8'hF4: uop[0].kind = K_HLT;
            8'hF6, 8'hF7: case (reg_f)
                3'd0: alu_modrm(A_TEST, op[0] ? wsz : SZ8, 1'b1, 1'b0,
                                op[0] ? imm_at(ipos, wsz) : sx8(ipos), uop, n);
                3'd2: alu_modrm(A_NOT, op[0] ? wsz : SZ8, 1'b1, 1'b0, 32'd0, uop, n);
                3'd3: alu_modrm(A_NEG, op[0] ? wsz : SZ8, 1'b1, 1'b0, 32'd0, uop, n);
                3'd4, 3'd5, 3'd6, 3'd7: grp3_md(op[0] ? wsz : SZ8, uop, n);
                default: ;
            endcase
            8'hFE: if (reg_f == 3'd0 || reg_f == 3'd1)
                alu_modrm(reg_f == 3'd0 ? A_INC : A_DEC, SZ8, 1'b1, 1'b0, 32'd0, uop, n);
            8'hFF: case (reg_f)
                3'd0, 3'd1: alu_modrm(reg_f == 3'd0 ? A_INC : A_DEC, wsz, 1'b1, 1'b0, 32'd0, uop, n);
                3'd2: if (!mem && !p66) begin   // CALL r32
                    uop[0] = push_st(1'b0, 4'd0, next_eip);
                    uop[1] = esp_add(-32'd4); uop[1].eop = 1'b0;
                    uop[2] = jmp_ind({1'b0, rm});
                    n = 2'd3;
                end
                3'd4: if (p66) ;
                    else if (!mem) uop[0] = jmp_ind({1'b0, rm});
                    else begin
                        uop[0] = load_tmp(SZ32);
                        uop[1] = jmp_ind(R_TMP);
                        n = 2'd2;
                    end
                3'd6: if (p66) ;
                    else if (!mem) begin   // PUSH r/m32
                        uop[0] = push_st(1'b1, {1'b0, rm}, 32'd0);
                        uop[1] = esp_add(-32'd4);
                        n = 2'd2;
                    end else begin
                        uop[0] = load_tmp(SZ32);
                        uop[1] = push_st(1'b1, R_TMP, 32'd0);
                        uop[2] = esp_add(-32'd4);
                        n = 2'd3;
                    end
                default: ;
            endcase
            default: ;
        endcase
        call = !p66 && (op == 8'hE8 || op == 8'hFF && reg_f == 3'd2 && !mem);
        ret = !p66 && op == 8'hC3;
        if (fault || pbad) begin
            uop = '0;
            uop[0] = u;
            uop[0].kind = K_ILL;
            n = 2'd1;
            call = 1'b0;
            ret = 1'b0;
        end
        for (int k = 0; k < 3; k++)
            if (k < int'(n) && uop[k].kind == K_BR && uop[k].pred_taken) begin
                redirect = 1'b1;
                target = uop[k].imm;
            end
    end
endmodule
