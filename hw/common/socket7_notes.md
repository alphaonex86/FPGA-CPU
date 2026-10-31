# Socket 7 notes - Biostar MB-8500TTD, Intel 430TX (MTXC + PIIX4)

T2 of `plan/interposers.md`. Covers variants `socket7-cyclonev` (5CEBA9/5CEFA9
F23C8N) and `socket7-ti180` (TI180G400C3); answers tagged **[Cv]** or **[Ti]**
are FPGA-specific, all others are common. Citations are PDF pages of the file,
except `cvhb` (cited as printed chapter page, e.g. 7-19), `devman` and `fmb`
(printed chapter pages, e.g. 4-8 and 2-2). The board CPU is a Pentium MMX 233
(family 5 model 4 stepping 3) per `cpuinfo`.

Sources:

| tag | file |
|---|---|
| mmx | sockets/socket7/pentium_mmx_datasheet_243185-004.pdf |
| devman | sockets/socket7/pentium_family_developers_manual_241428-005.pdf |
| fmb | sockets/socket7/intel_430hx_pcsiset_design_guide_297467-002.pdf |
| mtxc | sockets/socket7/intel_82439tx_mtxc_290559-001.pdf |
| piix4 | sockets/socket7/intel_82371ab_piix4.pdf |
| ics | sockets/socket7/board/ics9169c-27_clock_generator.pdf |
| spec | sockets/socket7/board/biostar_mb-8500ttd_spec.pdf |
| jumpers | sockets/socket7/board/biostar_mb-8500ttd_undocumented_jumpers.pdf |
| cpuinfo | sockets/socket7/board/cpuinfo_pentium_mmx_233.txt |
| ap579 | sockets/socket7/ap579_flexible_motherboard_243187-002.pdf |
| pinmap | sockets/kicad/pinmaps/socket7_p55c.csv |
| mmpins | sockets/parts/mill-max_catalog_metric.pdf |
| cvds | FPGAlist/CycloneV_A9/docs/cv_51002_device_datasheet.pdf |
| cvhb | FPGAlist/CycloneV_A9/docs/cv_5v2_device_handbook_vol1.pdf |
| cvcsv | FPGAlist/CycloneV_A9/pins/5ceba9_f484.csv |
| tids | FPGAlist/Ti180_G400/docs/ti180_datasheet.pdf |
| tian033 | FPGAlist/Ti180_G400/docs/an033_configuring_titanium.pdf |
| ticsv | FPGAlist/Ti180_G400/pins/ti180g400.csv |
| readme | FPGAlist/README.md |
| agents | AGENTS.md |

## R1 - DC levels the chipset drives onto the bus

- The host bus is 3.3 V TTL: at the CPU pins VIL -0.3 to 0.8 V, VIH min 2.0 V,
  VOL max 0.4 V at -4 mA, VOH min 2.4 V at 3 mA [mmx p.31 Table 11]. The P55C
  is a 3.3 V I/O part: absolute maximum on a 3V-only buffer input is
  VCC3 + 0.5 V (VCC3 max 4.6 V) [mmx p.30 Table 9].
- The MTXC connects directly to the Pentium 3.3 V (or 2.5 V) host bus with
  3.3 V drivers; its CPU-side pins are typed "3.3V/2.5V" [mtxc p.6, signal
  list pp.7-9]. So the chipset drives 3.3 V TTL onto the bus, not 5 V - unlike
  Socket 3, no 5 V translator is needed for voltage reasons.
- CPU CLK and PICCLK inputs are "3.3 V tolerant" on the MMX part
  [devman p.4-9, p.4-14], and Intel's FMB design guide lists the P55C inputs
  that are NOT 5 V tolerant: CLK, PICCLK, AHOLD, BRDYC#, EADS#, KEN, WB/WT#,
  INV, NA#, EWBE#, BOFF# [fmb p.2-2]. A production 430TX board therefore
  stays inside the 3.3 V domain on the host bus.
- [Cv] direct 3.3 V banks fit: 3.3-V LVTTL input VIL max 0.8 V / VIH min
  1.7 V, output VOL max 0.45 V / VOH min 2.4 V at 4 mA [cvds p.19 Table 15];
  margin to the chipset's 2.4 V VOH is 0.7 V.
