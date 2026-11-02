// Fetch + predecode + instruction extraction (plan/x86_core.md M2).
// F0 fetches the 16-byte block at pc_f plus the 14 bytes after it from the
// L1I (x86_l1i, read with pc_n; a miss holds F0), F1/F2 run x86_predecode, F2
// pushes the block into a 4-entry queue; extraction takes up to 3
// instructions per cycle from the head block starting at offset off,
// continuing into the next block, into the output register read by the
// decoders; an instruction of more than 3 uops only goes first. An
// instruction may run past its block: the window holds it whole.
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
    output logic [31:4]           fetch_next,    // L1I: pc_n, pc_f
    output logic [31:4]           fetch_pc,
    input  logic                  ic_hit,        // ic_bytes: the 30 bytes at pc_f
    input  logic [8*30-1:0]       ic_bytes,
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
        logic [15:0]       fault, multi;
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
    logic [15:0]      pd_fault, pd_multi;
    block_t           fq [FQ_N];
    logic [1:0]       fq_head, fq_tail;
    logic [2:0]       fq_count;
    logic [4:0]       off;          // start offset in the head block, < 16
    logic             stopped;      // after a faulting instruction
    logic             issue, push, out_free;
    logic [1:0]       pops;         // blocks the extracted instructions end
    logic [2:0]       x_valid;
    logic [3:0]       x_off;        // offset after the last one, in its block
    logic [2:0]       blk;          // instruction k is in the head block's next one
    logic [2:0][3:0]  s;            // its offset there
    logic [2:0][4:0]  nx;           // the next start: s + len (bit 4: next block)
    logic [2:0]       last;         // instruction k ends its block
    assign fetch_next = pc_n[31:4];
    assign fetch_pc = pc_f[31:4];

    x86_predecode #(.N(16)) pd (.clk(clk), .bytes(f1_bytes), .d32(1'b1), .len(pd_len),
                                .npfx(pd_npfx), .map(pd_map), .fault(pd_fault), .multi(pd_multi));

    always_comb begin
        f0_mark.taken = bh.valid && bh.tag == pc_f[31:4+BI_W] && bh.off >= f0_off;
        f0_mark.moff = bh.off;
        f0_mark.target = bh.target;
    end
    // blocks in F1, F2 and the queue never exceed its size
    assign issue = ic_hit && 3'(f1_valid) + 3'(f2_valid) + fq_count < 3'(FQ_N);
    assign push = f2_valid;
    assign out_free = valid == 3'd0 || take;

    // the offset after instruction k in its block, or in the block after it
    // when it ends its block (taken: the target's)
    function automatic logic [3:0] after(input block_t h, input logic [3:0] o, input logic end_k);
        return end_k && h.mark.taken ? h.mark.target[3:0] : 4'(h.nx[o]);
    endfunction

    // extraction from the head block and the next one
    always_comb begin
        block_t h [2];
        logic [2:0] go;   // instruction k + 1 follows instruction k
        h[0] = fq[fq_head];
        h[1] = fq[fq_head + 2'd1];
        blk = '0;
        s = '0;
        s[0] = off[3:0];
        for (int k = 0; k < 3; k++) begin
            nx[k] = h[blk[k]].nx[s[k]];
            last[k] = h[blk[k]].mark.taken && s[k] >= h[blk[k]].mark.moff || nx[k][4];
            go[k] = !h[blk[k]].fault[s[k]] && (!last[k] || !blk[k] && fq_count >= 3'd2);
            if (k < 2) begin
                blk[k + 1] = blk[k] | last[k];
                s[k + 1] = after(h[blk[k]], s[k], last[k]);
                go[k] = go[k] && !h[blk[k + 1]].multi[s[k + 1]];
            end
        end
        x_valid[0] = fq_count != 3'd0 && !stopped;
        x_valid[1] = x_valid[0] && go[0];
        x_valid[2] = x_valid[1] && go[1];
        // the last valid one: the offset after it, the blocks done
        x_off = after(h[blk[0]], s[0], last[0]);
        pops = 2'(last[0]);
        for (int k = 1; k < 3; k++)
            if (x_valid[k]) begin
                x_off = after(h[blk[k]], s[k], last[k]);
                pops = 2'(blk[k]) + 2'(last[k]);
            end
        if (!out_free || !x_valid[0]) pops = 2'd0;
    end

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
            fq_head <= fq_head + pops;
            fq_count <= fq_count + 3'(push) - 3'(pops);
            if (out_free) begin
                valid <= x_valid;
                if (x_valid[0]) begin
                    off <= {1'b0, x_off};
                    for (int k = 0; k < 3; k++)
                        if (x_valid[k] && fq[fq_head + 2'(blk[k])].fault[s[k]]) stopped <= 1'b1;
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
            logic [15:0][4:0] pnx;
            for (int i = 0; i < 16; i++) pnx[i] = 5'(i) + 5'(pd_len[i]);
            fq[fq_tail] <= {f2_pc, f2_bytes, pd_len, pd_npfx, pnx, pd_fault, pd_multi, f2_mark};   // block_t order
        end
        if (out_free)
            for (int k = 0; k < 3; k++) begin
                block_t h;
                h = fq[fq_head + 2'(blk[k])];
                bytes[k] <= h.bytes[8*s[k] +: 8*15];
                // blocks are 16-byte aligned: EIP = {pc[31:4], offset}
                eip[k] <= {h.pc[31:4], s[k]};
                next[k] <= h.mark.taken && last[k] ? h.mark.target
                           : {h.pc[31:4] + 28'(nx[k][4]), nx[k][3:0]};
                len[k] <= h.len[s[k]];
                npfx[k] <= h.npfx[s[k]];
                fault[k] <= h.fault[s[k]];
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
