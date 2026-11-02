// One BAR0 request across clock domains (toggle handshake): the PCIe side
// (uclk) starts it, the c2_card side (lclk) runs it, done comes back with
// the read data. The request and response registers stay stable while
// their toggle crosses (constrain them as max-delay paths).
module c2_req_sync (
    input  logic        uclk,
    input  logic        urst,
    input  logic        start,
    input  logic        write,
    input  logic [12:0] addr,
    input  logic [63:0] wdata,
    output logic        done,
    output logic [63:0] rdata,
    input  logic        lclk,
    input  logic        lrst,
    output logic        req_valid,
    input  logic        req_ready,
    output logic        req_write,
    output logic [12:0] req_addr,
    output logic [63:0] req_wdata,
    input  logic        rsp_valid,
    input  logic [63:0] rsp_data
);
    logic       req_t, ack_t;              // toggles
    logic [2:0] req_s, ack_s;              // synchronizers + edge
    logic       wait_rsp;
    logic [63:0] rsp;

    always_ff @(posedge uclk) begin
        if (urst) begin
            req_t <= 0;
            ack_s <= '0;
            done  <= 0;
        end else begin
            ack_s <= {ack_s[1:0], ack_t};
            done  <= ack_s[2] != ack_s[1];
            if (start) begin
                req_write <= write;
                req_addr  <= addr;
                req_wdata <= wdata;
                req_t     <= !req_t;
            end
        end
    end
    assign rdata = rsp;

    always_ff @(posedge lclk) begin
        if (lrst) begin
            req_s     <= '0;
            req_valid <= 0;
            wait_rsp  <= 0;
            ack_t     <= 0;
        end else begin
            req_s <= {req_s[1:0], req_t};
            if (req_s[2] != req_s[1]) req_valid <= 1;
            if (req_valid && req_ready) begin
                req_valid <= 0;
                if (req_write) ack_t <= !ack_t;
                else wait_rsp <= 1;
            end
            if (wait_rsp && rsp_valid) begin
                rsp      <= rsp_data;
                wait_rsp <= 0;
                ack_t    <= !ack_t;
            end
        end
    end
endmodule
