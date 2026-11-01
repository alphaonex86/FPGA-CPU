// Area/fmax harness for synth_cv.sh: x86_predecode (2 stages) between an
// input register (the L1I read register) and an output register.
module x86_predecode_synth (
  input  wire clk,
  input  wire [239:0] bytes_in,
  input  wire d32_in,
  output wire [159:0] out
);
    logic [239:0] bytes_q;
    logic         d32_q;
    logic [15:0][3:0] len, npfx;
    logic [15:0][1:0] map;
    logic [15:0]      fault;
    logic [159:0]     out_q;

    x86_predecode #(.N(16)) dut (.clk(clk), .bytes(bytes_q), .d32(d32_q), .len(len), .npfx(npfx),
                                  .map(map), .fault(fault));

    always_ff @(posedge clk) begin
        bytes_q <= bytes_in;
        d32_q   <= d32_in;
        out_q   <= {len, npfx, map, fault};
    end
    assign out = out_q;
endmodule
