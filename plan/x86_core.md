# x86 core: architecture (C6 from scratch, C7 SystemVerilog, C8 out-of-order)

Goal: maximum x86 performance inside 5CEFA9F23C8 (113,560 ALMs, 1,220
M10K = 12.5 Mbit, 342 DSP) (`AGENTS.md`, `plan/cpu_core.md` selection
criterion). Numbers marked *proposed* are starting points, each tuned by a
measurement (fmax x IPC on the target) before it is fixed.

## Target and limits

- ISA: i686 + x87 + MMX + SSE + SSE2, then x86-64 long mode and
  x86-64-v2 (`AGENTS.md`); datapath width a parameter (32 now, 64 later).
- Clock *proposed* 100 MHz on 5CEFA9F23C8, slow 1100 mV 85 C model (Vexii
  reached 61 MHz, limited by pipeline depth, `plan/cpu_core.md` step 1).
  Block ceilings on C8 are higher: M10K 240 MHz (180 MHz with old-data
  read-during-write), MLAB 300 MHz [cvds p.44-45 Table 33]; the limit is
  logic per stage, so stages stay short and RAM reads registered.
- IPC: >= 2 x86 instructions per cycle sustained on cached integer code
  (operator, 2026-10-31).

## Pipeline (proposed)

| stage group | function |
|---|---|
| fetch | 16 bytes/cycle from L1I 16 KB 4-way; BTB + gshare-class predictor + 16-entry RAS |
| predecode | instruction-start and opcode marks per byte, computed on L1I fill and stored beside the line, so decode never searches lengths |
| decode | 3 x86 instructions/cycle: 2 simple (1 uop) + 1 complex (<= 4 uops); longer ones from a microcode sequencer (M10K ROM, own code) |
| uop cache | decoded uops by fetch address, bypasses fetch/decode in loops (milestone M4) |
| rename | 3 uops/cycle; integer physical register file 64 x XLEN, each entry also holds the 6 arithmetic flags of the uop that wrote it, so EFLAGS renames with the result (C2); partial flag writes (INC/DEC keep CF) merge by reading the old flags as a source; AL/AH/AX writes merge the same way |
| schedule | distributed reservation stations (ALU x2, AGU load, AGU store, branch, mul/div, FP/SIMD), 8 entries each, oldest-ready select; single-cycle wakeup only on the ALU loop |
| execute | 2 ALU (flags), branch, load AGU + store AGU (base + index*scale + disp + segment base), mul (DSP), div (iterative), x87/SSE unit (later) |
| memory | 16-entry load queue, 16-entry store queue with store-to-load forwarding; TSO: loads execute early and replay on a snoop hit or ordering violation; L1D 16 KB 4-way write-back, 4 misses in flight; L2 256 KB in M10K, then the socket bus unit |
| retire | 64-entry ROB, 3 uops/cycle; an x86 instruction retires only when all its uops did (precise exceptions and interrupts at instruction boundaries) |

Physical register file on Cyclone V: 6 reads + 3 writes per cycle do not
map to one MLAB (simple dual-port); use per-write-port banks of MLAB
replicated per read port plus a live-value table.

## Milestones (each one ends with a Verilator lock-step run against Unicorn)

1. M1 length decoder + predecode: every byte stream decoded to the same
   instruction lengths as GNU objdump (i386, all prefixes, 0F maps).
   **Done 2026-11-01** (`rtl/tools/x86_len_test.sh`): `x86_len_decode`
   (prefix scan + `x86_opdecode`) matches objdump 2.47 at 784,137 32-bit
   and 944,575 16-bit starts (2 MB random, seed 7); `x86_predecode` (16
   starts/cycle, 2 stages: per-byte opcode decode, then one-hot prefix-run
   select) equals it on 200,000 biased random blocks (3 injected bugs
   caught). 5CEFA9F23C8, harness `rtl/tests/x86/synth/`: 3,793 ALMs,
   1,093 registers, 101.09 MHz slow 1100 mV 85 C (one stage: 46 MHz).
