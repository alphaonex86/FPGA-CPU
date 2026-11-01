// Predecode (plan/x86_core.md M1): the length decode of an instruction
// starting at each of the N bytes of a block; same results as
// x86_len_decode at every start. bytes holds the block plus the 14 bytes
// after it. Two stages, results one clock after bytes:
//   1. per byte: prefix flags and x86_opdecode as if the opcode were there
//   2. per start: end of the prefix run (one-hot), select that opcode's
//      length for the operand / address size the prefixes give
module x86_predecode #(
    parameter int N = 16
) (
    input  logic                clk,
    input  logic [8*(N+14)-1:0] bytes,
    input  logic                d32,
    output logic [N-1:0][3:0]   len,      // valid when !fault
    output logic [N-1:0][3:0]   npfx,
    output logic [N-1:0][1:0]   map,
    output logic [N-1:0]        fault     // unsupported (#UD) or > 15 bytes (#GP)
);
    localparam int B = N + 14;

    function automatic logic is_prefix(input logic [7:0] x);
        case (x)
            8'h26, 8'h2E, 8'h36, 8'h3E, 8'h64, 8'h65, 8'h66, 8'h67,
            8'hF0, 8'hF2, 8'hF3: return 1'b1;
            default: return 1'b0;
        endcase
    endfunction

    // stage 1
    logic [8*(B+10)-1:0]          padded;
    logic [B-1:0]                 pfx, p66, p67;
    logic [B-1:0][1:0][1:0][3:0]  oplen;
    logic [B-1:0][1:0]            opmap;
    logic [B-1:0]                 opunsup;
    logic [B-1:0]                 pfx_q, p66_q, p67_q;
    logic [B-1:0][1:0][1:0][3:0]  oplen_q;
    logic [B-1:0][1:0]            opmap_q;
    logic [B-1:0]                 opunsup_q;
    logic                         d32_q;

    assign padded = {80'd0, bytes};

    genvar j;
    generate for (j = 0; j < B; j = j + 1) begin : at
        assign pfx[j] = is_prefix(bytes[8*j +: 8]);
        assign p66[j] = bytes[8*j +: 8] == 8'h66;
        assign p67[j] = bytes[8*j +: 8] == 8'h67;
        x86_opdecode od (.win(padded[8*j +: 8*11]), .len(oplen[j]), .map(opmap[j]),
                         .unsup(opunsup[j]));
    end endgenerate

    always_ff @(posedge clk) begin
        pfx_q     <= pfx;
        p66_q     <= p66;
        p67_q     <= p67;
        oplen_q   <= oplen;
        opmap_q   <= opmap;
        opunsup_q <= opunsup;
        d32_q     <= d32;
    end

    // stage 2: run[t] = bytes i..i+t-1 are all prefixes; the opcode sits at
    // i+t where run[t] && !pfx[i+t] (t < 14), or at i+14 after 14 prefixes
    logic [14:0] run, at_t;
    logic        osz16, asz16;
    logic [4:0]  total;

    always_comb begin
        for (int i = 0; i < N; i++) begin
            for (int t = 0; t < 15; t++)
                run[t] = &(pfx_q[i +: 14] | ~((14'd1 << t) - 14'd1));
            for (int t = 0; t < 14; t++) at_t[t] = run[t] & !pfx_q[i+t];
            at_t[14] = run[14];
            osz16 = !d32_q ^ |(p66_q[i +: 14] & run[14:1]);
            asz16 = !d32_q ^ |(p67_q[i +: 14] & run[14:1]);
            total = 5'd0;
            npfx[i] = 4'd0;
            map[i] = 2'd0;
            fault[i] = 1'b0;
            for (int t = 0; t < 15; t++)
                if (at_t[t]) begin
                    total = total | 5'(t + oplen_q[i+t][asz16][osz16]);
                    npfx[i] = npfx[i] | 4'(t);
                    map[i] = map[i] | opmap_q[i+t];
                    fault[i] = fault[i] | opunsup_q[i+t];
                end
            fault[i] = fault[i] | total > 5'd15 | run[14] & pfx_q[i+14];
            len[i] = total[3:0];
        end
    end
endmodule
