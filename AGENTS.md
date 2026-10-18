# AGENTS.md — FPGACPU

FPGA x86 CPU on an interposer that plugs into an original CPU socket and runs the
board's stock BIOS, chipset, RAM and disks unmodified. Goal: best achievable
performance on each platform.

## Target platforms (only what the operator can test)

| Socket | Board | Chipset | Host bus | Original CPU power |
|---|---|---|---|---|
| Socket 3 | Biostar MB-8433UUD | UMC 8881F / 8886BF | 486, 32-bit, 25/33/40 MHz, Vcc 3.45/4/5 V jumper | IntelDX4-100: 4.3 W max |
| Socket 7 | Biostar MB-8500TTD | Intel 430TX | P5, 64-bit, 60/66 MHz, 3.3 V I/O | Pentium MMX 233: 17 W |
| Socket 370 | TBD, VIA Apollo Pro 133A | VT82C694X | P6 AGTL+ (VTT 1.5 V), 66/100/133 MHz | Pentium III-S 1.4 GHz: 32 W |

## CPU requirements

- Bus behaviour of an original CPU of each socket; CPUID and reset signature
  configurable per board so the stock BIOS accepts it.
- ISA baseline: i686 + x87 + MMX + SSE + SSE2 (modern software, e.g. Node.js,
  requires SSE2).
- Must stay extensible to x86-64 long mode, then SSE3..SSE4.2/POPCNT (x86-64-v2).
- On-chip L2 >= 128 KB, larger when the FPGA allows: the FSB and board RAM are
  the bottleneck for modern software and OSes.
- Power within the socket's budget (table above); Socket 3 is the tightest.
  FPGA < 10 W preferred; 10-40 W with an external supply only for a large gain
  (an ASIC of the same design would draw much less).
- Voltage level translators allowed (wider FPGA choice, easier routing); prefer
  compact ones.

## Additional goals

- Many configurations from one RTL tree (ISA level, cache sizes, clocks) to
  benchmark against each other.
- Module variant with its own RAM next to the FPGA.
- Possible ASIC if one model gets strong group demand: keep RTL vendor-neutral,
  vendor primitives only in thin wrappers.

## FPGA choice

- Toolchain must be free with no limit that blocks a full CPU design, for the
  exact device + package; anything needing a paid licence is rejected.
- Selected (authorized stock end of 2026): Altera Cyclone V E A9
  5CEBA9/5CEFA9F23C8N (preferred: 1.0 mm pitch, more logic) and Efinix Ti180
  TI180G400C3. Survey in `FPGAlist/README.md`.

## Layout

- `FPGAlist/` — FPGA survey (`README.md`), one subfolder per selected FPGA with
  datasheets, tools and board files for offline work.
- `sockets/` — original CPU datasheets (bus, pinout, power).
- `fetch.sh <sources.txt>...` — (re)downloads every file listed in a
  `sources.txt`; vendor-login software is listed in each folder's README.

## Rules

- Everything on disk is English.
