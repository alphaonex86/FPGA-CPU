// Integer ALU with x86 flags (M2 subset; A_LEA is computed by the caller).
// SZ8 / SZ16 operations run on the 32-bit adder with both operands shifted
// to the top, so CF/OF/SF/ZF come out at bit 31/32 unchanged; y is the
// result zero-extended (the caller merges it into the register).
// Undefined flags follow QEMU/Unicorn (AF = 0 after logic ops), the
// lock-step reference.
module x86_alu
    import x86_pkg::*;
(
    input  aop_t        op,
    input  logic [1:0]  sz,
    input  logic [31:0] a, b,
    input  flags_t      fin,      // flags before the uop (ADC/SBB/INC/DEC)
    output logic [31:0] y,
    output flags_t      f
);
    logic [32:0] sum, cs;
    logic [31:0] as, bs, ys;
    logic [4:0]  sh;
    logic        sub, carry_in, logic_op, incdec;

    always_comb begin
        sh = sz == SZ8 ? 5'd24 : sz == SZ16 ? 5'd16 : 5'd0;
        incdec = op == A_INC || op == A_DEC;
        as = a << sh;
        bs = (incdec ? 32'd1 : b) << sh;
        sub = (op == A_SUB || op == A_SBB || op == A_CMP || op == A_DEC);
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
        case (op)
            A_ZX8:   y = extend(b, SZ8, 1'b0);
            A_ZX16:  y = extend(b, SZ16, 1'b0);
            A_SX8:   y = extend(b, SZ8, 1'b1);
            A_SX16:  y = extend(b, SZ16, 1'b1);
            default: y = ys >> sh;
        endcase
        f.sf = ys[31];
        f.zf = ys == 32'd0;
        f.pf = ~^ys[sh +: 8];
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
    end
endmodule
