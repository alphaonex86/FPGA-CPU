# FPGA-CPU

An x86 CPU in an FPGA, on an interposer that plugs into an original PC CPU
socket and runs the board's stock BIOS, chipset, RAM and disks.

## Goals

- ISA: i686 + x87 + MMX + SSE + SSE2 first (modern software such as Node.js
  requires SSE2), then x86-64 and SSE3..SSE4.2 (x86-64-v2).
- Large on-chip L2 (>= 128 KB) to hide the slow front-side bus and board RAM.
- Best possible performance on each platform; many configurations (ISA level,
  cache sizes, clocks) from one RTL tree.
- Optional RAM on the module, next to the FPGA.
- Vendor-neutral RTL, so a popular model could later become an ASIC.

## Target boards

| Socket | Board | Chipset | Host bus |
|---|---|---|---|
| Socket 3 | Biostar MB-8433UUD | UMC 8881F / 8886BF | 486, 32-bit, 25/33/40 MHz |
| Socket 7 | Biostar MB-8500TTD | Intel 430TX | P5, 64-bit, 60/66 MHz |
| Socket 370 | VIA Apollo Pro 133A board (TBD) | VT82C694X | P6 AGTL+, 66/100/133 MHz |

## FPGAs

| FPGA | Logic | Block RAM | Package | Free toolchain |
|---|---|---|---|---|
| Altera Cyclone V E A9 — 5CEBA9/5CEFA9F23C8N (preferred) | 301k LE | 14.25 Mb | F484, 23x23 mm, 1.0 mm pitch, 224 I/O | Quartus Prime Lite (no licence) |
| Efinix Titanium Ti180 — TI180G400C3 | 176k LE | 13.1 Mb | 16x16 mm, 0.8 mm pitch, 274 I/O | Efinity (no licence) |

Both had authorized distributor stock at the end of 2026. The survey, I/O budget
per socket and power budget are in [FPGAlist/README.md](FPGAlist/README.md).

## Status

Planning: FPGAs chosen, documentation collected. No RTL yet.

## Layout

- `AGENTS.md` — project rules and requirements.
- `FPGAlist/` — FPGA survey; `CycloneV_A9/` and `Ti180_G400/` hold the vendor
  documentation, pin-outs, models, board references and toolchain notes.
- `sockets/` — original CPU datasheets (bus protocol, pinout, power).
- `fetch.sh` — downloads everything listed in the `sources.txt` files.

## Offline documentation

Vendor files are not stored in git (copyright, size). Download them with:

    ./fetch.sh FPGAlist/*/sources.txt sockets/sources.txt

Quartus and Efinity need a vendor account: see
[FPGAlist/CycloneV_A9/README.md](FPGAlist/CycloneV_A9/README.md) and
[FPGAlist/Ti180_G400/README.md](FPGAlist/Ti180_G400/README.md).

## License

GPL-3.0, see [LICENSE](LICENSE).
