// Forwarded clock, inverted: low while clk is high (Cyclone V DDIO output,
// so the edge leaves from the I/O cell like the data it clocks)
module c2_clk_fwd (
    input  logic clk,
    output logic q
);
    altddio_out #(
        .width(1), .intended_device_family("Cyclone V"), .lpm_type("altddio_out"),
        .extend_oe_disable("OFF"), .invert_output("OFF"), .oe_reg("UNREGISTERED"), .power_up_high("OFF")
    ) ddio (
        .outclock(clk), .datain_h(1'b0), .datain_l(1'b1), .dataout(q),
        .aclr(1'b0), .aset(1'b0), .oe(1'b1), .outclocken(1'b1), .sclr(1'b0), .sset(1'b0), .oe_out()
    );
endmodule
