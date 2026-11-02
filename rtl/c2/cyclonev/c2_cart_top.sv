// Slot 1 C2 cartridge on the variant A PCB (hw/slot1-cyclonev, Cyclone V
// 5CEFA9F23C8, D32 link on J5; plan/slot1_c2.md): c2_cart_core with BCLK
// through c2_bclk_pll. Ball map: gen_qsf.py from hw/slot1-cyclonev/pins.csv.
// The AGTL+ lines pass the cartridge's pass-gate translators: driven 0 or
// released, never high. A[35:32]#, DEP#, AP#, AERR#, BERR#, BINIT# balls
// carry the link in C2.
// BCLK runs at 66 MHz (plan/slot1.md D27, NM46): 100/66# low or the board jumper.
module c2_cart_top (
    input  logic        bclk,
    input  logic        link_dclk,
    input  logic [7:0]  link_down,
    output logic        link_uclk,
    output logic [7:0]  link_up,
    // P6 bus
    inout  wire  [31:3] a_n,
    inout  wire  [63:0] d_n,
    inout  wire  [4:0]  req_n,
    inout  wire         ads_n,
    inout  wire         br0_n,
    inout  wire         drdy_n,
    input  logic        bnr_n,
    input  logic        bpri_n,
    input  logic        trdy_n,
    input  logic        dbsy_n,
    input  logic [2:0]  rs_n,
    input  logic        reset_n,
    // CMOS pins from the chipset
    input  logic        intr,
    input  logic        nmi,
    input  logic        a20m_n,
    input  logic        init_n,
    input  logic        smi_n,
    input  logic        stpclk_n
);
    logic pclk, pll_locked;            // BCLK, aligned at the I/O cells
    c2_bclk_pll bclk_pll (.refclk(bclk), .rst(1'b0), .clk(pclk), .clk_in(), .locked(pll_locked));

    logic [35:3] a_drv;
    logic [63:0] d_drv;
    logic [4:0]  req_drv;
    logic        ads_drv, br0_drv, drdy_drv;
    c2_cart_core core (
        .link_dclk, .link_down, .link_uclk, .link_up, .pclk, .pclk_in(pclk), .pll_locked,
        .reset_n, .a_n(a_n[12:5]), .ads_n, .bnr_n, .bpri_n, .trdy_n, .dbsy_n, .drdy_n, .rs_n, .d_n,
        .a_drv, .req_drv, .ads_drv, .br0_drv, .drdy_drv, .d_drv, .addr_dir(), .addr_oeab(), .data_dir(),
        .data_oeab(), .intr, .nmi, .a20m_n, .init_n, .smi_n, .stpclk_n
    );

    // open drain: a_drv[35:32] is always 0 (32-bit addresses), those balls are the link
    genvar i;
    generate
        for (i = 3; i < 32; i++) begin : a_od
            assign a_n[i] = a_drv[i] ? 1'b0 : 1'bz;
        end
        for (i = 0; i < 64; i++) begin : d_od
            assign d_n[i] = d_drv[i] ? 1'b0 : 1'bz;
        end
        for (i = 0; i < 5; i++) begin : req_od
            assign req_n[i] = req_drv[i] ? 1'b0 : 1'bz;
        end
    endgenerate
    assign ads_n  = ads_drv  ? 1'b0 : 1'bz;
    assign br0_n  = br0_drv  ? 1'b0 : 1'bz;
    assign drdy_n = drdy_drv ? 1'b0 : 1'bz;
endmodule