2. M2 integer core, flat 32-bit, no caches (ideal memory): fetch, decode,
   rename, ALU/branch, ROB; `x86_trace_check` per retired instruction.
   **First core 2026-11-01** (`rtl/tools/x86_core_test.sh`,
   `x86_rand_test.sh`): P6-style stepping stone, results in a 32-entry
   ROB, RAT -> ROB tag or architectural register, flags renamed as one
   more register. Pipeline: frontend (16-byte blocks, 2-stage predecode,
   4-block queue, 3 instructions/cycle) -> decode -> P (decoded group
   registered: RET targets from the return stack, decode redirect, push)
   -> 16-uop queue -> R
   (rename, ROB/SQ allocation) -> D (operand read, RS write; stalls on a
   full RS) -> S (16-entry RS, age matrix, oldest ready per port; each
   ALU uop bound to one of 2 ALU ports at dispatch) -> X -> wb1 (ROB,
   capture) -> wb2 (bypass only); memory port S -> A (AGU) -> M (8-entry
   SQ, forward on an exact match, replay on a partial overlap, stores
   write at retire); mul/div port (`x86_muldiv`: 3-stage multiply,
   1 bit/cycle divider, issued in order since MULH/DIVR read the unit's
   last high half / remainder), its results on the memory result bus (a
   memory op in M that cycle replays: 3 capture buses, not 4). ALU grants wake dependents at once (back to back);
   an uncaptured operand must be on wb1/wb2 (simulation check). Branches:
   TAGE + static BTFN at decode / P, a 32-entry fetch BTB that learns decode's taken
   decisions, an 8-entry return stack; mispredicts flush the cycle after
   they retire. Subset: ALU/shift/rotate/SHLD/SHRD/BSF/BSR/BSWAP/BT/BTS/BTR/BTC
   (a register bit offset on a register only)/MOV moffs/XADD/CMPXCHG/CLC/STC/CMC/
   SAHF/LAHF/SETcc/CMOVcc/
   MUL/IMUL/DIV/IDIV on 8/16/32-bit operands (QEMU flag semantics), loads/stores,
   stack, branches (CALL r/m32; LOOP/LOOPE/LOOPNE: ECX - 1 written, taken when ECX != 1;
   JECXZ), [REP] MOVS/STOS/LODS, CMPS, [REPE/REPNE] SCAS (REP CMPS would
   need 7 uops: K_ILL), DF 0 / 1 (decode reads the architectural DF; a
   CLD/STD that changes it retires as K_DF and flushes), RET imm16;
   prefixes 66, F3, F2, F0 (LOCK: a no-op on one core; bus LOCK# in M8) and
   CS/DS/ES/SS. A REP iteration is the instruction looping on itself: uop 0
   leaves when ECX = 0 (else ECX -= 1), decode predicts the loop, the BTB
   learns it; up to 6 uops per instruction (P pushes a long slot 0 in two
   cycles). Matches Unicorn on x1/x2, 2000 random programs (`x86_rand.py`)
   and compiled C (`tests/x86/c*.c`, gcc i686 freestanding): `c1_mix`
   (records, strings, sort, CRC-32, recursion) 23,879 instructions, IPC
   0.805; `c2_core` (list, matrix, switch jump table, 64-bit arithmetic)
   9,369, IPC 0.891; `c3_string` (-Os: REP MOVS/STOS) 10,033, IPC 0.677;
   `c4_bits` (BSF/BSR/BSWAP) 3,363, IPC 0.831.
   IPC: 1.88 straight ALU code (2 ALU ports), 1.94 in a 14-instruction
   loop, 0.35 on random programs (random forward Jcc, string ops).
   5CEFA9F23C8 (`rtl/tests/x86/synth/x86_core_synth.sv`,
   `rtl/tools/synth_path.sh` for the worst path): single-cycle issue 5.88
   MHz (serial oldest-first select + execute + capture); pipelined issue
   45.9; registered flush 47.9; RS budget off the dispatch count 56.5
   MHz at 38,946 ALMs (34 %), 17,056 registers; with 8/16-bit operands,
   shifts and the BTB (registered update) 40.99 MHz, 43,639 ALMs (38 %),
   20,086 registers, worst path decode -> branch target -> redirect
   compare -> uop queue push, hence the P stage. With P and mul/div the
   default fit failed routing (43 % ALMs, local congestion); bisect: mul/div
   stubbed 53.87 MHz at 47,132 ALMs; perf recipe (aggressive routability)
   57.74 MHz at 52,085 ALMs. Fix: mul/div inputs registered (one more cycle
   of latency) so its DSP blocks place away from the issue / bypass logic:
   54.91 MHz, 49,173 ALMs (43 %), 22,976 registers, default recipe; worst
   path return stack -> P redirect compare -> P load enable (then the load
   enable no longer waits for the compare; frontend next-start chain
   precomputed per byte at queue push): 52.36 MHz, 49,725 ALMs; worst path
   in-group return stack index -> serial redirect compares (then: RET
   reads the top before its group, parallel compares): 56.83 MHz, 48,457
   ALMs, worst path wb tag -> operand bypass mux -> ALU shift -> ZF.
   With gshare: 54.95 MHz, 49,476 ALMs, 3 M10K, worst path ROB head ->
   retire valid -> gshare write index -> M10K address (then: the table
   write registered): 53.85 MHz, 49,516 ALMs (with BT, LOOP), worst path
   wb2 tag compare -> operand bypass mux -> ALU shifter -> ZF; then the
   bypass tags are compared in S against the buses that are wb1 / wb2 in
   the X cycle, X keeps only the mux on registered selects (a simulation
   check compares them with the old X-stage match): 57.05 MHz, 51,771
   ALMs, worst path store queue `known` count -> memory request -> grant
   -> pick -> bypass tag compare (S).
   CoreMark 1.0 (`rtl/tools/x86_coremark.sh`: 2K performance run, port in
   `rtl/tests/x86/coremark/`, gcc -O2 -march=i686, CRCs checked natively;
   1 and 2 iterations, both lock-step against Unicorn, the difference is
   one iteration): 339,549 instructions, 315,531 cycles per iteration, IPC
   1.076, 3.17 CoreMark/MHz on ideal memory (about 181 at 57 MHz). Whole
   1-iteration run (`core_tb +stats`): 4,561 flushes, 12,646 decode
   redirects; head waits LD 35,910, ALU 32,717, ST 19,570, MD 17,204.
   Indirect CALL/JMP are not predicted (fall-through: a flush each).
   Flushes split (`+stats`): Jcc 3,908, indirect / RET 653. Offline on the
   CoreMark trace (56,251 Jcc): gshare 4K 3,729 mispredicts, 64K 3,071,
   tournament 16K 3,199, TAGE (4 x 1K tagged, histories 5 / 12 / 24 / 48,
   4K bimodal base) 1,449, 1,632 with the update 6 branches late. Built
   (`x86_tage.sv`: one table copy per decode slot, read at the P load with
   the history up to two groups back, entries read kept in a 32-entry queue
   from P to retire, the first retired Jcc of a cycle trains): Jcc flushes
   CoreMark 3,908 -> 2,243, c1 273 -> 158; 3.444 CoreMark/MHz (290,354
   cycles per iteration), IPC c1 1.292, c2 1.125, c4 1.079.
   `rtl/tools/x86_synth.sh` compiles the core (sources in `x86_files.sh`).
   CoreMark run with TAGE: flushes Jcc 2,243, indirect CALL/JMP 424 (not
   predicted), RET 159; head waits LD 32,929, ALU 28,284, MD 17,167, ST
   16,942; decode redirects 13,281 (taken not followed 8,358): BTB 128
   entries IPC 1.127 -> 1.138, 512 -> 1.149 (the BTB would move to M10K,
   read with the next fetch address). Indirect CALL/JMP r/m: P keeps the
   frontend's BTB target, a wrong one flushes at retire and writes the
   actual target into the BTB: indirect flushes 424 -> 273.
   RET after a flush: the return stack is restored from a copy kept at
   retire (CALL push store / RET jump): RET flushes 171 -> 1, 3.501
   CoreMark/MHz (285,643 cycles per iteration, IPC 1.189).
   Multiply: the operand extension moved into the product stage (latency
   4 -> 3): 3.548 CoreMark/MHz (281,882 cycles). Issue contention on the
   1-iteration run (309,990 cycles, `+stats`): >= 3 ALU uops ready with
   both ports busy 46,691 cycles, >= 2 memory uops ready (one port, loads
   and stores) 32,154, one ALU port idle while the other has >= 2 ready
   18,359 (ports alternate at rename), loads replayed for the mul/div bus
   1,953. Tried: an ALU uop takes the port of its unfinished ALU producer:
   3.375 CoreMark/MHz (one port idle 50,509: consumers of one producer, a
   counter or ESP, pile up on its port); rejected. ALU port chosen at
   issue (port 0 the oldest ready, port 1 another one, both from the age
   matrix in parallel): the youngest 3.552, the second oldest 3.474, with
   Jcc flushes 2,244 -> 2,712 from retire timing alone: only the first Jcc
   retired in a cycle trained TAGE (1,447 of them skipped per iteration).
   Training decoupled from retire (outcomes noted at retire, the queue
   trains in order, one per cycle; its metadata in 4 RAM banks, the 32 x
   155-bit register queue did not route): Jcc flushes 2,244 -> 1,607, 3.735
   CoreMark/MHz (267,753 cycles, IPC 1.268); IPC c1 1.300, c2 1.168, c4
   1.110. On top of it the issue choice gives: youngest 3.709, second
   oldest 3.747 (+0.3 %, more logic in S, the critical stage): ports keep
   alternating at rename.
   Store port: stores issue on their own port 4 (S -> X: AGU, store queue
   entry and ROB done, no result bus, never replayed), port 2 keeps loads:
   3.735 -> 3.894 CoreMark/MHz (256,784 cycles, IPC 1.322; head waits on
   stores 16,418 -> 2,510). BTB 512 entries on top: 3.970 (+2.0 %; taken
   not followed 8,021 -> 5,072, the rest is set / clear thrash). Tried:
   P never clears a Jcc's entry (one redirect per loop exit, not two):
   3.629, falsely taken 3,360 -> 10,809; rejected.
   Multiply latency 2 (no input register): 3.956 (+1.6 %); not taken, the
   X bypass mux would feed the 33 x 33 product (the unit did not route).
   Routing: the banked-queue build routed (58,529 ALMs, 46.24 MHz, worst
   path TAGE RAM -> dir -> P redirect -> fetch queue write enables); the
   next two did not (peak vertical interconnect 97 % in one region at 53 %
   ALMs). Pipeline and fetch-queue data registers no longer depend on
   flush / redirect (only the valid bits do): fewer enables, the redirect
   off ~2,500 register enables. The uop queue writes every valid P slot
   (room is checked for all of them), only its tail follows p_take.
   With TAGE stubbed out the default recipe does not route either (peak
   vertical 79 %): the core needs the perf recipe (aggressive routability),
   now `x86_synth.sh`'s default. Store port tree (f95404f), perf: 58.8
   MHz, 64,551 ALMs, peak interconnect 68 % (3.894 x 58.8 = 229 CoreMark
   on ideal memory); worst path sq_head -> store queue check -> m_ok -> bus
   2 valid -> early wakeup -> RS ready. The load's store queue check moved
   to A, registered for M (older store addresses are all known at issue),
   overlap by dword equality and byte masks (a second forwarding store
   replays): CoreMark cycles unchanged.
   BTB 512 entries in RAM, read with pc_f's next value (no reset, a clear
   does not check the tag: one port): 3.957 CoreMark/MHz (252,702 cycles).
   Third ALU (port 5, result bus 3; rename rotates over the 3 ALUs): 4.101
   CoreMark/MHz (243,864 cycles, IPC 1.392); perf build 56.87 MHz, 65,898
   ALMs (+6.5K, same worst path as without it): taken.
   Bus 2 known a cycle ahead (a load's A check done and the bus free, or
   mul/div done next cycle: its pipeline is fixed): their dependents wake
   then (load-to-use 3 -> 2, mul 3 -> 2, nothing speculative): 4.510
   CoreMark/MHz (221,724 cycles, IPC 1.531).
   Mask build (2 ALUs): 58.83 MHz, 61,623 ALMs; worst path rename: uq_head
   -> uop -> ROB entry write enable (value written 0 at rename): rename now
   writes only the fields wb does not. Stores in two phases: the address as
   soon as its sources are ready (younger loads wait for it), the data then
   or later (a load matching a store without data replays): 4.757
   CoreMark/MHz (210,238 cycles, IPC 1.615; load head waits 31,234 ->
   20,384).
   Window: ROB 32 / RS 24 4.793, ROB 64 / RS 16 4.757, ROB 64 / RS 24
   4.847 (+1.9 %): not the limit. Cycles now (`+stats`, 1 iteration): uop
   queue empty 46,209, flush -> next retire 20,641 (1,833 flushes), decode
   redirects 9,252, head waits LD 20,384, MD 11,880, ALU 8,735: the
   frontend (refill depth, redirects) leads.
   Early wakeup perf build (3 ALUs): 53.16 MHz, 66,712 ALMs (4.510 x 53.16
   = 240 vs 4.101 x 56.87 = 233: +2.8 % net); worst path RS ready -> grant
   -> pick -> bypass tag compare -> X operand -> ALU. Tried: the bypass selects
   compared for every RS entry, in parallel with select, and picked by the
   grant: does not route (perf recipe, 67,574 ALMs; 512 comparators fed by
   every bus and RS tag); reverted.
   Two-phase stores perf build: 54.48 MHz, 66,402 ALMs (4.757 x 54.48 =
   259 CoreMark on ideal memory); worst path the wakeup loop: RS ready ->
   grant -> picked tag -> compare with waiting tags (RS and D) -> ready.
   Tried: the ALU wakeup comparing every waiting tag with every RS entry's
   tag, independent of the grant, ORing the granted entries' matches: 52.19
   MHz, 69,593 ALMs (worst path now the load wakeup: bypass -> AGU -> store
   queue lo +- 1 adders -> a_ok -> wakeup -> ready); reverted.
   Senior store queue: retire only commits a store (sq_cmt); the queue
   drains [head, cmt) to memory one per cycle, in order, and a flush keeps
   the retired entries: CoreMark unchanged (4.756), the L1D drain port.
   Perf builds: load check in A 58.2 MHz (61,462 ALMs), + BTB RAM 55.23
   MHz (59,392 ALMs; same worst path, placement spread ~5 %): S, sq_head ->
   count of known store addresses -> load request -> grant -> pick ->
   bypass tag compare. Registering that position (a cycle late) costs 3.957
   -> 3.776 CoreMark/MHz; instead each load keeps the mask of its older
   stores' queue entries (set in D, a retiring store clears its bit in
   every RS entry): request = no masked entry with an unknown address, same
   cycles.
   Cycle breakdown (`core_tb +stats`): cycles that retire nothing are
   mostly an unfinished ROB head (c1: 9,950 of 29,647; ALU 4,501, LD
   3,757, MD 484), not an empty ROB (5,775): latency, so loads and mul/div
   wake dependents in their result cycle (bus 2, also at D): IPC c1 0.805
   -> 0.859, c2 0.891 -> 0.959, c3 0.677 -> 0.771, c4 0.831 -> 0.900.
   Conditional branches: static BTFN mispredicted 817 of 3,350 Jcc in c1
   (= its 824 flushes); offline replay of the Unicorn traces: bimodal 548,
   gshare 4K 334, gshare whose weak counters keep BTFN 272 (best on every
   test, cold code stays at BTFN). Built (4K x 2-bit, 10-bit history,
   read as the group enters P, updated at retire): flushes c1 824 -> 287,
   c2 129 -> 57, c4 72 -> 18; IPC c1 1.174, c2 1.134, c4 1.049. Decode
   redirects rose (c1 216 -> 889); not BTB capacity (32, 128 and 512
   entries give the same IPC) but direction thrash: c1 542 taken branches
   the frontend did not follow + 345 it followed but P predicts not taken
   (the BTB entry is set / cleared on each disagreement). Tried: direction
   of BTB-marked Jcc from a gshare copy read at fetch (block pc ^ history
   of marked branches, the only history fetch knows: unmarked not-taken Jcc
   are invisible to it): decode redirects c1 889 -> 258 but flushes 287 ->
   441, IPC 1.174 -> 1.081 (c2 1.134 -> 1.094): rejected. Measured costs:
   a decode redirect about 1.6 cycles (the backend hides most of it), a
   mispredict about 15 (`+stats`, c1: 3.3 from the branch result to its
   retire, 11.5 from the flush to the next retire: r_flush, flush, F0, F1,
   F2, extract, decode, P, R, D, S, X, wb, retire). Offline predictor
   sweep (c1 3,350 Jcc): gshare 14-bit / longer history no better (272 ->
   292), tournament 258: these short tests are bound by cold and
   data-dependent branches. DE25-Nano
   A5EB013BB23BE4SCS (Quartus Pro 26.1.1, R/D split, before the BTB):
   133.48 MHz slow fix4 0C, 34,173 / 46,800 ALMs (73 %): the D11 bench
   board runs the core 2.4x faster but has little room left.
