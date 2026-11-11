// A global clock stopped glitch-free while ena is low (Cyclone V clock control block; ena is
// registered on the clock's falling edge, so it may come from another domain).
module c2_clk_gate (
    input  logic clk,
    input  logic ena,
    output logic gclk
);
    cyclonev_clkena #(.clock_type("global clock"), .ena_register_mode("falling edge"))
        gate (.inclk(clk), .ena(ena), .enaout(), .outclk(gclk));
endmodule
