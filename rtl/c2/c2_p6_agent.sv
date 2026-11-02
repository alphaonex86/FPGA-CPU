// P6 (Slot 1 / Socket 370) bus agent of the C2 cartridge: each cycle of the
// c2_cart board bus port becomes one P6 bus transaction as symmetric agent 0,
// one at a time, uncached: Memory Data Read, Memory Write (may be retried),
// I/O Read / Write, Interrupt Acknowledge, Special (sub-code on BE[7:0]#);
// a Retry response re-issues it.
// No cache: HIT#/HITM# are never driven (the DMA mirror is a later step).
// [PPRO1] Pentium Pro Family Developer's Manual vol. 1 (sockets/socket370/
// pentium_pro_developers_manual_vol1.pdf), [HWDM] P6 Family Hardware
// Developer's Manual 244001-001 (same folder).
// Pins as in FPGAcommon p6_bif: *_n are pin levels (low = asserted, also
// for A# and D#), *_drv = 1 pulls the open-drain line low. Inputs are
// registered first, so a signal driven in clock T is "observed in T+1" and
// an output decided then is driven in T+2, as the [PPRO1] figures count.
module c2_p6_agent (
    input  logic        clk,          // BCLK
    input  logic        rst,          // FPGA reset
    // board bus port (c2_cart): bus_req holds until bus_done
    input  logic        bus_req,
    input  logic        bus_space,    // 0 memory, 1 I/O
    input  logic        bus_write,
    input  logic        bus_inta,
    input  logic        bus_special,  // Special Transaction, sub-code in bus_wdata[2:0]
    input  logic [31:0] bus_addr,
    input  logic [1:0]  bus_size,     // log2 bytes, naturally aligned
    input  logic [31:0] bus_wdata,
    output logic        bus_done,
    output logic [31:0] bus_rdata,
    output logic        bus_err,      // Hard Failure or an illegal response
    // P6 bus
    input  logic        reset_n,
    input  logic [12:5] a_n,          // the power-on configuration straps
    input  logic        ads_n,
    input  logic        bnr_n,
    input  logic        bpri_n,
    input  logic        trdy_n,
    input  logic        dbsy_n,
    input  logic        drdy_n,
    input  logic [2:0]  rs_n,
    input  logic [63:0] d_n,
    output logic [35:3] a_drv,
    output logic [4:0]  req_drv,
    output logic        ads_drv,
    output logic        br0_drv,
    output logic        drdy_drv,
    output logic [63:0] d_drv,
    // board state for the bridge
    output logic        cpu_reset,    // RESET# asserted
    output logic [12:5] straps        // A[12:5]# sampled at the end of RESET# [HWDM] 5.1
);
    // RS[2:0]# [PPRO1] 4.5.3.4; any other response to ours is an error
    localparam logic [2:0] RS_RETRY = 3'b001, RS_NODATA = 3'b101, RS_NORMAL = 3'b111;

    // ---- inputs, registered once, positive logic
    logic        reset_q, ads_q, bnr_q, bpri_q, trdy_q, dbsy_q, drdy_q;
    logic [2:0]  rs_q;
    logic [63:0] d_q;
    logic [12:5] a_q;
    always_ff @(posedge clk) begin
        reset_q <= !reset_n;
        ads_q   <= !ads_n;
        bnr_q   <= !bnr_n;
        bpri_q  <= !bpri_n;
        trdy_q  <= !trdy_n;
        dbsy_q  <= !dbsy_n;
        drdy_q  <= !drdy_n;
        rs_q    <= ~rs_n;
        d_q     <= ~d_n;
        a_q     <= ~a_n;
    end
    assign cpu_reset = reset_q;
    wire rs_seen = rs_q != 3'b000;

    // ---- the request
    wire [2:0] lane   = bus_inta ? 3'd0 : bus_addr[2:0];   // INTA: vector on D[7:0]#
    wire       central = bus_inta || bus_special;                // REQa 01000
    wire       writes  = bus_write && !central;                  // carries write data
    wire       reads   = !bus_write && !bus_special;             // takes data (or INTA)
    wire [7:0] be     = bus_special ? {5'd0, bus_wdata[2:0]}
                      : (bus_size == 2'd2 ? 8'h0f : bus_size == 2'd1 ? 8'h03 : 8'h01) << lane;
    wire [4:0] reqa   = central ? 5'b01000 : bus_space ? {4'b1000, bus_write}
                      : bus_write ? 5'b00111 : 5'b00110;
    wire [35:3] addr_a = central ? '0 : {4'd0, bus_space ? 16'd0 : bus_addr[31:16], bus_addr[15:3]};
    // clock B: ATTR (UC), DID (agent 0, symmetric) and EXF all zero, BE on
    // Ab[15:8]# (0 for INTA); REQb = DSZ 00, LEN 00 (0-8 bytes), a Special's
    // REQb[0]# [HWDM] A.1.7-A.1.43, [PPRO1] 5.2.3.6
    wire [35:3] addr_b = bus_inta ? '0 : {20'd0, be, 5'd0};

    // ---- reset, arbitration [PPRO1] 4.1.5: agent 0 waits >= 3 clocks
    // after RESET# before BREQ0#, then parks (no other symmetric agent);
    // ownership 2 clocks after BREQ0# from the idle state [PPRO1] 4.1.5.3
    logic [2:0] arb;                   // clocks since RESET# observed inactive, saturating
    wire        owner = arb == 3'd7;
    always_ff @(posedge clk) begin
        if (rst || reset_q) arb <= '0;
        else if (arb != 3'd7) arb <= arb + 1'b1;
        if (reset_q) straps <= a_q;     // the last value before the edge
    end
    assign br0_drv = arb >= 3'd5;

    // ---- request stall [PPRO1] 4.1.3.2: BNR# sampled every other clock in
    // stalled / throttled (first 2 clocks after RESET#), the 3rd clock after
    // an observed ADS# when free; one transaction per throttled state
    typedef enum logic [1:0] { STALLED, THROTTLED, FREE } stall_t;
    stall_t     stall;
    logic       alt, throttle_used;
    logic [2:0] ads_hist;              // ads_q of the last 3 clocks
    wire        bnr_point = stall == FREE ? ads_hist[2] : alt && arb != '0;
    logic       issue;                 // ADS# goes out next clock
    always_ff @(posedge clk) begin
        ads_hist <= {ads_hist[1:0], ads_q};
        alt      <= !alt;
        if (issue) throttle_used <= 1;
        if (rst || reset_q) begin
            stall         <= STALLED;
            alt           <= 1;        // first sample point 2 clocks after RESET#
            throttle_used <= 0;
            ads_hist      <= '0;
        end else if (bnr_point) begin
            throttle_used <= 0;
            alt           <= 0;
            if (bnr_q) stall <= STALLED;
            else       stall <= stall == STALLED ? THROTTLED : FREE;
        end
    end

    // ---- in-order queue position of our transaction: responses come in
    // ADS# order, so ours is the one after `ahead` other responses
    logic [3:0] ioq, ahead;
    always_ff @(posedge clk) begin
        if (rst || reset_q) ioq <= '0;
        else ioq <= ioq + ads_q - rs_seen;
    end

    // ---- the transaction
    typedef enum logic [2:0] { IDLE, REQ_A, REQ_B, WAIT, DATA, DONE } state_t;
    state_t state;
    logic   wrote;                     // write data sent
    wire    head      = ahead == '0;
    wire    may_issue = owner && !bpri_q && !ads_q && !ads_drv &&
                        (stall == FREE || (stall == THROTTLED && !throttle_used));
    assign issue    = state == IDLE && bus_req && may_issue;
    assign bus_done = state == DONE;

    always_ff @(posedge clk) begin
        a_drv    <= '0;
        req_drv  <= '0;
        ads_drv  <= 0;
        drdy_drv <= 0;
        d_drv    <= '0;
        if (rst) begin
            state <= IDLE;
        end else if (reset_q) begin
            // RESET#: the transaction under way or a new request ends in an error
            if (state != DONE && (state != IDLE || bus_req)) begin
                bus_err <= 1;
                state   <= DONE;
            end else
                state <= IDLE;
        end else case (state)
            IDLE: if (issue) begin
                a_drv   <= addr_a;
                req_drv <= reqa;
                ads_drv <= 1;
                bus_err <= 0;
                wrote   <= 0;
                state   <= REQ_A;
            end
            REQ_A: begin               // ADS# on the pins; clock B next
                a_drv   <= addr_b;
                req_drv <= {4'd0, bus_special};
                state   <= REQ_B;
            end
            REQ_B: begin               // our ADS# observed now
                ahead <= ioq - rs_seen;
                state <= WAIT;
            end
            WAIT: begin
                if (rs_seen && !head) ahead <= ahead - 1'b1;
                // request-initiated write data: TRDY# observed with DBSY#
                // inactive -> DRDY# + data next clock, one chunk, no DBSY#
                // [PPRO1] 4.6.2.1
                if (head && writes && !wrote && trdy_q && !dbsy_q) begin
                    drdy_drv <= 1;
                    d_drv    <= {32'd0, bus_wdata} << (8 * lane);
                    wrote    <= 1;
                end
                if (rs_seen && head) begin
                    if (rs_q == RS_RETRY) state <= IDLE;
                    else if (rs_q == RS_NORMAL && reads) begin
                        // read data starts with the response [PPRO1] 4.6.2.2
                        if (drdy_q) begin
                            bus_rdata <= 32'(d_q >> (8 * lane));
                            state     <= DONE;
                        end else
                            state <= DATA;
                    end else begin
                        bus_err <= !(rs_q == RS_NODATA && (bus_special || writes && wrote));
                        state   <= DONE;
                    end
                end
            end
            DATA: if (drdy_q) begin
                bus_rdata <= 32'(d_q >> (8 * lane));
                state     <= DONE;
            end
            DONE: state <= IDLE;
            default: state <= IDLE;
        endcase
    end
endmodule
