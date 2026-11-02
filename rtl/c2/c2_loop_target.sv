// Loopback bus target for bring-up without a board (plan/slot1_c2.md): the
// devices of sw/c2-vmm/bus_sim.c in RTL on c2_cart's bus port. A 64 KB ROM
// at the top of 4 GB (ROM_HEX, 32-bit words), 256-byte scratch RAMs at
// 0xd0000 and 0xa0000, serial out at 0x3f8 (status 0x60 at 0x3fd), POST
// code at 0x80, INTR at 0xf5 (vector 0x20 + N) and at 0xf7 (N ms later,
// vector 0x28), a 4 KB byte FIFO at 0x1f0, a board reset of 1 ms when
// 0xcf9 is written with bits 2:1 set; anything else floats high.
module c2_loop_target #(
    parameter string ROM_HEX     = "test_rom.hex",
    parameter int    CLOCKS_MS   = 50000           // clocks per millisecond
) (
    input  logic        clk,
    input  logic        rst,
    input  logic        bus_req,
    input  logic        bus_space,
    input  logic        bus_write,
    input  logic        bus_inta,
    input  logic [31:0] bus_addr,
    input  logic [1:0]  bus_size,
    input  logic [31:0] bus_wdata,
    output logic        bus_done,
    output logic [31:0] bus_rdata,
    output logic        bus_err,      // a write to the full FIFO
    output logic        intr,
    output logic        board_reset,
    // serial byte out (to a UART), POST code
    output logic        serial_valid,
    output logic [7:0]  serial_byte,
    input  logic        serial_ready,
    output logic [7:0]  post
);
    logic [31:0] rom [16384];
    initial $readmemh(ROM_HEX, rom);
    logic [31:0] scratch [2][64];
    logic [7:0]  fifo [4096];
    logic [12:0] fifo_head, fifo_tail;        // free-running byte counts

    typedef enum logic [1:0] { IDLE, ROM_RD, BYTES, DONE } state_t;
    state_t state;
    logic [31:0] rom_q, data;
    logic [1:0]  byte_i;
    logic [7:0]  vector;
    logic [31:0] delay;                       // 0xf7 countdown (clocks)
    logic [31:0] reset_left;                  // board reset countdown (clocks)

    wire       is_mem    = !bus_space;
    wire       is_io     = bus_space;
    wire       at_rom    = is_mem && bus_addr[31:16] == 16'hffff;
    wire       scratch_d = is_mem && bus_addr[31:8] == 24'h000d00;
    wire       scratch_a = is_mem && bus_addr[31:8] == 24'h000a00;
    wire [1:0] lane      = bus_addr[1:0];
    wire [31:0] mask     = bus_size == 2'd2 ? 32'hffffffff : bus_size == 2'd1 ? 32'h0000ffff : 32'h000000ff;
    wire [3:0] be        = (bus_size == 2'd2 ? 4'hf : bus_size == 2'd1 ? 4'h3 : 4'h1) << lane;
    wire [31:0] scratch_q = scratch[scratch_a][bus_addr[7:2]];
    wire [31:0] wdata_lane = bus_wdata << 8 * lane;
    wire [1:0]  last_byte  = bus_size == 2'd2 ? 2'd3 : bus_size == 2'd1 ? 2'd1 : 2'd0;

    always_ff @(posedge clk) rom_q <= rom[bus_addr[15:2]];

    assign bus_done     = state == DONE;
    assign board_reset  = reset_left != '0;
    assign serial_valid = state == BYTES && is_io && bus_write && bus_addr == 32'h3f8;
    assign serial_byte  = bus_wdata[7:0];

    always_ff @(posedge clk) begin
        if (rst) begin
            state     <= IDLE;
            intr      <= 0;
            delay     <= '0;
            reset_left <= '0;
            fifo_head <= '0;
            fifo_tail <= '0;
            post      <= '0;
        end else begin
            if (reset_left != '0) begin   // the devices' state at a board reset
                reset_left <= reset_left - 1'b1;
                intr       <= 0;
                delay      <= '0;
            end
            if (delay != '0) begin
                delay <= delay - 1'b1;
                if (delay == 32'd1) begin
                    intr   <= 1;
                    vector <= 8'h28;
                end
            end
            case (state)
            IDLE: if (bus_req) begin
                data    <= mask;   // floats high
                byte_i  <= '0;
                bus_err <= 0;
                if (bus_inta) begin
                    data  <= {24'd0, vector};
                    intr  <= 0;
                    state <= DONE;
                end else if (at_rom && !bus_write)
                    state <= ROM_RD;
                else if (scratch_d || scratch_a) begin
                    if (bus_write) begin
                        for (int i = 0; i < 4; i++)
                            if (be[i]) scratch[scratch_a][bus_addr[7:2]][8 * i +: 8] <= wdata_lane[8 * i +: 8];
                    end else
                        data <= (scratch_q >> 8 * lane) & mask;
                    state <= DONE;
                end else if (is_io && (bus_addr == 32'h1f0 || bus_addr == 32'h3f8))
                    state <= BYTES;
                else begin
                    if (is_io && !bus_write && bus_addr == 32'h3fd) data <= 32'h60;
                    if (is_io && bus_write && bus_addr == 32'h80) post <= bus_wdata[7:0];
                    if (is_io && bus_write && bus_addr == 32'hf5) begin
                        intr   <= 1;
                        vector <= 8'h20 + bus_wdata[7:0];
                    end
                    if (is_io && bus_write && bus_addr == 32'hf7) delay <= bus_wdata[7:0] * CLOCKS_MS;
                    if (is_io && bus_write && bus_addr == 32'hcf9 && bus_wdata[2:1] == 2'b11) reset_left <= CLOCKS_MS;
                    state <= DONE;
                end
            end
            ROM_RD: begin
                data  <= (rom_q >> 8 * lane) & mask;
                state <= DONE;
            end
            BYTES: begin   // the FIFO one byte per clock; serial waits for the UART
                if (bus_addr == 32'h3f8) begin
                    if (serial_ready) state <= DONE;
                end else begin
                    if (bus_write && fifo_head - fifo_tail == 13'd4096)
                        bus_err <= 1;
                    else if (bus_write) begin
                        fifo[fifo_head[11:0]] <= bus_wdata[8 * byte_i +: 8];
                        fifo_head <= fifo_head + 1'b1;
                    end else if (fifo_head != fifo_tail) begin
                        data[8 * byte_i +: 8] <= fifo[fifo_tail[11:0]];
                        fifo_tail <= fifo_tail + 1'b1;
                    end
                    byte_i <= byte_i + 1'b1;
                    if (byte_i == last_byte) state <= DONE;
                end
            end
            DONE: state <= IDLE;
            endcase
        end
    end
    assign bus_rdata = data;
endmodule
