# Plan: Slot 1 (SC242) FPGA CPU — cartridge interposer with on-board RAM

Created 2026-10-20 from the operator's request. Complements `interposers.md`
(decisions there run D1-D7; the ones below continue at D8). Wait for decisions
D8-D15 before the hardware tasks.

## Operator requirements (2026-10-20)

- Slot 1 CPU: fast memory next to the CPU, **>= 4 GiB on-board**, fast enough to
  run Windows 7 (operator wording: "core i5 gen1+" class; see CPU core strategy).
- On-board RAM and voltage switchers/cartridge regulators on the interposer.
- Support the whole common motherboard range: all common FSB (66/100/133 MHz).
- Motherboard RAM not used (minimal use only, e.g. DMA path).
- FPGA choice researched on the internet; **good authorized availability is
  required** (operator, 2026-10-20).
- The operator is asked (asked = made to face) the questions that the design
  leaves open before the hardware starts.

## Why Slot 1 is different from the three sockets

- SC242 = 242 contacts, 2 x 121 (rows A/B), EISA-style **card-edge** slot; the
  interposer is a cartridge PCB with edge fingers, not a Mill-Max header
  interposer. New base generator; the ZIF/Mill-Max flow does not apply.
- P6 bus family (same protocol class as Socket 370), AGTL+ signalling, 5 VID
  pins program the board's VRM (1.3-3.50 V). Original CPUs are 233 MHz Celeron
  (66 MHz) up to P III 1 GHz SECC2 (26-33 W class, like Socket 370's budget).
- The original cartridge is SECC (SECC ASIC + half-speed L2) or SECC2; the
  interposer replaces the **whole cartridge**: no L2 on cartridge, all caches
  on die. BIOS presence detection, BSEL/multiplier straps and reset behaviour
  live on the connector and must be emulated per board.

## Facts collected today (with sources)

### FPGA candidates, only ones with good authorized stock

| Part | Logic | I/O (user) | Toolchain | Authorized stock | DDR/LPDDR hard IP | Verdict |
|---|---|---|---|---|---|---|
| Cyclone V 5CEBA9/5CEFA9 F484 | 301k LE | 224 | Quartus Lite free | 60+40 @ ~$325-354 (survey 2026-10-18) | hard DDR3 PHY+MMC exists, but UniPHY IP **paid** in current Quartus | primary candidate |
| Ti180G400C3 (survey pick) | 176k LE | 274 (200 HSIO + 74 HVIO) | Efinity free | 760 @ $84 | **no hard DDR/LPDDR4 in G400** (ti180_datasheet.pdf table 2: LPDDR4 row G400 = "-") | fabric fastest, RAM weakest |
| Ti180G529 (C3L/I3L/I4) | 176k LE | 210 HSIO + 48 HVIO | Efinity free | Digi-Key lists it, **"not kept in stock"** (order with lead time) | hard LPDDR4/4x **x32, up to 3.0 Gbps** (~12 GB/s) | only Ti180 with both big I/O and hard LPDDR4, but weak availability |
| Ti180J484D1 (SIP) | 176k LE | 190 HSIO | Efinity free | not surveyed | in-package LPDDR4x 2 Gbit (256 MB, x16) | too small for >= 4 GB |
| Artix-7 XC7A200T SBG484 | 215k LC | 285 | Vivado ML Std free | 0, 52 wk | DDR3 x64 SODIMM up to 1066 MT/s (AC701 reference) | out: no authorized stock |
| Ti375 C529 | 370k LE | ~227 | Efinity free | 45 wk, $184 | hard LPDDR4 x32 + 4x1 GHz RISC-V | out: no stock |

Conclusion under the availability rule: the working set today is **Cyclone V A9**
(most logic; DDR3 needs the D11 decision) and/or **Ti180G400C3** (fastest
fabric; RAM via a soft controller, slow). Ti180G529 is the only Ti180 that pairs
high I/O with the hard LPDDR4 controller; keep it as a later board if/when
stocked.

### On-board RAM dies

- LPDDR4x **x32** dies are cheap and available: Micron MT53E1G32D2 (32 Gbit =
  **4 GiB in one 200-ball 10x14.5 mm package**, 2133 MT/s) ships from authorized
  stock today ("Buy now, ships today"). 8 GiB = 2 packages.
- DDR3L dies are commodity (LCSC): 4 GiB x32 = 2 x 16 Gbit x16 dies.
- Both die types need level-compatible banks and routing rules on the cartridge
  PCB; pin assignment task (S5) reserves their banks before bus signals land.

### SC242 / Slot 1 pinout and straps

- 242 contacts, 2 x 121 A/B [cpu-world Slot 1 page; ps-2.kev009 eprm f708/709].
- FSB: 66, 100 MHz; 133 MHz only on third-party chipsets or with overclocked
  Intel chipsets [wikipedia Slot 1; VIA Apollo Pro 133 boards are the common
  133 MHz case]. BSEL straps and VID sit on the connector (verify exact pins in
  the fetched datasheets, S1/S2).
-англ AGTL+ layout guide AP-906 already in repo; AP-585 (P II AGTL+) to fetch.

## Memory architecture draft (refine in a later task, needs the chipset of D8)

- On-board RAM (>= 4 GB) is the memory the CPU actually touches for all
  cacheable misses; all caches on die + this RAM as "L3/main tile".
- Motherboard DIMMs stay minimal (e.g. one small module) so the stock chipset
  can be initialised and has DMA targets. Coherence: chipset DMA writes are
  seen on the FSB as snoops; dirty lines inside our RAM get written out and
  re-fetched; the exact protocol is written up with the chipset datasheet.
- Open (D14): the stock BIOS builds the OS memory map from the DIMMs it finds.
  With only a small DIMM the OS may see little RAM; exposing >= 4 GB probably
  needs a patched BIOS ROM (swap the flash chip with a modded stock image) —
  ask the operator.

## CPU core strategy draft

- No vendor shortcut available (Ti375's hard RISC-V is out on availability
  grounds) -> our own RTL tree, staged like AGENTS.md asks:
  1. i686 + MMX/SSE/SSE2 32-bit -> runs Windows 7 x86 (also XP/2000/9x).
  2. long mode + POPCNT/SSE3-SSE4.2 -> Windows 7 x64 + modern software.
  3. Performance stretch: wider issue, bigger L1/L2, later OoO; every step
     benchmarked.
- Expectation to be honest about: a Cyclone V/Ti180 soft core is far below real
  first-gen Core i5 silicon; the goal is "best possible inside these FPGAs",
  Windows 7 usable. Real numbers come once RTL exists (vendor power/timing
  runs).

## Mechanical

- Cartridge PCB with edge fingers in the SC242 slot; original cartridge outline,
  keying notches and retention-clip tabs define the keep-outs and height band.
- Regulators and RAM sit on the cartridge (front/back), everything inside the
  original SECC/SECC2 silhouette as much as possible. Exact PCB thickness and
  edge-pad geometry come from the slot connector drawing (fetch S0, measure M4
  on the real board).

## Fetch plan (sources)

Append to `sockets/sources.txt` (done today, files in `sockets/slot1/`):

Fetched and verified (title pages checked):

- `pentium2_350-450_sc242_24365703.pdf` — SC242 pinout, bus, VID; P II
  350/400/450 (SECC+SECC2)
- `pentium3_secc2_24445201.pdf` — P III 450/500 SECC/SECC2 (100 MHz bus,
  560-570 mA-class currents at 1.6-1.7 V comes later from the right revision)
- `board/intel_440bx_host_bridge_29063301.pdf` — 82443BX host bridge (440BX)
- `board/intel_82801AA_ich0_29065503.pdf` — ICH/ICH0 (i810/i820 era)
- `board/intel_82801BA_ich2_29068702.pdf` — ICH2
- `board/intel_82810_gmch_29065602.pdf` — 82810/82810E GMCH

Already on disk elsewhere (cite, do not duplicate):

- `p6_family_hardware_developers_manual_244001-001.pdf` — P6 bus protocol:
  `sockets/socket370/`
- `ap906_agtl_layout_guidelines.pdf` — AGTL+ layout: `sockets/socket370/`
- `intel_82371ab_piix4.pdf` — PIIX4E, pairs with 440BX: `sockets/socket7/`

Not found online yet (to locate in the operator's local archive or elsewhere):

- AP-585 (P II AGTL+ guidelines)
- 82820 MCH datasheet (i820)
- VIA Apollo Pro 133/133A north VT82C693A/694X and south VT82C596A/B
- A later Pentium III SECC2 order covering Katmai/Coppermine up to 1.13 GHz
- Board manuals + BIOS dumps of the three D8 boards (like the other sockets,
  these come from the operator's archive → `sockets/local-sources.txt`).

## Tasks

Mirror the T-series of `interposers.md`, S prefix. Each task ends with its
checks passing and one row updated in the Status table below.

**S0 Inputs.** Fetch the slot1 sources; `pins_to_csv.py` for the chosen FPGA
package (Cyclone V F484 exists; add Ti180 G529/G400 per D9). Checks: fetch exit
0; pin CSVs exist.
**S1 SC242 signal table** `hw/common/slot1_signals.csv` (pin,signal,dir,level,
standard,class,required,source) from the SECC2/Deschutes datasheets. Checks:
one row per connector contact group; every non-power contact has dir+level;
signal count reported vs. the 370 table (common P6 signal set) explained.
**S2 Slot 1 notes** `hw/common/slot1_notes.md` (AGTL+ termination: who
terminates what on the cartridge; VTT vs VID rails; BSEL/VID/PICCLK/presence
handling; FSB clock pins and levels; FPGA configuration timing vs. board
reset; SECC/SECC2 presence pins and BIOS-visible identity).
**S3 Power** `hw/<variant>/power.md`: cartridge regulators (FPGA rails + 1.5 V
VTT termination + RAM 1.35/0.6 V), VID straps to the socket VRM (or cut, per
D13), current/power estimate vs. the socket's CPU budget.
**S4 Libraries**: FPGA symbol from the pin CSV, RAM die symbol, VRM parts,
connector footprint (card-edge, from the connector drawing).
- Status (done): fetched `sockets/slot1/sc242_connector_designguidelines_243397-02.pdf`
  (242 contacts, 1.0 mm pitch edge connector spec; Fig 1 pad station grid)
  and `sockets/slot1/sec_cartridge_packaging_databook_ch16.pdf` (Databook
  ch 16, SC242 contact pairs 73+48, connectors 16.4.1) via
  `sockets/sources.txt`. Generated by `hw/tools/gen_slot1_lib.py` (23 checks
  PASS, quote-aware s-expression validation): `hw/lib/Slot1.pretty/SC242_CardEdge_242.kicad_mod`
  (2x121 card-edge plug footprint, 1.0 mm pitch, key notch between stations
  73/74) and `hw/lib/Slot1_Parts.kicad_sym` (DDR3L x16 die, Buck_sync,
  DDR_VTT_tracker). The FPGA symbol reuses the existing Cyclone V pin-CSV
  symbols in `hw/lib/`. Exact pad/key geometry left to NM11/D16.
**S5 Pin assignment** (done): generated by `hw/tools/gen_slot1_assign.py`
  (checks PASS). Source of truth for the FPGA balls = the official pin
  table's F484 block `FPGAlist/CycloneV_A9/pins/5cefa9.txt` (the converted
  CSV drops the DQS-for-X8/X16 and HMC DDR3 columns the DDR3 reservation
  needs). Outputs in `hw/slot1-cyclonev/`: `pins.csv` (145 slot 1 nets:
  133 AGTL+ translator channels + 11 CMOS + BCLK direct on M9/CLK0p),
  `ddr3.csv` (76 balls after the NM24 2-rank update, banks 7A/8A at 1.35 V,
  4 x8 DQ/DQS groups DQ4T/DQ3T/DQ2T/DQ1T, per-designator cross-check against
  the F484 HMC column), `parked.csv` (26 contacts tied on the cartridge),
  `assignment_quartus.qsf`
  (bank VCCIO 7A/8A = 1.35 V). Bank fill: 3A/4A/5A/5B exhausted, 3B 1 free
  (held CLK0n), 18 of 20 free 1.35 V balls used for AGTL+ overflow, 3 spares
  total. Translator chips: 20 with supply-pair boundaries (D21, fixed in
  S6). Decisions/NMs: D18-D21, NM21-NM24.
**S6 Schematic/ERC** (done): label-wired sheet from `hw/tools/
  gen_slot1_s6.py` (reuses the T6 emission machinery). Outputs in
  `hw/slot1-cyclonev/`: `slot1-cyclonev.kicad_sch` (A0, no wires, labels at
  pin world points), `slot1-cyclonev.net` (kicad-cli export), audit +
  `--severity-error` ERC = 0 violations, `slot1-cyclonev.kicad_pro` +
  `sym-lib-table`. Sheet content: FPGA bank units, the SC242 CPU symbol
  (new `sockets/kicad/CPU_SC242.kicad_sym` from `hw/tools/
  gen_slot1_cpu_sym.py`, 242 contacts = pin numbers, 4 units by signal
  family), 20 translator chips matching pins.csv T<dd>c<d>, 4 x DDR3L
  x16 die instances (NM24 2-rank: rank0 = die0/die1, rank1 = die2/die3")
  + DDR_VTT tracker (VDDR3 in, VTTREF0675 out feeding the dies' VREFCA/
  VREFDQ and the FPGA C14/B8 VREF balls), headers J1 F-JTAG, J2 passive-
  serial config, J3 12 V barrel, J4 board rail feed (VCCCORE, VTT15, GND),
  PWR_FLAG per power-input net. The regeneration found and fixed the S5
  translator fill (D21); die symbol regenerated with row A[15:0] +
  VREFCA (NM24, MT41K512M16 class).
  2026-10-31 rerun: VCC_AUX (6 balls) moved from VCCIO33 (3.3 V, above
  the 3.25 V abs max, cvds p.5 Table 2) to VCC_AUX25, and VCCPD7A8A from
  the misleading `VCCPD135` net to VCC_AUX25 (2.5 V for 1.35 V banks, cvds
  p.8 note 4); the generator now checks every supply ball's band before
  writing. Netlist diff = exactly those 11 balls. **S7-S9 outputs predate
  this netlist** (the board still has VCC_AUX on VCCIO33): rerun with the
  D23 chain.
  D23 rerun (2026-10-31): the sheet also draws the power tree and all
  decoupling from `hw/tools/slot1_pdn.py` (250 parts, also written to
  `pdn.csv` for S7): F1 2 A fuse after J3 (V12_IN -> V12); PS1 TPS54620
  12 -> 5 V; PS2 TPS54620 5 -> 1.0992 V core; PS3/PS4/PS5/PS6 TPS62130 for
  2.52 V aux, 3.328 V I/O, 1.792 V VCCPGM, 1.3584 V VDDR3; FB1 Murata
  BLM18AG601SN1D ferrite (600 R at 100 MHz, 500 mA, 0.38 R max) to
  VCCA_FPLL25. Sequence per the Cyclone V recommendation [cvhb p.10-4
  Fig 10-3: group 1 VCC to >= 80 % first, then group 2 with VCCIO
  together with VCCPD]: PG_5V -> EN of PS2 (core), PG_1V1 (94 % Vref,
  tps54620 p.6) -> EN of PS3..PS6 at once (an earlier draft brought the
  core up near the end: fixed 2026-10-31). Inductors checked in code
  against Coilcraft ratings (Ipk <= Isat 20 %, Iout <= Irms): PS1
  MSS1048-682 5.00/4.52 A and PS2 MSS1048-152 7.80/7.41 A [Doc 462-1],
  PS3..PS6 XFL4020-222 3.5/6.0 A [Doc 745-1]; TI's stricter rule (Isat
  above the high-side current limit 8-11 A, tps54620 p.6) is not met by
  PS2 and is accepted for now (output short = fuse/hiccup case). All
  values come from the TI equations in code (Eq 13/18/22/29/31/34-36 of
  the TPS54620, Eq 6 + Table 9-1 of the TPS62130), divider outputs
  checked against each rail's cvds band. Decoupling: U1 per devkit sheet
  29 (77 small + 6 bulk), translators 0.1 uF per VCCA/VCCB [cb3t p.11],
  15 per DDR3 die per devkit sheet 12. Rails merged to one net each
  (VCMOS -> VCC_AUX25, VCCPD33 -> VCCIO33, VCCIO135 -> VDDR3); new
  symbols TPS54620/TPS62130 in `Slot1_Parts.kicad_sym` (Buck_sync
  placeholder removed). Audit OK, ERC 0.
**S7 Placement** (done; D23 rerun 2026-10-31: outline 127.0 x 57.8 mm per
  D16; the power stages column-packed in the new strip y 47.0..57.8,
  generated TPS54620 RHL0014A land pattern [tps54620 p.45], U1's small
  capacitors on B.Cu over 31 supply/GND via-in-pad pairs (D25, Kuhn
  matching in slot1_pdn.py; the other 46 + 6 bulk below U1 on F.Cu), translator
  capacitors on B.Cu on their stitch vias, die capacitors in the free F.Cu
  right of and below the dies, 281 footprints, DRC 0 errors). Second pass
  2026-10-31: dies on the real 0.8 mm Micron land (see S8a) at
  (94/103.75, 15.5/32.5), courtyard 9.5 x 14.5 mm; J3 = real CUI
  PJ-063AH barrel jack (stock KiCad footprint, mouth 0.5 mm past the free
  edge y 57.8, opposite the card fingers)
  at (22.1, 45.8), J1/J2/J4 moved to x 32/42.5/53; stage 0402 parts and
  F1 on B.Cu under their stage (the F strip was 1.8 mm short); every
  pad centre of one side keeps 0.45 mm (via radius + clearance) from the
  other side's pads, because S8b drills a through via there (the first
  try put B.Cu GND vias on L2/L4 SW pads: 23 shorts). Generated by
  `hw/tools/gen_slot1_s7.py`. Output
  `hw/slot1-cyclonev/slot1-cyclonev.kicad_pcb` (DG Fig 1 outline 127.0 x 47.0
  mm, 1.57 mm substrate; A1 station at 4.0 mm; key notch 2.0 x 2.49 mm
  centred 76.5 mm from the left edge; 2.49 mm lead-in chamfers; DG line 183
  "242 contact, 1.0mm pitch"): 31 footprints (U1 FPGA centre, U2 card edge
  with A/B rows at local +1.75 and the 73/74 head+neck step pads per DG
  Detail A, U3..U6 dies as 6x16 generic 1.0 mm land grids [placeholder ball
  map, S8 puts in the MT41K512M16HA Fig 7 map], U7 tracker, TR01..TR20 in
  four columns, J1..J4 headers), 4 keep-out zones (connector cavity band
  y 3.5..7.0 no footprints, retention bands x<16/x>111 y>7.0 no footprints,
  notch mouth no tracks/vias), all pads unnetted (nets come at S8). Checks:
  242 card pads, every S6 ref placed, notch stations 72/73 = 73/74 heads,
  and `kicad-cli pcb drc --severity-error` = 0 violations. Mechanics that
  make the CLI DRC gate pass [KiCad 10.0.3 tests]: the rules live in a
  COMPLETE `slot1-cyclonev.kicad_pro` next to the board (the CLI ignores
  partial pros; 0.0 edge clearance means "unset" -> 0.5 mm default; rule
  min_copper_edge_clearance = 0.001 mm), a project `fp-lib-table` registers
  the five footprint libs and `gen_slot1_s7.py` emits matching .kicad_mod
  files for the placeholder libs (DDR3/TPS/Conn, from the same inline
  bodies), and U2 sits 0.055 mm off the insertion edge because the CLI
  measures edge clearance to the Edge.Cuts stroke edge (0.1 mm stroke ->
  +0.05 mm onto the board), not the centreline.
**S8 Routing** (in progress): **step A (done)** by `hw/tools/gen_slot1_s8.py`:
  the S7 board now carries the real MT41K512M16HA ball map
  [Micron 8Gb DDR3L datasheet Fig 7 p 18, decoded to
  `hw/common/mt41k512m16ha_balls.csv`: 16 rows x 6 columns of the 9-column
  grid, 0.8 mm pitch, 6.4 x 12.0 mm ball centres, 0.42 mm SMD land, Fig 9
  p 24; the first decode used 1.0 mm and a vertically mirrored map, fixed
  2026-10-31] on U3..U6 [NM25d closed], and every pad carries the
  net of its S6 netlist node: 529 nets / 1360 nodes / 1520 board pads,
  audited pad-by-pad against the netlist, including the die electrical
  functions through the ball->pin map (U7 pads renamed VIN/VTT/VTTSNS/
  VDDQ_REF/GND in S7 to match the symbol). kicad-cli DRC keeps 0 errors
  (6 ratsnest warnings stay on purpose until the pours/tracks land). Next:
  layer decision D22, then power pours (S8b) and track routing with AGTL+
  clearances + matched DDR3 byte lanes (S8c).
**S8 Routing** (in progress, phase 1 done, phase 2 = the 8-layer pass):
  - **step B (done, 8 layers)** by `hw/tools/gen_slot1_s8b.py`: F.Cu &
    B.Cu signals, In1.Cu + In4.Cu + In6.Cu GND planes, In2.Cu 14 strip
    pour zones, In3.Cu + In5.Cu signal mids, reserved DDR3 byte-lane
    corridors and via matrices (471 vias), kicad-cli DRC errors 0
    (warnings: the shrunk-via isolated_copper + ratsnest rows that S8c
    resolves).
  - **step C (done, phase 1)** by `hw/tools/gen_slot1_s8c.py` (NM27-NM33):
    same-layer planarity router over the 0.05 mm grid; pass 1 main M..F
    spine trails (short-first), pass 2 branch jobs off reserved corridors.
    Gate reached 2026-10-22 (run15): 74/184 die jobs routed, DRC 0.
  - **step D (done, D22 amendments: 6 then 8 copper layers)**: stack
    grows F/In1/In2/In3/In4/In5/In6/B (In1+In4+In6 = GND planes, In2 =
    rail strips, In3+In5 = signal mids); `gen_slot1_s8b.py` emits one
    GND plane zone per ground mid, the s8c router is generalized to N
    routing layers (6-layer: 0 = B, 1 = In3, 2 = F; 8-layer: 0 = B,
    1 = In3, 2 = In5, 3 = F - LAY_NAME/LAY_KICAD tables, pads still
    F-only, own via rings + foreign via disks on every routing layer,
    free flips to any layer at one drill cost, merge_own/realcopper/
    emit/vkill per layer). Gates: 6 layers (runs 25+26, deterministic):
    127/184 routed, DRC 0, 419 unconnected; 8 layers standing best
    (runs 27+28 + NM41 rip-up pass 4, runs 39+40, deterministic):
    **163/184 routed, DRC 0, 383 unconnected** (CLI
    stdout == pcbnew consistent), vs the 4-layer best 89/184, run22 -
    and 4522 tracks / 1091 vias (the pass-4 rip-up rewires 75
    job-paths to free formerly-impossible corridors). Remaining 21
    fails: victim re-routes starved by congestion + 2 reachable crits
    (NM41 verdict); all remaining router levers measured and
    rejected (NM42 fixpoint, NM43 order+reservation, NM44 demand
    pricing) - movement needs a structural input - phase-2
    architecture.
**S9 Verification audit + BOM** (done): `hw/tools/gen_slot1_s9.py` (NM34)
  refreshes `slot1-cyclonev.erc.json` / `slot1-cyclonev.drc.json` and
  writes `slot1-cyclonev.bom.csv`. Gates: ERC 0 errors (248 warnings: the
  accepted S6 NC/CFG stubs + off-grid cosmetic rows), DRC 0 errors with
  the CLI "Found N unconnected items" stdout line cross-checked against
  pcbnew (the JSON report never lists unconnected rows, NM27) and gate-
  failing on inconsistency, BOM ref set == PCB ref set (31 == 31).
  D23 rerun (2026-10-31, whole chain S6 -> S9 on the 57.8 mm board with
  the power tree): ERC 0 errors, DRC 0 errors, BOM 281 == PCB 281, S8c
  **160/184** DDR3 die jobs routed (163 before the D23 parts: the die
  capacitors right of and below the dies and the U1 B.Cu capacitors cost
  3 jobs), 499 unconnected = 286 slot/translator signal nets (never
  routed yet, as before) + 120 rail/GND pads (QFN leads < 0.5 mm get no
  via, plus pads the In2 raster leaves on a foreign strip) + 53 regulator
  internal nets (SW/FB/COMP/SS/BOOT/PG, unrouted by design: D23 = place
  before routing) + 40 DDR3. The S9 gate now compares the CLI stdout with
  the JSON unconnected_items list (KiCad 10 lists them, NM27 is outdated);
  pcbnew counts 14 more, all on the regulator stages (equal once PS/L/R/
  F/FB are removed), cause inside KiCad not found. Fixed on the way: S6
  rewrites a minimal .kicad_pro, so S7 now always writes the Default net
  class (0.15 clearance) - without it KiCad applied 0.2 mm and S8c's
  0.15 mm tracks gave 501 DRC errors; S9 printed "PASS audit" even with a
  failing gate.
  Second D23 pass (2026-10-31, chain S7 -> S9 twice, same result both
  times): ERC 0, DRC 0 errors (323 warnings: 199 via_dangling = rail
  pad vias over a foreign In2 strip, 87 lib_footprint_mismatch, 37
  isolated_copper; the 199 B.Fab text warnings fixed by mirroring B-side
  texts in S7), BOM 278 == PCB 278, S8c **133/184** die jobs (pass 1
  routes 141; the rip-up pass leaves 133 - the router keeps its last
  pass, not its best), 499 unconnected = 259 slot/translator signals +
  113 rail/GND pads + 81 DDR3 + 46 regulator internal. The drop from
  160 is the real die land: the 160 was routed on the wrong 1.0 mm,
  mirrored ball map; S8c's 0.35/0.20 die vias (D24) were already sized
  for 0.8 mm (one 0.15 track per 0.45 gap). Chain guards: S8a refuses an
  already netted board, S8b a board without a fresh S8a net table
  (each needs the fresh output of the step before; S8a also accepts the
  jack's unnamed NPTH peg).
  Board facts at audit time: 8 copper layers, 530 nets, 4160 tracks,
  1064 vias, 287/291 zones filled, 1500 bound pads (276 DDR3, 126 NC,
  1098 socket/AGTL+/power), U1 484 + dies 368 bound pads.
**S5 Pin assignment**: reserve LPDDR4/DDR3 banks first, then map the SC242
contacts -> FPGA balls (AGTL+ banks via translators; 3.3 V sideband direct).
**S6-S9** schematic/ERC, placement (cartridge outline + clip keep-outs),
routing (AGTL+ rules, memory byte lanes matched), verification audit + BOM.
**S10 Report** to the operator.
**S11+ RTL tasks** (core) follow in their own plan file once the board exists.

## Status

| Task | S0 | S1 | S2 | S3 | S4 | S5 | S6 | S7 | S8 | S9 | S10 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| slot1 (slot1-cyclonev per D9) | done | done | done | done | done | done | done | done | in prog (133/184 on the real 0.8 mm die land, DRC 0, 499 unconn) | done | done |

Not on the board yet (2026-10-31, after D23): S8c routes only the DDR3 die
nets (133/184); the SC242 -> translator -> FPGA nets are unrouted (259
unconnected items); the power tree and decoupling are placed (278 refs)
but their internal nets and 113 rail/GND pads are not routed; U7 is
still the generic VTT tracker placeholder.

## S10 Report (2026-10-22, to the operator)

**What was built** - the slot 1 (SC242) FPGA CPU cartridge
`hw/slot1-cyclonev/` per D9/D10: schematic (`slot1-cyclonev.kicad_sch`,
label-wired, generated), board (`slot1-cyclonev.kicad_pcb`, 127.0 x 47.0 mm
SC242 cartridge outline per the DG Fig 1, 8 copper layers per the D22
amendments: F/B signals, In1+In4+In6 GND planes, In2 rail strips, In3+In5
signal mids), generator
pipeline `hw/tools/gen_slot1_{lib,assign,s6,s7,s8,s8b,s8c,s9}.py`
(S0-outputs = `hw/common/slot1_signals.csv`, `slot1_notes.md`,
`mt41k512m16ha_balls.csv`; variant outputs `pins.csv`, `ddr3.csv`,
`parked.csv`, `power.md`, `assignment_quartus.qsf`, netlist, gate
JSONs, `slot1-cyclonev.bom.csv`).

**Parts** (BOM, 31 refs): 1 FPGA Cyclone V 5CEFA9 F484 (U1), SC242
card edge (U2), 4 MT41K512M16HA-125:IT DDR3L 4 Gbit x16 dies
(U3-U6, 2 ranks x 32 bit, 8 GiB), 20 8-ch level translators (TR01-TR20,
AGTL+ 1.5 V <-> 3.3 V bank grouping per D21), DDR VTT tracker (U7),
J1 JTAG / J2 config / J3 12 V barrel / J4 rails headers.

**Check results**
- S6 ERC: 0 errors, 248 warnings (all inventoried: 142 anchored NC/CFG
  stub labels, 55 endpoint-off-grid cosmetic, 51 lib rows).
- S7 DRC gate: 0 errors (24 card pads x121 grid, keep-outs, notch).
- S8a netting: 529 nets / 1520 pads audited pad-by-pad vs. the netlist
  (die electrical functions through the MT41K512M16HA ball map).
- S8b: 14 strip zones, 471 vias, DRC 0 errors.
- S8b: 14 strip zones, 471 vias, DRC 0 errors (8-layer stack).
- S8c runs 27+28 + NM41 rip-up pass 4 (2026-10-22/23, D22 amendments
  6 -> 8 layers, deterministic): **163/184** die routing jobs placed,
  DRC 0 errors, **383 unconnected** (CLI == pcbnew consistent).
  Progression: 4-layer best 89/184 & 457 (run22) -> 6-layer 127/184 &
  419 (runs 25+26, NM37/NM38) -> 8-layer 162/184 & 384 (runs 27+28)
  -> pass-4 rip-up 163/184 & 383 (runs 39+40: 75 job-paths ripped
  whole, roots + descendants protected, family re-routes in emission
  order). Remaining 21 fails are congestion-starved victim re-routes
  plus 2 crits - all phase-2 router levers measured and rejected
  (NM42 iterated fixpoint, NM43 order+reservation, NM44 demand
  pricing; see their entries); movement needs a structural input.
- S9 audit gates: ERC 0 / DRC 0 (error severity), unconnected
  cross-check consistent, BOM refs == PCB refs (31 == 31).
- Board state: 530 nets, 4522 tracks, 1091 vias, 287/291 zones filled,
  1500 bound pads (276 DDR3, 126 NC, 1098 socket/AGTL+/power).

**Open items**
- D16 (caliper/mechanical exactness), D17 (translator part
  confirmation) - need the operator (list in "Open decisions").
- Chipset datasheets of the B/133-class boards not online; fetch via the
  operator's local archive.
- S8c phase 2 (the remaining 21 jobs) before S10 can call the board
  fully routable: no router-order/pricing lever left - NM42
  (iterated fixpoint: run41 156/390), NM43 (victims-first +
  reservation: run43 161/385) and NM44 (probes 45/46 + demand
  pricing: run45 161/385) are all net-negative; the single-wave
  family rip-up is a true local optimum at 163/184 & 383 (NM41).
  Further movement needs a structural input (an extra routing
  layer, wider clearance budget, or board-form changes), priced by
  the operator first.

## Decided (2026-10-20, by the operator)

- **D8** test boards: Intel 440BX (66/100), VIA Apollo Pro 133/133A
  (66/100/133), Intel i810/i820 (133-class).
- **D9** FPGA: Cyclone V A9 (5CEBA9/5CEFA9 F484) first; Ti180 variants later.
- **D10** RAM: DDR3L, x32, soldered, **4 GiB** (2 x 16 Gbit x16 dies).
- **D11** DDR3 controller on Cyclone V: open-source route (hard DQS periphery +
  an open controller), UniPHY (paid) only as fallback, own RTL last resort.
- **D12** keep **1 small motherboard DIMM** on the board for the chipset/DMA
  path; coherence via FSB snoops.
- **D13** power: external DC input on the cartridge (same as Socket 370's D1).
- **D14** patched stock BIOS ROM is allowed (needed to expose the on-board RAM
  map to the OS).
- **D15** Windows 7 path: 32-bit first (i686+MMX+SSE+SSE2), then x64 with
  SSE3../SSE4.2/POPCNT.

## Open decisions: ask the operator, never decide alone

- **D8** ~~Slot 1 board(s) the operator can test on~~ (decided above).
- **D9** ~~FPGA build order under the availability rule~~ (decided above).
- **D10** ~~RAM technology + capacity~~ (decided above).
- **D11** ~~Cyclone V DDR3 controller route~~ (decided above).
- **D12** ~~Keep a small motherboard DIMM~~ (decided above).
- **D13** ~~Power~~ (decided above).
- **D14** ~~BIOS ROM patch~~ (decided above).
- **D15** ~~Windows 7 boot path~~ (decided above).
- **D16** (closed 2026-10-31 by the Intel standard, operator: "it is
  standardised") Every Slot 1 board must take an original cartridge, so the
  envelope is Intel's, not per board:
  - Substrate 5.000 x 2.275 in = **127.0 x 57.8 mm**, 0.062 in thick
    [`sockets/slot1/celeron_sepp_24365803.pdf` Fig 17 p 44 (3.804 + 1.196 wide,
    1.660 + 0.615 high); `pentium3_secc2_24445201.pdf` Fig 30 p 53 (2.275 +/-0.010)].
    The S7 outline (127.0 x 47.0 mm) is wrong: 47.0 mm = the 1.850 in of DG
    Fig 1 p 9, a horizontal dimension (2.835 + 1.850 and 2.992 + 2.008 run
    along the 5.000 in width). S7 grows the board to 57.8 mm: +1370 mm^2.
  - Primary side: boxed-processor envelope 1.291 in (32.8 mm) max from the
    substrate, 4.90 in wide, 2.19 in high [celeron Fig 20/21 p 54].
  - Secondary side: Intel keeps it bare [celeron Fig 18 p 44: "there will
    be no components on secondary side"]; SECC2 keep-out zones (retention/
    heat-sink contact areas, end zones 0.094-0.138 in) [p3s Fig 38 p 57].
    Amended 2026-10-31 (operator): that rule is dropped on every board, both
    sides carry components wherever nothing collides mechanically; first
    use: U1's small decoupling capacitors on B.Cu under the BGA (D25).
  - Open on the bench: a bare (SEPP-style) card needs a SEPP-capable or
    universal retention mechanism on each D8 board.
- **D17** (decided 2026-10-31 by the operator) Level translators on every
  Slot 1 CPU net (AGTL+ regenerated at the socket VTT, CMOS/APIC regenerated
  at an FPGA rail), same grounds as Socket 370's D3 [slot1_notes R1]. The
  real part (GTL2003-class 8-bit pass-gate, TSSOP20) is still to be chosen.
- **D23** (decided 2026-10-31 by the operator) Next Slot 1 step: place the S3
  power tree and all decoupling before any further routing. Status: done
  2026-10-31 (S6-S9 reruns, see S6/S7/S9).
- **D25** (decided 2026-10-31 by the operator) U1 small decoupling: 0402 on
  B.Cu inside U1's shadow, each on one supply/GND via-in-pad pair; the
  rest of the decoupling goes on F.Cu or B.Cu wherever it collides with
  nothing (D16 amendment).
- **D22** (decided 2026-10-21, amended 2026-10-22 twice by operator: first
  6, then 8 copper layers, same answer as the D5 pattern) Slot 1
  cartridge = 8 layers: signals F&B (B.Cu gets the die escapes, F.Cu the
  U1 lands), ground mids In1.Cu + In4.Cu + In6.Cu (In6 gives B.Cu its
  return reference), power mid In2.Cu rail strips, signal mids In3.Cu +
  In5.Cu; no HDI. The 133 MHz AGTL+ section and the DDR3L x32 bus ride
  the signal layers; every AGTL+ net has a translator pair so segment
  lengths stay short [S8 fill]; the ground mids give the DDR3 VREF rails
  solid planes. Amendment history: the 4-layer original (signals F&B,
  one GND mid In1.Cu, one power mid In2.Cu) left the U1 two-gate channel
  (x 81.5..90) at 89/184 routed with all U1 escapes fighting one
  corridor [NM36]; the operator raised the ceiling to 6 (127/184, NM37)
  and then to 8 (162/184, NM39).

## S5 pin-assignment decisions (agent, within D8-D17 scope)

- **D18** DDR3L x32 sits in banks 7A + 8A at VCCIO 1.35 V: four x8 DQ/DQS
  groups of the F484 top side (the "DQS for X8" columns DQ4T/DQ3T/DQ2T/DQ1T =
  HMC designators T_DQS_0/1/2/4; byte 3 = the T_DQ_32..39 cluster) [cv-52006
  Tables 6-5/6-16 p 6-4/6-40, `FPGAlist/CycloneV_A9/pins/5cefa9.txt` F484
  block]: 32 DQ + 4 DM + 4 DQS pairs + CKE (F14) / ODT (L8) rank-0 balls,
  CS#_0 (E9) in 8A, RZQ_2 (B11, 240 Ohm to GND) and RESET# (J19) in 7A;
  A[15:0]/BA[2:0]/RAS#/CAS#/WE#/CK pair in 8A. **Realized dies (NM24)**: no
  16 Gb x16 DDR3 die exists (DDR3 x16 stops at 8 Gb [alliance/micron 8 Gb
  x16 datasheet: 512M x 16, 64K row = A[15:0]]), so D10's "2 x 16 Gbit" is
  built as **4 x 8 Gb x16 dies = 2 ranks**: rank 0 = die0 (bytes 0-1) +
  die1 (bytes 2-3), rank 1 = die2 + die3 sharing the same byte-lane balls;
  rank controls on the HMC-provisioned pair balls: CS#_0/1 = E9/D9,
  CKE_0/1 = F14/B13, ODT_0/1 = L8/A12. Total DDR3 = 76 balls; option BOM:
  4 x MT41K512M16HA singles or 2 x TwinDie packages (one rank each) [farnell
  TwinDie datasheet]. The Cyclone V E A9 HMC width is 24-bit per side
  [cv-52006 Table 6-16 p 6-40], so the interface rides the DQ/DQS periphery
  routes per D11's open-source RTL; the same ball map is in production on
  the Opal Kelly FOMD-ACV 5CEFA9 board [local snapshot
  sockets/slot1/die/opalkelly_fomd_acv_ddr3_pinmap.html].
- **D19** Parked contacts (no FPGA pin, component ties on the cartridge;
  list `hw/slot1-cyclonev/parked.csv`): CPU test port TCK/TMS/TDI/TDO/TRST# +
  PREQ#/PRDY#; VID[4:0] divider (2.00 V, power.md); 100/66# left floating
  (100-MHz capable, slot1_notes "80"/NM4); TESTHI mode strap; BP[3:2]#/
  BPM[1:0]# inactive ties; IERR#/FERR# left undriven high (board terminators
  keep them inactive); PICCLK removed (local APIC timer runs from an
  internal core-derived clock); SLOTOCC# tied low (present) and
  PICD[1:0] tied (APIC ID 0); THERMDP/THERMDN open. Result after the NM24
  rank update: 145 FPGA balls for slot 1 nets, 76 for DDR3L, 3 free.
- **D20** AGTL+ translator channels may land in the 1.35 V banks 7A/8A once
  the 3.3 V pools fill: AGTL+ is an open-drain protocol (drive low, float to
  VTT), so the FPGA side only receives <= 1.5 V (VCCIO + 0.15, inside the
  I/O buffer tolerance) and never drives high [cv-52006 chapter on I/O
  buffering]; CMOS nets stay out of 1.35 V banks entirely.
- **NM21** BCLK reception supersede of slot1_notes R5 (N9 = CLK1p at bank
  VCCIO 2.5 V): with DDR3 owning 7A/8A there is no spare 2.5 V bank (3B at
  2.5 V leaves only 96 3.3 V balls for 133 AGTL+ channels - short by 13), so
  all translator banks are 3.3 V and BCLK lands on M9 = CLK0p (bank 3B,
  clock-capable [cvcsv]). Input around "3.3-V LVTTL": its VIH = 2.0 V and
  the SC242 AC window guarantees highs measured above 2.0 V for 2.1 ns [p2
  Table 9 p26], so the 2.5 V-class clock meets VIH legally; margin vis is
  the AC-window floor and any D8 board with a lower swing gets flagged at
  S6.
- **NM22** PICCLK removal is a deviation: any local APIC timer in the RTL
  must derive from a core-internal clock (frequency-counted from BCLK at
  reset, like the FSB-detect trick) instead of sampling PICCLK.
- **NM23** AGTL+ pins are assigned plain LVTTL/SSTL-135 bank standards and
  rely on the RTL driving 0/Z through the translator (Socket 370 T5 QSF does
  the same, no per-pin open-drain assignment); S8 must verify the open-drain
  drive and the 0.675 V VREF wiring (7A = C14, 8A = B8, inputs only) at
  compile time.
- **D21** (S6) A physical Translator_8ch chip has one VCCA/VCCB pair, so the
  144 translated signals are packed into chips that never mix supply pairs:
  a chip breaks on a bank VCCIO change (3.3 V vs 1.35 V) or a socket-rail
  change (AGTL+ -> VTT 1.5 V, CMOS -> 2.5 V, generated on the cartridge)
  [S6 fill fix; the S5 flat fill had mixed rails inside one chip]. Fill in
  signal order with 8 channels per chip: result = 20 chips (2 CMOS +
  18 AGTL+ of 3.3 V and 1.35 V banks mixed by boundary); BCLK direct.
- **NM24** D10 die wording corrected in S6: DDR3 JEDEC densities end at
  8 Gb per die; the x16 8 Gb die = MT41K512M16 (512M x 16, row 64 K =
  A[15:0], 96-FBGA) [alliance/micron datasheet in
  sockets/slot1/die/mt41k512m16ha_8gb_x16_ddr3l.pdf]. 4 GiB = 2 ranks x
  (2 die x 8 Gb). Rank-1 controls (B13 CKE, A12 ODT, D9 CS#) consume 4 balls
  the single-rank tie-off idea had parked; IO budget after D18: 76 DDR3 +
  145 slot 1 + 3 free (2 in 7A, 1 in 3B).
- **NM25** (S7 placement facts locked by the DRC gate, S8 must keep them):
  (a) the slot geometry is DG Fig 1: A1 at 4.0 mm, key notch between
  stations 73/74 with the head+neck step pads to y 3.5 (Detail A), 2.49 mm
  chamfers; (b) U2 is placed +0.055 mm off the insertion edge - the kicad-cli
  edge DRC measures to the Edge.Cuts stroke edge (+0.05 mm for the 0.1 mm
  stroke) and needs the 55 um offset instead of the DG242 flush land; inside
  any fab's edge-mill tolerance, D16/real-divider re-check; the S4 donor
  footprint stays flush at y=0; (c) the connector cavity keep-out is
  y 3.5..7.0 (finger faces end at 3.5) and the retention bands x<16/x>111
  start at y 7.0 - exact engagement sketches pending D16/NM11; (d) the die
  lands are a generic 6x16 placeholder grid - S8 replaces them with the
  MT41K512M16HA Fig 7 ball map (0.8 mm, Fig 9) and re-runs DRC.
- **NM26** (S8b, done 2026-10-21, `hw/tools/gen_slot1_s8b.py`): pours +
  stitching on the D22 stack, `kicad-cli` DRC 0 errors, 0 unconnected_items.
  (a) Layer set F.Cu/In1.Cu/In2.Cu/B.Cu + user layers; In1.Cu = one GND
  plane zone; In2.Cu = per-rail strip zones from a 2.0 mm cell raster
  Voronoi over every rail pad sample (reach cap 6 mm; row-wise maximal runs,
  strips of different nets never overlap; every strip gets its own
  `(priority n)` - same-net adjacent strips intersect at their shared edge
  and v10 refuses equal priorities). (b) Zone syntax facts for the v10
  toolchain: a zone becomes a real copper pour ONLY with `(fill yes ...)`;
  a `(placement ...)` token or a `(keepout ...)` clause turns the zone into
  a rule area (the first S8b draft carried all-"allowed" keepout clauses on
  the pours and pcbnew silently filled nothing); S7's keep-out zones keep
  their clauses on purpose. (c) The fills are persisted with the pcbnew
  python module (`ZONE_FILLER(board).Fill(board.Zones())` then Save;
  `kicad-cli pcb drc` does NOT refill - an unfilled pour passes
  unconnected_items by outline-virtualisation but its vias come back
  `via_dangling`). (d) Stitching: BGA (U1 + dies) power/GND lands widened
  0.3/0.45 -> 0.60 with a 0.6/0.3 via-in-pad (project min_through_hole is
  0.3, min_via_annular_width 0.05); card-edge contacts get a 0.6 mm stub to
  a 0.5/0.3 via, A row +2.55 mm / B row +3.45 mm below the pad centre (B
  stubs ride B.Cu); TSSOP translators get a 0.35 mm vertical stub to a
  0.5/0.3 via, first power pin of a row 0.675 mm inboard and each further
  one 0.8 more (uniform +1.05 mm collides with the next chip's pads: rows
  are 6.85 apart, chips' pad rows 2.675+0.55 deep). Pours use
  `(connect_pads yes (clearance 0.2))` (kills starved_thermal on U7's PTH
  pads) and `min_thickness 0.15` (the 0.2 mm fill ring between 1.0 mm-pitch
  BGA antipads needs it). (e) S7 fix: stations 73/74 stepped pads were
  emitted on fake `A.Cu/B.Cu` layers - the v10 loader mapped them to junk
  layers and their unconnected stub showed as the one track_dangling; they
  are now F.Cu/B.Cu per the B-row donor convention. (f) Left open for S8c
  (35 warnings): 19 via_dangling = low-current rails (VTTREF0675/VCCPD33/
  VCCPD135/VCCPGM18/VCC_1V1/VCCIO135/VCMOS) whose isolated ball row has no
  same-net neighbour to bridge the 0.2 mm antipad gaps - the fill vendor
  drops into the antipad lattice is geometrically impossible at 1.0 pitch
  with 0.6 lands, these rows need a track escape, not a wider pour;
  10 isolated_copper = VTTREF0675 fringe fill fragments at the die/U1
  periphery (no via inside, removable at S8c by trimming the raster);
  6 lib_footprint_mismatch = S4 library text vs pcbnew's re-render.
- **NM27** (S8c gates + entry work): (a) `kicad-cli pcb drc` does NOT run
  the ratsnest `unconnected_items` test at all (v10.0.3 probe: a demo net
  severed of all its tracks still yields zero such rows; no netlist option
  exists on the CLI), so the routing gate is DRC error-level rows for
  clearances PLUS a pcbnew `CONNECTIVITY_DATA.GetUnconnectedCount(True)`
  check that must reach 0 - the board's starting budget is 541 unconnected
  edges (signal nets have no tracks yet, only the S8b stitching stubs).
  (b) The NM26 strip-trim experiment (emit a strip only with a same-net
  pad inside it or within one cell) was reverted: any trimming degrades
  fill connectivity (via_dangling 19 -> 32 with a one-cell trim, 19 -> 53
  with strict containment) because the stripped cells carry the vias'
  fill islands; the raster stays untrimmed and the 10 VTTREF0675 fringe
  islands stay accepted as S9/CAD-clean-up material.
- **NM28** (S8c topology decisions): all U1/die balls get via-in-pad lands
  (U1 1.0 mm pitch: signal land 0.45 + via 0.45/0.30, power land 0.5 + via
  0.5/0.30; dies 0.8 mm pitch: signal land 0.45 + via 0.35/0.20 - a
  0.3-drill ring leaves no legal corridor in the 0.8 lattice - power land
  0.5 + via 0.5/0.30). Escapes run on B.Cu only in phase 1, leaving each
  via along a column/row midline to the ring-gap junction; F.Cu carries
  only open-area crossings in later phases. DDR3 net fan-out is handled as
  per-pair jobs (U1 pad -> each die pad) that may share their own reserved
  cells.
- **NM29** (S8c phase-1 router DRC-clean, 2026-10-21, `hw/tools/gen_slot1_s8c.py`):
  - Constraint world (wired into `gen_slot1_s7.py` floors, probed
    empirically): board floors min_track_width 0.15, min_hole_clearance
    0.15, min_clearance 0.0, min_through_hole_diameter 0.2,
    min_via_diameter 0.3; Default net-class clearance 0.15. The pair
    clearance resolves as the min of the two nets' classes;
    `netclass_patterns` do NOT resolve for netlist-imported nets; a
    present `.kicad_dru` resets every `.kicad_pro` numeric constraint, so
    floors live in the `.kicad_pro`.
  - Router: 0.05 mm grid, 4-connected A* (axis moves only - no
    corner-cut ambiguities), B.Cu only. B block map = foreign via-ring
    disks (ring + trace/2 + clearance, strict inequality so an
    exactly-min cell stays routable), foreign B.Cu tracks, Z4 notch, card
    edges; F.Cu pads do not block B. Own-net pad/via zones stay passable
    as the escape funnel. Route reservations Chebyshev-7 (min lateral
    0.4 mm -> 0.25 gap) and never overwritten; same-net fan-out shares
    its own cells.
  - Gate reached: 0 DRC error rows with 33/184 die jobs routed
    (unconnected 513; warnings 253 = 199 via_dangling on the not-yet-
    routed in-pad vias + 48 isolated_copper on shrunk-via fills + 6
    lib_mismatch). Single-layer planarity limits completion - phase 2
    adds F.Cu crossover legs in open space with via insertion.
  - Pipeline discipline: S7->S8a->S8b re-runs before every router
    revision; the s8c prep itself is idempotent-unsafe, always start from
    fresh S8b output.

- **NM30** (S8c phase-2-fixed, 2026-10-21, run5): 67/184 die jobs routed,
  DRC errors 0, unconnected 479. `via_ok` site-bitmap semantics fixed
  (1 = blocked: `not site[c] and not vkill[0][c] and not vkill[1][c]`);
  emit-time crossover-via site radius = max(sig_via + clearance,
  drill + 0.25) -> 0.6 mm; multi-pass main loop + `build_maps()` refactor
  in place.
- **NM31** (die power vias shrunk): die VDD lands/vias use the SAME
  0.35/0.20 geometry as signal vias (~28 mA/pin of ~0.5 A die VDD makes
  the drill safe electrically). Result unchanged (66 routed, DRC 0):
  power rings were NOT the primary seal.
- **NM32** (same-net pass-through): two router-only sealing bugs, both
  fixed - (a) `free()` applies only to pads/vias funnels of OWN cells;
  pass-1 emitted tracks of the SAME net were sealed for its later branch
  jobs. Fix: `selfpaths` per net merges every emitted path's cells into
  `own[name]` (flip cells both layers) at pass start and after each emit
  (`merge_own`). (b) `astar` bridged layers only at NEW `via_ok` sites;
  own pre-existing vias (in-pad + previously emitted flips, tracked in
  `_PLACED_VIA`) now give a free cost-1 flip that stacks NO copper and
  emit skips duplicating a via there.
- **NM33** (S8c phase-1 guard, 2026-10-22, run15): raster/geometry seam
  found and closed with an exact geometer guard `guard_ok()` - each
  emitted plan (segment endpoints, layer) is checked against ALL foreign
  copper (vias r + 0.225, tracks centre-to-centre >= 0.30 + eps,
  F-land rects) at DRC limits with half-cell fuzz eps; boundary-exact
  plans (d = 0.400/0.450 exactly) that the raster also frees pass, real
  collisions get rejected and the job fails. The three branch pairs that
  produced run8's 30 DRC errors (CKE0/DQ01 bay, A1/A4 U6-junction,
  RAS#/A3) are deterministic ownership-hole rides and now fail cleanly.
  Gate reached: **74/184 routed, DRC errors 0, unconnected 472** (logs
  /tmp/opencode/s8c15.log). Remaining 110: reach-fail bubbles
  (CK/CK#/BA2 to U4., far 550-1510 pops), the 3 guarded pairs, plain F/B
  congestion; next lever = bus-lane preplanning or negotiated congestion
  (deferred until phase-2 architecture).
- **NM34** (S9 verification audit, 2026-10-22): `hw/tools/gen_slot1_s9.py`
  is the S9 gate - (a) ERC regenerated, 0 error rows required
  (248 warnings = the accepted S6 NC/CFG stubs + off-grid cosmetic rows,
  counted by type); (b) DRC regenerated, 0 error rows required, plus the
  CLI stdout "Found N unconnected items" value cross-checked against
  pcbnew GetUnconnectedCount and gate-failing on inconsistency (the JSON
  report never lists unconnected rows, NM27); (c) BOM exported via
  `kicad-cli sch export bom` into `slot1-cyclonev.bom.csv`, gated on BOM
  ref set == PCB footprint ref set (31 == 31); (d) prints board facts
  (layers/nets/tracks/vias/zone-fill/pad families). Milestone passed.
- **NM35** (S8c phase-2 start + session collision, 2026-10-22):
  (a) failure classification on the fresh S8b board
  (/tmp/opencode/s8c_p2base.log): the remaining 110 jobs are NOT a
  CK/BA2-only pocket - every addr/ctl/data family loses some far-die
  legs, worst on U4/U6 (fail-line labels per die: U6 73, U5 62, U4 53,
  U3 29 across both passes), consistent with shortest-first starvation;
  (b) pass-2 job order reversed (long-first) and this IMPROVED the gate:
  the concurrent-session final board shows unconnected 470 / DRC errors
  0 (was 472) - the reversal edit stays in `gen_slot1_s8c.py`;
  (c) DIAGNOSTIC COLLISION on disk: while revising, a second agent
  session ran the SAME S7->S8a->S8b->S8c chain on this repo and its
  steps overwrote this session's outputs mid-run (its S7 at 08:35:44
  clobbered the just-saved s8c result - a gate read of that torn state
  shows the tell-tale netless `unconnected: 0`). The disk board
  (3490 tracks / 1038 vias / 470 unconnected / DRC 0) is the concurrent
  session's final s8c output and is the current best state. Two sessions
  must not run the destructive S7->S8b pipeline against one board
  without a lock - needs operator deconfliction (which session owns the
  workspace). This session froze destructive runs thereon; my s8c16 was
  lost to the race (its log /tmp/opencode/s8c16.log is valid up to
  "saved + filled").
- **NM36** (S8c phase-2 multi-source, 2026-10-22): the reach failures
  are CONGESTION, not structure - on the virgin S8b raster a path to
  every previously failing target exists (wallmap probe /tmp/opencode/
  wallmap.py, /DDR3_CK U4 cost 6000 = straight-line + flips). changes to
  `gen_slot1_s8c.py`:
  (a) multi-source astar: per-net seed list over REAL copper only
  (`realcopper`, NM36 source of truth) = every emitted path's cells
  (flip cells both layers); the board's own in-pad vias count as
  flip-overable (`_PLACED_VIA` semantics unchanged) but do NOT seed -
  a die pad's floating in-pad via would make the job a no-op (run19:
  routed 158 but unconnected 458 instead of ~383);
  (b) pass 1 = full depth order, pass 2 = leftovers reversed, pass 3 =
  leftovers at via_cost 30 (the r19/r20 structural experiments).
  Gate reached (run22 = deterministic rerun of run20 semantics):
  **89/184 routed, DRC errors 0, unconnected 457** (was 74/472, NM33).
  spine-first restructure (pass 1 = all net primaries first) made it
  WORSE (62 routed) - the interleaved depth order wins; reverted.
  Remaining 95 = the two-gate channel wall: all U1 escapes cross the
  x 81.5..90 corridor between U1 bay and the die field, exhausted by
  89 reserved corridors; next lever = bus-lane preplanning (assign
  channel lanes per net family BEFORE routing) - phase-2 architecture
  task. Guard-rejects changed with the restructure: 2 pairs now
  (CK# U4 vs A2, DM2 U4 vs DQ16), the old 3 are gone. S9 gate
  re-certified on run22 (ERC/DRC/BOM all PASS).
- **NM37** (D22 amendment, 2026-10-22, operator): "you can pass to 6
  layers". Stack becomes F/B signals, In1.Cu + In4.Cu GND planes,
  In2.Cu rail strips, In3.Cu free signal mid - motivated by NM36's
  channel-wall analysis (one more routing layer through the x 81.5..90
  U1 bay channel beats any pass-order trick). Realized in
  `gen_slot1_s8b.py` (second GND plane zone, uuid 100, layer list
  +In3/In4) and a 3-routing-layer generalization of `gen_slot1_s8c.py`
  (LAY_NAME: 0 = B.Cu, 1 = In3.Cu, 2 = F.Cu; see NM38). The
  astar flip now costs ONE drill to ANY other routing layer (a TH via
  crosses everything); pads stay F-only; own via rings + foreign via
  disks rasterize on every routing layer; merge_own / realcopper /
  emit reservations extend per layer; in-pad via `_PLACED_VIA` reuse
  semantics unchanged.
- **NM38** (6-layer run fixes, 2026-10-22): first 6-layer run surfaced
  two DRC seams, both fixed in `gen_slot1_s8c.py`:
  (a) own-funnel leak: a cell inside the net's pad funnel is own-
  passable, but a FOREIGN via's block disk can reach into the funnel -
  the router walked through (/DDR3_RESET# F cap at d 0.4472 vs a
  /DDR3_A3 via ring, limit 0.45). Fix: `own_cells` subtracts every
  other net's via block disk from each net's own sets (own in-pad vias
  keep coverage). The cap-corner distance 0.4472 = hypot(0.4, 0.2) is
  the ONLY 0.05-lattice distance closer than 0.006 to a clearance
  threshold, so the guard via check uses GUARD_VEPS = 0.0025 (rejects
  0.4472, keeps the legal exact-boundary 0.400/0.450 rings that eps 0
  wrongly rejected: run24 collapsed to 60/184 from that).
  (b) via-via ring clearance: the via-site bitmap priced a foreign via
  at its drill, not its ring (0.525 vs needed 0.60 for two 0.45 vias;
  run24: /DDR3_CS#1 vs /DDR3_BA2 at 0.559). Fix: r_site =
  max(dial + SIG_VIA/2 + CLEAR, hole rules) and guard_ok grows a VIA-V
  row checking every NEW flip position against foreign via rings (reused
  own vias excluded; flips passed from main as run-joint cells).
  Result (runs 25+26, deterministic): 127/184 routed, DRC 0, 419
  unconnected (4-layer best: 89/457). The old RESET# U6 cap corner now
  fails its job in-guard ("d0.447 @100.60,24.40") - clean reject, no
  DRC error. S9 gate re-certified: ERC 0 / DRC 0 / BOM PASS.
- **NM39** (D22 second amendment, 2026-10-22, operator): "switch to 8
  layer". Stack F/B signals, In1/In4/In6 GND planes (In6 gives B.Cu
  its return reference), In2 rail strips, In3 + In5 signal mids ->
  FOUR routing layers in the s8c router (LAY_NAME: 0 = B.Cu,
  1 = In3.Cu, 2 = In5.Cu, 3 = F.Cu; all layer loops generified over
  LAY_NAME, no more hardcoded b/g/f tuples). Realized in
  `gen_slot1_s8b.py` (layer list + In5/In6, third GND plane zone uuid
  101) and the N-layer s8c. Result (runs 27+28, deterministic):
  162/184 routed, DRC 0, 384 unconnected, 1064 vias - the In5 mid
  keeps routes on-layer, cutting drills vs the 6-layer 1092 while
  routing 35 more jobs. What remains: 22 reach bubbles (peak U4/U6
  targets) + the in-guard rejects; S9 gate re-certified (ERC/DRC/BOM
  all PASS). Phase-2 next lever unchanged: bus-lane preplanning.
- **NM40** (phase-2 experiment log, 2026-10-22/23): the 22 leftovers
  were probed in isolation (probe /tmp/opencode/probe22.py: fresh-S8b
  raster, only the job's own funnel passable): ALL 22 have valid
  isolated paths - zero structural failures; they fail purely from
  corridor congestion (isolated costs range 4.3k for /DDR3_BA0 U4 to
  206k for /DDR3_DQ26 U6: the bottom-row U4/U6 jobs detour heavily
  even alone). Three cheap levers tried against them, one full chain
  each (fresh S7-S8a-S8b before every run):
  (a) net-grouped todo order (spine job first, its branch jobs riding
  right after; depth-order locality kept inside each net): run29 =
  136/184 - WORSE than the interleaved depth order (consistent with
  NM36); reverted.
  (b) isolated-path preplanning: each of the 22 criticals routed and
  emitted BEFORE pass 1 (probe-exhaustive guard-passing paths,
  pre_done fallback to todo): run30 = 161/184 + 385 unconnected -
  NEUTRAL-WORSE: the isolated paths are detour-heavy and hog channel
  capacity the flexible nets would have shared; reverted. Verdict: a
  whole-path preplan can't beat the greedy order; the lane-assignment
  variant (preplan channel LANES, not paths) remains unproven.
  (c) reservation relaxation: OFFSETS' 4 single-axis exact-boundary
  offsets removed (0.30-exact centre distance is DRC-legal - strict <
  - and the guard's thresholds still adjudicate real geometry; KiCad
  grid maths are exact 50k-nm multiples so no sub-boundary rounding
  exists): run31 = 162/184, UNCHANGED - the failures are not
  reservation-window limited; reverted (same numbers, no reason to
  spend the margin).
  Standing best stays 162/184 (runs 27+28 semantics). Next real
  lever: deterministic rip-up (route the 22 with blocking nets'
  copper deleted, then re-route the ripped nets) or negotiated
  congestion - both are new machinery, not order tricks.
- **NM41** (deterministic rip-up pass 4, implemented 2026-10-23):
  leftover jobs are solved against the STATIC S8b raster (s8c-emitted
  copper transparent via build_maps/own_cells/guard_ok `skip` =
  uuid-strings of emitted items; `m_Uuid.AsString()` is the identity
  key - PCB_TRACK proxies are unhashable), every emitted job-path whose
  real geometry comes within the guard thresholds of a solution is
  RIPPED whole (objects deleted, _PLACED_VIA flip cells - never the
  static in-pad cells - and selfpaths entries reverted, realcopper
  seeds rebuilt from surviving paths to kill phantom starts), the 22
  route first on the rebuilt raster, ripped victims re-route behind
  them (victim credit is deducted from tot_ok at rip time so the final
  count cannot double-count). One rip only; a victim that misses its
  re-route is a net loss. Run log (runs 33-40, every run a fresh full
  chain S7-S8a-S8b-s8c):
  run33: bd.Delete on emit-time proxies crashed (GetClass on a freed
  object).
  run34/36: deletion ran to completion but 181/184 with UNCONNECTED
  400 (vs 384 base): forensic via KiCad pad clusters
  (cn.GetConnectedItems(pad): the GetConnectedPads python binding is
  empty) showed ~26 nets with a floating U1 pad each: run36's pre-rip
  snapshot (frozen_s8cred_pre_rip) proved the pass-1 copper intact.
  Root cause: swig proxies captured at emit() go STALE after bd.Add
  (the board's track container reallocates) - deletes by proxy hit
  arbitrary other copper. Identity key for emitted items everywhere:
  m_Uuid.AsString() strings (PCB_TRACK is unhashable).
  run37 (deletes resolved through a uuid->live-object map built at
  pass-4 start) fragmented the SAME ~26 nets: structural, not proxy
  luck. Mechanism: pass-1's FIRST job per net draws the FULL
  U1->die path (its realcopper seeds are empty) while every later
  rider seeds mid-spine and emits only its spur - the root carries
  the net's ONLY U1-side copper; ripping a root dismembers the net
  no matter how the job re-routes.
  run38: roots exempt (ej["root"] = path[0] == own U1 pad cell,
  recorded at emit registration): victims 107->59, 165/184 but
  unconnected 397: riders can also anchor on EARLIER RIDERS' cells,
  so a mid-tree rip orphans its descendants.
  run39: FAMILY rip - a victim takes the transitive descendant
  closure (same-net paths whose start cell lies on the victim's
  cells; roots skipped) and the whole family re-routes in emission
  order (ord recorded per registration: an anchor is always emitted
  before its dependents). 163/184, unconnected 383, DRC 0.
  run40: determinism re-run, byte-level verdict identical (same 75
  victims, 163/21, 383 unconnected, S9 all PASS). NEW STANDING BEST:
  163/184 routed (was 162), DRC 0, 383 unconnected (was 384); board
  facts 530 nets | 4522 tracks | 1091 vias | zones 287/291 filled.
  Cluster delta vs the old base: +4 links closed (BA0, DQ27, DQ31 all
  formerly-failing criticals now fully landed) minus one partial
  -4 fragmentation (A11: family ripped, all 3 re-routes failed =
  21 pass-4 fails: 2 crits + 19 victim re-routes). NET REMAINING
  DIALS: victim re-routes that fail under congestion (the same
  starvation mechanics as pass-1); iterative rip-to-fixpoint or
  negotiated congestion are the next levers if 383 -> ~365 matters.
  Unconnected is a near-pure function of the fail count (each
  detached die pad opens exactly the link its job would have
  closed): only fail reduction moves the number.
- **NM42** (rip-to-fixpoint wave 5, 2026-10-23, REJECTED): the pass-4
  machinery generalized to repeat over its own failures - pass 5
  re-solved the wave-4 failures against the CURRENT static substrate
  and ripped 73 MORE landed job-paths; only 66-of-94 re-routed
  (congestion cascade) -> 156/184, unconnected 390 (worse than
  163/383, run41). Iterated family rips never converge under this
  congestion profile; pass tuple reverted to (1, 2, 3, 4) and the
  board restored by the run42 chain (run39/40 code semantics). The
  metric insight stands: unconnected ~ 364 + fail count, so only
  fail reduction moves the number; the remaining levers are
  negotiated congestion (history costs) or corridor-lane
  preplanning.
- **NM43** (crit corridor reservation + victims-first, 2026-10-23,
  REJECTED): the wave-4 sweep order was crits-first, which lets the
  crits take the freshly ripped lanes and starve the 19 victim
  re-routes; tried: the crits' planned corridor cells (per layer)
  pre-reserved in `owner` (a foreign-owned cell blocks astar; the
  owning net passes), victims re-routing FIRST, crits landing LAST
  on their own cleared lanes. Result: 161/184 routed, unconnected
  385 (worse than 163/383) - the reservation over-constrained the
  victims (54/75 landed vs 56) and the crits landed the same 20/22
  either way; the corridor cells were never the binding shortage,
  so the victims-first displacement traded 2 jobs for nothing.
  Reverted (3 edits) and the board restored by run44. Verdict:
  crits-first + free victim lanes (NM41 shape) is the local optimum
  of this order lever; remaining phase-2 lever = negotiated
  congestion (history costs) only.
- **NM44** (static demand congestion pricing, 2026-10-25, REJECTED):
  probes first. probe45 = conflict census of the 21 residual jobs vs
  the landed copper on the virgin-raster isolated solutions: every
  residual needs 194-772 cells across 2-20 OTHER nets' land (total
  9700 cells; BA2 alone covers 1351) - the residuals are full-length
  U1 curves with BIG shared demand, not order-starved small jobs.
  probe46 = full 184-job demand census (every todo job solved
  isolated on the virgin S8b raster, ~10 min): 42,400 demanded
  cells, 59.6% covered by >=2 distinct nets, share histogram 2..14
  (max 14), the hot die-fan cells around (90-101, 25-31) on B.Cu.
  Implementation: the s8c sweep's astar paid `min(demand, 8)` per
  cell step (hist, NM44), pre-displacing the crowd via parallel
  cool lanes (via cost 80 unaffected; pass-4 static solve
  hist-free). Result (run45): pass 1 dropped to 157/27 (the detours
  failed more jobs than they freed; pass 4 landed 84/23 but the
  final tally 161/184, unconnected 385 - worse than 163/383).
  The in-chain census reproduced probe46 exactly (cells 42400,
  shared 25283) = deterministic. Reverted (4 edits) and the board
  restored by run46. VERDICT ACROSS PHASE 2: order (NM43), iterated
  fixpoint (NM42), and proactive pricing (NM44) are each net-negative
  vs the NM41 single-wave family rip-up; the 163/383 state is a true
  local optimum of this congestion profile, and further movement
  needs a structural input (more free routing layers, wider gaps,
  or a changed board order), not another router-order/pricing trick.
