// Socket 3 bus unit (plan/x86_core.md M8): the 486 local bus as a master, behind the core's 32-byte
// line port, plus a single-cycle port (I/O, interrupt acknowledge, special cycles, uncached memory).
// One clock, the socket's CLK. At the socket, from its rising edge [Intel DX4 write-back enhanced
// datasheet, bus operation; AMD 19751C AC table]: outputs valid 3-14 ns (floated within 20 ns);
// RDY# / BRDY# / KEN# / BOFF# / AHOLD / HOLD / read data stable from 5 ns before to 3 ns after it.
// What must follow RDY# / BRDY# / BOFF# / AHOLD in the very next clock is kept to a few registers
// fed straight from those pins: the state, BLAST# (low for a burst's fourth transfer right after
// the third BRDY#), the burst's A3-A2, and the three output enables (ADS# floats
// with the address: AHOLD or BOFF# sampled as a cycle would start keep it off the bus, ads_go tells the state). A
// pin -> logic -> pin loop across the FPGA misses that timing, so BLAST#, A3 and A2 sit on balls
// next to RDY# / BRDY# (hw/tools/gen_socket3_assign.py FAST). Everything else leaves from registers
// loaded in the idle clock before each cycle (I/O cells) and the other inputs come in through
// input registers: a cycle is IDLE, T1, T2...; HOLD is granted, and read data stored, a clock late.
// - A cycle: T1 (ADS# low, address and status), then T2 until RDY# or BRDY#; BRDY# with BLAST# high
//   goes on with the next transfer of the burst, RDY# ends the cycle. Write data is driven from
//   T1 (after the idle clock nobody else drives; its enable may then take the slow way).
// - Line read: per 16-byte block one burst from offset 0 (486 order 0-4-8-C); after a transfer ended
//   by RDY# or a back-off the rest of the block as single cycles (a burst from another offset has
//   another order). Line write: 8 single cycles; in enhanced mode a write-back (CACHE# low, never
//   narrow: BS8# / BS16# ignored), non-bursted as the databook allows: a burst would drive the next
//   dword in the clock after BRDY#, a pin -> pin loop from BRDY# (die top) to D (die bottom) that
//   misses 33 MHz by 5 ns.
// - BOFF#: floats the bus in the next clock, the transfer starts again when it is released. HOLD:
//   granted between cycles (not under LOCK#). AHOLD: the address floats, no new cycle. EADS# on a
//   floated address: `snoop` with the line address and INV (for the caches). `enhanced`: WB/WT# as
//   RESET falls.
// - STPCLK# with the core quiet and no job: Stop Grant special cycle (address 10h, BE2# low), then
//   no job until it is released. Enhanced mode, after the core's FLUSH# (flush_done): the First and
//   Second Flush Acknowledge cycles (BE3# / BE1# low, A4-A2 = 001) [Intel486 Table 10-9].
// - Even parity out on DP, PCHK# the clock after a read's data is stored.
// - BS8# / BS16# (as sampled the clock before the ready, Intel486 10.1.2): a transfer moves the lowest
//   enabled byte / the enabled bytes of the lowest enabled half; the rest of the dword follows in a
//   cycle of its own with the remaining BE# (Table 10-3), the same address. A single cycle had
//   BLAST# low, so the board ended it anyway; in a burst the next transfer is made the last one
//   (BLAST# low, its data ignored: BE# cannot follow RDY# within a clock, they are not on the fast
//   balls) and the rest of the 16-byte block goes as single cycles, not cached.
// Not yet: HITM# and the snoop write-back, SRESET (plan/x86_core.md M5).
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
    input  logic         flush_done,      // the caches finished a FLUSH#
    output logic         stopped,
    output logic         snoop,
    output logic [31:4]  snoop_addr,
    output logic         snoop_inv,
    output logic         enhanced,        // WB/WT# high at RESET: the write-back bus protocol
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
    input  logic         inv,
    input  logic         wb_wt_n,
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
    logic         ack;             // the job is a flush acknowledge cycle
    logic [1:0]   ack_due;         // flush acknowledge cycles still to run
    logic [2:0]   status;
    logic [31:2]  s_addr, addr;
    logic [31:0]  s_wdata, wdata;
    logic         ken_q, ken_first, ken_all, lock_on, hold_q, ahold_q, eads_q, inv_q, wbwt_q, bs8_q, bs16_q;
    logic [3:0]   rem;             // bytes of the current dword still to move (active high)
    logic         drop;            // the burst's next transfer only ends it: its data is ignored
    logic [31:4]  a_q;
    logic [1:0]   stp_s;
    logic [31:0]  d_q;
    logic [3:0]   dp_q;
    logic         take, take_last, take_mem;
    logic [2:0]   take_beat;
    logic [3:0]   take_be;
    logic         ready, ends, burst, write, wback, job_done, prep, start, try, ads_go;
    logic [3:0]   moved, rem_left;
    logic         partial, dw_done;
    logic         j_grant, j_ack, j_sc, j_mem;   // a job is taken this clock
    logic         mid_q, bo_entry;           // the first BACKOFF clock of a cycle under way
    // The RDY# / BRDY# / BOFF# loop: these registers meet the pins in one LUT (pin_next). Their next
    // values for "RDY#", "BRDY# only" and "neither / BOFF#" come from registers alone, kept as nodes
    // (synthesis would merge them with the pins into two levels: -0.1 ns at the pins' distance).
    (* keep *) logic [1:0] ao_r, ao_y, ao_n;
    (* keep *) logic [2:0] bt_t, bt_n;
    (* keep *) logic [3:0] rm_t, rm_n;
    (* keep *) logic       bl_r, bl_y, bl_n, dr_r, dr_y, dr_n, sg_r, sg_y, sg_n, do_r, do_y, do_n, tk_t, tl_t;

    function automatic logic [3:0] pin_next(input logic [3:0] vr, input logic [3:0] vy, input logic [3:0] vn);
        return !boff_n ? vn : !rdy_n ? vr : !brdy_n ? vy : vn;
    endfunction
    function automatic logic [3:0] parity(input logic [31:0] d);
        return {^d[31:24], ^d[23:16], ^d[15:8], ^d[7:0]};
    endfunction
    // the bytes one transfer moves [Intel486 Table 10-4]
    function automatic logic [3:0] lanes(input logic [3:0] be, input logic b8, input logic b16);
        if (b8) return be & (~be + 4'd1);
        if (b16 && be[1:0] != 2'd0) return be & 4'b0011;
        return be;
    endfunction

    assign write    = job == J_WRITE || (job == J_SINGLE && status[0]);
    assign wback    = job == J_WRITE && enhanced;            // a write-back
    assign burst    = job == J_READ && !single;
    assign ready    = st == T2 && boff_n && (!rdy_n || !brdy_n);
    assign ends     = !rdy_n || !blast_n;                 // with RDY#, BRDY# is ignored
    assign beat_n   = beat + 3'd1;
    assign moved    = drop ? 4'd0 : wback ? rem : lanes(rem, bs8_q, bs16_q);
    assign rem_left = rem & ~moved;
    assign partial  = !drop && rem_left != 4'd0;
    assign dw_done  = !drop && rem_left == 4'd0;
    assign job_done = dw_done && (job == J_SINGLE || beat == 3'd7);
    assign prep     = st == IDLE && job != J_NONE;        // the idle clock before a cycle: its registers load
    assign addr     = job == J_SINGLE ? s_addr : {line, beat};
    assign wdata    = job == J_WRITE ? wline[32*beat +: 32] : s_wdata;
    assign mem_ready = st == IDLE && job == J_NONE && !stopped && !sc_req && stp_s[1] && ack_due == 2'd0;
    assign sc_ready  = st == IDLE && job == J_NONE && !stopped && (stp_s[1] && ack_due == 2'd0 || lock_on);

    assign try = prep && !ahold_q && !(hold_q && !lock_on && !(job == J_SINGLE && sc_lock && !grant && !ack));

    always_comb begin
        st_n  = st;
        start = 1'b0;
        unique case (st)
            IDLE:
                if (hold_q && !lock_on && !(job == J_SINGLE && sc_lock && !grant && !ack)) st_n = HELD;
                else start = try;
            T1: st_n = ads_go ? T2 : IDLE;                // ADS# floated by AHOLD: again
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

    assign j_grant  = !stp_s[1] && st == IDLE && job == J_NONE && !stopped && quiet && !lock_on;
    assign j_ack    = !j_grant && ack_due != 2'd0 && st == IDLE && job == J_NONE && !stopped && !lock_on;
    assign j_sc     = !j_grant && !j_ack && sc_req && sc_ready;
    assign j_mem    = !j_grant && !j_ack && !j_sc && mem_req && mem_ready;
    assign bo_entry = st == BACKOFF && mid_q;
    always_comb begin
        logic t2, x_cont, blk_end;
        t2      = st == T2;
        x_cont  = !partial && beat_n[1:0] != 2'd3;            // a burst transfer that is not its last
        blk_end = dw_done && beat[1:0] == 2'd3;
        bl_n = rst || (st == T1 ? !ads_go || burst : !t2 || blast_n);
        bl_r = bl_n || t2;
        bl_y = rst || (t2 ? !blast_n || x_cont : bl_n);
        ao_n = rst ? 2'b11 : prep ? addr[3:2] : a_o[3:2];
        ao_r = ao_n;
        ao_y = !rst && t2 && blast_n && !partial ? beat_n[1:0] : ao_n;
        bt_n = j_mem ? 3'd0 : beat;
        bt_t = t2 && dw_done ? beat_n : bt_n;
        rm_n = j_grant ? 4'b0100 : j_ack ? (ack_due == 2'd2 ? 4'b1000 : 4'b0010) : j_sc ? sc_be : j_mem ? 4'hF : rem;
        rm_t = !t2 ? rm_n : dw_done ? 4'hF : partial ? rem_left : rem;
        dr_n = !rst && !bo_entry && drop;
        dr_r = !t2 && dr_n;
        dr_y = t2 ? !rst && partial && blast_n : dr_n;
        sg_n = j_mem ? 1'b0 : bo_entry && (beat[1:0] != 2'd0 || drop || rem != 4'hF) || single;
        sg_r = t2 ? !blk_end : sg_n;
        sg_y = t2 ? !blk_end && (!blast_n || partial || single) : sg_n;
        do_n = !rst && write && (st == IDLE && try || st == T1 && ads_go || t2);
        do_r = !t2 && do_n;
        do_y = t2 ? !rst && write && blast_n : do_n;
        tk_t = !rst && t2 && !write;
        tl_t = t2 && job_done && !grant && !ack;
    end

    always_ff @(posedge clk) begin
        st         <= st_n;
        stp_s      <= {stp_s[0], stpclk_n};
        d_q        <= d_i;
        dp_q       <= dp_i;
        ken_q      <= !ken_n;
        hold_q     <= hold;
        ahold_q    <= ahold;
        eads_q     <= !eads_n;
        inv_q      <= inv;
        wbwt_q     <= wb_wt_n;
        if (rst) enhanced <= wbwt_q;
        bs8_q      <= !bs8_n;
        bs16_q     <= !bs16_n;
        a_q        <= a_i;
        snoop      <= !a_oe && eads_q;
        snoop_addr <= a_q;
        snoop_inv  <= inv_q;
        // the registers fed from the pins
        ads_go  <= start && !ahold;
        ctl_oe  <= st_n != HELD && st_n != BACKOFF;
        a_oe    <= st_n != HELD && st_n != BACKOFF && !ahold;
        d_oe     <= boff_n && 1'(pin_next(4'(do_r), 4'(do_y), 4'(do_n)));
        blast_n  <= !boff_n || 1'(pin_next(4'(bl_r), 4'(bl_y), 4'(bl_n)));   // T1: low for a single transfer
        a_o[3:2] <= 2'(pin_next(4'(ao_r), 4'(ao_y), 4'(ao_n)));
        beat     <= 3'(pin_next(4'(bt_t), 4'(bt_t), 4'(bt_n)));
        rem      <= pin_next(rm_t, rm_t, rm_n);
        drop     <= 1'(pin_next(4'(dr_r), 4'(dr_y), 4'(dr_n)));
        single   <= 1'(pin_next(4'(sg_r), 4'(sg_y), 4'(sg_n)));
        take     <= 1'(pin_next(4'(tk_t), 4'(tk_t), 4'd0));
        take_last <= 1'(pin_next(4'(tl_t), 4'(tl_t), 4'd0));
        mid_q    <= st != IDLE && st != BACKOFF;
        // the registers of the idle clock
        ads_n <= !try;
        hlda <= st_n == HELD;
        breq <= job != J_NONE;
        if (prep) begin
            a_o[31:4] <= addr[31:4];              // A20M#: the core masks it
            be_n <= ~rem;
            {mio, dc, wr} <= job == J_READ ? MEM_READ : job == J_WRITE ? MEM_WRITE : status;
            cache_n <= !(burst || wback);
            d_o  <= wdata;
            dp_o <= parity(wdata);
            if (job == J_SINGLE && sc_lock && !grant && !ack) begin
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
            if (beat[1:0] == 2'd0) ken_first <= ken_q;
            if (beat[1:0] == 2'd3 && !(ken_first && ken_q && !single)) ken_all <= 1'b0;
            if (job_done) begin
                job     <= J_NONE;
                grant   <= 1'b0;
                ack     <= 1'b0;
                stopped <= grant;
            end
        end
        if (stopped && stp_s[1]) stopped <= 1'b0;
        // a read's data and done one clock after its ready (the input registers)
        take_mem   <= job != J_SINGLE;
        take_beat  <= job == J_SINGLE ? 3'd0 : beat;
        take_be    <= moved;
        mem_rvalid <= take && take_last && take_mem;
        sc_done    <= take ? take_last && !take_mem : ready && write && job_done && job == J_SINGLE && !grant && !ack;
        pchk_n     <= !(take && |(take_be & (parity(d_q) ^ dp_q)));
        for (int b = 0; b < 4; b++)
            if (take && take_be[b]) begin
                if (take_mem) mem_rdata[32*take_beat + 8*b +: 8] <= d_q[8*b +: 8];
                else sc_rdata[8*b +: 8] <= d_q[8*b +: 8];
            end
        if (take && take_last) mem_cacheable <= ken_all;
        // jobs
        // jobs (rem, beat, single: above)
        if (j_grant) begin
            job     <= J_SINGLE;                          // Stop Grant
            grant   <= 1'b1;
            status  <= SPECIAL;
            s_addr  <= 30'h0000_0004;
            s_wdata <= 32'd0;
        end else if (j_ack) begin
            job     <= J_SINGLE;                          // flush acknowledge
            ack     <= 1'b1;
            ack_due <= ack_due - 2'd1;
            status  <= SPECIAL;
            s_addr  <= 30'h0000_0004;
            s_wdata <= 32'd0;
        end else if (j_sc) begin
            job     <= J_SINGLE;
            status  <= sc_status;
            s_addr  <= sc_addr;
            s_wdata <= sc_wdata;
        end else if (j_mem) begin
            job     <= mem_we ? J_WRITE : J_READ;
            line    <= mem_addr;
            wline   <= mem_wdata;
            ken_all <= 1'b1;
        end
        if (flush_done && enhanced) ack_due <= 2'd2;
        if (rst) begin
            st      <= IDLE;
            job     <= J_NONE;
            grant   <= 1'b0;
            ack     <= 1'b0;
            ack_due <= 2'd0;
            stopped <= 1'b0;
            lock_on <= 1'b0;
            ads_n   <= 1'b1;
            lock_n  <= 1'b1;
            cache_n <= 1'b1;
            pchk_n  <= 1'b1;
            hlda    <= 1'b0;
            breq    <= 1'b0;
            a_oe    <= 1'b1;
            ctl_oe  <= 1'b1;
            {mio, dc, wr} <= MEM_READ;
            be_n    <= 4'b1111;
            a_o[31:4] <= '1;
            mem_rvalid <= 1'b0;
            sc_done    <= 1'b0;
            hold_q     <= 1'b0;
            ahold_q    <= 1'b0;
            stp_s      <= 2'b11;
        end
    end
endmodule
