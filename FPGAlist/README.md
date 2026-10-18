# FPGA survey (2026-10-18)

Need: x86 up to SSE2 now, x86-64 / SSE4.2 later, L2 >= 128 KB on-chip ->
>= 150k LUT4-equivalent, >= 4 Mbit BRAM, ~200 I/O, package <= 23x23 mm, free
toolchain with no limit blocking a full CPU (see `../AGENTS.md`). Level
translators allowed, so I/O voltage is not a filter.

Stock read live on 2026-10-18. Mouser, Arrow, Avnet, Farnell and Octopart blocked
automated access; "broker" = non-authorized seller.

## Top 5

| # | Part | Package | Logic | BRAM | DSP | I/O | Digi-Key (authorized) | Other sources | Free toolchain |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Altera Cyclone V E A9: 5CEBA9F23C8N / 5CEFA9F23C8N | F484, 23x23, 1.0 mm | 301k LE | 14.25 Mb | 342 | 224 | 60 @ $325.89 / 40 @ $354.22 | LCSC 0; broker 172 | Quartus Prime Lite 25.1 |
| 2 | Efinix Titanium TI180G400C3 | G400, 16x16, 0.8 mm | 176k LE | 13.1 Mb | 640 | 274 (74 at 3.3 V) | 760 @ $84.00 | none found | Efinity |
| 3 | AMD Artix-7 XC7A200T-FBG484 (or SBG484) | 23x23, 1.0 mm (SBG: 19x19, 0.8 mm) | 215k LC | 13.1 Mb | 740 | 285 (all HR 3.3 V) | 0, 52 wk ($275.99) | LCSC 650 @ $116.53 (-2I); brokers 7,467 | Vivado 2025.2 ML Standard |
| 4 | AMD Kintex-7 XC7K160T-FBG484 | 23x23, 1.0 mm | 162k LC | 11.7 Mb | 600 | 285 (185 HR + 100 HP) | 0 (1 due 2027-10, $398.97) | LCSC 28 @ $180.41 (-2I) | Vivado 2025.2 ML Standard |
| 5 | Efinix Titanium TI375C529C3 | C529, 19x19, 0.8 mm | 370k LE | 27.5 Mb | 1,344 | ~227 (51 at 3.3 V) + hard LPDDR4 | not stocked, 45 wk ($184.25) | none found | Efinity |

### Toolchain verdict (2 sources each)

- Quartus Prime Lite: no licence file, covers all Cyclone V incl. A9 (the A9
  exclusion was only in Web Edition 11.1-15.0). Missing: Logic Lock, register
  retiming, incremental compile. UniPHY DDR3 controller is paid -> write our own
  RAM controller (HyperRAM/SDRAM). Questa Starter capped at 5000 instances.
- Efinity: no licence, all devices and packages, debugger and IP included.
- Vivado 2025.2 ML Standard: no licence, never expires, covers XC7A200T,
  XC7K160T, KU3P/KU5P, AU25P (not Spartan US+ SU200P). 2026.1 BASIC is worse
  (yearly licence, xsim 50K instances, 1 ILA / 5 probes, no incremental).
- Simulation: every free vendor simulator is capped -> use Verilator.

### Notes per part

1. Cyclone V A9: largest logic in 23 mm with real authorized stock; ao486
   lineage (MiSTer). Fewest I/O (224). Lifecycle to 2045.
2. Ti180: cheapest, smallest, 16 nm, best authorized stock. Mostly 1.2-1.8 V
   HSIO -> translators. TI180J484 has only ~143 I/O.
3. XC7A200T: ao486 runs on XC7A100T at ~57 MHz with 128 KiB L2
   (github.com/KD5VMF/Nexys-A7-100T-ao486). No authorized stock now.
4. XC7K160T: faster fabric than Artix; 100 HP pins suit the RAM. Poor stock,
   higher static power.
5. Ti375: by far the most logic/BRAM for the best-performance target; no stock.

AGTL+ (Socket 370, VREF ~1.0 V) is outside datasheet VREF range on all of these
-> GTL translators or bench validation.

## Rejected

