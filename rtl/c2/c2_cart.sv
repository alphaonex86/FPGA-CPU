// Slot 1 C2 cartridge side (plan/slot1_c2.md "Bridge RTL"): receives a
// command from the card (c2_card.sv), runs its cycles on a generic board
// bus port (the P6 bus agent; the testbench in simulation), then replies.
// Up-link messages: {0x80} + reply payload; the status {0x40 | A6# << 3 |
// board reset << 2 | error << 1 | INTR} whenever its levels change or a
// cycle failed (always before the reply); between commands the pins
// {0x50 | STPCLK# << 1 | A20M#} when they change, the events {0x60 | SMI#
// << 2 | INIT# << 1 | NMI} on their assertion edges, and both level
// messages every 2^16 clocks (so a card reset later learns the levels).
// The pin inputs are synchronous to clk, asserted high. While link_lost
// (the card reset the link, c2_bus_sync) a running bus cycle ends, the
// command and its reply are dropped and nothing is sent; the level
// messages go out 16 clocks after (the card drops the pipeline's stale
// bytes first); link_flushed reports the flushed state.
module c2_cart (
    input  logic        clk,
    input  logic        rst,
    input  logic [7:0]  down,
    output logic [7:0]  up,
    // board bus port: bus_req holds until bus_done; data in the low bytes
    output logic        bus_req,
    output logic        bus_space,     // 0 memory, 1 I/O
    output logic        bus_write,
    output logic        bus_inta,      // interrupt acknowledge: vector in bus_rdata[7:0]
    output logic        bus_special,   // Special Transaction, sub-code in bus_wdata[2:0]
    output logic [31:0] bus_addr,
    output logic [1:0]  bus_size,      // log2 bytes
    output logic [31:0] bus_wdata,
    input  logic        bus_done,
    input  logic [31:0] bus_rdata,
    input  logic        bus_err,
    input  logic        intr,
    input  logic        board_reset,   // the board's RESET#
    input  logic        low_vector,    // A6# strap: reset vector 000FFFF0h
    input  logic        a20m,
    input  logic        stpclk,
    input  logic        nmi,
    input  logic        init,
    input  logic        smi,
    input  logic        link_lost,
    output logic        link_flushed
);
    typedef enum logic [3:0] {
        R_HDR, R_FIELDS, R_DATA, E_ADDR, E_LOAD, E_BUS, E_STORE, T_STATUS, T_HDR, T_DATA
    } state_t;
    state_t state;

    typedef enum logic [1:0] { C_CYCLE, C_INTA, C_REP, C_SPECIAL } cmd_t;
    cmd_t        cmd;
    logic        write;
    logic [63:0] fields;           // little-endian bytes: CYCLE addr, data; REP port, count
    logic [3:0]  fields_left;
    logic [12:0] count, elem;      // REP: element count and index
    logic [12:0] bytes, byte_i;    // data bytes (link side)
    logic [31:0] result;           // CYCLE read / INTA reply
    logic        err_event;
    logic [4:0]  levels_sent;      // {stpclk, a20m, low_vector, board_reset, intr}
    logic [15:0] status_age;       // clocks since both level messages went out
    logic [2:0]  events, ev_q;     // pending {smi, init, nmi} edges, last levels
    wire  [4:0]  levels = {stpclk, a20m, low_vector, board_reset, intr};
    wire  [2:0]  ev_rise = {smi, init, nmi} & ~ev_q;

    // the REP data buffer, 1024 x 32 with byte writes
    logic [31:0] buffer [1024];
    logic [9:0]  buf_addr;
    logic [3:0]  buf_we;
    logic [31:0] buf_wd, buf_q;
    always_ff @(posedge clk) begin
        for (int i = 0; i < 4; i++) if (buf_we[i]) buffer[buf_addr][8 * i +: 8] <= buf_wd[8 * i +: 8];
        buf_q <= buffer[buf_addr];
    end

    // REP element: word and byte lane in the buffer
    wire [12:0] elem_byte = elem << bus_size;
    wire [1:0]  lane      = elem_byte[1:0];
    wire [12:0] tx_next   = state == T_DATA ? byte_i + 13'd1 : 13'd0;
    wire [31:0] size_mask = bus_size == 2'd2 ? 32'hffffffff : bus_size == 2'd1 ? 32'h0000ffff : 32'h000000ff;

    always_comb begin
        buf_addr = elem_byte[11:2];
        buf_we   = '0;
        buf_wd   = result << 8 * lane;
        if (state == R_DATA) begin
            buf_addr = byte_i[11:2];
            buf_we   = 4'd1 << byte_i[1:0];
            buf_wd   = {4{down}};
        end else if (state == T_HDR || state == T_DATA)
            buf_addr = tx_next[11:2];
        else if (state == E_STORE && cmd == C_REP && !write)
            buf_we = (bus_size == 2'd2 ? 4'hf : bus_size == 2'd1 ? 4'h3 : 4'h1) << lane;
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            state     <= R_HDR;
            bus_req   <= 0;
            err_event <= 0;
            status_age <= '1;   // the first status right after reset
            events    <= '0;
            ev_q      <= '0;
            up        <= '0;
            link_flushed <= 0;
        end else begin
            up <= '0;
            status_age <= status_age + 1'b1;
            ev_q   <= {smi, init, nmi};
            events <= events | ev_rise;
            link_flushed <= link_lost && state == R_HDR;
            if (link_lost) begin
                if (state != E_BUS || bus_done) begin
                    bus_req <= 0;
                    state   <= R_HDR;
                end
                err_event  <= 0;
                status_age <= 16'hfff0;
            end else case (state)
            R_HDR: begin
                // between commands: status, pins, events, one per clock
                if (&status_age) begin
                    levels_sent <= ~levels;
                    status_age  <= '0;
                end else if (levels[2:0] != levels_sent[2:0] || err_event) begin
                    up               <= {4'b0100, levels[2:1], err_event, levels[0]};
                    levels_sent[2:0] <= levels[2:0];
                    err_event        <= 0;
                end else if (levels[4:3] != levels_sent[4:3]) begin
                    up               <= {6'b010100, levels[4:3]};
                    levels_sent[4:3] <= levels[4:3];
                end else if (events != '0) begin
                    up     <= {5'b01100, events};
                    events <= ev_rise;
                end
                byte_i <= '0;
                elem   <= '0;
                if (down[7] && down[6:4] == 3'b000) begin
                    cmd         <= C_CYCLE;
                    {bus_space, write, bus_size} <= down[3:0];
                    fields_left <= 4'd8;
                    state       <= R_FIELDS;
                end else if (down == 8'h40) begin
                    cmd   <= C_INTA;
                    state <= E_ADDR;
                end else if (down[7:3] == 5'b01001) begin
                    cmd    <= C_SPECIAL;
                    fields <= {29'd0, down[2:0], 32'd0};   // the sub-code as data
                    state  <= E_ADDR;
                end else if (down[7:3] == 5'b00100) begin
                    cmd         <= C_REP;
                    bus_space   <= 1;
                    {write, bus_size} <= down[2:0];
                    fields_left <= 4'd4;
                    state       <= R_FIELDS;
                end else if (down != 8'h00)
                    err_event <= 1;   // not a command: reported, ignored
            end
            R_FIELDS: begin
                fields      <= {down, fields[63:8]};
                fields_left <= fields_left - 4'd1;
                if (fields_left == 4'd1) begin
                    count <= {down[4:0], fields[63:56]};   // REP: the count's high byte arrives last
                    bytes <= {down[4:0], fields[63:56]} << bus_size;
                    state <= cmd == C_REP && write ? R_DATA : E_ADDR;
                end
            end
            R_DATA: begin
                byte_i <= byte_i + 13'd1;
                if (byte_i == bytes - 13'd1) state <= E_ADDR;
            end
            E_ADDR: state <= E_LOAD;   // buffer read of the element
            E_LOAD: begin
                bus_inta    <= cmd == C_INTA;
                bus_special <= cmd == C_SPECIAL;
                bus_write   <= write && (cmd == C_CYCLE || cmd == C_REP);
                bus_addr  <= cmd == C_REP ? {16'd0, fields[47:32]} : fields[31:0];
                bus_wdata <= (cmd == C_REP ? buf_q >> 8 * lane : fields[63:32]) & size_mask;
                bus_req   <= 1;
                state     <= E_BUS;
            end
            E_BUS: if (bus_done) begin
                bus_req <= 0;
                result  <= bus_rdata;
                if (bus_err) err_event <= 1;
                state   <= E_STORE;
            end
            E_STORE: begin   // a REP read stores the element (buf_we)
                elem  <= elem + 13'd1;
                state <= cmd == C_REP && elem != count - 13'd1 ? E_ADDR : T_STATUS;
            end
            T_STATUS: begin
                if (levels[2:0] != levels_sent[2:0] || err_event) begin
                    up               <= {4'b0100, levels[2:1], err_event, levels[0]};
                    levels_sent[2:0] <= levels[2:0];
                    err_event        <= 0;
                end
                state <= T_HDR;
            end
            T_HDR: begin
                up     <= 8'h80;
                byte_i <= '0;
                state  <= cmd == C_INTA || (cmd == C_CYCLE && !write) || (cmd == C_REP && !write) ? T_DATA : R_HDR;
            end
            T_DATA: begin
                up     <= cmd == C_REP ? buf_q[8 * byte_i[1:0] +: 8] : result[8 * byte_i[1:0] +: 8];
                byte_i <= byte_i + 13'd1;
                if (byte_i == (cmd == C_REP ? bytes : cmd == C_INTA ? 13'd1 : 13'd4) - 13'd1) state <= R_HDR;
            end
            default: state <= R_HDR;
            endcase
        end
    end
endmodule
