// BCLK through a Cyclone V PLL in normal mode: the clock network delay is
// compensated, so the I/O cell registers clock with BCLK at the pin (the
// raw pin -> clock tree path is ~5 ns, which would break P6 input hold).
// The PLL is set for one board frequency.
module c2_bclk_pll #(
    parameter string FREQ = "66.666666 MHz"
) (
    input  logic refclk,
    input  logic rst,
    output logic clk,
    output logic locked
);
    altera_pll #(
        .reference_clock_frequency(FREQ), .operation_mode("normal"), .number_of_clocks(1),
        .output_clock_frequency0(FREQ), .phase_shift0("0 ps"), .duty_cycle0(50),
        .fractional_vco_multiplier("false"), .pll_type("General"), .pll_subtype("General")
    ) pll (
        .refclk(refclk), .rst(rst), .outclk(clk), .locked(locked), .fboutclk(), .fbclk(1'b0)
    );
endmodule
