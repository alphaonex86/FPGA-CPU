# Slot 1 notes - cartridge interposer (first build per D9 Cyclone V)

*S2 of `plan/slot1.md`. The connector is the 242-contact card-edge slot
"SC 242" [p2 pp 5-6]; the interposer is a full-cartridge replacement (no
on-board L2, all caches on die). The bus personality is the P6 host bus of
the Pentium II Deschutes SC 242 datasheet [p2]; the Pentium III Katmai
450/500 connector datasheet [p3s] uses the same SC242 contacts and the same
VRM 8.2 VID table, so a 2.00 V VID strap is valid for both classes.
Board classes in scope (D8): Intel 440BX (66/100 MHz), VIA Apollo Pro
133/133A (66/100/133), Intel i810 (66/100) / i820 (133). Chipset datasheets
on disk cover the 440BX host bridge [bx] and the 82810 GMCH [gmch] only;
the VIA north/south bridges and the i820 MCH were not found online
(2026-10-20, plan) - chipset claims for the 133-class boards inherit the
same AGTL+ platform text and are gated behind Open item NM1.
Page conventions: PDF page = printed page for [p2] and [p3s] (footers
checked); [gmch] printed = PDF + 'chapter-page' style (footers checked); the
PIIX4E [piix4] text layer carries no printed page numbers, so [piix4] cites
PDF pages.

Sources:

| tag | file |
|---|---|
| p2 | sockets/slot1/pentium2_350-450_sc242_24365703.pdf |
| p3s | sockets/slot1/pentium3_secc2_24445201.pdf |
| bx | sockets/slot1/board/intel_440bx_host_bridge_29063301.pdf |
| gmch | sockets/slot1/board/intel_82810_gmch_29065602.pdf |
| ich | sockets/slot1/board/intel_82801AA_ich0_29065503.pdf |
| piix4 | sockets/socket7/intel_82371ab_piix4.pdf |
| p3f | sockets/socket370/pentium3_pga370_245264-008.pdf |
| sig | hw/common/slot1_signals.csv |
| cvds | FPGAlist/CycloneV_A9/docs/cv_51002_device_datasheet.pdf |
| cvpcg | FPGAlist/CycloneV_A9/docs/pcg-01014_pin_connection_guidelines.pdf |
| cvhb | FPGAlist/CycloneV_A9/docs/cv_5v2_device_handbook_vol1.pdf |
| cvcsv | FPGAlist/CycloneV_A9/pins/5cefa9_f484.csv |
| p6man | sockets/socket370/p6_family_hardware_developers_manual_244001-001.pdf |
| plan | plan/slot1.md |
| agents | AGENTS.md |

