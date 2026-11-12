// Uncached accesses (plan/x86_core.md M5): exact size, in order, through the bus unit's
// single-cycle port. UC: the VGA window A0000-BFFFF, and the 64 KB regions a memory line came from
// without KEN# (learn; UC_N of them, the oldest forgotten: it is learned again by one line read).
// A line in the caches is cacheable by construction (L1 / L2 never keep one without KEN#), so the
// table only has to answer for misses; a region that turns cacheable stays UC until reset or a flush.
// - A load: the core replays it until it is the ROB head with every older store drained (l_head);
//   then one single cycle per dword it touches fills a one-entry buffer, and the load forwards from
//   it (l_hit, again only as the head: a younger load at the same address must not take it). The
//   buffer is spent when the head retires.
// - A store: the retired store queue head, as one single write per dword it touches (s_done).
module x86_uc
    import x86_pkg::*;
#(
    parameter int UC_N = 8
) (
    input  logic         clk,
    input  logic         rst,
    input  logic         forget,      // a flush: the regions are learned again
    input  logic         learn,       // a memory line read came without KEN#
    input  logic [31:16] learn_region,
    // the load in A
    input  logic [31:0]  l_addr,
    input  logic [1:0]   l_size,
    input  logic         l_go,        // an uncached load, the ROB head, older stores drained
    output logic         l_uc,
    output logic         l_hit,
    output logic [31:0]  l_data,
    input  logic         retire,      // the ROB head retired
    // the store queue head
    input  logic         s_valid,
    input  logic [31:0]  s_addr,
    input  logic [1:0]   s_size,
    input  logic [31:0]  s_data,
    output logic         s_uc,
    output logic         s_done,
    // bus unit single-cycle port
    output logic         sc_req,
    output logic [2:0]   sc_status,   // {M/IO#, D/C#, W/R#}
    output logic [31:2]  sc_addr,
    output logic [3:0]   sc_be,       // active high
    output logic [31:0]  sc_wdata,
    input  logic         sc_ready,
    input  logic         sc_done,
    input  logic [31:0]  sc_rdata
);
    logic [UC_N-1:0]        tab_v;
    logic [UC_N-1:0][15:0]  tab;
    logic [$clog2(UC_N)-1:0] tab_rr;
    function automatic logic uc(input logic [31:0] a);
        logic u;
        u = a[31:17] == 15'h0005;
        for (int i = 0; i < UC_N; i++) if (tab_v[i] && tab[i] == a[31:16]) u = 1'b1;
        return u;
    endfunction
    function automatic logic [7:0] bmask(input logic [1:0] a, input logic [1:0] sz);
        return (sz == SZ8 ? 8'h1 : sz == SZ16 ? 8'h3 : 8'hF) << a;
    endfunction

    typedef enum logic [1:0] {U_IDLE, U_REQ, U_WAIT} st_t;
    st_t         st;
    logic        u_we, second;    // a store; the access's second dword
    logic [31:0] u_addr;
    logic [7:0]  u_m;             // byte mask over the two dwords
    logic [63:0] u_win;           // store data placed / load data gathered
    logic        buf_valid;
    logic [31:0] buf_addr;
    logic [1:0]  buf_size;

    assign l_uc  = uc(l_addr);
    assign s_uc  = s_valid && uc(s_addr);
    assign l_hit = l_go && buf_valid && buf_addr == l_addr && buf_size == l_size;
    assign l_data = 32'(u_win >> (8 * buf_addr[1:0]));

    assign sc_req    = st == U_REQ;
    assign sc_status = {2'b11, u_we};
    assign sc_addr   = second ? u_addr[31:2] + 30'd1 : u_addr[31:2];
    assign sc_be     = second ? u_m[7:4] : u_m[3:0];
    assign sc_wdata  = second ? u_win[63:32] : u_win[31:0];

    always_ff @(posedge clk) begin
        s_done <= 1'b0;
        if (learn && !uc({learn_region, 16'd0})) begin
            tab_v[tab_rr] <= 1'b1;
            tab[tab_rr] <= learn_region;
            tab_rr <= tab_rr + 1'd1;
        end
        if (forget) tab_v <= '0;
        if (rst) begin
            st <= U_IDLE;
            buf_valid <= 1'b0;
            tab_v <= '0;
            tab_rr <= '0;
        end else begin
            if (retire) buf_valid <= 1'b0;
            unique case (st)
                U_IDLE:
                    if (l_go && !buf_valid) begin
                        u_we <= 1'b0;
                        u_addr <= l_addr;
                        u_m <= bmask(l_addr[1:0], l_size);
                        second <= 1'b0;
                        buf_addr <= l_addr;
                        buf_size <= l_size;
                        st <= U_REQ;
                    end else if (s_uc && !s_done) begin
                        u_we <= 1'b1;
                        u_addr <= s_addr;
                        u_m <= bmask(s_addr[1:0], s_size);
                        second <= 1'b0;
                        u_win <= 64'(s_data) << (8 * s_addr[1:0]);
                        st <= U_REQ;
                    end
                U_REQ: if (sc_ready) st <= U_WAIT;
                U_WAIT:
                    if (sc_done) begin
                        if (!u_we) begin
                            if (second) u_win[63:32] <= sc_rdata;
                            else u_win[31:0] <= sc_rdata;
                        end
                        if (!second && u_m[7:4] != 4'd0) begin
                            second <= 1'b1;
                            st <= U_REQ;
                        end else begin
                            st <= U_IDLE;
                            if (u_we) s_done <= 1'b1;
                            else buf_valid <= 1'b1;
                        end
                    end
                default: st <= U_IDLE;
            endcase
        end
    end
endmodule
