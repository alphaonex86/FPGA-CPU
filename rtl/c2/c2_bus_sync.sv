// The c2_cart board bus port from the link clock (mclk) to the board bus
// clock (sclk, BCLK): toggle handshake each way. The request fields need no
// synchronizer: the master holds them from bus_req until bus_done, and the
// slave side reads them only after the request toggle crossed.
module c2_bus_sync (
    // master side (c2_cart)
    input  logic        mclk,
    input  logic        mrst,
    input  logic        m_req,
    output logic        m_done,
    output logic [31:0] m_rdata,
    output logic        m_err,
    // slave side (c2_p6_agent), same fields, held until s_done
    input  logic        sclk,
    input  logic        srst,
    output logic        s_req,
    input  logic        s_done,
    input  logic [31:0] s_rdata,
    input  logic        s_err
);
    logic       req_t, ack_t, busy;
    logic [2:0] req_s, ack_s;          // 2 synchronizer stages + edge history

    // master: start on bus_req (not in its done clock, when it still stands)
    always_ff @(posedge mclk) begin
        ack_s  <= {ack_s[1:0], ack_t};
        m_done <= 0;
        if (mrst) begin
            req_t <= 0;
            busy  <= 0;
            ack_s <= '0;
        end else if (!busy && m_req && !m_done) begin
            req_t <= !req_t;
            busy  <= 1;
        end else if (busy && ack_s[2] != ack_s[1]) begin
            busy   <= 0;
            m_done <= 1;
        end
    end

    // slave: hold s_req from the toggle until s_done, keep its answer (stable
    // until the master's next request) and toggle back
    always_ff @(posedge sclk) begin
        req_s <= {req_s[1:0], req_t};
        if (srst) begin
            s_req <= 0;
            ack_t <= 0;
            req_s <= '0;
        end else if (!s_req && req_s[2] != req_s[1]) begin
            s_req <= 1;
        end else if (s_req && s_done) begin
            s_req   <= 0;
            m_rdata <= s_rdata;
            m_err   <= s_err;
            ack_t   <= !ack_t;
        end
    end
endmodule