Contacts are those of `sig` (242 rows: A1-A121, B1-B121): 138 AGTL+
buffer contacts (128 AGTL+ I/O incl. A[35:3]# x33, D[63:0]# x64, DEP[7:0]# x8,
REQ[4:0]# x5, AP[1:0]#, BP[3:2]#, BPM[1:0]# and the 12 single I/O signals; 9
AGTL+ Input = BPRI#, BR1#, DEFER#, RESET#, RS[2:0]# x3, RSP#, TRDY#; 1
AGTL+ Output = PRDY#), of which 136 carry class "bus" (PRDY# is debug,
RESET# is control), 15 control contacts (11 CMOS Input incl. TESTHI,
3 CMOS Output = FERR#, IERR#, THERMTRIP#, plus RESET#), 7 debug
(TAP x5, PREQ#, PRDY#), 2 clock (BCLK, PICCLK), 6 strap (VID[4:0] x5,
100/66#), 5 sideband (PICD[1:0], THERMDP, THERMDN, SLOTOCC#),
57 power contacts (30 GND, 19 VCCCORE,
4 VTT, 3 VCCL2, 1 VCC5), 5 EMI, 9 Reserved [sig; p2 Tables 3/35].
Signal names are written as in `sig`: A[35:3]#, D[63:0]#, DEP[7:0]#,
REQ[4:0]#, RS[2:0]#, AP[1:0]#, BP[3:2]#, BPM[1:0]#, PICD[1:0],
LINT[1:0], VID[4:0].


## R1 - DC levels the chipset drives onto the bus

- AGTL+ group (host bus): open-drain buffers pulled to the termination rail
  VTT = 1.5 V +/-9% (1.365-1.635 V), receivers compare against
  VREF = 2/3 VTT, buffer on-resistance <= 16.67 Ohm, input window
  VIL <= 0.82 V / VIH >= 1.22 V up to VTT [p2 Table 6 p24, Table 8 p25].
  On the original cartridge VREF is generated on the substrate; "other
  AGTL+ logic should use a divider to 2/3 VTT" on the board [p2 2.12 p24,
  Table 8 note 2 p25].
- Chipset side: the 82443BX host interface is a "64-bit GTL+ based Host Bus
  Interface" at 66/100 MHz [bx PDF page 11] with reference and threshold
  pins GTLREF[B:A] "GTL buffer voltage reference input" and VTT[B:A] "GTL
  threshold voltage for early clamps" [bx Table 2-9, PDF page 24]; the
  82810 GMCH documents a "64-bit AGTL+ based System Bus Interface at
  66 MHz/100 MHz" [gmch PDF page 14] with the same open-drain AGTL+ buffer
  class ("AGTL+ Open Drain AGTL+ interface signal" [gmch PDF page 19]).
- CMOS group: 2.5 V window - VIL <= 0.5 V, VIH >= 2.0 V, max input 2.625 V
  (2.5 V +5%), outputs open-drain to 2.5 V +5%, IOL 14 mA [p2 Table 7 p24,
  2.8 p17]; "The CMOS, Clock, APIC, and TAP inputs can each be driven from
  ground to 2.5 V. The CMOS, APIC, and TAP outputs are open drain and should
  be pulled high to 2.5 V" [p2 2.8 p17].
- Who drives the CMOS-class CPU signals: on PIIX4E boards the south drives
  A20M# and CPURST open-drain and INIT#/A20GATE partner signals [piix4
  PDF page 26, section 2.1.6 CPU INTERFACE SIGNALS]; on ICH0/ICH2 boards the
  south drives INIT# ("asserted by the ICH for 16 PCI clocks to reset the
  processor") and STPCLK# open-drain [ich pages 2-6 and 2-8] and A20M#/A20GATE
  paths come via port 92 h + A20GATE [ich page 2-6 row A20GATE,
  piix4 page 26 row A20M#]. The Socket 370 survey measured a 4.7 k Ohm to
  VCC3 (3.3 V) pull practice on its 686B board [p3f, hw/common/
  socket370_notes.md R1]; 3.3 V is above the 2.625 V input max of this
  window too - the original parts survived; what each D8 board actually
  pulls to is unmeasured (NM2).
- 100/66# is a separate 3.3 V rail: dual-capable boards pull it to 3.3 V
  with a 200 Ohm resistor [p2 2.8.2 pp 19-20].
- BCLK is driven through a 2.0 V/0.5 V window (high time measured above
  2.0 V, low below 0.5 V) [p2 Table 9 p26].
- FPGA-side receiver: same conclusion as the Socket 370 T2 analysis - no
  GTL/GTL+ class in the Cyclone V I/O catalog and referenced-VREF classes
  start at 0.5 x VCCIO, so the 1.0 V AGTL+ VREF receiver is out of catalog
  [cvds page 19 Table 16]; level translators on every CPU net (AGTL+
  CPU net (AGTL+ regenerated at the socket VTT, CMOS at an FPGA rail) is the
  required architecture. Socket 370 took this as D3 (operator); for Slot 1
  the same choice is raised as open decision D17 [plan].

## R2 - Power pins and currents

- Contact rails [sig]: 19 VCCCORE contacts (2.00 V typ for the
  Deschutes/Katmai class [p2 Table 5 pp 22-23]), 3 VCCL2 contacts
  (3.3 V +/-5%, 3.135-3.465 V [p2 Table 5 p22]), 4 VTT contacts (AGTL+
  termination rail), 1 VCC5 contact (5 V +/-5%, "VCC5 and ICC5 are not used
  by the Pentium II processors. This supply is used for the SC 242 Test
  Kit" [p2 Table 5 note 19 p23]), 30 GND contacts [sig].
- VTT is fed through the connector: "Pentium II processors generate VREF on
  the processor substrate by using a voltage divider on VTT supplied through
  the SC 242 connector" and termination resistors sit at the substrate end
  [p2 Table 8 note 2 p25]. Budget for the original CPU: IVTT max 2.7 A
  [p2 Table 5 p23]; the interposer only rebuilds the substrate end of the
  bus (termination + VREF divider), not a core.
- Original CPU totals (reference for the socket's tolerance): ICCCORE
  13.6 A max at 450 MHz, ICCL2 1.0 A, ICC Stop-Grant 1.0 A, dICCCORE/dt
  20 A/us (specified at the SC 242 pins), dICCVTT/dt 8 A/us [p2 Table 5
  pp 22-23]. Our cartridge draws none of the core/L2 current: the VRM sees
  only the strapped VID; minimum-load / idle stability of the board VRM
  without a real core load is unmeasured (NM3).
- VID strap: 5 pins, "either an open circuit or a short circuit to VSS";
  "1" = open; the supply "must supply the voltage that is requested or
  disable itself" [p2 2.6 p15]; bold supported range 1.80-2.05 V [p2
  Table 1 pp 15-16]; VRM output must disable for requests below 1.80 V
  [p2 Table 1 note 3]; if pin pull-ups are needed, >= 10 k Ohm to the
  converter (regulator input) rail so VID failure cannot push VCCCORE high
  [p2 2.6 p15-16]. The Katmai connector datasheet repeats the same table
  (2.00 V = 00001) [p3s Table 1 pp 16-17].
- Interposer's own rails come from the D13 external DC input; the socket's
  VTT contacts stay as the termination/termination-reference source for the
  AGTL+ nets (S3 quantifies the split: what the socket provides vs. what
  the external supply carries) [plan].

## R3 - Bus termination

- "All Pentium II processor system bus outputs are open drain" - pulled up
  externally by the termination [p2 2.8 p17]. AGTL+ platform topology:
  daisy-chain routing, "termination resistors to VTT at each end of the
  signal trace", and the board trace impedance "specified and held to a
  65 Ohm +/-15% tolerance" [p2 2.12 pp 24-25].
- "Pentium II processors contain AGTL+ termination resistors at the end of
  each signal trace on the processor substrate" - nominal RTT = 56 Ohm
  +/-5% [p2 Table 8 and note 2, p25]. Our cartridge is the substrate:
  the interposer fits the end-of-trace termination network (56 Ohm class)
  and its VREF divider; schematic-level detail is S4/S5 (schematic and
  pin assignment).
- RESET# is the P6-family exception without processor-end on-die
  termination: "RESET# must always be terminated to VTT on the motherboard;
  on-die termination is not provided for this signal" [p3f pages 22-23
  Table 3 note 6 - this statement is carried by the same bus family's
  platform text]; the SC242 substrate note [p2 Table 8 note 2 p25] carves
  no exception either. The board's chipset-end termination covers RESET#
  (NM4 verifies per board from the traces/board manuals).
- Unused AGTL+ inputs: "should be left as no connects; AGTL+ termination is
  provided on the processor" [p2 2.7 p16-17].
- VREF tuning: the original substrate divider is rebuilt on the interposer;
  the socket VTT contacts supply VTT to both the termination and the
  divider [sig].

## R4 - Straps, presence, and sideband

- VID[4:0] (A119-A121, B119-B120 [sig]): strapping is passive open/short -
  "00001" = 2.00 V (inside the bold supported range of both the Deschutes
  [p2 Table 1 pp 15-16] and Katmai [p3s Table 1 pp 16-17] tables). Soldered
  straps, no FPGA dependency. Never present 11111 (no-core code).
- SLOTOCC# (B101): output, drive low. SC 242 Occupation Truth Table [p2
  Table 41 pp 79-80]: SLOTOCC# = 0 with VID[4:0] != 11111 = "Processor with
  core in SC 242 connector"; SLOTOCC# = 0 with VID[4:0] = 11111 =
  "Terminator cartridge" (no core); SLOTOCC# = 1 = "SC 242 connector not
  occupied". Drive it from powered logic or a always-on open-drain gate so
  it is valid from power-on, not from FPGA configuration.
- 100/66# (B21): bidirectional strap on the 3.3 V rail; low = 66 MHz bus,
  high (3.3 V) = 100; a dual-capable board "must be pulled up to 3.3 V with
  a 1/4 W, 200 Ohm resistor" and feeds the signal to its clock
  driver/synthesizer [p2 2.8.2 pp 19-20]. Our strap policy: leave the line
  at high-Z for the 100/133 builds so the board pull-up reads "100-capable";
  ground it only if a specific 66 MHz board proves pathological (NM4).
  The connector datasheet documents no 133 entry (this catalog tops at
  100 MHz [p2 Table 9 p26]); how a 133-class board selects its FSB is the
  board's own clock-generator strap, and the cartridge-side 133 personality
  (BSEL-style codes of the later Coppermine cards) is not on disk yet (NM1).
- APIC lines: PICCLK must be driven with a valid clock (2.0-33.3 MHz,
  12.0 ns high/low min [p2 Tables 17/18 p30]) and each PICD line pulled up
  separately ("PICD[1:0] lines must be pulled-up to 2.5 V even when the
  APIC will not be used"; ~150 Ohm recommended [p2 2.7 p16-17, 2.8 p17])
  [p2 Table 2 p18]. Chipset side: the ICH is the APIC-side agent, its
  APICCLK input "can run at 16.66667 MHz", APICD[1:0] I/OD [ich pages 2-6];
  the clock generator that feeds PICCLK is board-specific (NM5).
- CMOS open-drain pull-ups per Table 2 [p2 p18]: TDI/TDO/TMS/PICD 150 Ohm;
  FERR#/IERR#/THERMTRIP# 150-220 Ohm; A20M#/IGNNE#/INIT#/LINT/PWRGOOD/SLP#
  150-330 Ohm; STPCLK#/SMI# 410 Ohm; FLUSH# 500 Ohm; TRST# "must be pulled
  to ground via a 680 Ohm resistor or driven low at power on" (Table 2
  note 3 + Table 19 [p2 p18, p31]).
- TESTHI (A13): "All TESTHI pins must be connected to 2.5 V via a pull-up
  resistor of between 1 and 100 k Ohm value" [p2 2.7 p16-17], and Table 2
  note 4 takes 1 k-10 k Ohm to 2.0 V (VCCCORE) or, if 2.5 V ramps after
  core, 100 k Ohm to VCC2.5 [p2 Table 2 note 4 p18]. On the cartridge the
  rail that is guaranteed early is the socket's VCCCORE rail: 10 k Ohm to
  it (S3 picks the final resistor).
- THERMDP (B14) / THERMDN (B15): anode/cathode of the original die's thermal
  diode [p2 Table 35 pp 58-59 + Table 41/42 p79-81]; boards may run an
  on-board reader; with no die the contact presents an open diode (NM6:
  per-board check of the thermal-monitoring path in the manuals/BIOS).
- EMI contacts (B1, B41, B61, B81, B100): "EMI pins should be connected to
  motherboard ground and/or to chassis ground through zero Ohm resistors",
  placed close to the connector [p2 2.8 p17].
- VCC_L2 (B113, B117, B121) and VCC5 (B109): leave unconnected on the
  cartridge (no L2 on die-side board; VCC5 unused by the CPU class [p2
  Table 5 note 19 p23]) [sig].
- Reserved contacts (9): "All RESERVED pins must remain unconnected" [p2
  2.7 p16].
- SECC vs SECC2 identity: both are packaging variants of the same connector
  card the interposer replaces wholesale; the BIOS-visible identity is the
  one under CPUID/VID/SLOTOCC#/reset straps, which per [agents] stays
  configurable per board (S4 records the CPUID/signature per D8 board).

## R5 - Bus clock and related clock pins

- BCLK at the processor edge fingers: max bus frequency 100.00 MHz in this
  catalog (all core frequencies [p2 Table 9 p26]); period 10.0 ns; high
  time measured above 2.0 V = 2.1 ns min, low time below 0.5 V = 1.97 ns
  min, rise 0.88-2.37 ns, fall 1.13-2.94 ns (0.5-2.0 V window), T1B' SC 242
  to core-logic offset 0.78 ns absolute value [p2 Table 9 p26]; period
  stability at the core +/-250 ps [p2 Table 10 p27]. The 133 MHz class of
  D8 boards (Apollo Pro 133/133A, i820) needs their own clock tables (NM1);
  nothing in the SC242 catalog forbids it beyond the same swing class.
- Receiver choice (per D9 only Cyclone V is built first): ball N9 = CLK1p of
  bank 3B [cvcsv]; "in single-ended use only the CLKp pin feeds the PLL"
  [cvpcg page 2]; thresholds VIH 1.7 V / VIL 0.7 V with the bank at
  VCCIO 2.5 V [cvds page 19]; VOH 2.0 V min of a 2.5 V clock generator
  clears VIH - the same reasoning documented for the Socket 370 T2 notes
  [p3f, hw/common/socket370_notes.md R5]. 133 MHz-capable reception on the
  listed clock-capable balls is confirmed by the pin CSV clock rows
  [cvcsv].
- PICCLK 2.0-33.3 MHz, 12 ns high/low min at the fingers [p2 Tables 17/18
  p30]; TCK <= 16.667 MHz [p2 Table 19 p31]; both land wherever the S5
  pin map is cheapest (TAP and PICCLK are no PLL consumers).

## R6 - Reset and configuration

### Reset requirements (CPU side)

- RESET# codings: "RESET# can be asserted (active) asynchronously, but must
  be deasserted synchronously" [p2 Table 12 note 6 p28]; pulse width
  T10' = 1.00 ms minimum "after VCCCORE, VCCL2, and BCLK become stable"
  [p2 Tables 12/13 p28].
- Reset configuration signals A[14:5]#, BR0#, FLUSH#, INIT#: setup 4 BCLK
  before RESET# deassertion (T16), hold 2-20 BCLK after the clock that
  deasserts RESET# (T17) [p2 Table 16 p29]; "For a Reset, the clock ratio
  defined by these signals must be a safe value (their final or a lower
  multiplier)" [p2 Table 16 note 2 p29]. Documented 350/400/450 ratio
  families 7/2, 4/1, 9/2 [p2 Table 11 p27]; the P6 ratio mechanism itself
  is the family text [p6man 5-7 Table 5-6]. The interposer presents a
  static safe code (S4).
- A20M#/IGNNE#/LINT[1:0] at reset: 1 ms setup before deassertion (T18),
  unknown-driver dropping tolerated <= 5 BCLK after RESET# assertion (T19),
  hold 2-20 BCLK after the deassert clock (T20) [p2 Table 16 p29].
- PWRGOOD: input, CMOS group; "a 2.5 V tolerant processor input... clean
  indication that the clocks and power supplies (VCCCORE, etc.) are stable
  and within their specifications... transition monotonically to a high
  (2.5 V) state" and "must also meet the minimum pulse width specification
  in Table 14 and Table 15, and be followed by a 1 ms RESET# pulse" [p2
  Table 41 pp 79-80]. The board sources it (reset chain below).
