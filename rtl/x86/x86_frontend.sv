// Fetch + predecode + instruction extraction (plan/x86_core.md M2).
// F0 fetches the 16-byte block at pc_f plus the 14 bytes after it, F1/F2 run
// x86_predecode, F2 pushes the block into a 4-entry queue; extraction takes
// up to 3 instructions per cycle from the head block starting at offset
// off, into the output register read by the decoders. An instruction may
// run past its block: the window holds it whole.
module x86_frontend
    import x86_pkg::*;
(
    input  logic                  clk,
    input  logic                  rst,
    input  logic                  redirect,      // flush, continue at redirect_pc
    input  logic [31:0]           redirect_pc,
    input  logic                  take,          // decoders consume the output
    output logic [31:0]           fetch_addr,    // ideal memory: fetch_data is
    input  logic [8*30-1:0]       fetch_data,    // bytes fetch_addr.. this cycle
    output logic [2:0]            valid,
    output logic [2:0][8*15-1:0]  bytes,
    output logic [2:0][31:0]      eip,
    output logic [2:0][3:0]       len,
    output logic [2:0]            fault
);
    localparam int FQ_N = 4;

    typedef struct packed {
        logic [31:0]       pc;
        logic [8*30-1:0]   bytes;
        logic [15:0][3:0]  len;
        logic [15:0]       fault;
    } block_t;

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

    x86_predecode #(.N(16)) pd (.clk(clk), .bytes(f1_bytes), .d32(1'b1), .len(pd_len),
                                .npfx(pd_npfx), .map(pd_map), .fault(pd_fault));

    assign fetch_addr = pc_f;
    // blocks in F1, F2 and the queue never exceed its size
    assign issue = 3'(f1_valid) + 3'(f2_valid) + fq_count < 3'(FQ_N);
    assign push = f2_valid;
    assign out_free = valid == 3'd0 || take;

    // extraction from the head block
    always_comb begin
        block_t h;
        h = fq[fq_head];
        s[0] = off;
        s[1] = s[0] + 5'(h.len[s[0][3:0]]);
        s[2] = s[1][4] ? 5'd16 : s[1] + 5'(h.len[s[1][3:0]]);
        x_valid[0] = fq_count != 3'd0 && !stopped;
        x_valid[1] = x_valid[0] && !s[1][4] && !h.fault[s[0][3:0]];
        x_valid[2] = x_valid[1] && !s[2][4] && !h.fault[s[1][3:0]];
        x_next = !x_valid[1] ? s[1] : !x_valid[2] ? s[2] : s[2] + 5'(h.len[s[2][3:0]]);
    end
    assign pop = out_free && x_valid[0] && x_next[4];

    always_ff @(posedge clk) begin
        if (rst || redirect) begin
            pc_f <= {redirect_pc[31:4], 4'd0};
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
            f1_pc <= pc_f;
            f1_bytes <= fetch_data;
            if (issue) pc_f <= pc_f + 32'd16;
            f2_valid <= f1_valid;
            f2_pc <= f1_pc;
            f2_bytes <= f1_bytes;
            if (push) begin
                fq[fq_tail] <= {f2_pc, f2_bytes, pd_len, pd_fault};   // block_t order
                fq_tail <= fq_tail + 2'd1;
            end
            if (pop) fq_head <= fq_head + 2'd1;
            fq_count <= fq_count + 3'(push) - 3'(pop);
            if (out_free) begin
                valid <= x_valid;
                for (int k = 0; k < 3; k++) begin
                    bytes[k] <= fq[fq_head].bytes[8*s[k][3:0] +: 8*15];
                    eip[k] <= fq[fq_head].pc + 32'(s[k][3:0]);
                    len[k] <= fq[fq_head].len[s[k][3:0]];
                    fault[k] <= fq[fq_head].fault[s[k][3:0]];
                end
                if (x_valid[0]) begin
                    off <= {1'b0, x_next[3:0]};
                    for (int k = 0; k < 3; k++)
                        if (x_valid[k] && fq[fq_head].fault[s[k][3:0]]) stopped <= 1'b1;
                end
            end
        end
    end
endmodule
