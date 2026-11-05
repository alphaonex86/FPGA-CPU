// Slot 1 C2 Mu cartridge (hw/slot1-c2mu, XC7A100T-2FGG484; plan/slot1_c2.md
// D39/D40): the LattePanda Mu's PCIe x4 (HSIO8-11) -> c2_pcie_bridge ->
// c2_card, its link wired inside this FPGA to c2_cart_core -> c2_p6_agent
// behind the SN74GTL16612 transceivers, as c2_cart_gtl_top on the D33 board.
// Clocks: osc50 is the link clock (c2_card and c2_cart in one domain, no
// cable), BCLK through an MMCM (agent 2.25 ns = 54 deg after BCLK, input
// registers 10.75 ns = 258 deg after it: the slack balance of c2mu.xdc).
// Mu power: once configured, the FPGA presses the Mu's power button (an NMOS
// on PWR_SW#) for ~250 ms (>= 125 ms) if PSON is low: the Mu boots after the FPGA, so
// its BIOS finds the PCIe endpoint (REFCLK2 starts on device presence).
// Board power: the transceivers drive only while the slot's VTT is up.
// LED on: PCIe link up.
module c2mu_top (
    input  logic        osc50,
    input  logic        pcie_clk_p,
    input  logic        pcie_clk_n,
    output logic [3:0]  pcie_tx_p,
    output logic [3:0]  pcie_tx_n,
    input  logic [3:0]  pcie_rx_p,
    input  logic [3:0]  pcie_rx_n,
    input  logic        pcie_perst_n,
    output logic        mu_pwr_on,
    output logic        mu_rst,
    input  logic        mu_pson,
    output logic        led,
    input  logic        bclk,
    input  logic        vtt_sense,
    // transceiver A sides (c2_cart_gtl_top)
    inout  wire  [31:3] a_n,
    inout  wire  [4:0]  req_n,
    inout  wire  [63:0] d_n,
    output logic        addr_oeab_n,
    output logic        addr_oeba_n,
    output logic        data_oeab_n,
    output logic        data_oeba_n,
    output logic        tx_oeab_n,
    output logic        ab_le,
    input  logic        ads_n,
    input  logic        bnr_n,
    input  logic        bpri_n,
    input  logic        trdy_n,
    input  logic        dbsy_n,
    input  logic        drdy_n,
    input  logic [2:0]  rs_n,
    input  logic        reset_n,
    output logic        ads_tx_n,
    output logic        drdy_tx_n,
    output logic        br0_tx_n,
    output logic [3:0]  tx_spare_n,
    input  logic        intr,
    input  logic        nmi,
    input  logic        a20m_n,
    input  logic        init_n,
    input  logic        smi_n,
    input  logic        stpclk_n
);
    // ---- link clock and its reset (~1.3 ms after configuration)
    logic        lclk, lrst = 1;
    logic [16:0] por = '0;
    BUFG lclk_buf (.I(osc50), .O(lclk));
    always_ff @(posedge lclk) begin
        if (!por[16]) por <= por + 1'b1;
        lrst <= !por[16];
    end

    // ---- Mu power button: wait ~84 ms, press ~250 ms while the Mu is off
    logic [24:0] pwr_count = '0;
    logic [1:0]  pson_s;
    always_ff @(posedge lclk) begin
        pson_s <= {pson_s[0], mu_pson};
        if (!pwr_count[24]) pwr_count <= pwr_count + 1'b1;
        mu_pwr_on <= !pwr_count[24] && pwr_count[23:22] != 2'b00 && !pson_s[1];
    end
    assign mu_rst = 0;

    // ---- PCIe x4 -> BAR0 request port
    logic pcie_ref, user_lnk_up, pcie_err;
    IBUFDS_GTE2 pcie_ref_buf (.I(pcie_clk_p), .IB(pcie_clk_n), .CEB(1'b0), .O(pcie_ref), .ODIV2());
    logic        req_valid, req_ready, req_write, rsp_valid;
    logic [12:0] req_addr;
    logic [63:0] req_wdata, rsp_data;
    c2_pcie_bridge #(.LANES(4)) bridge (
        .pcie_ref, .pcie_rst_n(pcie_perst_n && !lrst), .pcie_tx_p, .pcie_tx_n, .pcie_rx_p, .pcie_rx_n,
        .user_lnk_up, .lclk, .lrst, .req_valid, .req_ready, .req_write, .req_addr, .req_wdata, .rsp_valid,
        .rsp_data, .err(pcie_err)
    );
    assign led = user_lnk_up;

    // ---- c2_card <-> c2_cart_core: the link inside the FPGA
    logic [7:0] down, up;
    logic       link_quiet;
    c2_card card (
        .clk(lclk), .rst(lrst), .req_valid, .req_ready, .req_write, .req_addr, .req_wdata, .rsp_valid, .rsp_data,
        .down, .up, .up_valid(1'b1), .ext_err(pcie_err), .link_quiet
    );

    logic pclk, pclk_in, pll_locked;
    c2_bclk_mmcm #(.PHASE(54.0), .PHASE_IN(258.0)) bclk_mmcm (
        .refclk(bclk), .clk(pclk), .clk_in(pclk_in), .locked(pll_locked)
    );

    logic [35:3] a_drv;
    logic [63:0] d_drv;
    logic [4:0]  req_drv;
    logic        ads_drv, br0_drv, drdy_drv, addr_dir, addr_oeab, data_dir, data_oeab;
    c2_cart_core #(.D_CLOCKED(1)) core (
        .link_dclk(lclk), .link_down(down), .link_uclk(), .link_up(up), .pclk, .pclk_in, .pll_locked,
        .reset_n, .a_n(a_n[12:5]), .ads_n, .bnr_n, .bpri_n, .trdy_n, .dbsy_n, .drdy_n, .rs_n, .d_n,
        .a_drv, .req_drv, .ads_drv, .br0_drv, .drdy_drv, .d_drv, .addr_dir, .addr_oeab, .data_dir, .data_oeab,
        .intr, .nmi, .a20m_n, .init_n, .smi_n, .stpclk_n
    );

    // board powered (slot VTT up), in BCLK
    logic [1:0] vtt_s;
    always_ff @(posedge pclk) vtt_s <= {vtt_s[0], vtt_sense};
    wire bus_on = vtt_s[1] && pll_locked;

    // dir: the FPGA drives the LVTTL side (high = released), the
    // transceiver's B -> A path off; a_drv[35:32] is always 0
    assign a_n   = addr_dir ? ~a_drv[31:3] : 'z;
    assign req_n = addr_dir ? ~req_drv : 'z;
    assign d_n   = data_dir ? ~d_drv : 'z;
    assign addr_oeab_n = !(addr_oeab && bus_on);
    assign addr_oeba_n = addr_dir;
    assign data_oeab_n = !(data_oeab && bus_on);
    assign data_oeba_n = data_dir;
    assign tx_oeab_n   = !bus_on;
    assign ads_tx_n    = !ads_drv;
    assign drdy_tx_n   = !drdy_drv;
    assign br0_tx_n    = !br0_drv;
    assign tx_spare_n  = '1;
    assign ab_le       = 0;
endmodule
