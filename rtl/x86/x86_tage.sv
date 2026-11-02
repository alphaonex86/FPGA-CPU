// Conditional branch direction for the P stage (plan/x86_core.md M2): TAGE
// with a 4K x 2-bit bimodal base (a weak counter keeps decode's static BTFN)
// and 4 tagged tables of 1K x {valid, 9-bit tag, 3-bit counter, 2-bit u},
// global histories 5 / 12 / 24 / 48 (offline on CoreMark: 3,731 -> 1,632
// mispredicts against the 4K gshare). One read port per decode slot (a table
// copy each), read as the group enters P with the history up to the group
// before the previous one (the same whether or not P was busy). The entries
// read go into a queue in program order (P push) and come back at retire:
// the first retired branch of a cycle updates its provider, or the base, and
// allocates in a longer table when mispredicted; a flush drops the rest.
module x86_tage
    import x86_pkg::*;
(
    input  logic             clk,
    input  logic             rst,
    input  logic             look,        // the group at look_pc enters P
    input  logic [2:0][31:0] look_pc,
    input  logic             p_busy,      // P holds a group (it pushes this cycle)
    input  logic [2:0]       btfn,        // P: static direction of slot k
    output logic [2:0]       dir,         // P: predicted direction of slot k
    input  logic             p_push,      // P pushes its group ...
    input  logic [2:0]       push,        // ... with these slots' Jcc, in order
    output logic             room,        // the queue takes a group's 3 Jcc
    input  logic             flush,
    input  logic [2:0]       ret,         // retired queued Jcc, in order
    input  logic [2:0]       ret_taken
);
    localparam int NT = 4, TW = 10, TG = 9, GH = 48, BW = 12, QN = 32, QW = $clog2(QN);

    typedef struct packed {
        logic          v;
        logic [TG-1:0] tag;
        logic [2:0]    ctr;
        logic [1:0]    u;
    } te_t;

    typedef struct packed {
        logic [BW-1:0]          bidx;
        logic [1:0]             bctr;
        logic                   pv;          // a tagged table provided pred
        logic [1:0]             prov;
        logic                   pred, altp;
        logic [NT-1:0][TW-1:0]  idx;
        logic [NT-1:0][TG-1:0]  tag;
        te_t [NT-1:0]           e;
    } meta_t;

    function automatic int hlen(input int t);
        case (t)
            0: return 5;
            1: return 12;
            2: return 24;
            default: return 48;
        endcase
    endfunction

    // XOR of the first len history bits in w-bit chunks
    function automatic logic [TW-1:0] fold(input logic [GH-1:0] h, input int len, input int w);
        logic [TW-1:0] v = '0;
        for (int i = 0; i < GH; i++) if (i < len) v[i % w] = v[i % w] ^ h[i];
        return v;
    endfunction

    function automatic logic [1:0] sat2(input logic [1:0] c, input logic up);
        return up ? (c == 2'd3 ? c : c + 2'd1) : (c == 2'd0 ? c : c - 2'd1);
    endfunction

    logic [GH-1:0]               gh, gh_prev, rgh, rgh_n;   // speculative (P) / retired
    logic [GH-1:0]               lh;                        // lookup history
    logic [2:0][NT-1:0][TW-1:0]  l_idx, q_idx;
    logic [2:0][NT-1:0][TG-1:0]  l_tag, q_tag;
    logic [2:0][BW-1:0]          q_bidx;
    te_t  [2:0][NT-1:0]          q_e;
    logic [2:0][1:0]             q_b;
    meta_t [2:0]                 m;
    meta_t                       bmq [QN];
    logic [QW:0]                 qh, qt;

    assign lh = p_busy ? gh : gh_prev;
    always_comb
        for (int k = 0; k < 3; k++)
            for (int t = 0; t < NT; t++) begin
                l_idx[k][t] = look_pc[k][TW-1:0] ^ look_pc[k][2*TW-1:TW] ^ fold(lh, hlen(t), TW);
                l_tag[k][t] = look_pc[k][TG+1:2] ^ TG'(fold(lh, hlen(t), TG))
                            ^ TG'({fold(lh, hlen(t), TG - 1), 1'b0});
            end

    // update (registered: off the retire path)
    logic              w_bwe;
    logic [BW-1:0]     w_bidx;
    logic [1:0]        w_bctr;
    logic [NT-1:0]     w_we;
    logic [NT-1:0][TW-1:0] w_idx;
    te_t  [NT-1:0]     w_e;

    genvar gk, gt;
    generate for (gk = 0; gk < 3; gk = gk + 1) begin : slot
        logic [1:0] base [1 << BW];
        initial for (int i = 0; i < 1 << BW; i++) base[i] = 2'd1;
        always_ff @(posedge clk) begin
            if (look) q_b[gk] <= base[look_pc[gk][BW-1:0]];
            if (w_bwe) base[w_bidx] <= w_bctr;
        end
        for (gt = 0; gt < NT; gt = gt + 1) begin : tab
            te_t tt [1 << TW];
            initial for (int i = 0; i < 1 << TW; i++) tt[i] = '0;
            always_ff @(posedge clk) begin
                if (look) q_e[gk][gt] <= tt[l_idx[gk][gt]];
                if (w_we[gt]) tt[w_idx[gt]] <= w_e[gt];
            end
        end
    end endgenerate

    always_ff @(posedge clk)
        if (look) begin
            q_idx <= l_idx;
            q_tag <= l_tag;
            for (int k = 0; k < 3; k++) q_bidx[k] <= look_pc[k][BW-1:0];
        end

    // P: provider = longest hitting table, alt = the next one, else the base
    always_comb
        for (int k = 0; k < 3; k++) begin
            logic bdir, found, found2;
            bdir = q_b[k] == 2'd3 || q_b[k] != 2'd0 && btfn[k];
            m[k].bidx = q_bidx[k];
            m[k].bctr = q_b[k];
            m[k].idx = q_idx[k];
            m[k].tag = q_tag[k];
            m[k].e = q_e[k];
            m[k].pv = 1'b0;
            m[k].prov = '0;
            m[k].pred = bdir;
            m[k].altp = bdir;
            found = 1'b0;
            found2 = 1'b0;
            for (int t = NT - 1; t >= 0; t--)
                if (q_e[k][t].v && q_e[k][t].tag == q_tag[k][t]) begin
                    if (!found) begin
                        m[k].pv = 1'b1;
                        m[k].prov = 2'(t);
                        m[k].pred = q_e[k][t].ctr[2];
                    end else if (!found2) begin
                        m[k].altp = q_e[k][t].ctr[2];
                        found2 = 1'b1;
                    end
                    found = 1'b1;
                end
            dir[k] = m[k].pred;
        end

    assign room = 6'(QN) - 6'(qt - qh) >= 6'd3;

    // retire: the first retired branch trains its provider (u when it
    // differed from alt) or the base; a mispredict allocates in the first
    // longer table with u = 0, decrementing the u of those it passes
    logic              r_bwe;
    logic [1:0]        r_bctr;
    logic [NT-1:0]     r_we;
    te_t  [NT-1:0]     r_e;
    meta_t             r_m;
    logic              r_t, r_any;
    always_comb begin
        logic stop;
        te_t  e;
        stop = 1'b0;
        r_any = 1'b0;
        r_t = 1'b0;
        rgh_n = rgh;
        for (int k = 0; k < 3; k++)
            if (ret[k]) begin
                if (!r_any) r_t = ret_taken[k];
                r_any = 1'b1;
                rgh_n = {rgh_n[GH-2:0], ret_taken[k]};
            end
        r_m = bmq[qh[QW-1:0]];
        r_bwe = r_any && !r_m.pv;
        r_bctr = sat2(r_m.bctr, r_t);
        r_we = '0;
        r_e = r_m.e;
        e = r_m.e[r_m.prov];
        if (r_any && r_m.pv) begin
            e.ctr = r_t ? (e.ctr == 3'd7 ? e.ctr : e.ctr + 3'd1) : (e.ctr == 3'd0 ? e.ctr : e.ctr - 3'd1);
            if (r_m.pred != r_m.altp)
                e.u = r_m.pred == r_t ? (e.u == 2'd3 ? e.u : e.u + 2'd1) : (e.u == 2'd0 ? e.u : e.u - 2'd1);
            r_we[r_m.prov] = 1'b1;
            r_e[r_m.prov] = e;
        end
        if (r_any && r_m.pred != r_t)
            for (int t = 0; t < NT; t++)
                if (!stop && (!r_m.pv || t > int'(r_m.prov))) begin
                    r_we[t] = 1'b1;
                    if (r_m.e[t].u == 2'd0 || !r_m.e[t].v) begin
                        r_e[t] = '{v: 1'b1, tag: r_m.tag[t], ctr: r_t ? 3'd4 : 3'd3, u: 2'd0};
                        stop = 1'b1;
                    end else
                        r_e[t].u = r_m.e[t].u - 2'd1;
                end
    end

    always_ff @(posedge clk) begin
        w_bwe <= r_bwe && !rst;
        w_bidx <= r_m.bidx;
        w_bctr <= r_bctr;
        w_we <= rst ? '0 : r_we;
        w_idx <= r_m.idx;
        w_e <= r_e;
        rgh <= rst ? '0 : rgh_n;
        qh <= rst ? '0 : qh + (QW + 1)'(ret[0]) + (QW + 1)'(ret[1]) + (QW + 1)'(ret[2]);
        if (rst) begin
            gh <= '0;
            gh_prev <= '0;
            qt <= '0;
        end else if (flush) begin
            gh <= rgh;   // the flushing branch included
            gh_prev <= rgh;
            qt <= qh;
        end else if (p_push) begin
            logic [GH-1:0] h;
            logic [QW:0] t;
            h = gh;
            t = qt;
            for (int k = 0; k < 3; k++)
                if (push[k]) begin
                    h = {h[GH-2:0], m[k].pred};
                    bmq[t[QW-1:0]] <= m[k];
                    t = t + 1'b1;
                end
            gh_prev <= gh;
            gh <= h;
            qt <= t;
        end
    end
endmodule
