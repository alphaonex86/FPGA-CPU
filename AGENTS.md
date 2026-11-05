# AGENTS.md — FPGACPU

FPGA x86 CPU on an interposer that plugs into an original CPU socket and runs the
board's stock BIOS, chipset, RAM and disks unmodified. Goal: best achievable
performance on each platform.

Linked project: https://github.com/alphaonex86/FPGAmotherboard (real CPU, FPGA
chipset, same sockets; source of `sockets/kicad/`).

## Target platforms (only what the operator can test)

| Socket | Board | Chipset | Host bus | Original CPU power |
|---|---|---|---|---|
| Socket 3 | Biostar MB-8433UUD | UMC 8881F / 8886BF | 486, 32-bit, 25/33/40 MHz, Vcc 3.45/4/5 V jumper | IntelDX4-100: 4.3 W max |
| Socket 7 | Biostar MB-8500TTD | Intel 430TX | P5, 64-bit, 60/66 MHz, 3.3 V I/O | Pentium MMX 233: 17 W |
| Socket 370 | TBD, VIA Apollo Pro 133A | VT82C694X | P6 AGTL+ (VTT 1.5 V), 66/100/133 MHz | Pentium III-S 1.4 GHz: 32 W |

## CPU requirements

- Bus behaviour of an original CPU of each socket; CPUID and reset signature
  configurable per board so the stock BIOS accepts it.
- Must work on both the original motherboards and the FPGAmotherboard boards
  (FPGA chipset, same sockets; developed by another session) (operator,
  2026-11-01).
- Superscalar: at least 2 instructions per cycle (operator, 2026-10-31).
- ISA baseline: i686 + x87 + MMX + SSE + SSE2 (modern software, e.g. Node.js,
  requires SSE2).
- Must stay extensible to x86-64 long mode, then SSE3..SSE4.2/POPCNT (x86-64-v2).
- On-chip L2 >= 128 KB, larger when the FPGA allows: the FSB and board RAM are
  the bottleneck for modern software and OSes.
- Power within the socket's budget (table above); Socket 3 is the tightest.
  FPGA < 10 W preferred; 10-40 W with an external supply only for a large gain
  (an ASIC of the same design would draw much less).
- On-board flash larger than the FPGA bitstream: it also holds BIOS and/or
  UEFI images, option ROMs and other firmware for experiments (operator,
  2026-11-01).
- Voltage level translators allowed (wider FPGA choice, easier routing); prefer
  compact ones.

## Additional goals

- Many configurations from one RTL tree (ISA level, cache sizes, clocks) to
  benchmark against each other.
- Module variant with its own RAM next to the FPGA.
- Stacked boards: 2-3 PCBs mounted on the base PCB (grow in height, not
  sideways) are allowed when needed, mainly for the sockets, e.g. RAM >= 1 GB
  (operator, 2026-10-31).
- Components on both PCB sides wherever there is no mechanical conflict
  (operator, 2026-10-31).
- Possible ASIC if one model gets strong group demand: keep RTL vendor-neutral,
  vendor primitives only in thin wrappers.

## FPGA choice

- Toolchain must be free with no limit that blocks a full CPU design, for the
  exact device + package; anything needing a paid licence is rejected.
- The toolchain must be downloadable from Bolivia: efinixinc.com is blocked
  there (HTTP 403) and Efinix has no free/open-source alternative flow, so
  Efinix FPGAs are prohibited (operator, 2026-11-01).
- Selected (authorized stock end of 2026): Altera Cyclone V E A9
  5CEBA9/5CEFA9F23C8N (preferred: 1.0 mm pitch, more logic); the Efinix
  Ti180 TI180G400C3 is dropped (rule above). Survey in `FPGAlist/README.md`.

## Layout

- `FPGAlist/` — FPGA survey (`README.md`), one subfolder per selected FPGA with
  datasheets, tools and board files for offline work.
- `sockets/` — per socket CPU, chipset and board docs; `sockets/kicad/` socket
  footprints, symbols, 3D models, pin maps.
- `isa/` — x86 ISA manuals.
- `plan/` — `interposers.md` (4 interposer boards, tasks, status), `slot1.md`, `slot1_variants.md` (A/B/C1/C2 study), `x86_core.md` (x86 core architecture),
  `cpu_core.md` (base core evaluation), `slot1_c2.md` (C2: N100 + FPGA bridge) and `prompt.md`.
- `sw/c2-vmm/` — Slot 1 C2 VMM (KVM); `test.sh` runs its test ROM.
- `rtl/` — RTL; `rtl/c2/` C2 bridge (`xilinx/build.tcl`: card bitstream), `rtl/tools/vivado.sh`.
- `fetch.sh <sources.txt>...` — (re)downloads every file listed in a
  `sources.txt` (`sockets/local-sources.txt`: local `file://` copies);
  vendor-login software is listed in each folder's README.

## Rules

- Everything on disk is English.
- Every document used is kept offline in the tree, never only as a link: seller and
  hardware-specific links die fast (operator, 2026-11-02).
- Slot 1 / Socket 370 FSB may run at 66 MHz when that gives a large benefit
  (board RAM only for DMA) (operator, 2026-11-01).
- PCB routing is the last step: pins (in a crossing-free order), placement and everything
  else final and verified first; routing never changes the pins (operator, 2026-11-05).
- CPU goal is maximum performance inside the selected Cyclone V: large rewrites,
  a from-scratch x86 core and a separate RISC-V core are all fine; licence is no
  selection criterion (GitHub code counts as usable; copyrighted parts, avoided
  when possible, go in a separate marked folder) (operator, 2026-11-01).