- Reset source chain: PIIX4E drives CPURST ("driven inactive a minimum of
  2 ms after PWROK is driven active... 2 ms when initiated through the RC
  register... inactive edge... synchronously to the rising edge of PCICLK")
  [piix4 PDF page 26]; the GMCH extends it: "The GMCH asserts CPURST# while
  RESET# (PCIRST# from ICH) is asserted and for approximately 1 ms after
  RESET# is deasserted. The CPURST# allows the processor to begin execution
  in a known state." [gmch PDF page 20]. Which trace reaches the slot is
  unmeasured (NM7).

### What the FPGA pins do while unconfigured

- **[Cv]** 25 k weak pull-ups are active before and during configuration
  [cvds pages 17-18 Table 14]; nCONFIG low tri-states the I/O [cvpcg
  page 4]; POR holds the I/O tri-stated until user mode [cvhb AS chapter].
- On AGTL+ nets this is harmless: 25 k against the 56 Ohm end termination
  moves the idle high level by only ~1-2% - and both ends interpret a high
  as bus idle.
- The real hazards are the CPU outputs that read as "in use" when left at
  their weak pull level:

| contact | output | active level | why weak state is unsafe | interposer fix |
|---|---|---|---|---|
| B21 | 100/66# | high (3.3 V) | floating = board reads "100 capable" | leave floated: correct for the 100/133 builds; a 66-only build gets a hard strap in S3 (NM4) |
| B98, B107 | A[3]#, DRDY# (every AGTL+ I/O, per `sig`) | low | high (terminated) = bus idle = safe | none: open-drain high-Z is idle [p2 2.8 p17, Table 8 p25] |
| A7, A4, A15 | FERR#, IERR#, THERMTRIP# | low | open-drain outputs, high = inactive: safe | none beyond the board's own pull-ups [p2 Table 2 p18] |
| B101 | SLOTOCC# | low | driven by always-on logic (R4), not the FPGA | none: valid from power-on |
| A119-A121, B119-B120 | VID[4:0] | strap | soldered, no FPGA dependency | soldered per R4 |

- CPU-input side: the board's chipsets drive those nets themselves (PIIX4E
  open drains [piix4 PDF page 26], ICH open drains [ich pages 2-6, 2-8]);
  our weak pull-up merely biases the node, and the 410-330 Ohm class pull
  pairs dwarf it.

