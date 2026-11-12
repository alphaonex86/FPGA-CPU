# x86_core benchmark history

One row per architectural change, optimisation or cache concept of the core, written by
`rtl/tools/x86_bench.sh "<change>"` (operator 2026-11-12). Only the project's own core (rtl/x86):
external CPUs such as the C2 Mu are excluded. The programs and their sizes are the same for every
architecture (split or unified L1, other sizes, caches resized at run time, new ideas), so rows compare
architectures as well as changes; `config` names the configuration (`X86_PARAMS` to Verilator,
`CONFIG`). Each program loops forever; after its first run (the warm-up) exactly the set's cycles
are measured on the core model, the whole trace checked against Unicorn. A score is IPC (x86
instructions retired per cycle; n/a: an instruction the core cannot run yet, x87 before M6). The
clock (fmax) and power are not in the score: a change that moves them notes the Quartus result in its
text. Earlier measurements (CoreMark/MHz per step) are in plan/x86_core.md.

Each row holds the geometric mean of each group, then of every program (`all`); every program's IPC
of every run is in `plan/bench_results.csv` (set, date, commit, config, change, program, group, ipc),
and the script prints each program against the first run of the set with the same config. The set id
is a hash of the programs, their sources, flags and cycles: a new id starts a new table.

Groups (sources in rtl/tests/x86/bench/ and rtl/tests/x86/; portable C, no assembly):
- `lat`: a list chase, one node per 32-byte line in a coprime stride (load-to-use latency), over
  8 KB / 64 KB / 256 KB / 1 MB.
- `bw`: a sequential sum (read bandwidth) over the same sizes, and copy_256k (half onto half: writes).
- `code`: code_11k and code_87k, that much code called once per pass (instruction fetch);
  codedata_27k, 15 KB of code reading 12 KB of data (split against unified L1).
- `phase`: hot 4 KB, cold 512 KB, hot 4 KB (caches that adapt: resizing, gating, replacement).
- `core`: ilp (8 independent chains: width), chain (one dependent chain: latency), branch (random
  stores: misprediction), call (recursion: call / return).
- `app_i386` / `app_full`: application profiles, each built generic (-march=i386: any x86) and with
  every instruction the core runs (`ISA_FULL`, raised at M6 / M7): coremark, mix, core, string, bits
  (c5, c1-c4), interp (Python-like bytecode interpreter: dispatch, reference counts, dict), objects
  (Java-like: virtual calls, allocation, GC mark), compress (LZ77 + decompression), sort (quicksort),
  hash (hash join over 384 KB), crypto (SHA-256), parse (tokenizer + recursive-descent evaluator).
- `fp`: fpu (x87 double), built with `ISA_FULL`.

Set 1 (retired 2026-11-12: sizes followed the configured caches, no warm-up window): 1,000,000
cycles from reset, +mem_lat=10; b_l1 / b_l2 / b_ram: a list chase + sum over half the L1D, half
the L2, twice the L2.

| date | commit | L1I / L1D / L2 KB | change | c5_coremark | c1_mix | c2_core | c3_string | c4_bits | b_l1 | b_l2 | b_ram | b_fpu | geomean |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-11-12 | f42f776 | 16 / 16 / 256 | baseline: M5 core + HITM# | 1.650 | 1.694 | 1.427 | 1.161 | 1.265 | 2.320 | 1.108 | 0.593 | n/a | 1.315 |

Set 2 (retired 2026-11-12, one row: no groups, no ISA variants, no application profiles): 1,000,000
cycles per program after its warm-up, +mem_lat=10.

| date | commit | config | change | coremark | mix | core | string | bits | lat_8k | lat_64k | lat_256k | lat_1m | bw_8k | bw_64k | bw_256k | bw_1m | copy_256k | code_11k | code_87k | codedata_27k | phase | fpu | geomean |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-11-12 | f42f776 + bench | default | baseline of set 2 (f42f776 RTL) | 1.681 | 1.700 | 1.418 | 1.163 | 1.266 | 1.279 | 0.486 | 0.454 | 0.231 | 2.710 | 1.787 | 1.711 | 1.671 | 1.124 | 0.781 | 0.602 | 0.955 | 1.911 | n/a | 1.096 |
