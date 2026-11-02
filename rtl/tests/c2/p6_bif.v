//
// p6_bif.v - Intel P6 / AGTL+ system bus front end, response agent side.
//
// ORIGINAL RTL for board C: a real Intel Pentium III (Coppermine, FC-PGA,
// Socket 370) with an Artix-7 XC7A50T as the entire chipset.  This module is
// the CPU bus front end only.  It turns the six-phase P6 bus into the one
// synchronous host port this tree speaks, rtl/HOSTPORT.md, so the VIA
// Apollo Pro 133A model in rtl/chipset/apollo133a and the memory controller in
// rtl/sdram need no second convention.  It contains no address decode, no
// wait-state policy and no peripherals.
//
// -------------------------------------------------------------------- SOURCES
// Everything below is quoted from documents on this machine.  Nothing is
// guessed; where a fact could not be sourced it is called out in README.md.
//
//   [HWDM]   Intel 244001-001, "P6 Family of Processors Hardware Developer's
//            Manual", ../../../FPGAmotherboard/socket370/docs/datasheets/
//            cpu_Intel_P6_family_HW_devmanual_244001-001.pdf
//   [PPRO1]  Intel Pentium Pro Family Developer's Manual, Volume 1, same
//            directory, cpu_Intel_PentiumPro_devmanual_vol1.pdf
//   [P3CU]   Intel 245264-008, Pentium III Processor for the PGA370 Socket
//   [CLAUDE] FPGAmotherboard/socket370/CLAUDE.md, "The bus: AGTL+ / P6"
//
// -------------------------------------------------------- ELECTRICAL, NOT RTL
// AGTL+ is open-drain to VTT with a VREF differential receiver, and the CPU
// carries on-die RTT on every bus signal except RESET#.  There is no GTL/GTL+
// IOSTANDARD in 7-series, so the board synthesises it: every bus pin is an
// OBUFT with .I tied to 1'b0 plus an IBUF, both HSTL_II_18, VCCO 1.8 V, an
// external VREF of 1.00 V, and the data rides on the output enable.  That is
// why this module has a *_drv output per line instead of a tri-state bus:
//
//     OBUFT #(.IOSTANDARD("HSTL_II_18")) o (.O(pad), .I(1'b0), .T(~x_drv));
//     IBUF  #(.IOSTANDARD("HSTL_II_18")) i (.I(pad), .O(x_n));
//
//   x_drv = 1  ->  the FPGA pulls the line to VOL ~0.28 V  ->  signal ASSERTED
//   x_drv = 0  ->  Hi-Z, the CPU's on-die RTT pulls to VTT ->  signal INACTIVE
//
// Never enable a push-pull high: VCCO 1.8 V is above VTT 1.50 V and would
// over-drive the CPU pin.  RESET# additionally needs a motherboard resistor to
// VTT because it is the one signal with no on-die RTT.  [CLAUDE], [P3CU] Tbl 3
//
// All the *_n inputs are pin levels: a P6 signal name ending in '#' is active
// low, so every input is inverted once here and the whole module then thinks
// in positive logic.  A[35:3]# and D[63:0]# are inverted the same way: the
// logical value 1 is a low voltage on the pin.
//
// ------------------------------------------------------------ THE SIX PHASES
// Arbitration -> Request -> Error -> Snoop -> Response -> Data.  Phases of
// different transactions overlap; the phases of one transaction never do.
// With ADS# asserted in T1 the fixed skeleton is [PPRO1] 4.4.3.2 / 4.5.2.1:
//
//   T1  Request clock A   ADS# low.  A[35:3]# = address, REQ[4:0]# = type
//   T2  Request clock B   ADS# high. A# = ATTR/DID/BE/EXF, REQ# = DSZ/LEN
//   T4  Error phase       AERR#, fixed, one clock, ADS#+3.  Not wired: see
//                         README, "Deliberately left out"
//   T5  Snoop phase       HIT#/HITM#/DEFER# driven, ADS#+4, or 3 clocks after
//                         the previous transaction's snoop results, later wins
//   T7  Response phase    RS[2:0]# for one clock, then back to 000.  Earliest
//                         is two clocks after the snoop results are driven and
//                         three clocks after the previous RS[2:0]# assertion
//   T7+ Data phase        may extend past the Response Phase
//
// The Request Phase is "always one clock of active ADS# followed by one clock
// of inactive ADS#.  There is always an idle clock between request phases for
// bus turnaround" [PPRO1] 4.2.3.1 - hence at most one ADS# every three clocks.
//
// ---------------------------------------------------------------- THE STRAPS
// "P6 family processor system bus agents sample their hardware configuration
// at reset, on the active-to-inactive transition of RESET#.  The configuration
// signals (except IGNNE#, A20M# and LINT[1:0]) must be asserted 4 clocks
// before the active-to-inactive transition of RESET# and be deasserted two
// clocks after" [HWDM] 5.1.  This module drives the straps for the whole
// RESET# active window and for exactly two clocks after it, then releases.
//
//   A7#  low  -> In-order Queue depth 1 instead of 8          [HWDM] 5.1.12
//   A10# low  -> BINIT# observation enabled, which a P6 requires [HWDM] 5.1.11
//   A6#  low  -> reset vector 000FFFF0h instead of FFFFFFF0h  [HWDM] 5.1.13
//   A5#  high -> FRC disabled                                 [HWDM] 5.1.14
//   A8#/A9# high -> AERR#/BERR# observation off, so those pins may be left
//                unconnected on the board
//   A11#/A12# high -> APIC cluster ID 0                       [HWDM] 5.1.16
//   BR0# low  -> "During power-up configuration, the central agent must assert
//                the BR0# bus signal", so the CPU takes agent ID 0 [HWDM] A.1.16
//
// A line the FPGA does not drive floats to VTT through the CPU's on-die RTT,
// which is the inactive level, which is the wanted default for every strap
// above that is listed "high".  Only A7#, A10# and optionally A6# are driven.
//
// --------------------------------------------------------- RESPONSE LEGALITY
// RS[2:0]#, [PPRO1] Table 4-2 and 4.5.3.4:
//   000 Idle    001 Retry    010 Deferred    011 RESERVED
//   100 Hard Failure   101 No Data   110 Implicit Writeback   111 Normal Data
// Retry and Deferred are legal only when DEFER# was asserted in the Snoop
// Phase, and Deferred additionally only when the request agent asserted DEN#.
// This module never asserts DEFER#, so it can never legally drive 001 or 010,
// and it never drives the reserved 011.  Implicit Writeback is *required* when
// HITM# was observed, Normal Data is required when the request asked for read
// data and HITM# was inactive, No Data otherwise, Hard Failure at any time.
//
`default_nettype none

module p6_bif #(
    // BCLKs RESET# is held active.  The board value is >= 1 ms after VCCCORE
    // and BCLK are in spec [P3CU] Table 16 T10, i.e. 66667 clocks at 66 MHz.
    // Must be >= 4 so the strap window is legal.  The testbench overrides it.
    parameter integer RESET_CLKS   = 66667,
    // 1 = drive A7# low at reset -> In-order Queue depth 1.  The single
    // biggest simplification available, and the board takes it.
    parameter integer STRAP_A7_LOW = 1,
    // 1 = drive A6# low at reset -> reset vector 000FFFF0h.  Board C boots
    // from the flash window at FFFFFFF0h, so this is 0.
    parameter integer STRAP_A6_LOW = 0
) (
    input  wire        clk,          // BCLK, the very clock the CPU is fed
    input  wire        rst_n,        // FPGA-side synchronous reset, active low

    // ------------------------------------------------- AGTL+ received levels
    input  wire [35:3] a_n,
    input  wire [4:0]  req_n,
    input  wire        ads_n,
    input  wire [63:0] d_n,
    input  wire        drdy_n,
    input  wire        dbsy_n,
    input  wire        hit_n,
    input  wire        hitm_n,
    input  wire        bnr_n,
    input  wire        lock_n,
    input  wire        binit_n,

    // ------------------------------------------------ AGTL+ drive-low enables
    output wire [35:3] a_drv,        // reset straps, then the snoop transactions' Aa
    output reg  [4:0]  req_drv,      // REQa of a snoop transaction, see below
    output reg         ads_drv,
    output reg  [63:0] d_drv,        // read data back to the CPU
    output reg  [2:0]  rs_drv,
    output reg         trdy_drv,
    output reg         drdy_drv,
    output reg         dbsy_drv,
    output reg         hit_drv,      // snoop stall only, always with hitm_drv
    output reg         hitm_drv,
    output reg         bnr_drv,
    output reg         bpri_drv,
    output reg         br0_drv,
    output reg         reset_drv,
    output wire        defer_drv,    // constant 0, see the header
    output wire        binit_drv,    // constant 0, observation only

    // ------------------------------------------- north bridge memory decode
    // Combinational, no handshake, exactly the port apollo133a and i430tx
    // expose: the front end presents the address it latched in the Request
    // Phase and reads the answer in the same clock.  mem_cacheable is NOT
    // taken: the P6 bus has no KEN#, the CPU's own MTRRs decide what is
    // cacheable, and the chipset has no say.  See README.
    output wire [31:0] mem_addr,
    output wire        mem_we,
    input  wire        mem_sel_dram,
    input  wire        mem_sel_pci,

    // ----------------------------------------------- north bridge I/O port
    // Single-clock strobe with a combinational answer, right-justified at
    // io_addr, again exactly apollo133a's port.  io_hit low means the north
    // bridge did not claim the port and the cycle is forwarded through the
    // host bus below with host_io set.
    output reg         io_stb,
    output reg         io_we,
    output reg  [15:0] io_addr,
    output reg  [1:0]  io_size,      // 0 = byte, 1 = word, 2 = dword
    output reg  [31:0] io_wdata,     // right-justified at io_addr
    input  wire [31:0] io_rdata,     // right-justified at io_addr
    input  wire        io_hit,

    // ---------------------------------------------------- internal host bus
    // THE CONTRACT IS rtl/HOSTPORT.md, and is not restated here.  This master
    // is registered, so host_req stands through the acknowledge clock (C3),
    // and it takes host_rvalid in that same clock or any clock after it (C6) -
    // see the read-answer block after the service engine's case.  64 bits wide
    // because that is the P6 data bus; a 32-byte line arrives as four
    // sequential accesses in P6 burst order.  Data is on its natural byte
    // lanes here, selected by host_be - only the io_* port is right-justified.
    output reg         host_req,
    output reg         host_we,
    output reg  [35:3] host_addr,    // quadword address, i.e. A[35:3]#;
                                     // for an I/O cycle [15:3] is the port
    output reg  [63:0] host_wdata,
    output reg  [7:0]  host_be,      // 1 = that byte lane is live
    output wire        host_dram,    // 1 = SDRAM, straight from mem_sel_dram
    output reg         host_io,      // 1 = an I/O cycle the north bridge
                                     //     did not claim
    output reg  [2:0]  host_attr,    // ATTR[2:0]#: 000 UC 100 WC 101 WT
                                     //             110 WP 111 WB
    output reg         host_dc,      // 1 = data, 0 = code fetch
    output reg         host_lock,    // LOCK# was active for this transaction
    output reg         host_smmem,   // SMMEM# = A[7]# in request clock B
    input  wire        host_ready,
    input  wire [63:0] host_rdata,
    input  wire        host_rvalid,
    input  wire        host_err,     // sampled with host_ready: Hard Failure

    // ------------------------------------------------------------- events
    // Special Transactions and Interrupt Acknowledge do not go through the
    // host bus: they are one-clock events.  Answering every Special
    // Transaction is mandatory - Linux idles with HLT, so Halt arrives
    // continuously and a missed one wedges the processor.
    output reg         spc_stb,      // one clock, with spc_type valid
    output reg  [2:0]  spc_type,     // SPC_* below, = BE[2:0]# [HWDM] Tbl A-3
    output reg         inta_stb,     // one clock per Interrupt Acknowledge
    input  wire [7:0]  inta_vector,  // must be continuously valid

    // ------------------------------------------------------------ arbitration
    // Priority-agent arbitration, for the NIC DMA master that coherency forces
    // this board to have (see README).  dma_gnt means the bus is ours; snp_ok
    // means it is ours AND the line at snp_line has been snooped for this
    // access (snp_inv = a DMA write), so the access may go to memory.
    input  wire        snoop_stall,  // extend the Snoop Phase by two clocks
    input  wire        dma_req,
    output reg         dma_gnt,
    input  wire [35:5] snp_line,
    input  wire        snp_inv,
    output wire        snp_ok,

    // ----------------------------------------------------------------- status
    output reg         cpu_ready,    // reset done and BNR# seen idle twice
    output wire [8:0]  err           // sticky protocol violations, ERR_* below
);

    // ---------------------------------------------------------------------
    // Configuration derived from the straps.  One knob: the queue depth here
    // cannot disagree with the pin the CPU samples, because both come from the
    // same parameter.  A7# low means an In-order Queue depth of 1, otherwise 8
    // [HWDM] 5.1.12, so IOQ_LAST/IOQ_MAX are 0/1 or 7/8.
    // ---------------------------------------------------------------------
    localparam [2:0]   IOQ_LAST  = (STRAP_A7_LOW != 0) ? 3'd0 : 3'd7;
    localparam [3:0]   IOQ_MAX   = (STRAP_A7_LOW != 0) ? 4'd1 : 4'd8;
    localparam [31:0]  RST_LIMIT = RESET_CLKS;

    // Internal transaction classes.  Not a port: what leaves this module is
    // io_stb / host_io / spc_stb / inta_stb.
    localparam [2:0] TC_MEM     = 3'd0;
    localparam [2:0] TC_IO      = 3'd1;
    localparam [2:0] TC_SPECIAL = 3'd2;
    localparam [2:0] TC_INTACK  = 3'd3;
    localparam [2:0] TC_BTM     = 3'd4;

    // spc_type is the Special Transaction sub-code carried on BE[7:0]#,
    // [HWDM] Table A-3.  Note these are plain binary codes; the P5 bus in
    // rtl/cpu_p5 uses a one-hot encoding with different numbers.
    // 1 Shutdown  2 Flush  3 Halt  4 Sync  5 Flush Ack  6 Stop Clock Ack
    // 7 SMI Ack.  0 and 8..255 are reserved and raise ERR_RSVD.

    // err bit positions
    // 0 ERR_ADS2      ADS# active two clocks running
    // 1 ERR_RATE      less than 3 clocks between ADS# assertions
    // 2 ERR_IOQ       ADS# while the in-order queue is already full
    // 3 ERR_RSVD      reserved REQ[4:0]# / DSZ / LEN encoding, or a
    //                 reserved Special Transaction sub-code on BE[7:0]#
    // 4 ERR_DEFREP    a Deferred Reply arrived, but DEFER# is never asserted
    // 5 ERR_BINIT     BINIT# observed asserted
    // 6 ERR_HARDFAIL  a Hard Failure response was driven
    // 7 ERR_IWBWR     HITM# on a transaction that also carries write data
    // 8 ERR_DECODE    the north bridge decoded a memory address to both DRAM
    //                 and PCI, or to neither

    // ---------------------------------------------------------------------
    // Pin levels to positive logic.  Done once, here, and nowhere else.
    // ---------------------------------------------------------------------
    wire [35:3] a_in     = ~a_n;
    wire [4:0]  req_in   = ~req_n;
    wire        ads_in   = ~ads_n;
    wire [63:0] d_in     = ~d_n;
    wire        drdy_in  = ~drdy_n;
    wire        dbsy_in  = ~dbsy_n;
    wire        hit_in   = ~hit_n;
    wire        hitm_in  = ~hitm_n;
    wire        bnr_in   = ~bnr_n;
    wire        lock_in  = ~lock_n;
    wire        binit_in = ~binit_n;

    assign defer_drv = 1'b0;
    assign binit_drv = 1'b0;

    // Forward declarations shared between the always blocks below.
    reg  [2:0] ioq_rd;
    reg        pop_ent;
    reg        req_b;
    reg  [3:0] ioq_cnt;
    reg        run;
    reg        own_done;    // the service engine retired our snoop transaction
    reg  [1:0] g_st;        // the snoop transaction generator, at the end

    // ---------------------------------------------------------------------
    // Reset sequencing and the power-on configuration straps
    // ---------------------------------------------------------------------
    wire [35:3] straps = { 23'b0,                                 // A[35:13]#
                           1'b0,                                  // A12# cluster 0
                           1'b0,                                  // A11# cluster 0
                           1'b1,                                  // A10# BINIT# obs
                           1'b0,                                  // A9#  BERR# off
                           1'b0,                                  // A8#  AERR# off
                           (STRAP_A7_LOW != 0) ? 1'b1 : 1'b0,     // A7#  IOQ depth
                           (STRAP_A6_LOW != 0) ? 1'b1 : 1'b0,     // A6#  reset vec
                           1'b0,                                  // A5#  no FRC
                           1'b0,                                  // A4#
                           1'b0 };                                // A3#

    localparam [1:0] R_ASSERT = 2'd0,   // RESET# low, straps driven
                     R_HOLD   = 2'd1,   // RESET# released, straps held 2 clocks
                     R_WAIT   = 2'd2,   // straps released, waiting for BNR# idle
                     R_RUN    = 2'd3;

    reg [1:0]  rstate;
    reg [31:0] rst_cnt;
    reg [1:0]  hold_cnt;
    reg [1:0]  bnr_idle;
    reg        f_binit;
    reg [35:3] strap_drv;

    always @(posedge clk) begin
        if (!rst_n) begin
            rstate    <= R_ASSERT;
            rst_cnt   <= 32'd0;
            hold_cnt  <= 2'd0;
            bnr_idle  <= 2'd0;
            reset_drv <= 1'b1;
            br0_drv   <= 1'b1;
            strap_drv <= straps;
            run       <= 1'b0;
            cpu_ready <= 1'b0;
            f_binit   <= 1'b0;
        end else begin
            if (binit_in) f_binit <= 1'b1;
            case (rstate)
            R_ASSERT: begin
                // RESET# active.  The straps are driven for the whole window,
                // far more than the 4 clocks [HWDM] 5.1 demands.
                reset_drv <= 1'b1;
                br0_drv   <= 1'b1;
                strap_drv <= straps;
                if (rst_cnt >= RST_LIMIT - 32'd1) begin
                    reset_drv <= 1'b0;          // the active-to-inactive edge
                    rstate    <= R_HOLD;
                    hold_cnt  <= 2'd0;
                end else begin
                    rst_cnt <= rst_cnt + 32'd1;
                end
            end
            R_HOLD: begin
                // Exactly two clocks of strap hold after RESET# went inactive.
                if (hold_cnt == 2'd1) begin
                    strap_drv <= 33'd0;
                    br0_drv  <= 1'b0;
                    rstate   <= R_WAIT;
                    bnr_idle <= 2'd0;
                end else begin
                    hold_cnt <= hold_cnt + 2'd1;
                end
            end
            R_WAIT: begin
                // "each processor begins active BNR# sequencing from RESET#'s
                // active-to-inactive transition until it is able to accept bus
                // transactions": wait for two consecutive idle samples.
                if (bnr_in) begin
                    bnr_idle <= 2'd0;
                end else if (bnr_idle == 2'd1) begin
                    rstate    <= R_RUN;
                    run       <= 1'b1;
                    cpu_ready <= 1'b1;
                end else begin
                    bnr_idle <= bnr_idle + 2'd1;
                end
            end
            default: begin
                run       <= 1'b1;
                cpu_ready <= 1'b1;
            end
            endcase
        end
    end

    // ---------------------------------------------------------------------
    // The in-order queue.  Eight slots are declared unconditionally; with
    // IOQ_DEPTH 1 the pointers provably never leave zero, so synthesis trims
    // the other seven.
    // ---------------------------------------------------------------------
    reg  [7:0]  q_val;
    reg  [7:0]  q_snp;           // Snoop Phase complete
    reg  [7:0]  q_hitm;          // HITM# was observed for this transaction
    reg  [3:0]  q_age   [0:7];   // clocks since ADS#, saturating
    reg  [35:3] q_addr  [0:7];
    reg  [7:0]  q_be    [0:7];
    reg  [2:0]  q_boff  [0:7];
    reg  [1:0]  q_size  [0:7];
    reg  [2:0]  q_attr  [0:7];
    reg  [2:0]  q_type  [0:7];
    reg  [2:0]  q_n     [0:7];   // data chunks, 0..4
    reg         q_rd    [0:7];   // we owe read data
    reg         q_wr    [0:7];   // it carries request-initiated write data
    reg         q_dc    [0:7];
    reg         q_lock  [0:7];
    reg         q_smmem [0:7];
    reg  [2:0]  q_scode [0:7];   // Special Transaction sub-code, BE[2:0]#
    reg         q_own   [0:7];   // our own snoop transaction

    reg  [2:0]  ioq_wr, snp_rd;

    wire [2:0] ioq_wr_nx = (ioq_wr == IOQ_LAST) ? 3'd0 : ioq_wr + 3'd1;
    wire [2:0] ioq_rd_nx = (ioq_rd == IOQ_LAST) ? 3'd0 : ioq_rd + 3'd1;
    wire [2:0] snp_rd_nx = (snp_rd == IOQ_LAST) ? 3'd0 : snp_rd + 3'd1;
    wire       ioq_full  = (ioq_cnt >= IOQ_MAX);

    // ---------------------------------------------------------------------
    // Byte-enable helpers.  These build io_addr's low three bits and io_size
    // directly, so the north bridge's I/O port wires straight to this module
    // with no decoder in between.
    // ---------------------------------------------------------------------
    function [2:0] be_low;
        input [7:0] b;
        begin
            casez (b)
            8'b???????1: be_low = 3'd0;
            8'b??????10: be_low = 3'd1;
            8'b?????100: be_low = 3'd2;
            8'b????1000: be_low = 3'd3;
            8'b???10000: be_low = 3'd4;
            8'b??100000: be_low = 3'd5;
            8'b?1000000: be_low = 3'd6;
            8'b10000000: be_low = 3'd7;
            default:     be_low = 3'd0;
            endcase
        end
    endfunction

    function [1:0] be_size;
        input [7:0] b;
        integer j;
        integer c;
        begin
            c = 0;
            for (j = 0; j < 8; j = j + 1) if (b[j]) c = c + 1;
            case (c)
            1:       be_size = 2'd0;
            2:       be_size = 2'd1;
            8:       be_size = 2'd3;
            default: be_size = 2'd2;
            endcase
        end
    endfunction

    // ---------------------------------------------------------------------
    // Request Phase: two clocks, heavily multiplexed
    // ---------------------------------------------------------------------
    reg [4:0]   reqa_q;
    reg [35:3]  addr_q;
    reg         lock_q;
    reg         own_q;            // the ADS# on the pins was ours
    reg [1:0]   ads_gap;          // clocks since the last ADS#, saturating at 3
    reg         f_ads2, f_rate, f_ioq, f_rsvd, f_defrep;

    // Clock B fields [HWDM] Appendix A, [CLAUDE]
    wire [2:0] attr_b  = a_in[26:24];       // ATTR[2:0]# inside Ab[31:24]#
    wire [7:0] be_b    = a_in[15:8];        // BE[7:0]#
    wire       smmem_b = a_in[7];           // EXF[4:0]#: SMMEM# is A[7]#
    wire [1:0] len_b   = req_in[1:0];       // REQb[1:0]# = LEN[1:0]#
    wire [1:0] dsz_b   = req_in[4:3];       // REQb[4:3]# = DSZ[1:0]#, always 00

    // Transaction decode, [HWDM] Table A-7 read from the PDF on this machine.
    // REQa alone is not enough: the 01000 group splits into Interrupt
    // Acknowledge and Special Transactions on REQb[0]#, and 01001 into Branch
    // Trace Message and two reserved central-agent codes the same way.
    wire reqa_central = (reqa_q[4:3] == 2'b01) && (reqa_q[2:1] == 2'b00);
    wire reqa_io      = (reqa_q[4:3] == 2'b10) && (reqa_q[2:1] == 2'b00);
    wire reqa_mem     = (reqa_q[2:1] != 2'b00);
    wire is_defrep    = (reqa_q == 5'b00000);
    wire is_intack    = reqa_central && !reqa_q[0] && (len_b == 2'b00);
    wire is_special   = reqa_central && !reqa_q[0] && (len_b == 2'b01);
    wire is_btm       = reqa_central &&  reqa_q[0] && (len_b == 2'b00);
    wire is_write     = reqa_q[0];          // REQa0# for both memory and I/O
    wire b_rsvd       = (dsz_b != 2'b00) || is_defrep ||
                        (!is_defrep && !reqa_central && !reqa_io && !reqa_mem) ||
                        (reqa_central && !is_intack && !is_special && !is_btm) ||
                        (is_special && ((be_b == 8'd0) || (be_b > 8'd7))) ||
                        ((reqa_io || reqa_mem) && (len_b == 2'b11));

    // LEN[1:0]#: 00 = 0-8 bytes, 01 = 16, 10 = 32 [HWDM] Table A-6.
    // "If no bytes are enabled, then a No Data Response" [PPRO1] 4.5.3.
    wire [2:0] len_chunks = (len_b == 2'b10) ? 3'd4 :
                            (len_b == 2'b01) ? 3'd2 :
                            (be_b == 8'd0)   ? 3'd0 : 3'd1;

    reg [2:0] new_type;
    reg [2:0] new_n;
    reg [2:0] new_boff;
    reg [1:0] new_size;
    reg       new_rd;
    reg       new_wr;

    always @(*) begin
        new_type = TC_MEM;
        new_n    = 3'd0;
        new_rd   = 1'b0;
        new_wr   = 1'b0;
        new_boff = 3'd0;
        new_size = 2'd3;
        if (is_intack) begin
            // A one-byte interrupt vector on D[7:0]#.  The length is fixed,
            // not taken from BE[7:0]#, because BE is not a byte-enable field
            // for the 01000 group.
            new_type = TC_INTACK;  new_n = 3'd1;  new_rd = 1'b1;
            new_size = 2'd0;
        end else if (is_special) begin
            new_type = TC_SPECIAL; new_n = 3'd0;
        end else if (is_btm) begin
            new_type = TC_BTM;     new_n = 3'd1;  new_wr = 1'b1;
        end else if (reqa_io || reqa_mem) begin
            new_type = reqa_io ? TC_IO : TC_MEM;
            new_n    = len_chunks;
            new_rd   = !is_write && (len_chunks != 3'd0);
            new_wr   =  is_write && (len_chunks != 3'd0);
            new_boff = be_low(be_b);
            new_size = be_size(be_b);
        end
    end

    wire push_ent = run && !ads_in && req_b && !ioq_full;

    integer i;

    always @(posedge clk) begin
        if (!rst_n) begin
            req_b    <= 1'b0;
            ads_gap  <= 2'd3;
            ioq_wr   <= 3'd0;
            q_val    <= 8'd0;
            f_ads2   <= 1'b0;
            f_rate   <= 1'b0;
            f_ioq    <= 1'b0;
            f_rsvd   <= 1'b0;
            f_defrep <= 1'b0;
            reqa_q   <= 5'd0;
            addr_q   <= 33'd0;
            lock_q   <= 1'b0;
            own_q    <= 1'b0;
            for (i = 0; i < 8; i = i + 1) q_age[i] <= 4'd0;
        end else begin
            // Age every live entry: q_age[i] == T - (ADS# clock of entry i).
            for (i = 0; i < 8; i = i + 1)
                if (q_val[i] && q_age[i] != 4'd15) q_age[i] <= q_age[i] + 4'd1;

            if (!run) begin
                req_b   <= 1'b0;
                ads_gap <= 2'd3;
            end else if (ads_in) begin
                // Request clock A.
                if (req_b)               f_ads2 <= 1'b1;  // ADS# two clocks running
                else if (ads_gap < 2'd2) f_rate <= 1'b1;  // faster than 1 per 3
                if (ioq_full)            f_ioq  <= 1'b1;
                reqa_q  <= req_in;
                addr_q  <= a_in;
                lock_q  <= lock_in;
                own_q   <= ads_drv;
                req_b   <= 1'b1;
                ads_gap <= 2'd0;
            end else begin
                if (ads_gap != 2'd3) ads_gap <= ads_gap + 2'd1;
                if (req_b) begin
                    // Request clock B: decode is complete, push the entry.
                    req_b <= 1'b0;
                    if (is_defrep) f_defrep <= 1'b1;
                    if (b_rsvd)    f_rsvd   <= 1'b1;
                    if (!ioq_full) begin
                        q_val  [ioq_wr] <= 1'b1;
                        q_age  [ioq_wr] <= 4'd2;   // clock B is ADS#+1, so this
                                                   // register is read at ADS#+2
                        q_addr [ioq_wr] <= addr_q;
                        q_be   [ioq_wr] <= be_b;
                        q_boff [ioq_wr] <= new_boff;
                        q_size [ioq_wr] <= new_size;
                        q_attr [ioq_wr] <= attr_b;
                        q_type [ioq_wr] <= new_type;
                        q_n    [ioq_wr] <= new_n;
                        q_rd   [ioq_wr] <= new_rd;
                        q_wr   [ioq_wr] <= new_wr;
                        q_dc   [ioq_wr] <= reqa_q[2] ? reqa_q[1] : 1'b1;
                        q_lock [ioq_wr] <= lock_q;
                        q_smmem[ioq_wr] <= smmem_b;
                        q_scode[ioq_wr] <= be_b[2:0];
                        q_own  [ioq_wr] <= own_q;
                        ioq_wr          <= ioq_wr_nx;
                    end
                end
            end

            // The response engine retires the entry it has finished with.
            // A push and a pop can never name the same slot: a pop implies the
            // slot is still counted, and ioq_full then blocks the push.
            if (pop_ent) q_val[ioq_rd] <= 1'b0;
        end
    end

    // ---------------------------------------------------------------------
    // Snoop Phase
    //
    // "The Snoop Phase for a transaction begins 4 clocks after ADS# is driven
    // asserted or 3 clocks after the snoop results of the previous transaction
    // are driven, whichever is later" [PPRO1] 4.4.3.2.  "A slow snooping agent
    // can request a two-clock STALL in a valid Snoop Phase by activating both
    // HIT# and HITM#.  In the case of a STALL, snoop results are sampled again
    // 2 clocks after the previous sample point" [PPRO1] 4.4.3.3.
    //
    // This module is not a caching agent, so its own snoop result is always
    // CLEAN: it drives neither HIT# nor HITM# except to request that stall.
    // ---------------------------------------------------------------------
    reg [3:0] snp_gap;      // clocks since snoop results were last driven
    reg       snp_win;      // this clock is a valid snoop window
    reg       snp_stalled;  // the last window was a STALL, so the next is +2

    wire [3:0] snp_age    = q_age[snp_rd];
    wire [3:0] snp_age_nx = (snp_age == 4'd15) ? 4'd15 : snp_age + 4'd1;
    wire [3:0] snp_gap_nx = (snp_gap == 4'd15) ? 4'd15 : snp_gap + 4'd1;
    wire [3:0] snp_need   = snp_stalled ? 4'd2 : 4'd3;
    wire       snp_open   = run && q_val[snp_rd] && !q_snp[snp_rd] &&
                            (snp_age_nx >= 4'd4) && (snp_gap_nx >= snp_need);

    always @(posedge clk) begin
        if (!rst_n) begin
            snp_gap     <= 4'd15;
            snp_win     <= 1'b0;
            snp_stalled <= 1'b0;
            snp_rd      <= 3'd0;
            q_snp       <= 8'd0;
            q_hitm      <= 8'd0;
            hit_drv     <= 1'b0;
            hitm_drv    <= 1'b0;
        end else begin
            // Sample the results of the window that is ending now.
            if (snp_win) begin
                if (hit_in && hitm_in) begin
                    snp_stalled <= 1'b1;             // STALL: extend by 2 clocks
                end else begin
                    q_snp [snp_rd] <= 1'b1;
                    q_hitm[snp_rd] <= hitm_in;
                    snp_rd         <= snp_rd_nx;
                    snp_stalled    <= 1'b0;
                end
            end
            // Open the next window, and drive the stall inside it if asked.
            snp_win  <= snp_open;
            hit_drv  <= snp_open && snoop_stall;
            hitm_drv <= snp_open && snoop_stall;
            snp_gap  <= snp_open ? 4'd0 : snp_gap_nx;
            if (pop_ent) begin
                q_snp [ioq_rd] <= 1'b0;
                q_hitm[ioq_rd] <= 1'b0;
            end
        end
    end

    // ---------------------------------------------------------------------
    // Service engine, Response Phase and Data Phase
    //
    // One internal context: requests pipeline on the bus, the internal
    // accesses behind them do not.  See README, "Deliberate deviations".
    // ---------------------------------------------------------------------
    localparam [3:0] S_IDLE  = 4'd0,
                     S_RDREQ = 4'd1,   // drive the host read for chunk k
                     S_RDWT  = 4'd2,   // read accepted, host_rvalid still owed
                     S_TRDY  = 4'd3,   // assert TRDY#, wait for the CPU's data
                     S_WDAT  = 4'd4,   // collecting the CPU's write chunks
                     S_WRREQ = 4'd5,   // push chunk k to the host
                     S_IOX   = 4'd6,   // io_stb for one clock, io_hit sampled
                     S_RESP  = 4'd7,   // wait for the response window
                     S_DATA  = 4'd8,   // streaming read data after RS[2:0]#
                     S_IWBT  = 4'd9,   // implicit writeback: snoop-initiated TRDY#
                     S_IWBD  = 4'd10,  // implicit writeback: take a chunk
                     S_IWBW  = 4'd11,  // implicit writeback: push it to the host
                     S_SPC   = 4'd12;  // one-clock Special Transaction strobe

    reg [3:0]   st;
    reg [2:0]   k;              // chunk index inside the transaction
    reg [63:0]  buf0, buf1, buf2, buf3;
    reg         fail;           // host_err seen: drive Hard Failure
    reg [3:0]   rs_gap;         // clocks since RS[2:0]# was last asserted
    reg [2:0]   dat_k, dat_n;   // read-data streamer
    reg [35:3]  iwb_addr;       // address of the line being written back
    reg         iwb_own;        // ... for our own snoop transaction
    reg         f_hard, f_iwbwr, f_decode;

    // Head-of-queue aliases.  Verilog-2001 has no part-select of an array
    // element, so every field is pulled out into a wire first.
    wire [2:0]  h        = ioq_rd;
    wire        h_val    = q_val[h];
    wire        h_snp    = q_snp[h];
    wire        h_hitm   = q_hitm[h];
    wire [3:0]  h_age    = q_age[h];
    wire [35:3] h_addr   = q_addr[h];
    wire [7:0]  h_be     = q_be[h];
    wire [2:0]  h_boff   = q_boff[h];
    wire [1:0]  h_size   = q_size[h];
    wire [2:0]  h_attr   = q_attr[h];
    wire [2:0]  h_type   = q_type[h];
    wire [2:0]  h_n      = q_n[h];
    wire        h_rd     = q_rd[h];
    wire        h_wr     = q_wr[h];
    wire        h_dc     = q_dc[h];
    wire        h_lock   = q_lock[h];
    wire        h_smmem  = q_smmem[h];
    wire [2:0]  h_scode  = q_scode[h];
    wire        h_own    = q_own[h];

    // Line burst order: chunk k of a transaction based at A[4:3]# = s is at
    // s ^ k, i.e. 00 -> 0,8,10,18   01 -> 8,0,18,10   10 -> 10,18,0,8
    // 11 -> 18,10,8,0.  [PPRO1] 4.6, [CLAUDE].  The P5 bus uses exactly the
    // same n, n^1, n^2, n^3 order, which is why rtl/chipset/i430tx says so too.
    wire [35:3] caddr     = { h_addr[35:5], h_addr[4:3] ^ k[1:0] };
    wire [35:3] iwb_caddr = { iwb_addr[35:5], iwb_addr[4:3] ^ k[1:0] };

    // The clock in which a read chunk is accepted.  host_err is sampled with
    // host_ready and means no data will come back at all, so an errored
    // acceptance is not a read answer.
    wire rd_acc = (st == S_RDREQ) && host_req && host_ready && !host_err;

    // The io_* port is right-justified at io_addr, which is apollo133a's and
    // i430tx's documented convention.  Everything on the host bus stays on its
    // natural byte lanes, selected by host_be, which the host port wants.
    wire [5:0]  shf      = { h_boff, 3'b000 };
    wire [63:0] chunk_k  = (k == 3'd0) ? buf0 :
                           (k == 3'd1) ? buf1 :
                           (k == 3'd2) ? buf2 : buf3;
    wire [63:0] dat_out  = (dat_k == 3'd0) ? buf0 :
                           (dat_k == 3'd1) ? buf1 :
                           (dat_k == 3'd2) ? buf2 : buf3;

    // Write data right-justified for the north bridge's I/O port.  An I/O
    // access is at most 4 bytes wide but can start on any of the 8 lanes, so
    // the shift is 64 bits wide and only the bottom dword survives.
    function [31:0] rj32;
        input [63:0] v;
        input [2:0]  off;
        begin
            case (off)
            3'd0:    rj32 = v[31:0];
            3'd1:    rj32 = v[39:8];
            3'd2:    rj32 = v[47:16];
            3'd3:    rj32 = v[55:24];
            3'd4:    rj32 = v[63:32];
            3'd5:    rj32 = { 8'd0,  v[63:40] };
            3'd6:    rj32 = { 16'd0, v[63:48] };
            default: rj32 = { 24'd0, v[63:56] };
            endcase
        end
    endfunction
    wire [31:0] io_wdata_rj = rj32(buf0, h_boff);

    // Where a transaction goes once its write data has been collected.
    wire [3:0] after_wdata = (h_type == TC_IO)  ? S_IOX  :
                             (h_type == TC_BTM) ? S_RESP : S_WRREQ;

    // The north bridge memory decode looks at the access being presented.
    assign mem_addr  = { host_addr[31:3], 3'b000 };
    assign mem_we    = host_we;
    assign host_dram = host_req && !host_io && mem_sel_dram;

    // The response may be driven in the clock after all of these hold.
    wire resp_go = (st == S_RESP) && h_val && h_snp && (rs_gap >= 4'd2) &&
                   (!(h_rd && !fail) || !dbsy_in);

    // Response encoding [PPRO1] Table 4-2 / 4.5.3.4.
    wire [2:0] resp_code = fail                    ? 3'b100 :  // Hard Failure
                           (h_rd && (h_n != 3'd0)) ? 3'b111 :  // Normal Data
                                                     3'b101;   // No Data

    always @(posedge clk) begin
        if (!rst_n) begin
            st         <= S_IDLE;
            k          <= 3'd0;
            buf0       <= 64'd0;
            buf1       <= 64'd0;
            buf2       <= 64'd0;
            buf3       <= 64'd0;
            fail       <= 1'b0;
            rs_gap     <= 4'd15;
            dat_k      <= 3'd0;
            dat_n      <= 3'd0;
            iwb_addr   <= 33'd0;
            iwb_own    <= 1'b0;
            own_done   <= 1'b0;
            pop_ent    <= 1'b0;
            ioq_rd     <= 3'd0;
            ioq_cnt    <= 4'd0;
            host_req   <= 1'b0;
            host_we    <= 1'b0;
            host_addr  <= 33'd0;
            host_wdata <= 64'd0;
            host_be    <= 8'd0;
            host_io    <= 1'b0;
            host_attr  <= 3'd0;
            host_dc    <= 1'b0;
            host_lock  <= 1'b0;
            host_smmem <= 1'b0;
            io_stb     <= 1'b0;
            io_we      <= 1'b0;
            io_addr    <= 16'd0;
            io_size    <= 2'd0;
            io_wdata   <= 32'd0;
            spc_stb    <= 1'b0;
            spc_type   <= 3'd0;
            inta_stb   <= 1'b0;
            f_decode   <= 1'b0;
            rs_drv     <= 3'b000;
            trdy_drv   <= 1'b0;
            drdy_drv   <= 1'b0;
            dbsy_drv   <= 1'b0;
            d_drv      <= 64'd0;
            f_hard     <= 1'b0;
            f_iwbwr    <= 1'b0;
        end else begin
            // ---- in-order queue accounting -----------------------------
            pop_ent  <= 1'b0;
            own_done <= 1'b0;
            case ({ push_ent, pop_ent })
            2'b10:   ioq_cnt <= ioq_cnt + 4'd1;
            2'b01:   ioq_cnt <= ioq_cnt - 4'd1;
            default: ioq_cnt <= ioq_cnt;
            endcase
            if (pop_ent) ioq_rd <= ioq_rd_nx;

            // ---- RS[2:0]# and the event strobes are one clock wide ------
            rs_drv   <= 3'b000;
            spc_stb  <= 1'b0;
            inta_stb <= 1'b0;
            if (rs_gap != 4'd15) rs_gap <= rs_gap + 4'd1;

            // ---- the north bridge must decode a memory access to exactly
            //      one target; sel_dram and sel_pci are complements
            if (host_req && !host_io && (mem_sel_dram == mem_sel_pci))
                f_decode <= 1'b1;

            case (st)
            // ------------------------------------------------ pick up work
            S_IDLE: begin
                fail <= 1'b0;
                k    <= 3'd0;
                if (h_val && !pop_ent) begin
                    case (h_type)
                    TC_SPECIAL: st <= S_SPC;
                    TC_INTACK:  begin
                        // The vector is a continuously valid input, so there
                        // is nothing to fetch: latch it and answer.
                        buf0     <= { 56'd0, inta_vector };
                        inta_stb <= 1'b1;
                        st       <= S_RESP;
                    end
                    TC_IO:      st <= (h_n == 3'd0) ? S_RESP :
                                      (h_wr ? S_TRDY : S_IOX);
                    TC_BTM:     st <= S_TRDY;
                    default:    st <= h_wr ? S_TRDY : (h_rd ? S_RDREQ : S_RESP);
                    endcase
                end
            end

            // ---------------------------------------------- read from host
            S_RDREQ: begin
                host_req   <= 1'b1;
                host_we    <= 1'b0;
                host_io    <= (h_type == TC_IO);
                host_addr  <= caddr;
                host_be    <= (h_n == 3'd1) ? h_be : 8'hFF;
                host_attr  <= h_attr;
                host_dc    <= h_dc;
                host_lock  <= h_lock;
                host_smmem <= h_smmem;
                if (host_req && host_ready) begin
                    host_req <= 1'b0;
                    if (host_err) begin
                        fail <= 1'b1;
                        st   <= S_RESP;   // no read data will come back
                    end else begin
                        st   <= S_RDWT;
                    end
                end
            end
            // The answer itself is taken after the case, because it may
            // arrive in the acceptance clock instead of a later one; this
            // state is only where the machine waits for a later one.
            S_RDWT: ;

            // ---------------------------------------------- write data in
            // Request-initiated TRDY# for transaction n: at least 3 clocks
            // after ADS# of n and at least 1 clock after RS[2:0]# of n-1.
            // [PPRO1] 4.5.3.1
            S_TRDY: begin
                if (!trdy_drv) begin
                    if ((h_age >= 4'd2) && (rs_gap >= 4'd1)) trdy_drv <= 1'b1;
                end else if (drdy_in && !drdy_drv) begin
                    // The first chunk is on the bus in the clock DRDY# is
                    // sampled, so it is captured here.
                    trdy_drv <= 1'b0;
                    buf0     <= d_in;
                    if (h_n == 3'd1) begin
                        k  <= 3'd0;
                        st <= after_wdata;
                    end else begin
                        k  <= 3'd1;
                        st <= S_WDAT;
                    end
                end
            end
            S_WDAT: if (drdy_in && !drdy_drv) begin
                case (k)
                3'd1:    buf1 <= d_in;
                3'd2:    buf2 <= d_in;
                default: buf3 <= d_in;
                endcase
                if (k + 3'd1 >= h_n) begin
                    k  <= 3'd0;
                    st <= after_wdata;
                end else begin
                    k <= k + 3'd1;
                end
            end
            S_WRREQ: begin
                host_req   <= 1'b1;
                host_we    <= 1'b1;
                host_io    <= (h_type == TC_IO);
                host_addr  <= caddr;
                host_wdata <= chunk_k;
                host_be    <= (h_n == 3'd1) ? h_be : 8'hFF;
                host_attr  <= h_attr;
                host_dc    <= h_dc;
                host_lock  <= h_lock;
                host_smmem <= h_smmem;
                if (host_req && host_ready) begin
                    host_req <= 1'b0;
                    if (host_err) begin
                        fail <= 1'b1;
                        st   <= S_RESP;
                    end else if (k + 3'd1 >= h_n) begin
                        st   <= S_RESP;
                    end else begin
                        k    <= k + 3'd1;
                    end
                end
            end

            // --------------------------------------------- north bridge I/O
            // One clock of io_stb, then io_hit and io_rdata are sampled.  A
            // miss is forwarded through the host bus with host_io set, which
            // is how the RTL8139's I/O BAR and the UART get reached.
            S_IOX: begin
                if (!io_stb) begin
                    io_stb   <= 1'b1;
                    io_we    <= h_wr;
                    io_addr  <= { h_addr[15:3], h_boff };
                    io_size  <= h_size;
                    io_wdata <= io_wdata_rj;
                end else begin
                    io_stb <= 1'b0;
                    if (io_hit) begin
                        if (!h_wr) buf0 <= { 32'd0, io_rdata } << shf;
                        st <= S_RESP;
                    end else begin
                        k  <= 3'd0;
                        st <= h_wr ? S_WRREQ : S_RDREQ;
                    end
                end
            end

            // -------------------------------------- Special Transaction out
            S_SPC: begin
                spc_stb  <= 1'b1;
                spc_type <= h_scode;
                st       <= S_RESP;
            end

            // --------------------------------------------- Response Phase
            S_RESP: begin
                if (h_val && h_snp && h_hitm && !fail) begin
                    // Implicit Writeback is a required response, not a choice.
                    if (h_wr) f_iwbwr <= 1'b1;   // not implemented, see README
                    iwb_addr <= h_addr;
                    iwb_own  <= h_own;
                    st       <= S_IWBT;
                end else if (resp_go) begin
                    rs_drv   <= resp_code;
                    rs_gap   <= 4'd0;
                    pop_ent  <= 1'b1;
                    own_done <= h_own;      // No Data: nothing more to wait for
                    if (fail) f_hard <= 1'b1;
                    if (!fail && h_rd && (h_n != 3'd0)) begin
                        // Normal Data: the response clock is also the first
                        // data clock.  DBSY# is not needed for one chunk.
                        d_drv    <= buf0;
                        drdy_drv <= 1'b1;
                        dbsy_drv <= (h_n > 3'd1);
                        dat_k    <= 3'd1;
                        dat_n    <= h_n;
                        st       <= (h_n > 3'd1) ? S_DATA : S_IDLE;
                    end else begin
                        st <= S_IDLE;
                    end
                end
            end
            S_DATA: begin
                d_drv    <= dat_out;
                drdy_drv <= 1'b1;
                // "Multi-clock data transfers begin with assertion of DBSY#
                // and complete with deassertion of DBSY# no sooner than one
                // clock prior to the last data transfer" [PPRO1] 4.6.3.1
                dbsy_drv <= (dat_k + 3'd1 < dat_n);
                if (dat_k + 3'd1 >= dat_n) begin
                    dat_k <= 3'd0;
                    st    <= S_IDLE;
                end else begin
                    dat_k <= dat_k + 3'd1;
                end
            end

            // ------------------------------------- Implicit Writeback path
            // "The response agent may assert TRDY# as early as [snoop+2] ...
            // The response agent must drive the response on RS[2:0]# in [the]
            // clock after the active TRDY# for an implicit writeback and
            // inactive DBSY# is sampled.  Note that the response must be
            // driven in the same clock that the data transfer begins."
            // [PPRO1] 4.6.2.3
            S_IWBT: begin
                if (!trdy_drv) begin
                    if (rs_gap >= 4'd1) trdy_drv <= 1'b1;
                end else if (!dbsy_in) begin
                    trdy_drv <= 1'b0;
                    rs_drv   <= 3'b110;
                    rs_gap   <= 4'd0;
                    pop_ent  <= 1'b1;
                    k        <= 3'd0;
                    st       <= S_IWBD;
                end
            end
            S_IWBD: if (drdy_in && !drdy_drv) begin
                // The modified line arrives on four consecutive clocks.
                case (k)
                3'd0:    buf0 <= d_in;
                3'd1:    buf1 <= d_in;
                3'd2:    buf2 <= d_in;
                default: buf3 <= d_in;
                endcase
                if (k >= 3'd3) begin
                    k  <= 3'd0;
                    st <= S_IWBW;
                end else begin
                    k <= k + 3'd1;
                end
            end
            S_IWBW: begin
                // Write it through to memory, chunk by chunk.
                host_req   <= 1'b1;
                host_we    <= 1'b1;
                host_io    <= 1'b0;
                host_addr  <= iwb_caddr;
                host_wdata <= chunk_k;
                host_be    <= 8'hFF;
                host_attr  <= 3'b111;      // a writeback line is WB by definition
                host_dc    <= 1'b1;
                host_lock  <= 1'b0;
                host_smmem <= 1'b0;
                if (host_req && host_ready) begin
                    host_req <= 1'b0;
                    if (k >= 3'd3) begin
                        st       <= S_IDLE;
                        own_done <= iwb_own;   // the line is in memory now
                    end else begin
                        k <= k + 3'd1;
                    end
                end
            end

            default: st <= S_IDLE;
            endcase

            // ---------------------------------------------- the read answer
            // rtl/HOSTPORT.md C6: host_rvalid may be in the SAME clock as the
            // host_ready that accepted the read, or any number of clocks
            // after it.  Both are taken here - rd_acc is the acceptance
            // clock, S_RDWT is every clock after it - so there is exactly one
            // copy of the capture and neither latency can be forgotten.
            // These assignments come after the case, so where they disagree
            // with it about st, they win.
            //
            // Missing the same-clock case is not a slow read, it is a HANG:
            // the front end sits in S_RDWT for ever and the processor never
            // gets its Response Phase.  soc_dram_port and soc370_dram_port
            // both answer in the acceptance clock.
            if (host_rvalid && (rd_acc || (st == S_RDWT))) begin
                case (k)
                3'd0:    buf0 <= host_rdata;
                3'd1:    buf1 <= host_rdata;
                3'd2:    buf2 <= host_rdata;
                default: buf3 <= host_rdata;
                endcase
                if (k + 3'd1 >= h_n) begin
                    st <= S_RESP;
                end else begin
                    k  <= k + 3'd1;
                    st <= S_RDREQ;
                end
            end

            // D[63:0]#, DRDY# and DBSY# are driven only in the clocks that
            // actually carry read data.
            if ((st != S_DATA) && !((st == S_RESP) && resp_go)) begin
                drdy_drv <= 1'b0;
                dbsy_drv <= 1'b0;
                d_drv    <= 64'd0;
            end
        end
    end

    // ---------------------------------------------------------------------
    // Arbitration Phase, priority-agent side, and the BNR# throttle
    //
    // "Observing BPRI# active causes all other agents to stop issuing new
    // requests, unless such requests are part of an ongoing locked operation.
    // The priority agent keeps BPRI# asserted until all of its requests are
    // completed" [HWDM] A.1.15.  In a single-master system LOCK# can be
    // ignored except that the DMA master must not take the bus mid-lock,
    // which is the !lock_in term below.
    //
    // "When the reset condition is generated by the activation of RESET#,
    // BPRI# and BNR# must be sampled inactive together on a valid BNR#
    // sampling point, to allow new request generation by a symmetric agent"
    // [HWDM] 5.2 - hence both are gated on run.
    //
    // BNR# is asserted on alternate clocks only, never two running, because
    // it is a wire-OR signal with an edge-glitch rule [HWDM] A.1.12.  With the
    // A7# strap the CPU already limits itself to one outstanding transaction,
    // so this throttle costs nothing and exists as the backstop.
    // ---------------------------------------------------------------------
    always @(posedge clk) begin
        if (!rst_n) begin
            bpri_drv <= 1'b0;
            dma_gnt  <= 1'b0;
            bnr_drv  <= 1'b0;
        end else begin
            // Held until our own snoop transaction is complete, too.
            bpri_drv <= run && (dma_req || (g_st != 2'd0)) && (bpri_drv || !lock_in);
            dma_gnt  <= bpri_drv && (ioq_cnt == 4'd0) && !dbsy_in &&
                        !ads_in && !req_b;
            bnr_drv  <= run && ioq_full && !bnr_drv;
        end
    end

    // ---------------------------------------------------------------------
    // DMA snoop transactions, request-agent side
    //
    // The P6 bus snoops only what appears on it, so a DMA access waits (snp_ok
    // low) until its line has been snooped by a zero-length transaction of
    // ours, as a 440BX does: Memory Read & Invalidate before a DMA write (the
    // CPU's copy goes Invalid), Memory Data Read before a DMA read (it goes
    // Shared) [PPRO1] Table 3-5.  "Zero length requests (LEN = 00B and BE =
    // 00H) for read transactions ... Response must be No Data Response in the
    // absence of HITM#" [PPRO1] 5.2.1; with HITM# the CPU writes the line back
    // and the service engine puts it in memory before own_done.  Our ADS#
    // enters the in-order queue from the pins like any other, so its Snoop and
    // Response Phases are the ones above.  Clock B is all zero: DSZ, LEN, BE,
    // ATTR, DID, EXF.
    //
    // While BPRI# stays asserted the CPU issues no new request [HWDM] A.1.15,
    // so it cannot take back a line it lost or shared: one transaction per
    // line per tenure, and a read-snooped line still needs the invalidate
    // before a write.
    // ---------------------------------------------------------------------
    localparam [4:0] RQ_MRI = 5'b00010, RQ_MDR = 5'b00110;
    localparam [1:0] G_IDLE = 2'd0, G_B = 2'd1, G_WAIT = 2'd2;

    reg [35:3] gen_a;
    reg [35:5] g_line, cov_line;
    reg        g_inv, cov_inv, cov_val;

    wire covered = cov_val && (cov_line == snp_line) && (cov_inv || !snp_inv);
    assign snp_ok = dma_gnt && covered && (g_st == G_IDLE);
    assign a_drv  = strap_drv | gen_a;

    always @(posedge clk) begin
        if (!rst_n) begin
            g_st     <= G_IDLE;
            gen_a    <= 33'd0;
            req_drv  <= 5'd0;
            ads_drv  <= 1'b0;
            g_line   <= 31'd0;
            g_inv    <= 1'b0;
            cov_line <= 31'd0;
            cov_inv  <= 1'b0;
            cov_val  <= 1'b0;
        end else begin
            gen_a   <= 33'd0;
            req_drv <= 5'd0;
            ads_drv <= 1'b0;
            if (!bpri_drv) cov_val <= 1'b0;
            case (g_st)
            G_IDLE: if (dma_req && dma_gnt && !covered && (ads_gap == 2'd3) && !bnr_in) begin
                ads_drv <= 1'b1;
                req_drv <= snp_inv ? RQ_MRI : RQ_MDR;
                gen_a   <= { snp_line, 2'b00 };
                g_line  <= snp_line;
                g_inv   <= snp_inv;
                g_st    <= G_B;
            end
            G_B:    g_st <= G_WAIT;
            default: if (own_done) begin
                cov_val  <= 1'b1;
                cov_line <= g_line;
                cov_inv  <= g_inv;
                g_st     <= G_IDLE;
            end
            endcase
        end
    end

    assign err = { f_decode, f_iwbwr, f_hard, f_binit, f_defrep,
                   f_rsvd, f_ioq, f_rate, f_ads2 };

endmodule

`default_nettype wire
