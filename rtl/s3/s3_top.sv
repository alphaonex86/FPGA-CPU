// socket3-cyclonev board top (hw/socket3-cyclonev, 5CEFA9F23C8): x86_core behind the Socket 3 bus
// unit, one port per pins.csv signal (board.py: A20M# -> a20m_n, M/IO# -> m_io_n, D7 -> d[7]).
// Everything runs on the socket's CLK through a PLL in normal mode (the clock at the I/O registers
// = the clock at the pin; the raw pin -> clock tree path would break input hold); PHASE moves it
// against the pin clock (later: more input setup, later outputs; 790 ps, 8 VCO / 8 steps, splits the margin of the
// RDY# / BRDY# -> BLAST# loop evenly on the 5CEFA9F23C8: full build 2026-11-12 at 987 ps, BLAST# out -0.139 ns, RDY# in +0.752). VCO fixes the PLL at 38 x CLK, so it
// locks from 15.8 to 34.2 MHz (VCO 600-1300 MHz): the 25 / 33 MHz jumpers and the FPGAmotherboard's
// Stop Grant steps 16.67-33.33 MHz. The core's clock stops while the PLL is unlocked (CLK stopped
// or changed in Stop Grant): it keeps its state. The bus unit (idle then) stays on the PLL clock
// itself: a gate in front of its I/O registers costs the RDY# / BRDY# loop ~0.4 ns. The CPU stays in reset while RESET is high or
// VCORE_OK is low (the bus switches are open then: BUS_OE# of the same detector, plan/interposers.md
// FPGAmotherboard compatibility).
// FLUSH#: the core writes its caches back and invalidates them (standard mode: no special cycle).
// Inputs the core has no use for yet (plan/x86_core.md M5): INTR, NMI, SMI#, IGNNE#,
// SRESET, UP#, CLKMUL, the CPU JTAG pins. snoop_err (a snoop on a dirty line in standard mode) has
// no pin: internal until the JTAG readout.
module s3_top #(
    parameter string FREQ  = "33.333333 MHz",
    parameter string PHASE = "790 ps",   // > 0: s3_top.sdc takes the inputs at the next edge
    parameter string VCO   = "422.222222 MHz"   // 38 / 3 x FREQ
) (
    input  wire        clk,
    input  wire        reset,
    input  wire        sreset,
    inout  wire [31:2] a,
    inout  wire [31:0] d,
    inout  wire [3:0]  dp,
    output wire [3:0]  be_n,
    output wire        ads_n,
    output wire        m_io_n,
    output wire        d_c_n,
    output wire        w_r_n,
    output wire        blast_n,
    output wire        lock_n,
    output wire        plock_n,
    output wire        pcd,
    output wire        pwt,
    output wire        cache_n,
    output wire        hlda,
    output wire        breq,
    output wire        pchk_n,
    output wire        ferr_n,
    output wire        hitm_n,
    output wire        smiact_n,
    output wire        tdo,
    input  wire        rdy_n,
    input  wire        brdy_n,
    input  wire        ken_n,
    input  wire        hold,
    input  wire        ahold,
    input  wire        boff_n,
    input  wire        eads_n,
    input  wire        inv,
    input  wire        wb_wt_n,
    input  wire        bs8_n,
    input  wire        bs16_n,
    input  wire        intr,
    input  wire        nmi,
    input  wire        smi_n,
    input  wire        a20m_n,
    input  wire        ignne_n,
    input  wire        flush_n,
    input  wire        stpclk_n,
    input  wire        up_n,
    input  wire        clkmul,
    input  wire        tck,
    input  wire        tdi,
    input  wire        tms,
    input  wire        vcore_ok
);
    logic         clk_pll, clk_p, locked, pll_rst;
    logic         rst = 1'b1;
    logic [1:0]   reset_s = 2'b11, ok_s = 2'b00, a20m_s = 2'b11, flush_s = 2'b11, locked_r;
    logic [15:0]  relock;
    logic         mem_req, mem_we, mem_ready, mem_rvalid;
    logic [31:5]  mem_addr;
    logic [255:0] mem_wdata, mem_rdata;
    logic         sc_req, sc_ready, sc_done, mem_cacheable;
    logic [2:0]   sc_status;
    logic [31:2]  sc_addr;
    logic [3:0]   sc_be;
    logic [31:0]  sc_wdata, sc_rdata;
    logic [31:2]  a_o;
    logic [31:0]  d_o;
    logic [3:0]   dp_o, be_o;
    logic         a_oe, ctl_oe, d_oe, ads_o, mio, dc, wr, blast_o, lock_o, cache_o;
    logic         snoop, snoop_inv, enhanced, flush_done;
    logic [31:4]  snoop_line;

    c2_bclk_pll #(.FREQ(FREQ), .PHASE(PHASE), .VCO(VCO)) pll (.refclk(clk), .rst(pll_rst), .clk(clk_pll), .clk_in(),
                                                       .locked(locked));
    c2_clk_gate gate (.clk(clk_pll), .ena(locked), .gclk(clk_p));

    // on the pin clock itself: no lock for 2^16 clocks (the socket clock stopped in Stop Grant, or
    // its frequency changed) -> the PLL is reset for 16 clocks and locks again
    always_ff @(posedge clk) begin
        locked_r <= {locked_r[0], locked};
        relock   <= locked_r[1] ? 16'd0 : relock + 16'd1;
        pll_rst  <= !locked_r[1] && relock[15:4] == '1;
    end

    always_ff @(posedge clk_p) begin
        reset_s <= {reset_s[0], reset};
        ok_s    <= {ok_s[0], vcore_ok};
        a20m_s  <= {a20m_s[0], a20m_n};
        flush_s <= {flush_s[0], flush_n};
        rst     <= reset_s[1] || !ok_s[1];
    end

    x86_core core (.clk(clk_p), .rst(rst), .reset_eip(32'hffff_fff0), .a20m(!a20m_s[1]), .cache_flush(!flush_s[1]),
                   .snoop(snoop), .snoop_line(snoop_line), .snoop_inv(snoop_inv), .enhanced(enhanced), .snoop_err(),
                   .flush_done(flush_done),
                   .mem_req(mem_req), .mem_we(mem_we), .mem_addr(mem_addr), .mem_wdata(mem_wdata),
                   .mem_ready(mem_ready), .mem_rvalid(mem_rvalid), .mem_rdata(mem_rdata),
                   .mem_cacheable(mem_cacheable), .sc_req(sc_req), .sc_status(sc_status), .sc_addr(sc_addr), .sc_be(sc_be), .sc_wdata(sc_wdata),
                   .sc_ready(sc_ready), .sc_done(sc_done), .sc_rdata(sc_rdata),
                   .ret_valid(), .ret_eop(), .ret_next_eip(), .ret_wdst(), .ret_dst(), .ret_value(),
                   .ret_wflags(), .ret_flags(), .halted(), .illegal());

    s3_bus bus (.clk(clk_pll), .rst(rst),
                .mem_req(mem_req), .mem_we(mem_we), .mem_addr(mem_addr), .mem_wdata(mem_wdata),
                .mem_ready(mem_ready), .mem_rvalid(mem_rvalid), .mem_rdata(mem_rdata), .mem_cacheable(mem_cacheable),
                .sc_req(sc_req), .sc_status(sc_status), .sc_lock(1'b0), .sc_addr(sc_addr), .sc_be(sc_be),
                .sc_wdata(sc_wdata), .sc_ready(sc_ready), .sc_done(sc_done), .sc_rdata(sc_rdata),
                .quiet(1'b1), .stopped(), .snoop(snoop), .snoop_addr(snoop_line), .snoop_inv(snoop_inv),
                .enhanced(enhanced), .flush_done(flush_done),
                .a_o(a_o), .a_oe(a_oe), .a_i(a[31:4]), .be_n(be_o), .ads_n(ads_o), .mio(mio), .dc(dc), .wr(wr),
                .blast_n(blast_o), .lock_n(lock_o), .cache_n(cache_o), .ctl_oe(ctl_oe),
                .d_o(d_o), .dp_o(dp_o), .d_oe(d_oe), .d_i(d), .dp_i(dp), .pchk_n(pchk_n),
                .hlda(hlda), .breq(breq), .rdy_n(rdy_n), .brdy_n(brdy_n), .ken_n(ken_n), .hold(hold),
                .ahold(ahold), .boff_n(boff_n), .eads_n(eads_n), .inv(inv), .wb_wt_n(wb_wt_n), .stpclk_n(stpclk_n),
                .bs8_n(bs8_n), .bs16_n(bs16_n));

    assign a       = a_oe ? a_o : 'z;
    assign d       = d_oe ? d_o : 'z;
    assign dp      = d_oe ? dp_o : 'z;
    // floated with the bus under HLDA and BOFF#
    assign be_n    = ctl_oe ? be_o : 'z;
    assign ads_n   = a_oe ? ads_o : 1'bz;             // with the address (s3_bus.sv)
    assign m_io_n  = ctl_oe ? mio : 1'bz;
    assign d_c_n   = ctl_oe ? dc : 1'bz;
    assign w_r_n   = ctl_oe ? wr : 1'bz;
    assign blast_n = ctl_oe ? blast_o : 1'bz;
    assign lock_n  = ctl_oe ? lock_o : 1'bz;
    assign cache_n = ctl_oe ? cache_o : 1'bz;
    assign plock_n = ctl_oe ? 1'b1 : 1'bz;
    assign pcd     = ctl_oe ? 1'b0 : 1'bz;
    assign pwt     = ctl_oe ? 1'b0 : 1'bz;
    assign ferr_n   = 1'b1;
    assign hitm_n   = 1'b1;
    assign smiact_n = 1'b1;
    assign tdo      = 1'bz;
endmodule
