// L1 data cache (plan/x86_core.md M3): 16 KB, 4-way, 32-byte lines,
// write-back, write-allocate, one miss in flight.
// - Data: two M10K banks, even and odd dwords of each line; a row is the
//   bank's half line (4 dwords) of one {set, way}. An access reads the
//   dword of its address and the next one, one from each bank, so any
//   access of up to 4 bytes reads in one cycle, across lines too.
// - Tags: per way, in MLAB read unregistered; copies for the load's even
//   and odd dword lines (A) and for the store drain. The hit way is known
//   in A and addresses the data banks at the A -> M edge.
// - Loads: a_hit in A (the core wakes dependents on it); a miss starts the
//   fill if the MSHR is free, the load replays.
// - Stores: the drained store queue head writes with byte enables and sets
//   the line dirty; a line-crossing store writes its two lines in two
//   steps; a miss starts the fill and holds the drain.
// - Miss: a dirty victim is read (the load port stolen for that cycle) and
//   written back, then the line is read and written with its tag.
// - Probe (an L1I miss): the line, if dirty, is written back the same way
//   and stays, clean.
// - Reset clears the tags, a set per clock (S_CLR), before the first lookup.
// - Flush (FLUSH#, WBINVD): fl_req held; every dirty line is written back
//   (S_SWP, a way per clock, the probe's write-back), then S_CLR; fl_done
//   until fl_req drops. No hit, miss or drain meanwhile.
// - A line that came without KEN# is not installed (the victim stays): the
//   access replays and goes uncached (x86_uc has learned its region).
module x86_l1d
    import x86_pkg::*;
