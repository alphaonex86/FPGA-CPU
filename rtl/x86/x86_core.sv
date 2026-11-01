// Out-of-order x86 integer core, M2 (plan/x86_core.md): flat 32-bit code,
// ideal memory ports, 3 x86 instructions decoded and 3 uops renamed,
// issued and retired per cycle.
// - Rename P6-style: results live in the ROB until retire, then in the
//   architectural registers (arch); RAT entries point to a ROB tag or arch.
//   The 6 arithmetic flags rename like a register (C2).
// - One unified reservation station capturing operands. Pipeline S (select,
//   age matrix, oldest ready first per port) -> X (execute) -> wb1 (result
//   register: ROB, capture) -> wb2 (bypass only). Ports: 2 ALU/branch, each
//   ALU uop bound to one at dispatch; 1 memory port S -> A (AGU) -> M.
// - An ALU grant wakes its dependents at once (back to back issue); their
//   value then comes from the wb1/wb2 bypass until captured. Loads wake
//   their dependents from wb1.
// - Loads wait for every older store address, forward from an equal-address
//   older store, replay on a partially overlapping one.
// - Stores write memory at retire. A mispredicted branch retires, the
//   pipeline flushes the next cycle.
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
    output logic [1:0]            store_size,    // SZ8 / SZ16 / SZ32
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
    logic [2:0][31:0]     x_next, d_want;   // frontend / decode next EIP
    logic [2:0]           d_mis;            // they differ: redirect after k
    logic                 btb_we;
    logic [1:0]           btb_k;
    localparam int RAS_N = 8;
    logic [31:0]          ras [RAS_N];      // return stack, decode-time, may be wrong
    logic [$clog2(RAS_N)-1:0] ras_sp;       // top = ras[ras_sp - 1]
    logic [2:0]           d_call, d_ret;

    x86_frontend fe (.clk(clk), .rst(rst), .redirect(fe_redirect), .redirect_pc(fe_redirect_pc),
                     .take(dec_take), .fetch_addr(fetch_addr), .fetch_data(fetch_data),
                     .valid(x_valid), .bytes(x_bytes), .eip(x_eip), .len(x_len), .fault(x_fault),
                     .next(x_next), .btb_we(btb_we), .btb_set(d_redirect[btb_k]),
                     .btb_pc(x_eip[btb_k]), .btb_target(d_target[btb_k]));

    genvar gi;
    generate for (gi = 0; gi < 3; gi = gi + 1) begin : dec
        x86_decode d (.bytes(x_bytes[gi]), .eip(x_eip[gi]), .len(x_len[gi]), .fault(x_fault[gi]),
                      .ret_target(ras[ras_sp - 1'b1]), .call(d_call[gi]), .ret(d_ret[gi]),
                      .uop(d_uop[gi]), .n(d_n[gi]), .redirect(d_redirect[gi]), .target(d_target[gi]));
    end endgenerate
    always_comb
        for (int k = 0; k < 3; k++) begin
            d_want[k] = d_redirect[k] ? d_target[k] : x_eip[k] + 32'(x_len[k]);
            d_mis[k] = d_want[k] != x_next[k];
        end

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

    // ready: may issue; captured: value holds it (else it is on wb1/wb2)
    typedef struct packed {
        logic             ready, captured;
        logic [TAG_W-1:0] tag;
        logic [31:0]      value;
    } src_t;

    typedef struct packed {
        logic             ready, captured;
        logic [TAG_W-1:0] tag;
        flags_t           value;
    } fsrc_t;

    typedef struct packed {
        logic             valid;
        logic             issued;    // memory uops stay until M completes
        logic             port;      // ALU uops: ALU port
        uop_t             u;
        logic [TAG_W-1:0] tag;
        src_t [2:0]       src;       // s1, s2, s3
        fsrc_t            fsrc;
        logic [SQ_W:0]    sq_snap;   // loads: store queue tail at dispatch
        logic [SQ_W-1:0]  sq_idx;    // stores: own store queue entry
    } rs_t;

    typedef struct packed {
        logic        addr_valid;
        logic [1:0]  size;
        logic [31:0] addr, data;
    } sq_t;

    rob_t             rob [ROB_N];
    logic [TAG_W-1:0] rob_head, rob_tail;
    logic [TAG_W:0]   rob_count;
    rs_t              rs [RS_N];
    logic [RS_N-1:0]  older [RS_N];   // older[e][f]: entry f is older than e
    logic             alu_port;       // port of the next dispatched ALU uop
    sq_t              sq [SQ_N];
    logic [SQ_W:0]    sq_head, sq_tail;      // with wrap bit
    logic [31:0]      arch [NREG];
    flags_t           arch_flags;
    logic             rat_rob [NREG];
    logic [TAG_W-1:0] rat_tag [NREG];
    logic             frat_rob;
    logic [TAG_W-1:0] frat_tag;

    // ---------------- result registers ----------------
    // 0, 1: ALU/branch ports; 2: memory port. wb1 writes the ROB and the RS
    // (capture); wb2 is wb1 one cycle later, for the X/A bypass only.
    logic [2:0]             wb_valid;
    logic [2:0][TAG_W-1:0]  wb_tag;
    logic [2:0][31:0]       wb_value;
    flags_t [2:0]           wb_flags;
    logic [2:0]             wb_mispred;
    logic [2:0][31:0]       wb_redirect_pc;   // branches: the actual next EIP
    logic [2:0]             wb_br;
    logic [2:0]             wb2_valid;
    logic [2:0][TAG_W-1:0]  wb2_tag;
    logic [2:0][31:0]       wb2_value;
    flags_t [2:0]           wb2_flags;

    // ---------------- decode -> uop queue ----------------
    logic [3:0] d_total;
    always_comb begin
        logic stop;
        d_total = 4'd0;
        stop = 1'b0;
        for (int k = 0; k < 3; k++)
            if (x_valid[k] && !stop) begin
                d_total = d_total + 4'(d_n[k]);
                stop = d_mis[k];
            end
    end
    assign dec_take = x_valid != 3'd0 && 5'(UQ_N) - uq_count >= 5'(d_total);

    // ---------------- retire ----------------
    logic [1:0]  r_n;            // uops retired this cycle
    logic        r_flush, r_halt, r_ill, r_store;
    logic [31:0] r_flush_pc;
    logic        flush;           // r_flush one cycle later: clears the pipeline
    logic [31:0] flush_pc;
    always_comb begin
        logic stop;
        r_n = 2'd0;
        r_flush = 1'b0;
        r_halt = 1'b0;
        r_ill = 1'b0;
        r_store = 1'b0;
        r_flush_pc = 32'd0;
        stop = halted || flush;
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
    assign store_size = sq[sq_head[SQ_W-1:0]].size;

    // frontend redirect: retire flush first, else the first instruction of
    // the decoded group the frontend did not follow as decode predicts (the
    // BTB learns it)
    always_comb begin
        fe_redirect = flush;
        fe_redirect_pc = flush_pc;
        btb_we = 1'b0;
        btb_k = 2'd0;
        if (rst) fe_redirect_pc = reset_eip;
        else if (!flush && dec_take)
            for (int k = 2; k >= 0; k--)
                if (x_valid[k] && d_mis[k]) begin
                    fe_redirect = 1'b1;
                    fe_redirect_pc = d_want[k];
                    btb_we = 1'b1;
                    btb_k = 2'(k);
                end
    end

    // ---------------- R: rename ----------------
    // R reads the uop queue and the RAT and allocates the ROB entry, the
    // store queue entry and the RS budget; D (next cycle) reads the operand
    // values and writes the RS. A producer renamed in the same group needs
    // no special case in D: its ROB entry is allocated, not done.
    typedef struct packed {
        uop_t                  u;
        logic [TAG_W-1:0]      tag;
        logic                  port;
        logic [SQ_W:0]         sq_snap;
        logic [3:0]            in_rob;   // s1, s2, s3, flags
        logic [3:0][TAG_W-1:0] stag;
    } rn_t;

    logic [1:0] rn_n;     // uops renamed this cycle
    rn_t [2:0]  rn;
    logic       d_ok;     // D writes its group: enough free RS entries, else D and R stall

    function automatic logic is_alu(input kind_t k);
        return k == K_ALU || k == K_BR;
    endfunction

    function automatic logic needs_rs(input kind_t k);
        return !(k == K_HLT || k == K_ILL);
    endfunction

    always_comb begin
        logic [TAG_W:0] rob_free;
        logic [SQ_W:0]  sqt;
        logic           stop, par;
        logic [3:0]     sr;
        uop_t           u;
        rob_free = (TAG_W + 1)'(ROB_N) - rob_count;
        sqt = sq_tail;
        rn_n = 2'd0;
        par = 1'b0;
        stop = halted || !d_ok;
        for (int k = 0; k < 3; k++) begin
            u = uq[4'(uq_head + 4'(k))];
            rn[k] = '0;
            rn[k].u = u;
            rn[k].tag = TAG_W'(rob_tail + TAG_W'(k));
            rn[k].port = alu_port ^ par;
            par = par ^ is_alu(u.kind);
            rn[k].sq_snap = sqt;
            for (int i = 0; i < 3; i++) begin
                sr = i == 0 ? u.s1 : i == 1 ? u.s2 : u.s3;
                rn[k].in_rob[i] = rat_rob[sr];
                rn[k].stag[i] = rat_tag[sr];
                for (int j = 0; j < k; j++)
                    if (rn[j].u.wdst && rn[j].u.dst == sr) begin
                        rn[k].in_rob[i] = 1'b1;
                        rn[k].stag[i] = rn[j].tag;
                    end
            end
            rn[k].in_rob[3] = frat_rob;
            rn[k].stag[3] = frat_tag;
            for (int j = 0; j < k; j++)
                if (rn[j].u.wflags) begin
                    rn[k].in_rob[3] = 1'b1;
                    rn[k].stag[3] = rn[j].tag;
                end
            if (!stop && 5'(k) < uq_count && (TAG_W + 1)'(k) < rob_free
                && !(u.kind == K_ST && sqt - sq_head >= (SQ_W + 1)'(SQ_N)))
                rn_n = 2'(k + 1);
            else stop = 1'b1;
            if (u.kind == K_ST) sqt = sqt + 1'b1;
        end
    end

    // ---------------- D: operand read, RS write ----------------
    logic [2:0]           dq_valid;
    rn_t [2:0]            dq;
    rs_t  [2:0]           ds_rs;
    logic [2:0][RS_N-1:0] ds_slot;   // one-hot RS entry per uop
    logic [2:0]           ds_to_rs;

    function automatic src_t read_src(input logic [3:0] r, input logic in_rob,
                                      input logic [TAG_W-1:0] t);
        src_t x;
        x.tag = t;
        x.ready = !in_rob || rob[t].done;
        x.captured = 1'b0;
        x.value = !in_rob ? arch[r] : rob[t].value;
        for (int p = 0; p < 3; p++)
            if (in_rob && wb_valid[p] && wb_tag[p] == t) begin
                x.ready = 1'b1;
                x.value = wb_value[p];
            end
        return x;
    endfunction

    always_comb begin
        logic [RS_N-1:0]      free;
        logic [2:0][RS_N-1:0] fs;   // the first 3 free RS entries, one-hot
        logic [1:0]           nrs, need;
        logic [4:0]           nfree;
        logic [3:0]           sr [3];
        logic                 su [3];
        uop_t                 u;
        logic [TAG_W-1:0]     t;
        nfree = '0;
        for (int e = 0; e < RS_N; e++) begin
            free[e] = !rs[e].valid;
            nfree = nfree + 5'(free[e]);
        end
        need = 2'd0;
        for (int k = 0; k < 3; k++) need = need + 2'(dq_valid[k] && needs_rs(dq[k].u.kind));
        d_ok = nfree >= 5'(need);
        for (int i = 0; i < 3; i++) begin
            fs[i] = free & -free;   // lowest set bit
            free = free & ~fs[i];
        end
        nrs = 2'd0;
        for (int k = 0; k < 3; k++) begin
            u = dq[k].u;
            ds_rs[k] = '0;
            ds_rs[k].valid = 1'b1;
            ds_rs[k].port = dq[k].port;
            ds_rs[k].u = u;
            ds_rs[k].tag = dq[k].tag;
            ds_rs[k].sq_snap = dq[k].sq_snap;
            ds_rs[k].sq_idx = dq[k].sq_snap[SQ_W-1:0];
            sr[0] = u.s1; su[0] = u.us1;
            sr[1] = u.s2; su[1] = u.us2;
            sr[2] = u.s3; su[2] = u.us3;
            for (int i = 0; i < 3; i++) begin
                ds_rs[k].src[i] = read_src(sr[i], dq[k].in_rob[i], dq[k].stag[i]);
                if (!su[i]) ds_rs[k].src[i].ready = 1'b1;
                ds_rs[k].src[i].captured = ds_rs[k].src[i].ready;
            end
            t = dq[k].stag[3];
            ds_rs[k].fsrc.tag = t;
            ds_rs[k].fsrc.ready = !dq[k].in_rob[3] || rob[t].done || !u.rflags;
            ds_rs[k].fsrc.value = !dq[k].in_rob[3] ? arch_flags : rob[t].flags;
            for (int p = 0; p < 3; p++)
                if (dq[k].in_rob[3] && wb_valid[p] && wb_tag[p] == t) begin
                    ds_rs[k].fsrc.ready = 1'b1;
                    ds_rs[k].fsrc.value = wb_flags[p];
                end
            ds_rs[k].fsrc.captured = ds_rs[k].fsrc.ready;
            ds_to_rs[k] = d_ok && dq_valid[k] && needs_rs(u.kind);
            ds_slot[k] = fs[nrs];
            nrs = nrs + 2'(ds_to_rs[k]);
        end
    end

    // ---------------- S: select ----------------
    localparam int RS_W = $clog2(RS_N);
    logic [2:0][RS_N-1:0] req, grant;   // ports 0, 1 ALU, 2 memory
    logic [1:0][TAG_W-1:0] gtag;        // ALU grants: wake dependents now

    function automatic rs_t pick(input logic [RS_N-1:0] g);
        logic [$bits(rs_t)-1:0] v = '0;
        for (int e = 0; e < RS_N; e++) v = v | ({$bits(rs_t){g[e]}} & rs[e]);
        return rs_t'(v);
    endfunction

    function automatic logic [RS_W-1:0] slot_of(input logic [RS_N-1:0] g);
        logic [RS_W-1:0] v = '0;
        for (int e = 0; e < RS_N; e++) v = v | ({RS_W{g[e]}} & RS_W'(e));
        return v;
    endfunction

    always_comb begin
        logic [SQ_W:0] known;   // older store addresses known, from sq_head
        logic          stop;
        known = '0;
        stop = 1'b0;
        for (int k = 0; k < SQ_N; k++)
            if (!stop && (SQ_W + 1)'(k) < sq_tail - sq_head
                && sq[SQ_W'(sq_head[SQ_W-1:0] + SQ_W'(k))].addr_valid) known = known + 1'b1;
            else stop = 1'b1;
        for (int e = 0; e < RS_N; e++) begin
            logic srcs;
            srcs = rs[e].valid && !rs[e].issued && rs[e].src[0].ready && rs[e].src[1].ready
                   && rs[e].src[2].ready && rs[e].fsrc.ready;
            req[0][e] = srcs && is_alu(rs[e].u.kind) && !rs[e].port;
            req[1][e] = srcs && is_alu(rs[e].u.kind) && rs[e].port;
            req[2][e] = srcs && (rs[e].u.kind == K_ST
                                 || rs[e].u.kind == K_LD && rs[e].sq_snap - sq_head <= known);
        end
        for (int p = 0; p < 3; p++)
            for (int e = 0; e < RS_N; e++)
                grant[p][e] = req[p][e] && (req[p] & older[e]) == '0 && !halted;
        for (int p = 0; p < 2; p++) begin
            rs_t g;
            g = pick(grant[p]);
            gtag[p] = g.tag;
        end
    end

    // ---------------- X / A: execute, address ----------------
    logic [2:0]  ix_valid;   // issue registers
    rs_t [2:0]   ix;
    logic [RS_W-1:0] ix_slot;   // memory port: RS entry

    // operand: captured, else the producer result on wb1 / wb2
    function automatic logic [31:0] opnd(input src_t x);
        logic [31:0] v = x.value;
        if (!x.captured)
            for (int q = 0; q < 3; q++) begin
                if (wb2_valid[q] && wb2_tag[q] == x.tag) v = wb2_value[q];
                if (wb_valid[q] && wb_tag[q] == x.tag) v = wb_value[q];
            end
        return v;
    endfunction

    function automatic flags_t fopnd(input fsrc_t x);
        flags_t v = x.value;
        if (!x.captured)
            for (int q = 0; q < 3; q++) begin
                if (wb2_valid[q] && wb2_tag[q] == x.tag) v = wb2_flags[q];
                if (wb_valid[q] && wb_tag[q] == x.tag) v = wb_flags[q];
            end
        return v;
    endfunction

    function automatic rs_t resolve(input rs_t r);
        rs_t x = r;
        for (int i = 0; i < 3; i++) x.src[i].value = opnd(r.src[i]);
        x.fsrc.value = fopnd(r.fsrc);
        return x;
    endfunction

    function automatic logic [31:0] agu(input rs_t r);
        return (r.u.us1 ? r.src[0].value : 32'd0)
             + (r.u.us2 ? r.src[1].value << r.u.scale : 32'd0) + r.u.imm;
    endfunction

    rs_t [2:0]        xr;    // issue registers with resolved operands
    logic [1:0][31:0] alu_y;
    flags_t [1:0]     alu_f;
    always_comb for (int p = 0; p < 3; p++) xr[p] = resolve(ix[p]);

    // a source value, AH..BH moved down
    function automatic logic [31:0] byte_hi(input logic [31:0] v, input logic hi);
        return hi ? v >> 8 : v;
    endfunction

    generate for (gi = 0; gi < 2; gi = gi + 1) begin : alu
        x86_alu u_alu (.op(xr[gi].u.aop), .sz(xr[gi].u.osz), .cond(xr[gi].u.cond),
                       .a(byte_hi(xr[gi].src[0].value, xr[gi].u.hi1)),
                       .b(xr[gi].u.us2 ? byte_hi(xr[gi].src[1].value, xr[gi].u.hi2) : xr[gi].u.imm),
                       .fin(xr[gi].fsrc.value), .y(alu_y[gi]), .f(alu_f[gi]));
    end endgenerate

`ifndef SYNTHESIS
    // invariant: an uncaptured source of an issued uop is on wb1 or wb2
    always_ff @(posedge clk)
        if (!rst)
            for (int p = 0; p < 3; p++)
                if (ix_valid[p])
                    for (int i = 0; i < 4; i++) begin
                        logic cap, hit;
                        logic [TAG_W-1:0] t;
                        cap = i < 3 ? ix[p].src[i].captured : ix[p].fsrc.captured;
                        t = i < 3 ? ix[p].src[i].tag : ix[p].fsrc.tag;
                        hit = 1'b0;
                        for (int q = 0; q < 3; q++)
                            hit = hit || wb_valid[q] && wb_tag[q] == t || wb2_valid[q] && wb2_tag[q] == t;
                        if (!cap && !hit) $error("port %0d source %0d: tag %0d on no bypass", p, i, t);
                    end
`endif

    // memory port A -> M register
    logic             am_valid, am_store, am_dhi;
    logic [TAG_W-1:0] am_tag;
    logic [31:0]      am_addr, am_data;   // store data, or a load's merge source
    logic [1:0]       am_osz, am_lext;
    logic [SQ_W:0]    am_sq_snap;
    logic [SQ_W-1:0]  am_sq_idx;
    logic [RS_W-1:0]  am_slot;

    // ---------------- M: memory ----------------
    // loads: forward from an older store at the same address at least as
    // wide, replay on any other overlap
    function automatic logic load_ok(input logic [SQ_W:0] snap, input logic [31:0] a,
                                     input logic [1:0] lsz,
                                     output logic fwd, output logic [31:0] fdata);
        logic ok = 1'b1;
        fwd = 1'b0;
        fdata = 32'd0;
        for (int k = 0; k < SQ_N; k++)
            if ((SQ_W + 1)'(k) < snap - sq_head) begin
                sq_t s;
                s = sq[SQ_W'(sq_head[SQ_W-1:0] + SQ_W'(k))];
                if (!s.addr_valid) ok = 1'b0;
                else if (s.addr == a && s.size >= lsz) begin
                    fwd = 1'b1;
                    fdata = s.data;
                end else if (a - s.addr < 32'd1 << s.size || s.addr - a < 32'd1 << lsz) ok = 1'b0;
            end
        return ok;
    endfunction

    logic        m_ok, m_fwd;
    logic [31:0] m_fdata;
    assign load_addr = am_addr;
    always_comb begin
        logic ld_ok;
        ld_ok = load_ok(am_sq_snap, am_addr, am_osz, m_fwd, m_fdata);
        m_ok = am_store || ld_ok;
    end

    // ---------------- results of X and M ----------------
    logic [2:0]             ex_valid;
    logic [2:0][31:0]       ex_value, ex_redirect_pc;
    flags_t [2:0]           ex_flags;
    logic [2:0]             ex_mispred, ex_br;
    always_comb begin
        for (int p = 0; p < 2; p++) begin
            rs_t r;
            logic taken;
            logic [31:0] pc, pred;
            r = xr[p];
            ex_valid[p] = ix_valid[p];
            ex_value[p] = r.u.aop == A_LEA ? agu(r) : merge(r.src[0].value, alu_y[p], r.u.osz, r.u.dhi);
            ex_flags[p] = r.u.wflags ? alu_f[p] : r.fsrc.value;
            taken = r.u.uncond || cond_taken(r.u.cond, r.fsrc.value);
            pc = !taken ? r.u.next_eip : r.u.indirect ? r.src[0].value : r.u.imm;
            pred = r.u.pred_taken ? r.u.imm : r.u.next_eip;
            ex_mispred[p] = r.u.kind == K_BR && pc != pred;
            ex_redirect_pc[p] = pc;
            ex_br[p] = r.u.kind == K_BR;
        end
        ex_valid[2] = am_valid && m_ok;
        begin
            logic [31:0] raw;
            raw = m_fwd ? m_fdata : load_data;
            ex_value[2] = am_lext == LX_MERGE ? merge(am_data, raw, am_osz, am_dhi)
                                              : extend(raw, am_osz, am_lext == LX_SIGN);
        end
        ex_flags[2] = '0;
        ex_mispred[2] = 1'b0;
        ex_redirect_pc[2] = 32'd0;
        ex_br[2] = 1'b0;
    end

    // ---------------- state update ----------------
    always_ff @(posedge clk) begin
        flush <= r_flush && !rst;
        flush_pc <= r_flush_pc;
        if (rst || flush) begin
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
            ix_valid <= '0;
            dq_valid <= '0;
            am_valid <= 1'b0;
            wb_valid <= '0;
            wb2_valid <= '0;
        end
        if (rst) begin
            sq_head <= '0;
            sq_tail <= '0;
            halted <= 1'b0;
            illegal <= 1'b0;
            alu_port <= 1'b0;
            ras_sp <= '0;
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
            if (!flush) begin
                rob_head <= rob_head + TAG_W'(r_n);
                if (r_store) sq_head <= sq_head + 1'b1;
                // wb1 -> ROB
                for (int p = 0; p < 3; p++)
                    if (wb_valid[p]) begin
                        rob[wb_tag[p]].done <= 1'b1;
                        rob[wb_tag[p]].value <= wb_value[p];
                        rob[wb_tag[p]].flags <= wb_flags[p];
                        rob[wb_tag[p]].mispred <= wb_mispred[p];
                        rob[wb_tag[p]].redirect_pc <= wb_redirect_pc[p];
                        if (wb_br[p]) rob[wb_tag[p]].next_eip <= wb_redirect_pc[p];
                    end
                // X / M -> wb1 -> wb2
                wb_valid <= ex_valid;
                wb_value <= ex_value;
                wb_flags <= ex_flags;
                wb_mispred <= ex_mispred;
                wb_redirect_pc <= ex_redirect_pc;
                wb_br <= ex_br;
                for (int p = 0; p < 2; p++) wb_tag[p] <= ix[p].tag;
                wb_tag[2] <= am_tag;
                wb2_valid <= wb_valid;
                wb2_tag <= wb_tag;
                wb2_value <= wb_value;
                wb2_flags <= wb_flags;
                // S -> X / A
                for (int p = 0; p < 3; p++) begin
                    ix_valid[p] <= grant[p] != '0;
                    ix[p] <= pick(grant[p]);
                end
                ix_slot <= slot_of(grant[2]);
                for (int p = 0; p < 2; p++)
                    for (int e = 0; e < RS_N; e++)
                        if (grant[p][e]) rs[e].valid <= 1'b0;
                for (int e = 0; e < RS_N; e++)
                    if (grant[2][e]) rs[e].issued <= 1'b1;
                // A -> M
                am_valid <= ix_valid[2];
                am_store <= ix[2].u.kind == K_ST;
                am_tag <= ix[2].tag;
                am_addr <= agu(xr[2]);
                am_data <= ix[2].u.us3 ? byte_hi(xr[2].src[2].value, ix[2].u.hi3) : ix[2].u.imm2;
                am_osz <= ix[2].u.osz;
                am_lext <= ix[2].u.lext;
                am_dhi <= ix[2].u.dhi;
                am_sq_snap <= ix[2].sq_snap;
                am_sq_idx <= ix[2].sq_idx;
                am_slot <= ix_slot;
                // M: done or replay
                if (am_valid) begin
                    if (m_ok) rs[am_slot].valid <= 1'b0;
                    else rs[am_slot].issued <= 1'b0;
                    if (am_store) sq[am_sq_idx] <= '{addr_valid: 1'b1, size: am_osz, addr: am_addr, data: am_data};
                end
                // wakeup: ALU grants (ready), wb1 (ready + capture)
                for (int e = 0; e < RS_N; e++) begin
                    for (int i = 0; i < 3; i++) begin
                        for (int p = 0; p < 2; p++)
                            if (grant[p] != '0 && rs[e].src[i].tag == gtag[p]) rs[e].src[i].ready <= 1'b1;
                        for (int p = 0; p < 3; p++)
                            if (wb_valid[p] && !rs[e].src[i].captured && rs[e].src[i].tag == wb_tag[p]) begin
                                rs[e].src[i].ready <= 1'b1;
                                rs[e].src[i].captured <= 1'b1;
                                rs[e].src[i].value <= wb_value[p];
                            end
                    end
                    for (int p = 0; p < 2; p++)
                        if (grant[p] != '0 && rs[e].fsrc.tag == gtag[p]) rs[e].fsrc.ready <= 1'b1;
                    for (int p = 0; p < 3; p++)
                        if (wb_valid[p] && !rs[e].fsrc.captured && rs[e].fsrc.tag == wb_tag[p]) begin
                            rs[e].fsrc.ready <= 1'b1;
                            rs[e].fsrc.captured <= 1'b1;
                            rs[e].fsrc.value <= wb_flags[p];
                        end
                end
                // D: RS (+ age matrix row)
                begin
                    logic [RS_N-1:0] valid_now, new_slots, row;
                    for (int e = 0; e < RS_N; e++) valid_now[e] = rs[e].valid;
                    new_slots = '0;
                    for (int k = 0; k < 3; k++)
                        if (ds_to_rs[k]) new_slots = new_slots | ds_slot[k];
                    for (int e = 0; e < RS_N; e++) older[e] <= older[e] & ~new_slots;
                    row = valid_now;
                    for (int k = 0; k < 3; k++)
                        if (ds_to_rs[k]) begin
                            for (int e = 0; e < RS_N; e++)
                                if (ds_slot[k][e]) begin
                                    rs[e] <= ds_rs[k];
                                    older[e] <= row;
                                end
                            row = row | ds_slot[k];
                        end
                end
                // R: ROB, RAT, store queue entry -> D
                for (int k = 0; k < 3; k++) begin
                    if (d_ok) begin
                        dq_valid[k] <= 2'(k) < rn_n;
                        dq[k] <= rn[k];
                    end
                    if (2'(k) < rn_n) begin
                        uop_t u;
                        u = rn[k].u;
                        rob[rn[k].tag] <= '{done: !needs_rs(u.kind), kind: u.kind,
                            dst: u.dst, wdst: u.wdst, wflags: u.wflags, eop: u.eop, value: 32'd0,
                            flags: '0, next_eip: u.next_eip, mispred: 1'b0, redirect_pc: 32'd0};
                        if (u.kind == K_ST) sq[rn[k].sq_snap[SQ_W-1:0]].addr_valid <= 1'b0;
                        if (u.wdst) begin
                            rat_rob[u.dst] <= 1'b1;
                            rat_tag[u.dst] <= rn[k].tag;
                        end
                        if (u.wflags) begin
                            frat_rob <= 1'b1;
                            frat_tag <= rn[k].tag;
                        end
                        if (is_alu(u.kind)) alu_port <= !rn[k].port;
                    end
                end
                rob_tail <= rob_tail + TAG_W'(rn_n);
                rob_count <= rob_count + (TAG_W + 1)'(rn_n) - (TAG_W + 1)'(r_n);
                if (rn_n != 2'd0) sq_tail <= rn[rn_n - 2'd1].sq_snap
                                             + (SQ_W + 1)'(rn[rn_n - 2'd1].u.kind == K_ST);
                // uop queue
                begin
                    logic [3:0] t, pushed;
                    logic       stop;
                    logic [$clog2(RAS_N)-1:0] sp;
                    sp = ras_sp;
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
                                stop = d_mis[k];
                                if (d_call[k]) begin
                                    ras[sp] <= x_eip[k] + 32'(x_len[k]);
                                    sp = sp + 1'b1;
                                end
                                if (d_ret[k]) sp = sp - 1'b1;
                            end
                    ras_sp <= sp;
                    pushed = t - uq_tail;   // 4-bit: wraps with the pointers
                    uq_tail <= t;
                    uq_head <= uq_head + 4'(rn_n);
                    uq_count <= uq_count + 5'(pushed) - 5'(rn_n);
                end
            end
        end
    end
endmodule
