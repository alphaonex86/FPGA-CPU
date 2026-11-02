// L1 instruction cache (plan/x86_core.md M3): 16 KB, 4-way, 32-byte lines,
// one miss in flight. Two banks, half 0 and half 1 of each line; the RAMs
// (tags and data, a copy per bank) are read with pc_n like the BTB, so in
// F0 the 32 bytes from pc_f are the block's half and the other one, of the
// next line when the block is half 1. A hit needs both: an instruction
// may run past its block. A miss fills the block's own half first.
module x86_l1i
    import x86_pkg::*;
(
    input  logic            clk,
    input  logic            rst,
    input  logic [31:4]     pc_n,      // the next fetch block: RAMs read with it
    input  logic [31:4]     pc_f,      // the fetch block (pc_n a cycle ago)
    output logic            hit,       // bytes: the 30 bytes at pc_f
    output logic [8*30-1:0] bytes,
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

    logic                        fill;     // line f_line into way f_way
    logic [31:5]                 f_line;
    logic [1:0]                  f_way;
    logic [1:0][SW-1:0]          n_set;
    tg_t  [1:0][WAYS-1:0]        t_rd;
    logic [1:0][WAYS-1:0][127:0] d_rd;
    always_comb
        for (int b = 0; b < 2; b++) begin
            logic [31:5] l;
            l = bank_line(pc_n, b);
            n_set[b] = l[5 +: SW];
        end
    genvar gb, gw;
    generate for (gb = 0; gb < 2; gb = gb + 1) begin : bk
        for (gw = 0; gw < WAYS; gw = gw + 1) begin : wy
            (* ramstyle = "no_rw_check" *) tg_t t [SETS];
            (* ramstyle = "no_rw_check" *) logic [127:0] d [SETS];
            initial for (int i = 0; i < SETS; i++) t[i] = '0;
            always_ff @(posedge clk) begin
                if (fill && f_way == 2'(gw)) begin
                    t[f_line[5 +: SW]] <= '{v: 1'b1, tag: f_line[31 -: TW]};
                    d[f_line[5 +: SW]] <= mem_rdata[128 * gb +: 128];
                end
                t_rd[gb][gw] <= t[n_set[gb]];
                d_rd[gb][gw] <= d[n_set[gb]];
            end
        end
    end endgenerate

    // F0: tag compare and way select
    logic              filled;     // the RAMs were read while the fill wrote them
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
        hit = b_hit == 2'b11 && !filled;
        bytes = 240'(pc_f[4] ? {b_data[0], b_data[1]} : {b_data[1], b_data[0]});
    end

    function automatic logic [1:0] victim(input tg_t [WAYS-1:0] w, input logic [1:0] r);
        for (int i = WAYS - 1; i >= 0; i--) if (!w[i].v) return 2'(i);
        return r;
    endfunction

    typedef enum logic [1:0] {S_IDLE, S_REQ, S_WAIT} st_t;
    st_t        st;
    logic [1:0] rr;              // replacement when no way is free
    assign fill = st == S_WAIT && mem_rvalid;
    always_ff @(posedge clk) begin
        if (rst) begin
            st <= S_IDLE;
            filled <= 1'b0;
            rr <= 2'd0;
        end else begin
            filled <= fill;
            case (st)
                S_IDLE:
                    if (b_hit != 2'b11 && !filled) begin
                        logic mb;
                        mb = b_hit[pc_f[4]] ? !pc_f[4] : pc_f[4];
                        f_line <= bank_line(pc_f, int'(mb));
                        f_way <= victim(t_rd[mb], rr);
                        rr <= rr + 2'd1;
                        st <= S_REQ;
                    end
                S_REQ: if (mem_ready) st <= S_WAIT;
                S_WAIT: if (mem_rvalid) st <= S_IDLE;
                default: st <= S_IDLE;
            endcase
        end
    end
    assign mem_req = st == S_REQ;
    assign mem_addr = f_line;
endmodule
