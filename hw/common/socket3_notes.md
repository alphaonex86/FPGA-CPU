# Socket 3 notes - Biostar MB-8433UUD-A, UMC UM8881F + UM8886BF

T2 of `plan/interposers.md`. Covers variants `socket3-cyclonev` (5CEBA9/5CEFA9
F23C8N) and `socket3-ti180` (TI180G400C3); answers tagged **[Cv]** or **[Ti]**
are FPGA-specific, all others are common. Page numbers are printed pages of the
cited PDFs (in `intel_dx4_write_back_enhanced.pdf` the PDF page is the printed
page + 4).

Sources:

| tag | file |
|---|---|
| dx4 | sockets/socket3/intel_dx4_write_back_enhanced.pdf |
| am5x86 | sockets/socket3/amd_am5x86_19751C.pdf |
| umc | sockets/socket3/umc_um8881_um8886_reverse_engineered_2026-02-16.pdf |
| impl | sockets/socket3/486_common_socket_implementation.pdf |
| board | sockets/socket3/board/biostar_mb-8433uud_manual_v2.pdf |
| pinmap | sockets/kicad/pinmaps/am5x86_pga168.csv |
| mmpins | sockets/parts/mill-max_catalog_metric.pdf |
| cvds | FPGAlist/CycloneV_A9/docs/cv_51002_device_datasheet.pdf |
| cvpcg | FPGAlist/CycloneV_A9/docs/pcg-01014_pin_connection_guidelines.pdf |
| cvcsv | FPGAlist/CycloneV_A9/pins/5ceba9_f484.csv |
| tids | FPGAlist/Ti180_G400/docs/ti180_datasheet.pdf |
| tian033 | FPGAlist/Ti180_G400/docs/an033_configuring_titanium.pdf |
| ticsv | FPGAlist/Ti180_G400/pins/ti180g400.csv |
| cvhb | FPGAlist/CycloneV_A9/docs/cv_5v2_device_handbook_vol1.pdf |
| pq | sockets/parts/sharp_pq30rv21.pdf |
| agents | AGENTS.md |

Pin names A1..S17 are PGA pins of `pinmap` (168 rows: 114 signal, 51 power,
3 internal-NC, counted from the file). Bus signals are written as A[31:2],
D[31:0], BE[3:0], DP[3:0] to avoid clash with pin names.

## R1 - DC levels the chipset drives onto the bus

