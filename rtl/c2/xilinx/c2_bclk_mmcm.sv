// BCLK (66.67 MHz) through a 7 Series MMCM with BUFG feedback: the clock
// network delay is compensated, so the I/O registers clock with BCLK at the
// pin (the Xilinx twin of cyclonev/c2_bclk_pll.sv). clk: PHASE degrees
// late; clk_in (input registers): PHASE_IN degrees late. VCO 1 GHz: phase
// steps of 3 degrees (125 ps).
module c2_bclk_mmcm #(
    parameter real PHASE    = 0.0,
    parameter real PHASE_IN = 0.0
) (
    input  logic refclk,
    output logic clk,
    output logic clk_in,
    output logic locked
);
    logic fb, fb_buf, clk0, clk1;
    MMCME2_BASE #(
        .CLKIN1_PERIOD(15.0), .CLKFBOUT_MULT_F(15.0), .DIVCLK_DIVIDE(1),
        .CLKOUT0_DIVIDE_F(15.0), .CLKOUT0_PHASE(PHASE), .CLKOUT1_DIVIDE(15), .CLKOUT1_PHASE(PHASE_IN)
    ) mmcm (
        .CLKIN1(refclk), .CLKFBIN(fb_buf), .CLKFBOUT(fb), .CLKOUT0(clk0), .CLKOUT1(clk1), .LOCKED(locked),
        .RST(1'b0), .PWRDWN(1'b0),
        .CLKFBOUTB(), .CLKOUT0B(), .CLKOUT1B(), .CLKOUT2(), .CLKOUT2B(), .CLKOUT3(), .CLKOUT3B(),
        .CLKOUT4(), .CLKOUT5(), .CLKOUT6()
    );
    BUFG fb_bufg (.I(fb), .O(fb_buf));
    BUFG clk_bufg (.I(clk0), .O(clk));
    BUFG clk_in_bufg (.I(clk1), .O(clk_in));
endmodule
