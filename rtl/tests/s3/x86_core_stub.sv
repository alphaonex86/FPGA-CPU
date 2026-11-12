// Stand-in for x86_core in a bus-only Quartus build (rtl/s3/build.sh <out> bus): line reads and
// writes from a counter and an LFSR, every read bit folded back so nothing is optimised away.
module x86_core (
    input  logic         clk,
    input  logic         rst,
    input  logic [31:0]  reset_eip,
    input  logic         a20m,
    input  logic         cache_flush,
    input  logic         snoop,
    input  logic [31:4]  snoop_line,
    input  logic         snoop_inv,
    input  logic         enhanced,
    output logic         snoop_err,
    output logic         flush_done,
    output logic         mem_req,
    output logic         mem_we,
    output logic [31:5]  mem_addr,
    output logic [255:0] mem_wdata,
    input  logic         mem_ready,
    input  logic         mem_rvalid,
    input  logic [255:0] mem_rdata,
    input  logic         mem_cacheable,
    output logic         sc_req,
    output logic [2:0]   sc_status,
    output logic [31:2]  sc_addr,
    output logic [3:0]   sc_be,
    output logic [31:0]  sc_wdata,
    input  logic         sc_ready,
    input  logic         sc_done,
    input  logic [31:0]  sc_rdata,
    output logic [2:0]   ret_valid,
    output logic [2:0]   ret_eop,
    output logic [2:0][31:0] ret_next_eip,
    output logic [2:0]   ret_wdst,
    output logic [2:0][3:0] ret_dst,
    output logic [2:0][31:0] ret_value,
    output logic [2:0]   ret_wflags,
    output logic [2:0][6:0] ret_flags,
    output logic         halted,
    output logic         illegal
);
    logic busy;
    always_ff @(posedge clk) begin
        if (mem_req && mem_ready) begin
            mem_req <= 1'b0;
            busy    <= !mem_we;
        end
        if (mem_rvalid) begin
            busy      <= 1'b0;
            mem_wdata <= mem_wdata ^ mem_rdata ^ 256'(mem_cacheable);
        end
        if (!mem_req && !busy) begin
            mem_req   <= 1'b1;
            mem_we    <= mem_wdata[0];
            mem_addr  <= mem_addr + 27'd1 + mem_wdata[27:1] + sc_fold[26:0];
            mem_wdata <= {mem_wdata[254:0], mem_wdata[255] ^ mem_wdata[250] ^ mem_wdata[245] ^ mem_wdata[9]};
        end
        if (rst) begin
            mem_req   <= 1'b0;
            busy      <= 1'b0;
            mem_addr  <= reset_eip[31:5];
            mem_wdata <= 256'd1;
        end
    end
    // single cycles: one per line read, its read data folded into the next line's address
    logic [31:0] sc_fold;
    always_ff @(posedge clk) begin
        if (sc_req && sc_ready) sc_req <= 1'b0;
        if (mem_rvalid && !sc_req) begin
            sc_req    <= 1'b1;
            sc_status <= {2'b11, mem_rdata[3]};
            sc_addr   <= mem_rdata[31:2] ^ 30'(mem_addr);
            sc_be     <= mem_rdata[7:4] | 4'd1;
            sc_wdata  <= mem_rdata[63:32];
        end
        if (sc_done) sc_fold <= sc_fold ^ sc_rdata;
        if (rst) begin
            sc_req  <= 1'b0;
            sc_fold <= 32'd0;
        end
    end
    assign {ret_valid, ret_eop, ret_next_eip, ret_wdst, ret_dst, ret_value, ret_wflags, ret_flags, halted, illegal} = '0;
    assign snoop_err = snoop ^ snoop_inv ^ enhanced ^ ^snoop_line;   // keeps the bus unit's snoop outputs
    assign flush_done = cache_flush && mem_rvalid;                    // drives the flush acknowledge path
endmodule
