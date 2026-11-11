// Socket 3 bus unit (plan/x86_core.md M8): the 486 local bus as a master, behind the core's 32-byte
// line port, plus a single-cycle port (I/O, interrupt acknowledge, special cycles, uncached memory).
// One clock, the socket's CLK. At the socket, from its rising edge [Intel DX4 write-back enhanced
// datasheet, bus operation; AMD 19751C AC table]: outputs valid 3-14 ns (floated within 20 ns);
// RDY# / BRDY# / KEN# / BOFF# / AHOLD / HOLD / read data stable from 5 ns before to 3 ns after it.
// What must follow RDY# / BRDY# / BOFF# / AHOLD in the very next clock is kept to a few registers
// fed straight from those pins: the state, BLAST# (low for a burst's fourth transfer right after
// the third BRDY#), the burst's A3-A2, ADS# (held back by AHOLD) and the three output enables. A
// pin -> logic -> pin loop across the FPGA misses that timing, so BLAST#, A3 and A2 sit on balls
// next to RDY# / BRDY# (hw/tools/gen_socket3_assign.py FAST). Everything else leaves from registers
// loaded in the idle clock before each cycle (I/O cells) and the other inputs come in through
// input registers: a cycle is IDLE, T1, T2...; HOLD is granted, and read data stored, a clock late.
// - A cycle: T1 (ADS# low, address and status), then T2 until RDY# or BRDY#; BRDY# with BLAST# high
//   goes on with the next transfer of the burst, RDY# ends the cycle. Write data is driven from
//   T1 (after the idle clock nobody else drives; its enable may then take the slow way).
// - Line read: per 16-byte block one burst from offset 0 (486 order 0-4-8-C); after a transfer ended
//   by RDY# or a back-off the rest of the block as single cycles (a burst from another offset has
//   another order). Line write: 8 single cycles (write-through towards the board: no burst write).
// - BOFF#: floats the bus in the next clock, the transfer starts again when it is released. HOLD:
//   granted between cycles (not under LOCK#). AHOLD: the address floats, no new cycle. EADS# on a
//   floated address: `snoop` with the line address (invalidation, for the caches).
// - STPCLK# with the core quiet and no job: Stop Grant special cycle (address 10h, BE2# low), then
//   no job until it is released.
// - Even parity out on DP, PCHK# the clock after a read's data is stored.
// Not yet: dynamic bus sizing (BS8# / BS16#: err_bs), the write-back protocol (HITM#, INV, the
// write-back of a line the snoop hits: the core's L2 holds dirty lines), FLUSH#, SRESET.
module s3_bus (
    input  logic         clk,
    input  logic         rst,
    // line port
    input  logic         mem_req,
    input  logic         mem_we,
    input  logic [31:5]  mem_addr,
    input  logic [255:0] mem_wdata,
    output logic         mem_ready,
    output logic         mem_rvalid,
    output logic [255:0] mem_rdata,
    output logic         mem_cacheable,   // with mem_rvalid: KEN# made both blocks line fills
    // single-cycle port: one transfer; sc_lock held from the first request to the last done
    input  logic         sc_req,
    input  logic [2:0]   sc_status,       // {M/IO#, D/C#, W/R#}
    input  logic         sc_lock,
    input  logic [31:2]  sc_addr,
    input  logic [3:0]   sc_be,           // active high
    input  logic [31:0]  sc_wdata,
    output logic         sc_ready,
    output logic         sc_done,
    output logic [31:0]  sc_rdata,
    // to the core
    input  logic         quiet,           // at an instruction boundary: Stop Grant may be issued
    output logic         stopped,
    output logic         snoop,
    output logic [31:4]  snoop_addr,
    output logic         err_bs,
    // pins; *_oe: the group is driven
    output logic [31:2]  a_o,
    output logic         a_oe,
    input  logic [31:4]  a_i,
    output logic [3:0]   be_n,
    output logic         ads_n,
    output logic         mio,
    output logic         dc,
    output logic         wr,
    output logic         blast_n,
    output logic         lock_n,
    output logic         cache_n,
    output logic         ctl_oe,
    output logic [31:0]  d_o,
    output logic [3:0]   dp_o,
    output logic         d_oe,
    input  logic [31:0]  d_i,
    input  logic [3:0]   dp_i,
    output logic         pchk_n,
    output logic         hlda,
    output logic         breq,
    input  logic         rdy_n,
    input  logic         brdy_n,
    input  logic         ken_n,
    input  logic         hold,
    input  logic         ahold,
    input  logic         boff_n,
    input  logic         eads_n,
    input  logic         a20m_n,          // asynchronous
    input  logic         stpclk_n,        // asynchronous
    input  logic         bs8_n,
    input  logic         bs16_n
);
    typedef enum logic [2:0] {IDLE, T1, T2, HELD, BACKOFF} state_t;
    typedef enum logic [1:0] {J_NONE, J_READ, J_WRITE, J_SINGLE} job_t;
    localparam logic [2:0] MEM_READ = 3'b110, MEM_WRITE = 3'b111, SPECIAL = 3'b001;

    state_t       st, st_n;
    job_t         job;
    logic [31:5]  line;
    logic [255:0] wline;
    logic [2:0]   beat, beat_n;    // dword of the line
    logic         single;          // the rest of this 16-byte block as single cycles
    logic         grant;           // the job is the Stop Grant cycle
    logic [2:0]   status;
    logic [31:2]  s_addr, addr;
    logic [3:0]   s_be;
    logic [31:0]  s_wdata, wdata;
    logic         ken_q, ken_first, ken_all, lock_on, hold_q, ahold_q, eads_q, bs_q;
    logic [31:4]  a_q;
    logic [1:0]   a20m_s, stp_s;
    logic [31:0]  d_q;
    logic [3:0]   dp_q;
    logic         take, take_last, take_mem;
    logic [2:0]   take_beat;
    logic [3:0]   take_be;
    logic         ready, ends, burst, write, job_done, prep, start;

    function automatic logic [3:0] parity(input logic [31:0] d);
        return {^d[31:24], ^d[23:16], ^d[15:8], ^d[7:0]};
    endfunction

    assign write    = job == J_WRITE || (job == J_SINGLE && status[0]);
    assign burst    = job == J_READ && !single;
    assign ready    = st == T2 && boff_n && (!rdy_n || !brdy_n);
    assign ends     = !rdy_n || !blast_n;                 // with RDY#, BRDY# is ignored
    assign beat_n   = beat + 3'd1;
    assign job_done = job == J_SINGLE || beat == 3'd7;
    assign prep     = st == IDLE && job != J_NONE;        // the idle clock before a cycle: its registers load
    assign addr     = job == J_SINGLE ? s_addr : {line, beat};
    assign wdata    = job == J_WRITE ? wline[32*beat +: 32] : s_wdata;
    assign mem_ready = st == IDLE && job == J_NONE && !stopped && !sc_req && stp_s[1];
    assign sc_ready  = st == IDLE && job == J_NONE && !stopped && (stp_s[1] || lock_on);

    always_comb begin
        st_n  = st;
        start = 1'b0;
        unique case (st)
            IDLE:
                if (hold_q && !lock_on && !(job == J_SINGLE && sc_lock && !grant)) st_n = HELD;
                else if (prep && !ahold_q) start = 1'b1;
            T1: st_n = ads_n ? IDLE : T2;                 // ADS# held back by AHOLD: again
            T2: if (ready && ends) st_n = IDLE;
            HELD: if (!hold_q) st_n = IDLE;
            default: st_n = IDLE;                         // BACKOFF: released
        endcase
        if (start) st_n = T1;
        if (!boff_n && st_n != HELD) begin
            st_n  = BACKOFF;
            start = 1'b0;
        end
    end

    always_ff @(posedge clk) begin
        st         <= st_n;
        a20m_s     <= {a20m_s[0], a20m_n};
        stp_s      <= {stp_s[0], stpclk_n};
        d_q        <= d_i;
        dp_q       <= dp_i;
        ken_q      <= !ken_n;
        hold_q     <= hold;
        ahold_q    <= ahold;
        eads_q     <= !eads_n;
        bs_q       <= !bs8_n || !bs16_n;
        a_q        <= a_i;
        snoop      <= !a_oe && eads_q;
        snoop_addr <= a_q;
        // the registers fed from the pins
        ads_n   <= !(start && !ahold);
        ctl_oe  <= st_n != HELD && st_n != BACKOFF;
        a_oe    <= st_n != HELD && st_n != BACKOFF && !ahold;
        d_oe    <= (st_n == T1 || st_n == T2) && write;
        if (st_n != T2) blast_n <= 1'b1;
        else if (st == T1) blast_n <= burst;              // a single transfer: the last one
        else if (ready) blast_n <= beat_n[1:0] != 2'd3;   // the burst goes on
        if (ready && !ends) a_o[3:2] <= beat_n[1:0];
        // the registers of the idle clock
        hlda <= st_n == HELD;
        breq <= job != J_NONE;
        if (prep) begin
            a_o  <= {addr[31:21], addr[20] & a20m_s[1], addr[19:2]};
            be_n <= job == J_SINGLE ? ~s_be : 4'b0000;
            {mio, dc, wr} <= job == J_READ ? MEM_READ : job == J_WRITE ? MEM_WRITE : status;
            cache_n <= !burst;
            d_o  <= wdata;
            dp_o <= parity(wdata);
            if (job == J_SINGLE && sc_lock && !grant) begin
                lock_n  <= 1'b0;
                lock_on <= 1'b1;
            end
        end else if (st == IDLE) cache_n <= 1'b1;
        if (!sc_lock) begin
            lock_n  <= 1'b1;
            lock_on <= 1'b0;
        end
        // transfers
        if (ready) begin
            beat <= beat_n;
            if (beat[1:0] == 2'd3) single <= 1'b0;
            else if (ends) single <= 1'b1;
            if (beat[1:0] == 2'd0) ken_first <= ken_q;
            if (beat[1:0] == 2'd3 && !(ken_first && ken_q && !single)) ken_all <= 1'b0;
            if (job_done) begin
                job     <= J_NONE;
                grant   <= 1'b0;
                stopped <= grant;
            end
        end
        if (st_n == BACKOFF && st != IDLE && st != BACKOFF && beat[1:0] != 2'd0) single <= 1'b1;
        if (st == T2 && bs_q) err_bs <= 1'b1;
        if (stopped && stp_s[1]) stopped <= 1'b0;
        // a read's data and done one clock after its ready (the input registers)
        take       <= ready && !write;
        take_last  <= ready && job_done && !grant;
        take_mem   <= job != J_SINGLE;
        take_beat  <= job == J_SINGLE ? 3'd0 : beat;
        take_be    <= ~be_n;
        mem_rvalid <= take && take_last && take_mem;
        sc_done    <= take ? take_last && !take_mem : ready && write && job == J_SINGLE && !grant;
        pchk_n     <= !(take && |(take_be & (parity(d_q) ^ dp_q)));
        if (take && take_mem) mem_rdata[32*take_beat +: 32] <= d_q;
        if (take && !take_mem) sc_rdata <= d_q;
        if (take && take_last) mem_cacheable <= ken_all;
        // jobs
        if (!stp_s[1] && st == IDLE && job == J_NONE && !stopped && quiet && !lock_on) begin
            job     <= J_SINGLE;                          // Stop Grant
            grant   <= 1'b1;
            status  <= SPECIAL;
            s_addr  <= 30'h0000_0004;
            s_be    <= 4'b0100;
            s_wdata <= 32'd0;
        end else if (sc_req && sc_ready) begin
            job     <= J_SINGLE;
            status  <= sc_status;
            s_addr  <= sc_addr;
            s_be    <= sc_be;
            s_wdata <= sc_wdata;
        end else if (mem_req && mem_ready) begin
            job     <= mem_we ? J_WRITE : J_READ;
            line    <= mem_addr;
            wline   <= mem_wdata;
            beat    <= 3'd0;
            single  <= 1'b0;
            ken_all <= 1'b1;
        end
        if (rst) begin
            st      <= IDLE;
            job     <= J_NONE;
            grant   <= 1'b0;
            stopped <= 1'b0;
            lock_on <= 1'b0;
            err_bs  <= 1'b0;
            ads_n   <= 1'b1;
            blast_n <= 1'b1;
            lock_n  <= 1'b1;
            cache_n <= 1'b1;
            pchk_n  <= 1'b1;
            hlda    <= 1'b0;
            breq    <= 1'b0;
            a_oe    <= 1'b1;
            ctl_oe  <= 1'b1;
            d_oe    <= 1'b0;
            {mio, dc, wr} <= MEM_READ;
            be_n    <= 4'b1111;
            a_o     <= '1;
            mem_rvalid <= 1'b0;
            sc_done    <= 1'b0;
            take       <= 1'b0;
            hold_q     <= 1'b0;
            ahold_q    <= 1'b0;
            a20m_s     <= 2'b11;
            stp_s      <= 2'b11;
        end
    end
endmodule
