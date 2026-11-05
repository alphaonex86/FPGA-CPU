# Plan: interposer boards, 3 sockets x 2 FPGAs (4 kept, D9)

Four KiCad 10 projects, one interposer PCB each: a Mill-Max PGA header underneath
plugs into the target board's ZIF socket, and the FPGA, its power, configuration
(and optional RAM) sit on top.

| Variant | Socket / board | FPGA |
|---|---|---|
| `socket3-cyclonev` (pilot) | Socket 3, Biostar MB-8433UUD-A, UMC 8881F/8886BF | 5CEBA9F23C8N / 5CEFA9F23C8N |
| `socket7-cyclonev` | Socket 7, Biostar MB-8500TTD, Intel 430TX | same |
| `socket370-cyclonev` | Socket 370, VIA VT82C694X + VT82C686B board | same |
| `socket3-de25mux` | Socket 3, MB-8433UUD-A, adapter to a DE25-Nano (D11) | none on the adapter (74LVC mux); DE25-Nano Agilex 5 |
| `socket7-de25std` | Socket 7, MB-8500TTD, adapter to a DE25-Standard HSMC + GPIO (D12) | none on the adapter (74LVC, data 2:1); DE25-Standard Agilex 5 |
| ~~`socket370-ti180`~~ | dropped (D10), files deleted 2026-11-01 | - |
| ~~`socket3-ti180`, `socket7-ti180`~~ | dropped (D9) | - |
| slot1 (see `plan/slot1.md`) | Slot 1 (SC242), board per slot1 D8 | per slot1 D9 |

Order: the pilot first (simplest bus, 2.54 mm pins, 3.3 V I/O, ao486 is a 486
core), then the other Cyclone V variants. A variant starts only when the
previous one passes all its checks.
Layout: `hw/<variant>/` per project, `hw/lib/` shared symbols/footprints,
`hw/tools/` scripts, `hw/common/` per-socket tables and notes.

## Inputs (all in this repo, offline)

| What | Where |
|---|---|
| Base: footprint (Mill-Max header pads), 3D, check board on the ZIF | `sockets/kicad/Interposer.pretty/`, `sockets/kicad/3dmodels/` (run `sockets/kicad/tools/gen_base.py`), `sockets/kicad/*-base-check.kicad_pcb` |
| ZIF socket footprints + STEP (keep-out, lever) | `sockets/kicad/Sockets.pretty/`, `sockets/kicad/3dmodels/` |
| Socket pin maps (pin, signal, group) | `sockets/kicad/pinmaps/*.csv` |
| FPGA pin tables (ball, bank, function, config, vref, clock, pair, user_io) | `python3 FPGAlist/tools/pins_to_csv.py` -> `FPGAlist/CycloneV_A9/pins/5ce[bf]a9_f484.csv`, `FPGAlist/Ti180_G400/pins/ti180g400.csv` |
| FPGA footprints (KiCad stock) | `Package_BGA:BGA-484_23.0x23.0mm_Layout22x22_P1.0mm`, `Package_BGA:LFBGA-400_16x16mm_Layout20x20_P0.8mm`; verify pads against `FPGAlist/CycloneV_A9/docs/pkgds_package_information.pdf`, `FPGAlist/Ti180_G400/docs/titanium_packaging_ug.pdf` |
| FPGA power, configuration, reset | Cyclone V: `docs/pcg-01014_pin_connection_guidelines.pdf`, `docs/cv_5v2_device_handbook_vol1.pdf`, `docs/schematic_review_worksheet.doc`, dev kit `boards/*installer.zip`. Ti180: `docs/ti180_datasheet.pdf`, `docs/an033_configuring_titanium.pdf`, `docs/an046_reset_guidelines.pdf`, `boards/ti180*_schematics.pdf` |
| Socket 3 bus | `sockets/socket3/intel_dx4_write_back_enhanced.pdf` Table 7 (PGA pins), Table 8 (pin descriptions); `amd_am5x86_19751C.pdf` (DC p58); `i486_hardware_reference_manual_1990.pdf` (bus cycles); `486_common_socket_implementation.pdf` |
| Socket 7 bus | `sockets/socket7/pentium_mmx_datasheet_243185-004.pdf` Table 1, Table 2 (quick pin reference), Table 8 (functional grouping), §3.1.2 (3.3 V I/O); `pentium_family_developers_manual_241428-005.pdf` |
| Socket 370 bus | `sockets/socket370/pentium3_pga370_245264-008.pdf` Tables 3/4 (signal groups, p23), 9-11 (DC, p34-35), 42 (signal description, p85-92), §2.0 on-die termination (p13), §2.7 unused pins (p22); `p6_family_hardware_developers_manual_244001-001.pdf`; `ap906_agtl_layout_guidelines.pdf` |
| Chipset, board, BIOS dump | `sockets/socket*/` and `sockets/socket*/board/` |
| Budgets | `AGENTS.md` (power per socket), `FPGAlist/README.md` (I/O and power budget) |
| Board design practice | FPGAmotherboard boards (github.com/alphaonex86/FPGAmotherboard): FPGA power trees, BOMs, Ti180 SPI flash, TI regulators already used |

