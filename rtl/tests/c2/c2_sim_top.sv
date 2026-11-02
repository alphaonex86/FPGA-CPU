// C2 bridge test model, PCIe AXI4-Stream to board bus port: c2_tlp ->
// c2_req_sync -> c2_card (link clock) -> link -> c2_cart (the cartridge
// clock: the link clock as the cartridge receives it) -> up link through
// c2_afifo back into the link clock. The C++ testbench (bus_rtl.cpp) plays
// the PCIe IP and the board; with C2_LOOP_TARGET defined the board is
// c2_loop_target (RTL devices, the bring-up bitstream's); with C2_P6 the
// bus port crosses to BCLK (c2_bus_sync) and runs c2_p6_agent on a P6 bus
// whose chipset is FPGAcommon's p6_bif, the testbench serves its host port;
// C2_GTL adds the D35/D37 GTL+ transceivers: D# B -> A one BCLK late, and
// their direction (p6_err[9]: a drive without OEAB, also in the clock
// after it, where the registered A -> B output still holds it, or an
// OEAB/dir order that makes LVTTL contention).
// board_rst: the board's reset (into the cartridge, or p6_bif's reset);
// cpu_pins: the chipset's CMOS outputs {SMI#, INIT#, NMI, STPCLK#, A20M#},
// asserted (into the cartridge, with C2_P6 through c2_bus_sync).
// link_quiet: the card stops the down clock (the testbench stops cclk with
// C2_P6; otherwise the cartridge sees it as link_lost directly);
// inject_*: replace a down byte, or an up byte as the card receives it
// (link desync tests).
module c2_sim_top #(
    parameter int    LINK_DELAY = 3,     // cartridge-side registers each way (I/O, cable)
    /* verilator lint_off UNUSEDPARAM */   // used with C2_LOOP_TARGET only
    parameter string ROM_HEX    = "test_rom.hex"
    /* verilator lint_on UNUSEDPARAM */
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
    output logic        bus_special,
    output logic [31:0] bus_addr,
    output logic [1:0]  bus_size,
    output logic [31:0] bus_wdata,
    input  logic        bus_done,
    input  logic [31:0] bus_rdata,
    input  logic        bus_err,
    input  logic        intr,
    /* verilator lint_off UNUSEDSIGNAL */   // the loop target makes its own
    input  logic        board_rst,
    input  logic [4:0]  cpu_pins,
    /* verilator lint_on UNUSEDSIGNAL */
    output logic        serial_valid,
    output logic [7:0]  serial_byte,
    input  logic        serial_ready,
    output logic        link_quiet,
    input  logic        inject_down_valid,
    input  logic [7:0]  inject_down_byte,
    input  logic        inject_up_valid,
    input  logic [7:0]  inject_up_byte
`ifdef C2_P6
    ,
    input  logic        bclk,        // the board's BCLK
    output logic        host_req,
    output logic        host_we,
    output logic        host_io,
    output logic [35:3] host_addr,
    output logic [63:0] host_wdata,
    output logic [7:0]  host_be,
    input  logic        host_ready,
    input  logic [63:0] host_rdata,
    input  logic        host_rvalid,
    input  logic [7:0]  inta_vector,
    output logic        spc_stb,
    output logic [2:0]  spc_type,
    output logic [9:0]  p6_err,
    output logic        p6_cpu_ready
`endif
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
        .down(down_card), .up(up_card), .up_valid, .ext_err(up_overflow || tlp_err_s[2]), .link_quiet
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
    assign down_cart = inject_down_valid ? inject_down_byte : down_pipe[LINK_DELAY - 1];
`ifndef C2_P6
    logic [1:0] quiet_s;
    always_ff @(posedge cclk) quiet_s <= {quiet_s[0], link_quiet};
`endif

