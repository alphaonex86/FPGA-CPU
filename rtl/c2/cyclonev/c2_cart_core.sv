// The C2 cartridge without its board pins (c2_cart_top: variant A PCB,
// pass-gates; c2_cart_gtl_top: dedicated PCB, GTL+ transceivers): c2_cart
// on the link clock received on J5, c2_bus_sync, c2_p6_agent on the PLL's
// BCLK (pclk; pclk_in clocks the agent's input registers).
module c2_cart_core #(
    parameter bit D_CLOCKED = 0      // c2_p6_agent
) (
    // J5 link: the card launches on its clock's rising edge and sends that
    // clock inverted (link_dclk rises mid-bit); the cartridge does the same
    input  logic        link_dclk,
    input  logic [7:0]  link_down,
    output logic        link_uclk,
    output logic [7:0]  link_up,
    input  logic        pclk,
    input  logic        pclk_in,
    input  logic        pll_locked,
    // P6 pin levels (low = asserted, also A# and D#) and open-drain drives
    input  logic        reset_n,
    input  logic [12:5] a_n,
    input  logic        ads_n,
    input  logic        bnr_n,
    input  logic        bpri_n,
    input  logic        trdy_n,
    input  logic        dbsy_n,
    input  logic        drdy_n,
    input  logic [2:0]  rs_n,
    input  logic [63:0] d_n,
    output logic [35:3] a_drv,
    output logic [4:0]  req_drv,
    output logic        ads_drv,
    output logic        br0_drv,
    output logic        drdy_drv,
    output logic [63:0] d_drv,
    output logic        addr_dir,
    output logic        addr_oeab,
    output logic        data_dir,
    output logic        data_oeab,
    // CMOS pins from the chipset (LINT[1:0] = NMI / INTR, no local APIC)
    input  logic        intr,
    input  logic        nmi,
    input  logic        a20m_n,
    input  logic        init_n,
    input  logic        smi_n,
    input  logic        stpclk_n
);
    wire cclk = link_dclk;

    // power-on resets (registers power up 0), one per clock; BCLK's also
    // while the PLL is unlocked
    /* verilator lint_off PROCASSINIT */
    logic [3:0] por_c = '0, por_b = '0;
    /* verilator lint_on PROCASSINIT */
    always_ff @(posedge cclk) if (!(&por_c)) por_c <= por_c + 1'b1;
    always_ff @(posedge pclk or negedge pll_locked)
        if (!pll_locked) por_b <= '0;
        else if (!(&por_b)) por_b <= por_b + 1'b1;
    wire crst = !(&por_c), brst = !(&por_b);

    // ---- link I/O: input and output registers in the I/O cells
    logic [7:0] down_q, up_c;
    always_ff @(posedge cclk) begin
        down_q  <= link_down;
        link_up <= up_c;
    end
    c2_clk_fwd uclk_fwd (.clk(cclk), .q(link_uclk));

    // ---- the cartridge on the link clock
    logic        bus_req, bus_space, bus_write, bus_inta, bus_special, bus_done, bus_err;
    logic [31:0] bus_addr, bus_wdata, bus_rdata;
    logic [1:0]  bus_size;
    logic        m_reset, m_low_vector, link_lost, link_flushed;
    logic [4:0]  m_pins;
    logic [1:0]  intr_s;               // a level: 2 flops
    always_ff @(posedge cclk) intr_s <= {intr_s[0], intr};
    c2_cart cart (
        .clk(cclk), .rst(crst), .down(down_q), .up(up_c), .bus_req, .bus_space, .bus_write, .bus_inta,
        .bus_special, .bus_addr, .bus_size, .bus_wdata, .bus_done, .bus_rdata, .bus_err, .intr(intr_s[1]),
        .board_reset(m_reset), .low_vector(m_low_vector), .a20m(m_pins[0]), .stpclk(m_pins[1]), .nmi(m_pins[2]),
        .init(m_pins[3]), .smi(m_pins[4]), .link_lost, .link_flushed
    );

    // ---- BCLK side
    logic        s_req, s_done, s_err, cpu_reset;
    logic [31:0] s_rdata;
    logic [12:5] straps;
    c2_bus_sync bus_sync (
        .mclk(cclk), .mrst(crst), .m_req(bus_req), .m_done(bus_done), .m_rdata(bus_rdata), .m_err(bus_err),
        .m_reset, .m_low_vector, .m_pins, .m_link_lost(link_lost), .m_link_flushed(link_flushed),
        .sclk(pclk), .srst(brst), .s_req, .s_done, .s_rdata, .s_err, .s_reset(cpu_reset), .s_low_vector(straps[6]),
        .s_pins({!smi_n, !init_n, nmi, !stpclk_n, !a20m_n})
    );
    c2_p6_agent #(.D_CLOCKED(D_CLOCKED)) agent (
        .clk(pclk), .clk_in(pclk_in), .rst(brst), .bus_req(s_req), .bus_space, .bus_write, .bus_inta,
        .bus_special, .bus_addr, .bus_size, .bus_wdata, .bus_done(s_done), .bus_rdata(s_rdata), .bus_err(s_err),
        .reset_n, .a_n, .ads_n, .bnr_n, .bpri_n, .trdy_n, .dbsy_n, .drdy_n, .rs_n, .d_n,
        .a_drv, .req_drv, .ads_drv, .br0_drv, .drdy_drv, .d_drv, .addr_dir, .addr_oeab, .data_dir, .data_oeab,
        .cpu_reset, .straps
    );
endmodule
