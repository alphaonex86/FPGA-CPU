// Slot 1 C2 PCIe card side (plan/slot1_c2.md "Bridge RTL"): the BAR0
// register block of sw/c2-vmm/bus.h on a vendor-neutral request port (the
// PCIe IP wrapper feeds it), and the link to the cartridge (c2_cart.sv):
// one byte per clock each way, 0x00 between messages. One command at a
// time: a request that needs the cartridge holds req_ready low until the
// cartridge's reply, so BAR0 requests run strictly in order. The up bytes
// come through a clock-crossing FIFO: up_valid marks each one.
module c2_card (
    input  logic        clk,
    input  logic        rst,
    // BAR0: writes are 64-bit; a read returns rsp_data once (rsp_valid)
    input  logic        req_valid,
    output logic        req_ready,
    input  logic        req_write,
    input  logic [12:0] req_addr,
    input  logic [63:0] req_wdata,
    output logic        rsp_valid,
    output logic [63:0] rsp_data,
    // link
    output logic [7:0]  down,
    input  logic [7:0]  up,
    input  logic        up_valid,
    input  logic        ext_err      // PCIe / link-FIFO fault: sets the protocol error
);
    localparam logic [31:0] ID = 32'h43324231;   // "C2B1"

    typedef enum logic [1:0] { IDLE, SEND, WAIT, RESP } state_t;
    state_t state;

    // STATUS: bit 0 INTR, bit 1 bus error, bit 2 protocol error (a bad BAR0
    // access or link byte); the error bits are sticky, a STATUS read clears
    logic        intr, err_bus, err_proto;
    logic [31:0] rdata;            // the last read cycle / INTA vector
    logic [63:0] resp;
    logic        resp_window;      // RESP returns the window word
    logic        resp_vector;      // after the reply: RESP with the INTA vector

    // message to send: up to 9 header bytes, then payload bytes from the window
    logic [7:0]  tx_hdr [9];
    logic [3:0]  tx_hdr_len, tx_hdr_i;
    logic [12:0] tx_pay_len, tx_pay_i;
    logic        tx_in_hdr;
    // reply expected: payload length, into rdata or the window
    logic [12:0] rx_len, rx_i;
    logic        rx_window, rx_busy;

    // the 4 KB window, 512 x 64 with byte writes
    logic [63:0] window [512];
    logic [8:0]  win_addr;
    logic [7:0]  win_we;
    logic [63:0] win_wd, win_q;
    always_ff @(posedge clk) begin
        for (int i = 0; i < 8; i++) if (win_we[i]) window[win_addr][8 * i +: 8] <= win_wd[8 * i +: 8];
        win_q <= window[win_addr];
    end

    wire        accept    = req_valid && req_ready;
    wire        is_window = req_addr[12];
    wire        is_cycle  = req_addr[12:7] == 6'b000010;   // 0x100-0x17f
    wire        is_rep    = req_addr[12:6] == 7'b0000110;  // 0x180-0x1bf
    wire [1:0]  lsz       = req_addr[4:3];
    wire [12:0] rep_count = req_wdata[44:32];
    wire [13:0] rep_bytes = {1'b0, rep_count} << lsz;
    wire        rep_ok    = lsz != 2'd3 && req_wdata[63:45] == '0 && rep_count != '0 && rep_bytes <= 14'd4096;
    wire        rx_byte   = up_valid && rx_busy && state == WAIT;

    assign req_ready = state == IDLE;
    assign rsp_valid = state == RESP;
    assign rsp_data  = resp_window ? win_q : resp;

    // window port: reply bytes > the payload being sent > a BAR0 access
    wire [12:0] tx_next = tx_in_hdr ? 13'd0 : tx_pay_i + 13'd1;
    always_comb begin
        win_addr = req_addr[11:3];
        win_we   = '0;
        win_wd   = req_wdata;
        if (rx_byte && rx_window) begin
            win_addr = rx_i[11:3];
            win_we   = 8'd1 << rx_i[2:0];
            win_wd   = {8{up}};
        end else if (state == SEND)
            win_addr = tx_next[11:3];
        else if (accept && req_write && is_window)
            win_we = '1;
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            state     <= IDLE;
            intr      <= 0;
            err_bus   <= 0;
            err_proto <= 0;
            rx_busy   <= 0;
            down      <= '0;
        end else begin
            down <= '0;
            case (state)
            IDLE: if (accept) begin
                resp_window <= 0;
                resp_vector <= 0;
                tx_hdr_i    <= '0;
                tx_pay_i    <= '0;
                tx_pay_len  <= '0;
                tx_in_hdr   <= 1;
                rx_window   <= 0;
                rx_len      <= '0;
                if (req_write) begin
                    if (is_cycle && lsz != 2'd3) begin
                        // {0x80 | space << 3 | write << 2 | log2 size, addr[4], data[4]}
                        tx_hdr[0]  <= {4'h8, req_addr[6:3]};
                        for (int i = 0; i < 8; i++) tx_hdr[1 + i] <= req_wdata[8 * i +: 8];
                        tx_hdr_len <= 4'd9;
                        rx_len     <= req_addr[5] ? 13'd0 : 13'd4;
                        state      <= SEND;
                    end else if (is_rep && rep_ok) begin
                        // {0x20 | write << 2 | log2 size, port[2], count[2]}, then a write's data
                        tx_hdr[0]  <= {5'b00100, req_addr[5:3]};
                        tx_hdr[1]  <= req_wdata[7:0];
                        tx_hdr[2]  <= req_wdata[15:8];
                        tx_hdr[3]  <= rep_count[7:0];
                        tx_hdr[4]  <= {3'b000, rep_count[12:8]};
                        tx_hdr_len <= 4'd5;
                        tx_pay_len <= req_addr[5] ? rep_bytes[12:0] : '0;
                        rx_len     <= req_addr[5] ? 13'd0 : rep_bytes[12:0];
                        rx_window  <= !req_addr[5];
                        state      <= SEND;
                    end else if (!is_window)
                        err_proto <= 1;
                end else begin
                    state <= RESP;
                    resp  <= '0;
                    if (is_window)
                        resp_window <= 1;
                    else case (req_addr)
                        13'h000: resp <= {32'd0, ID};
                        13'h008: begin
                            resp      <= {61'd0, err_proto, err_bus, intr};
                            err_bus   <= 0;
                            err_proto <= 0;
                        end
                        13'h010: resp <= {32'd0, rdata};
                        13'h018: begin   // INTA: {0x40}, reply 1 byte
                            tx_hdr[0]   <= 8'h40;
                            tx_hdr_len  <= 4'd1;
                            rx_len      <= 13'd1;
                            resp_vector <= 1;
                            state       <= SEND;
                        end
                        default: err_proto <= 1;
                    endcase
                end
            end
            SEND: begin
                if (tx_in_hdr) begin
                    down     <= tx_hdr[tx_hdr_i];
                    tx_hdr_i <= tx_hdr_i + 4'd1;
                    if (tx_hdr_i == tx_hdr_len - 4'd1) begin
                        tx_in_hdr <= 0;
                        if (tx_pay_len == '0) state <= WAIT;
                    end
                end else begin
                    down     <= win_q[8 * tx_pay_i[2:0] +: 8];
                    tx_pay_i <= tx_pay_i + 13'd1;
                    if (tx_pay_i == tx_pay_len - 13'd1) state <= WAIT;
                end
            end
            WAIT: ;
            RESP: begin
                resp_window <= 0;
                state       <= IDLE;
            end
            endcase

            // replies and status messages from the cartridge
            if (rx_byte) begin
                if (!rx_window) rdata[8 * rx_i[1:0] +: 8] <= up;
                rx_i <= rx_i + 13'd1;
                if (rx_i == rx_len - 13'd1) begin
                    rx_busy <= 0;
                    state   <= resp_vector ? RESP : IDLE;
                    resp    <= {56'd0, up};   // INTA: the 1-byte reply is the vector
                end
            end else if (up_valid) begin
                if (up == 8'h80 && state == WAIT) begin
                    rdata <= '0;
                    rx_i  <= '0;
                    if (rx_len == '0) state <= IDLE;
                    else rx_busy <= 1;
                end else if (up[7:2] == 6'b010000) begin
                    intr <= up[0];
                    if (up[1]) err_bus <= 1;
                end else if (up != 8'h00)
                    err_proto <= 1;
            end
            if (ext_err) err_proto <= 1;
        end
    end
endmodule