- [Ti] electrically direct as well - 3.3 V LVTTL HVIO input VIH min 2.1 V,
  output VOL max 0.4 V / VOH min 2.4 V [tids p.85 Table 64] - margin to
  2.4 V is 0.3 V. But the G400 has only 74 of 274 user I/O 3.3 V-capable and
  HVIO is limited to 6 outputs/bidirectional per bank at 3.3 V, so the whole
  bus must go through translators anyway [readme "I/O budget" section]. The
  translators are then a pin-count choice, not a level necessity; translators
  on all nets keeps one layout language for both socket 7 variants.

## R2 - Power pins

- Rails on the socket: VCC2 = core, VCC3 = I/O, VSS [pinmap]. Counts match
  the datasheet: 28 VCC3, 25 VCC2, 53 VSS [mmx p.28 sec. 3.1.2.1].
- Voltages: VCC2 2.7 / 2.8 / 2.9 V (+/- 3.57 %), VCC3 3.135 / 3.3 / 3.6 V
  [mmx p.31 Table 10]. Absolute max: VCC2 3.7 V, VCC3 4.6 V [mmx p.30 Table 9].
- No power sequencing: "no specific power sequence required" for VCC2/VCC3,
  recommended both ON or both OFF within one second [mmx p.28 sec. 3.1.1.1].
- Currents at 233 MHz: core ICC2 max 6.5 A (power-supply design value,
  measured at VCC2 = 2.9 V), I/O ICC3 max 750 mA [mmx p.31 Table 12].
- Power: active max 17.0 W (typical 7.9 W), Stop-Grant max 2.61 W, Stop-Clock
  < 0.3 W [mmx p.32 Table 13] = the 17 W budget for this socket [agents].
- Per pin: the CPU datasheet gives no per-pin current limit (say-so). The
  average is 6.5 A over 25 VCC2 pins = 0.26 A/pin; the Mill-Max 550 header
  uses pin #5503 rated 1 A per pin [mmpins p.188-189] - ample.
- Board VRM: dual-voltage mode selected by JP8 (open = dual), core voltage
  set by JP7 positions, table 2.02 to 3.9 V core [jumpers p.1]; official
  board settings: I/O 3.4 V with 2.8 / 2.9 / 3.2 V core, the MMX 233 runs at
  66 MHz x 3.5 with 2.8 V core and JP7/JP8 open [spec p.5]. So the board
  feeds both rails through the socket pins. **D1 decided 2026-10-21 by the
  operator: take interposer power from the socket rails** (see
  `plan/interposers.md`); ~0.26 A average per VCC2 pin against the 1 A
  Mill-Max 550 rating [mmpins p.189].

## R3 - Bus termination

- No VTT pin exists on Socket 7: the socket power nets are only VCC2, VCC3
  and VSS [pinmap]. There is no parallel termination to a termination rail
  as on Socket 370; the bus is single-ended TTL.
- Neither the CPU datasheet nor the MTXC requires system termination on the
  CPU bus; the CPU specs are DC levels plus leakage/capacitance (Cin 15 pF,
  Cio 25 pF, Cclk 15 pF) [mmx p.33 Table 14]. The datasheet does tell the
  system designer to respect "the signal quality restrictions imposed by
  3.3 V buffers" and to simulate [mmx p.30 sec. 3.1.2.4].
- The only termination guidance in the manuals is for debugger fan-out:
  series termination at the driver when TDO/PRDY/INIT/RESET also feed a
  debug port [devman p.15-5].
- Interposer: no termination network; keep the added capacitance to the
  listed 15-25 pF class, byte lanes length-matched (T8).

## R4 - Straps and sideband

BF[1:0] set the bus:core ratio, sampled at RESET and fixed until the next
non-warm (>= 1 ms) reset [mmx p.15]. BF1 has an internal pull-up and BF0 an
internal pull-down [mmx p.25 Table 5]; 2/7 = 233 MHz at 66 MHz bus, floating
BF = 1/2 default [mmx p.23 Table 3]; external resistor limits: pull-down
<= 500 ohm, pull-up <= 2.2 k [ap579 p.10]. The board drives BF via multiplier
jumpers JP9 (MMX 233 = all open) [spec p.5].

`fmb` is Intel's design guide for the 430HX PCIset; its CPU-side rules are
the Socket 7 UP wiring checklist and carry over to the 430TX (identical CPU
interface; the PIIX3-specific bullets are marked). The TX-specific guide is
not in the repo (say-so).

