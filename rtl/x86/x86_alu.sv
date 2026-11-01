// 32-bit integer ALU with x86 flags (M2 subset; A_LEA is computed by the
// caller).
// Undefined flags follow QEMU/Unicorn (AF = 0 after logic ops), the
// lock-step reference.
module x86_alu
    import x86_pkg::*;
(
    input  aop_t        op,
    input  logic [31:0] a, b,
    input  flags_t      fin,      // flags before the uop (ADC/SBB/INC/DEC)
    output logic [31:0] y,
    output flags_t      f
);
    logic [32:0] sum;
    logic        sub, carry_in, logic_op;

    always_comb begin
        sub = (op == A_SUB || op == A_SBB || op == A_CMP || op == A_DEC);
        carry_in = op == A_ADC || op == A_SBB ? fin.cf : 1'b0;
        logic_op = (op == A_OR || op == A_AND || op == A_XOR || op == A_TEST);
        case (op)
            A_INC:  sum = {1'b0, a} + 33'd1;
            A_DEC:  sum = {1'b0, a} - 33'd1;
            default: sum = sub ? {1'b0, a} - {1'b0, b} - {32'd0, carry_in}
                               : {1'b0, a} + {1'b0, b} + {32'd0, carry_in};
        endcase
        case (op)
            A_OR:           y = a | b;
            A_AND, A_TEST:  y = a & b;
            A_XOR:          y = a ^ b;
            A_MOV:          y = b;
            default:        y = sum[31:0];
        endcase
        f.sf = y[31];
        f.zf = y == 32'd0;
        f.pf = ~^y[7:0];
        if (logic_op) begin
            f.cf = 1'b0;
            f.of = 1'b0;
            f.af = 1'b0;
        end else begin
            logic [31:0] bb;
            bb = (op == A_INC || op == A_DEC) ? 32'd1 : b;
            f.af = (a[4] ^ bb[4] ^ y[4]);
            f.of = sub ? (a[31] ^ bb[31]) & (a[31] ^ y[31])
                       : ~(a[31] ^ bb[31]) & (a[31] ^ y[31]);
            f.cf = (op == A_INC || op == A_DEC) ? fin.cf : sum[32];
        end
    end
endmodule

