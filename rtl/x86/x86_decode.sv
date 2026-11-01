// One x86 instruction -> up to 3 uops (plan/x86_core.md M2 subset, 32-bit
// code, no prefixes): ALU ops 01-3D, 81/83, INC/DEC 40-4F + FF /0 /1,
// TEST 85/A9/F7 /0, MOV 89/8B/B8-BF/C7 /0, LEA, PUSH r32/imm/r/m, POP r32,
// CALL rel32/r32, RET, JMP rel/r/m, Jcc rel8/rel32, NOP, HLT. Anything else
// is one K_ILL uop.
// Memory destinations: LD TMP; ALU TMP; ST TMP. Static prediction: direct
// JMP/CALL and backward Jcc taken (redirect), the rest not taken.
module x86_decode
    import x86_pkg::*;
(
    input  logic [8*15-1:0] bytes,
    input  logic [31:0]     eip,
    input  logic [3:0]      len,
    input  logic            fault,      // predecode: #UD or > 15 bytes
    output uop_t [2:0]      uop,
    output logic [1:0]      n,          // valid uops: uop[0 .. n-1]
    output logic            redirect,   // frontend continues at target
    output logic [31:0]     target
);
    function automatic logic [7:0] b(input int i);
        return i < 15 ? bytes[8*i +: 8] : 8'h00;
    endfunction
    function automatic logic [31:0] sx8(input int i);
        return {{24{b(i) >= 8'h80}}, b(i)};
    endfunction
    function automatic logic [31:0] imm32_at(input int i);
        return {b(i + 3), b(i + 2), b(i + 1), b(i)};
    endfunction

    logic [7:0]  op, modrm, sib;
    logic [31:0] next_eip, disp, imm, rel;
    logic        mem;
    int          ipos;       // first byte after ModRM / SIB / displacement
    uop_t        u, mop;     // template, memory-access template
    aop_t        aop;
    logic [2:0]  reg_f, rm;

    // r32 operand of ModRM.reg / ModRM.rm (mod = 11)
    function automatic logic [3:0] r4(input logic [2:0] r);
        return {1'b0, r};
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

    function automatic logic reads_flags(input aop_t a);
        return (a == A_ADC || a == A_SBB || a == A_INC || a == A_DEC);
    endfunction

    // ALU uop "d = d op src" (src = register s or immediate); CMP/TEST do not
    // write d, MOV writes no flags
    function automatic uop_t alu(input uop_t t, input aop_t a, input logic [3:0] dr,
                                 input logic us, input logic [3:0] s, input logic [31:0] i);
        uop_t x = t;
        x.kind = K_ALU;
        x.aop = a;
        x.dst = dr;
        x.wdst = !(a == A_CMP || a == A_TEST);
        x.s1 = dr;
        x.us1 = a != A_MOV;
        x.s2 = s;
        x.us2 = us;
        x.imm = i;
        x.rflags = reads_flags(a);
        x.wflags = a != A_MOV;
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
    function automatic uop_t load_tmp();
        uop_t x = mop;
        x.kind = K_LD; x.dst = R_TMP; x.wdst = 1'b1; x.eop = 1'b0;
        return x;
    endfunction

    // the three forms of an ALU instruction on ModRM: reg op= r/m, r/m op= reg
    // or r/m op= imm; dst_rm selects which side is written
    task automatic alu_modrm(input aop_t a, input logic dst_rm, input logic us,
                             input logic [31:0] i, output uop_t [2:0] uo, output logic [1:0] no);
        uop_t ld, st;
        uo = '0;
        ld = load_tmp();
        st = mop; st.kind = K_ST; st.s3 = R_TMP; st.us3 = 1'b1;
        if (!mem) begin
            uo[0] = dst_rm ? alu(u, a, r4(rm), us, r4(reg_f), i)
                            : alu(u, a, r4(reg_f), 1'b1, r4(rm), i);
            no = 2'd1;
        end else if (!dst_rm) begin
            if (a == A_MOV) begin
                uo[0] = ld; uo[0].dst = r4(reg_f); uo[0].eop = 1'b1;
                no = 2'd1;
            end else begin
                uo[0] = ld;
                uo[1] = alu(u, a, r4(reg_f), 1'b1, R_TMP, i);
                no = 2'd2;
            end
        end else if (a == A_MOV) begin
            uo[0] = st; uo[0].s3 = r4(reg_f); uo[0].us3 = us; uo[0].imm2 = i;
            no = 2'd1;
        end else begin
            uo[0] = ld;
            uo[1] = alu(u, a, R_TMP, us, r4(reg_f), i);
            no = 2'd2;
            if (a != A_CMP && a != A_TEST) begin
                uo[1].eop = 1'b0;
                uo[2] = st;
                no = 2'd3;
            end
        end
    endtask

    always_comb begin
        op = b(0);
        modrm = b(1);
        sib = b(2);
        reg_f = modrm[5:3];
        rm = modrm[2:0];
        next_eip = eip + 32'(len);
        uop = '0;
        n = 2'd1;
        redirect = 1'b0;
        target = 32'd0;

        u = '0;
        u.eop = 1'b1;
        u.next_eip = next_eip;

        // ModRM memory operand, 32-bit addressing
        mem = modrm[7:6] != 2'b11;
        mop = u;
        ipos = 2;
        disp = 32'd0;
        if (mem) begin
            if (rm == 3'd4) begin
                ipos = 3;
                mop.scale = sib[7:6];
                mop.s2 = r4(sib[5:3]);
                mop.us2 = sib[5:3] != 3'd4;
                mop.s1 = r4(sib[2:0]);
                mop.us1 = !(sib[2:0] == 3'd5 && modrm[7:6] == 2'b00);
                if (sib[2:0] == 3'd5 && modrm[7:6] == 2'b00) begin
                    disp = imm32_at(3);
                    ipos = 7;
                end
            end else begin
                mop.s1 = r4(rm);
                mop.us1 = !(rm == 3'd5 && modrm[7:6] == 2'b00);
                if (rm == 3'd5 && modrm[7:6] == 2'b00) begin
                    disp = imm32_at(2);
                    ipos = 6;
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
        imm = imm32_at(ipos);
        rel = op == 8'h0F ? imm32_at(2) : op[7:4] == 4'h7 || op == 8'hEB ? sx8(1) : imm32_at(1);
        aop = grp1(op[5:3]);

        uop[0] = u;
        uop[0].kind = K_ILL;
        casez (op)
            8'b00???001: alu_modrm(aop, 1'b1, 1'b1, 32'd0, uop, n);
            8'b00???011: alu_modrm(aop, 1'b0, 1'b1, 32'd0, uop, n);
            8'b00???101: uop[0] = alu(u, aop, 4'd0, 1'b0, 4'd0, imm32_at(1));
            8'b01000???: uop[0] = alu(u, A_INC, r4(op[2:0]), 1'b0, 4'd0, 32'd0);
            8'b01001???: uop[0] = alu(u, A_DEC, r4(op[2:0]), 1'b0, 4'd0, 32'd0);
            8'b01010???: begin   // PUSH r32
                uop[0] = push_st(1'b1, r4(op[2:0]), 32'd0);
                uop[1] = esp_add(-32'd4);
                n = 2'd2;
            end
            8'b01011???: begin   // POP r32: LD; ESP += 4; (POP ESP: value wins)
                uop[0] = u; uop[0].kind = K_LD; uop[0].eop = 1'b0;
                uop[0].dst = op[2:0] == 3'd4 ? R_TMP : r4(op[2:0]); uop[0].wdst = 1'b1;
                uop[0].s1 = R_ESP; uop[0].us1 = 1'b1;
                uop[1] = esp_add(32'd4);
                n = 2'd2;
                if (op[2:0] == 3'd4) begin
                    uop[1].eop = 1'b0;
                    uop[2] = alu(u, A_MOV, R_ESP, 1'b1, R_TMP, 32'd0);
                    n = 2'd3;
                end
            end
            8'b0111????, 8'hEB, 8'hE9: begin   // Jcc rel8, JMP rel8 / rel32
                uop[0] = u; uop[0].kind = K_BR;
                uop[0].cond = op[3:0];
                uop[0].uncond = op[7:4] != 4'h7;
                uop[0].rflags = op[7:4] == 4'h7;
                uop[0].imm = next_eip + rel;
                uop[0].pred_taken = uop[0].uncond || rel[31];
            end
            8'h0F: if (modrm[7:4] == 4'h8) begin   // Jcc rel32 (byte 1 is the opcode)
                uop[0] = u; uop[0].kind = K_BR;
                uop[0].cond = modrm[3:0];
                uop[0].rflags = 1'b1;
                uop[0].imm = next_eip + rel;
                uop[0].pred_taken = rel[31];
            end
            8'h68, 8'h6A: begin   // PUSH imm32 / imm8
                uop[0] = push_st(1'b0, 4'd0, op[1] ? sx8(1) : imm32_at(1));
                uop[1] = esp_add(-32'd4);
                n = 2'd2;
            end
            8'h81: alu_modrm(grp1(reg_f), 1'b1, 1'b0, imm, uop, n);
            8'h83: alu_modrm(grp1(reg_f), 1'b1, 1'b0, sx8(ipos), uop, n);
            8'h85: alu_modrm(A_TEST, 1'b1, 1'b1, 32'd0, uop, n);
            8'h89: alu_modrm(A_MOV, 1'b1, 1'b1, 32'd0, uop, n);
            8'h8B: alu_modrm(A_MOV, 1'b0, 1'b1, 32'd0, uop, n);
            8'h8D: if (mem) begin
                uop[0] = mop; uop[0].kind = K_ALU; uop[0].aop = A_LEA;
                uop[0].dst = r4(reg_f); uop[0].wdst = 1'b1;
            end
            8'h90: uop[0].kind = K_ALU;   // NOP: A_ADD writing nothing
            8'hA9: uop[0] = alu(u, A_TEST, 4'd0, 1'b0, 4'd0, imm32_at(1));
            8'b10111???: uop[0] = alu(u, A_MOV, r4(op[2:0]), 1'b0, 4'd0, imm32_at(1));
            8'hC3: begin   // RET: LD TMP <- [ESP]; ESP += 4; JMP TMP
                uop[0] = u; uop[0].kind = K_LD; uop[0].eop = 1'b0;
                uop[0].dst = R_TMP; uop[0].wdst = 1'b1;
                uop[0].s1 = R_ESP; uop[0].us1 = 1'b1;
                uop[1] = esp_add(32'd4); uop[1].eop = 1'b0;
                uop[2] = jmp_ind(R_TMP);
                n = 2'd3;
            end
            8'hC7: if (reg_f == 3'd0) alu_modrm(A_MOV, 1'b1, 1'b0, imm, uop, n);
            8'hE8: begin   // CALL rel32: ST [ESP-4] <- next; ESP -= 4; JMP
                uop[0] = push_st(1'b0, 4'd0, next_eip);
                uop[1] = esp_add(-32'd4); uop[1].eop = 1'b0;
                uop[2] = u; uop[2].kind = K_BR; uop[2].uncond = 1'b1;
                uop[2].imm = next_eip + rel; uop[2].pred_taken = 1'b1;
                n = 2'd3;
            end
            8'hF4: uop[0].kind = K_HLT;
            8'hF7: if (reg_f == 3'd0) alu_modrm(A_TEST, 1'b1, 1'b0, imm, uop, n);
            8'hFF: case (reg_f)
                3'd0, 3'd1: alu_modrm(reg_f == 3'd0 ? A_INC : A_DEC, 1'b1, 1'b0, 32'd0, uop, n);
                3'd2: if (!mem) begin   // CALL r32
                    uop[0] = push_st(1'b0, 4'd0, next_eip);
                    uop[1] = esp_add(-32'd4); uop[1].eop = 1'b0;
                    uop[2] = jmp_ind(r4(rm));
                    n = 2'd3;
                end
                3'd4: if (!mem) uop[0] = jmp_ind(r4(rm));
                    else begin
                        uop[0] = load_tmp();
                        uop[1] = jmp_ind(R_TMP);
                        n = 2'd2;
                    end
                3'd6: if (!mem) begin   // PUSH r/m32
                    uop[0] = push_st(1'b1, r4(rm), 32'd0);
                    uop[1] = esp_add(-32'd4);
                    n = 2'd2;
                end else begin
                    uop[0] = load_tmp();
                    uop[1] = push_st(1'b1, R_TMP, 32'd0);
                    uop[2] = esp_add(-32'd4);
                    n = 2'd3;
                end
                default: ;
            endcase
            default: ;
        endcase
        if (fault) begin
            uop = '0;
            uop[0] = u;
            uop[0].kind = K_ILL;
            n = 2'd1;
        end
        for (int k = 0; k < 3; k++)
            if (k < int'(n) && uop[k].kind == K_BR && uop[k].pred_taken) begin
                redirect = 1'b1;
                target = uop[k].imm;
            end
    end
endmodule
