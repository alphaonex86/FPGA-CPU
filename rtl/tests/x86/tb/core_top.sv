// M2 testbench top: x86_core with a 1 MB memory loaded from +image=<hex> at
// 0x1000 behind a line port of +mem_lat=<cycles> read latency (default
// 10; writes posted, one read in flight), writing the retire trace (one line per x86
// instruction, x86_trace_check format) to +trace=<file>; +debug prints the
// frontend redirects, the extracted instructions, mul/div starts and results
// and the retired uops; +stats a cycle breakdown at the end.
module core_top (
    input  logic clk,
    input  logic rst,
    output logic halted,
    output logic illegal,
    output logic [31:0] cycles,
    output logic [31:0] insns
);
    import x86_pkg::*;
    localparam int MEM = 1 << 20;

    logic [7:0]  mem [MEM];
    logic        mem_req, mem_we, mem_ready, mem_rvalid, rd_pend;
    logic [31:5] mem_addr, rd_line;
    logic [255:0] mem_wdata, mem_rdata;
    int          mem_lat, rd_cnt;
    logic [2:0]  ret_valid, ret_eop, ret_wdst, ret_wflags;
    logic [2:0][31:0] ret_next_eip, ret_value;
    logic [2:0][3:0]  ret_dst;
    flags_t [2:0]     ret_flags;
    logic [31:0] regs [8];
    flags_t      flags;
    int          trace;
    logic        debug, stats;
    // +stats: cycles that retire nothing (ROB empty / head not done), uop
    // queue empty, decode redirects, retire flushes
    logic [31:0] st_empty, st_wait, st_uq_empty, st_dec_redir, st_flush;
    logic [31:0] st_wait_kind [8];   // head waits by the head uop kind (kind_t)
    logic [31:0] st_dr [4];          // decode redirects: not followed, falsely taken, target, cut
    logic [31:0] st_mp_wait, st_refill;   // flushing branch: result -> retire; flush -> next retire
    logic [31:0] st_fl [6];               // flushes: P-predicted Jcc, indirect, RET, other branch, K_DF, store to code
    logic [31:0] st_skew, st_alu3, st_mem2, st_replay, st_replay_md;   // issue contention
    logic [31:0] st_miss, st_wb;              // L2 misses, writebacks
    logic [31:0] st_imiss, st_dmiss, st_dwb;  // L1I, L1D misses, L1D writebacks
    logic [31:0] mp_cycle [ROB_N];
    logic        ind [ROB_N];       // the ROB entry is an indirect branch (RET: predicted taken)
    logic        refill;
    logic [31:0] st_x [4], st_rn [4];   // instructions extracted, uops renamed per cycle

    x86_core core (.clk(clk), .rst(rst), .reset_eip(32'h1000),
                   .mem_req(mem_req), .mem_we(mem_we), .mem_addr(mem_addr), .mem_wdata(mem_wdata),
                   .mem_ready(mem_ready), .mem_rvalid(mem_rvalid), .mem_rdata(mem_rdata),
                   .ret_valid(ret_valid), .ret_eop(ret_eop), .ret_next_eip(ret_next_eip),
                   .ret_wdst(ret_wdst), .ret_dst(ret_dst), .ret_value(ret_value),
                   .ret_wflags(ret_wflags), .ret_flags(ret_flags),
                   .halted(halted), .illegal(illegal));

    always_comb begin
        for (int i = 0; i < 32; i++) mem_rdata[8*i +: 8] = mem[20'({rd_line, 5'd0} + 32'(i))];
    end
    assign mem_ready = !rd_pend;
    assign mem_rvalid = rd_pend && rd_cnt == 0;

    initial begin
        string image, tname;
        for (int i = 0; i < MEM; i++) mem[i] = 8'h00;
        if (!$value$plusargs("image=%s", image) || !$value$plusargs("trace=%s", tname)) begin
            $display("usage: +image=<hex> +trace=<file>");
            $finish;
        end
        $readmemh(image, mem, 32'h1000);
        debug = $test$plusargs("debug");
        stats = $test$plusargs("stats");
        if (!$value$plusargs("mem_lat=%d", mem_lat)) mem_lat = 10;
        if (mem_lat < 1) begin
            $display("+mem_lat must be >= 1");
            $finish;
        end
        trace = $fopen(tname, "w");
        if (trace == 0) begin
            $display("cannot write %s", tname);
            $finish;
        end
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            for (int r = 0; r < 8; r++) regs[r] <= 32'd0;
            regs[4] <= 32'h0010_0000;
            flags <= '0;
            cycles <= 32'd0;
            insns <= 32'd0;
            {st_empty, st_wait, st_uq_empty, st_dec_redir, st_flush, st_mp_wait, st_refill} <= '0;
            {st_skew, st_alu3, st_mem2, st_replay, st_replay_md, st_miss, st_wb} <= '0;
            {st_imiss, st_dmiss, st_dwb} <= '0;
            rd_pend <= 1'b0;
            refill <= 1'b0;
            for (int i = 0; i < 6; i++) st_fl[i] <= 32'd0;
            for (int i = 0; i < 8; i++) st_wait_kind[i] <= 32'd0;
            for (int i = 0; i < 4; i++) st_dr[i] <= 32'd0;
            for (int i = 0; i < 4; i++) {st_x[i], st_rn[i]} <= '0;
        end else begin
            logic [31:0] r [8];
            flags_t      f;
            logic [31:0] done;
            r = regs;
            done = insns;
            f = flags;
            cycles <= cycles + 32'd1;
            if (ret_valid == 3'd0 && !halted) begin
                if (core.rob_count == '0) st_empty <= st_empty + 32'd1;
                else begin
                    st_wait <= st_wait + 32'd1;
                    st_wait_kind[core.rob[core.rob_head].kind] <= st_wait_kind[core.rob[core.rob_head].kind] + 32'd1;
                end
            end
            if (core.uq_count == '0) st_uq_empty <= st_uq_empty + 32'd1;
            if (core.fe_redirect && !core.flush) begin
                int c;
                logic ft;
                ft = core.p_next[core.p_btb_k] != core.p_seq[core.p_btb_k];
                c = !core.p_btb ? 3 : !ft ? 0 : !core.p_dir[core.p_btb_k] ? 1 : 2;
                st_dec_redir <= st_dec_redir + 32'd1;
                st_dr[c] <= st_dr[c] + 32'd1;
            end
            if (core.flush) st_flush <= st_flush + 32'd1;
            if (core.fe.out_free && !core.fe_redirect && !core.flush)
                st_x[$countones(core.fe.x_valid)] <= st_x[$countones(core.fe.x_valid)] + 32'd1;
            st_rn[core.rn_n] <= st_rn[core.rn_n] + 32'd1;
            begin
                int n0, n1, n2;
                n0 = $countones(core.req[0]);
                n1 = $countones(core.req[1]);
                n2 = $countones(core.req[2]);
                if (n0 >= 2 && n1 == 0 || n1 >= 2 && n0 == 0) st_skew <= st_skew + 32'd1;
                if (n0 + n1 >= 3 && n0 > 0 && n1 > 0) st_alu3 <= st_alu3 + 32'd1;
                if (n2 >= 2) st_mem2 <= st_mem2 + 32'd1;
            end
            if (core.am_valid && !core.m_ok) begin
                st_replay <= st_replay + 32'd1;
                if (core.md_done) st_replay_md <= st_replay_md + 32'd1;
            end
            if (!core.flush)
                for (int k = 0; k < 3; k++)
                    if (2'(k) < core.rn_n) ind[core.rn[k].tag] <= core.rn[k].u.kind == K_BR && core.rn[k].u.indirect;
            for (int p = 0; p < core.NW; p++)
                if (core.wb_valid[p] && core.wb_mispred[p]) mp_cycle[core.wb_tag[p]] <= cycles;
            if (core.r_flush) begin
                int c;
                logic [TAG_W-1:0] t;
                t = core.rob_head + TAG_W'(core.r_n - 2'd1);
                st_mp_wait <= st_mp_wait + cycles - mp_cycle[t];
                c = core.rob[t].kind == K_DF ? 4 : !(core.rob[t].kind == K_BR && core.rob[t].mispred) ? 5
                  : core.rob[t].bp_jcc ? 0 : ind[t] ? (core.rob[t].bp_taken ? 2 : 1) : 3;
                st_fl[c] <= st_fl[c] + 32'd1;
            end
            if (core.flush) refill <= 1'b1;
            else if (ret_valid != 3'd0) refill <= 1'b0;
            if (refill && ret_valid == 3'd0) st_refill <= st_refill + 32'd1;
            if (debug) begin
                if (core.fe_redirect) $display("%0d redirect %08x", cycles, core.fe_redirect_pc);
                for (int k = 0; k < 3; k++)
                    if (core.x_valid[k] && core.p_load)
                        $display("%0d decode %08x len %0d", cycles, core.x_eip[k], core.x_len[k]);
                if (core.ix_valid[3])
                    $display("%0d md start op %0d tag %0d a %08x b %08x c %08x", cycles, core.xr[3].u.aop,
                             core.xr[3].tag, core.xr[3].src[0].value, core.u_md.b, core.u_md.c);
                if (core.md_done)
                    $display("%0d md done tag %0d value %08x", cycles, core.md_tag, core.md_value);
                for (int k = 0; k < 3; k++)
                    if (ret_valid[k])
                        $display("%0d retire eop %0d next %08x dst %0d=%08x", cycles, ret_eop[k],
                                 ret_next_eip[k], ret_wdst[k] ? 32'(ret_dst[k]) : -1, ret_value[k]);
            end
            if (core.im_ready) st_imiss <= st_imiss + 32'd1;
            if (core.dm_req && core.dm_ready && !core.dm_we) st_dmiss <= st_dmiss + 32'd1;
            if (core.dm_req && core.dm_ready && core.dm_we) st_dwb <= st_dwb + 32'd1;
            if (mem_rvalid) rd_pend <= 1'b0;
            else if (rd_pend) rd_cnt <= rd_cnt - 1;
            if (mem_req && mem_ready) begin
                if (mem_we) begin
                    for (int i = 0; i < 32; i++) mem[20'({mem_addr, 5'd0} + 32'(i))] <= mem_wdata[8*i +: 8];
                    st_wb <= st_wb + 32'd1;
                end else begin
                    rd_pend <= 1'b1;
                    rd_cnt <= mem_lat - 1;
                    rd_line <= mem_addr;
                    st_miss <= st_miss + 32'd1;
                end
            end
            for (int k = 0; k < 3; k++)
                if (ret_valid[k]) begin
                    if (ret_wdst[k] && ret_dst[k] < 4'd8) r[ret_dst[k][2:0]] = ret_value[k];
                    if (ret_wflags[k]) f = ret_flags[k];
                    if (ret_eop[k] && core.rob[core.rob_head + 5'(k)].kind != K_HLT
                        && core.rob[core.rob_head + 5'(k)].kind != K_ILL) begin
                        $fdisplay(trace, "%08x %08x %08x %08x %08x %08x %08x %08x %08x %08x",
                                  ret_next_eip[k], r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7],
                                  eflags(f));
                        done = done + 32'd1;
                    end
                end
            regs <= r;
            flags <= f;
            insns <= done;
        end
    end

    final begin
        $fclose(trace);
        if (stats)
            $display("stats: per cycle: extracted 0/1/2/3 %0d %0d %0d %0d (output free), renamed 0/1/2/3 %0d %0d %0d %0d",
                     st_x[0], st_x[1], st_x[2], st_x[3], st_rn[0], st_rn[1], st_rn[2], st_rn[3]);
        if (stats)
            $display("stats: retire 0: ROB empty %0d, head waits %0d; uop queue empty %0d; decode redirects %0d; flushes %0d",
                     st_empty, st_wait, st_uq_empty, st_dec_redir, st_flush);
        if (stats)
            $display("stats: head waits by kind: ALU %0d LD %0d ST %0d BR %0d MD %0d",
                     st_wait_kind[K_ALU], st_wait_kind[K_LD], st_wait_kind[K_ST], st_wait_kind[K_BR], st_wait_kind[K_MD]);
        if (stats)
            $display("stats: decode redirects: taken not followed %0d, falsely taken %0d, target %0d, cut %0d",
                     st_dr[0], st_dr[1], st_dr[2], st_dr[3]);
        if (stats)
            $display("stats: flushing branch result -> retire %0d cycles, flush -> next retire %0d cycles",
                     st_mp_wait, st_refill);
        if (stats)
            $display("stats: issue: ALU ready on one port only (>= 2) %0d, >= 3 ALU ready on both %0d, >= 2 memory ready %0d; memory replays %0d (mul/div bus %0d)",
                     st_skew, st_alu3, st_mem2, st_replay, st_replay_md);
        if (stats)
            $display("stats: misses: L1I %0d, L1D %0d (writebacks %0d), L2 %0d (writebacks %0d; memory read latency %0d)",
                     st_imiss, st_dmiss, st_dwb, st_miss, st_wb, mem_lat);
        if (stats)
            $display("stats: flushes: Jcc %0d, indirect %0d, RET %0d, other branch %0d, DF %0d, store to code %0d",
                     st_fl[0], st_fl[1], st_fl[2], st_fl[3], st_fl[4], st_fl[5]);
    end
endmodule