3. M3 loads/stores, LSQ, L1I/L1D, then L2; Dhrystone/CoreMark for x86 IPC.
   Keeps what M2 relies on: a load's dependents wake in A, so a hit is
   known in A; RAM reads addressed by the value a register takes.
   Done:
   - Test bench: one 32-byte line port, read latency `+mem_lat` (default
     10), writes posted, one read in flight: the shape of the socket bus
     units (M8). `x86_rand.py ... stride`: the buffer is 6 copies 4 KB
     apart (one L1D set: evictions, write-backs).
   - L1D (`x86_l1d.sv`) 16 KB, 4-way, 32-byte lines, write-back,
     write-allocate, one miss in flight. Tags in MLAB, a copy per reader
     (the load's even and odd dword lines, the drain), read unregistered
     with the AGU address in A: the hit joins the store queue check (a
     miss replays, does not wake). Data in M10K, even / odd dword banks
     addressed at the A -> M edge: any access of up to 4 bytes reads in one
     cycle, across lines too. The store queue drains into it with byte
     enables (a line-crossing store in two steps); a miss holds the drain.
     CoreMark 4.756 at mem_lat 10 (117 misses, all in the setup).
   Next:
   - A missing load leaves the RS waiting on its line (no replay loop),
     woken when the fill writes it; more misses in flight.
   - L1I 16 KB, 4-way, 32-byte lines, read with pc_f's next value like the
     BTB; the 30-byte window reads two 16-byte half-line banks; a miss
     stalls fetch.
   - Stores to code (loaders, self-modifying code): a drained store
     invalidates its L1I line, L1I fills see dirty L1D lines; in-flight
     instructions in M5.
   - L2 256 KB in M10K behind both, then the bus unit.
4. M4 uop cache, predictor tuning; fmax closure on 5CEFA9F23C8.
5. M5 system: real/protected mode, segmentation, paging + TLBs, exceptions,
   interrupts, I/O ports, CPUID/MSRs; test386 and the single-step datasets
   (z486 repo, reference only).
6. M6 x87 (80-bit) and MMX; M7 SSE/SSE2.
7. M8 bus units behind L2: Socket 3 (486), DE25-Nano adapter (D11), then
   Socket 7 and Socket 370.
   Socket 3 must honour STPCLK# (Am5x86 contract, AMD 19751C sec.
   5.2-5.5.3; the FPGAmotherboard chipset uses it for DVFS): at an
   instruction boundary issue the Stop Grant special cycle (M/IO#=0, D/C#=0,
   W/R#=1, address 0000_0010h, BE3#-BE0#=1011b, ended by BRDY#); CLK may then
   stop and return at 33.33/25/20/16.67 MHz, resume when STPCLK# rises
   (>= 1 ms of stable CLK before); only INTR moves while CLK is stopped;
   STPCLK# stays high >= 8 clocks between assertions. Socket 7 (P55C)
   follows later, with A4 in the special-cycle decode (peer session
   "motherboard FPGA", 2026-11-01).
   All sockets: honour A20M# (mask physical address bit 20 while asserted;
   inactive at the first fetch and across RESET; the FPGAmotherboard
   chipset drives it from 8042 output port bit 1 OR port 0x92 bit 1) and
   INIT# (S370) / INIT (S7), a 15-bus-clock pulse on 8042 command 0xFE or a
   port 0x92 bit 0 write: soft reset to the reset vector, caches and DRAM
   kept (peer session "motherboard FPGA", FPGAcommon 4d2f944 / d547ce2,
   2026-11-01).

## Layout

- `rtl/x86/` SystemVerilog sources, one module per file.
- `rtl/tests/x86/` assembly tests; `rtl/tools/x86_test.sh` +
  `x86_trace_check.c` (Unicorn 2.1.4) for the reference.
- The DE25-Nano (46,800 ALMs) hosts milestone subsets; the full core is
  sized for the A9 (C5, selection criterion).
