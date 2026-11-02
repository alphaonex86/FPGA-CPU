// C2 bridge test model: card + cartridge joined by the link, LINK_DELAY
// registers each way (I/O registers and cable); the BAR0 port and the
// cartridge bus port are driven by the C++ testbench (bus_rtl.cpp).
module c2_sim_top #(
    parameter int LINK_DELAY = 3
) (
    input  logic        clk,
    input  logic        rst,
    input  logic        req_valid,
    output logic        req_ready,
    input  logic        req_write,
    input  logic [12:0] req_addr,
    input  logic [63:0] req_wdata,
    output logic        rsp_valid,
    output logic [63:0] rsp_data,
    output logic        bus_req,
    output logic        bus_space,
    output logic        bus_write,
    output logic        bus_inta,
    output logic [31:0] bus_addr,
    output logic [1:0]  bus_size,
    output logic [31:0] bus_wdata,
    input  logic        bus_done,
    input  logic [31:0] bus_rdata,
    input  logic        bus_err,
    input  logic        intr
);
    logic [7:0] down_card, down_cart, up_cart, up_card;
    logic [7:0] down_pipe [LINK_DELAY], up_pipe [LINK_DELAY];
    always_ff @(posedge clk) begin
        down_pipe[0] <= down_card;
        up_pipe[0]   <= up_cart;
        for (int i = 1; i < LINK_DELAY; i++) begin
            down_pipe[i] <= down_pipe[i - 1];
            up_pipe[i]   <= up_pipe[i - 1];
        end
    end
    assign down_cart = down_pipe[LINK_DELAY - 1];
    assign up_card   = up_pipe[LINK_DELAY - 1];

    c2_card card (
        .clk, .rst, .req_valid, .req_ready, .req_write, .req_addr, .req_wdata, .rsp_valid, .rsp_data,
        .down(down_card), .up(up_card)
    );
    c2_cart cart (
        .clk, .rst, .down(down_cart), .up(up_cart), .bus_req, .bus_space, .bus_write, .bus_inta,
        .bus_addr, .bus_size, .bus_wdata, .bus_done, .bus_rdata, .bus_err, .intr
    );
endmodule
