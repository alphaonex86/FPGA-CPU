// L2 (plan/x86_core.md M3): unified, KB kilobytes (default 256), 4-way,
// 32-byte lines, write-back, between the L1s' line port and memory (same
// port shape on both sides).
// - Front: one L1 request at a time. A read hit answers 2 cycles after it
//   is taken (tags, then data), also while the engine reads memory; a line
//   write (an L1D write-back) allocates without reading memory.
// - Engine: one memory line in flight (a miss or a prefetch); a dirty
//   victim is written back first. A read waiting on the engine's line
//   takes it from the memory data.
// - Reset clears the tags, a set per clock, before the first request.
// - Flush: fl_req held (no request taken meanwhile); once idle, a set per
//   two clocks, each dirty way written back by the engine and invalidated,
//   then the reset clear; fl_done until fl_req drops.
// - A memory line that came without KEN# (mem_cacheable low) is answered
//   (rcacheable low) but not kept: its way is left invalid.
// - Prefetch: once demand reads stream (each within PF + 1 lines after the
//   last), up to PF lines after the last one, in its 4 KB page, one at a
//   time when the front and the engine are idle.
module x86_l2 #(
    parameter int KB = 256,
    parameter int PF = 1
) (
    input  logic          clk,
    input  logic          rst,
    // L1 side
    input  logic          req,
    input  logic          we,
    input  logic [31:5]   addr,
    input  logic [255:0]  wdata,
    output logic          ready,      // takes the request this cycle
    output logic          rvalid,
    output logic [255:0]  rdata,
    output logic          rcacheable, // with rvalid
    // memory side
    output logic          mem_req,
    output logic          mem_we,
    output logic [31:5]   mem_addr,
    output logic [255:0]  mem_wdata,
    input  logic          mem_ready,
    input  logic          mem_rvalid,
    input  logic [255:0]  mem_rdata,
    input  logic          mem_cacheable,  // with mem_rvalid
    // flush
    input  logic          fl_req,
    output logic          fl_done
);
    localparam int WAYS = 4, SETS = KB * 1024 / 32 / WAYS, SW = $clog2(SETS), TW = 27 - SW;

    typedef struct packed {
        logic          v, d;
        logic [TW-1:0] tag;
    } tg_t;

    // front: S_HOLD waits for the engine (its line, or idle to retry)
    typedef enum logic [1:0] {S_IDLE, S_TAG, S_DATA, S_HOLD} st_t;
    typedef enum logic [2:0] {E_IDLE, E_VRD, E_WB, E_MREQ, E_MWAIT} en_t;
    st_t           st;
    en_t           en;
    logic          r_we, r_pf;     // the request taken; a prefetch (no answer)
    logic [31:5]   r_addr;
    logic [255:0]  r_wdata;
    logic [1:0]    r_way;          // hit way (S_DATA)
    logic [31:5]   e_addr;         // engine line
    logic [1:0]    e_way;
    logic          e_we;           // write-allocate: r_wdata after the write-back
    logic [TW-1:0] v_tag;
    logic [1:0]    rr;             // replacement when no way is free
    logic          fill, fill_q;   // the engine writes its line (fill_q: last cycle)
    logic [31:5]   pf_line, pf_base;   // next prefetch, last demand read
    logic          clearing;
    logic [SW-1:0] clr;            // the set cleared this clock
    // flush: W_RD reads the tags of sw_set, W_CHK writes a dirty way back
    typedef enum logic [2:0] {W_IDLE, W_RD, W_CHK, W_WAIT, W_CLR, W_DONE} sw_t;
    sw_t           sw_st;
    logic [SW-1:0] sw_set;
    logic          e_sw;           // the engine writes a dirty way back for the flush
    logic          sw_inv;         // ... and invalidates it now

    // tags (a RAM per way) and data ({set, way} rows), registered reads
    logic [SW-1:0]           t_ra, w_set;
    tg_t  [WAYS-1:0]         t_rd;
    logic                    t_we;
    tg_t                     t_wd;
    logic [1:0]              w_way;
    logic                    d_we;
    logic [SW+1:0]           d_ra;
    logic [255:0]            d_wd, d_rd;
    logic                    pf_go;
    assign t_ra = sw_st != W_IDLE ? sw_set : st != S_IDLE ? r_addr[5 +: SW] : pf_go ? pf_line[5 +: SW] : addr[5 +: SW];
    assign fl_done = sw_st == W_DONE;
    genvar gw;
    generate for (gw = 0; gw < WAYS; gw = gw + 1) begin : tw
        (* ramstyle = "no_rw_check" *) tg_t t [SETS];
        initial for (int i = 0; i < SETS; i++) t[i] = '0;
        always_ff @(posedge clk) begin
            if (clearing) t[clr] <= '0;
            else if (t_we && w_way == 2'(gw)) t[w_set] <= t_wd;
            t_rd[gw] <= t[t_ra];
        end
    end endgenerate
    (* ramstyle = "no_rw_check" *) logic [255:0] data [SETS * WAYS];
    always_ff @(posedge clk) begin
        if (d_we) data[{w_set, w_way}] <= d_wd;
        d_rd <= data[d_ra];
    end

    function automatic logic [1:0] victim(input tg_t [WAYS-1:0] w, input logic [1:0] r);
        for (int i = WAYS - 1; i >= 0; i--) if (!w[i].v) return 2'(i);
        return r;
    endfunction

    // S_TAG: hit way; the engine's way of its set is not a hit (its victim
    // or its line being filled), nor are tags read during a fill (fill_q)
    logic       hit, stale, e_busy;
    logic [1:0] hway, vway, sw_dirty;
    always_comb begin
        hit = 1'b0;
        hway = 2'd0;
        for (int w = 0; w < WAYS; w++)
            if (t_rd[w].v && t_rd[w].tag == r_addr[31 -: TW]) begin
                hit = 1'b1;
                hway = 2'(w);
            end
        e_busy = en != E_IDLE;
        stale = fill_q || e_busy && hit && hway == e_way && r_addr[5 +: SW] == e_addr[5 +: SW];
        vway = victim(t_rd, rr);
        sw_dirty = 2'd0;
        for (int w = 0; w < WAYS; w++) if (t_rd[w].v && t_rd[w].d) sw_dirty = 2'(w);
    end

    // prefetch: the next line within PF of the last demand read, same page
    logic [26:0] pf_dist;
    assign pf_dist = pf_line - pf_base;
    assign pf_go = st == S_IDLE && !clearing && !fl_req && !req && !e_busy && pf_dist != 27'd0 && pf_dist <= 27'(PF)
                   && pf_line[31:12] == pf_base[31:12];

    // the engine starts on a miss in S_TAG (it alone writes the RAMs then)
    logic start, start_dirty;
    always_comb begin
        start = st == S_TAG && !stale && !hit && !e_busy && !(r_we && !(t_rd[vway].v && t_rd[vway].d));
        start_dirty = t_rd[vway].v && t_rd[vway].d;
    end

    logic fw;
    // RAM writes: a front line write (hit or clean allocate, engine idle),
    // the engine's fill or write-allocate
    always_comb begin
        logic ew;
        fw = st == S_TAG && r_we && !stale && !e_busy && (hit || !(t_rd[vway].v && t_rd[vway].d));
        ew = en == E_WB && mem_ready && e_we;
        sw_inv = en == E_WB && mem_ready && e_sw;
        fill = en == E_MWAIT && mem_rvalid;
        d_we = fw || ew || fill;
        d_wd = fill ? mem_rdata : r_wdata;
        w_set = fw ? r_addr[5 +: SW] : e_addr[5 +: SW];
        w_way = fw ? (hit ? hway : vway) : e_way;
        t_we = d_we || sw_inv;
        t_wd = '{v: !sw_inv && (!fill || mem_cacheable), d: !fill, tag: fw ? r_addr[31 -: TW] : e_addr[31 -: TW]};
        d_ra = en == E_VRD || en == E_WB ? {e_addr[5 +: SW], e_way}   // the victim, kept for mem_wdata
                                         : {r_addr[5 +: SW], st == S_TAG ? hway : r_way};
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            clearing <= 1'b1;
            clr <= '0;
            st <= S_IDLE;
            en <= E_IDLE;
            rr <= 2'd0;
            fill_q <= 1'b0;
            pf_line <= '0;
            pf_base <= '0;
            sw_st <= W_IDLE;
        end else begin
            fill_q <= fill;
            if (clearing) begin
                clr <= clr + 1'd1;
                if (clr == '1) clearing <= 1'b0;
            end
            case (st)
                S_IDLE:
                    if (req && ready) begin
                        r_we <= we;
                        r_pf <= 1'b0;
                        r_addr <= addr;
                        r_wdata <= wdata;
                        st <= S_TAG;
                        if (!we) begin
                            pf_base <= addr;
                            // a stream: within PF + 1 lines after the last demand read
                            if (addr - pf_base - 27'd1 > 27'(PF)) pf_line <= addr;
                            else if (pf_line - addr - 27'd1 > 27'(PF)) pf_line <= addr + 27'd1;
                        end
                    end else if (pf_go) begin
                        r_we <= 1'b0;
                        r_pf <= 1'b1;
                        r_addr <= pf_line;
                        pf_line <= pf_line + 27'd1;
                        st <= S_TAG;
                    end
                S_TAG:
                    if (r_pf) st <= S_IDLE;
                    else if (stale) st <= S_HOLD;
                    else if (hit && !r_we) begin
                        // the data port holds the victim during a write-back
                        r_way <= hway;
                        st <= en == E_VRD || en == E_WB ? S_HOLD : S_DATA;
                    end else if (start || r_we && !e_busy) st <= r_we && !start ? S_IDLE : S_HOLD;
                    else st <= S_HOLD;
                S_DATA: st <= S_IDLE;
                S_HOLD:
                    if (r_we ? en == E_WB && mem_ready && e_we : fill && e_addr == r_addr) st <= S_IDLE;
                    else if (!e_busy) st <= S_TAG;
                default: st <= S_IDLE;
            endcase
            case (en)
                E_IDLE:
                    if (fw && !hit) rr <= rr + 2'd1;
                    else if (sw_st == W_CHK && t_rd[sw_dirty].v && t_rd[sw_dirty].d) begin
                        e_addr <= {t_rd[sw_dirty].tag, sw_set};
                        e_way <= sw_dirty;
                        e_we <= 1'b0;
                        e_sw <= 1'b1;
                        v_tag <= t_rd[sw_dirty].tag;
                        en <= E_VRD;
                    end else if (start) begin
                        e_sw <= 1'b0;
                        e_addr <= r_addr;
                        e_way <= vway;
                        e_we <= r_we;
                        v_tag <= t_rd[vway].tag;
                        rr <= rr + 2'd1;
                        en <= start_dirty ? E_VRD : E_MREQ;
                    end
                E_VRD: en <= E_WB;      // d_ra: the victim, d_rd next cycle
                E_WB: if (mem_ready) en <= e_we || e_sw ? E_IDLE : E_MREQ;
                E_MREQ: if (mem_ready) en <= E_MWAIT;
                E_MWAIT: if (mem_rvalid) en <= E_IDLE;
                default: en <= E_IDLE;
            endcase
            unique case (sw_st)
                W_IDLE: if (fl_req && st == S_IDLE && !e_busy && !clearing) begin
                    sw_set <= '0;
                    sw_st <= W_RD;
                end
                W_RD: sw_st <= W_CHK;
                W_CHK:
                    if (t_rd[sw_dirty].v && t_rd[sw_dirty].d) sw_st <= W_WAIT;
                    else begin
                        sw_set <= sw_set + 1'd1;
                        sw_st <= W_RD;
                        if (sw_set == '1) begin
                            clearing <= 1'b1;
                            clr <= '0;
                            sw_st <= W_CLR;
                        end
                    end
                W_WAIT: if (!e_busy) sw_st <= W_RD;
                W_CLR: if (!clearing) sw_st <= W_DONE;
                W_DONE: if (!fl_req) sw_st <= W_IDLE;
                default: sw_st <= W_IDLE;
            endcase
        end
    end

    assign ready = st == S_IDLE && !clearing && !fl_req;
    assign rvalid = st == S_DATA || st == S_HOLD && !r_we && fill && e_addr == r_addr;
    assign rdata = st == S_DATA ? d_rd : mem_rdata;
    assign rcacheable = st == S_DATA || mem_cacheable;
    assign mem_req = en == E_WB || en == E_MREQ;
    assign mem_we = en == E_WB;
    assign mem_addr = en == E_WB ? {v_tag, e_addr[5 +: SW]} : e_addr;
    assign mem_wdata = d_rd;
endmodule
