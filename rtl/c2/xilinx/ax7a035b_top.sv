// Slot 1 C2 PCIe card on the ALINX AX7A035B (FPGAlist/c2_cards): PCIe IP
// (pcie_ip.tcl) -> c2_tlp -> c2_req_sync -> c2_card -> link on J11
// (plan/slot1_c2.md "Cable link v0"). Link clock 50 MHz from the 200 MHz
// oscillator; the down clock leaves inverted (an ODDR), so the cartridge
// samples mid-bit, and the cartridge returns its clock the same way.
// PERST# is not on an FPGA pin in the manual: the PCIe core is reset by
// power-up (MMCM lock) and the RESET key; check the schematic on delivery.
// LEDs (low = on): 1 PCIe link up, 2 blinks while the cartridge's clock
// returns, 3 card idle, 4 a PCIe or link FIFO error seen.
// LOOPBACK (bring-up without the cartridge): c2_cart and c2_loop_target
// (ROM_HEX) inside this FPGA on the link clock, serial out on the USB UART.
module ax7a035b_top #(
    parameter bit    LOOPBACK = 0,
    parameter string ROM_HEX  = ""
) (
    input  logic       pcie_clk_p,
    input  logic       pcie_clk_n,
    output logic [1:0] pcie_tx_p,
    output logic [1:0] pcie_tx_n,
    input  logic [1:0] pcie_rx_p,
    input  logic [1:0] pcie_rx_n,
    input  logic       sys_clk_p,     // 200 MHz
    input  logic       sys_clk_n,
    input  logic       reset_key_n,
    output logic [3:0] led_n,
    // J11 (link): down = card -> cartridge
    output logic [7:0] down_d,
    output logic       down_clk,
    input  logic [7:0] up_d,
    input  logic       up_clk,
    output logic [15:0] j11_gnd,      // even pins 4-34: grounded on the cartridge, driven low
    output logic       uart_tx        // to the CP2102, 115200 8N1
);
    // ---- clocks and resets
    logic pcie_ref, sys_clk, mmcm_fb, lclk_mmcm, lclk, mmcm_locked;
    IBUFDS_GTE2 pcie_ref_buf (.I(pcie_clk_p), .IB(pcie_clk_n), .CEB(1'b0), .O(pcie_ref), .ODIV2());
    IBUFDS sys_clk_buf (.I(sys_clk_p), .IB(sys_clk_n), .O(sys_clk));
    MMCME2_BASE #(
        .CLKIN1_PERIOD(5.0), .CLKFBOUT_MULT_F(5.0), .DIVCLK_DIVIDE(1), .CLKOUT0_DIVIDE_F(20.0)
    ) mmcm (
        .CLKIN1(sys_clk), .CLKFBIN(mmcm_fb), .CLKFBOUT(mmcm_fb), .CLKOUT0(lclk_mmcm), .LOCKED(mmcm_locked),
        .RST(1'b0), .PWRDWN(1'b0),
        .CLKFBOUTB(), .CLKOUT0B(), .CLKOUT1(), .CLKOUT1B(), .CLKOUT2(), .CLKOUT2B(), .CLKOUT3(), .CLKOUT3B(),
        .CLKOUT4(), .CLKOUT5(), .CLKOUT6()
    );
    BUFG lclk_buf (.I(lclk_mmcm), .O(lclk));

    // power-up / key reset in the link clock: ~1.3 ms after lock
    logic [16:0] por = '0;
    logic        lrst = 1;
    always_ff @(posedge lclk) begin
        if (!mmcm_locked || !reset_key_n) por <= '0;
        else if (!por[16]) por <= por + 1'b1;
        lrst <= !por[16];
    end

    // ---- PCIe -> BAR0 request port
    logic        user_lnk_up, pcie_err;
    logic        req_valid, req_ready, req_write, rsp_valid;
    logic [12:0] req_addr;
    logic [63:0] req_wdata, rsp_data;
    c2_pcie_bridge #(.LANES(2)) bridge (
        .pcie_ref, .pcie_rst_n(!lrst), .pcie_tx_p, .pcie_tx_n, .pcie_rx_p, .pcie_rx_n, .user_lnk_up,
        .lclk, .lrst, .req_valid, .req_ready, .req_write, .req_addr, .req_wdata, .rsp_valid, .rsp_data,
        .err(pcie_err)
    );

    logic [7:0] down, up;
    logic       up_valid, up_empty, up_overflow, up_overflow_l, link_quiet;
    logic [1:0] up_overflow_s;
    c2_card card (
        .clk(lclk), .rst(lrst), .req_valid, .req_ready, .req_write, .req_addr, .req_wdata, .rsp_valid, .rsp_data,
        .down, .up, .up_valid, .ext_err(up_overflow_l || pcie_err), .link_quiet
    );

    // ---- link I/O
    (* IOB = "TRUE" *) logic [7:0] down_q;
    always_ff @(posedge lclk) down_q <= down;
    assign down_d = down_q;
    // held low during a link reset (c2_card link_quiet)
    ODDR #(.DDR_CLK_EDGE("SAME_EDGE")) down_clk_oddr (
        .C(lclk), .CE(1'b1), .D1(1'b0), .D2(!link_quiet), .R(1'b0), .S(1'b0), .Q(down_clk)
    );
    assign j11_gnd = '0;

    logic uclk_in, rclk;
    IBUF up_clk_ibuf (.I(up_clk), .O(uclk_in));
    BUFG up_clk_buf (.I(uclk_in), .O(rclk));
    (* IOB = "TRUE" *) logic [7:0] up_q;
    always_ff @(posedge rclk) up_q <= up_d;
    // the returned clock runs only while the cartridge is powered: its
    // domain resets from the link reset, synchronized
    logic [1:0] rrst_s;
    always_ff @(posedge rclk or posedge lrst) rrst_s <= lrst ? 2'b11 : {rrst_s[0], 1'b0};
    c2_afifo #(.W(8), .AW(3)) up_fifo (
        .wclk(rclk), .wrst(rrst_s[1]), .we(1'b1), .wd(up_q), .overflow(up_overflow),
        .rclk(lclk), .rrst(lrst), .re(1'b1), .rd(up_link), .empty(up_empty)
    );
    always_ff @(posedge lclk) up_overflow_s <= lrst ? '0 : {up_overflow_s[0], up_overflow};
    assign up_overflow_l = up_overflow_s[1];

    // ---- the cartridge: on J11, or in this FPGA
    logic [7:0] up_link;
    if (LOOPBACK) begin : loop
        logic        bus_req, bus_space, bus_write, bus_inta, bus_special, bus_done, bus_err, intr, board_reset;
        logic        a20m, stpclk, nmi, init;
        logic [31:0] bus_addr, bus_wdata, bus_rdata;
        logic [1:0]  bus_size;
        logic        serial_valid, serial_ready;
        logic [7:0]  serial_byte, up_cart;
        c2_cart cart (
            .clk(lclk), .rst(lrst), .down, .up(up_cart), .bus_req, .bus_space, .bus_write, .bus_inta, .bus_special,
            .bus_addr, .bus_size, .bus_wdata, .bus_done, .bus_rdata, .bus_err, .intr, .board_reset, .low_vector(1'b0),
            .a20m, .stpclk, .nmi, .init, .smi(1'b0), .link_lost(link_quiet), .link_flushed()
        );
        c2_loop_target #(.ROM_HEX(ROM_HEX)) target (
            .clk(lclk), .rst(lrst), .bus_req, .bus_space, .bus_write, .bus_inta, .bus_special, .bus_addr, .bus_size,
            .bus_wdata, .bus_done, .bus_rdata, .bus_err, .intr, .board_reset, .a20m, .stpclk, .nmi, .init, .serial_valid, .serial_byte, .serial_ready, .post()
        );
        c2_uart_tx uart (
            .clk(lclk), .rst(lrst), .valid(serial_valid), .data(serial_byte), .ready(serial_ready), .tx(uart_tx)
        );
        assign up       = up_cart;
        assign up_valid = 1;
    end else begin : cable
        assign up       = up_link;
        assign up_valid = !up_empty;
        assign uart_tx  = 1;
    end

    // ---- LEDs (low = on)
    logic        err_seen;
    logic [23:0] rclk_count;
    always_ff @(posedge lclk) begin
        if (lrst) err_seen <= 0;
        else if (up_overflow_l || pcie_err) err_seen <= 1;
    end
    always_ff @(posedge rclk) rclk_count <= rclk_count + 1'b1;
    assign led_n = ~{err_seen, req_ready, rclk_count[23], user_lnk_up};
endmodule
