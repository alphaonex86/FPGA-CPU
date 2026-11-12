# x86_core power per workload

Written by `rtl/tools/x86_power.sh "<change>"` after `rtl/tools/x86_bench.sh` and a full socket 3
build of the same RTL. Each program's measured window (2000 cycles after its warm-up, core clock
30 ns) is dumped from the core model as a VCD and read by the Quartus Power Analyzer on that build's
netlist: about 60 % of the registers take their toggle rate from the program, the rest is propagated
from them. A cell: total FPGA power in W / energy per instruction in nJ (power x clock period / IPC
of the window). Rows of different builds (device, placement) compare less exactly than rows of the
same build; the vectorless estimate of a build is in its `s3.pow.summary` (1.10 W at 12.5 % toggle,
2026-11-12, C8). First measurement 2026-11-12 (C8 build, by hand): CoreMark 2.36 W total, 1.76 W
core dynamic.
