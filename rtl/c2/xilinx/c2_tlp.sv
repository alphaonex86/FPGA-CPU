// 7 Series PCIe IP (PG054, 64-bit AXI4-Stream, user_clk) <-> one BAR0
// request at a time (c2_req_sync). BAR0 is a 32-bit memory BAR: memory
// write TLPs of 2 DW (a 64-bit store) and memory reads of 1 or 2 DW are
// served; m_axis_rx_tready stays low while a request runs, so TLPs are
// taken strictly in order. Header fields as in the PCIe spec; a data DW
// carries its first byte in bits 31:24 (PG054 Figure 3-2), so data is
// byte-swapped into the little-endian bus value.
module c2_tlp (
    input  logic        clk,
    input  logic        rst,
    input  logic [63:0] rx_tdata,
    input  logic [7:0]  rx_tkeep,
    input  logic        rx_tlast,
    input  logic        rx_tvalid,
    output logic        rx_tready,
    input  logic [21:0] rx_tuser,
    output logic [63:0] tx_tdata,
    output logic [7:0]  tx_tkeep,
    output logic        tx_tlast,
    output logic        tx_tvalid,
    input  logic        tx_tready,
    input  logic [15:0] completer_id,     // {bus, device, function}
    // request (c2_req_sync)
    output logic        start,
    output logic        write,
    output logic [12:0] addr,
    output logic [63:0] wdata,
    input  logic        done,
    input  logic [63:0] rdata,
    output logic        err               // an unsupported BAR0 TLP (one clock)
);
    typedef enum logic [3:0] { H0, H1, D1, DROP, DECODE, BUSY, CPL0, CPL1, CPL2 } state_t;
    state_t state;

    logic [31:0] dw0, dw1, dw2, data0, data1;
    logic        bar0, extra_beats, ur;
    logic [63:0] result;

    function automatic logic [31:0] bswap(input logic [31:0] d);
        return {d[7:0], d[15:8], d[23:16], d[31:24]};
    endfunction

    wire [6:0] fmt_type = dw0[30:24];
    wire [9:0] len      = dw0[9:0];
    wire       is_mwr   = fmt_type == 7'b1000000;   // MWr, 3 DW header
    wire       is_mrd   = fmt_type == 7'b0000000;   // MRd, 3 DW header
    wire       is_msg   = fmt_type[4:3] == 2'b10;   // messages: ignored
    wire       be_full  = dw1[7:0] == (len == 10'd1 ? 8'h0f : 8'hff);

    assign rx_tready = state == H0 || state == H1 || state == D1 || state == DROP;

    // completion (CplD, or Cpl with status UR), 3 DW header:
    // beat 0 {DW1, DW0}, beat 1 {data 0, DW2}, beat 2 {-, data 1}
    wire [31:0] cpl_dw0 = {1'b0, ur ? 2'b00 : 2'b10, 5'b01010, 1'b0, dw0[22:20], 4'd0,   // fmt type TC
                           2'd0, dw0[13:12], 2'd0, ur ? 10'd0 : len};                    // attr length
    wire [31:0] cpl_dw1 = {completer_id, ur ? 3'b001 : 3'b000, 1'b0, len, 2'b00};
    wire [31:0] cpl_dw2 = {dw1[31:8], 1'b0, dw2[6:2], 2'b00};   // requester ID, tag, lower address

    assign tx_tvalid = state == CPL0 || state == CPL1 || state == CPL2;
    assign tx_tdata  = state == CPL0 ? {cpl_dw1, cpl_dw0}
                     : state == CPL1 ? {ur ? 32'd0 : bswap(result[31:0]), cpl_dw2}
                     : {32'd0, bswap(result[63:32])};
    assign tx_tkeep  = state == CPL2 || (state == CPL1 && ur) ? 8'h0f : 8'hff;
    assign tx_tlast  = state == CPL2 || (state == CPL1 && len != 10'd2);

    always_ff @(posedge clk) begin
        start <= 0;
        err   <= 0;
        if (rst)
            state <= H0;
        else case (state)
            H0: if (rx_tvalid) begin
                {dw1, dw0}  <= rx_tdata;
                bar0        <= rx_tuser[2];
                extra_beats <= 0;
                state       <= rx_tlast ? DECODE : H1;
            end
            H1: if (rx_tvalid) begin
                {data0, dw2} <= rx_tdata;
                state <= rx_tlast ? DECODE : D1;
            end
            D1: if (rx_tvalid) begin
                data1       <= rx_tdata[31:0];
                extra_beats <= !rx_tlast;
                state       <= rx_tlast ? DECODE : DROP;
            end
            DROP: if (rx_tvalid && rx_tlast) state <= DECODE;
            DECODE: begin
                ur    <= 0;
                write <= is_mwr;
                addr  <= {dw2[12:2], 2'b00};
                wdata <= {bswap(data1), bswap(data0)};
                if (bar0 && be_full && (is_mwr && len == 10'd2 && !extra_beats
                                        || is_mrd && (len == 10'd1 || len == 10'd2))) begin
                    start <= 1;
                    state <= BUSY;
                end else if (is_mrd) begin   // unsupported read: completed as UR
                    ur    <= 1;
                    err   <= 1;
                    state <= CPL0;
                end else begin
                    err   <= !is_msg;
                    state <= H0;
                end
            end
            BUSY: if (done) begin
                result <= rdata;
                state  <= write ? H0 : CPL0;
            end
            CPL0: if (tx_tready) state <= CPL1;
            CPL1: if (tx_tready) state <= tx_tlast ? H0 : CPL2;
            CPL2: if (tx_tready) state <= H0;
            default: state <= H0;
        endcase
    end
endmodule