| pin | signal | what the docs say | proposed handling |
|---|---|---|---|
| X34, Y33 | BF1, BF0 | ratio straps, board JP9 [spec p.5]; internal pull-up / pull-down [mmx p.25] | route to FPGA, read at reset, select the fabric ratio; keep JP9 at the CPU's position |
| Q35 | CPUTYP | UP = strapped to VSS [devman p.4-9]; internal pull-down [mmx p.25]; FMB: NC on UP boards [fmb p.2-2] | FPGA input reads the internal-pull default = UP |
| AA05 | WB/WT# | selects S or E state, sampled with first BRDY#/NA# [devman p.4-16]; FMB pulls it up to VCC3 through 8.2 k [fmb p.2-2] | FPGA input; sampled write-back enabled |
| AG33 | A27 | also a chipset strap: state at the RESET rising edge sets the DRAM refresh rate (low = 66 MHz default, pull-up = 60 MHz detect), weak pull-down inside the chipset [fmb p.2-2] | interposer must keep A27 LOW while RESET is stretched: dedicated pull-down on the socket side, do not rely on the bus pull-ups |
| AL03, AG05 | PWT, PCD | high-active outputs [mmx p.24]; FMB: NC on UP boards [fmb p.2-2] | route to FPGA (drives them); no board load |
| AK08 | A20M# | PIIX4 open-drain output [piix4 p.26] | FPGA input, 3.3 V tolerant input, no translator |
| AA33 | INIT | PIIX4 open-drain, active high for Pentium via CONFIG1, held ~64 PCI clocks [piix4 p.26]; INIT high at RESET falling edge = BIST [devman p.4-12] | FPGA input; accept INIT as reset pulse of the fabric |
| AN07 | FLUSH# | low at RESET falling edge = tristate test mode [devman p.4-10]; FMB: pulled up to VCC3 through 8.2 k [fmb p.2-2] | keep the pull-up; the parked interposer never enters test mode; driver on the board: NM6 |
| Y35 | FRCMC#1 | sampled at RESET falling edge = checker mode; FRC unsupported on MMX [devman p.4-11, p.4-15]; FMB: pulled up to VCC3 through 8.2 k [fmb p.2-2] | pulled high, never assert |
| Q05 | FERR# | CPU output, PIIX4 input, drives IRQ13 [piix4 p.26] | FPGA output, active low; pull-up = inactive, safe |
| AA35 | IGNNE# | PIIX4 open-drain, gated by FERR# [piix4 p.26]; FMB (HX, PIIX3): 4.7 k pull-up [fmb p.2-3] | FPGA input |
| AB34, V34 | SMI#, STPCLK# | PIIX4 open-drain [piix4 p.27]; CPU inputs have internal pull-ups [mmx p.25]; FMB (HX, PIIX3): 4.7 k pull-ups [fmb p.2-3] | FPGA inputs; idle high is safe |
| AD34, AC33 | INTR/LINT0, NMI/LINT1 | PIIX4 open-drain interrupt outputs [piix4 p.25]; FMB (HX, PIIX3): 4.7 k pull-ups [fmb p.2-3] | FPGA inputs |
| H34, J33, L35 | PICCLK, PICD0, PICD1 | APIC serial interface [devman p.4-14]; PICCLK and PICD0 internal pull-up, PICD1 internal pull-down [mmx pp.25-26]; FMB: left NC in UP designs [fmb p.2-2]; PICD1 (APICD1) high at reset = secondary role [fmb p.4-5] | no board net expected: leave to the internal pulls (PICD1 pull-down = primary) |
| V04, Z34 | AHOLD / PEN# | AHOLD from MTXC; PEN# parity-enable for machine check [devman p.4-14]; PEN#: FMB pulls it up to VCC3 through 8.2 k [fmb p.2-2] | FPGA inputs |
| AB04, W03 | HOLD, EWBE# | FMB ties the processor HOLD and EWBE# pins directly to GND [fmb p.2-2] | read the board (NM6): if tied, HLDA is unused (it is on the FMB NC list) and the fabric must not wait on EWBE# |
| Q03, R04, S03, S05 | PM0/BP0, PM1/BP1, BP2, BP3 | high-active breakpoint/perf outputs, reset default = performance monitoring [devman p.4-8]; FMB: NC on UP boards [fmb p.2-2] | route to FPGA for the future core; nothing on the board |
| AC05, AC35 | PRDY, R/S# | Intel debug port pair [devman p.4-14]; R/S# internal pull-up [mmx p.25]; FMB: NC on UP boards [fmb p.2-2] | no board net; leave pulled |
| AE35 | D/P# | defined only for dual processing [devman p.4-9]; FMB: NC on UP boards [fmb p.2-2] | keep pulled high, unused in UP |
| AE03, AD04, AA03, AC03 | PBREQ#, PBGNT#, PHIT#, PHITM# | dual-processor pins, all internal pull-ups [mmx p.26 Table 7]; FMB: left NC in UP designs [fmb p.2-2] | inactive high in UP, safe |

