// L1 instruction cache (plan/x86_core.md M3): 16 KB, 4-way, 32-byte lines,
// one miss in flight. Two banks, half 0 and half 1 of each line; the RAMs
// (tags and data, a copy per bank) are read with pc_n like the BTB, so in
// F0 the 32 bytes from pc_f are the block's half and the other one, of the
// next line when the block is half 1. A hit needs both: an instruction
// may run past its block. A miss fills the block's own half first.
// Stores to code: a store snoops the tags at its address (two more copies,
// MLAB) and is flagged when its line is here or being filled; draining, a
// flagged store invalidates every way of its set (the core holds fetch
// meanwhile). A miss waits while an older store to its line is queued,
// then the L1D writes the line back if dirty (probe), then it reads L2.
module x86_l1i
    import x86_pkg::*;
(
    input  logic            clk,
    input  logic            rst,
    input  logic [31:4]     pc_n,      // the next fetch block: RAMs read with it
    input  logic [31:4]     pc_f,      // the fetch block (pc_n a cycle ago)
    input  logic            hold,      // a store to code is draining: no hit, no miss
    output logic            hit,       // bytes: the 30 bytes at pc_f
    output logic [8*30-1:0] bytes,
    // stores
    input  logic [1:0][31:5] sn_line,  // a store's first and last byte lines
    output logic            sn_hit,    // either is here or being filled
    input  logic            inv,       // a store to code drained into inv_line
    input  logic [31:5]     inv_line,
    // miss
    output logic [31:5]     miss_line,
    input  logic            sq_busy,   // an older store to miss_line is queued
    output logic            pr_req,    // the L1D: write miss_line back if dirty
    input  logic            pr_done,
    // memory, 32-byte lines
    output logic            mem_req,
    output logic [31:5]     mem_addr,
    input  logic            mem_ready, // takes the request this cycle
    input  logic            mem_rvalid,
    input  logic [255:0]    mem_rdata
);
    localparam int SETS = 128, WAYS = 4, SW = $clog2(SETS), TW = 32 - 5 - SW;

    typedef struct packed {
        logic          v;
        logic [TW-1:0] tag;
    } tg_t;

    // the line bank b holds for the 32 bytes from block pc
    function automatic logic [31:5] bank_line(input logic [31:4] pc, input int b);
        return pc[4] && b == 0 ? pc[31:5] + 27'd1 : pc[31:5];
    endfunction

    typedef enum logic [2:0] {S_IDLE, S_SQ, S_PROBE, S_REQ, S_WAIT} st_t;
    st_t                         st;
    logic                        fill;     // line f_line into way f_way
    logic                        f_stale;  // a store to code drained into its set meanwhile
    logic [31:5]                 f_line;
    logic [1:0]                  f_way;
    logic [1:0][SW-1:0]          n_set;
    tg_t  [1:0][WAYS-1:0]        t_rd, s_rd;
    logic [1:0][WAYS-1:0][127:0] d_rd;
    // tag writes: an invalidation (every way of its set) first, else the fill
    logic [SW-1:0]               t_wa;
    tg_t                         t_wd;
    assign t_wa = inv ? inv_line[5 +: SW] : f_line[5 +: SW];
    assign t_wd = '{v: !inv && !f_stale, tag: f_line[31 -: TW]};
    always_comb
        for (int b = 0; b < 2; b++) begin
            logic [31:5] l;
            l = bank_line(pc_n, b);
            n_set[b] = l[5 +: SW];
        end
    genvar gb, gw;
    generate for (gb = 0; gb < 2; gb = gb + 1) begin : bk
        for (gw = 0; gw < WAYS; gw = gw + 1) begin : wy
            logic t_we;
            (* ramstyle = "no_rw_check" *) tg_t t [SETS];
            (* ramstyle = "MLAB, no_rw_check" *) tg_t s [SETS];   // snoop copy
            (* ramstyle = "no_rw_check" *) logic [127:0] d [SETS];
            initial for (int i = 0; i < SETS; i++) begin
                t[i] = '0;
                s[i] = '0;
            end
            assign t_we = inv || fill && f_way == 2'(gw);
            always_ff @(posedge clk) begin
                if (t_we) begin
                    t[t_wa] <= t_wd;
                    s[t_wa] <= t_wd;
                end
                if (fill && f_way == 2'(gw)) d[f_line[5 +: SW]] <= mem_rdata[128 * gb +: 128];
                t_rd[gb][gw] <= t[n_set[gb]];
                d_rd[gb][gw] <= d[n_set[gb]];
            end
            assign s_rd[gb][gw] = s[sn_line[gb][5 +: SW]];
        end
    end endgenerate

    // F0: tag compare and way select
    logic              filled;     // the RAMs were read while a tag write
    logic [1:0]        b_hit;
    logic [1:0][127:0] b_data;
    always_comb begin
        for (int b = 0; b < 2; b++) begin
            logic [31:5] l;
            l = bank_line(pc_f, b);
            b_hit[b] = 1'b0;
            b_data[b] = d_rd[b][0];
            for (int w = 0; w < WAYS; w++)
                if (t_rd[b][w].v && t_rd[b][w].tag == l[31 -: TW]) begin
                    b_hit[b] = 1'b1;
                    b_data[b] = d_rd[b][w];
                end
        end
        hit = b_hit == 2'b11 && !filled && !hold;
        bytes = 240'(pc_f[4] ? {b_data[0], b_data[1]} : {b_data[1], b_data[0]});
    end

    // stores: snoop copy b holds the tags of sn_line[b]'s set
    always_comb begin
        sn_hit = 1'b0;
        for (int b = 0; b < 2; b++) begin
            if (st != S_IDLE && sn_line[b] == f_line) sn_hit = 1'b1;
            for (int w = 0; w < WAYS; w++)
                if (s_rd[b][w].v && s_rd[b][w].tag == sn_line[b][31 -: TW]) sn_hit = 1'b1;
        end
    end

    function automatic logic [1:0] victim(input tg_t [WAYS-1:0] w, input logic [1:0] r);
        for (int i = WAYS - 1; i >= 0; i--) if (!w[i].v) return 2'(i);
        return r;
    endfunction

    logic [1:0] rr;              // replacement when no way is free
    assign fill = st == S_WAIT && mem_rvalid;
    always_ff @(posedge clk) begin
        if (rst) begin
            st <= S_IDLE;
            filled <= 1'b0;
            rr <= 2'd0;
        end else begin
            filled <= fill || inv;
            if (inv && st != S_IDLE && inv_line[5 +: SW] == f_line[5 +: SW]) f_stale <= 1'b1;
            case (st)
                S_IDLE:
                    if (b_hit != 2'b11 && !filled && !hold) begin
                        logic mb;
                        mb = b_hit[pc_f[4]] ? !pc_f[4] : pc_f[4];
                        f_line <= bank_line(pc_f, int'(mb));
                        f_way <= victim(t_rd[mb], rr);
                        f_stale <= 1'b0;
                        rr <= rr + 2'd1;
                        st <= S_SQ;
                    end
                S_SQ: if (!sq_busy) st <= S_PROBE;
                S_PROBE: if (pr_done) st <= S_REQ;
                S_REQ: if (mem_ready) st <= S_WAIT;
                S_WAIT: if (mem_rvalid) st <= S_IDLE;
                default: st <= S_IDLE;
            endcase
        end
    end
    assign miss_line = f_line;
    assign pr_req = st == S_PROBE;
    assign mem_req = st == S_REQ;
    assign mem_addr = f_line;
endmodule