`ifdef C2_LOOP_TARGET
    logic        t_done, t_err, t_intr, t_reset, t_a20m, t_stpclk, t_nmi, t_init;
    logic [31:0] t_rdata;
    logic [7:0]  post;
    c2_cart cart (
        .clk(cclk), .rst, .down(down_cart), .up(up_cart), .bus_req, .bus_space, .bus_write, .bus_inta, .bus_special,
        .bus_addr, .bus_size, .bus_wdata, .bus_done(t_done), .bus_rdata(t_rdata), .bus_err(t_err), .intr(t_intr),
        .board_reset(t_reset), .low_vector(1'b0), .a20m(t_a20m), .stpclk(t_stpclk), .nmi(t_nmi), .init(t_init),
        .smi(1'b0), .link_lost(quiet_s[1]), .link_flushed()
    );
    // simulated time advances only with BAR0 accesses: 1 "ms" of the 0xf7
    // timer is 50 clocks here, so it fires while the guest loops
    c2_loop_target #(.ROM_HEX(ROM_HEX), .CLOCKS_MS(50)) target (
        .clk(cclk), .rst, .bus_req, .bus_space, .bus_write, .bus_inta, .bus_special, .bus_addr, .bus_size,
        .bus_wdata, .bus_done(t_done), .bus_rdata(t_rdata), .bus_err(t_err), .intr(t_intr), .board_reset(t_reset),
        .a20m(t_a20m), .stpclk(t_stpclk), .nmi(t_nmi), .init(t_init), .serial_valid, .serial_byte, .serial_ready, .post
    );
`elsif C2_P6
    logic        p_done, p_err, s_req, s_done, s_err, m_reset, m_low_vector, link_lost, link_flushed;
    logic [31:0] p_rdata, s_rdata;
    logic [4:0]  m_pins;
    c2_cart cart (
        .clk(cclk), .rst, .down(down_cart), .up(up_cart), .bus_req, .bus_space, .bus_write, .bus_inta, .bus_special,
        .bus_addr, .bus_size, .bus_wdata, .bus_done(p_done), .bus_rdata(p_rdata), .bus_err(p_err), .intr,
        .board_reset(m_reset), .low_vector(m_low_vector), .a20m(m_pins[0]), .stpclk(m_pins[1]), .nmi(m_pins[2]),
        .init(m_pins[3]), .smi(m_pins[4]), .link_lost, .link_flushed
    );
    c2_bus_sync bus_sync (
        .mclk(cclk), .mrst(rst), .m_req(bus_req), .m_done(p_done), .m_rdata(p_rdata), .m_err(p_err),
        .m_reset, .m_low_vector, .m_pins, .m_link_lost(link_lost), .m_link_flushed(link_flushed),
        .sclk(bclk), .srst(rst), .s_req, .s_done, .s_rdata, .s_err, .s_reset(cpu_reset), .s_low_vector(straps[6]),
        .s_pins(cpu_pins)
    );
    assign serial_valid = 0;
    assign serial_byte  = '0;

    // the P6 bus: every line is the wired-OR of its open-drain drivers
    logic [35:3] a_cpu, a_cs;
    logic [4:0]  req_cpu, req_cs;
    logic [63:0] d_cpu, d_cs;
    logic [2:0]  rs_cs;
    logic        ads_cpu, ads_cs, drdy_cpu, drdy_cs, dbsy_cs, trdy_cs, hit_cs, hitm_cs, bnr_cs, bpri_cs,
                 br0_cpu, br0_cs, reset_cs, defer_cs, binit_cs, cpu_reset;
    logic [12:5] straps;
    logic        addr_dir, addr_oeab, data_dir, data_oeab;
`ifdef C2_GTL
    // the agent's A#/REQ#/D# reach the bus only through OEAB; with dir its
    // LVTTL side carries its own levels instead of the bus
    wire [35:3] a_n   = ~((addr_oeab ? a_cpu : '0) | a_cs);
    wire [4:0]  req_n = ~((addr_oeab ? req_cpu : '0) | req_cs);
    wire [63:0] d_n   = ~((data_oeab ? d_cpu : '0) | d_cs);
    wire [12:5] a_agent = addr_dir ? ~a_cpu[12:5] : a_n[12:5];
    // D#: B -> A through the transceiver register (CLKBA = BCLK)
    logic [63:0] d_bus_q;
    always_ff @(posedge bclk) d_bus_q <= d_n;
    wire [63:0] d_agent = data_dir ? ~d_cpu : d_bus_q;
    localparam bit D_CLOCKED = 1;
    logic       addr_dir_q, addr_oeab_q, data_dir_q, data_oeab_q, addr_drove, data_drove, gtl_err;
    always_ff @(posedge bclk) begin
        {addr_dir_q, addr_oeab_q, data_dir_q, data_oeab_q} <= {addr_dir, addr_oeab, data_dir, data_oeab};
        addr_drove <= |a_cpu || |req_cpu;
        data_drove <= |d_cpu;
        if (rst) gtl_err <= 0;
        else if ((|a_cpu || |req_cpu || addr_drove) && !addr_oeab || (|d_cpu || data_drove) && !data_oeab ||
                 addr_oeab && !(addr_dir && addr_dir_q) || addr_dir_q && !addr_dir && addr_oeab_q ||
                 data_oeab && !(data_dir && data_dir_q) || data_dir_q && !data_dir && data_oeab_q)
            gtl_err <= 1;
    end
`else
    wire [35:3] a_n   = ~(a_cpu | a_cs);
    wire [4:0]  req_n = ~(req_cpu | req_cs);
    wire [63:0] d_n   = ~(d_cpu | d_cs);
    wire [12:5] a_agent = a_n[12:5];
    wire [63:0] d_agent = d_n;
    wire        gtl_err = 0;
    localparam bit D_CLOCKED = 0;
