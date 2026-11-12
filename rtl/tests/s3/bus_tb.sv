// s3_bus unit test (rtl/tools/s3_bus_test.sh): random line reads / writes and single cycles against a
// 486 bus slave written from the datasheet rules, with what cpu486_bif never does: RDY# instead of
// BRDY#, wait states, BOFF#, HOLD, AHOLD + EADS#, STPCLK#. Checks: the data both ways (a shadow
// memory), one ADS# clock per cycle, burst order and BLAST#, a floated bus after BOFF# / under HLDA,
// no bus cycle while backed off, held or in Stop Grant, the Stop Grant cycle itself, parity.
// Bus sizing: each 4 KB page is 8, 16 or 32 bits wide (BS8# / BS16# from the address); a narrow
// transfer drives junk on the lanes it does not serve, writes only those, and the next cycle must
// carry exactly the remaining BE# at the same address; a narrow burst must end at its next transfer.
// Undisturbed (every rate 0), every line read must be two full bursts. +seed=<n> +ops=<n>; +rdy=<percent of transfers ended by RDY#> +boff= +hold= +ahold= +stp= (per mille
// of clocks); +bs=<percent of narrow pages>.
module bus_tb (
    input  logic clk,
    output logic done,
    output logic failed
);
    localparam int WORDS = 1 << 14;                 // 64 KB of dwords
    logic [31:0] mem [WORDS], shadow [WORDS];
    logic        rst;
    int          seed, ops, p_rdy, p_boff, p_hold, p_ahold, p_stp, p_bs;
    int          n_ops, n_reads, n_burst, n_single, n_boff, n_hold, n_grant, n_snoop, n_narrow, cycle, stp_gap;
    logic [1:0]  width [16];                        // per 4 KB page: 0 32-bit, 1 16-bit, 2 8-bit

    // DUT ports
    logic         mem_req, mem_we, mem_ready, mem_rvalid, mem_cacheable;
    logic [31:5]  mem_addr;
    logic [255:0] mem_wdata, mem_rdata;
    logic         sc_req, sc_ready, sc_done, sc_lock;
    logic [2:0]   sc_status;
    logic [31:2]  sc_addr, a_o;
    logic [3:0]   sc_be, be_n, dp_o;
    logic [31:0]  sc_wdata, sc_rdata, d_o, d_pin;
    logic         stopped, snoop, a_oe, ads_n, mio, dc, wr, blast_n, lock_n, cache_n, ctl_oe, d_oe;
    logic [31:4]  snoop_addr;
    logic         pchk_n, hlda, breq, ads_r;
    assign ads_n = a_oe ? ads_r : 1'b1;           // the pad: floated with the address, pulled up on the board
    logic         rdy_n, brdy_n, ken_n, hold, ahold, boff_n, eads_n, stpclk_n, bs8_n, bs16_n;

    // slave
    typedef enum logic [1:0] {S_IDLE, S_WAIT} sstate_t;
    sstate_t      ss;
    logic [31:2]  s_a;
    logic [2:0]   s_status;
    logic [3:0]   s_be;
    logic [1:0]   s_beat;
    int           s_wait;
    logic         s_drive, bad_parity, float_due;
    logic [31:0]  s_data, s_junk, s_mask;
    logic [31:2]  beat_addr, cur_a;
    logic [1:0]   cur_w;
    logic         s_drop;                          // a narrow burst went on: this transfer only ends it
    logic [3:0]   s_served, s_left, exp_be;
    logic         exp_valid;
    logic [31:2]  exp_a;

    function automatic logic [3:0] lanes(input logic [3:0] be, input logic [1:0] w);
        logic [3:0] low;
        low = be & (~be + 4'd1);
        return w == 2'd2 ? low : w == 2'd1 && be[1:0] != 2'd0 ? be & 4'b0011 : be;
    endfunction

    assign cur_a     = ss == S_IDLE ? a_o : s_a;
    assign cur_w     = width[cur_a[15:12]];
    assign bs8_n     = !((ss != S_IDLE || !ads_n) && cur_w == 2'd2);
    assign bs16_n    = !((ss != S_IDLE || !ads_n) && cur_w == 2'd1);
    assign s_served  = s_drop ? 4'd0 : lanes(s_be, cur_w);
    assign beat_addr = {s_a[31:4], s_a[3:2] ^ s_beat};
    for (genvar b = 0; b < 4; b++) begin : g_mask
        assign s_mask[8*b +: 8] = {8{s_served[b]}};
    end
    assign s_data    = mem[beat_addr[15:2]] & s_mask | s_junk & ~s_mask;
    assign d_pin     = d_oe ? d_o : s_drive ? s_data : 32'hzzzz_zzzz;

    s3_bus dut (.clk(clk), .rst(rst),
                .mem_req(mem_req), .mem_we(mem_we), .mem_addr(mem_addr), .mem_wdata(mem_wdata),
                .mem_ready(mem_ready), .mem_rvalid(mem_rvalid), .mem_rdata(mem_rdata), .mem_cacheable(mem_cacheable),
                .sc_req(sc_req), .sc_status(sc_status), .sc_lock(sc_lock), .sc_addr(sc_addr), .sc_be(sc_be),
                .sc_wdata(sc_wdata), .sc_ready(sc_ready), .sc_done(sc_done), .sc_rdata(sc_rdata),
                .quiet(1'b1), .stopped(stopped), .snoop(snoop), .snoop_addr(snoop_addr),
                .a_o(a_o), .a_oe(a_oe), .a_i(28'h123_4567), .be_n(be_n), .ads_n(ads_r), .mio(mio), .dc(dc), .wr(wr),
                .blast_n(blast_n), .lock_n(lock_n), .cache_n(cache_n), .ctl_oe(ctl_oe),
                .d_o(d_o), .dp_o(dp_o), .d_oe(d_oe), .d_i(d_pin),
                .dp_i({^d_pin[31:24], ^d_pin[23:16], ^d_pin[15:8], ^d_pin[7:0]} ^ {3'd0, bad_parity}),
                .pchk_n(pchk_n), .hlda(hlda), .breq(breq), .rdy_n(rdy_n), .brdy_n(brdy_n), .ken_n(ken_n),
                .hold(hold), .ahold(ahold), .boff_n(boff_n), .eads_n(eads_n), .stpclk_n(stpclk_n),
                .bs8_n(bs8_n), .bs16_n(bs16_n));

    task automatic fail(input string what);
        $display("FAIL cycle %0d: %s", cycle, what);
        failed <= 1'b1;
        done   <= 1'b1;
    endtask

    function automatic int roll(input int per_mille);
        return int'($urandom_range(999)) < per_mille ? 1 : 0;
    endfunction

    task automatic answer(input logic write);     // the transfer's ready, sampled at the next edge
        if (int'($urandom_range(99)) < p_rdy) rdy_n <= 1'b0;
        else brdy_n <= 1'b0;
        s_drive <= !write;
        s_junk <= $urandom;
        bad_parity <= roll(20) != 0;
    endtask

    // stimulus: one operation at a time
    typedef enum logic [1:0] {O_IDLE, O_READ, O_WRITE, O_SINGLE} op_t;
    op_t          op;
    logic [31:5]  op_line;
    logic [31:2]  op_addr;
    logic         op_we, pending;
    logic [3:0]   op_be;
    logic [31:0]  expect_single;
    logic         bad_q, bad_qq;

    initial begin
        if (!$value$plusargs("seed=%d", seed)) seed = 1;
        if (!$value$plusargs("ops=%d", ops)) ops = 20000;
        if (!$value$plusargs("rdy=%d", p_rdy)) p_rdy = 30;
        if (!$value$plusargs("boff=%d", p_boff)) p_boff = 20;
        if (!$value$plusargs("hold=%d", p_hold)) p_hold = 20;
        if (!$value$plusargs("ahold=%d", p_ahold)) p_ahold = 20;
        if (!$value$plusargs("stp=%d", p_stp)) p_stp = 5;
        if (!$value$plusargs("bs=%d", p_bs)) p_bs = 20;
        void'($urandom(seed));
        for (int i = 0; i < 16; i++)
            width[i] = int'($urandom_range(99)) < p_bs ? 2'($urandom_range(2, 1)) : 2'd0;
        for (int i = 0; i < WORDS; i++) begin
            mem[i] = $urandom;
            shadow[i] = mem[i];
        end
    end

    always_ff @(posedge clk) begin
        cycle <= cycle + 1;
        rst   <= cycle < 4;
        if (cycle < 4) begin
            ss <= S_IDLE;
            {mem_req, sc_req, sc_lock, pending, s_drive, hold, ahold, bad_parity} <= '0;
            {rdy_n, brdy_n, ken_n, boff_n, eads_n, stpclk_n} <= '1;
            op <= O_IDLE;
            {done, failed, float_due, bad_q, bad_qq} <= '0;
            {n_ops, n_reads, n_burst, n_single, n_boff, n_hold, n_grant, n_snoop, n_narrow} <= '0;
            {s_drop, exp_valid} <= '0;
        end else if (!done) begin
            // ---- stimulus
            if (mem_req && mem_ready) mem_req <= 1'b0;
            if (sc_req && sc_ready) sc_req <= 1'b0;
            if (op == O_IDLE && !pending && n_ops < ops) begin
                int kind;
                kind = int'($urandom_range(9));
                pending <= 1'b1;
                if (kind < 5) begin
                    op <= O_READ;
                    mem_req <= 1'b1;
                    mem_we <= 1'b0;
                    mem_addr <= 27'($urandom_range(WORDS / 8 - 1));
                    op_line <= 27'(0);
                end else if (kind < 8) begin
                    logic [255:0] w;
                    logic [31:5]  l;
                    l = 27'($urandom_range(WORDS / 8 - 1));
                    for (int i = 0; i < 8; i++) begin
                        w[32*i +: 32] = $urandom;
                        shadow[{l[15:5], 3'(i)}] <= w[32*i +: 32];
                    end
                    op <= O_WRITE;
                    mem_req <= 1'b1;
                    mem_we <= 1'b1;
                    mem_addr <= l;
                    mem_wdata <= w;
                end else begin
                    logic [31:2] sa;
                    logic [3:0]  sb;
                    logic [31:0] sw;
                    sa = 30'($urandom_range(WORDS - 1));
                    sb = 4'($urandom_range(15, 1));
                    sw = $urandom;
                    op <= O_SINGLE;
                    sc_req <= 1'b1;
                    sc_lock <= roll(300) != 0;
                    op_we <= kind == 9;
                    sc_status <= {2'b11, kind == 9};
                    sc_addr <= sa;
                    sc_be <= sb;
                    sc_wdata <= sw;
                    if (kind == 9)
                        for (int b = 0; b < 4; b++)
                            if (sb[b]) shadow[sa[15:2]][8*b +: 8] <= sw[8*b +: 8];
                    op_addr <= sa;
                    op_be <= sb;
                end
            end
            if (mem_req && mem_ready) op_line <= mem_addr;
            if (mem_rvalid) begin
                if (op != O_READ) fail("mem_rvalid without a read");
                n_reads <= n_reads + 1;
                for (int i = 0; i < 8; i++)
                    if (mem_rdata[32*i +: 32] != shadow[{op_line[15:5], 3'(i)}]) fail("line read data");
                op <= O_IDLE;
                pending <= 1'b0;
                n_ops <= n_ops + 1;
            end
            if (op == O_WRITE && !mem_req && dut.job == 2'd0 && pending) begin      // the bus unit finished the line
                op <= O_IDLE;
                pending <= 1'b0;
                n_ops <= n_ops + 1;
            end
            if (sc_done) begin
                if (op != O_SINGLE) fail("sc_done without a single cycle");
                if (!op_we)
                    for (int b = 0; b < 4; b++)
                        if (op_be[b] && sc_rdata[8*b +: 8] != shadow[op_addr[15:2]][8*b +: 8]) fail("single read data");
                op <= O_IDLE;
                pending <= 1'b0;
                sc_lock <= 1'b0;
                n_ops <= n_ops + 1;
            end
            if (n_ops == ops && op == O_IDLE && dut.job == 2'd0) begin
                for (int i = 0; i < WORDS; i++)
                    if (mem[i] != shadow[i]) begin
                        $display("FAIL: memory[%0d] %08x, expected %08x", i, mem[i], shadow[i]);
                        failed <= 1'b1;
                    end
                if ((p_rdy != 100 && n_burst == 0) || (p_rdy != 0 && n_single == 0) || (p_boff != 0 && n_boff == 0) || (p_hold != 0 && n_hold == 0)
                    || (p_stp != 0 && n_grant == 0) || (p_ahold != 0 && n_snoop == 0) || (p_bs != 0 && n_narrow == 0))
                    fail("a path was never exercised");
                // undisturbed: every line read is two bursts of four (three continued transfers each)
                if (p_rdy + p_boff + p_hold + p_ahold + p_stp + p_bs == 0 && n_burst != 6 * n_reads) fail("a burst was cut short");
                $display("%0d operations in %0d clocks: %0d burst transfers, %0d cycles ended by RDY#, %0d back-offs, %0d holds, %0d Stop Grants, %0d snoops, %0d narrow transfers",
                         n_ops, cycle, n_burst, n_single, n_boff, n_hold, n_grant, n_snoop, n_narrow);
                done <= 1'b1;
            end

            // ---- bus masters / chipset side effects
            boff_n <= !(roll(p_boff) != 0);
            if (!boff_n) n_boff <= n_boff + 1;
            if (!hold && roll(p_hold) != 0) hold <= 1'b1;
            else if (hold && hlda && roll(300) != 0) begin
                hold <= 1'b0;
                n_hold <= n_hold + 1;
            end
            ahold  <= ahold ? roll(700) != 0 : roll(p_ahold) != 0;
            eads_n <= !(ahold && !a_oe);
            if (snoop) begin
                n_snoop <= n_snoop + 1;
                if (snoop_addr != 28'h123_4567) fail("snoop address");
            end
            stp_gap <= stpclk_n ? stp_gap + 1 : 0;            // high >= 8 clocks between assertions [19751C]
            if (stpclk_n && stp_gap >= 8 && roll(p_stp) != 0) stpclk_n <= 1'b0;
            else if (!stpclk_n && stopped && roll(200) != 0) stpclk_n <= 1'b1;

            // ---- protocol checks
            float_due <= !boff_n;
            if (float_due && (a_oe || ctl_oe || d_oe)) fail("bus driven in the clock after BOFF#");
            if (hlda && (a_oe || ctl_oe || d_oe)) fail("bus driven under HLDA");
            if (ahold && $past(ahold) && a_oe) fail("address driven under AHOLD");
            if (hlda && !lock_n) fail("HLDA under LOCK#");
            if (!ads_n && (!ctl_oe || !a_oe)) fail("ADS# with a floated bus");
            if (!ads_n && $past(!ads_n)) fail("ADS# for two clocks");
            if (!ads_n && stopped) fail("a cycle in Stop Grant");
            if (d_oe && s_drive) fail("both ends drive the data bus");
            bad_q  <= s_drive && bad_parity && s_served[0] && (!rdy_n || !brdy_n) && boff_n;
            bad_qq <= bad_q;
            if (!pchk_n != bad_qq) fail("PCHK#");

            // ---- the slave
            rdy_n   <= 1'b1;
            brdy_n  <= 1'b1;
            s_drive <= 1'b0;
            ken_n   <= !(roll(800) != 0);
            if (!boff_n) begin                                  // the cycle is void, it comes again
                ss <= S_IDLE;
                s_drop <= 1'b0;
                if (ss != S_IDLE && s_left != 4'd0) begin       // with the bytes a narrow transfer left
                    exp_valid <= 1'b1;
                    exp_a <= s_a;
                    exp_be <= s_left;
                end
            end else unique case (ss)
                S_IDLE: if (!ads_n) begin
                    if (exp_valid && (a_o != exp_a || ~be_n != exp_be)) fail("the cycle after a narrow transfer");
                    exp_valid <= 1'b0;
                    s_left <= 4'd0;
                    s_a <= a_o;
                    s_status <= {mio, dc, wr};
                    s_be <= ~be_n;
                    s_beat <= 2'd0;
                    s_wait <= int'($urandom_range(3));
                    ss <= S_WAIT;
                    if (roll(300) != 0) begin                   // no wait state: ready in the first T2
                        s_wait <= 0;
                        answer(wr);
                    end
                    if (sc_lock && op == O_SINGLE && {mio, dc, wr} != 3'b001 && lock_n) fail("LOCK# high in a locked cycle");
                    if ({mio, dc, wr} == 3'b001) begin
                        n_grant <= n_grant + 1;
                        if (a_o != 30'd4 || be_n != 4'b1011) fail("Stop Grant address / BE#");
                        if (stpclk_n) fail("Stop Grant without STPCLK#");
                    end
                end
                default: begin
                    if (!ads_n) fail("ADS# inside a cycle");
                    if (a_oe && a_o[31:4] != s_a[31:4]) fail("address changed inside a cycle");
                    if ((!rdy_n || !brdy_n)) begin              // the transfer the CPU samples now
                        logic [3:0] left;
                        left = s_be & ~s_served;
                        if (s_status[0]) begin
                            if (!d_oe) fail("write data not driven");
                            if (dp_o != {^d_o[31:24], ^d_o[23:16], ^d_o[15:8], ^d_o[7:0]}) fail("write parity");
                            if (s_status == 3'b111)
                                for (int b = 0; b < 4; b++)
                                    if (s_served[b]) mem[beat_addr[15:2]][8*b +: 8] <= d_o[8*b +: 8];
                        end
                        if (s_drop && blast_n) fail("a narrow burst not ended at its next transfer");
                        if (!s_drop && left != 4'd0) begin
                            s_left <= left;
                            n_narrow <= n_narrow + 1;
                        end
                        if (!rdy_n || !blast_n) begin
                            ss <= S_IDLE;
                            s_drop <= 1'b0;
                            if (!rdy_n && blast_n) n_single <= n_single + 1;
                            if (!s_drop && left != 4'd0 || s_drop && s_left != 4'd0) begin
                                exp_valid <= 1'b1;
                                exp_a <= s_a;
                                exp_be <= s_drop ? s_left : left;
                            end
                        end else begin
                            if (left != 4'd0) s_drop <= 1'b1;
                            if (s_status[0]) fail("burst write");
                            if (s_beat == 2'd3) fail("BLAST# high on the fourth transfer");
                            if (a_oe && a_o[3:2] != (s_a[3:2] ^ s_beat)) fail("burst address");
                            s_beat <= s_beat + 2'd1;
                            s_wait <= int'($urandom_range(2));
                            n_burst <= n_burst + 1;
                            if (roll(500) != 0) begin           // the next transfer in the next clock
                                s_wait <= 0;
                                answer(1'b0);
                            end
                        end
                    end else if (s_wait != 0) s_wait <= s_wait - 1;
                    else answer(s_status[0]);
                end
            endcase
        end
    end
endmodule
