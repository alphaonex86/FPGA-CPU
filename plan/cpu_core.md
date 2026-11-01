# CPU core: base project evaluation (2026-10-31)

Idea (operator, 2026-10-31): do not write an x86 core from scratch; take an
open RISC-V core as the back end and make x86 (and RISC-V) "just a front
end" that cracks opcodes into the back end's micro-ops.

Requirements it must meet (`AGENTS.md`): >= 2 instructions per cycle,
i686 + x87 + MMX + SSE + SSE2, extensible to x86-64 then x86-64-v2, L2
>= 128 KB, per-socket bus behaviour, vendor-neutral RTL (ASIC option),
many configurations from one tree, fits Cyclone V E A9 (301k LE) (the
Ti180 is out: Efinix prohibited, `plan/interposers.md` D10) (`FPGAlist/README.md`).

## Candidates

All figures are the projects' own claims, not measured here.

| core | ISA / width | execution | perf claim | FPGA size claim | HDL, licence | fit |
|---|---|---|---|---|---|---|
| VexiiRiscv | RV32/64 IMAFDCSUB, MMU Sv32/Sv39 | in-order, single or dual issue (asymmetric lanes), BTB/GShare/RAS | 5.24 CoreMark/MHz, 2.50 DMIPS/MHz [vexii] | none published | SpinalHDL (Scala) -> Verilog, MIT [vexii] | best base, see below |
| NaxRiscv | RV32/64 IMAFDCSU, MMU | out-of-order, register renaming, e.g. 2 decode / 3 EU / 2 retire | 2.93 DMIPS/MHz, 5.02 CoreMark/MHz @ 155 MHz | 13.3 kLUT, Artix-7 -3 [nax] | SpinalHDL; licence not stated on the page | OoO upgrade path, same author and framework |
| SoomRV | RV32IMAC | 4-wide OoO | 5.42 CoreMark/MHz [soom] | none published | SystemVerilog, MIT | no RV64 datapath: blocks x86-64 |
| biRISC-V | RV32IM | in-order dual issue | 4.1 CoreMark/MHz, 1.9 DMIPS/MHz [biri] | "fits Artix-7, > 50 MHz" | Verilog | no FPU, no 64-bit: too small |
| ao486 | x86 486SX (no x87) | scalar, microcoded | Win95/Linux boot; fmax 39 MHz on Cyclone IV [ao486] | CPU 36,517 LE, SoC 91,256 LE (EP4CE115, `FPGAlist/README.md`) | Verilog | reference model for x86 semantics, not a base for 2 IPC |
| z386 | 80386 | rebuilt around Intel's recovered microcode | ~ao486 class [z386] | - | SystemVerilog | uses Intel's microcode: unusable for an ASIC / redistributed design |
| z486 (z386 successor, 2026-08) | 80486 + x87 (experimental, "sufficient to run DOS Quake"); no MMX/SSE | scalar pipelined: D1/D2 decode, hardwired common instructions, microsequencer for complex ones | Dhrystone CPI 2.8 -> 2.0 (IPC 0.36 -> 0.5); "roughly 486DX2-66-class"; Doom timedemo 29.1 FPS vs 21.0 ao486; 85 MHz on MiSTer [z486] | 16,329 ALMs, 21,906 with x87 (DE10-Nano Cyclone V) [z486] | SystemVerilog, Apache-2.0, except the "recovered microcode image" [z486 LICENSE-SCOPE.md] | best x86 reference; same microcode problem as z386 |
| BOOM, CVA6, XiangShan | RV64 | OoO / in-order | - | ASIC-oriented, no FPGA area claim found | Chisel / SV | too large or unmeasured for these parts |