`endif
    assign p6_err[9] = gtl_err;
    wire        ads_n = ~(ads_cpu | ads_cs), drdy_n = ~(drdy_cpu | drdy_cs);
    c2_p6_agent #(.D_CLOCKED(D_CLOCKED)) agent (
        .clk(bclk), .clk_in(bclk), .rst, .bus_req(s_req), .bus_space, .bus_write, .bus_inta, .bus_special, .bus_addr, .bus_size,
        .bus_wdata,
        .bus_done(s_done), .bus_rdata(s_rdata), .bus_err(s_err),
        .reset_n(!reset_cs), .a_n(a_agent), .ads_n, .bnr_n(!bnr_cs), .bpri_n(!bpri_cs), .trdy_n(!trdy_cs),
        .dbsy_n(!dbsy_cs), .drdy_n, .rs_n(~rs_cs), .d_n(d_agent),
        .a_drv(a_cpu), .req_drv(req_cpu), .ads_drv(ads_cpu), .br0_drv(br0_cpu), .drdy_drv(drdy_cpu),
        .d_drv(d_cpu), .addr_dir, .addr_oeab, .data_dir, .data_oeab, .cpu_reset, .straps
    );
    // board bus decode: every memory address is PCI (no DRAM model), every
    // I/O port goes to the host port
    p6_bif #(.RESET_CLKS(24)) chipset (
        .clk(bclk), .rst_n(!rst && !board_rst), .a_n, .req_n, .ads_n, .d_n, .drdy_n,
        .dbsy_n(!dbsy_cs), .hit_n(!hit_cs), .hitm_n(!hitm_cs), .bnr_n(!bnr_cs), .lock_n(1'b1),
        .binit_n(!binit_cs),
        .a_drv(a_cs), .req_drv(req_cs), .ads_drv(ads_cs), .d_drv(d_cs), .rs_drv(rs_cs), .trdy_drv(trdy_cs),
        .drdy_drv(drdy_cs), .dbsy_drv(dbsy_cs), .hit_drv(hit_cs), .hitm_drv(hitm_cs), .bnr_drv(bnr_cs),
        .bpri_drv(bpri_cs), .br0_drv(br0_cs), .reset_drv(reset_cs), .defer_drv(defer_cs), .binit_drv(binit_cs),
        .mem_addr(), .mem_we(), .mem_sel_dram(1'b0), .mem_sel_pci(1'b1),
        .io_stb(), .io_we(), .io_addr(), .io_size(), .io_wdata(), .io_rdata(32'd0), .io_hit(1'b0),
        .host_req, .host_we, .host_addr, .host_wdata, .host_be, .host_dram(), .host_io, .host_attr(), .host_dc(),
        .host_lock(), .host_smmem(), .host_ready, .host_rdata, .host_rvalid, .host_err(1'b0),
        .spc_stb, .spc_type, .inta_stb(), .inta_vector,
        .snoop_stall(1'b0), .dma_req(1'b0), .dma_gnt(), .snp_line('0), .snp_inv(1'b0), .snp_ok(),
        .cpu_ready(p6_cpu_ready), .err(p6_err[8:0])
    );
`else
    c2_cart cart (
        .clk(cclk), .rst, .down(down_cart), .up(up_cart), .bus_req, .bus_space, .bus_write, .bus_inta, .bus_special,
        .bus_addr, .bus_size, .bus_wdata, .bus_done, .bus_rdata, .bus_err, .intr,
        .board_reset(board_rst), .low_vector(1'b0), .a20m(cpu_pins[0]), .stpclk(cpu_pins[1]), .nmi(cpu_pins[2]),
        .init(cpu_pins[3]), .smi(cpu_pins[4]), .link_lost(quiet_s[1]), .link_flushed()
    );
    assign serial_valid = 0;
    assign serial_byte  = '0;
`endif

    // up bytes on the cartridge clock (as the card receives them with the
    // returned clock) into the link clock
    logic up_overflow_w, up_valid_n;
    logic [1:0] up_overflow_s;
    c2_afifo #(.W(8), .AW(3)) up_fifo (
        .wclk(cclk), .wrst(rst), .we(1'b1), .wd(inject_up_valid ? inject_up_byte : up_pipe[LINK_DELAY - 1]),
        .overflow(up_overflow_w),
        .rclk(lclk), .rrst(rst), .re(1'b1), .rd(up_card), .empty(up_valid_n)
    );
    assign up_valid = !up_valid_n;
    always_ff @(posedge lclk) up_overflow_s <= rst ? '0 : {up_overflow_s[0], up_overflow_w};
    assign up_overflow = up_overflow_s[1];
endmodule
