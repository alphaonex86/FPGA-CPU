// x86_predecode against N x86_len_decode (the objdump-checked reference) on
// the same bytes; the reference is registered once to match the latency.
// bad[i]: start i differs (fault, then npfx / map / len when no fault).
module predecode_check #(
    parameter int N = 16
) (
    input  logic                clk,
    input  logic [8*(N+14)-1:0] bytes,
    input  logic                d32,
    output logic [N-1:0]        bad
);
    logic [N-1:0][3:0] len, npfx, len_r, npfx_r;
    logic [N-1:0][1:0] map, map_r;
    logic [N-1:0]      fault, fault_r, multi;   // multi: not checked (performance only)

    x86_predecode #(.N(N)) dut (.clk(clk), .bytes(bytes), .d32(d32), .len(len),
                                .npfx(npfx), .map(map), .fault(fault), .multi(multi));

    genvar i;
    generate for (i = 0; i < N; i = i + 1) begin : ref_at
        logic [3:0] l, p;
        logic [1:0] m;
        logic       unsup, too_long;
        x86_len_decode r (.win(bytes[8*i +: 8*15]), .d32(d32), .len(l), .npfx(p),
                          .map(m), .unsup(unsup), .too_long(too_long));
        always_ff @(posedge clk) begin
            len_r[i]   <= l;
            npfx_r[i]  <= p;
            map_r[i]   <= m;
            fault_r[i] <= unsup | too_long;
        end
        assign bad[i] = fault[i] != fault_r[i] || npfx[i] != npfx_r[i]
                        || !fault[i] && (len[i] != len_r[i] || map[i] != map_r[i]);
    end endgenerate
endmodule
