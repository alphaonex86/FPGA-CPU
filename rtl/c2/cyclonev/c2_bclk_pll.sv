// BCLK through a Cyclone V PLL: "normal" compensates the clock network
// delay, so the I/O cell registers clock with BCLK at the pin (the raw pin
// -> clock tree path is ~5 ns, which would break P6 input hold);
// "source_synchronous" matches the clock to the pin -> input register
// path instead (less PVT skew between them). clk_in: a second phase for
// the input registers.
// The PLL is set for one board frequency; it follows any reference that keeps the VCO in range
// (C8: 600-1300 MHz). VCO, when set, is a third output whose only job is to fix the VCO multiplier
// (the fitter picks the one VCO frequency that is a multiple of FREQ and of VCO); one toggle
// register keeps it from being swept before the PLL is solved.
module c2_bclk_pll #(
    parameter string FREQ     = "66.666666 MHz",
    parameter string MODE     = "normal",
    parameter string PHASE    = "0 ps",
    parameter string PHASE_IN = "0 ps",
    parameter string VCO      = ""
) (
    input  logic refclk,
    input  logic rst,
    output logic clk,
    output logic clk_in,
    output logic locked
);
    localparam int N = VCO == "" ? 2 : 3;
    logic [N-1:0] outclk;
    altera_pll #(
        .reference_clock_frequency(FREQ), .operation_mode(MODE), .number_of_clocks(N),
        .output_clock_frequency0(FREQ), .phase_shift0(PHASE), .duty_cycle0(50),
        .output_clock_frequency1(FREQ), .phase_shift1(PHASE_IN), .duty_cycle1(50),
        .output_clock_frequency2(VCO), .phase_shift2("0 ps"), .duty_cycle2(50),
        .fractional_vco_multiplier("false"), .pll_type("General"), .pll_subtype("General")
    ) pll (
        .refclk(refclk), .rst(rst), .outclk(outclk), .locked(locked), .fboutclk(), .fbclk(1'b0)
    );
    generate if (N == 3) begin : keep_vco
        (* noprune *) logic t = 1'b0;
        always_ff @(posedge outclk[N-1]) t <= !t;
    end endgenerate
    assign clk    = outclk[0];
    assign clk_in = outclk[1];
endmodule
