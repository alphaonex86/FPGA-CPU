//
// cpu486_bif.v - bus interface to a real AMD Am5x86-P75 (Socket 3, PGA-168).
//
// ORIGINAL RTL.  Board FPGAmotherboard/socket3 (both FPGA variants).
//
// WHAT IT DOES.  It turns the 486 local bus - ADS#, M/IO#, D/C#, W/R#, BE3#-BE0#,
// BLAST#, BRDY#, KEN#, RESET - into the 16-bit host port soc_softcore's cpu_ port
// speaks (rtl/HOSTPORT.md), so the OPTi 82C499 path of board E serves a real CPU.
// A bus interface only: no decode beyond KEN#, no wait-state policy, no peripheral.
//
// SPECIFICATION SOURCES.
//   AMD 19751C "Am5x86 Microprocessor" (FPGAmotherboard/socket3/docs/datasheets),
//   AC table at 33 MHz, all relative to the CLK rising edge:
//     t6  ADS#, A31-A2, BE#, M/IO#, D/C#, W/R# valid 3-14 ns; t8a BLAST# 3-14 ns;
//     t10 write data valid 3-14 ns; t14/t15 KEN# setup 5 / hold 3 ns;
//     t16/t17 BRDY# setup 5 / hold 3 ns; t22/t23 read data setup 5 / hold 3 ns.
//   19751C pin descriptions, verbatim:
//     BRDY# "is ignored when the bus is idle and at the end of the first clock in a
//       bus cycle"; "If RDY is returned simultaneously with BRDY, BRDY is ignored".
//     KEN# "When the microprocessor generates a cacheable cycle and KEN is active
//       one clock before RDY or BRDY during the first transfer of the cycle, the
//       cycle becomes a cache line fill cycle.  Returning KEN active one clock
//       before RDY during the last read in the cache line fill causes the line to
//       be placed in the on-chip cache."
//     BE3#-BE0# "During the first cache fill cycle, however, an external system
//       should ignore these signals and assume that all bytes are active."
//     WB/WT# "If WB/WT is sampled Low at RESET, all cache line fills are
//       write-through."
//   Intel 241731-002 / 486DX2 datasheet 7.2.4.2, Table 7.7: burst order
//     0-4-8-C, 4-0-C-8, 8-C-0-4, C-8-4-0, "followed by any burst cycle (cache or
//     not), cache line fill (burst or not) or code prefetch" = A3:A2 XOR beat.
//
// THE CYCLE.  One clock, the CPU's CLK; every CPU output is sampled and every CPU
// input launched on the rising edge (the top de-skews the FPGA copy of CLK).
//   E0  T1 begins: ADS#, address and status launched (t6 <= 14 ns).
//   E1  ADS# sampled: the cycle is captured, KEN# is launched from the same pins
//       (so it is valid at E2), a read issues its first host half.
//   E2  a write's data (t10 after E1) is captured and its first half issued.
//   Ek  the beat's data is on the host port: BRDY# and read data launched.
//   Ek+1 CPU samples BRDY#; BLAST# sampled here says whether a beat follows.
// So a single read takes 3 clocks (16 bits) or 4 (32 bits) against a zero-latency
// slave, a single write 4 or 5, and KEN# is always sampled one clock before the
// first BRDY#.  RDY# is never used: BRDY# ends non-burst cycles the same way.
//
// MEMORY READS TRANSFER ALL FOUR BYTES, every beat, from the address in burst order
// the module computes itself.  A line fill needs it (BE# above), a prefetch or a
// non-cacheable multi-transfer read follows the same order, and memory reads have
// no side effects on this board.  I/O, INTA and writes keep the CPU's byte enables.
//
// READ-DATA TURNAROUND.  Read data is driven from Ek and released half a clock after
// Ek+1, on the falling edge: 15 ns of hold against t23 = 3 ns, and the bus is free
// 15 ns before the earliest next write data (t10 >= 3 ns after the T2 edge).
//
// NOT IMPLEMENTED, deliberately:
//   * write-back mode, snooping and bus masters: WB/WT# is held low (write-through),
//     AHOLD/HOLD low, EADS#/BOFF# high, INV low.  soc_softcore has no DMA and no
//     bus master, so nothing but the CPU writes memory and no snoop is needed.
//   * BS8#/BS16#: pulled up on the board, not wired to the FPGA; the 32-to-16
//     split is done here instead.
//   * burst writes: write-through mode has none.  A write that sees BLAST# high
//     sets err_burst_write (the CPU would wait for more BRDY#s).
//
`default_nettype none

module cpu486_bif #(
    // CLK periods to hold RESET after rst_n is released (19751C/486: >= 15; the
    // board's power sequencer holds rst_n low through the 1 ms power-up wait).
    parameter integer RESET_CLKS = 64,
    // First address above DRAM; KEN# is returned below 640 KiB and from 1 MiB to here.
    parameter [31:0]  MEM_TOP    = 32'h0200_0000
) (
    input  wire        clk,          // the FPGA's copy of the CPU CLK
    input  wire        rst_n,

    // ---------------------------------------------------------- Am5x86 pins
    input  wire [31:2] cpu_a,
    input  wire [3:0]  cpu_be_n,
    input  wire        cpu_ads_n,
    input  wire        cpu_mio_n,    // 1 = memory
    input  wire        cpu_dc_n,     // 1 = data
    input  wire        cpu_wr_n,     // 1 = write
    input  wire        cpu_blast_n,
    input  wire [31:0] cpu_d_i,
    output wire [31:0] cpu_d_o,
    output wire        cpu_d_oe,
    output reg         cpu_brdy_n,
    output reg         cpu_ken_n,
    output reg         cpu_reset,    // ACTIVE HIGH
    // tie-offs of the bus contract above
    output wire        cpu_rdy_n,
    output wire        cpu_wbwt_n,
    output wire        cpu_ahold,
    output wire        cpu_hold,
    output wire        cpu_eads_n,
    output wire        cpu_inv,
    output wire        cpu_boff_n,

    // --------------------------------------------- host port, rtl/HOSTPORT.md
    // Registered master: host_req stands through the acknowledge cycle (C3) and
    // host_rvalid is taken in that cycle or later (C6).  Word address, 16 bits.
    output reg         host_req,
    output reg         host_we,
    output reg         host_mio,
    output reg         host_dc,
    output reg  [31:1] host_addr,
    output reg  [15:0] host_wdata,
    output reg  [1:0]  host_be,
    input  wire        host_ready,
    input  wire [15:0] host_rdata,
    input  wire        host_rvalid,

    // ------------------------------------------------------- special cycles
    // One clock per special cycle (M/IO# = 0, D/C# = 0, W/R# = 1), answered here.
    // Stop Grant is spc_a = 3'b100 (address 0x10), spc_be = 4'b0100.
    output reg         spc_stb,
    output reg  [4:2]  spc_a,
    output reg  [3:0]  spc_be,       // active high
    output reg         err_burst_write
);

    assign cpu_rdy_n  = 1'b1;
    assign cpu_wbwt_n = 1'b0;
    assign cpu_ahold  = 1'b0;
    assign cpu_hold   = 1'b0;
    assign cpu_eads_n = 1'b1;
    assign cpu_inv    = 1'b0;
    assign cpu_boff_n = 1'b1;

    // ------------------------------------------------------------------ reset
    localparam integer    RSTW    = (RESET_CLKS < 2) ? 1 : $clog2(RESET_CLKS + 1);
    localparam [RSTW-1:0] RST_TOP = RESET_CLKS[RSTW-1:0];
    reg [RSTW-1:0] rst_cnt;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rst_cnt   <= {RSTW{1'b0}};
            cpu_reset <= 1'b1;
        end else if (rst_cnt != RST_TOP) begin
            rst_cnt   <= rst_cnt + 1'b1;
            cpu_reset <= 1'b1;
        end else begin
            cpu_reset <= 1'b0;
        end
    end

    // ------------------------------------------------- decode at the ADS# edge
    wire [31:0] pin_addr  = {cpu_a, 2'b00};
    wire        pin_mem_rd = cpu_mio_n & ~cpu_wr_n;
    wire        pin_cacheable = pin_mem_rd &
                    ((pin_addr < 32'h000A_0000) ||
                     (pin_addr >= 32'h0010_0000 && pin_addr < MEM_TOP));
    wire        pin_special = ~cpu_mio_n & ~cpu_dc_n & cpu_wr_n;
    wire [3:0]  pin_be = pin_mem_rd ? 4'b1111 : ~cpu_be_n;

    // The 32-to-16 split: bytes 0-1 at {dword,0}, bytes 2-3 at {dword,1}.  A beat
    // with no byte enabled still runs its low half, so a beat always ends.
    function first_half(input [3:0] b);
        first_half = (b[1:0] == 2'b00) && (b[3:2] != 2'b00);
    endfunction

    // --------------------------------------------------------- state machine
    localparam [2:0] ST_IDLE  = 3'd0,
                     ST_WDATA = 3'd1,   // write: data valid at the edge after ADS#
                     ST_HOST  = 3'd2,   // host_req up, waiting for host_ready
                     ST_RDATA = 3'd3,   // read accepted, waiting for host_rvalid
                     ST_ACK   = 3'd4;   // BRDY# out, the CPU samples it this edge

    reg [2:0]  state;
    reg [31:2] c_a;          // the address captured at ADS#
    reg [3:0]  c_be;         // byte enables of every beat, active high
    reg        c_wr;
    reg [1:0]  beat;
    reg        half;         // 0 = bytes 0-1, 1 = bytes 2-3
    reg [31:0] c_wd;
    reg [15:0] rlo;
    reg [31:0] d_o_r;
    reg        d_oe_r, d_oe_neg;

    wire        last_half = half || (c_be[3:2] == 2'b00);
    wire [31:2] beat_dw   = {c_a[31:4], c_a[3:2] ^ beat};
    wire [1:0]  next_beat = beat + 2'd1;

    task launch(input [31:2] dw, input h, input [3:0] b, input [31:0] wd);
        begin
            host_req   <= 1'b1;
            host_addr  <= {dw, h};
            host_be    <= h ? b[3:2] : b[1:0];
            host_wdata <= h ? wd[31:16] : wd[15:0];
        end
    endtask

    task finish_beat(input [31:0] rd);
        begin
            host_req   <= 1'b0;
            d_o_r      <= rd;
            d_oe_r     <= ~c_wr;
            cpu_brdy_n <= 1'b0;
            state      <= ST_ACK;
        end
    endtask

    wire [31:0] rd_beat = half ? {host_rdata, rlo} : {16'h0000, host_rdata};

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= ST_IDLE;
            {host_req, host_we, host_mio, host_dc} <= 4'b0000;
            host_addr  <= 31'd0;
            host_wdata <= 16'd0;
            host_be    <= 2'b00;
            c_a <= 30'd0; c_be <= 4'd0; c_wr <= 1'b0; c_wd <= 32'd0;
            beat <= 2'd0; half <= 1'b0; rlo <= 16'd0;
            d_o_r <= 32'd0; d_oe_r <= 1'b0;
            cpu_brdy_n <= 1'b1;
            cpu_ken_n  <= 1'b1;
            spc_stb <= 1'b0; spc_a <= 3'd0; spc_be <= 4'd0;
            err_burst_write <= 1'b0;
        end else begin
            spc_stb <= 1'b0;
            case (state)
                ST_IDLE: if (!cpu_ads_n && !cpu_reset) begin
                    c_a      <= cpu_a;
                    c_be     <= pin_be;
                    c_wr     <= cpu_wr_n;
                    host_we  <= cpu_wr_n;
                    host_mio <= cpu_mio_n;
                    host_dc  <= cpu_dc_n;
                    beat     <= 2'd0;
                    half     <= first_half(pin_be);
                    rlo      <= 16'd0;
                    if (pin_special) begin
                        spc_stb    <= 1'b1;
                        spc_a      <= cpu_a[4:2];
                        spc_be     <= ~cpu_be_n;
                        cpu_brdy_n <= 1'b0;   // sampled at E2, legal (not E1)
                        state      <= ST_ACK;
                    end else if (cpu_wr_n) begin
                        state <= ST_WDATA;
                    end else begin
                        cpu_ken_n <= ~pin_cacheable;
                        launch(cpu_a, first_half(pin_be), pin_be, 32'd0);
                        state <= ST_HOST;
                    end
                end

                ST_WDATA: begin
                    c_wd <= cpu_d_i;
                    launch(c_a, half, c_be, cpu_d_i);
                    state <= ST_HOST;
                end

                ST_HOST: if (host_ready) begin
                    if (c_wr) begin
                        if (last_half) finish_beat(32'd0);
                        else begin half <= 1'b1; launch(beat_dw, 1'b1, c_be, c_wd); end
                    end else if (host_rvalid) begin
                        if (last_half) finish_beat(rd_beat);
                        else begin
                            rlo  <= host_rdata;
                            half <= 1'b1;
                            launch(beat_dw, 1'b1, c_be, 32'd0);
                        end
                    end else begin
                        host_req <= 1'b0;
                        state    <= ST_RDATA;
                    end
                end

                ST_RDATA: if (host_rvalid) begin
                    if (last_half) finish_beat(rd_beat);
                    else begin
                        rlo   <= host_rdata;
                        half  <= 1'b1;
                        launch(beat_dw, 1'b1, c_be, 32'd0);
                        state <= ST_HOST;
                    end
                end

                ST_ACK: begin
                    cpu_brdy_n <= 1'b1;
                    d_oe_r     <= 1'b0;
                    if (!cpu_blast_n || c_wr) begin
                        if (cpu_blast_n) err_burst_write <= 1'b1;
                        cpu_ken_n <= 1'b1;
                        state     <= ST_IDLE;
                    end else begin
                        beat <= next_beat;
                        half <= first_half(c_be);
                        launch({c_a[31:4], c_a[3:2] ^ next_beat}, first_half(c_be), c_be, 32'd0);
                        state <= ST_HOST;
                    end
                end

                default: state <= ST_IDLE;
            endcase
        end
    end

    always @(negedge clk or negedge rst_n) begin
        if (!rst_n) d_oe_neg <= 1'b0;
        else        d_oe_neg <= d_oe_r;
    end

    assign cpu_d_o  = d_o_r;
    assign cpu_d_oe = d_oe_r | d_oe_neg;

endmodule

`default_nettype wire
