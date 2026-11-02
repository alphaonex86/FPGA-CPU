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

    // ---- PCIe IP
    logic        user_clk, user_reset, user_lnk_up;
    logic [63:0] rx_tdata, tx_tdata;
    logic [7:0]  rx_tkeep, tx_tkeep;
    logic        rx_tlast, rx_tvalid, rx_tready, tx_tlast, tx_tvalid, tx_tready;
    logic [21:0] rx_tuser;
    logic [7:0]  cfg_bus_number;
    logic [4:0]  cfg_device_number;
    logic [2:0]  cfg_function_number;
    logic        cfg_to_turnoff;
    c2_pcie pcie (
        .pci_exp_txp(pcie_tx_p), .pci_exp_txn(pcie_tx_n), .pci_exp_rxp(pcie_rx_p), .pci_exp_rxn(pcie_rx_n),
        .int_pclk_out_slave(), .int_pclk_sel_slave(2'b00), .int_pipe_rxusrclk_out(), .int_rxoutclk_out(),
        .int_dclk_out(), .int_userclk1_out(), .int_userclk2_out(), .int_oobclk_out(), .int_mmcm_lock_out(),
        .int_qplllock_out(), .int_qplloutclk_out(), .int_qplloutrefclk_out(),
        .user_clk_out(user_clk), .user_reset_out(user_reset), .user_lnk_up(user_lnk_up), .user_app_rdy(),
        .tx_buf_av(), .tx_cfg_req(), .tx_err_drop(),
        .s_axis_tx_tready(tx_tready), .s_axis_tx_tdata(tx_tdata), .s_axis_tx_tkeep(tx_tkeep),
        .s_axis_tx_tlast(tx_tlast), .s_axis_tx_tvalid(tx_tvalid), .s_axis_tx_tuser(4'd0), .tx_cfg_gnt(1'b1),
        .m_axis_rx_tdata(rx_tdata), .m_axis_rx_tkeep(rx_tkeep), .m_axis_rx_tlast(rx_tlast),
        .m_axis_rx_tvalid(rx_tvalid), .m_axis_rx_tready(rx_tready), .m_axis_rx_tuser(rx_tuser),
        .rx_np_ok(1'b1), .rx_np_req(1'b1),
        .fc_cpld(), .fc_cplh(), .fc_npd(), .fc_nph(), .fc_pd(), .fc_ph(), .fc_sel(3'd0),
        .cfg_mgmt_do(), .cfg_mgmt_rd_wr_done(), .cfg_status(), .cfg_command(), .cfg_dstatus(), .cfg_dcommand(),
        .cfg_lstatus(), .cfg_lcommand(), .cfg_dcommand2(), .cfg_pcie_link_state(), .cfg_pmcsr_pme_en(),
        .cfg_pmcsr_powerstate(), .cfg_pmcsr_pme_status(), .cfg_received_func_lvl_rst(),
        .cfg_mgmt_di(32'd0), .cfg_mgmt_byte_en(4'd0), .cfg_mgmt_dwaddr(10'd0), .cfg_mgmt_wr_en(1'b0),
        .cfg_mgmt_rd_en(1'b0), .cfg_mgmt_wr_readonly(1'b0),
        .cfg_err_ecrc(1'b0), .cfg_err_ur(1'b0), .cfg_err_cpl_timeout(1'b0), .cfg_err_cpl_unexpect(1'b0),
        .cfg_err_cpl_abort(1'b0), .cfg_err_posted(1'b0), .cfg_err_cor(1'b0), .cfg_err_atomic_egress_blocked(1'b0),
        .cfg_err_internal_cor(1'b0), .cfg_err_malformed(1'b0), .cfg_err_mc_blocked(1'b0), .cfg_err_poisoned(1'b0),
        .cfg_err_norecovery(1'b0), .cfg_err_tlp_cpl_header(48'd0), .cfg_err_cpl_rdy(), .cfg_err_locked(1'b0),
        .cfg_err_acs(1'b0), .cfg_err_internal_uncor(1'b0),
        .cfg_trn_pending(1'b0), .cfg_pm_halt_aspm_l0s(1'b0), .cfg_pm_halt_aspm_l1(1'b0),
        .cfg_pm_force_state_en(1'b0), .cfg_pm_force_state(2'd0), .cfg_dsn(64'h0000_0000_4332_4231),
        .cfg_interrupt(1'b0), .cfg_interrupt_rdy(), .cfg_interrupt_assert(1'b0), .cfg_interrupt_di(8'd0),
        .cfg_interrupt_do(), .cfg_interrupt_mmenable(), .cfg_interrupt_msienable(), .cfg_interrupt_msixenable(),
        .cfg_interrupt_msixfm(), .cfg_interrupt_stat(1'b0), .cfg_pciecap_interrupt_msgnum(5'd0),
        .cfg_to_turnoff(cfg_to_turnoff), .cfg_turnoff_ok(cfg_to_turnoff),
        .cfg_bus_number(cfg_bus_number), .cfg_device_number(cfg_device_number),
        .cfg_function_number(cfg_function_number), .cfg_pm_wake(1'b0), .cfg_pm_send_pme_to(1'b0),
        .cfg_ds_bus_number(8'd0), .cfg_ds_device_number(5'd0), .cfg_ds_function_number(3'd0),
        .cfg_mgmt_wr_rw1c_as_rw(1'b0), .cfg_msg_received(), .cfg_msg_data(), .cfg_bridge_serr_en(),
        .cfg_slot_control_electromech_il_ctl_pulse(), .cfg_root_control_syserr_corr_err_en(),
        .cfg_root_control_syserr_non_fatal_err_en(), .cfg_root_control_syserr_fatal_err_en(),
        .cfg_root_control_pme_int_en(), .cfg_aer_rooterr_corr_err_reporting_en(),
        .cfg_aer_rooterr_non_fatal_err_reporting_en(), .cfg_aer_rooterr_fatal_err_reporting_en(),
        .cfg_aer_rooterr_corr_err_received(), .cfg_aer_rooterr_non_fatal_err_received(),
        .cfg_aer_rooterr_fatal_err_received(), .cfg_msg_received_err_cor(), .cfg_msg_received_err_non_fatal(),
        .cfg_msg_received_err_fatal(), .cfg_msg_received_pm_as_nak(), .cfg_msg_received_pm_pme(),
        .cfg_msg_received_pme_to_ack(), .cfg_msg_received_assert_int_a(), .cfg_msg_received_assert_int_b(),
        .cfg_msg_received_assert_int_c(), .cfg_msg_received_assert_int_d(), .cfg_msg_received_deassert_int_a(),
        .cfg_msg_received_deassert_int_b(), .cfg_msg_received_deassert_int_c(),
        .cfg_msg_received_deassert_int_d(), .cfg_msg_received_setslotpowerlimit(),
        .pl_directed_link_change(2'd0), .pl_directed_link_width(2'd0), .pl_directed_link_speed(1'b0),
        .pl_directed_link_auton(1'b0), .pl_upstream_prefer_deemph(1'b1), .pl_sel_lnk_rate(), .pl_sel_lnk_width(),
        .pl_ltssm_state(), .pl_lane_reversal_mode(), .pl_phy_lnk_up(), .pl_tx_pm_state(), .pl_rx_pm_state(),
        .pl_link_upcfg_cap(), .pl_link_gen2_cap(), .pl_link_partner_gen2_supported(), .pl_initial_link_width(),
        .pl_directed_change_done(), .pl_received_hot_rst(), .pl_transmit_hot_rst(1'b0),
        .pl_downstream_deemph_source(1'b0), .cfg_err_aer_headerlog(128'd0), .cfg_aer_interrupt_msgnum(5'd0),
        .cfg_err_aer_headerlog_set(), .cfg_aer_ecrc_check_en(), .cfg_aer_ecrc_gen_en(), .cfg_vc_tcvc_map(),
        .sys_clk(pcie_ref), .sys_rst_n(!lrst),
        .pcie_drp_clk(1'b0), .pcie_drp_en(1'b0), .pcie_drp_we(1'b0), .pcie_drp_addr(9'd0), .pcie_drp_di(16'd0),
        .pcie_drp_do(), .pcie_drp_rdy()
    );

    // ---- bridge
    logic        start, write, done, tlp_err, tlp_err_u;
    logic [12:0] addr;
    logic [63:0] wdata, rdata;
    logic        req_valid, req_ready, req_write, rsp_valid;
    logic [12:0] req_addr;
    logic [63:0] req_wdata, rsp_data;
    logic [2:0]  tlp_err_s;
    c2_tlp tlp (
        .clk(user_clk), .rst(user_reset), .rx_tdata, .rx_tkeep, .rx_tlast, .rx_tvalid, .rx_tready, .rx_tuser,
        .tx_tdata, .tx_tkeep, .tx_tlast, .tx_tvalid, .tx_tready,
        .completer_id({cfg_bus_number, cfg_device_number, cfg_function_number}),
        .start, .write, .addr, .wdata, .done, .rdata, .err(tlp_err)
    );
    c2_req_sync sync (
        .uclk(user_clk), .urst(user_reset), .start, .write, .addr, .wdata, .done, .rdata,
        .lclk, .lrst, .req_valid, .req_ready, .req_write, .req_addr, .req_wdata, .rsp_valid, .rsp_data
    );
    always_ff @(posedge user_clk) if (user_reset) tlp_err_u <= 0; else if (tlp_err) tlp_err_u <= 1;
    always_ff @(posedge lclk) tlp_err_s <= lrst ? '0 : {tlp_err_s[1:0], tlp_err_u};

    logic [7:0] down, up;
    logic       up_valid, up_empty, up_overflow, up_overflow_l;
    logic [1:0] up_overflow_s;
    c2_card card (
        .clk(lclk), .rst(lrst), .req_valid, .req_ready, .req_write, .req_addr, .req_wdata, .rsp_valid, .rsp_data,
        .down, .up, .up_valid, .ext_err(up_overflow_l || tlp_err_s[2])
    );

    // ---- link I/O
    (* IOB = "TRUE" *) logic [7:0] down_q;
    always_ff @(posedge lclk) down_q <= down;
    assign down_d = down_q;
    ODDR #(.DDR_CLK_EDGE("SAME_EDGE")) down_clk_oddr (
        .C(lclk), .CE(1'b1), .D1(1'b0), .D2(1'b1), .R(1'b0), .S(1'b0), .Q(down_clk)
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
        logic        bus_req, bus_space, bus_write, bus_inta, bus_done, bus_err, intr;
        logic [31:0] bus_addr, bus_wdata, bus_rdata;
        logic [1:0]  bus_size;
        logic        serial_valid, serial_ready;
        logic [7:0]  serial_byte, up_cart;
        c2_cart cart (
            .clk(lclk), .rst(lrst), .down, .up(up_cart), .bus_req, .bus_space, .bus_write, .bus_inta,
            .bus_addr, .bus_size, .bus_wdata, .bus_done, .bus_rdata, .bus_err, .intr
        );
        c2_loop_target #(.ROM_HEX(ROM_HEX)) target (
            .clk(lclk), .rst(lrst), .bus_req, .bus_space, .bus_write, .bus_inta, .bus_addr, .bus_size, .bus_wdata,
            .bus_done, .bus_rdata, .bus_err, .intr, .serial_valid, .serial_byte, .serial_ready, .post()
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
        else if (up_overflow_l || tlp_err_s[2]) err_seen <= 1;
    end
    always_ff @(posedge rclk) rclk_count <= rclk_count + 1'b1;
    assign led_n = ~{err_seen, req_ready, rclk_count[23], user_lnk_up};
endmodule
