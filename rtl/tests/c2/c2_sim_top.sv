// C2 bridge test model, PCIe AXI4-Stream to board bus port: c2_tlp ->
// c2_req_sync -> c2_card (link clock) -> link -> c2_cart (the cartridge
// clock: the link clock as the cartridge receives it) -> up link through
// c2_afifo back into the link clock. The C++ testbench (bus_rtl.cpp) plays
// the PCIe IP and the board.
module c2_sim_top #(
    parameter int LINK_DELAY = 3     // cartridge-side registers each way (I/O, cable)
) (
    input  logic        uclk,        // PCIe user clock
    input  logic        lclk,        // card link clock
    input  logic        cclk,        // cartridge clock
    input  logic        rst,
    input  logic [63:0] rx_tdata,
    input  logic [7:0]  rx_tkeep,
    input  logic        rx_tlast,
    input  logic        rx_tvalid,
    output logic        rx_tready,
    input  logic [21:0] rx_tuser,
    output logic [63:0] tx_tdata,
    output logic [7:0]  tx_tkeep,
    output logic        tx_tlast,
    output logic        tx_tvalid,
    input  logic        tx_tready,
    input  logic [15:0] completer_id,
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
    logic        start, write, done, tlp_err;
    logic [12:0] addr;
    logic [63:0] wdata, rdata;
    logic        req_valid, req_ready, req_write, rsp_valid;
    logic [12:0] req_addr;
    logic [63:0] req_wdata, rsp_data;
    logic [7:0]  down_card, down_cart, up_cart, up_card;
    logic        up_valid, up_overflow, tlp_err_l;
    logic [2:0]  tlp_err_s;

    c2_tlp tlp (
        .clk(uclk), .rst, .rx_tdata, .rx_tkeep, .rx_tlast, .rx_tvalid, .rx_tready, .rx_tuser,
        .tx_tdata, .tx_tkeep, .tx_tlast, .tx_tvalid, .tx_tready, .completer_id,
        .start, .write, .addr, .wdata, .done, .rdata, .err(tlp_err)
    );
    c2_req_sync sync (
        .uclk, .urst(rst), .start, .write, .addr, .wdata, .done, .rdata,
        .lclk, .lrst(rst), .req_valid, .req_ready, .req_write, .req_addr, .req_wdata, .rsp_valid, .rsp_data
    );
    // a TLP error pulse (uclk) stretched into the link clock: sticky
    always_ff @(posedge uclk) if (rst) tlp_err_l <= 0; else if (tlp_err) tlp_err_l <= 1;
    always_ff @(posedge lclk) tlp_err_s <= rst ? '0 : {tlp_err_s[1:0], tlp_err_l};

    c2_card card (
        .clk(lclk), .rst, .req_valid, .req_ready, .req_write, .req_addr, .req_wdata, .rsp_valid, .rsp_data,
        .down(down_card), .up(up_card), .up_valid, .ext_err(up_overflow || tlp_err_s[2])
    );

    logic [7:0] down_pipe [LINK_DELAY], up_pipe [LINK_DELAY];
    always_ff @(posedge cclk) begin
        down_pipe[0] <= down_card;
        up_pipe[0]   <= up_cart;
        for (int i = 1; i < LINK_DELAY; i++) begin
            down_pipe[i] <= down_pipe[i - 1];
            up_pipe[i]   <= up_pipe[i - 1];
        end
    end
    assign down_cart = down_pipe[LINK_DELAY - 1];

    c2_cart cart (
        .clk(cclk), .rst, .down(down_cart), .up(up_cart), .bus_req, .bus_space, .bus_write, .bus_inta,
        .bus_addr, .bus_size, .bus_wdata, .bus_done, .bus_rdata, .bus_err, .intr
    );

    // up bytes on the cartridge clock (as the card receives them with the
    // returned clock) into the link clock
    logic up_overflow_w, up_valid_n;
    logic [1:0] up_overflow_s;
    c2_afifo #(.W(8), .AW(3)) up_fifo (
        .wclk(cclk), .wrst(rst), .we(1'b1), .wd(up_pipe[LINK_DELAY - 1]), .overflow(up_overflow_w),
        .rclk(lclk), .rrst(rst), .re(1'b1), .rd(up_card), .empty(up_valid_n)
    );
    assign up_valid = !up_valid_n;
    always_ff @(posedge lclk) up_overflow_s <= rst ? '0 : {up_overflow_s[0], up_overflow_w};
    assign up_overflow = up_overflow_s[1];
endmodule
