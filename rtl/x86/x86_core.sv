// Out-of-order x86 integer core, M2 (plan/x86_core.md): flat 32-bit code,
// ideal memory ports, 3 x86 instructions decoded and 3 uops renamed,
// issued and retired per cycle.
// - Rename P6-style: results live in the ROB until retire, then in the
//   architectural registers (arch); RAT entries point to a ROB tag or arch.
//   The 6 arithmetic flags rename like a register (C2).
// - One unified reservation station capturing operands; issue oldest-ready
//   first: 2 ALU/branch ports + 1 load/store port; results written back at
//   the end of the cycle (dependent ALU uops issue back to back).
// - Loads wait for every older store address, forward from an equal-address
//   older store, wait for a partially overlapping one to retire.
// - Stores write memory at retire. Mispredicts flush at retire.
module x86_core
    import x86_pkg::*;
(
    input  logic                  clk,
    input  logic                  rst,
    input  logic [31:0]           reset_eip,
    output logic [31:0]           fetch_addr,
    input  logic [8*30-1:0]       fetch_data,
    output logic [31:0]           load_addr,     // ideal memory, same cycle
    input  logic [31:0]           load_data,
    output logic                  store_en,
    output logic [31:0]           store_addr,
    output logic [31:0]           store_data,
    // retire trace: up to 3 uops per cycle, in order
    output logic [2:0]            ret_valid,
    output logic [2:0]            ret_eop,
    output logic [2:0][31:0]      ret_next_eip,
    output logic [2:0]            ret_wdst,
    output logic [2:0][3:0]       ret_dst,
    output logic [2:0][31:0]      ret_value,
    output logic [2:0]            ret_wflags,
    output flags_t [2:0]          ret_flags,
    output logic                  halted,
    output logic                  illegal       // halted on an unsupported instruction
);
    localparam int UQ_N = 16;

    // ---------------- frontend + decode ----------------
    logic                 fe_redirect;
    logic [31:0]          fe_redirect_pc;
    logic [2:0]           x_valid, x_fault;
    logic [2:0][8*15-1:0] x_bytes;
    logic [2:0][31:0]     x_eip;
    logic [2:0][3:0]      x_len;
    logic                 dec_take;
    uop_t [2:0][2:0]      d_uop;
    logic [2:0][1:0]      d_n;
    logic [2:0]           d_redirect;
    logic [2:0][31:0]     d_target;

    x86_frontend fe (.clk(clk), .rst(rst), .redirect(fe_redirect), .redirect_pc(fe_redirect_pc),
                     .take(dec_take), .fetch_addr(fetch_addr), .fetch_data(fetch_data),
                     .valid(x_valid), .bytes(x_bytes), .eip(x_eip), .len(x_len), .fault(x_fault));

    genvar gi;
    generate for (gi = 0; gi < 3; gi = gi + 1) begin : dec
        x86_decode d (.bytes(x_bytes[gi]), .eip(x_eip[gi]), .len(x_len[gi]), .fault(x_fault[gi]),
                      .uop(d_uop[gi]), .n(d_n[gi]), .redirect(d_redirect[gi]), .target(d_target[gi]));
    end endgenerate

    // uop queue between decode and rename
    uop_t       uq [UQ_N];
    logic [3:0] uq_head, uq_tail;
    logic [4:0] uq_count;

    // ---------------- backend state ----------------
    typedef struct packed {
        logic        done;
        kind_t       kind;
        logic [3:0]  dst;
        logic        wdst, wflags, eop;
        logic [31:0] value;
        flags_t      flags;
        logic [31:0] next_eip;
        logic        mispred;
        logic [31:0] redirect_pc;
    } rob_t;

    typedef struct packed {
        logic             ready;
        logic [TAG_W-1:0] tag;
        logic [31:0]      value;
    } src_t;

    typedef struct packed {
        logic             ready;
        logic [TAG_W-1:0] tag;
        flags_t           value;
    } fsrc_t;

    typedef struct packed {
        logic             valid;
        uop_t             u;
        logic [TAG_W-1:0] tag;
        src_t [2:0]       src;       // s1, s2, s3
        fsrc_t            fsrc;
        logic [SQ_W:0]    sq_snap;   // loads: store queue tail at dispatch
        logic [SQ_W-1:0]  sq_idx;    // stores: own store queue entry
    } rs_t;

    typedef struct packed {
        logic        addr_valid;
        logic [31:0] addr, data;
    } sq_t;

    rob_t             rob [ROB_N];
    logic [TAG_W-1:0] rob_head, rob_tail;
    logic [TAG_W:0]   rob_count;
    rs_t              rs [RS_N];
    sq_t              sq [SQ_N];
    logic [SQ_W:0]    sq_head, sq_tail;      // with wrap bit
    logic [31:0]      arch [NREG];
    flags_t           arch_flags;
    logic             rat_rob [NREG];
    logic [TAG_W-1:0] rat_tag [NREG];
    logic             frat_rob;
    logic [TAG_W-1:0] frat_tag;

    // ---------------- write-back buses (results of this cycle) ----------------
    // 0, 1: ALU/branch ports; 2: load/store port
    logic [2:0]             wb_valid;
    logic [2:0][TAG_W-1:0]  wb_tag;
    logic [2:0][31:0]       wb_value;
    flags_t [2:0]           wb_flags;
    logic [2:0]             wb_mispred;
    logic [2:0][31:0]       wb_redirect_pc;   // branches: the actual next EIP
    logic [2:0]             wb_br;

    // ---------------- decode -> uop queue ----------------
    logic [3:0] d_total;
    always_comb begin
        logic stop;
        d_total = 4'd0;
        stop = 1'b0;
        for (int k = 0; k < 3; k++)
            if (x_valid[k] && !stop) begin
                d_total = d_total + 4'(d_n[k]);
                stop = d_redirect[k];
            end
    end
    assign dec_take = x_valid != 3'd0 && 5'(UQ_N) - uq_count >= 5'(d_total);

    // ---------------- retire ----------------
    logic [1:0]  r_n;            // uops retired this cycle
    logic        r_flush, r_halt, r_ill, r_store;
    logic [31:0] r_flush_pc;
    always_comb begin
        logic stop;
        r_n = 2'd0;
        r_flush = 1'b0;
        r_halt = 1'b0;
        r_ill = 1'b0;
        r_store = 1'b0;
        r_flush_pc = 32'd0;
        stop = halted;
        for (int k = 0; k < 3; k++) begin
            rob_t e;
            e = rob[TAG_W'(rob_head + TAG_W'(k))];
            ret_valid[k] = 1'b0;
            if (!stop && (TAG_W + 1)'(k) < rob_count && e.done && !(e.kind == K_ST && r_store)) begin
                ret_valid[k] = 1'b1;
                r_n = 2'(k + 1);
                if (e.kind == K_ST) r_store = 1'b1;
                if (e.kind == K_HLT) begin r_halt = 1'b1; stop = 1'b1; end
                if (e.kind == K_ILL) begin r_halt = 1'b1; r_ill = 1'b1; stop = 1'b1; end
                if (e.kind == K_BR && e.mispred) begin
                    r_flush = 1'b1;
                    r_flush_pc = e.redirect_pc;
                    stop = 1'b1;
                end
            end else stop = 1'b1;
            ret_eop[k] = e.eop;
            ret_next_eip[k] = e.next_eip;
            ret_wdst[k] = e.wdst;
            ret_dst[k] = e.dst;
            ret_value[k] = e.value;
            ret_wflags[k] = e.wflags;
            ret_flags[k] = e.flags;
        end
    end
    assign store_en = r_store;
    assign store_addr = sq[sq_head[SQ_W-1:0]].addr;
    assign store_data = sq[sq_head[SQ_W-1:0]].data;

    // frontend redirect: retire flush first, else the first predicted-taken
    // branch of the decoded group
    always_comb begin
        fe_redirect = r_flush;
        fe_redirect_pc = r_flush_pc;
        if (rst) fe_redirect_pc = reset_eip;
        else if (!r_flush && dec_take)
            for (int k = 2; k >= 0; k--)
                if (x_valid[k] && d_redirect[k]) begin
                    fe_redirect = 1'b1;
                    fe_redirect_pc = d_target[k];
                end
    end

    // ---------------- rename / dispatch ----------------
    logic [1:0]           ds_n;      // uops dispatched this cycle
    rs_t  [2:0]           ds_rs;
    logic [2:0][RS_N-1:0] ds_slot;   // one-hot RS entry per dispatched uop
    logic [2:0]           ds_to_rs;

    function automatic src_t read_src(input logic [3:0] r, input logic in_rob,
                                      input logic [TAG_W-1:0] t);
        src_t x;
        x.tag = t;
        x.ready = !in_rob || rob[t].done;
        x.value = !in_rob ? arch[r] : rob[t].value;
        for (int p = 0; p < 3; p++)
            if (in_rob && wb_valid[p] && wb_tag[p] == t) begin
                x.ready = 1'b1;
                x.value = wb_value[p];
            end
        return x;
    endfunction

    always_comb begin
        logic [RS_N-1:0]  used;
        logic [TAG_W:0]   rob_free;
        logic [SQ_W:0]    sqt;
        logic             stop, need_rs, need_sq, got, in_rob;
        uop_t             u;
        logic [3:0]       sr [3];
        logic             su [3];
        logic [TAG_W-1:0] t;
        src_t             x;
        rob_free = (TAG_W + 1)'(ROB_N) - rob_count;
        sqt = sq_tail;
        used = '0;
        for (int e = 0; e < RS_N; e++) used[e] = rs[e].valid;
        ds_n = 2'd0;
        stop = r_flush || halted;
        for (int k = 0; k < 3; k++) begin
            u = uq[4'(uq_head + 4'(k))];
            need_rs = !(u.kind == K_HLT || u.kind == K_ILL);
            need_sq = u.kind == K_ST;
            ds_rs[k] = '0;
            ds_rs[k].valid = 1'b1;
            ds_rs[k].u = u;
            ds_rs[k].tag = TAG_W'(rob_tail + TAG_W'(k));
            ds_rs[k].sq_snap = sqt;
            ds_rs[k].sq_idx = sqt[SQ_W-1:0];
            ds_slot[k] = '0;
            got = 1'b0;
            for (int e = 0; e < RS_N; e++)
                if (need_rs && !got && !used[e]) begin
                    got = 1'b1;
                    ds_slot[k][e] = 1'b1;
                end
            // sources: arch, an in-flight ROB entry, or an older uop of this group
            sr[0] = u.s1; su[0] = u.us1;
            sr[1] = u.s2; su[1] = u.us2;
            sr[2] = u.s3; su[2] = u.us3;
            for (int i = 0; i < 3; i++) begin
                in_rob = rat_rob[sr[i]];
                t = rat_tag[sr[i]];
                for (int j = 0; j < k; j++)
                    if (ds_rs[j].u.wdst && ds_rs[j].u.dst == sr[i]) begin
                        in_rob = 1'b1;
                        t = ds_rs[j].tag;
                    end
                ds_rs[k].src[i] = read_src(sr[i], in_rob, t);
                if (in_rob && in_group(k, t)) ds_rs[k].src[i].ready = 1'b0;
                if (!su[i]) ds_rs[k].src[i].ready = 1'b1;
            end
            in_rob = frat_rob;
            t = frat_tag;
            for (int j = 0; j < k; j++)
                if (ds_rs[j].u.wflags) begin
                    in_rob = 1'b1;
                    t = ds_rs[j].tag;
                end
            x = read_src(4'd0, in_rob, t);
            ds_rs[k].fsrc.tag = t;
            ds_rs[k].fsrc.ready = x.ready && !(in_rob && in_group(k, t)) || !u.rflags;
            ds_rs[k].fsrc.value = !in_rob ? arch_flags : rob[t].flags;
            for (int p = 0; p < 3; p++)
                if (in_rob && wb_valid[p] && wb_tag[p] == t) ds_rs[k].fsrc.value = wb_flags[p];
            ds_to_rs[k] = need_rs;
            if (!stop && 5'(k) < uq_count && (TAG_W + 1)'(k) < rob_free && (got || !need_rs)
                && !(need_sq && sqt - sq_head >= (SQ_W + 1)'(SQ_N))) begin
                ds_n = 2'(k + 1);
                used = used | ds_slot[k];
                if (need_sq) sqt = sqt + 1'b1;
            end else stop = 1'b1;
        end
    end

    // a tag written by an older uop of the same dispatch group: not ready
    function automatic logic in_group(input int k, input logic [TAG_W-1:0] t);
        logic r = 1'b0;
        for (int j = 0; j < 3; j++)
            if (j < k && TAG_W'(rob_tail + TAG_W'(j)) == t) r = 1'b1;
        return r;
    endfunction

    // ---------------- issue + execute ----------------
    logic [RS_N-1:0] alu_ready, mem_ready;
    logic [1:0]      alu_pick_v;
    logic [1:0][$clog2(RS_N)-1:0] alu_pick;
    logic            mem_pick_v;
    logic [$clog2(RS_N)-1:0] mem_pick;

    function automatic logic [TAG_W-1:0] age(input logic [TAG_W-1:0] t);
        return t - rob_head;
    endfunction

    // loads: every older store address known, no partial overlap
    function automatic logic load_ok(input rs_t r, input logic [31:0] a,
                                     output logic fwd, output logic [31:0] fdata);
        logic ok = 1'b1;
        fwd = 1'b0;
        fdata = 32'd0;
        for (int k = 0; k < SQ_N; k++)
            if ((SQ_W + 1)'(k) < r.sq_snap - sq_head) begin
                sq_t s;
                logic [31:0] d;
                s = sq[SQ_W'(sq_head[SQ_W-1:0] + SQ_W'(k))];
                d = s.addr - a;
                if (!s.addr_valid) ok = 1'b0;
                else if (s.addr == a) begin
                    fwd = 1'b1;
                    fdata = s.data;
                end else if (d < 32'd4 || d > 32'hFFFF_FFFC) ok = 1'b0;  // partial overlap
            end
        return ok;
    endfunction

    function automatic logic [31:0] agu(input rs_t r);
        return (r.u.us1 ? r.src[0].value : 32'd0)
             + (r.u.us2 ? r.src[1].value << r.u.scale : 32'd0) + r.u.imm;
    endfunction

    always_comb begin
        for (int e = 0; e < RS_N; e++) begin
            logic srcs;
            srcs = rs[e].valid && rs[e].src[0].ready && rs[e].src[1].ready && rs[e].src[2].ready
                   && rs[e].fsrc.ready;
            alu_ready[e] = srcs && (rs[e].u.kind == K_ALU || rs[e].u.kind == K_BR);
            mem_ready[e] = srcs && (rs[e].u.kind == K_LD || rs[e].u.kind == K_ST);
        end
        alu_pick_v = '0;
        alu_pick = '0;
        mem_pick_v = 1'b0;
        mem_pick = '0;
        for (int p = 0; p < 2; p++)
            for (int e = 0; e < RS_N; e++)
                if (alu_ready[e] && !(p == 1 && alu_pick_v[0] && alu_pick[0] == e[$clog2(RS_N)-1:0])
                    && (!alu_pick_v[p] || age(rs[e].tag) < age(rs[alu_pick[p]].tag))) begin
                    alu_pick_v[p] = 1'b1;
                    alu_pick[p] = e[$clog2(RS_N)-1:0];
                end
        for (int e = 0; e < RS_N; e++)
            if (mem_ready[e] && (!mem_pick_v || age(rs[e].tag) < age(rs[mem_pick].tag))) begin
                mem_pick_v = 1'b1;
                mem_pick = e[$clog2(RS_N)-1:0];
            end
    end

    logic [31:0] ld_addr;
    logic        ld_ok, ld_fwd;
    logic [31:0] ld_fdata;
    assign ld_addr = agu(rs[mem_pick]);
    assign load_addr = ld_addr;
    always_comb ld_ok = load_ok(rs[mem_pick], ld_addr, ld_fwd, ld_fdata);

    logic [1:0][31:0] alu_y;
    flags_t [1:0]     alu_f;
    generate for (gi = 0; gi < 2; gi = gi + 1) begin : alu
        x86_alu u_alu (.op(rs[alu_pick[gi]].u.aop), .a(rs[alu_pick[gi]].src[0].value),
                   .b(rs[alu_pick[gi]].u.us2 ? rs[alu_pick[gi]].src[1].value : rs[alu_pick[gi]].u.imm),
                   .fin(rs[alu_pick[gi]].fsrc.value), .y(alu_y[gi]), .f(alu_f[gi]));
    end endgenerate

    logic mem_go;   // the picked memory uop completes this cycle
    always_comb begin
        for (int p = 0; p < 2; p++) begin
            rs_t r;
            logic taken;
            logic [31:0] pc, pred;
            r = rs[alu_pick[p]];
            wb_valid[p] = alu_pick_v[p];
            wb_tag[p] = r.tag;
            wb_value[p] = r.u.aop == A_LEA ? agu(r) : alu_y[p];
            wb_flags[p] = r.u.wflags ? alu_f[p] : r.fsrc.value;
            taken = r.u.uncond || cond_taken(r.u.cond, r.fsrc.value);
            pc = !taken ? r.u.next_eip : r.u.indirect ? r.src[0].value : r.u.imm;
            pred = r.u.pred_taken ? r.u.imm : r.u.next_eip;
            wb_mispred[p] = r.u.kind == K_BR && pc != pred;
            wb_redirect_pc[p] = pc;
            wb_br[p] = r.u.kind == K_BR;
        end
        mem_go = mem_pick_v && (rs[mem_pick].u.kind == K_ST || ld_ok);
        wb_valid[2] = mem_go;
        wb_tag[2] = rs[mem_pick].tag;
        wb_value[2] = ld_fwd ? ld_fdata : load_data;
        wb_flags[2] = rs[mem_pick].fsrc.value;
        wb_mispred[2] = 1'b0;
        wb_redirect_pc[2] = 32'd0;
        wb_br[2] = 1'b0;
        if (r_flush || halted) wb_valid = '0;
    end

    // ---------------- state update ----------------
    always_ff @(posedge clk) begin
        if (rst || r_flush) begin
            uq_head <= '0;
            uq_tail <= '0;
            uq_count <= '0;
            rob_head <= '0;
            rob_tail <= '0;
            rob_count <= '0;
            for (int e = 0; e < RS_N; e++) rs[e].valid <= 1'b0;
            sq_tail <= sq_head + (SQ_W + 1)'(r_store);   // retired stores leave
            sq_head <= sq_head + (SQ_W + 1)'(r_store);
            for (int r = 0; r < NREG; r++) rat_rob[r] <= 1'b0;
            frat_rob <= 1'b0;
        end
        if (rst) begin
            sq_head <= '0;
            sq_tail <= '0;
            halted <= 1'b0;
            illegal <= 1'b0;
            for (int r = 0; r < NREG; r++) arch[r] <= 32'd0;
            arch[R_ESP] <= 32'h0010_0000;
            arch_flags <= '0;
        end else begin
            // retire: architectural state, RAT entries that still point here
            for (int k = 0; k < 3; k++)
                if (ret_valid[k]) begin
                    rob_t e;
                    logic [TAG_W-1:0] t;
                    t = TAG_W'(rob_head + TAG_W'(k));
                    e = rob[t];
                    if (e.wdst) begin
                        arch[e.dst] <= e.value;
                        if (rat_rob[e.dst] && rat_tag[e.dst] == t) rat_rob[e.dst] <= 1'b0;
                    end
                    if (e.wflags) begin
                        arch_flags <= e.flags;
                        if (frat_rob && frat_tag == t) frat_rob <= 1'b0;
                    end
                end
            if (r_halt) halted <= 1'b1;
            if (r_ill) illegal <= 1'b1;
            if (!r_flush) begin
                rob_head <= rob_head + TAG_W'(r_n);
                if (r_store) sq_head <= sq_head + 1'b1;
                // write-back
                for (int p = 0; p < 3; p++)
                    if (wb_valid[p]) begin
                        rob[wb_tag[p]].done <= 1'b1;
                        rob[wb_tag[p]].value <= wb_value[p];
                        rob[wb_tag[p]].flags <= wb_flags[p];
                        rob[wb_tag[p]].mispred <= wb_mispred[p];
                        rob[wb_tag[p]].redirect_pc <= wb_redirect_pc[p];
                        if (wb_br[p]) rob[wb_tag[p]].next_eip <= wb_redirect_pc[p];
                    end
                for (int p = 0; p < 2; p++)
                    if (alu_pick_v[p]) rs[alu_pick[p]].valid <= 1'b0;
                if (mem_go) begin
                    rs[mem_pick].valid <= 1'b0;
                    if (rs[mem_pick].u.kind == K_ST)
                        sq[rs[mem_pick].sq_idx] <= '{addr_valid: 1'b1, addr: ld_addr,
                            data: rs[mem_pick].u.us3 ? rs[mem_pick].src[2].value : rs[mem_pick].u.imm2};
                end
                // wakeup
                for (int e = 0; e < RS_N; e++)
                    for (int p = 0; p < 3; p++)
                        if (wb_valid[p]) begin
                            for (int i = 0; i < 3; i++)
                                if (!rs[e].src[i].ready && rs[e].src[i].tag == wb_tag[p]) begin
                                    rs[e].src[i].ready <= 1'b1;
                                    rs[e].src[i].value <= wb_value[p];
                                end
                            if (!rs[e].fsrc.ready && rs[e].fsrc.tag == wb_tag[p]) begin
                                rs[e].fsrc.ready <= 1'b1;
                                rs[e].fsrc.value <= wb_flags[p];
                            end
                        end
                // dispatch
                for (int k = 0; k < 3; k++)
                    if (2'(k) < ds_n) begin
                        uop_t u;
                        u = ds_rs[k].u;
                        rob[ds_rs[k].tag] <= '{done: (u.kind == K_HLT || u.kind == K_ILL), kind: u.kind,
                            dst: u.dst, wdst: u.wdst, wflags: u.wflags, eop: u.eop, value: 32'd0,
                            flags: '0, next_eip: u.next_eip, mispred: 1'b0, redirect_pc: 32'd0};
                        if (ds_to_rs[k])
                            for (int e = 0; e < RS_N; e++)
                                if (ds_slot[k][e]) rs[e] <= ds_rs[k];
                        if (u.kind == K_ST) sq[ds_rs[k].sq_idx].addr_valid <= 1'b0;
                        if (u.wdst) begin
                            rat_rob[u.dst] <= 1'b1;
                            rat_tag[u.dst] <= ds_rs[k].tag;
                        end
                        if (u.wflags) begin
                            frat_rob <= 1'b1;
                            frat_tag <= ds_rs[k].tag;
                        end
                    end
                rob_tail <= rob_tail + TAG_W'(ds_n);
                rob_count <= rob_count + (TAG_W + 1)'(ds_n) - (TAG_W + 1)'(r_n);
                if (ds_n != 2'd0) sq_tail <= ds_rs[ds_n - 2'd1].sq_snap
                                             + (SQ_W + 1)'(ds_rs[ds_n - 2'd1].u.kind == K_ST);
                // uop queue
                begin
                    logic [3:0] t, pushed;
                    logic       stop;
                    t = uq_tail;
                    stop = 1'b0;
                    if (dec_take)
                        for (int k = 0; k < 3; k++)
                            if (x_valid[k] && !stop) begin
                                for (int i = 0; i < 3; i++)
                                    if (i < int'(d_n[k])) begin
                                        uq[t] <= d_uop[k][i];
                                        t = t + 4'd1;
                                    end
                                stop = d_redirect[k];
                            end
                    pushed = t - uq_tail;   // 4-bit: wraps with the pointers
                    uq_tail <= t;
                    uq_head <= uq_head + 4'(ds_n);
                    uq_count <= uq_count + 5'(pushed) - 5'(ds_n);
                end
            end
        end
    end
endmodule
