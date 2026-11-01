// Integer ALU with x86 flags (M2 subset; A_LEA is computed by the caller).
// SZ8 / SZ16 add/sub/logic run on the 32-bit adder with both operands
// shifted to the top, so CF/OF/SF/ZF come out at bit 31/32 unchanged; y is
// the result zero-extended (the caller merges it into the register).
// Undefined flags follow QEMU/Unicorn, the lock-step reference: AF = 0
// after logic ops and shifts; shift CF/OF from the value shifted by
// count - 1 (cc_helper_template.h compute_all_shl/sar); rotates set only
// CF/OF (translate.c gen_rot_rm_T1); count 0 changes nothing. SHLD/SHRD
// shift a with bits of c (gen_shiftd_rm_T1: 64-bit concatenation; 16-bit
// a:c:a, so counts above 16 match), flags as SHL/SHR.
module x86_alu
    import x86_pkg::*;
(
    input  aop_t        op,
    input  logic [1:0]  sz,
    input  logic [3:0]  cond,     // A_SETCC / A_CMOV
    input  logic [31:0] a, b,
    input  logic [31:0] c,        // A_SHLD / A_SHRD: bits shifted in
    input  flags_t      fin,      // flags before the uop
    output logic [31:0] y,
    output flags_t      f
);
    logic [32:0] sum, cs;
    logic [31:0] as, bs, ys;
    logic [4:0]  sh;
    logic        sub, carry_in, logic_op, incdec, neg;

    // shifts / rotates
    logic [4:0]  cnt, msb;
    logic [31:0] v, pre, res, rot;
    logic        is_shift, is_rot;
    logic [63:0] dx, dpre;          // SHLD / SHRD

    function automatic logic parity(input logic [7:0] x);
        return ~^x;
    endfunction

    always_comb begin
        sh = sz == SZ8 ? 5'd24 : sz == SZ16 ? 5'd16 : 5'd0;
        incdec = op == A_INC || op == A_DEC;
        neg = op == A_NEG;
        as = neg ? 32'd0 : a << sh;
        bs = (incdec ? 32'd1 : neg ? a : b) << sh;
        sub = (op == A_SUB || op == A_SBB || op == A_CMP || op == A_DEC || neg);
        carry_in = op == A_ADC || op == A_SBB ? fin.cf : 1'b0;
        logic_op = (op == A_OR || op == A_AND || op == A_XOR || op == A_TEST);
        cs = {32'd0, carry_in} << sh;
        sum = sub ? {1'b0, as} - {1'b0, bs} - cs : {1'b0, as} + {1'b0, bs} + cs;
        case (op)
            A_OR:           ys = as | bs;
            A_AND, A_TEST:  ys = as & bs;
            A_XOR:          ys = as ^ bs;
            A_MOV:          ys = bs;
            default:        ys = sum[31:0];
        endcase
        f.sf = ys[31];
        f.zf = ys == 32'd0;
        f.pf = parity(ys[sh +: 8]);
        if (logic_op) begin
            f.cf = 1'b0;
            f.of = 1'b0;
            f.af = 1'b0;
        end else begin
            f.af = as[sh + 5'd4] ^ bs[sh + 5'd4] ^ ys[sh + 5'd4];
            f.of = sub ? (as[31] ^ bs[31]) & (as[31] ^ ys[31])
                       : ~(as[31] ^ bs[31]) & (as[31] ^ ys[31]);
            f.cf = incdec ? fin.cf : sum[32];
        end
        y = ys >> sh;

        // shifts and rotates, on the operand zero (SAR: sign) extended
        is_shift = op == A_SHL || op == A_SHR || op == A_SAR || op == A_SHLD || op == A_SHRD;
        is_rot = op == A_ROL || op == A_ROR;
        cnt = b[4:0];
        msb = 5'd31 - sh;
        v = op == A_SAR ? extend(a, sz, 1'b1) : extend(a, sz, 1'b0);
        case (op)
            A_SHL:   pre = v << (cnt - 5'd1);
            A_SHR:   pre = v >> (cnt - 5'd1);
            default: pre = $signed(v) >>> (cnt - 5'd1);
        endcase
        case (op)   // one shift per statement: a ?: mixing unsigned would make >>> logical
            A_SHL:   res = pre << 1;
            A_SHR:   res = pre >> 1;
            default: res = $signed(pre) >>> 1;
        endcase
        dx = sz == SZ16 ? {16'd0, a[15:0], c[15:0], a[15:0]} : op == A_SHLD ? {a, c} : {c, a};
        if (op == A_SHLD) begin
            dpre = dx << (cnt - 5'd1);
            pre = extend(dpre[63:32], sz, 1'b0);
            res = 32'((dpre << 1) >> 32);
        end else if (op == A_SHRD) begin
            dpre = dx >> (cnt - 5'd1);
            pre = extend(dpre[31:0], sz, 1'b0);
            res = dpre[32:1];
        end else dpre = '0;
        res = extend(res, sz, 1'b0);
        rot = sz == SZ8 ? {4{a[7:0]}} : sz == SZ16 ? {2{a[15:0]}} : a;   // replicated
        rot = op == A_ROL ? rot << cnt | rot >> (6'd32 - {1'b0, cnt})
                          : rot >> cnt | rot << (6'd32 - {1'b0, cnt});
        rot = extend(rot, sz, 1'b0);
        if (is_shift || is_rot) begin
            f = fin;
            y = extend(a, sz, 1'b0);
            if (cnt != 5'd0) begin
                if (is_shift) begin
                    y = res;
                    f.cf = op == A_SHL || op == A_SHLD ? pre[msb] : pre[0];
                    f.of = pre[msb] ^ res[msb];
                    f.sf = res[msb];
                    f.zf = res == 32'd0;
                    f.pf = parity(res[7:0]);
                    f.af = 1'b0;
                end else begin
                    y = rot;
                    f.cf = op == A_ROL ? rot[0] : rot[msb];
                    f.of = op == A_ROL ? rot[msb] ^ rot[0] : rot[msb] ^ rot[msb - 5'd1];
                end
            end
        end

        case (op)
            A_ZX8:   y = extend(b, SZ8, 1'b0);
            A_ZX16:  y = extend(b, SZ16, 1'b0);
            A_SX8:   y = extend(b, SZ8, 1'b1);
            A_SX16:  y = extend(b, SZ16, 1'b1);
            A_NOT:   y = ~a;
            A_SETCC: y = {31'd0, cond_taken(cond, fin)};
            A_CMOV:  y = cond_taken(cond, fin) ? b : a;
            A_SIGN:  y = {32{sz == SZ16 ? b[15] : b[31]}};
            default: ;
        endcase
    end
endmodule
