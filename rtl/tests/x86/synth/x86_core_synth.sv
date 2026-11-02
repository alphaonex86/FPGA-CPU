// Area/fmax harness for synth_cv.sh: x86_core with every memory port behind
// a register; the retire trace is XOR-folded so synthesis keeps it.
module x86_core_synth (
  input  wire clk,
  input  wire rst_in,
  input  wire [239:0] fetch_data_in,
  input  wire [255:0] mem_rdata_in,
  input  wire mem_ready_in,
  input  wire mem_rvalid_in,
  output wire [31:0] fetch_addr_out,
  output wire [284:0] mem_out,
  output wire [33:0] trace_out
);
    import x86_pkg::*;
    logic             rst, halted, illegal;
    logic [239:0]     fetch_data;
    logic [31:0]      fetch_addr;
    logic             mem_req, mem_we, mem_ready, mem_rvalid;
    logic [31:5]      mem_addr;
    logic [255:0]     mem_wdata, mem_rdata;
    logic [2:0]       ret_valid, ret_eop, ret_wdst, ret_wflags;
    logic [2:0][31:0] ret_next_eip, ret_value;
    logic [2:0][3:0]  ret_dst;
    flags_t [2:0]     ret_flags;
    logic [31:0]      fetch_addr_q, fold;
    logic [284:0]     mem_q;
    logic [33:0]      trace_q;

    x86_core core (.clk(clk), .rst(rst), .reset_eip(32'h000F_FFF0),
                   .fetch_addr(fetch_addr), .fetch_data(fetch_data),
                   .mem_req(mem_req), .mem_we(mem_we), .mem_addr(mem_addr), .mem_wdata(mem_wdata),
                   .mem_ready(mem_ready), .mem_rvalid(mem_rvalid), .mem_rdata(mem_rdata),
                   .ret_valid(ret_valid), .ret_eop(ret_eop), .ret_next_eip(ret_next_eip),
                   .ret_wdst(ret_wdst), .ret_dst(ret_dst), .ret_value(ret_value),
                   .ret_wflags(ret_wflags), .ret_flags(ret_flags),
                   .halted(halted), .illegal(illegal));

    always_comb begin
        fold = {23'd0, ret_valid, ret_eop, ret_wdst};
        for (int k = 0; k < 3; k++)
            fold = fold ^ ret_next_eip[k] ^ ret_value[k] ^ {21'd0, ret_dst[k], ret_wflags[k], ret_flags[k]};
    end

    always_ff @(posedge clk) begin
        rst <= rst_in;
        fetch_data <= fetch_data_in;
        mem_rdata <= mem_rdata_in;
        mem_ready <= mem_ready_in;
        mem_rvalid <= mem_rvalid_in;
        fetch_addr_q <= fetch_addr;
        mem_q <= {mem_req, mem_we, mem_addr, mem_wdata};
        trace_q <= {halted, illegal, fold};
    end
    assign fetch_addr_out = fetch_addr_q;
    assign mem_out = mem_q;
    assign trace_out = trace_q;
endmodule
