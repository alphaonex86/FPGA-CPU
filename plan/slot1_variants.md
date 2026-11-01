# Slot 1 / Socket 370 CPU variants A, B, C1, C2 (D26, 2026-11-01)

Feasibility study asked by the operator (D26 in `slot1.md`): every variant
checked against sources; the infeasible ones are discarded with the reason.
Speeds marked *estimate* are not measured yet; "Measure" lines say how.
Constraints in force: D27 FSB at 66 MHz allowed, D28 board devices (IDE,
PCI, ISA) may be slower than CPU and RAM, D12 board RAM used only as needed
(DMA).

## Common facts (all variants)

- FSB speed is set by the CPU: Slot 1 BSEL0 low = 66 MHz, high = 100 MHz
  [`sockets/slot1/pentium3_secc2_24445201.pdf` p.19 sec. 2.8.2]; PGA370
  BSEL[1:0] = 00 66 MHz, 01 100 MHz, 11 133 MHz [`sockets/socket370/
  pentium3_pga370_245264-008.pdf` p.26 Table 5]. 66 MHz GTL+ at the edge
  fingers: output valid 1.07-6.37 ns, setup 1.96 ns, hold 1.53 ns
  [`sockets/slot1/celeron_sepp_24365803.pdf` p.26 Table 13].
- Board DMA reaches the CPU bus only as snoops: the 440BX issues a Memory
  Read & Invalidate on the host bus for each PCI write to DRAM and a Memory
  Data Read for each PCI read [`sockets/slot1/board/
  intel_440bx_host_bridge_29063301.pdf` pdf p.93 Table 4-5]; AGP-protocol
  cycles are never snooped [same, pdf p.91, p.106], nor GART aperture cycles
  [same, pdf p.11; VIA `sockets/socket370/via_vt82c694t_datasheet_1.00.pdf`
  pdf p.43 note].
- A snooping agent may stall the snoop phase by asserting HIT# and HITM#
  together, resampled every 2 clocks for as long as needed; HITM# makes it
  supply the line (implicit writeback) [`sockets/socket370/
  pentium_pro_developers_manual_vol1.pdf` p.3-19 / pdf p.54].
