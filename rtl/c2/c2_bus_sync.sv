// The c2_cart board bus port from the link clock (mclk) to the board bus
// clock (sclk, BCLK): toggle handshake each way. The request fields need no
// synchronizer: the master holds them from bus_req until bus_done, and the
// slave side reads them only after the request toggle crossed. The board
// reset level and the CMOS pins cross through 2 flops, the A6# strap (reset
// vector 000FFFF0h) is taken once the reset level fell: stable by then. The
// edge-triggered pins (NMI, INIT#, SMI#: 2 BCLKs minimum) are stretched by
// 7 BCLKs first, so the link clock sees them at any BCLK.
module c2_bus_sync (
    // master side (c2_cart)
    input  logic        mclk,
    input  logic        mrst,
    input  logic        m_req,
    output logic        m_done,
    output logic [31:0] m_rdata,
    output logic        m_err,
    output logic        m_reset,
    output logic        m_low_vector,
    output logic [4:0]  m_pins,
    // slave side (c2_p6_agent), same fields, held until s_done
    input  logic        sclk,
    input  logic        srst,
    output logic        s_req,
    input  logic        s_done,
    input  logic [31:0] s_rdata,
    input  logic        s_err,
    input  logic        s_reset,       // RESET# asserted
    input  logic        s_low_vector,  // A6# sampled at the end of RESET#
    input  logic [4:0]  s_pins         // asserted: {SMI#, INIT#, NMI, STPCLK#, A20M#}
);
    logic       req_t, ack_t, busy;
    logic [2:0] req_s, ack_s, reset_s; // 2 synchronizer stages + edge history

    logic [4:0] pins_q, pins_x, pins_s0, pins_s1;
    logic [2:0] stretch [3];
    always_ff @(posedge sclk) begin
        pins_q <= s_pins;
        pins_x[1:0] <= pins_q[1:0];
        for (int i = 0; i < 3; i++) begin
            if (pins_q[2 + i]) stretch[i] <= 3'd7;
            else if (stretch[i] != '0) stretch[i] <= stretch[i] - 1'b1;
            pins_x[2 + i] <= pins_q[2 + i] || stretch[i] != '0;
        end
        if (srst) for (int i = 0; i < 3; i++) stretch[i] <= '0;
    end

    assign m_reset = reset_s[1];
    assign m_pins  = pins_s1;
    always_ff @(posedge mclk) begin
        reset_s <= {reset_s[1:0], s_reset};
        pins_s0 <= pins_x;
        pins_s1 <= pins_s0;
        if (reset_s[2] && !reset_s[1]) m_low_vector <= s_low_vector;
        if (mrst) begin
            reset_s      <= '0;
            m_low_vector <= 0;
        end
    end

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