### Configuration time vs board reset

- **[Cv]** supply ramp 200 us-100 ms [cvds page 9]; POR 4-12 ms fast / 100-300
  ms standard [cvds page 69 Table 55]; first DCLK 1506 us after nCONFIG
  high (tCF2CK) [cvds page 71 Table 58]; Active Serial runs on the 12.5 MHz
  internal oscillator by default [cvhb chapter 7-19]; AS x1 load time =
  .rbf bits / DCLK [cvhb page 7-23]; CONF_DONE-to-initialization rows are
  [cvds page 74 Table 60]. Exact total needs the compiled .rbf size (S5).
- The reset contract is 1.00 ms [p2 Tables 12/13 p28] plus the GMCH's own
  ~1 ms extension [gmch PDF page 20] - either way far shorter than
  configuration. Same gate as the Socket 370 build (T2 of
  `plan/interposers.md`): the chipset's RESET#/CPURST# drives our CPU-local
  reset, we deassert our own reset only after CONF_DONE, and the first
  deassertion is synchronous to BCLK [p2 Table 12 note 6 p28]. While
  configuration runs, the bus sees a quiet cartridge (no agent claims
  BR0#, no ADS#), which is the same electrical signature as an empty slot
  (NM8: verify per board that the chipset tolerates a late agent joining -
  no CPU-present timeout appears in the chipset datasheets on disk).
- After configuration: the ratio/config codes are already latched by the
  hold rows [p2 Table 16 p29]; from there the cartridge just plays the
  protocol of [p6man] - no extra timing gate beyond the config-done reset
  handling above. SLP#/STPCLK# sleep sub-states only matter to the power
  policy (S3).


## Open items (NM)

- NM1: 133 MHz-class chipset datasheets (VIA VT82C693A/694X + 686B/C596,
  Intel 82820 MCH) are not on disk - one more fetch pass, then the
  operator's local archive (`sockets/local-sources.txt` pattern).
- NM2: which rail each D8 board pulls the CMOS-class CPU inputs to
  (2.5 V per spec vs. a 3.3 V pull that the original parts survived).
- NM3: board VRM behaviour with the strapped VID but no core load
  (idle stability, min-load).
- NM4: per-board 100/66# wiring (which D8 boards ground it or pull it), and
  whether any board misbehaves with the line floated from power-on.
- NM5: per-board PICCLK source and frequency (clock chip read).
- NM6: per-board thermal-diode reader usage (THERMDP/THERMDN).
- NM7: which net (PIIX4E CPURST vs. GMCH CPURST#) reaches the slot on each
  D8 board.
- NM8: whether each D8 chipset accepts a slot agent that joins the bus only
  hundreds of ms after power (config-time gating).
- NM9: FPGA wire/RAM current run through the RTL power estimator once real
  RTL exists (replaces power estimates in `hw/slot1-cyclonev/power.md`).
- NM10: validate the AGTL+ termination draw envelope of the interposer end
  (56 Ohm per net, driven-low concurrent count vs. dI/dt 8 A/µs) on real
  traces.
- NM11: exact SC242 edge-finger pad shapes and the milled key-notch
  width/depth. The S4 footprint (`hw/lib/Slot1.pretty/SC242_CardEdge_242.kicad_mod`)
  is built from the station grid derived from the SC242 Connector Design
  Guidelines (243397-02, Fig 1: 1.0 mm pitch verified as 72 x 1 mm = 2.835 in
  and 47 x 1 mm = 1.850 in, A1 0.157 in from the card end, substrate 5.000 in
  x 0.062 in) and the connector's 2.0 mm polarization key (243397-02 sec 2.3);
  the drawn Detail-A pad shapes are a "reference only" sketch (243397-02
  Figs 2-3 point to 243341 for real dimensions, not fetched). Verify against
  a real SECC/SECC2 substrate with calipers (D16) or fetch 243341 before
  fabrication.
