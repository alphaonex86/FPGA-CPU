// L2 (plan/x86_core.md M3): unified, KB kilobytes (default 256), 4-way,
// 32-byte lines, write-back, one request at a time, between the L1s'
// line port and memory (same port shape on both sides).
// A read hit answers 2 cycles after it is taken (tags, then data); a line
// write (an L1D write-back) allocates without reading memory. A miss
// writes back a dirty victim, then reads the line (reads only).
module x86_l2 #(
    parameter int KB = 256
) (
    input  logic          clk,
    input  logic          rst,
    // L1 side
    input  logic          req,
    input  logic          we,
    input  logic [31:5]   addr,
    input  logic [255:0]  wdata,
    output logic          ready,      // takes the request this cycle
    output logic          rvalid,
    output logic [255:0]  rdata,
    // memory side
    output logic          mem_req,
    output logic          mem_we,
    output logic [31:5]   mem_addr,
    output logic [255:0]  mem_wdata,
    input  logic          mem_ready,
    input  logic          mem_rvalid,
    input  logic [255:0]  mem_rdata
);
    localparam int WAYS = 4, SETS = KB * 1024 / 32 / WAYS, SW = $clog2(SETS), TW = 27 - SW;

    typedef struct packed {
        logic          v, d;
        logic [TW-1:0] tag;
    } tg_t;

    typedef enum logic [2:0] {S_IDLE, S_TAG, S_DATA, S_VRD, S_WB, S_MREQ, S_MWAIT} st_t;
    st_t           st;
    logic          r_we;           // the request taken
    logic [31:5]   r_addr;
    logic [255:0]  r_wdata;
    logic [1:0]    r_way;          // hit way, else victim (after S_TAG)
    logic [1:0]    w_way;          // the way written / read this cycle
    logic [TW-1:0] v_tag;
    logic [1:0]    rr;             // replacement when no way is free

    // tags (a RAM per way) and data ({set, way} rows), registered reads
    logic [SW-1:0]           t_ra;
    tg_t  [WAYS-1:0]         t_rd;
    logic                    t_we;
    tg_t                     t_wd;
    logic                    d_we;
    logic [SW+1:0]           d_ra;
    logic [255:0]            d_wd, d_rd;
    assign t_ra = st == S_IDLE ? addr[5 +: SW] : r_addr[5 +: SW];
    genvar gw;
    generate for (gw = 0; gw < WAYS; gw = gw + 1) begin : tw
        (* ramstyle = "no_rw_check" *) tg_t t [SETS];
        initial for (int i = 0; i < SETS; i++) t[i] = '0;
        always_ff @(posedge clk) begin
            if (t_we && w_way == 2'(gw)) t[r_addr[5 +: SW]] <= t_wd;
            t_rd[gw] <= t[t_ra];
        end
    end endgenerate
    (* ramstyle = "no_rw_check" *) logic [255:0] data [SETS * WAYS];
    always_ff @(posedge clk) begin
        if (d_we) data[{r_addr[5 +: SW], w_way}] <= d_wd;
        d_rd <= data[d_ra];
    end

    function automatic logic [1:0] victim(input tg_t [WAYS-1:0] w, input logic [1:0] r);
        for (int i = WAYS - 1; i >= 0; i--) if (!w[i].v) return 2'(i);
        return r;
    endfunction

    // S_TAG: hit way
    logic       hit;
    logic [1:0] hway;
    always_comb begin
        hit = 1'b0;
        hway = 2'd0;
        for (int w = 0; w < WAYS; w++)
            if (t_rd[w].v && t_rd[w].tag == r_addr[31 -: TW]) begin
                hit = 1'b1;
                hway = 2'(w);
            end
    end

    // RAM writes: a line write (hit or allocate), a fill
    always_comb begin
        logic wr, fill;
        logic [1:0] vw;
        vw = victim(t_rd, rr);
        w_way = st != S_TAG ? r_way : hit ? hway : vw;
        wr = st == S_TAG && r_we && (hit || !(t_rd[vw].v && t_rd[vw].d))
             || st == S_WB && mem_ready && r_we;
        fill = st == S_MWAIT && mem_rvalid;
        d_we = wr || fill;
        d_wd = fill ? mem_rdata : r_wdata;
        t_we = d_we;
        t_wd = '{v: 1'b1, d: wr, tag: r_addr[31 -: TW]};
        d_ra = {r_addr[5 +: SW], w_way};
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            st <= S_IDLE;
            rr <= 2'd0;
        end else
            case (st)
                S_IDLE:
                    if (req) begin
                        r_we <= we;
                        r_addr <= addr;
                        r_wdata <= wdata;
                        st <= S_TAG;
                    end
                S_TAG:
                    if (hit) begin
                        r_way <= hway;
                        st <= r_we ? S_IDLE : S_DATA;
                    end else begin
                        logic [1:0] w;
                        w = victim(t_rd, rr);
                        r_way <= w;
                        v_tag <= t_rd[w].tag;
                        rr <= rr + 2'd1;
                        st <= t_rd[w].v && t_rd[w].d ? S_VRD : r_we ? S_IDLE : S_MREQ;
                    end
                S_DATA: st <= S_IDLE;
                S_VRD: st <= S_WB;      // d_ra: the victim, d_rd next cycle
                S_WB: if (mem_ready) st <= r_we ? S_IDLE : S_MREQ;
                S_MREQ: if (mem_ready) st <= S_MWAIT;
                S_MWAIT: if (mem_rvalid) st <= S_IDLE;
                default: st <= S_IDLE;
            endcase
    end

    assign ready = st == S_IDLE;
    assign rvalid = st == S_DATA || st == S_MWAIT && mem_rvalid;
    assign rdata = st == S_DATA ? d_rd : mem_rdata;
    assign mem_req = st == S_WB || st == S_MREQ;
    assign mem_we = st == S_WB;
    assign mem_addr = st == S_WB ? {v_tag, r_addr[5 +: SW]} : r_addr;
    assign mem_wdata = d_rd;
endmodule
