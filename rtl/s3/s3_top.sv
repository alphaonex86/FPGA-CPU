// socket3-cyclonev board top (hw/socket3-cyclonev, 5CEFA9F23C8): x86_core behind the Socket 3 bus
// unit, one port per pins.csv signal (board.py: A20M# -> a20m_n, M/IO# -> m_io_n, D7 -> d[7]).
// Everything runs on the socket's CLK through a PLL in normal mode (the clock at the I/O registers
// = the clock at the pin; the raw pin -> clock tree path would break input hold). The CPU stays in
// reset while RESET is high, the PLL is unlocked or VCORE_OK is low (the bus switches are open
// then: BUS_OE# of the same detector, plan/interposers.md FPGAmotherboard compatibility).
// Inputs the core has no use for yet (plan/x86_core.md M5): INTR, NMI, SMI#, IGNNE#, FLUSH#,
// SRESET, INV, WB/WT#, UP#, CLKMUL, the CPU JTAG pins.
module s3_top #(
    parameter string FREQ  = "33.333333 MHz",
    parameter string PHASE = "0 ps"
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
    logic         clk_p, locked, rst;
    logic [1:0]   reset_s, ok_s, lock_s;
    logic         mem_req, mem_we, mem_ready, mem_rvalid;
    logic [31:5]  mem_addr;
    logic [255:0] mem_wdata, mem_rdata;
    logic [31:2]  a_o;
    logic [31:0]  d_o;
    logic [3:0]   dp_o, be_o;
    logic         a_oe, ctl_oe, d_oe, ads_o, mio, dc, wr, blast_o, lock_o, cache_o;

    c2_bclk_pll #(.FREQ(FREQ), .PHASE(PHASE)) pll (.refclk(clk), .rst(1'b0), .clk(clk_p), .clk_in(), .locked(locked));

    always_ff @(posedge clk_p) begin
        reset_s <= {reset_s[0], reset};
        ok_s    <= {ok_s[0], vcore_ok};
        lock_s  <= {lock_s[0], locked};
        rst     <= reset_s[1] || !ok_s[1] || !lock_s[1];
    end

    x86_core core (.clk(clk_p), .rst(rst), .reset_eip(32'hffff_fff0),
                   .mem_req(mem_req), .mem_we(mem_we), .mem_addr(mem_addr), .mem_wdata(mem_wdata),
                   .mem_ready(mem_ready), .mem_rvalid(mem_rvalid), .mem_rdata(mem_rdata),
                   .ret_valid(), .ret_eop(), .ret_next_eip(), .ret_wdst(), .ret_dst(), .ret_value(),
                   .ret_wflags(), .ret_flags(), .halted(), .illegal());

    s3_bus bus (.clk(clk_p), .rst(rst),
                .mem_req(mem_req), .mem_we(mem_we), .mem_addr(mem_addr), .mem_wdata(mem_wdata),
                .mem_ready(mem_ready), .mem_rvalid(mem_rvalid), .mem_rdata(mem_rdata), .mem_cacheable(),
                .sc_req(1'b0), .sc_status(3'd0), .sc_lock(1'b0), .sc_addr(30'd0), .sc_be(4'd0), .sc_wdata(32'd0),
                .sc_ready(), .sc_done(), .sc_rdata(),
                .quiet(1'b1), .stopped(), .snoop(), .snoop_addr(), .err_bs(),
                .a_o(a_o), .a_oe(a_oe), .a_i(a[31:4]), .be_n(be_o), .ads_n(ads_o), .mio(mio), .dc(dc), .wr(wr),
                .blast_n(blast_o), .lock_n(lock_o), .cache_n(cache_o), .ctl_oe(ctl_oe),
                .d_o(d_o), .dp_o(dp_o), .d_oe(d_oe), .d_i(d), .dp_i(dp), .pchk_n(pchk_n),
                .hlda(hlda), .breq(breq), .rdy_n(rdy_n), .brdy_n(brdy_n), .ken_n(ken_n), .hold(hold),
                .ahold(ahold), .boff_n(boff_n), .eads_n(eads_n), .a20m_n(a20m_n), .stpclk_n(stpclk_n),
                .bs8_n(bs8_n), .bs16_n(bs16_n));

    assign a       = a_oe ? a_o : 'z;
    assign d       = d_oe ? d_o : 'z;
    assign dp      = d_oe ? dp_o : 'z;
    // floated with the bus under HLDA and BOFF#
    assign be_n    = ctl_oe ? be_o : 'z;
    assign ads_n   = ctl_oe ? ads_o : 1'bz;
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