Sources: [vexii] https://github.com/SpinalHDL/VexiiRiscv and
https://spinalhdl.github.io/VexiiRiscv-RTD/ ; [nax]
https://github.com/SpinalHDL/NaxRiscv ; [soom]
https://github.com/git-mathis/SoomRV ; [biri]
https://github.com/ultraembedded/biriscv ; [ao486]
https://github.com/alfikpl/ao486 , https://opencores.org/project/ao486 ;
[z486] https://github.com/nand2mario/z486 , https://github.com/nand2mario/z486_MiSTer
(read 2026-11-01) ;
[z386] https://linuxiac.com/open-source-z386-brings-intel-80386-microcode-back-to-life/ ,
https://misterfpga.org/viewtopic.php?p=107765 .
No published design does hardware x86 -> RISC-V micro-op cracking; the
nearest is an FPGA binary-translation research poster (HABITAT, St Andrews,
SICSA 2026), which is software-assisted translation, not a decoder.

## z486 vs the VexiiRiscv back end (operator question, 2026-11-01)

Other cores looked at and dropped: S80186 (80186, GPL-3.0, ~1,800 ALMs,
60 MHz on Cyclone V: 16-bit only) [https://github.com/jamieiles/80x86];
a 2-way out-of-order x86 soft processor at ~200 MHz (Stanford EE380 talk,
2019) [https://web.stanford.edu/class/ee380/Abstracts/190605-slides.pdf],
no public RTL found.

| | z486 | VexiiRiscv + own x86 front end (C1-C3) |
|---|---|---|
| runs x86 today | yes: DOS, Doom, Quake; real/protected mode, paging, segments | no: front end, flags, segments, x86 MMU, x87, system all to write |
| measured here | not yet | rv64imac dual: 12,932 ALMs, 60.7 MHz, IPC 1.24 on RISC-V code |
| IPC | 0.5 (Dhrystone CPI 2.0) | 1.24 RISC-V; x86 IPC unknown until the cracker exists |
| >= 2 instructions/cycle | no: scalar, needs a U/V-pipe redesign of an x86-native pipeline | dual issue already there |
| x86-64 / SSE2 | none; 32-bit datapath | 64-bit datapath; SIMD lane still to add |
| licence / ASIC | RTL Apache-2.0, but complex instructions run Intel's recovered microcode (excluded from the licence): blocks an ASIC and any redistributed board | MIT, all own code |
| x87 | experimental, incomplete | to write (80-bit unit) |

Reading: z486 is far ahead on x86 semantics and could boot the Socket 3
board soonest; it falls short on the hard requirements (>= 2 IPC, SSE2,
x86-64, an ASIC-clean licence) and its microcode would have to be
rewritten anyway. Its Apache-2.0 hardwired paths, decoder and test sets
(test386.py, single-step real/protected-mode datasets) are usable as
reference and test material in either plan.

## Recommendation: VexiiRiscv as the back end

- Its pipeline is a set of plugins (fetch, decode, lanes, LSU, MMU, FPU),
  so an x86 decoder is "one more decode plugin" feeding the same lanes; a
  RISC-V decoder can stay as a second front end for bring-up (run the
  existing RISC-V tests and Linux first, then switch the front end).
- Dual issue in-order is the Pentium P5 model (U/V pipes), the simplest
  way to the operator's >= 2 instructions per cycle. NaxRiscv, same
  framework, is the OoO step if the FSB-bound workloads need it later.
- RV64 datapath already there: x86-64 long mode later is a decoder/MMU
  change, not a datapath rewrite.
- Generates plain Verilog: vendor-neutral, same tree for Cyclone V
  and an ASIC; every option is a Scala parameter, which matches "many
  configurations from one RTL tree".
- Cost: SpinalHDL/Scala knowledge and a JVM build (sbt or mill); the
  generated Verilog is not meant to be hand-edited.

## What the RISC-V back end does NOT give (x86 work list)

The "simple front end" is the decoder only for reg-reg ALU ops. The rest
is back-end work in Vexii plugins:

1. Decoder: 1-15 byte instructions with prefixes; 2 x86 instructions per
   cycle needs a predecoded length-marked I-cache line or a uop cache.
2. EFLAGS: RISC-V has no flags. Every ALU uop must produce CF/ZF/SF/OF/
   PF/AF (a flag lane or flags renamed with the result).
3. Partial registers and sizes: AL/AH/AX/EAX writes, 8/16/32(/64)-bit
   operand and address sizes, segment base added in the AGU, limits and
   checks in protected mode, real mode, V86, A20.
4. Load-op-store instructions cracked into 2-3 uops that commit or fault
   as one x86 instruction (precise exceptions at instruction boundaries),
   REP string ops, PUSH/POP/CALL/RET with ESP updates.
5. x87: 80-bit extended precision, register stack, tag word, exceptions.
   The RISC-V D unit is 64-bit: x87 needs its own unit (or a microcoded
   extended-precision path). MMX aliases the x87 registers.
6. SSE/SSE2: 128-bit XMM registers and 8x16/4x32/2x64 SIMD + scalar
   double; Vexii has no SIMD unit: new lane.
7. MMU: x86 two-level 32-bit paging (later PAE / 4-level), TLB with x86
   permission bits, accessed/dirty updates by the walker; Sv32/Sv39 walker
   is a template only.
8. Memory model: x86 TSO vs RISC-V RVWMO; self-modifying code needs a
   coherent I-cache (snoop on stores), no fence.i.
9. System: IDT, exceptions, task gates, SMM, I/O ports, CPUID, MSRs, TSC,
   reset signature, cache-control pins; micro-code sequencer for the
   complex instructions.
10. Bus: Vexii talks AXI4/TileLink/Wishbone; each socket needs its own
    bus unit (486, P5, P6 AGTL+) behind the L2.

ao486 (Bochs-modelled) is the reference for items 3, 4, 9 and for the
test approach (lock-step against an emulator, the way Vexii already
lock-steps against Spike).

## FPGAmotherboard compatibility (operator, 2026-11-01)

The core must run on the original boards and on the FPGAmotherboard boards
(FPGA chipset, other session; its rule 9: any fast mode is negotiated, off
by default). Contract received for Socket 3 (FPGAmotherboard
socket3/docs/notes/design-decisions.md):
- the board targets the Am5x86-P75 only [am5x86 19751C]: B13 = WB/WT#,
  CLKMUL (R17) tied low; the CPUID/reset-signature profile must offer it;
- bus CLK 8-33 MHz, changed only during Stop Grant (STPCLK#) for DVFS:
  the bus PLL must relock inside Stop Grant and the core must not assume
  a fixed bus clock;
- direct LVCMOS33, VIH 2.0 V / VOH 2.4 V min;
- VCORE starts at 0 V and comes up after the interposer FPGA: the bus
  interface ignores every socket pin and keeps the CPU parked until the
  board input VCORE_OK is high, and parks again when it falls
  (plan/interposers.md FPGAmotherboard compatibility).

## Decisions (core)

- **C1** (decided 2026-11-01 by the operator) x86 instructions crack into
  an own micro-op format, not into RISC-V instruction words: the x86 front
  end bypasses the Vexii RISC-V decoder (wide uops, 32/64-bit immediates)
  and feeds the execute lanes directly.
- **C2** (decided 2026-11-01 by the operator) EFLAGS in hardware: every
  flag-setting uop writes a flags register beside its result (new execute
  plugin, bypass between the two lanes); Jcc / ADC / SETcc read it in one
  cycle.
- **C3** (decided 2026-11-01 by the operator) Lock-step reference: Unicorn
  (QEMU CPU core as a C library, one hook per instruction), testbench only
  (GPLv2, never in the RTL).
- **C4** (decided 2026-11-01 by the operator) x86 first, but the RISC-V
  front end stays selectable at generation time (a config option, its code
  never deleted) for later experiments: e.g. RISC-V Linux with own firmware
  in the interposer (board BIOS never run; Debian riscv64 is RV64GC; device
  tree + i8259, 8250, i8042, IDE, CF8/CFC PCI drivers, x86 option ROMs via
  an emulator like U-Boot bios_emulator). Not a milestone now.

## Next steps (each answers a concrete question)

1. Generate VexiiRiscv dual-issue RV64 (no FPU, then with D) and run
   Quartus Lite 25.1 (installed, `~/altera_lite/25.1std`) on 5CEFA9F23C8:
   ALMs, fmax. Does the back end leave room for x86 decode + x87 + SSE +
   L2 >= 128 KB inside 301k LE, and at what clock?
   **Done 2026-11-01** (`rtl/tools/setup.sh`, `gen_vexii.sh <config>`,
   `synth_cv.sh`; VexiiRiscv 9f70315, core alone, ports virtual, 10 ns
   target, slow 1100 mV 85 C model):

   | config | ALMs | registers | M10K | DSP | fmax |
   |---|---|---|---|---|---|
   | rv64imac_dual (S/U + MMU, max-ipc, 16 KB L1 I/D) | 12,932 (11 %) | 16,360 | 105 | 17 | 60.7 MHz |
   | rv64imafdc_dual (same + F/D) | 16,879 (15 %) | 19,848 | 115 | 17 | 52.0 MHz |

   Room: yes, ~85 % of the ALMs and > 90 % of the M10K are left; a 128 KB
   L2 is 1 Mbit of the 12.5 Mbit. Clock: 50-60 MHz as generated, already
   above every Socket 3 bus clock (<= 40 MHz) but below Socket 7/370.
   Critical paths: the max-ipc lane1 -> lane0 early-ALU bypass (rv64imac)
   and the execute -> fetch TLB write (rv64imafdc), both inside the back
   end.

   fmax vs IPC sweep (2026-11-01, `rtl/tools/vexii_configs.sh`,
   `bench_vexii.sh`: prebuilt NaxSoftware Dhrystone / CoreMark in the
   VexiiRiscv Verilator testbench, default testbench memory; both fit the
   16 KB L1, so this is core IPC, not system IPC). CoreMark = CoreMark/MHz
   x fmax:

   | config | ALMs | fmax | DMIPS/MHz | CoreMark/MHz | IPC (CoreMark) | CoreMark |
   |---|---|---|---|---|---|---|
   | rv64imac_dual (max-ipc) | 12,932 | 60.7 | 2.61 | 4.84 | 1.24 | 294 |
   | rv64imac_dual_rbra (+ relaxed branch) | 12,839 | 60.6 | 2.59 | 4.72 | 1.21 | 286 |
   | rv64imac_dual_nolate (- late ALU) | 11,249 | 59.4 | 2.35 | 4.41 | 1.13 | 262 |
   | rv64imafdc_dual (+ F/D) | 16,879 | 52.0 | 2.60 | 4.84 | 1.24 | 252 |
   | rv64imac_single (max-ipc, 1 lane) | 9,524 | 65.0 | 1.78 | 3.33 | 0.85 | 216 |
   | rv64imac_dual_nolate_bp1 (- late ALU, bypass from 1) | 11,035 | 59.1 | 1.49 | 2.81 | 0.72 | 166 |

   Answer: the full max-ipc dual-issue core is the best; the lighter
   bypass, no late ALU and the relaxed branch cost IPC and buy no fmax.
   Each removal only moves the worst path (execute branch -> fetch L1 /
   TLB RAM address, then late-ALU 64-bit bypass, register file, dispatch):
   about 60 MHz is the depth of this pipeline at 64 bits on C8, not one
   path. More clock needs more stages (decoder/dispatcher/fetch fork
   placement), a later question. The F/D unit costs 14 % clock: keep the
   FPU off the integer critical loop when x87/SSE are added.
2. ~~Same netlist in Efinity for the Ti180~~: dropped, Efinix is
   prohibited (`plan/interposers.md` D10).
3. Only then: an x86 decode plugin for the integer reg-reg / load-op
   subset, lock-stepped against an emulator, on the RISC-V back end.