- Consequence, the *DMA mirror* (used by A, B, C2 whenever the CPU RAM is
  not the board's DIMM): for a DMA read the FPGA stalls the snoop, fetches
  the current line from its own RAM and returns it with HITM#; for a DMA
  write the FPGA records the snooped address, later reads the line from the
  board DRAM with its own bus read and copies it to its RAM. Invariant
  (in RTL): every recorded line is copied before an interrupt is forwarded
  to the CPU, so a driver never sees "DMA done" before the data.
  Limits: guest RAM <= board DRAM (the chipset decodes DMA only inside its
  DRAM: 440BX 512 MB, 1 GB registered [440BX pdf p.12]; VT82C694T 1.5 GB
  [VIA pdf p.9]); AGP texture DMA bypasses it (use a PCI card or keep the
  GART pages in board RAM); the VIA "snoop filtering" [VIA pdf p.11] may
  skip repeated snoops of one line: test it on the board first.
- Pins for a DE25 board at 66 MHz (D27): the S370 FPGA signals are D64,
  DEP8, A33, REQ5, AP2 (wide) + ~20 phase signals needing same-clock
  reaction + ~30 slow ones (`hw/socket370-cyclonev/pins.csv`). 2:1 on the
  112 wide lines = 56 + 20 direct + ~4 lines of a slow shift chain + ~6
  strobes/directions = ~86. DE25-Standard has 116 [`cpu_core.md` E1]:
  fits; each muxed line runs 133 MHz, the same rate judged plausible for
  S7 on HSMC. DE25-Nano has 72: only with 3:1 on data (200 MHz on 0.1"
  headers): not counted on. Timing: a board-clocked register + GTL
  translator must drive within 6.37 ns of BCLK; the SN74GTL16612 (18-bit
  LVTTL/GTL+ registered transceiver, TI status active) is the candidate
  for the register + level stage. Every 66 MHz claim is to be confirmed
  on the D8 boards (some set the FSB by jumper, not by BSEL).

## A. Own x86 core in the cartridge FPGA (current plan)

- Feasible: it is `x86_core.md` (C6-C8), plus the Slot 1 bus unit, local
  DDR3 (D10) and the DMA mirror above.
- Speed *estimate*: 100 MHz x 2 IPC target on 5CEFA9 ~ a P-III at 200 MHz,
  below the board's own P-III 1 GHz. On an Agilex 5 the same netlist ran
  2.7x faster (`cpu_core.md` E1), but the DE25 parts are 2.6x smaller.
- Status: kept. Only variant with no second processor and no software
  layer; the RTL is shared with the S3/S7/S370 interposers.

## B. Real ARM64 core + x86 translation (FPGA as translator)

Verified facts:
- Agilex 5 HPS: 2x Cortex-A76 up to 1.8 GHz + 2x A55; the FPGA-to-HPS
  bridge is one 256-bit ACE5-Lite port, cache coherent through the CCU
  [Intel Agilex 5 device overview 762191 "HPS in SoCs"; HPS TRM 814346
  "FPGA-to-HPS bridge"]. A76 = Armv8.2-A + LDAPR (RCpc) [HPS TRM 814346
  "MPU A76 core"]; no FlagM (v8.4).
- A hard core cannot take instructions from the fabric: the FPGA can only
  write ARM code into memory (coherent bridge); the A76 fetches it as normal
  memory, after an I-cache invalidate done in A76 software (Arm requires
  it for any code written by another agent).

What the FPGA translator buys, and what it does not:
- Translation time: a hardware translator (our M1 length decoder reused,
  plus an ARM64 emitter) produces code per block in nanoseconds, where a
  software DBT spends thousands of host cycles; this matters at boot and
  for code run once, not in steady state. Denver (NVIDIA) and Crusoe
  (Transmeta) are the hardware/firmware DBT precedents; their speed came
  from assists *inside* the core (shadow registers, gated store buffer,
  alias detection [realworldtech "Wolves in CISC Clothing"; USPTO
  6011908]), which an external FPGA cannot add to an A76.
- Steady state is decided by what the generated code must do:
  1. Memory model: x86 TSO vs Arm weak ordering is the largest DBT cost
     (FEX developers: 10-30 % slower than native on average, memory-model
     emulation the main bottleneck [github.com/FEX-Emu/FEX discussion
     5349]); Rosetta 2 reaches ~78-79 % of native with hardware TSO
     [en.wikipedia.org/wiki/Rosetta_(software)]. Here the guest is single
     threaded on one A76 (operator, E1), so guest RAM needs no barriers;
     only MMIO / I/O (device memory) and DMA-visible accesses are ordered.
     This removes the main cost.
  2. Flags: CF/ZF/SF/OF map to NZCV (CF inverted after SUB, one extra
     instruction without FlagM); PF/AF lazily from the saved result;
     dead-flag elimination at translation drops most of it.
  3. Registers: 8 x86 GPRs + EFLAGS state + segment bases fit pinned in the
     31 Arm registers.
  4. MMU: QEMU-TCG's slowness is mostly its software TLB on every access.
     Native speed needs shadow page tables: x86 page tables mirrored into
     A76 stage-1 tables (VMware-style, write-protect guest tables), FS/GS
     bases added explicitly, non-flat segments on a slow path.
  5. Self-modifying code: write-protect translated pages; precise
     exceptions: block-level state recovery; interrupts at block ends.
  6. x87 80-bit: softfloat (slow) or 64-bit double (FEX-style reduced
     precision); SSE/SSE2 -> NEON is direct.
- Speed *estimate*: 70-90 % of the A76's native speed on integer code,
  i.e. several times a P-III 1 GHz; far above A, below C2.
- Cost: the largest of all variants: a hardware translator plus a full
  system runtime on the A76 (shadow MMU, exceptions, interrupts, I/O, SMM)
  - FEX-sized software on top of new RTL.
- Platform: the DE25-Standard via the 66 MHz 2:1 adapter (pins above), or
  an Agilex 5 SoC on our own cartridge.
- Measure first (cheap, answers "how far from native"): FEX or Box64 on
  the DE25 A76 under Linux, same benchmark natively (CoreMark, 7-zip).
- Status: feasible, kept as the research variant; the claim "FPGA
  translator = native ARM speed" holds only for the translation time; the
  steady-state speed comes from points 1-5, all in A76 software.

## C1. Low-power x86 with its own FSB + FPGA bus translator

- Candidates: Atom N270 1.6 GHz, 2.5 W, 533 MT/s source-synchronous FSB
  [Intel N270 datasheet, May 2008]; Core 2 Duo SU9400 1.4 GHz, 800 MT/s
  FSB [Intel product page 36697].
- The FPGA would be the full northbridge of that CPU (its memory, its
  interrupts) and a P6 agent on the board: two bus protocols, one of them
  the quad-pumped Pentium 4-class bus, for which no public protocol
  specification was found (datasheets give signals and AC timing only), at
  533-800 MT/s with source-synchronous strobes.
- Speed: Atom N270 ~ P-III 1 GHz class (in-order), so no gain over the
  original CPU; Core 2 ULV ~2-3x, but the parts are second-hand only (BGA,
  2008-2009).
- Status: discarded (no protocol documentation, no gain for the Atom, no
  authorized stock). Reopen only if the operator has the FSB protocol
  documents.

## C2. Modern ~6 W x86 + FPGA PCIe <-> P6 bridge, board BIOS and OS in a VM

Shape: an Intel N100 (4 cores, 6 W TDP, 9 PCIe 3.0 lanes, VT-x + EPT,
VT-d [Intel product page 231803]) runs Linux + KVM; one vCPU executes the
board's stock BIOS and the OS natively under VT-x. The FPGA on the cartridge
is a PCIe endpoint and a P6 bus agent: the VMM forwards every guest I/O
port and every non-RAM physical address to the FPGA, which runs it as a bus
cycle on the board. Guest RAM is the N100's own; the board DIMM holds only
the DMA mirror.

- CPU and RAM speed *estimate*: native (VT-x), ~10x a P-III 1 GHz on
  integer code; board devices slower (each access = VM exit + PCIe round
  trip + bus cycle, ~2-3 us), accepted by D28.
- CPUID is the VMM's choice: report a P-III signature to the stock BIOS.
- Interrupts: the FPGA sees INTR/NMI (LINT0/LINT1) and SMI#, signals them
  by MSI; the VMM runs the interrupt-acknowledge cycle through the FPGA to
  get the vector and injects it (KVM without in-kernel irqchip). SMM runs
  in the VM (KVM SMM support); the FPGA marks its bus cycles as SMM while
  the guest is in SMM.
- Shadow BIOS / ROM fetches: the VMM copies ROM and shadow regions into
  guest RAM once the BIOS enables shadowing, so POST does not fetch every
  instruction over PCIe.
- DMA: the DMA mirror (common facts); limits there apply (guest RAM <=
  board DRAM, AGP texture DMA, VIA snoop filtering).
- FPGA: needs PCIe hard IP, which the 5CEFA9 (E variant) lacks. Candidates:
  Cyclone V GX (PCIe Gen1/Gen2 hard IP up to x4 [Cyclone V device overview
  683694]; Quartus Lite free for Cyclone V; PCIe IP licence-free per an
  Intel forum answer for Cyclone V ST - confirm for GX), Artix-7 XC7A100T
  (in the free Vivado ML Standard device list [AMD UG973]; PCIe block
  licence to confirm in Vivado). Logic need is small (bus unit + PCIe +
  mirror), so a small GX part may do.
  The C2 cartridge cannot reuse the slot1-cyclonev PCB with a GX part:
  Quartus rejects 5CEFA9F23C8 -> 5CGXFC9C7F23C8 as a migration pair (Error
  119016, test 2026-11-01), although 5CGXFC9 (same 301K LE as the A9)
  exists in F23 in C6/C7/C8 grades (Quartus 25.1 part list).
  Bench boards with PCIe edge + wide I/O (prices DigiKey 2026-11-01):
  Numato Tagus NLFX1005 (XC7A200T, FMC, 1,397 USD, in stock); AMD AC701
  (XC7A200T, PCIe x4, FMC HPC, 1.5-2.8 kUSD); ALINX AX7A200B (XC7A200T,
  PCIe 2.0 x2/x4, 2x 40-pin headers, price unverified).
  Filter (operator, 2026-11-01: drop boards without accessible software or
  a software alternative, then the 2 best by price):
  - Toolchains: Quartus Lite works here (Cyclone V GX/GT). Vivado 2025.2 ML
    Standard is licence-free and lists XC7A200T [AMD UG973], but the
    download is behind an AMD account + export form, not verified from
    Bolivia; alternative openXC7 (yosys + nextpnr-xilinx) has Artix
    PCIE_2_1 + GTP support in release 0.9.0, PCIe hardware-verified only on
    Kintex-7 [github.com/openXC7/nextpnr-xilinx releases 0.9.0].
    Update 2026-11-01 (operator): the Vivado download from Bolivia works
    (in progress); board choice after it finishes.
  - Dropped: LiteFury/NiteFury (M.2, too few I/O); Tagus, AC701, Cyclone V
    GX/GT Intel kits (945-2,800 USD; GX kit stock 0, GT kit -B 1,380-1,558
    USD, stock 0) on price.
  - Best 2 by price: Puzhi PZ-A7200T-KFB (XC7A200T-2FGG484I, PCIe 2.0 x2,
    2x 40-pin, ~62-64 single-ended I/O, 1 GB DDR3, 343 USD eBay listing)
    and ALINX AX7A200B (XC7A200T, PCIe 2.0, 2x 40-pin, documented manual,
    ~60,400 RUB at serverflow.ru, out of stock). Both need Vivado or
    openXC7.
  - I/O: ~64 lines do not carry the full 66 MHz 2:1 Slot 1 bus (~86, see
    common facts). They do carry a transaction link to a cartridge FPGA
    that owns the bus pins (e.g. the slot1-cyclonev cartridge plus a link
    header): ~20-40 lines at 100 MHz move one bus transaction in well
    under the ~2-3 us device-access budget. The bench steps before the
    cartridge (PCIe + VMM forwarding latency) need no bus pins at all.
  The LattePanda Mu
  Lite carrier has a PCIe 3.0 x4 slot (12 V input only) [docs.lattepanda.com
  mu_edition/lite_carrier]; coreboot supports the Mu [doc.coreboot.org].
- x86 module: LattePanda Mu (N100, 8 GB LPDDR5, 60 x 69.6 mm, up to 9 PCIe
  3.0 lanes, TDP 6-35 W, ~161 EUR at Mouser [cnx-software 2024-04-11;
  Mouser DFR1146]) could sit on the cartridge itself (stacked board, AGENTS
  rule), or any N100 mini-PC by an external PCIe cable.
- Power: N100 6 W + FPGA + translators, inside the Slot 1 / S370 budget
  with the external DC input (D13).
- Software: Linux + KVM + a small VMM of our own (I/O and MMIO forwarding,
  interrupt bridge, shadow copy, mirror control); QEMU is the fallback
  base, but its machine models would have to be removed.
- Status: feasible, best speed per effort; risks to retire first on the
  bench: the VIA snoop filtering and the board's tolerance of long snoop
  stalls (VIA Rx52 "Dynamic Defer Timer" [VIA pdf p.31] is to be read
  before), PCIe latency per device access, AGP cards.

## Ranking (speed / effort)

| variant | CPU speed vs P-III 1 GHz (*estimate*) | new hardware | new software | verdict |
|---|---|---|---|---|
| A | ~0.2x | cartridge (exists) | none | kept, shared RTL |
| B | several x | DE25-Standard + adapter, or own Agilex 5 SoC card | translator RTL + full-system runtime | kept, research; measure FEX first |
| C1 | ~1x (Atom) | FPGA northbridge for a P4-class bus | none | discarded |
| C2 | ~10x | FPGA with PCIe + N100 module | VMM on KVM | kept, best |
