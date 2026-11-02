// BCLK through a Cyclone V PLL: "normal" compensates the clock network
// delay, so the I/O cell registers clock with BCLK at the pin (the raw pin
// -> clock tree path is ~5 ns, which would break P6 input hold);
// "source_synchronous" matches the clock to the pin -> input register
// path instead (less PVT skew between them). clk_in: a second phase for
// the input registers.
// The PLL is set for one board frequency.
module c2_bclk_pll #(
    parameter string FREQ     = "66.666666 MHz",
    parameter string MODE     = "normal",
    parameter string PHASE    = "0 ps",
    parameter string PHASE_IN = "0 ps"
) (
    input  logic refclk,
    input  logic rst,
    output logic clk,
    output logic clk_in,
    output logic locked
);
    logic [1:0] outclk;
    altera_pll #(
        .reference_clock_frequency(FREQ), .operation_mode(MODE), .number_of_clocks(2),
        .output_clock_frequency0(FREQ), .phase_shift0(PHASE), .duty_cycle0(50),
        .output_clock_frequency1(FREQ), .phase_shift1(PHASE_IN), .duty_cycle1(50),
        .fractional_vco_multiplier("false"), .pll_type("General"), .pll_subtype("General")
    ) pll (
        .refclk(refclk), .rst(rst), .outclk(outclk), .locked(locked), .fboutclk(), .fbclk(1'b0)
    );
    assign clk    = outclk[0];
    assign clk_in = outclk[1];
endmodule
