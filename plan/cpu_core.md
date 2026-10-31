# CPU core: base project evaluation (2026-10-31)

Idea (operator, 2026-10-31): do not write an x86 core from scratch; take an
open RISC-V core as the back end and make x86 (and RISC-V) "just a front
end" that cracks opcodes into the back end's micro-ops.

Requirements it must meet (`AGENTS.md`): >= 2 instructions per cycle,
i686 + x87 + MMX + SSE + SSE2, extensible to x86-64 then x86-64-v2, L2
>= 128 KB, per-socket bus behaviour, vendor-neutral RTL (ASIC option),
many configurations from one tree, fits Cyclone V E A9 (301k LE) and Ti180
(176k LE) (`FPGAlist/README.md`).

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
| BOOM, CVA6, XiangShan | RV64 | OoO / in-order | - | ASIC-oriented, no FPGA area claim found | Chisel / SV | too large or unmeasured for these parts |

Sources: [vexii] https://github.com/SpinalHDL/VexiiRiscv and
https://spinalhdl.github.io/VexiiRiscv-RTD/ ; [nax]
https://github.com/SpinalHDL/NaxRiscv ; [soom]
https://github.com/git-mathis/SoomRV ; [biri]
https://github.com/ultraembedded/biriscv ; [ao486]
https://github.com/alfikpl/ao486 , https://opencores.org/project/ao486 ;
[z386] https://linuxiac.com/open-source-z386-brings-intel-80386-microcode-back-to-life/ ,
https://misterfpga.org/viewtopic.php?p=107765 .
No published design does hardware x86 -> RISC-V micro-op cracking; the
nearest is an FPGA binary-translation research poster (HABITAT, St Andrews,
SICSA 2026), which is software-assisted translation, not a decoder.

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
- Generates plain Verilog: vendor-neutral, same tree for Cyclone V, Ti180
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

## Next steps (each answers a concrete question)

1. Generate VexiiRiscv dual-issue RV64 (no FPU, then with D) and run
   Quartus Lite 25.1 (installed, `~/altera_lite/25.1std`) on 5CEFA9F23C8:
   ALMs, fmax. Does the back end leave room for x86 decode + x87 + SSE +
   L2 >= 128 KB inside 301k LE, and at what clock?
2. Same netlist in Efinity for the Ti180 (176k LE): does it fit at all?
3. Only then: an x86 decode plugin for the integer reg-reg / load-op
   subset, lock-stepped against an emulator, on the RISC-V back end.