| Part | Reason |
|---|---|
| PolarFire MPF200T (all <= 23 mm packages) | needs paid Libero Gold |
| PolarFire MPF300T-1FCG484E | Silver OK but yearly licence + Linux floating server on physical host; Digi-Key 0 |
| Gowin GW5AST-138 PG484A | Education = non-commercial only; Standard = yearly MAC-locked licence; Apicula not usable; package stock unverified |
| Spartan US+ SU200P | only in Vivado 2026.1 (limited BASIC); Digi-Key 0 |
| Kintex US+ KU3P / KU5P SFVB784 | free in 2025.2 but $1,746 / $2,353, Digi-Key 0, 52 wk |
| Artix US+ AU25P SFVB784 | Digi-Key 0, 52 wk ($462) |
| Efinix Ti135N484 | 106 I/O |
| XC7S100, XC7A100T | <= 64k LUT6, below target |
| Lattice ECP5-85, CertusPro-NX 100, Avant-E30 | below target or paid Radiant; no stock |
| Cyclone 10 LP 10CL120, EP4CE115 | <= 4 Mb BRAM, 119k LE |
| Altera Agilex 3 | Quartus Pro licence fetched online |
| Efinix Trion T120 | 112k LE, no VREF inputs |

## Selected

Cyclone V E A9 F484 (preferred: 1.0 mm pitch, more logic) and Ti180 G400, both
with authorized stock at end of 2026. Files: `CycloneV_A9/`, `Ti180_G400/`
(re-fetch with `../fetch.sh */sources.txt`).

## I/O budget

FPGA user I/O, counted from the vendor pin files: 5CEBA9/5CEFA9 F484 = 224 IO;
TI180G400 = 274 GPIO (200 HSIO 1.2-1.8 V + 74 HVIO 3.3 V).

Socket logic signals, counted from the CPU datasheets in `../sockets/`:

| Socket | All signals | Without JTAG, debug, parity/ECC |
|---|---|---|
| Socket 3 (IntelDX4, 271329 table 3-2) | 113 | 104 |
| Socket 7 (Pentium MMX, 243185 table 1) | 176 | 149 |
| Socket 370 (Pentium III, 245264 table 28) | 161 + ~6 straps (BSEL, VID) | 139 |

Module side: HyperRAM x8 ~12, translator OE/DIR ~8, clock/UART/ID ~6 -> ~26
(SDR SDRAM x16 instead of HyperRAM: ~53).

- Cyclone V A9: worst case Socket 7 with every pin + HyperRAM = 202 of 224. With
  SDR SDRAM x16, drop JTAG/debug pins (149 + 53 = 202).
- Ti180 G400: everything fits (176 + 53 = 229 of 274), but the bus goes through
  translators: HSIO is 1.8 V max and the datasheet limits 3.3 V HVIO to 6
  outputs/bidirectional per bank.

## Socket power budget

FPGA < 10 W preferred; 10-40 W with external supply only for a large gain.

| Board | Original CPU max | Source |
|---|---|---|
| Socket 3 MB-8433UUD (3.45 V) | IntelDX4-100: 4.3 W | en.wikipedia.org/wiki/Intel_DX4 |
| Socket 3 at 5 V jumper + own regulator | PODP5V63: 6.4 W measured at 62.5 MHz | x86.fr/?p=1046 |
| Socket 7 MB-8500TTD | Pentium MMX 233: 17 W | datasheets.chipdb.org/Intel/x86/Pentium%20MMX/ |
| Socket 370 | Pentium III-S 1.4 GHz: 32 W | techpowerup.com/cpudb/1276/pentium-iii-1400s |

FPGA power is not measured yet: run the vendor estimator once RTL exists.

## Sources

- Digi-Key: `digikey.com/en/products/result?keywords=<part>`
- LCSC: `lcsc.com/product-detail/C1550735.html` (5CEBA9), `C1521767.html` (XC7A200T-2FBG484I)
- Findchips: `findchips.com/search/<part>`
- Quartus editions: `altera.com/products/development-tools/quartus/compare`
- Vivado: `docs.amd.com/r/2025.2-English/ug973-vivado-release-notes-install-license/Supported-Devices`,
  `docs.amd.com/r/en-US/ug973-vivado-release-notes-install-license/Feature-Availability-by-Subscription-Tier`
- Efinity: `efinixinc.com/products-efinity.html`, `efinixinc.com/docs/efinity-ug-v18.3.pdf`
- Libero licensing: `microchip.com/en-us/products/fpgas-and-plds/fpga-and-soc-design-tools/fpga/licensing`
- Gowin: `en.wiki.sipeed.com/hardware/en/tang/common-doc/get_started/install-the-ide.html`, `cdn.gowinsemi.com.cn/SUG501E.pdf`
- ao486 size reference (EP4CE115): CPU 36,517 LE, full SoC 91,256 LE — github.com/alfikpl/ao486
