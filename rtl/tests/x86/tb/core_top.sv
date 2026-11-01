// M2 testbench top: x86_core with an ideal 1 MB memory loaded from
// +image=<hex> at 0x1000, writing the retire trace (one line per x86
// instruction, x86_trace_check format) to +trace=<file>; +debug prints the
// frontend redirects, the extracted instructions, mul/div starts and results
// and the retired uops.
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
    logic [31:0] fetch_addr, load_addr, load_data, store_addr, store_data;
    logic [8*30-1:0] fetch_data;
    logic        store_en;
    logic [1:0]  store_size;
    logic [2:0]  ret_valid, ret_eop, ret_wdst, ret_wflags;
    logic [2:0][31:0] ret_next_eip, ret_value;
    logic [2:0][3:0]  ret_dst;
    flags_t [2:0]     ret_flags;
    logic [31:0] regs [8];
    flags_t      flags;
    int          trace;
    logic        debug;

    x86_core core (.clk(clk), .rst(rst), .reset_eip(32'h1000),
                   .fetch_addr(fetch_addr), .fetch_data(fetch_data),
                   .load_addr(load_addr), .load_data(load_data),
                   .store_en(store_en), .store_addr(store_addr), .store_data(store_data),
                   .store_size(store_size),
                   .ret_valid(ret_valid), .ret_eop(ret_eop), .ret_next_eip(ret_next_eip),
                   .ret_wdst(ret_wdst), .ret_dst(ret_dst), .ret_value(ret_value),
                   .ret_wflags(ret_wflags), .ret_flags(ret_flags),
                   .halted(halted), .illegal(illegal));

    always_comb begin
        for (int i = 0; i < 30; i++) fetch_data[8*i +: 8] = mem[20'(fetch_addr + 32'(i))];
        for (int i = 0; i < 4; i++) load_data[8*i +: 8] = mem[20'(load_addr + 32'(i))];
    end

    initial begin
        string image, tname;
        for (int i = 0; i < MEM; i++) mem[i] = 8'h00;
        if (!$value$plusargs("image=%s", image) || !$value$plusargs("trace=%s", tname)) begin
            $display("usage: +image=<hex> +trace=<file>");
            $finish;
        end
        $readmemh(image, mem, 32'h1000);
        debug = $test$plusargs("debug");
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
        end else begin
            logic [31:0] r [8];
            flags_t      f;
            logic [31:0] done;
            r = regs;
            done = insns;
            f = flags;
            cycles <= cycles + 32'd1;
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
            if (store_en)
                for (int i = 0; i < 4; i++)
                    if (i < 1 << store_size) mem[20'(store_addr + 32'(i))] <= store_data[8*i +: 8];
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

    final $fclose(trace);
endmodule
