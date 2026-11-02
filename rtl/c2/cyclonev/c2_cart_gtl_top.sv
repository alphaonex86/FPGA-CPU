// Slot 1 C2 cartridge on its dedicated PCB (hw/slot1-c2cart, 5CEBA4F23C8 or
// an A9; plan/slot1_c2.md D33/D35): c2_cart_core behind SN74GTL16612
// transceivers. ADDR (A#, REQ#) and DATA (D#) are bidirectional LVTTL with
// a direction pair per group; A -> B (all chips) and the DATA chips'
// B -> A are clocked by BCLK through a CY2309 zero-delay buffer (D# lags
// one BCLK, D_CLOCKED). TX carries the driven control
// lines (low = assert, passed to the bus as an open-drain low); the
// observed ones come straight from the bus (SSTL-18 against VREF).
// PLL phases (c2_cart_gtl_top.sdc): the agent runs 1.75 ns after BCLK
// into the transceiver registers; its inputs sample 5 ns before BCLK.
// BCLK 66 MHz: 100/66# tied low.
module c2_cart_gtl_top #(
    parameter string PHASE    = "1750 ps",
    parameter string PHASE_IN = "10000 ps"
) (
    input  logic        bclk,
    input  logic        link_dclk,
    input  logic [7:0]  link_down,
    output logic        link_uclk,
    output logic [7:0]  link_up,
    // transceiver A sides
    inout  wire  [31:3] a_n,
    inout  wire  [4:0]  req_n,
    inout  wire  [63:0] d_n,
    output logic        addr_oeab_n,
    output logic        addr_oeba_n,
    output logic        data_oeab_n,
    output logic        data_oeba_n,
    output logic        tx_oeab_n,     // pulled up on the PCB: TX off until configured
    output logic        ab_le,         // every chip's LEAB: 0 = A -> B clocked
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
    output logic [3:0]  tx_spare_n,    // TX channels of lines C2 does not drive: released
    // CMOS pins from the chipset (pass-gates)
    input  logic        intr,
    input  logic        nmi,
    input  logic        a20m_n,
    input  logic        init_n,
    input  logic        smi_n,
    input  logic        stpclk_n
);
    logic pclk, pclk_in, pll_locked;
    c2_bclk_pll #(.PHASE(PHASE), .PHASE_IN(PHASE_IN)) bclk_pll (
        .refclk(bclk), .rst(1'b0), .clk(pclk), .clk_in(pclk_in), .locked(pll_locked)
    );

    logic [35:3] a_drv;
    logic [63:0] d_drv;
    logic [4:0]  req_drv;
    logic        ads_drv, br0_drv, drdy_drv, addr_dir, addr_oeab, data_dir, data_oeab;
    c2_cart_core #(.D_CLOCKED(1)) core (
        .link_dclk, .link_down, .link_uclk, .link_up, .pclk, .pclk_in, .pll_locked,
        .reset_n, .a_n(a_n[12:5]), .ads_n, .bnr_n, .bpri_n, .trdy_n, .dbsy_n, .drdy_n, .rs_n, .d_n,
        .a_drv, .req_drv, .ads_drv, .br0_drv, .drdy_drv, .d_drv, .addr_dir, .addr_oeab, .data_dir, .data_oeab,
        .intr, .nmi, .a20m_n, .init_n, .smi_n, .stpclk_n
    );

    // dir: the FPGA drives the LVTTL side (high = released), the
    // transceiver's B -> A path off; a_drv[35:32] is always 0
    assign a_n   = addr_dir ? ~a_drv[31:3] : 'z;
    assign req_n = addr_dir ? ~req_drv : 'z;
    assign d_n   = data_dir ? ~d_drv : 'z;
    assign addr_oeab_n = !addr_oeab;
    assign addr_oeba_n = addr_dir;
    assign data_oeab_n = !data_oeab;
    assign data_oeba_n = data_dir;
    // the TX chip's A inputs sit on bus-hold until the FPGA drives them
    assign tx_oeab_n = !pll_locked;
    assign ads_tx_n  = !ads_drv;
    assign drdy_tx_n = !drdy_drv;
    assign br0_tx_n  = !br0_drv;
    assign tx_spare_n = '1;
    assign ab_le      = 0;
endmodule
