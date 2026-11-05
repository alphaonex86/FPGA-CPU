// Forwarded clock, inverted: low while clk is high (7 Series ODDR, the
// Xilinx twin of cyclonev/c2_clk_fwd.sv)
module c2_clk_fwd (
    input  logic clk,
    output logic q
);
    ODDR #(.DDR_CLK_EDGE("SAME_EDGE")) oddr (.C(clk), .CE(1'b1), .D1(1'b0), .D2(1'b1), .R(1'b0), .S(1'b0), .Q(q));
endmodule