## R5 - Bus clock

- Single-ended CLK on pin AK18 [pinmap]; TTL levels required, 3.3 V tolerant
  on the MMX part; and CLK must start toggling within 150 ms after VCC is
  valid (reliability) [devman p.4-9]. The board clock runs independently of
  the interposer, so this is satisfied by never gating it.
- Frequencies: CPU supports 1/3, 2/5, 2/7 ratios up to 66 MHz bus; 233 MHz
  needs 66 MHz x 2/7 [mmx p.23 Table 3]. Board jumpers JP11 select
  50 / 55 / 60 / 66 / 75 / 83 MHz [spec p.5, jumpers p.1]; the MMX 233
  setting is 66 MHz [spec p.5].
- The board clock generator is an ICS9169C-27: the CPU output swings from
  ground to the VDDC/VVOH rail, which may be any voltage 3.0 to 5.5 V
  [ics p.5]. Intel's FMB lists CLK among the P55C inputs that are not 5 V
  tolerant [fmb p.2-2], so a rules-following board swings at most ~3.5 V;
  NM5 confirms with the scope before wiring the clock direct into a 3.3 V
  bank - a > 3.465 V swing would force the clock through a translator.
- [Cv] feed CLK into N9 = CLK1p (bank 3B, clock-capable input) [cvcsv],
  bank powered at 3.3 V LVTTL [cvds p.19 Table 15]; bank's 3.3 V support to
  be confirmed at T5 (same ball as the socket 3 pilot, clock direction is
  input-only here too).
- [Ti] use a clock-capable HVIO (3.3 V) ball, e.g. A8 = GPIOR_P_22_CLK13_P
  [ticsv]; HVIO 3.3 V LVTTL and 200 Mbps toggle [tids p.85 Table 64, p.88
  Table 73]. Do not use the GPIOL/HSIO clock pins (1.8 V banks) for a 3.3 V
  clock. 66 MHz is far below both limits.

## R6 - Reset and configuration

- Board reset: PIIX4 drives CPURST (open drain; active high for Pentium per
  CONFIG1), negated at the earliest 2 ms after PWROK; PWROK means power and
  PCICLK stable for at least 1 ms [piix4 pp.26, 39]; RSTDRV to the ISA bus
  negates after PWROK [piix4 p.20]; PCIRST# negates >= 1 ms after PWROK
  [piix4 p.17]; system reset logic in sec. 8.11 [piix4 p.189].
- CPU requirement: RESET held active a minimum of 1 ms after VCC and CLK are
  valid at power-up (t39) [mmx p.36 Table 15]; FLUSH#, FRCMC# and INIT are
  sampled on the RESET falling edge [devman p.4-15].
- [Cv] boot time from repo: POR delay selectable via MSEL, standard 100-300
  ms, fast 4-12 ms [cvds p.69 Table 55]; nCONFIG high to first DCLK >= 1.506
  ms (tCF2CK) [cvds p.71 Table 58]; AS mode DCLK defaults to the internal
  12.5 MHz oscillator [cvhb 7-19]; load time = rbf size x (DCLK period /
  bits per cycle), about 80 ms per megabit at AS x1 12.5 MHz [cvhb 7-23];
  CONF_DONE to user mode 175-437 us [cvds pp.74-75 Table 60]. The rbf size
  of a real design comes from Quartus (T6).
- [Ti] power-up waits 4.5 ms after the supplies [tids pp.76-77], tDMIN 32 us
  after CRESET_N release [tids pp.99-101]; configuration time = bitstream
  size / (CCK x bus width), Ti180 bitstream at most 50,096,640 bits
  [tian033 pp.4-5] - tens to hundreds of ms at 10 MHz CCK.
- Both FPGAs boot far past the board's few-ms CPURST, and the CPU needs its
  straps and a clean 1 ms+ reset after CLK/VCC [mmx p.15]. **Proposed
  handling (input to T3/T6): stretch the CPU-side reset.** Gate the socket's
  RESET (AK20) as `cpu_reset = CPURST OR NOT done` ([Cv] CONF_DONE, [Ti]
  open-drain CDONE with external pull-up [tids p.104]). The chipset and the
  rest of the board boot unimpeded [piix4 p.189]; the interposer releases
  the CPU once configured, with FLUSH# and FRCMC# already high (their
  pull-ups, R4) and BF/CPUTYP stable from the board jumpers. CPURST is
  open-drain and Intel's FMB pulls it up to 3.3 V through 330 ohm (HX/PIIX3
  rule) [piix4 p.26; fmb p.2-3] - so the gate can sit directly in the 3.3 V
  domain unless the board departs from that (NM4).