- The UM8881F host bridge and UM8886BF I/O bridge are powered from +5 V
  (HB pins "VCC5V - Power supply +5V" [umc p.12-14]; IBC pins "VCC - Power
  supply +5V" [umc p.26]). Everything the chipset drives to the socket is
  therefore a 5 V output: PHOLD (E15), BOFF# (D17), EADS# (B17), KEN# (F15),
  RDY# (F16), BRDY# (H15) [umc p.16], A20M# (D15), NMI (B15), INTR (A16),
  SMI# (B10), STPCLK# (G15), IGNNE# (A15), CPU reset CPURSTO (C10)
  [umc p.26-27], CPU clock from the UM9515-01 PLL through a 74F244 line
  driver [board p.17].
- The original CPUs take it: DX4 input VIL <= +0.8 V, VIH >= 2.0 V (max
  VCC5+0.3), pin absolute max -0.5 V to VCC5+0.5 V with VCC5 = 5 V [dx4
  p.30-31, Tables 16, 18]; Am5x86 VIH 2.0 V to VCC+2.4 V [am5x86 p.58]. So
  yes: the Socket 3 bus is 5 V, on both the 3.45 V and the 5 V Vcc jumper
  setting (the jumpers only set the CPU core rail [board p.19]).
- Neither FPGA tolerates 5 V: Cyclone V DC input voltage is rated -0.5 to
  3.6 V and maximum allowed AC input is 3.8 V at 100% of high time, VCCIO
  max 3.465 V [cvds p.9 Table 5, p.6 Table 3, p.8 Table 4];
  Ti180 absolute maximum VCCIO33 is 3.63 V and max current through any I/O
  pin is 10 mA [tids p.82 Table 61].
- **Decision D2 (taken by the agent on 2026-10-19, delegated by the
  operator): the interposer uses level translators on every CPU net; there
  is no direct-3.3 V option. The board Vcc jumpers stay at 3.45 V** (the
  3.3 V parts' window; the jumpers only set the CPU core rail and do not
  change anything the chipset drives, [board p.19]).
- Board pull-ups seen during the chipset trace are tied to VCC5V (4 k7 on
  LRDY#/LDEV# [umc p.16], 470 R on REFRESH# [umc p.14]).

## R2 - Power pins

- Original CPU rails: one core rail. Am5x86 VCC = 3.3 V +/-0.3 V [am5x86
  p.58]; Write-Back Enhanced IntelDX4 VCC = 3.3 V +/-0.3 V [dx4 p.30 Table
  17]. The DX4 adds VCC5 on pin J1, a 5 V reference input for its
  5 V-tolerant I/O buffers only [dx4 p.23 Table 8 sheet 8]; on the Am5x86
  that pin is internal NC [pinmap]. VOLDET (S4) tells the board the part is
  a 3 V CPU [dx4 p.23]; the Am5x86 ties VOLDET internally to VSS [am5x86
  p.9 note 1, p.17].
- Socket power pins [pinmap]: 23 VCC, 28 VSS.
- CPU current: DX4-100 ICC max 1300 mA at 3.3 V (thermal design) and 1450 mA
  at 3.6 V (supply selection) [dx4 p.32 Table 19], i.e. 4.3 W, the budget
  figure in [agents]. Am5x86-133 ICC max 931 mA [am5x86 p.58] = 3.1 W.
- Interposer header current limit: Mill-Max 551 series with pin #5503
  [mmpins p.140], "Current rating (per pin): 1 A" [mmpins p.141] - 23 pins
  give a far higher margin than any CPU draw.
- Board VRM: Sharp PQ30RV21 variable low-dropout regulator sets the socket
  VCC rail to 3.45, 4 or 5 V by jumpers JP37/JP39/JP36 [board p.17, p.19].
  Datasheet in repo [pq]: absolute maximum output current 2 A
  (PQ30RV2/PQ30RV21), input voltage max 35 V, dropout max 0.5 V, power
  dissipation 18 W only with an infinite heatsink [pq p.2]. 2 A at 3.45 V
  = 6.9 W, above the 4.3 W the DX4-100 draws, so the board VRM can feed
  the interposer within the original-CPU budget; the pilot leaves the
  jumpers at 3.45 V (the 3.3 V parts' window).
- Consequence for the interposer regulator input: whatever the Vcc jumper is
  set to, 3.45-5 V; the board also needs our bus outputs to reach its TTL
  VIH (2.0 V) - 3.3 V translator outputs satisfy that; only the CPU clock
  input needed 4.4 V but we never generate it (R5).

## R3 - Bus termination

- The Socket 3 bus is unterminated single-ended TTL: the DX4 output specs are
  resistive (VOL 0.45 V at IOL 4-5 mA, VOH 2.4 V at IOH -2 mA), with no
  series/parallel termination requirement anywhere in [dx4 p.30-31]. Nothing
  like the Socket 370 AGTL+ on-die termination - no VTT rail exists here.
- What the CPU expects is only weak logic-level biasing:
  DP[3:0] "must be connected to VCC through a pull-up resistor in systems
  that do not use parity" [dx4 p.16]; STPCLK# "must be pulled high via a
  10 k pull-up" [dx4 p.19]; RESERVED# (C11 on the DX4) needs its own 10 k
  pull-up, not shared [dx4 p.23]; CLKMUL needs 10 k pull-up when tied high
  [dx4 p.23]. Several CPU inputs have internal pulls (EADS#, KEN#, BS16#,
  BS8#, IGNNE#, TCK/TMS/TDI, CLKMUL: pull-up; AHOLD: pull-down; HOLD: none)
  [dx4 p.19-21].
- Board practice matches: discrete pull-ups to VCC5V on control lines
  [umc p.14, p.16].
- Interposer: no termination. Keep the translator pins close to their pads;
  provide the pull-ups the CPU datasheet demands on our side of the
  translators, and define HOLD externally (it has no internal pull-down
  [dx4 p.19]).

## R4 - Straps and sideband

What the board does comes from the chipset trace and the board manual; the
CPU-side behaviour from the datasheets. "NM" = needs measurement/trace on the
real board (see Open items).

| pin | signal | dir (CPU) | board behavior, cited | proposed interposer handling |
|---|---|---|---|---|
| C3 | CLK | I | UM9515 PLL -> 74F244 buffer, FSB 20-83 MHz by jumpers JP15/16/17 [board p.17, 19] | read through translator, see R5 |
| R17 | CLKMUL | I | multiplier select jumpers JP45 [board p.19]; DX4: internal pull-up, 10 k when high; 2x if low, 3x if high [dx4 p.23]; must be grounded for AM486DX2 [impl p.2 note 8] | no resistor (the FPGAmotherboard ties R17 to GND, plan/interposers.md); the FPGA weak pull-up (25 k [cvds p.18 Table 14]) stands in for the DX4 internal one; FPGA reads it after config and sets its core multiplier (never drives) |
| B13 | WB/WT# | I | set by the CPU-type jumpers/resistor packs JP10/JP11/JP31/JP46, RN11-RN15 [board p.20]; chipset L1 write policy register 51.02 [umc p.17] | sampled like at reset: must be valid >= 2 clocks before/after our stretched RESET de-assertion [dx4 p.23]; FPGA reads after config; exact board network = NM3 |
| B12 | CACHE# | O | routed to the HB CACHE# input through board jumper J12/J13 [umc p.12] | FPGA drives the WB-Enhanced CACHE# output [dx4 p.22]; jumper must be in the DX4/P24D position |
| C17/D16 | BS16#/BS8# | I | not on the UMC HB (no bus-size pins in the pin list) [umc p.12-16] | leave at internal-pull-up level (32-bit bus); FPGA input |
| C11 | UP (Am5x86) | I | sampled in the clock before RESET falls; low = outputs tri-state immediately (CPU parked) [am5x86 p.17] | 10 k pull-up on the FPGA side of the switch; FPGA input; treat low as "stay parked" |
| C11 | RESERVED# (DX4) | I | - | on the DX4 this pin MUST have its own 10 k pull-up [dx4 p.23]; the Am5x86-style UP handling satisfies it |
| J1 | VCC5 (DX4) / NC (Am5x86) | I | DX4: 5 V reference for the tolerant buffers [dx4 p.23]; common-socket boards jumper it NC/VCC/VCC5 by CPU type [impl p.2-3]; on this board NM3 | leave unconnected (Am5x86 mode); our translators supply their own rails |
| S4 | VOLDET | O | lets the system detect a 3 V vs 5 V CPU [dx4 p.23]; Am5x86 ties it to VSS [am5x86 p.9, p.17]; what MB-8433UUD-A does with it: not documented in repo | tied to VSS on the interposer = "3 V part", exactly the Am5x86; the FPGAmotherboard only powers VCORE once it reads S4 low (plan/interposers.md) |
| B10 | SMI# | I | driven by UM8886BF pin 32 [umc p.26] | FPGA input; SMM implemented later (optional) |
| C12 | SMIACT# | O | UM8886BF pin 50 input [umc p.27] | pull-up-safe output |
| C10 | SRESET | I | the chipset's CPU reset: CPURSTO, UM8886BF pin 29, "CPU reset (486 pin C10 SRST)" [umc p.26]; internal pull-down [am5x86 p.17] | reset input, ORed with the config-done gate (R6) |
| C16 | RESET | I | not traced on this board; CPURSTO documented only for C10 [umc p.26]; RSTDRV is "reset to rest of system ... excluding CPU" [umc p.29] | treat as second reset input with a 100k pull-down on the interposer (weak: the FPGAmotherboard holds RESET asserted with only 8.2k to VCORE, plan/interposers.md); verify on the board = NM2 |
| G15 | STPCLK# | I | UM8886BF pin 33 STCK# [umc p.26]; CPU needs the 10 k pull-up [dx4 p.19] | board keeps its pull-up; translator passes it through |
| Q15 | BREQ | O | active HIGH, "never floated" [dx4 p.19]; board net near jumper J21 [umc p.12], exact destination NM3 | 4 k7 pull-down on the socket side (R6) |
| D15 | A20M# | I | driven by UM8886BF pin 31 [umc p.26]; CPU samples it HIGH at the falling edge of RESET [dx4 p.21] | FPGA input, nothing to add |
| A15 | IGNNE# | I | driven by UM8886BF pin 28 [umc p.26] | input, internal pull-up [dx4 p.22] |
| C14 | FERR# | O | UM8886BF pin 25 input [umc p.26] | pull-up-safe output |
| A16 / B15 | INTR / NMI | I | UM8886BF pins 37 / 30 [umc p.26] | FPGA inputs |
| A10 | INV | I | snoop invalidation input of WB-Enhanced mode [dx4 p.22]; the board feeds it from the cache-configuration jumper network (the HB W/R network "goes to jumpers (J15 INV, J17)") [umc p.16]; full network NM3 | FPGA input; implement WB snoop protocol |
| C15 | FLUSH# | I | not documented in the repo | FPGA input with pull-down until traced (NM3); FLUSH needs one clock low [dx4 p.20] |
| E15 | HOLD | I | HB pin 185 PHOLD output [umc p.16] | FPGA input; define at translator (no internal pull-down [dx4 p.19]) |
| A17 | AHOLD | I | not on the HB pin list [umc p.12-16] | input, internal pull-down [dx4 p.20], safe |
| B17 | EADS# | I | HB pin 186 output [umc p.16] | input, internal pull-up [dx4 p.20] |
| F15 | KEN# | I | HB pin 187 output [umc p.16] | input, internal pull-up [dx4 p.20] |
| F16 / H15 | RDY# / BRDY# | I | HB pins 188 / 189 outputs [umc p.16] | inputs, driven by board |
| D17 | BOFF# | I | HB pin 184 output [umc p.16] | input, driven by board |
| L15 / J17 | PWT / PCD | O | HB PPCD input pin 205 [umc p.16]; page cacheability outputs [dx4 p.20] | pulled-up state = write-through / cache-disable: conservative, safe |
| A5, H3, F1, N3 | DP3-DP0 | IO | parity checked on the bus [umc p.16]; BIOS "Memory Parity Check - Disabled" by default [board p.21] | keep the Intel pull-ups when parity is unused [dx4 p.16], on the FPGA side of the switches; translators bidirectional |
| A3, B14, A14, B16 | TCK/TMS/TDI/TDO | I/O | JTAG pins, internal pull-ups [dx4 p.21] | to the debug connector, per D7 |

## R5 - Bus clock

- Frequency: board jumpers select FSB 20/25/33/40/50/60/66/83 MHz from a
  UM9515-01 PLL (14.3 MHz crystal), buffered to CPU/ISA/PCI by a 74F244
  [board p.17, p.19]. The DX4-100 runs at max 33 MHz CLK, the DX4-75 at
  25 MHz [dx4 p.32-33 Tables 19-20].
- Level: 5 V TTL - a 74F244 (5 V part) drives it [board p.17]; the DX4 CLK
  input needs VIH >= VCC5 - 0.6 = 4.4 V and has AC thresholds at 2 V / 0.8 V
  [dx4 p.31 Table 18, p.33 Table 20].
- The interposer only receives the clock; it never drives CLK. Translate it
  to 3.3 V and land it on a clock-capable FPGA input:
  - **[Cv]** CLK1p, ball N9, bank 3B [cvcsv]. In single-ended use only the
    CLKp half feeds the PLL [cvpcg p.2]; every F484 bank (3A, 3B, 4A, 5A,
    5B, 7A, 8A, 9A) supports VCCIO 3.3 V [cvds p.8 Table 4]. Alternatives
    on the same clock pairs: M9 (CLK0p, 3B), or the 7A/8A pairs [cvcsv].
  - **[Ti]** global-clock-capable single-ended P pins inside the 3.3 V
    HVIO banks (TL, TR, BL, BR support VCCIO33 3.3 V [tids p.47 Table 23]):
    TL: P11, R11, R13, T15; BL: R9, U10, T9, T7 [ticsv]. GPIO P resources
    drive the global clock network [tids p.13 Table 4]; differential CCD
    pairs exist in HSIO banks 2B, 3B, 4B as fallback [ticsv]. HVIO 3.3 V
    LVCMOS VIH 2.1 V [tids p.85 Table 64] - translator output fits; 3.3 V
    LVCMOS max toggle 200 Mbps >> 83 MHz [tids p.88 Table 73].
- A 25/33/40 MHz clock is far below any limit above; the bank holding the
  clock pin must be powered at 3.3 V.

## R6 - Reset and configuration

### Reset requirements (CPU side)

- Cold reset: RESET must stay active at least 1 ms after VCC and CLK are
  valid [dx4 p.34 Table 20 note 4]; same requirement on the Am5x86 [am5x86
  p.16]. Warm RESET or SRESET pulse: >= 15 CLK [dx4 p.34], SRESET >= 15 CLK
  [dx4 p.19]. SRESET has an internal pull-down [am5x86 p.17].
- Board source: CPURSTO out of the UM8886BF (pin 29, from RSTIN# "reset
  input from power good circuitry") [umc p.26]; the length of the power-on
  pulse is not documented in the repo -> NM1, and whether C16 is also driven
  -> NM2.

### What the FPGA pins do while unconfigured

- **[Cv]** All I/O pins are "tied to an internal weak pull-up" from power-up
  onwards, and that pull-up "is enabled after the device has exited POR"
  [cvhb p.7-4 Figure 7-1 note 1]; "The user I/O pins are tied to an internal
  weak pull-up until the device is configured" [cvhb p.7-5]; value 25 k
  [cvds p.18 Table 14]; pulling nCONFIG low tri-states the I/O [cvpcg p.4].
- **[Ti]** user pins (HSIO and HVIO) are "input tri-state with weak
  pull-up" during reset and during configuration; weak pull-up 25-67 k
  (typ 42 k) [tids p.109 Table 115, p.88 Table 74]. "All the pins are in
  internal weak pull-up during configuration mode except for TCK and TDO"
  [tids p.104 Table 110].
- So while the FPGA configures, every interposer net is weakly pulled up at
  the FPGA rail. External resistors of 4 k7 or less win against 25-42 k
  internal pulls. The translator output-enables do not depend on the
  FPGA: they close as soon as the socket rail is up and stay open while it
  is down (VCORE-present detector, plan/interposers.md), so no pull-up
  back-feeds an unpowered socket rail, and the pulls below act while the
  FPGA configures.

### CPU outputs whose pulled-up state is unsafe

| pin | output | active level | why a pull-up is unsafe | fix (socket side of the translator) |
|---|---|---|---|---|
| P15 | HLDA | HIGH, and it "remains driven during bus hold" [dx4 p.19] | the HB samples it (PHLDA pin 207 [umc p.16]): the board would believe the bus was granted while no CPU is there | 4 k7 pull-down to VSS |
| Q15 | BREQ | HIGH, "never floated" [dx4 p.19] | false coprocessor/bus request toward the board FERR/IGNNE logic network [umc p.12] | 4 k7 pull-down to VSS |
| S4 | VOLDET | LOW = "3.3 V part" [dx4 p.23] | pull-up would claim a 5 V part, the opposite of the Am5x86 behaviour [am5x86 p.9] | tied to VSS |
| N15, Q16, R16, S17 | LOCK#, PLOCK#, BLAST#, ADS# | LOW | pulled high = inactive: safe, no cycle can start without ADS# | none |
| B12, A12, Q17, C12, C14 | CACHE#, HITM#, PCHK#, SMIACT#, FERR# | LOW | pulled high = cacheable-off / no snoop hit / no parity error / not in SMM / no FPU error: safe | none |
| L15, J17 | PWT, PCD | HIGH [dx4 p.20] | high = write-through, page-cache-disable: conservative | none |
| DP[3:0] (A5, H3, F1, N3) | parity | HIGH | Intel requires exactly this pull-up when parity is unused [dx4 p.16] | keep pull-ups (FPGA side) |
| A[31:2], D[31:0], BE[3:0] | bus | any | no bus cycle exists while ADS# is high and RESET is stretched | none |
| B16 | TDO | hi-Z unless clocked | safe | none |

CPU-input side: HOLD has no internal pull-down [dx4 p.19] -> pull-down at
the translator's FPGA-side input; STPCLK# pull-up exists on the board [dx4
p.19].

### Configuration time vs board reset

- **[Cv]** Boot-time budget, all from repo: supply ramp allowed 200 us to
  100 ms [cvds p.9]; POR delay after ramp, set by MSEL pins: standard
  100-300 ms, fast 4-12 ms [cvds p.69 Table 55]; after nCONFIG is released
  the first DCLK edge comes at the earliest 1.506 ms later (tCF2CK)
  [cvds p.71 Table 58]; in Active Serial mode DCLK defaults to a 12.5 MHz
  internal oscillator (configurable 12.5/25/50/100 MHz) [cvhb p.7-19];
  load time = .rbf size x (minimum DCLK period / bits per DCLK cycle)
  [cvhb p.7-23], i.e. about 80 ms per megabit at AS x1 with the default
  12.5 MHz; CONF_DONE to user mode 175-437 us [cvds p.74-75 Table 60].
  The .rbf size of a 5CEBA9 design is a Quartus output (T6); with standard
  POR the boot is easily hundreds of ms.
- **[Ti]** power-up waits 4.5 ms after the supplies [tids p.76-77], tDMIN
  32 us after CRESET_N release [tids p.99-101]; configuration time =
  bitstream size / (CCK x bus width) [tian033 p.5]; Ti180 has at most
  50 096 640 configuration bits and Efinity compresses a typical design to
  about half [tian033 p.4 Table 1, p.5] - tens to hundreds of ms at a 10
  MHz CCK.
- Either FPGA therefore boots far longer than the CPU's 1 ms reset minimum;
  one cannot count on the board's reset still being active at
  configuration-end.
- **Proposed handling (input to T3/T6): stretch the CPU-side reset.**
  Gate the CPU's C10/C16 with the board's reset: `cpu_reset = board_reset
  OR NOT done` (CONF_DONE [Cv] / open-drain CDONE with external pull-up
  [Ti], tids p.104 Table 110). The chipset boots on unimpeded (reset to the
  rest of the system is independent of the CPU's [umc p.29]); the CPU stays
  parked and tri-stated until configuration ends, then sees a clean
  de-assertion, held >= 1 ms by a trivial counter, with the strap inputs
  (WB/WT#, CLKMUL, UP, BS16#/BS8#) long stable because they come from board
  jumpers. Verify on the bench that the board tolerates a CPU held in reset
  for hundreds of ms after power-on (no BIOS-timeout behaviour - UMC BIOS
  runs from the chipset side, but this is an assumption to test).

## Open items (operator)

- **NM1** scope CPURSTO (pin C10) at power-on: length of the reset pulse on
  MB-8433UUD-A.
- **NM2** is RESET (C16) driven at all on this board? If not, keep the
  interposer's pull-down on C16 and rely on C10 (this is what an original
  Am5x86 would see too).
- **NM3** trace on MB-8433UUD-A: destination of BREQ (Q15), the WB/WT# and
  INV networks behind the CPU-type jumpers JP10/JP11/JP31/JP46 and RN11-
  RN15 [board p.20], FLUSH# (C15), and whether the J1 net carries +5 V
  (DX4 VCC5).
- **[Cv]** exact total configuration time: needs the .rbf size of the design
  from Quartus at T6; the estimation formula and default DCLK are now in
  the repo [cvhb p.7-19, p.7-23].
