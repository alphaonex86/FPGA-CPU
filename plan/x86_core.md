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
   last high half / remainder). ALU grants wake dependents at once (back to back);
   an uncaptured operand must be on wb1/wb2 (simulation check). Branches:
   static BTFN at decode, a 32-entry fetch BTB that learns decode's taken
   decisions, an 8-entry return stack; mispredicts flush the cycle after
   they retire. Subset: ALU/shift/rotate/SETcc/CMOVcc/MUL/IMUL/DIV/IDIV
   on 8/16/32-bit operands (QEMU flag semantics), loads/stores, stack,
   branches; prefixes 66 and CS/DS/ES/SS. Matches Unicorn on x1/x2, 2000
   random programs (`x86_rand.py`) and compiled C (`tests/x86/c1_mix.c`,
   gcc -O2 i686: records, strings, sort, CRC-32, recursion; 23,879
   instructions, IPC 0.716). IPC: 1.88 straight ALU code (2 ALU ports), 1.94 in a
   14-instruction loop, 0.45 on random programs (random forward Jcc).
   5CEFA9F23C8 (`rtl/tests/x86/synth/x86_core_synth.sv`,
   `rtl/tools/synth_path.sh` for the worst path): single-cycle issue 5.88
   MHz (serial oldest-first select + execute + capture); pipelined issue
   45.9; registered flush 47.9; RS budget off the dispatch count 56.5
   MHz at 38,946 ALMs (34 %), 17,056 registers; with 8/16-bit operands,
   shifts and the BTB (registered update) 40.99 MHz, 43,639 ALMs (38 %),
   20,086 registers, worst path decode -> branch target -> redirect
   compare -> uop queue push, hence the P stage. DE25-Nano
   A5EB013BB23BE4SCS (Quartus Pro 26.1.1, R/D split, before the BTB):
   133.48 MHz slow fix4 0C, 34,173 / 46,800 ALMs (73 %): the D11 bench
   board runs the core 2.4x faster but has little room left.
3. M3 loads/stores, LSQ, L1I/L1D, then L2; Dhrystone/CoreMark for x86 IPC.
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

## Layout

- `rtl/x86/` SystemVerilog sources, one module per file.
- `rtl/tests/x86/` assembly tests; `rtl/tools/x86_test.sh` +
  `x86_trace_check.c` (Unicorn 2.1.4) for the reference.
- The DE25-Nano (46,800 ALMs) hosts milestone subsets; the full core is
  sized for the A9 (C5, selection criterion).