- While the FPGA configures its pins float in the weak pull-up state:
  [Cv] every I/O tied to an internal 25 k pull-up, enabled once POR has
  exited and held "until the device is configured" [cvds p.18 Table 14;
  cvhb 7-4 Figure 7-1 note 1, 7-5]; [Ti] HVIO weak pull-up 25-67 k (typ
  42 k) [tids p.88 Table 74], "all the pins are in internal weak pull-up
  during configuration mode except for TCK and TDO" [tids p.104]. Socket
  side of the translator (or direct 3.3 V bank) therefore needs:

| output | active level | why the pull-up is unsafe | fix (socket side) |
|---|---|---|---|
| AJ01 BREQ | HIGH, "always driven" [mmx p.24; devman p.4-8] | fake processor bus request; no MTXC/PIIX4 consumer in their signal lists, board net unknown (NM6) | 4 k7 pull-down to VSS |
| AL17 SCYC | HIGH [mmx p.24] | fake "pipeline invalidated" flag; no MTXC/PIIX4 consumer | 4 k7 pull-down to VSS |
| Q03, R04, S03, S05 PM0/BP0, PM1/BP1, BP2, BP3 | HIGH [mmx p.24] | asserted breakpoint/perf outputs; no documented consumer | 4 k7 pull-downs to VSS |
| AC05 PRDY | HIGH = ready (idle high) [devman p.4-14] | pull-up equals idle | none |
| AL03, AG05 PWT, PCD | HIGH [mmx p.24] | conservative cache hints, no MTXC consumer | none |
| AL01 VCC2DET# | LOW; "the P55C will always drive VCC2DET low" as its signature [mmx p.24; fmb p.2-1] | while parked the pull-up shows "not a P55C": harmless if the board does not sense the pin (its VRM is jumper-set [jumpers p.1]), otherwise it could hold off the core rail | drive LOW from the FPGA once configured; NM6 check for a sense net |
| ADS#, ADSC#, LOCK#, SMIACT#, HIT#, HITM#, PCHK#, APCHK#, FERR#, IERR#, TDO | LOW | pull-up = inactive | none |
| A[31:3], D[63:0], DP[7:0], BE[7:0]# | data/address | no cycle exists while RESET is stretched and ADS# is pulled high | none, **except A27**: the chipset samples A27 at the RESET rising edge for the DRAM refresh rate, so give A27 its own pull-down (R4) |

  CPU-input side: FLUSH# pull-up (R4 test-mode trap); PEN# and WB/WT# keep
  whatever the board provides (NM6); HOLD-type inputs of the interposer see
  MTXC outputs, no conflict.

## Open items (operator)

Resolved from the Intel FMB checklist [fmb] (HX rules; TX-specific guide not
in the repo): CPURST pull-up = 330 ohm to 3.3 V [fmb p.2-3]; pull-ups on
FRCMC#, FLUSH#, WB/WT#, AP, PEN# (8.2 k to VCC3) [fmb p.2-2] and SMI#,
STPCLK#, INTR#, NMI, IGNNE# (4.7 k) [fmb p.2-3]; PICCLK/PICD, PM/BP, SCYC,
CPUTYP, D/P#, PRDY, R/S#, PWT, PCD, HLDA, IERR#, PCHK#, APCHK# = NC in UP
designs [fmb p.2-2]. What stays open is only what the FMB rules cannot
settle about this specific board:

- **NM4** scope CPURST power-on pulse length on MB-8500TTD, and confirm it
  matches the FMB pull-up (330 ohm to 3.3 V): if the board departs to 5 V,
  the reset-stretch gate moves behind a translator.
- **NM5** scope CPU CLK (AK18) amplitude: the FMB lists CLK among the P55C
  inputs that are NOT 5 V tolerant [fmb p.2-2], so a correct board swings
  <= ~3.5 V; confirm before wiring the clock direct into a 3.3 V bank.
- **NM6** three board checks: are the processor HOLD and EWBE# pins tied to
  GND as the FMB prescribes [fmb p.2-2]? who drives FLUSH# (the FMB only
  prescribes its pull-up)? is there any VCC2DET# sense logic on the VRM?
- **[Cv]** exact total configuration time: needs the design's rbf size from
  Quartus at T6; formula and default DCLK are in the repo [cvhb 7-19, 7-23].