(
    input  logic          clk,
    input  logic          rst,
    // A: load lookup, data in M (the cycle after)
    input  logic          a_valid,
    input  logic [31:0]   a_addr,
    input  logic [1:0]    a_size,
    output logic          a_hit,
    input  logic [31:0]   m_addr,      // the address looked up in A
    output logic [31:0]   m_data,      // its 4 bytes
    // store drain: the store queue head
    input  logic          d_valid,
    input  logic [31:0]   d_addr,
    input  logic [1:0]    d_size,
    input  logic [31:0]   d_data,
    output logic          d_done,      // written: the head leaves
    output logic          d_step,      // a drain step writes d_line this cycle
    output logic [31:5]   d_line,
    // probe: write pr_line back if dirty
    input  logic          pr_req,
    input  logic [31:5]   pr_line,
    output logic          pr_done,
    // memory, 32-byte lines
    output logic          mem_req,
    output logic          mem_we,
    output logic [31:5]   mem_addr,
    output logic [255:0]  mem_wdata,
    input  logic          mem_ready,   // takes the request this cycle
    input  logic          mem_rvalid,
    input  logic [255:0]  mem_rdata,
    input  logic          mem_rcacheable,
    // flush
    input  logic          fl_req,
    output logic          fl_done
);
    localparam int SETS = 128, WAYS = 4, SW = $clog2(SETS), TW = 32 - 5 - SW;

    typedef struct packed {
        logic          v, d;
        logic [TW-1:0] tag;
    } tg_t;

    // a dword address (byte address [31:2]) split for a bank
    function automatic logic [SW-1:0] set_of(input logic [29:0] dw);
        return dw[3 +: SW];
    endfunction
    function automatic logic [TW-1:0] tag_of(input logic [29:0] dw);
        return dw[29 -: TW];
    endfunction
    function automatic logic [3:0] bmask(input logic [1:0] sz);
        return sz == SZ8 ? 4'h1 : sz == SZ16 ? 4'h3 : 4'hF;
    endfunction

    // ---------------- tags: [copy][way], copy 0 even / 1 odd load line, 2 drain
    logic          t_we;
    logic [SW-1:0] t_set;
    logic [1:0]    t_way;
    tg_t           t_wd;
    logic [2:0][SW-1:0]       t_ra;
    tg_t  [2:0][WAYS-1:0]     t_rd;
    genvar gc, gw;
    generate for (gc = 0; gc < 3; gc = gc + 1) begin : tc
        for (gw = 0; gw < WAYS; gw = gw + 1) begin : tw
            x86_ram_async #(.W($bits(tg_t)), .N(SETS)) t (.clk(clk), .we(t_we && (st == S_CLR || t_way == 2'(gw))),
                                                          .wa(t_set), .wd(t_wd), .ra(t_ra[gc]),
                                                          .q(t_rd[gc][gw]));
        end
    end endgenerate

    // ---------------- data banks: [bank] rows {set, way}, 16 bytes
    logic [1:0][SW+1:0]           b_wa, b_ra;
    logic [1:0][15:0]             b_be;          // zero: no write (no separate enable: M10K inference)
    logic [1:0][127:0]            b_wd, b_rd;
    genvar gb;
    generate for (gb = 0; gb < 2; gb = gb + 1) begin : bk
        // a load reading the row the drain writes gets the old data (the
        // store, still queued, forwards or replays it)
        logic [15:0][7:0] mem [SETS * WAYS];
        always_ff @(posedge clk) begin
            for (int i = 0; i < 16; i++) if (b_be[gb][i]) mem[b_wa[gb]][i] <= b_wd[gb][8*i +: 8];
            b_rd[gb] <= mem[b_ra[gb]];
        end
    end endgenerate

    // ---------------- miss handling
    typedef enum logic [3:0] {S_IDLE, S_EVRD, S_EVDATA, S_WB, S_REQ, S_WAIT, S_FILL, S_CLR, S_SWP} st_t;
    st_t            st;
    logic [SW-1:0]  clr;           // S_CLR: the set cleared this clock
    logic [SW+1:0]  sw;            // S_SWP: {set, way} looked at this clock
    logic           sweeping, swept;
    tg_t            sw_tg;
    logic [31:5]    f_line;        // the line being filled
    logic [1:0]     f_way;
    logic [TW-1:0]  v_tag;         // its victim
    logic [255:0]   f_buf;         // victim data, then the fill data
    logic [1:0]     rr;            // replacement when no way is free
    logic           miss;          // a miss starts the MSHR this cycle
    logic           probing;       // a probe looks up its line this cycle
    logic           probe;         // the eviction is a probe's
    logic [31:5]    miss_line;
    tg_t  [WAYS-1:0] miss_ways;    // the set of the missing line

    function automatic logic [1:0] victim(input tg_t [WAYS-1:0] w, input logic [1:0] r);
        for (int i = WAYS - 1; i >= 0; i--) if (!w[i].v) return 2'(i);
        return r;
    endfunction

    // ---------------- A: load lookup
    logic [29:0]      a_dw;
    logic [1:0][29:0] a_bdw;       // dword of each bank
    logic [1:0]       a_need, a_bhit;
    logic [1:0][1:0]  a_bway;
    // addresses in their own block: the lookup below reads the tags they address
    always_comb begin
        logic [7:0] m8;
        a_dw = a_addr[31:2];
        a_bdw[0] = a_dw[0] ? a_dw + 30'd1 : a_dw;
        a_bdw[1] = a_dw[0] ? a_dw : a_dw + 30'd1;
        m8 = 8'(bmask(a_size)) << a_addr[1:0];
        a_need[0] = (a_dw[0] ? m8[7:4] : m8[3:0]) != 4'd0;
        a_need[1] = (a_dw[0] ? m8[3:0] : m8[7:4]) != 4'd0;
    end
    assign probing = st == S_IDLE && pr_req;
    assign t_ra = {st == S_SWP ? sw[2 +: SW] : probing ? pr_line[5 +: SW] : d_line[5 +: SW], set_of(a_bdw[1]), set_of(a_bdw[0])};
    assign sw_tg = t_rd[2][sw[1:0]];
    assign fl_done = swept;
    always_comb begin
        for (int b = 0; b < 2; b++) begin
            a_bhit[b] = 1'b0;
            a_bway[b] = 2'd0;
            for (int w = 0; w < WAYS; w++)
                if (t_rd[b][w].v && t_rd[b][w].tag == tag_of(a_bdw[b])) begin
                    a_bhit[b] = 1'b1;
                    a_bway[b] = 2'(w);
                end
        end
        // the load port is taken by a victim read in S_EVRD, the fill may
        // write the row the load reads in S_FILL
        a_hit = st != S_EVRD && st != S_FILL && st != S_CLR && !fl_req && (!a_need[0] || a_bhit[0]) && (!a_need[1] || a_bhit[1]);
    end

    // M: the 8-byte window from the address's dword, then its 4 bytes
    always_comb begin
        logic [29:0]      dw;
        logic [1:0][31:0] bd;
        logic [63:0]      win;
        logic [1:0]       j0;
        dw = m_addr[31:2];
        j0 = dw[0] ? dw[2:1] + 2'd1 : dw[2:1];
        bd[0] = b_rd[0][32 * j0 +: 32];
        bd[1] = b_rd[1][32 * dw[2:1] +: 32];
        // dw odd: its next dword is the even one after it (index + 1, maybe
        // index 0 of the next line: dw[2:1] + 1 wraps)
        win = dw[0] ? {bd[0], bd[1]} : {bd[1], bd[0]};
        m_data = 32'(win >> (8 * m_addr[1:0]));
    end

    // ---------------- drain: the store queue head, a line per step
    logic        d_second;      // a line-crossing store's second line
    logic [29:0] d_dw;
    logic [7:0]  d_m8;
    logic [63:0] d_w8;
    logic        d_hit, d_cross;
    logic [1:0]  d_way;
    logic        d_write;       // the step writes this cycle
    assign d_line = d_second ? 27'(d_addr[31:5] + 27'd1) : d_addr[31:5];
    always_comb begin
        d_dw = d_addr[31:2];
        d_m8 = 8'(bmask(d_size)) << d_addr[1:0];
        d_w8 = 64'(d_data) << (8 * d_addr[1:0]);
        d_cross = d_dw[2:0] == 3'd7 && d_m8[7:4] != 4'd0;
        d_hit = 1'b0;
        d_way = 2'd0;
        for (int w = 0; w < WAYS; w++)
            if (t_rd[2][w].v && t_rd[2][w].tag == d_line[31 -: TW]) begin
                d_hit = 1'b1;
                d_way = 2'(w);
            end
        // not into the line being evicted / filled (its data is captured),
        // nor while a probe uses the tag port
        d_write = d_valid && d_hit && !fl_req && st != S_FILL && st != S_CLR && st != S_SWP && !probing && !(st == S_WB && probe)
                  && !(st != S_IDLE && d_line[5 +: SW] == f_line[5 +: SW] && d_way == f_way);
        d_done = d_write && (d_second || !d_cross);
    end
    assign d_step = d_write;

    // probe lookup (the drain's tag copy)
    logic       p_hit;
    logic [1:0] p_way;
    always_comb begin
        p_hit = 1'b0;
        p_way = 2'd0;
        for (int w = 0; w < WAYS; w++)
            if (t_rd[2][w].v && t_rd[2][w].tag == pr_line[31 -: TW]) begin
                p_hit = 1'b1;
                p_way = 2'(w);
            end
        pr_done = probing && !(p_hit && t_rd[2][p_way].d) || st == S_WB && probe && mem_ready;
    end

    // ---------------- bank and tag ports
    always_comb begin
        logic        miss_a, miss_b;
        logic [29:0] bdw;
        logic [3:0]  m4;
        logic [31:0] w4;
        {bdw, m4, w4} = '0;
        // reads: the load (rows of its hit ways), or the victim
        for (int b = 0; b < 2; b++)
            b_ra[b] = st == S_EVRD ? {f_line[5 +: SW], f_way} : {set_of(a_bdw[b]), a_bway[b]};
        // writes: the fill, else the drain
        b_wa = '0;
        b_be = '0;
        b_wd = '0;
        t_we = 1'b0;
        t_set = '0;
        t_way = '0;
        t_wd = '0;
        if (st == S_CLR) begin
            t_we = 1'b1;
            t_set = clr;
        end else if (st == S_FILL) begin
            for (int b = 0; b < 2; b++) begin
                b_wa[b] = {f_line[5 +: SW], f_way};
                b_be[b] = '1;
                for (int j = 0; j < 4; j++) b_wd[b][32*j +: 32] = f_buf[32 * (2 * j + b) +: 32];
            end
            t_we = 1'b1;
            t_set = f_line[5 +: SW];
            t_way = f_way;
            t_wd = '{v: 1'b1, d: 1'b0, tag: f_line[31 -: TW]};
        end else if (st == S_WB && probe) begin   // the probed line, clean
            t_we = mem_ready;
            t_set = f_line[5 +: SW];
            t_way = f_way;
            t_wd = '{v: 1'b1, d: 1'b0, tag: v_tag};
        end else if (d_write) begin
            for (int b = 0; b < 2; b++) begin
                bdw = d_dw[0] == 1'(b) ? d_dw : d_dw + 30'd1;   // the bank's dword
                m4 = d_dw[0] == 1'(b) ? d_m8[3:0] : d_m8[7:4];
                w4 = d_dw[0] == 1'(b) ? d_w8[31:0] : d_w8[63:32];
                if (m4 != 4'd0 && bdw[29:3] == d_line) begin
                    b_wa[b] = {d_line[5 +: SW], d_way};
                    b_be[b] = 16'(m4) << (4 * bdw[2:1]);
                    b_wd[b] = 128'(w4) << (32 * bdw[2:1]);
                end
            end
            if (!t_rd[2][d_way].d) begin
                t_we = 1'b1;
                t_set = d_line[5 +: SW];
                t_way = d_way;
                t_wd = '{v: 1'b1, d: 1'b1, tag: d_line[31 -: TW]};
            end
        end
        // a miss (a load in A first, else the drain) when the MSHR is free
        miss_a = a_valid && st == S_IDLE && !pr_req && (a_need[0] && !a_bhit[0] || a_need[1] && !a_bhit[1]);
        miss = st == S_IDLE && !pr_req && !fl_req && (miss_a || d_valid && !d_hit);
        miss_b = !(a_need[0] && !a_bhit[0]);   // the load's missing line
        miss_line = miss_a ? a_bdw[miss_b][29:3] : d_line;
        miss_ways = miss_a ? t_rd[miss_b] : t_rd[2];
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            st <= S_CLR;
            clr <= '0;
            d_second <= 1'b0;
            rr <= 2'd0;
            sweeping <= 1'b0;
            swept <= 1'b0;
        end else begin
            if (d_write) d_second <= !d_done;
            if (!fl_req) swept <= 1'b0;
            case (st)
                S_IDLE:
                    if (probing) begin
                        if (p_hit && t_rd[2][p_way].d) begin
                            f_line <= pr_line;
                            f_way <= p_way;
                            v_tag <= t_rd[2][p_way].tag;
                            probe <= 1'b1;
                            st <= S_EVRD;
                        end
                    end else if (fl_req && !swept) begin
                        sweeping <= 1'b1;
                        sw <= '0;
                        st <= S_SWP;
                    end else if (miss) begin
                        logic [1:0] w;
                        logic dirty;
                        w = victim(miss_ways, rr);
                        // the drain may dirty the victim this cycle
                        dirty = miss_ways[w].v && (miss_ways[w].d || d_write && d_way == w
                                                   && d_line[5 +: SW] == miss_line[5 +: SW]);
                        f_line <= miss_line;
                        f_way <= w;
                        v_tag <= miss_ways[w].tag;
                        probe <= 1'b0;
                        st <= dirty ? S_EVRD : S_REQ;
                        rr <= rr + 2'd1;
                    end
                S_EVRD: st <= S_EVDATA;
                S_EVDATA: begin
                    for (int j = 0; j < 4; j++) begin
                        f_buf[32 * (2 * j) +: 32] <= b_rd[0][32*j +: 32];
                        f_buf[32 * (2 * j + 1) +: 32] <= b_rd[1][32*j +: 32];
                    end
                    st <= S_WB;
                end
                S_WB: if (mem_ready) st <= !probe ? S_REQ : sweeping ? S_SWP : S_IDLE;
                S_SWP:
                    if (sw_tg.v && sw_tg.d) begin   // written back, then looked at again (clean)
                        f_line <= {sw_tg.tag, sw[2 +: SW]};
                        f_way <= sw[1:0];
                        v_tag <= sw_tg.tag;
                        probe <= 1'b1;
                        st <= S_EVRD;
                    end else begin
                        sw <= sw + 1'd1;
                        if (sw == '1) begin
                            clr <= '0;
                            st <= S_CLR;
                        end
                    end
                S_REQ: if (mem_ready) st <= S_WAIT;
                S_WAIT:
                    if (mem_rvalid) begin
                        f_buf <= mem_rdata;
                        st <= mem_rcacheable ? S_FILL : S_IDLE;
                    end
                S_FILL: st <= S_IDLE;
                S_CLR: begin
                    clr <= clr + 1'd1;
                    if (clr == '1) begin
                        st <= S_IDLE;
                        swept <= sweeping;
                        sweeping <= 1'b0;
                    end
                end
                default: st <= S_IDLE;
            endcase
        end
    end

    assign mem_req = st == S_WB || st == S_REQ;
    assign mem_we = st == S_WB;
    assign mem_addr = st == S_WB ? {v_tag, f_line[5 +: SW]} : f_line;
    assign mem_wdata = f_buf;
endmodule
