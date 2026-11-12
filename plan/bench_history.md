# x86_core benchmark history

One row per architectural change or optimisation of the core, written by
`rtl/tools/x86_bench.sh "<note>"` (operator 2026-11-12). Only the project's own core (rtl/x86):
external CPUs such as the C2 Mu are excluded. Each program loops forever and runs exactly
1,000,000 cycles on the core model (+mem_lat=10, the trace checked against Unicorn); the cells
are IPC (x86 instructions retired / 1,000,000), the last the geometric mean of those that ran
(n/a: an instruction the core cannot run yet, x87 before M6). The core's clock (fmax) is not in
the score: a change that moves it is noted with the Quartus result. Earlier measurements
(CoreMark/MHz per step) are in plan/x86_core.md. Cache sizes are a column (L1I / L1D / L2 KB, the
script's L1I_KB, L1D_KB, L2_KB): one table compares sizes as well as changes.

Programs: c5_coremark, c1_mix, c2_core, c3_string, c4_bits (rtl/tests/x86/); b_l1, b_l2, b_ram
(rtl/tests/x86/bench/b_mem.c: a list chase + a sequential sum over half the L1D, half the L2,
twice the L2), b_fpu (x87 double).

| date | commit | L1I / L1D / L2 KB | change | c5_coremark | c1_mix | c2_core | c3_string | c4_bits | b_l1 | b_l2 | b_ram | b_fpu | geomean |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