## Decided

- Pins: Mill-Max PGA header soldered under the interposer, series 551 (Socket 3,
  2.54 mm) / 550 (Socket 7 and 370, interstitial); pads, insulator and stack-up
  in `sockets/kicad/tools/gen_base.py`. Ordered via mill-max.com/pga with the pin
  pattern of the base footprint.
- The base footprint goes on F.Cu unmirrored (socket top view = interposer top view).
  Header tails stand 1.6 mm (551) / 2.57 mm (550) above F.Cu over the pin ring
  unless trimmed; the centre window on top is free (F.CrtYd ring).
- Board 1.6 mm unless D5 says otherwise (gen_base.py `PCB`).
- Cyclone V hard DDR controller needs the paid UniPHY IP: plan for a soft RAM
  controller (HyperRAM or SDR SDRAM), so B and F parts are interchangeable.
- KiCad 10, `kicad-cli` at `nice -n 19`, tracks at 90/45 degrees only, vias are free.
- **D2** (decided 2026-10-19, delegated by the operator to the agent) Socket 3:
  level translators on every CPU net — the UMC chipset is +5 V powered and drives
  5 V TTL on the bus under both Vcc jumper settings, and neither FPGA is 5 V
  tolerant (`hw/common/socket3_notes.md` R1); no direct 3.3 V option exists.
  Board Vcc jumpers stay at 3.45 V (the 3.3 V parts' window).
- **D3** (decided 2026-10-20 by the operator) Socket 370 AGTL+: level
  translators on every CPU net; direct VREF-based FPGA landing is rejected
  (neither FPGA's VREF-referenced standards reach 1.0 V,
  `hw/common/socket370_notes.md` R1). With it: Coppermine-class AGTL+
  1.5 V personality only (no Tualatin branch), VCCCORE programmed to at
  most 1.7 V, supported FSB set 66/100/133 MHz (already in AGENTS.md).
- **D1** (decided 2026-10-20 by the operator) Socket 370: external supply on
  the interposer; the socket rails stay untouched (the board's VRM still
  feeds VCCCORE/VTT through the header, VID straps code <=1.7 V).
- **D1** (decided 2026-10-21 by the operator) Socket 7: power from the socket's
  own rails through the header pins (VCC2 core 2.8 V + VCC3 I/O), inside the
  17 W the board VRM was built for; ~0.26 A average per VCC2 pin against the
  1 A Mill-Max 550 rating (`hw/common/socket7_notes.md` R2).
- **D4** (decided 2026-10-20 by the operator) Prototype boards carry no
  module RAM; the RAM-module variant is a later build.
- **D5** (decided 2026-10-20 by the operator) 4 layers on the socket 370
  prototypes (signals F&B, one ground mid, one power mid); no HDI.
- **D1** (decided 2026-10-31 by the operator) Socket 3: external 12 V supply
  on the interposer (barrel jack, FPGAmotherboard power tree); the socket VCC
  pins stay unused (board LDO PQ30RV21: 2 A abs max, `hw/common/socket3_notes.md` R2).
- **D6** (decided 2026-10-31 by the operator) Socket 3 outline: west, south
  and east edges inside the ZIF body (52.43 x 60.30 mm); everything else
  (regulators, 12 V jack, headers) leaves over the north side (cam housing,
  "Socket 3" label), the only free one, past the board edge (~3 mm away). The
  lever band on the east side stays free over the whole interposer length at
  every height (the lever swings with the interposer seated). Top view
  `sockets/socket3/board/mb-8433uud-a_rev3.1_front.jpg`, scaled on the hole
  lattice (22.35 px per 2.54 mm): east body edge 26.2 mm from the pin-field
  centre, lever 26.5..29.6 mm (entirely outside the body; the lever top sits
  higher, so parallax can only have pushed it outward by <~1 mm). The east
  outline stops at the body edge minus 0.5 mm = 25.7 mm, vs the header
  courtyard at 21.84 mm: 3.8 mm margin. (The low side photo `8.02.15 AMb`
  showed the raised lever overlapping the body: perspective, its pivot sits
  behind the front face.) No part of the interposer overhangs a motherboard
  part, so M2 does not apply to Socket 3.
- **D8** (decided 2026-10-31 by the operator) When one board is too small:
  2-3 PCBs stacked on the base PCB (growing in height, not sideways), above
  all for the sockets and RAM >= 1 GB. Both PCB sides carry components
  wherever nothing collides mechanically.
- **D12** (decided 2026-11-01 by the operator) `socket7-de25std`: the
  operator buys a DE25-Standard (116 I/O: 80 HSMC + 36 GPIO); a Socket 7
  adapter without FPGA muxes only D/DP 2:1 (133 MHz per line on the HSMC),
  the rest direct or slow-muxed (`plan/cpu_core.md` E1). Signal
  integrity at 133 MHz per line is the risk to check first. Socket 370
  stays interposer-only (no DE25 can carry AGTL+ 133 MHz without a SERDES).
- **D11** (decided 2026-11-01 by the operator) `socket3-de25mux`: a
  Socket 3 adapter without FPGA that links the DE25-Nano's 72 header I/O
  to the socket through 74LVC registers multiplexed 3:1 or 4:1, the
  next-clock control signals direct (analysis and per-socket verdict in
  `plan/cpu_core.md` E1). Quick bring-up with the stock BIOS; the
  socket3-cyclonev interposer stays the product.
- **D10** (decided 2026-11-01 by the operator) Efinix is prohibited:
  efinixinc.com answers HTTP 403 from Bolivia, Efinity cannot be
  downloaded and no free/open-source flow builds Titanium bitstreams, so
  socket370-ti180 is dropped too; Cyclone V is the only FPGA.
- **D9** (decided 2026-11-01 by the operator) socket3-ti180 and
  socket7-ti180 are dropped. Only 74 of the Ti180's 274 I/O are 3.3 V
  HVIO; HSIO stops at 1.8 V [tids p.84 Table 62]. Socket 7 (166 signals,
  3.3 V TTL) and Socket 3 (113, 5 V) are push-pull buses without
  pull-ups, so a pass-gate or CB3T would hand the chipset 1.8 V (< VIH
  2.0 V); they would need DIR-controlled transceivers: SN74AVC8T245
  1.8 -> 3.3 V <= 3.9 ns, 3.6 V max [avc8t245 p.8 Table 5.8];
  SN74LVC8T245 1.8 -> 5 V <= 7.1 ns but 5 -> 1.8 V <= 23.4 ns
  [lvc8t245 p.10 Table 5.7] (datasheets in `sockets/parts/`).
  socket370-ti180 stayed (until D10): AGTL+ is open-drain with VTT pull-ups (D3).
- **D7** (decided 2026-10-20 by the operator) JTAG header only (no USB
  bridge); TAP and PRDY#/PREQ# land on it; configuration via passive
  serial from the host (socket3-cyclonev: replaced by the AS x4 flash, Flash
  below).
- **D6** provisional 2026-10-20: outline estimated from the socket/ZIF
  footprint keepout until M1/M2 land; M2 numbers re-check the outline.

## Open decisions: ask the operator, never decide alone

- **D1** ~~Power per board~~ (decided above for all three sockets).
- **D4** ~~Module RAM~~ (decided above).
- **D5** ~~Layer count, fab, HDI or not~~ (decided above: 4 layers).
- **D6** Maximum interposer outline and height per board (needs M1, M2) - advanced with an estimated outline, to be re-checked.
- **D7** ~~Debug/config: JTAG connector type, UART, on-board USB-JTAG or not~~ (decided above).
- **Flash** (requirement, operator 2026-11-01; scheme decided by the
  operator 2026-11-01: one large flash, Active Serial x4; size decided by
  the operator 2026-11-01: one SOIC-16 footprint, MT25QL01G (1 Gbit,
  128 MiB) fitted, MT25QL256 (EPCQ256 class) the fallback if AS x4 does
  not boot from the 1 Gbit part on the bench; pin-compatible: the
  MT25QL SOIC-16W pin-out is family-wide and equals the EPCQ128A AS x4 one
  [sockets/parts/micron_mt25ql01gbbb.pdf, cf52014 Figure 3], checked
  2026-11-05)
  every variant carries a flash large enough for the FPGA bitstream and
  also BIOS and/or UEFI images, option ROMs and other firmware to
  experiment with; JTAG kept. One 5CEA9 bitstream is 102,871,776 bits
  (~12.3 MiB), recommended EPCQ256 [cvds p.78 Table 65]; EPCQ devices
  support AS x1 and x4 [cvhb p.7-23], but AS x4 is not supported in the
  EPCQ512 (Intel EPCQ datasheet 683078, online); the current EPCQ-A line
  stops at EPCQ128A [FPGAlist/CycloneV_A9/docs/cf52014_epcq-a_datasheet.pdf
  p.4 Table 1]; EPCQ-L is for
  Arria 10 / Stratix 10 / Cyclone 10 GX only. Quartus 25.1 `quartus_cpf`
  builds a 5CEFA9F23C8 .jic for EPCQ128A, EPCQ256, EPCQ512, EPCQL1024,
  MT25QL256/512/01G, MT25QU01G (refuses Macronix MX25L/MX66 and Spansion
  S25FL): that proves JTAG programming, not AS x4 boot (it also takes
  EPCQL1024).
## FPGAmotherboard compatibility (decided 2026-11-01 by the operator)

socket3-cyclonev on the FPGAmotherboard Socket 3 board (contract from the
other session): its Artix-7 enables VCORE (TPS546B24A, 3.45 V nominal,
0.5-3 ms ramp) only when VOLDET (S4) reads low against its internal pull-up
(VIL 0.8 V); 10k pull-ups to VCORE on BS16#, BS8#, DP3-DP0, UP#, 8.2k on
RESET; CLKMUL (R17) tied to GND; no back-feed allowed into a VCORE at 0 V.
Done in T5/T6 (`gen_socket3_assign.py`, `gen_socket3_t6.py`,
`socket3_pdn.py`), also right on the original board (VCORE always on):
1. S4 tied to VSS (Am5x86 behaviour).
2. CB3T OE# = BUS_OE# from a TLV6700 on S_VCC: switches close at 3.04-3.21 V
   rising, open below >= 2.97 V; its OUTA is VCORE_OK on FPGA ball AA8:
   the RTL treats socket pins as invalid and keeps the CPU parked until it
   is high.
3. UP#/DP3-DP0 pull-ups moved to the FPGA side of the switches.
4. CLKMUL pull-up removed; FPGA weak pull-up in the .qsf instead.
5. RESET (C16) pull-down 4k7 -> 100k: their RESET is high-Z for the whole
   VCORE ramp, held asserted only by the 8.2k to VCORE (3.19 V with our
   100k, 1.26 V = undefined with 4k7). On an original board where C16 is
   undriven (NM2) 100k is weak against input leakage: check at NM2.

## Operator measurements (record the numbers in `sockets/kicad/README.md`)

- **M1** Socket 3 and Socket 7 ZIF: body height, lever bar, lever swing room.
  The Socket 7 list is in FPGAmotherboard `socket7/docs/notes/common-paths-and-owned-hardware.md`
  ("Socket 7 ZIF - the six measurements"). Socket 370 comes from Intel 244410.
  Socket 3 (2026-10-31): not in any document - Intel leaves the height to the
  socket vendor (`sockets/socket3/intel486_microprocessors_and_related_products_241731-002.pdf`
  sec 16.3.1.1), no vendor drawing online (TE 916637-1, the Socket 7 twin,
  is obsolete with no drawing); body 52.43 x 60.30 mm photo-scaled in
  FPGAmotherboard. Height (2026-10-31, operator photos
  `/mnt/data/perso/retro/Socket 3/socket-photo/`, front view scaled on the
  52.43 mm body width, 16.55 px/mm, ~10 deg camera tilt): ZIF top face
  **7.3 +/- 0.4 mm** above the board PCB (the 3D models assume 8.0). Interposer
  PCB bottom = 7.3 + 6.40 = 13.7 mm, top 15.3 mm above the board PCB.
  Original CPU + fan-heatsink top ~26 mm (photo estimate): the case space the
  board already guarantees.
- **M2** Free space around each socket on the three boards: tallest part per side and its distance.
- **M3** The Mill-Max male pin is 3.91 mm long, CPU pins 3.05-3.30 mm: confirm the
  header seats fully in each ZIF (sample header, or socket hole depth).
  Socket 3 (2026-10-31, operator, caliper): contact hole depth 5 mm, CPU pin
  4 mm -> the 3.91 mm header pin seats fully, no lift. Closed for Socket 3.

## Tasks per variant

Each task writes its output from a script in `hw/tools/` (re-runnable, never
hand-edited) and ends with its checks passing.

**T0 Setup.** `./fetch.sh FPGAlist/*/sources.txt sockets/sources.txt isa/sources.txt sockets/local-sources.txt`,
`python3 FPGAlist/tools/pins_to_csv.py`, `python3 sockets/kicad/tools/gen_base.py`.
Check: all exit 0; the three check boards render (`kicad-cli pcb render`).

**T1 Socket signal table** `hw/common/<socket>_signals.csv` (once per socket):
`pin,signal,dir,level,standard,class,required,source`. `dir` seen from the CPU
(I, O, IO, OD); `class` = bus, control, clock, strap, sideband, debug, power, nc;
`source` = file + table/page. Checks: one row per pin-map row, every non-power
pin has dir and level, the signal count is reported and any difference from
`FPGAlist/README.md` (113 DX4 / 176 / 161 + straps) explained (the Socket 3 pin
map is the Am5x86's: 114 signal rows; the DX4 has the same 114).

**T2 Socket notes** `hw/common/<socket>_notes.md` (once per socket), each answer
with file + page:
- R1 DC levels the chipset drives onto the bus (5 V on Socket 3?).
- R2 Power pins: rails, voltage, max current per pin and total (board VRM limit).
- R3 Bus termination: Socket 370 CPUs terminate AGTL+ on the die (245264 p13),
  so the interposer must terminate to VTT; RESET# is terminated on the board (p23).
- R4 Straps and sideband (BF, BSEL, VID, CPUPRES#, THERMDP/N, PICCLK, ...): what the board does with each, proposed handling.
- R5 Bus clock: frequency, level, which FPGA clock-capable input.
- R6 Reset and configuration: FPGA pins float with weak pull-ups while it
  configures; list each CPU output whose pulled-up state is unsafe and its fix
  (pull-down or hold); FPGA configuration time vs the board's RESET timing.

**T3 Power** `hw/<variant>/power.md`: rails (Cyclone V VCC 1.1 V, VCCAUX 2.5 V,
VCCPD, VCCIO, VCCPGM, VCCBAT; Ti180 per datasheet), source per D1, regulators
(prefer parts already on the FPGAmotherboard BOMs), sequencing per vendor, current
and power estimate (mark it "estimate" until the vendor estimator runs on real RTL).
Check: total within D1's budget.

**T4 Libraries** in `hw/lib/`: FPGA symbol generated from the pin CSV (one unit
per bank, plus power and configuration units), base symbol from the T1 table,
other parts from KiCad stock where possible. Checks: symbol pin count equals the
CSV ball count; footprint pads equal symbol pins.

**T5 Pin assignment** `hw/tools/assign_pins.py <variant>` -> `hw/<variant>/pins.csv`
plus the vendor constraints (Quartus `.qsf` / Efinity). Rules: VCCIO of the bank
matches the signal level (after translators); the bus clock on a clock-capable
pin; bus bytes kept in one bank; shortest distance from base pad to FPGA ball
(both positions are known in mm). Checks: no ball used twice; every required
signal assigned; per-bank VCCIO consistent; report of used/free I/O.
2026-10-31 (`hw/tools/assign_common.py`): the ball pool takes only
`user_io=1` balls and the check rejects any other; before, GND and VREFB balls
(supply pins, cvpcg p.19) carrying a bank name were assigned (socket3: 4,
socket7: 6 signals). Socket 7 plan rebalanced (BE4#/BE5#/SCYC -> 5B,
VCC2DET# -> 3B); banks 4A/5B/7A/8A are now full, ~19 I/O free.
socket3-cyclonev (2026-11-05, `gen_socket3_assign.py`): placement first, the
map from it (operator 2026-11-05: pins in a crossing-free order before
routing). Two least total length matchings on the T7 layout: socket pin ->
translator channel (all 16 chips), then A pin -> ball (+6 mm per ring in from
the BGA edge); a least length matching has no crossing lines. CLK tries every
CLKnp input and takes the fewest crossings with same-face A legs; U1 the
rotation of the fewest, then the least length: 270 deg, 0 crossings, 5559 ->
5854 mm. Every bank is 3.3 V, so the old bank plan (byte per bank) is gone;
`layout.csv` hands U1 and the chip spots to T7.
socket7-cyclonev (2026-11-05, `gen_socket7_assign.py`): the same on the
socket 7 T7 layout, one stage (direct nets): socket pin -> ball, least
total length + 6 mm per ring depth; the bank plan (byte per bank) is
gone. U1 at 90 deg (5084 mm); CLK on W16 with 1 crossing (the fewest of
the clock inputs and rotations).

**T6 Schematic and netlist** generated from T3-T5. Check: ERC 0 errors.
Every Cyclone V generator first checks each supply ball against its band
(cvds p.8-9 Table 4, VCCPD per note 4: `cv_supply_errors` in
`gen_t6_schematic.py`) and refuses to write the sheet on a violation.
Status socket3-cyclonev (`hw/tools/gen_socket3_t6.py`, 2026-11-01): 113
signals via 16 SN74CB3T3245 (`hw/lib/Socket_Parts.kicad_sym`, single VCC
3.3 V, OE# = BUS_OE# from the VCORE-present TLV6700, see FPGAmotherboard
compatibility); S4 tied to VSS; 16 resistors: socket-side 4k7 pull-downs
HLDA, BREQ, 100k RESET; FPGA-side 4k7 HOLD down, 10k UP#, DP0-3 up (notes
R4/R6); CLKMUL FPGA weak pull-up only; FPGA nSTATUS/CONF_DONE/nCONFIG
10k up, AS_DCLK 10k down, AS_DATA3 10k up (flash HOLD# in x1), TCK 1k
down, TMS/TDI 10k up, RREF_TL 2k0 1% (PLL used) (cvpcg p.4-7, p.16);
U4 MT25QL01GBBB8ESF on the dedicated AS balls, AS x4, MSEL[4..0] = 10011,
standard POR (cvhb p.7-3 Table 7-2; fast POR would need ramps <= 4 ms,
cvds p.9), configuration scheme + device in the T5 .qsf; J1 FPGA JTAG
2x3, J3 12 V jack (the passive-serial header is gone); every instance
carries its footprint (2026-11-05); nCE to GND,
unused VREFB to GND (cvpcg p.4, p.19). S_VCC joins the 23 socket VCC pins
and the detector divider only (D1). FLUSH# gets no pull-down: it is active
low, a pull-down would flush permanently (notes R4 proposal rejected,
NM3). Power tree + decoupling drawn from `socket3_pdn.py` (148 parts,
`pdn.csv` for T7). Audit 113/113 + VCORE_OK + AS nets, ERC 0.
Status socket7-cyclonev (`hw/tools/gen_socket7_t6.py`, 2026-11-01): 166
signals direct, FPGA ball net = socket pin net (3.3 V TTL bus, no
translators, notes R1); every bank, VCCPD and VCCPGM on VCCIO33, the
board's S_VCC3 (3.4 V [spec p.5], inside 3.465 V) behind a load switch
enabled by the core PGOOD (operator 2026-11-01, power.md Sequencing); 14 resistors: 4k7 socket-side
pull-downs BREQ, SCYC, PM0/BP0, PM1/BP1, BP2, BP3 (outputs whose
configuration pull-up is unsafe, notes R6) and A27 (refresh-rate strap
the chipset samples at RESET, notes R4); FPGA configuration pulls as
socket 3. The 10 socket pins the interposer leaves open (PICCLK, PICD0/1,
FRCMC#, PHIT#/PHITM#, PBREQ#/PBGNT#, R/S#, D/P#: NC on UP boards, notes
R4) and the NC pins carry a no-connect flag (`t6.NOCONNECT`). No FLUSH#
pull-up: the board has its 8.2 k [fmb p.2-2]. 2026-11-05: AS x4 flash U4
as socket 3 (MSEL 10011, nCONFIG/AS_DATA3 up, AS_DCLK down, PS header
gone, AS x4 lines in the .qsf), footprints on every instance, power tree
+ decoupling from `socket7_pdn.py` (96 parts, `pdn.csv`): TLV62585 core
buck on VCC2, TLV75725 aux LDO and TPS22918 VCCIO33 switch on VCC3, both
enabled by the buck PG pulled up to VCC_1V1 (power.md). Audit 166/166 +
AS nets, VCC2 25 / VCC3 28 / VSS 53 pins, ERC 0.
Status socket370 (both, `hw/tools/gen_t6_schematic.py`, 2026-10-20): label-wired
sheet, no wires; every required signal's net holds its FPGA ball and its
translator A-pin, its `S_<signal>` net holds the CPU socket pin and the paired
B-pin (BCLK/PICCLK direct). Netlist audit 167/167 required signals; ERC
`--severity-error` = 0 violations per variant.
- Translator chips (8 channel, `hw/lib/Interposer_Logic.kicad_sym`): Cyclone V
  23, Ti180 24 (fills by (VCCIO, socket rail) groups; T5's `translator` column
  was an estimate and is superseded by these fills).
- `PWR_FLAG` on every net hosting a power input: translator rails + `GND`,
  the 12 V jack, and the socket supply nets the CPU pins draw from
  (S_VCCCORE, S_VTT, S_VREF, S_PLL, S_VCC1, S_VCC2.5, S_VCCCMOS) plus the
  FPGA rail nets (VCC_1V1/0V95, VCCAUX/VCCA, VCCPGM18, VCCIO33/25, VCCPD33,
  VCC_AUX25). CPU GND pins, FPGA ground balls and header grounds share one
  `GND` net (the interposer pour bonds them).
- Cyclone V VCCPD (fixed 2026-10-31, operator: move the 2.5 V signals):
  the F484 has no VCCPD3B ball; VCCPD3B4A (W11, W12, W14, W17) serves 3B
  and 4A, and note 4 (cvds p.8 Table 4) forbids 2.5 V 3B next to 3.3 V 4A.
  The 9 signals at 2.5 V (BCLK, PICCLK, TAP, PREQ#/PRDY#) now sit in 5B
  (own VCCPD5B -> VCC_AUX25; BCLK on N16 = CLK6p); 3B runs 3.3 V with
  A15#/A16#, A30#-A35#, BSEL, VID, SLEWCTRL, RTTCTRL, CPUPRES#. The old
  sheet also had VCC_AUX on VCCIO33 (3.3 V > 3.25 V abs max, cvds p.5
  Table 2) and 6 signals on VREFB/GND balls; both are gone (T5 user-I/O
  filter in `assign_pins.py`). ~18 I/O free.
- socket370-ti180: deleted 2026-11-01 (operator, D10): `hw/socket370-ti180/`
  and its branches in `assign_pins.py`, `gen_t6_schematic.py`,
  `gen_power.py`; last version in git at 3dc042f. Shared fix kept: T6
  checks that every used bank's VCCIO balls sit on the rail of its pins.csv
  VCCIO (`bank_vccio_errors`). Quartus .qsf: the BCLK standard is now
  "2.5 V" (no "2.5-V LVTTL" exists, cvhb p.5-7 Table 5-7).
- Headers: J1 CPU TAP 2x6 (TCK/TMS/TDI/TDO/TRST#/PRDY#/PREQ#), J2 FPGA JTAG
  2x3, J3 passive-serial config 2x5 (CV: nCONFIG/nSTATUS/CONF_DONE/DCLK/DATA0;
  Ti: CRESET_N/CDONE/CCK/CDI/CSO), J4 12 V barrel jack, J5 board-rail feed
  1x5 (S_VCCCORE, VTT15, VCC3, VCC25, GND). Ti `VQPS` ball floats (fuse
  supply, power.md).

**T7 Placement**: FPGA in the free centre on top (or beside it), header under it,
regulators and flash around; outline inside D6; nothing over the ZIF lever bar or
its swing; heights inside D6. Check: courtyard DRC clean, 3D view with the ZIF model.
Status socket3-cyclonev (`hw/tools/gen_socket3_t7.py`, 2026-11-05): U1 north
of the pin ring (operator 2026-11-05: with U1 in the centre the translators go
north and every net crosses the north ring twice, ~226 tracks for ~136 gaps on
2 signal layers); 16 SN74CB3T3245PW (JLC C15298, the DGS VSSOP is smaller but
not stocked) in four columns of 4 beside U1, F.Cu and B.Cu at the same spots,
A pins facing U1; the strips between the columns and the board edge and beside
the ring stay free for the socket legs; U4 flash in the window at its AS
balls; jack, regulators and JTAG in the north band. Board 51.4 x 101.8 mm
(D6: 0.5 mm inside the ZIF body west/south/east), 4 layers, DRC 0 errors,
1390/1390 netlist pins on pads. 3D view (kicad-cli render): J3 plug opening faces the north edge (front 1.1 mm inside it), FPGA, translator columns and the flash in the window as placed, nothing on the lever band.
Status socket7-cyclonev (`hw/tools/gen_socket7_t7.py`, 2026-11-05): outline
0.5 mm inside the ZIF body on all four sides, 51.6 x 62.3 mm (the body is
ASSUMED from the PGA370 envelope: re-check with M1); U1 in the centre of
the PGA296 base (F.Cu window 31.3 mm, B.Cu 27.0 mm), the F.Cu window kept
free for the socket legs, U1 capacitors under it on B.Cu; power tree,
flash, pulls and JTAG in the 12 mm band between the ring and the
cam-housing edge. Open: J1's THT tails reach ~3 mm under the board over
the cam housing, 3.99 mm above the socket top (M1). DRC 0 errors.

**T8 Routing**: layers per D5; Socket 370 per AP-906 (AGTL+, 133 MHz), Socket 7 at
66 MHz with matched lengths per byte lane. Check: DRC 0 errors, 0 unconnected.

**T9 Verification**: audit script: every base pad's net is the T1 signal and
reaches the T5 ball (or its translator); every power pad on its rail. 3D check
against the ZIF and M2. BOM with authorized stock (Digi-Key / LCSC). Fab outputs
with `kicad-cli` (gerbers, drill, positions, BOM).

**T10 Report** to the operator: what was built, check results, open items, cost.

## Status

| Variant | T0 | T1 | T2 | T3 | T4 | T5 | T6 | T7 | T8 | T9 | T10 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| socket3-cyclonev | done | done | done | done | done | done | done | done | | | |
| socket7-cyclonev | done | done | done | done | done | done | done | done | | | |
| socket370-cyclonev | done | done | done | done | done | done | done | | | | |
| ~~socket370-ti180~~ | dropped (D10) after T6 | | | | | | | | | | |
