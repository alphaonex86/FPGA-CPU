// Fetch + predecode + instruction extraction (plan/x86_core.md M2).
// F0 fetches the 16-byte block at pc_f plus the 14 bytes after it from the
// L1I (x86_l1i; a miss holds F0), F1/F2 run
// x86_predecode, F2 pushes the block into a 4-entry queue; extraction takes
// up to 3 instructions per cycle from the head block starting at offset
// off, into the output register read by the decoders. An instruction may
// run past its block: the window holds it whole.
// BTB: per 16-byte block, the start offset and target of the taken branch
// decode predicted there; F0 follows it, so the block ends at that
// instruction and the next block is the target's. Each instruction carries
// the EIP the frontend continues at (next); decode redirects and fixes the
// BTB when it disagrees, so a stale entry only costs cycles. The BTB is a
// RAM read with pc_f's next value (no reset: entries start invalid).
module x86_frontend
    import x86_pkg::*;
(
    input  logic                  clk,
    input  logic                  rst,
    input  logic                  redirect,      // flush, continue at redirect_pc
    input  logic [31:0]           redirect_pc,
    input  logic                  take,          // decoders consume the output
    output logic                  mem_req,       // L1I line reads
    output logic [31:5]           mem_addr,
    input  logic                  mem_ready,
    input  logic                  mem_rvalid,
    input  logic [255:0]          mem_rdata,
    output logic [2:0]            valid,
    output logic [2:0][8*15-1:0]  bytes,
    output logic [2:0][31:0]      eip,
    output logic [2:0][3:0]       len,
    output logic [2:0][3:0]       npfx,          // prefix bytes before the opcode
    output logic [2:0]            fault,
    output logic [2:0][31:0]      next,
    input  logic                  btb_we,        // set (btb_set) or clear the
    input  logic                  btb_set,       // entry of btb_pc's block
    input  logic [31:0]           btb_pc,
    input  logic [31:0]           btb_target
);
    localparam int FQ_N = 4;
    localparam int BTB_N = 512;
    localparam int BI_W = $clog2(BTB_N);

    typedef struct packed {
        logic                 valid;
        logic [27-BI_W:0]     tag;
        logic [3:0]           off;      // start offset of the branch
        logic [31:0]          target;
    } btb_t;

    // taken: the block ends at the first instruction starting at >= moff
    typedef struct packed {
        logic              taken;
        logic [3:0]        moff;
        logic [31:0]       target;
    } mark_t;

    typedef struct packed {
        logic [31:0]       pc;
        logic [8*30-1:0]   bytes;
        logic [15:0][3:0]  len, npfx;
        logic [15:0][4:0]  nx;          // next instruction start: i + len[i]
        logic [15:0]       fault;
        mark_t             mark;
    } block_t;

    (* ramstyle = "no_rw_check" *) btb_t btb [BTB_N];
    btb_t             bh;           // the entry of pc_f's block
    logic [31:0]      pc_n;         // pc_f's next value
    logic [3:0]       f0_off;       // first start offset in the block at pc_f
    mark_t            f0_mark, f1_mark, f2_mark;

    logic [31:0]      pc_f, f1_pc, f2_pc;
    logic             f1_valid, f2_valid;
    logic [8*30-1:0]  f1_bytes, f2_bytes;
    logic [15:0][3:0] pd_len, pd_npfx;
    logic [15:0][1:0] pd_map;
    logic [15:0]      pd_fault;
    block_t           fq [FQ_N];
    logic [1:0]       fq_head, fq_tail;
    logic [2:0]       fq_count;
    logic [4:0]       off;          // start offset in the head block, < 16
    logic             stopped;      // after a faulting instruction
    logic             issue, push, pop, out_free;
    logic [2:0]       x_valid;
    logic [4:0]       x_next;
    logic [2:0][4:0]  s;
    logic [2:0]       last;         // instruction k ends the head block
    logic             ic_hit;
    logic [8*30-1:0]  ic_bytes;     // the 30 bytes at pc_f

    x86_l1i u_l1i (.clk(clk), .rst(rst), .pc_n(pc_n[31:4]), .pc_f(pc_f[31:4]),
                   .hit(ic_hit), .bytes(ic_bytes),
                   .mem_req(mem_req), .mem_addr(mem_addr), .mem_ready(mem_ready),
                   .mem_rvalid(mem_rvalid), .mem_rdata(mem_rdata));

    x86_predecode #(.N(16)) pd (.clk(clk), .bytes(f1_bytes), .d32(1'b1), .len(pd_len),
                                .npfx(pd_npfx), .map(pd_map), .fault(pd_fault));

    always_comb begin
        f0_mark.taken = bh.valid && bh.tag == pc_f[31:4+BI_W] && bh.off >= f0_off;
        f0_mark.moff = bh.off;
        f0_mark.target = bh.target;
    end
    // blocks in F1, F2 and the queue never exceed its size
    assign issue = ic_hit && 3'(f1_valid) + 3'(f2_valid) + fq_count < 3'(FQ_N);
    assign push = f2_valid;
    assign out_free = valid == 3'd0 || take;

    // extraction from the head block
    always_comb begin
        block_t h;
        h = fq[fq_head];
        s[0] = off;
        s[1] = h.nx[s[0][3:0]];
        s[2] = s[1][4] ? 5'd16 : h.nx[s[1][3:0]];
        for (int k = 0; k < 3; k++)
            last[k] = h.mark.taken && s[k][3:0] >= h.mark.moff
                      || (k < 2 ? s[k + 1][4] : h.nx[s[2][3:0]][4]);
        x_valid[0] = fq_count != 3'd0 && !stopped;
        x_valid[1] = x_valid[0] && !last[0] && !h.fault[s[0][3:0]];
        x_valid[2] = x_valid[1] && !last[1] && !h.fault[s[1][3:0]];
        x_next = !x_valid[1] ? s[1] : !x_valid[2] ? s[2] : h.nx[s[2][3:0]];
    end
    // the last valid instruction ends the block
    assign pop = out_free && x_valid[0] && (!x_valid[1] ? last[0] : !x_valid[2] ? last[1] : last[2]);

    assign pc_n = rst || redirect ? {redirect_pc[31:4], 4'd0}
                : !issue ? pc_f
                : f0_mark.taken ? {f0_mark.target[31:4], 4'd0} : pc_f + 32'd16;
    initial for (int i = 0; i < BTB_N; i++) btb[i] = '0;
    always_ff @(posedge clk) begin
        pc_f <= pc_n;
        bh <= btb[pc_n[4 +: BI_W]];
    end

    always_ff @(posedge clk) begin
        if (rst || redirect) begin
            f0_off <= redirect_pc[3:0];
            off <= {1'b0, redirect_pc[3:0]};
            f1_valid <= 1'b0;
            f2_valid <= 1'b0;
            fq_head <= 2'd0;
            fq_tail <= 2'd0;
            fq_count <= 3'd0;
            stopped <= 1'b0;
            valid <= 3'd0;
        end else begin
            f1_valid <= issue;
            if (issue) f0_off <= f0_mark.taken ? f0_mark.target[3:0] : 4'd0;
            f2_valid <= f1_valid;
            if (push) fq_tail <= fq_tail + 2'd1;
            if (pop) fq_head <= fq_head + 2'd1;
            fq_count <= fq_count + 3'(push) - 3'(pop);
            if (out_free) begin
                valid <= x_valid;
                if (x_valid[0]) begin
                    off <= {1'b0, pop && fq[fq_head].mark.taken ? fq[fq_head].mark.target[3:0] : x_next[3:0]};
                    for (int k = 0; k < 3; k++)
                        if (x_valid[k] && fq[fq_head].fault[s[k][3:0]]) stopped <= 1'b1;
                end
            end
        end
    end

    // data: written whatever the redirect (the valid bits above drop it), so
    // the redirect only drives the control registers (timing)
    always_ff @(posedge clk) begin
        f1_pc <= pc_f;
        f1_bytes <= ic_bytes;
        f1_mark <= f0_mark;
        f2_pc <= f1_pc;
        f2_bytes <= f1_bytes;
        f2_mark <= f1_mark;
        if (push) begin
            logic [15:0][4:0] nx;
            for (int i = 0; i < 16; i++) nx[i] = 5'(i) + 5'(pd_len[i]);
            fq[fq_tail] <= {f2_pc, f2_bytes, pd_len, pd_npfx, nx, pd_fault, f2_mark};   // block_t order
        end
        if (out_free)
            for (int k = 0; k < 3; k++) begin
                bytes[k] <= fq[fq_head].bytes[8*s[k][3:0] +: 8*15];
                // blocks are 16-byte aligned: EIP = {pc[31:4], offset}
                eip[k] <= {fq[fq_head].pc[31:4], s[k][3:0]};
                next[k] <= fq[fq_head].mark.taken && last[k] ? fq[fq_head].mark.target
                           : {fq[fq_head].pc[31:4] + 28'(fq[fq_head].nx[s[k][3:0]][4]),
                              fq[fq_head].nx[s[k][3:0]][3:0]};
                len[k] <= fq[fq_head].len[s[k][3:0]];
                npfx[k] <= fq[fq_head].npfx[s[k][3:0]];
                fault[k] <= fq[fq_head].fault[s[k][3:0]];
            end
    end

    // BTB update registered first: off the decode -> redirect path
    logic        bu_we, bu_set;
    logic [31:0] bu_pc, bu_target;
    always_ff @(posedge clk) begin
        bu_we <= btb_we && !rst;
        bu_set <= btb_set;
        bu_pc <= btb_pc;
        bu_target <= btb_target;
        // a clear does not check the tag (one RAM port): P clears a branch
        // the frontend just followed, so the entry is almost always its own
        if (bu_we)
            btb[bu_pc[4 +: BI_W]] <= {bu_set, bu_pc[31:4+BI_W], bu_pc[3:0], bu_target};   // btb_t order
    end
endmodule
