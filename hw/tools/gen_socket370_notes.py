#!/usr/bin/env python3
"""Generate hw/common/socket370_notes.md (plan/interposers.md task T2, socket 370).

One file for both socket 370 variants (socket370-cyclonev, socket370-ti180);
per-FPGA answers are marked. Page numbers are the printed pages of the PDFs.
"""
import csv
import collections
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "hw" / "common" / "socket370_notes.md"

rows = list(csv.reader((ROOT / "sockets/kicad/pinmaps/pga370_coppermine.csv").open()))[1:]
g = collections.Counter(r[4] for r in rows)
pwr = collections.Counter(r[3] for r in rows if r[4] == "Power/Other")
assert g["Power/Other"] == 192
assert pwr["VCCCORE"] == 74 and pwr["GND"] == 77 and pwr["VTT"] == 15 and pwr["VREF"] == 8

CONTENT = """# Socket 370 notes - VT82C694X (Apollo Pro 133A) + VT82C686B board

T2 of `plan/interposers.md`. Covers variants `socket370-cyclonev` (5CEBA9/5CEFA9
F23C8N) and `socket370-ti180` (TI180G400C3); answers tagged **[Cv]** or **[Ti]**
are FPGA-specific, all others are common. Page numbers are the printed pages of
the cited PDFs (footers checked: PDF page = printed page for [p3], [clk],
[vrm]; for [nb] and [sb] printed = PDF page - 6).

The board has no schematic or datasheet in the repo (photo + BIOS dump only);
the chipset die closest to the target 694X with documentation on disk is the
VT82C694T Apollo Pro 133T north bridge [nb], so chipset-side statements are
what the 694T documents. Decisions taken (operator, 2026-10-20): D3 = level
translators on every CPU net; Coppermine-class AGTL+ 1.5 V personality only
(no Tualatin branch); VCCCORE ceiling 1.7 V; supported FSB set 66/100/133
MHz per [agents]. The interposer's bus personality is the one in [agents]:
P6 host bus, AGTL+, the Coppermine-class Pentium III for the PGA370 socket
[p3].

Sources:

| tag | file |
|---|---|
| p3 | sockets/socket370/pentium3_pga370_245264-008.pdf |
| nb | sockets/socket370/via_vt82c694t_datasheet_1.00.pdf |
| sb | sockets/socket370/via_vt82c686b_datasheet.pdf |
| clk | sockets/socket370/board/ics94241_clock_generator.pdf |
| vrm | sockets/socket370/board/isl6524_vrm_controller.pdf |
| mm | sockets/parts/mill-max_catalog_metric.pdf |
| pinmap | sockets/kicad/pinmaps/pga370_coppermine.csv |
| cvds | FPGAlist/CycloneV_A9/docs/cv_51002_device_datasheet.pdf |
| cvpcg | FPGAlist/CycloneV_A9/docs/pcg-01014_pin_connection_guidelines.pdf |
| cvhb | FPGAlist/CycloneV_A9/docs/cv_5v2_device_handbook_vol1.pdf |
| cvcsv | FPGAlist/CycloneV_A9/pins/5ceba9_f484.csv |
| tids | FPGAlist/Ti180_G400/docs/ti180_datasheet.pdf |
| tian033 | FPGAlist/Ti180_G400/docs/an033_configuring_titanium.pdf |
| ticsv | FPGAlist/Ti180_G400/pins/ti180g400.csv |
| plan | plan/interposers.md |
| agents | AGENTS.md |

Balls are those of `pinmap` (370 rows counted from the file): 129 AGTL+ I/O, 9
AGTL+ Input (BPRI#, DEFER#, TRDY#, RESET#, RS[2:0]#, RSP#), 1 AGTL+ Output
(PRDY#), 11 CMOS Input, 3 CMOS Output (FERR#, IERR#, THERMTRIP#), 2 APIC I/O,
1 APIC Clock (PICCLK), 1 System Bus Clock (BCLK), 5 TAP, 192 Power/Other, 16
Reserved. Inside the Power/Other rows: rails 74 VCCCORE, 77 GND, 15 VTT, 8
VREF, one each VCC1.5 / VCC2.5 / VCCCMOS; straps/analog BSEL x2, CLKREF,
CPUPRES#, EDGCTRL, PLL x2, RTTCTRL, SLEWCTRL, THERMDP, THERMDN, VID[3:0].
Datasheet prose says "75 VCCCORE" power pins [p3 17] but the processor's own
pin listing (Table 40, [p3 73-77]) has 74, same as `pinmap`; recount against
Table 40 before the T4 symbol is drawn. Group lists are Table 3 + Table 4
[p3 23-24]; directional summary Tables 43-46 [p3 92-94]. Bus signals are
written D[63:0]#, A[35:3]#, DEP[7:0]#, REQ[4:0]#, RS[2:0]#, AP[1:0]#,
BP[3:2]#, BPM[1:0]#, PICD[1:0], BR[1:0]#, VID[3:0], PLL[2:1], LINT[1:0],
BSEL[1:0] to avoid clash with ball names.

## R1 - DC levels the chipset drives onto the bus

- Host bus are AGTL+ signals: open drain, pulled to the termination rail VTT
  (1.5 V [p3 36 Table 12]), receivers compare against VREF = 2/3 VTT +/-2% generated on the
  motherboard [p3 30 Table 7 note 7, 36 Table 12 note 5, 92]. The chipset
  therefore drives/receives the bus at these same levels: the AGTL+ I/O
  group and the AGTL+ Input group (RESET#, BPRI#, DEFER#, TRDY#,
  RS[2:0]#, RSP#, BR[1:0]#) per Table 3 [p3 23].
- North bridge: the VT82C694T documents a "GTL+ compliant host bus" [nb
  features page 1], supplies its host I/O from its VTT pins and takes in a
  GTLREF reference input [nb pin list pages 7-8]; its reset to the socket is
  CPURST# plus the delayed twin CPURSTD# ("delayed 2T from CPURST#", 2T = 2
  host clocks) [nb pin descriptions page 9, and pages 15-16 pinout].
- South bridge: the VT82C686B drives the CPU interface signals INTR, NMI,
  INIT#, STPCLK#, SMI#, IGNNE#, SLP#, A20M# and a power-up CPURST, all
  open-drain, and its own datasheet says: "Connect each of the above signals
  to 4.7K ohm pullup resistors to VCC3" - idle level 3.3 V [sb pinouts page
  10]. FERR# is its 1.5 V-interface input, "APICD[1:0]" a 1.5 V interface,
  and the assembler clock for its I/O APIC is OSC 14.31818 MHz, "so OSC must
  be externally connected to the CPU I/O APIC clock input" - that is our
  PICCLK source [sb page 10].
- Level check against the CPU windows: a 3.3 V idle is above the Pentium III
  CMOS input-high window (VIH1.5 max 1.5 V [p3 34-35 Tables 10/11]; only
  BCLK, PICCLK, PWRGOOD are 2.5 V-tolerant [p3 23 note 4, 26 Table 6]) but
  within the VTT +/-2.18 V absolute maximum [p3 26]. So the original parts
  were out of DC spec on this parameter on such boards, undamaged; the
  actual pull rail and idle level on this board is unmeasured: logged
  (NM1). Neither FPGA lists GTL/GTL+ in its I/O standards (LVCMOS/LVTTL
  3.3 down to 1.2 plus SSTL/HSTL/HSUL classes [cvds 19 Table 16,
  tids 24 Table 5, 25 Table 6]), and the referenced-VREF classes sit at
  0.5 x VCCIO and above, so a GTL-class 1.0 V VREF receiver is outside the
  catalogs. That is the datasheet core of decision D3 (operator,
  2026-10-20): level translators on every CPU net - AGTL+ class referenced
  to the socket's VTT, CMOS/APIC class regenerated at the FPGA rail;
  T5 allocates balls against it.

## R2 - Power pins

- Rails [pinmap]: 74 VCCCORE = core rail; 15 VTT + 8 VREF = AGTL+
  termination and reference ("The VTT inputs must be connected to the VTT
  supply" [p3 18]); one each VCC1.5 (same rail as VTT), VCC2.5 (not used
  by this CPU [p3 90]) and VCCCMOS (out only).
- CPU-side totals: ICCCORE max 22.6 A for the 0.68A-die 1.13 GHz Coppermine
  [p3 31 Table 7], inside the 32 W socket budget of [agents].
- IVTT max 2.7 A [p3 32 Table 7]; the
  board-side per-trace termination resistors draw the matching current at
  the chipset end [p3 13]; VCCCMOS 250 mA [p3 32].
- Transients: dICCCORE/dt 240 A/us and dIvTT/dt 8 A/us [p3 32 Table 7].
- Per-pin: the Mill-Max 550 interstitial header that is our plug [plan]
  gives "Current rating (per pin): 1 A" [mm pages 140-141]; the series 550
  pin type is #5012, 3.91 mm long [mm pages 140-141]; 370 balls at 1 A
  each dwarf any single rail draw.
- Board VRM: the ISL6524 in `sockets/socket370/board/` represents the
  VRM-class controller of such boards: core PWM OUT1 driven by a VRM 8.5
  5-bit DAC, 1.050-1.825 V in 25 mV steps, +/-1% static [vrm features page
  1 and electrical page 4]; three linear regulators 1.2 V +/-3%, 1.5 V
  +/-3%, 1.8 V +/-3% [vrm page 1 and page 4]; DAC VID input low < 0.8 V /
  high > 2.0 V [vrm page 4]; separate delayed VTTPG [vrm page 1].
- Operator ceiling: VCCCORE is programmed to at most 1.7 V - inside the
  VRM 8.5 range of 1.050-1.825 V above and inside the CPU VID tables
  [p3 20-21]; the VID[3:0] strap that encodes it (a code at or below
  1.7 V) is chosen in T3 with D1.
- Which VRM parts are populated and what level feeds
  the socket VTT balls: unmeasured (NM7) and an input
  to T3/D1 - this file covers only the socket-side budget above.

## R3 - Bus termination

- "All P6 family processor system bus outputs are open drain"; on-die
  termination is provided at one end of the bus, "except RESET#", 40-130
  Ohm on the 1.5 V VTT AGTL+ platform, scaled by the RTTCTRL strap
  [p3 13, 36 Table 12, 91]; the board supplies a termination resistor at
  the chipset end of each trace [p3 13].
- RESET# is the exception without on-die termination: "RESET# must always
  be terminated to VTT on the motherboard; on-die termination is not
  provided for this signal" [p3 23 Table 3 note 6, 22, 36 Table 12 note 2].
- Unused AGTL+ inputs: "will be terminated by the processor's on-die
  termination resistors and thus do not need to be terminated on the
  motherboard" [p3 22]; RESET#, as above, is always terminated on the
  board.
- PICD[1:0] "must be pulled-up to VCCCMOS even when the APIC will not be
  used... A separate pull-up resistor must be provided for each PICD
  signal" [p3 22, 90 description].
- The board's own pull practice (686B datasheet) is 4.7 k to VCC3 for the
  CMOS-class CPU interface pins [sb page 10]; pull-ups on AGTL+ from the
  board appear in every AGTL platform as the per-trace end resistors
  [p3 13].
- Interposer rules: no pull-ups on AGTL+ nets (the die and per-trace
  resistors already are the network); interposer traces short (incident
  wave switching [p3 13]); keep the CMOS-class pull-ups the same shape the
  board has. Our FPGA's configuration-time weak pull-ups are harmless against
  an AGTL+ net: 25 k (Cyclone V [cvds 17-18 Table 14]) or 25-67 k (Ti180
  [tids 88 Table 74, 109 Table 115]) against a 40-56 Ohm termination to
  1.5 V shifts the node by (3.3 V - 1.5 V) x Rterm/(25 k + Rterm) =
  about 3 mV, inside the steady-state input window (VSS + 1.65 V) of
  [p3 34 Table 9 note 6]. Size this divider again per each net in T5; D3
  is taken (translators), so the FPGA side never lands an AGTL+ net
  directly - the VREF mismatch of [cvds 19 Table 16], [tids 24-25 Tables
  5-6] is why.

## R4 - Straps and sideband

| ball(s) | signal | dir (CPU) | behavior, cited | proposed interposer handling |
|---|---|---|---|---|
| W37 | BCLK | I | "All processor system bus agents must receive this signal"; everything keyed to its rising edge [p3 85] | to the FPGA clock network (R5); never drive it |
| AJ31, AJ33 | BSEL[1:0] | O (single driver) | the CPU drives the bus frequency code to the chipset and clock generator: "00"=66, "01"=100, "11"=133 [p3 25-26, 87]; board pulls with 1 K [p3 25-26] | drive open-drain to the design's FSB choice - supported set 66/100/133 MHz (operator) matching the clock chips' 66.67/100.00/133.33 outputs [clk pinout page 1]; while unconfigured the balls weakly pulled to our VCCIO rail present a 133 MHz request - correct only for a 133 MHz build, and the board's clock generator may latch BSEL before we leave configuration (measure: NM6); for 66/100 MHz builds force the code with an interposer strap or a pull-down sized against the board's 1 K [p3 25-26] |
| AJ37, AL35, AL37, AM36 | VID[3:0] | O (passive) | "not signals" - open circuit or short to VSS encodes the core voltage; 0.8/2.0 V DAC windows on the VRM [p3 20-21, Table 2 p.21, 92; vrm electrical page 4] | strapped opens/shorts encoded on the interposer to program VCCCORE for the rail the FPGA actually needs, at most 1.7 V (operator ceiling); exact code in T3 with D1 |
| C37 | CPUPRES# | O (active low) | "0 ... Processor core installed" - presence code [p3 88] | hard pull-down on the interposer, effective while the FPGA configures (R6) |
| AG1 | EDGCTRL | O | "adjusts the edge rate ... for previous processors and should be pulled up to VCCCORE with a 51 ohm +/-5% resistor... not used by the Pentium III processor" [p3 88] | resistor to VCCCORE on the socket side per the description; ball left undriven |
| E27 | SLEWCTRL | I (strap) | "provides AGTL+ slew rate control. The Pentium III processor samples this input when it is the driving agent" [p3 91]; resistor value lives in the platform design guide, not in the repo | receiver or fixed strap; value source: NM4 |
| S35 | RTTCTRL | I (strap) | "samples this input to sense the presence of motherboard AGTL+ termination" [p3 91]; sets the on-die RTT range [p3 36 Table 12 note 4] | receiver or fixed strap; value source: NM4 |
| AD6, E33, F18, K4, R6, V6, AK12, AK22 | VREF | I | AGTL+ receiver reference, "typically 2/3 of VTT", board dividers [p3 30 note 7, 36 Table 12 note 5, 92] | feed to all AGTL-receiver banks (or a translator, per D3) |
| Y33 | CLKREF | I | PLL reference "held to 1.25 V +/-6.5%", with the recommendation that the motherboard generate it from the 2.5 V or 3.3 V supply [p3 30 Table 7 note 15] | regenerate on the interposer from a clean rail (the board's own is unmeasured: NM5) |
| U33, W33 | PLL[2:1] | I | PLL supply inputs "connected to VCCCORE through a low pass filter that minimizes jitter" [p3 90, 18 2.3.1] | on-interposer low-pass filter |
| AD36 | VCC1.5 | I | "termination voltage for CMOS signals"; "The supply for VCC1.5 must be the same one used to supply VTT" [p3 18] | tie to the socket's VTT rail on the interposer |
| Z36 | VCC2.5 | I | "not used by the Pentium III processor" [p3 90] | leave open |
| AB36 | VCCCMOS | O | board's CMOS pull-up rail, generated inside the package from VCC1.5 for this CPU [p3 18, Figure 5 p.18] | pass through to the FPGA-side CMOS rail the chip expects (D3-dependent); what the board hangs on it: NM5 |
| AL29, AL31 | THERMDN, THERMDP | O/I | thermal diode pair "used to calculate core (junction) temperature" [p3 91] | pass-through stub; chipset pin lists don't wire it [nb]/[sb]; whether the board samples it: NM5 |
| J33 | PICCLK | I | APIC bus clock, "PICCLK should not be removed during the AutoHALT Power Down or Stop-Grant states" [p3 17]; valid-clock requirement "even when APIC will not be used" [p3 22]; 2.0-33.3 MHz timing [p3 40 Table 19] | receiver; the CPU must clock its own APIC emulation from it (OSC 14.318 MHz class [sb page 10]) |
| J35, L35 | PICD[1:0] | IO | APIC serial messages; each needs its own pull-up to VCCCMOS even when APIC unused [p3 22, 90]; timing [p3 40 Table 19] | open-drain I/O at the translator; reuse the board's pull rail (NM1) |
| M36, L37 | LINT[1:0] (INTR, NMI) | I | APIC enabled by default after Reset; with APIC disabled LINT0 = INTR, LINT1 = NMI [p3 89]; driven by the south bridge [sb pinouts page 10] | inputs through the translator; both modes implemented in RTL |
| AG33 | INIT# | I | resets integer state, "BIST" code if sampled active at the RESET# edge [p3 89] | input, board-driven; no strap |
| AG37 / AG35 / AH30 / AJ35 / AE33 / AE37 | IGNNE# / STPCLK# / SLP# / SMI# / A20M# / FLUSH# | I | 686B open-drain with 4.7 K to VCC3 [sb page 10]; FLUSH# also a reset-configuration input [p3 89, 40 Table 18]; STPCLK# state machine [p3 15-16, 91]; A20M# emulates 8086 wrap [p3 85] | translated inputs; no hazards (active-low, idle high) |
| A35 / J37 | PRDY# / PREQ# | O / I | probe ready/request debug pair [p3 89] | to the debug connector per D7; PREQ# pulled inactive when unused |
| AK32, AL33, AN33, AN35, AN37 | TAP (TCK, TMS, TDI, TDO, TRST#) | I/O | TAP group [pinmap]; see Tables 44-46 direction summary [p3 92-93] | to the debug connector per D7 |
| X4 | RESET2# | (pinmap: AGTL+ I/O; Table 3: Power/Other) | reset for compat: "does not use the RESET2# pin" [p3 90] | no connection |

Reset-configuration inputs are board-driven (A[14:5]#, BR[1:0]#, INIT#,
FLUSH#; setup 4 clocks before, hold 2-20 after the de-asserting clock [p3 40
Table 18]); "the central agent must assert the BR0# bus signal" during
power-up configuration [p3 87] - the chipset's job [nb] on an unmodified
board, no interposer risk beyond passing AGTL+ cleanly; our device reads
the same agent-id semantics (sampled active = agent 0 [p3 87]).

## R5 - Bus clock

- Frequency: the supported FSB set is 66/100/133 MHz (operator, per
  [agents]); the board's clock generator runs the code the CPU drives on
  BSEL[1:0] [p3 25-26]. The only clock chip documentation on disk, the
  ICS94241, has programmable CPU outputs at exactly 66.67/100.00/133.33
  MHz per its FS[4:0] strap table [clk pinout page 1],
  CPU domain on a 2.5 V supply ("VDDLCPU... Supply for CPU clocks 2.5 V
  nominal" [clk pinout page 4]), VOH >= 2.0 V into 12 mA, rise 0.95-1.3 ns
  measured 0.5 V to 2.0 V [clk electrical page 11]. The VT82C694T HCLK pin
  is documented for 66/100/133 MHz [nb pin description page 16], the same
  range as the BCLK tables [p3 37 Table 14].
- Single-ended branch: BCLK high time is measured above 2.0 V, low time
  below 0.5 V, rise/fall 0.4-1.6 ns [p3 37-38 Table 14 notes 8-9]; DC
  thresholds from the 2.5 V rows: VIH2.5 >= 2.0 V, VIL2.5 <= 0.7 V
  [p3 34-35 Tables 10/11]. Receiver choice:
  - **[Cv]** ball N16 = CLK6p, bank 5B [cvcsv] (3B shares VCCPD3B4A with
    3.3 V bank 4A, cvds Table 4 note 4); "in single-ended use only the
    CLKp pin feeds the PLL" [cvpcg page 2]; the owning bank is powered at
    VCCIO 2.5 V (banks take 1.0-3.465 V [cvds Table 4 page 8]); the 2.5 V
    receiver specs are VIH 1.7 V / VIL 0.7 V [cvds page 19 input table]:
    VOH 2.0 V minimum vs 1.7 V, VOL 0.4 V vs 0.7 V - both fit; other clock
    pairs are listed in [cvcsv].
  - **[Ti]** global-clock single-ended P pins: TL P11, R11, R13, T15; BL R9,
    U10, T9, T7 [ticsv]; "GPIO P resources drive the global clock network"
    [tids page 13 Table 4]; HVIO banks take LVCMOS 2.5 V (VCCIO33 2.5
    listed [tids page 24 Table 5]); bank rails themselves to 3.3 V range
    [tids page 47 Table 23]; thresholds VIH 1.7 V / VIL 0.45 V [tids page
    85 Table 64] - VOH 2.0 versus 1.7 passes; VOL 0.4 V versus 0.45 V
    leaves 50 mV [clk electrical page 11]. Differential BCLK/BCLK# (AGTL
    boards) land on HSIO differential pairs [tids page 25 Table 6]
    with the differential receiver thresholds of [p3 38 Table 15].
- The bank carrying the BCLK ball is the 2.5 V bank; T5 resolves the
  associated VCCIO grouping.

## R6 - Reset and configuration

### Reset requirements (CPU side)

- RESET# "resets all processors to known states and invalidates their L1
  and L2 caches"; power-on reset: "RESET# must stay active for at least one
  millisecond after VCCCORE and CLK have reached their proper
  specifications"; bus agents tri-state within two clocks; "a number of bus
  signals are sampled at the active-to-inactive transition of RESET# for
  power-on configuration" [p3 90]. AC: the pulse-width row is 1.00 ms
  minimum and de-assertion must be synchronous with respect to BCLK
  [p3 39 Table 16 note 6], with A[14:5]/BR/INIT-straps setup/hold as
  in R4 [p3 40 Table 18] and outputs valid 1 clock / driven 4 clocks after
  RESET# inactive [p3 40 Table 20].
- PWRGOOD: clean, monotonic to high, "followed by a 1 ms RESET# pulse"
  [p3 90], minimum inactive pulse 10 BCLK [p3 40 Table 17]; on the board
  power-good chain starts from the VRM's delayed VTTPG then core PGOOD
  [vrm page 1]; how the board routes it to the socket: board trace (NM5).
- Board reset sources: north CPURST#/CPURSTD# (CPURSTD# is "delayed 2T
  from CPURST#" [nb pages 9 and 15-16]); the south bridge has its own
  CPURST "asserts CPURST to reset the CPU during power-up" [sb page 10].
  Which net reaches the socket: NM1.

### What the FPGA pins do while unconfigured

- **[Cv]** the I/O buffers present weak pull-ups (25 k for VCCIO
  3.3/3.0/2.5 [cvds pages 17-18 Table 14]) that are active before and
  during configuration; nCONFIG low tri-states the I/O [cvpcg page 4];
  POR holds the I/O tri-stated until user mode [cvhb AS chapter]..
- **[Ti]** user pins are "input tri-state with weak pull-up" during reset
  and configuration, value 25-67 k typical 42 k [tids pages 88 Table 74 and
  109 Table 115]; "all the pins are... internal weak pull-up during
  configuration mode except for TCK and TDO" [tids page 104 Table 110].
- On AGTL+ nets this is a non-event: 25-67 k against a 40-56 Ohm board
  termination moves the node about 3%: 3 mV (computation in R3), inside the
  steady-state window [p3 34 Table 9 note 6]. The list of real hazards is
  on the CPU output side, both FPGA cases:

### CPU outputs whose pulled-up state is unsafe

| ball(s) | output | active level | why a pull-up is unsafe | fix (interposer side) |
|---|---|---|---|---|
| C37 | CPUPRES# | low | "1" reads "PGA370 socket not occupied" [p3 88] | hard pull-down, no FPGA dependency |
| AJ31, AJ33 | BSEL[1:0] | high | both weakly high = code 11 = 133 MHz request [p3 25-26 Table 5] | correct only for a 133 MHz build; for 66/100 MHz builds drive low after configuration and fit an interposer strap/pull-down sized vs the board's 1 K before the clock generator latches (measure first: NM6) |
| every other CPU output | AGTL+ I/O group, CMOS outputs FERR#/IERR#/THERMTRIP# (AC35, AE35, AH28), PRDY# (A35) | low | open drain, active low: high = inactive everywhere [p3 92 Tables 43-46, 88-91]; THERMTRIP# has the extra note "indeterminate until... RESET#... de-asserted" [p3 91] | none beyond the board's own pull-ups [p3 22]; PRDY# is debug-only |
| all remaining strap/ball nets | VID[3:0], THERMDP/N, PLL, CLKREF, RTTCTRL, SLEWCTRL, EDGCTRL | straps/supplies | defined above in R4 [p3 88-91] | soldered per R4; transistor drives only after configuration and only where needed (BSEL) |

CPU-input side is board-driven (686B open drains [sb page 10]) - the
"unconfigured-FPGA weak pull-up" contributes on the order of 3.3 V divided
by 25 k + 4.7 k: negligible against the 4.7 k to VCC3 pull-ups the board
already has.

### Configuration time vs board reset

- **[Cv]** supply ramp 200 us - 100 ms [cvds page 9]; POR 4-12 ms fast /
  100-300 ms standard [cvds page 69 Table 55]; first DCLK 1506 us after
  nCONFIG high (tCF2CK) [cvds page 71 Table 58]; Active Serial uses the
  12.5 MHz internal oscillator by default [cvhb AS chapter 7-19]; AS x1
  load time = .rbf size x (minimum DCLK period / 1 bit) [cvhb 7-23]; the
  CONF_DONE-to-initialization numbers are the AS timing rows of
  [cvds page 74 Table 60]. Exact total needs the compiled .rbf size (T6).
- **[Ti]** power-up waits 4.5 ms after the supplies [tids pages 76-77];
  tDMIN 32 us after CRESET_N release [tids pages 99-101]; configuration
  time = bitstream size / (CCK x bus width) [tian033 page 5]; Ti180 has at
  most 50 096 640 configuration bits and typical compression is about
  half [tian033 page 4 Table 1, page 5] - tens to hundreds of ms at a 10
  MHz CCK.
- Either FPGA takes "hundreds of ms" - far beyond the 1 ms RESET contract
  [p3 39 Table 16] and the north's own 2-clock CPURSTD# stretch [nb pages
  9 and 15-16]. Proposed handling (input to T3/T6), same shape as the
  pilot: gate the RESET# the chipset drives with config-done:
  `seen_reset = board_reset OR NOT config_done` (CONF_DONE for [Cv];
  CDONE is open-drain with a required external pull-up for [Ti] [tids
  page 104 Table 110]); during configuration our AGTL+ outputs are
  open-drain-high-Z so no net is actively driven, then we release the
  chipset's SYS such that our CPU looks reset and the first de-assertion
  is BCLK-synchronous [p3 39 Table 16]. Board tolerance for a CPU holding
  this class of reset for hundreds of ms is an assumption to verify: Open
  item below.

## Open items (operator)

Board facts the repo cannot answer - "NMn" items, measured on the real
VT82C694X + VT82C686B board:

- **NM1** Which net resets the socket (north CPURST#/CPURSTD# vs south
  CPURST), the boot reset pulse length, and the pull rail behind the
  4.7 K CPU-interface pull-ups [sb page 10] (VCC3 3.3 V as printed?  the
  CPU's 1.5 V window says otherwise; see R1).
- **NM2** Board's BCLK: identify the clock chip, single-ended vs
  differential output mode and level [clk page 1] (ICS94241 is the in-repo
  candidate).
- **NM3** Board-side termination resistors on the AGTL+ net set: present
  per trace or die-only termination? sizes? [p3 13, Table 7 note 10 p.32].
- **NM4** Strap values for RTTCTRL and SLEWCTRL come from the platform
  design guide, not in this repo [p3 36 Table 12 note 4, 91]: get them or
  probe what the 694X board ties.
- **NM5** VCCCMOS consumers, THERMDP/DN wiring, PWRGOOD chain: board
  trace [p3 18 p.18, 91; vrm page 1].
- **NM6** When the board's clock generator latches BSEL[1:0] relative to
  our configuration window, and the resistors (1 K per [p3 25-26]) - for
  a 66/100 MHz build decide whether the idle-133 window during
  configuration is harmful and size any strap/pull-down.
- **NM7** Populated VRM rails and measured VTT (assumed 1.5 V AGTL+,
  Coppermine class): this decides which corner of
  `hw/<variant>/power.md` T3 writes and the VID code to strap
  (ceiling 1.7 V) [vrm page 1].

Decided (operator, 2026-10-20): D3 = level translators on every CPU net;
Coppermine AGTL+ 1.5 V personality only; VCCCORE ceiling 1.7 V; FSB set
66/100/133 MHz. Still open per `plan/interposers.md`: D1 (power source -
a socket-fed VCCCORE plan must respect the 1.7 V ceiling), D4 (module
RAM), D5 (layers), D6 (outline/height per M1, M2), D7 (debug connector).
"""

assert "[Cv]" in CONTENT and "[Ti]" in CONTENT

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(CONTENT)
print(f"wrote {OUT} ({len(CONTENT.splitlines())} lines), power balls: "
      f"VCCCORE {pwr['VCCCORE']} GND {pwr['GND']} VTT {pwr['VTT']} VREF {pwr['VREF']}")
