// The C2 card's PCIe side on a 7 Series FPGA: the PCIe IP (pcie_ip.tcl,
// module c2_pcie, LANES wide) -> c2_tlp -> c2_req_sync -> the BAR0 request
// port of c2_card in the link clock (lclk). err: a TLP fault seen, in lclk.
module c2_pcie_bridge #(
    parameter int LANES = 2
) (
    input  logic             pcie_ref,        // from an IBUFDS_GTE2
    input  logic             pcie_rst_n,      // PERST# and the local reset
    output logic [LANES-1:0] pcie_tx_p,
    output logic [LANES-1:0] pcie_tx_n,
    input  logic [LANES-1:0] pcie_rx_p,
    input  logic [LANES-1:0] pcie_rx_n,
    output logic             user_lnk_up,
    input  logic             lclk,
    input  logic             lrst,
    output logic             req_valid,
    input  logic             req_ready,
    output logic             req_write,
    output logic [12:0]      req_addr,
    output logic [63:0]      req_wdata,
    input  logic             rsp_valid,
    input  logic [63:0]      rsp_data,
    output logic             err
);
    logic        user_clk, user_reset;
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
        .int_pclk_out_slave(), .int_pclk_sel_slave({LANES{1'b0}}), .int_pipe_rxusrclk_out(), .int_rxoutclk_out(),
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
        .sys_clk(pcie_ref), .sys_rst_n(pcie_rst_n),
        .pcie_drp_clk(1'b0), .pcie_drp_en(1'b0), .pcie_drp_we(1'b0), .pcie_drp_addr(9'd0), .pcie_drp_di(16'd0),
        .pcie_drp_do(), .pcie_drp_rdy()
    );

    logic        start, write, done, tlp_err, tlp_err_u;
    logic [12:0] addr;
    logic [63:0] wdata, rdata;
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
    assign err = tlp_err_s[2];
endmodule
