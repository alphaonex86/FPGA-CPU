#!/usr/bin/env python3
"""Task S3 (plan/slot1.md): generate hw/slot1-cyclonev/power.md for the
slot1-cyclonev variant. Rail requirements are cited from the FPGA datasheet
(Cyclone V CV-51002) and the Slot 1 datasheet work (hw/common/slot1_notes.md).
Regulator parts per D23 (datasheets in sockets/parts/). Checks pass or exit 1."""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "hw/slot1-cyclonev/power.md"

REPORT = """\
# Slot 1 + Cyclone V E A9 (5CEBA9/5CEFA9F23C8N) cartridge power (plan/slot1.md task S3)

Source per D13 (operator, `plan/slot1.md`): external DC input on the
cartridge, same shape as the Socket 370 build's D1. The board's VRM keeps
feeding VCCCORE/VCCL2 through the contacts, but the cartridge draws none of
it (no core, no L2); the socket VTT contacts keep feeding the AGTL+
termination and the VREF divider exactly like the original cartridge did
([notes] R2/R3). RAM is on-board DDR3L x32 4 GiB per [plan] D10.

Sources:

| tag | file |
|---|---|
| cvds | FPGAlist/CycloneV_A9/docs/cv_51002_device_datasheet.pdf |
| cvhb | FPGAlist/CycloneV_A9/docs/cv_5v2_device_handbook_vol1.pdf |
| p2 | sockets/slot1/pentium2_350-450_sc242_24365703.pdf |
| p3s | sockets/slot1/pentium3_secc2_24445201.pdf |
| notes | hw/common/slot1_notes.md |
| plan | plan/slot1.md |
| tps54620 | sockets/parts/ti_tps54620_6a_buck.pdf |
| tps62130 | sockets/parts/ti_tps62130_3a_buck.pdf |
| tps51200 | sockets/parts/ti_tps51200_vtt_sink_source.pdf |
| jack | sockets/parts/cui_pj-063ah_barrel_jack.pdf |

Strapped to the board, not generated on the cartridge:
- VID[4:0] = 00001 = 2.00 V (bold supported range of the VRM 8.2 table,
  valid for both the Deschutes and Katmai classes [p2 Table 1 pp 15-16;
  p3s Table 1 pp 16-17]; also [notes] R2/R4). The VRM outputs 2.00 V into
  the contacts; the cartridge's only draw on that rail is the TESTHI tie
  (R4: ~10 k).
- VTT 1.5 V +/-9% from the 4 VTT contacts through the board's regulator:
  the AGTL+ end-of-bus termination (56 Ohm class, one per AGTL+ net) and
  the VREF divider hang on it [notes R3; p2 Table 8 p25]. The board sized
  this rail for the original cartridge's termination draw (IVTT max 2.7 A,
  dICCVTT/dt 8 A/µs [p2 Table 5 p23]) - the load class is the same, only
  the end moves (NM3 of [notes] covers the idle-level stability).
- VCCL2 3.3 V and VCC5: left unconnected on the cartridge [notes R4] - the
  board regulators see an open circuit (NM3 of [notes]: VRM min-load).

Input: 12 V barrel jack CUI PJ-063AH (2.0 mm centre pin, 24 V / 8 A
[jack p.1]), centre-positive, 2 A fuse. All
converter outputs are strictly monotonic ramps (see Sequencing).

## Rails (generated on the cartridge)

| rail | where | required band | source |
|---|---|---|---|
| VCC | FPGA core, periphery | 1.07-1.13 V (typ 1.1 V, non-scrubbing part) | cvds p.8 Table 4 |
| VCC_AUX | FPGA auxiliary supply | 2.375-2.625 V (typ 2.5 V) | cvds p.8 Table 4 |
| VCCPD | FPGA I/O pre-driver | 2.5 V when VCCIO is 2.5/1.8/1.5/1.35/1.25/1.2 V; 3.3 V when VCCIO 3.3 V | cvds p.8 Table 4 note 4 |
| VCCIO | per bank | 2.5 V on the BCLK bank ([notes] R5); 3.3 V on default banks; translator-side rails fixed by D17 | cvds p.8-9 Table 4 |
| VCCPGM | FPGA configuration pins | 1.8/2.5/3.0/3.3 V per chosen class | cvds p.9 Table 4 |
| VCCA_FPLL | PLL analog regulator supply | 2.375-2.625 V | cvds p.9 Table 4 |
| tRAMP | all FPGA supplies strictly monotonic, no plateaus | 200 us-100 ms | cvds p.9 Table 4 / p.69 Table 55 |
| VDDR3 | DDR3L dies + SSTL135 termination | 1.35 V -0/+5% | plan D10 |
| VTTDDR | DDR3 address/command termination tracking | VDDR3/2 = 0.675 V (source/sink) | plan D10 |
| VCMOS | translator high side + PICD pull-ups (150 Ohm) | 2.5 V | p2 Table 7 p24 (2.5 V window), Table 2 p18 (pull-up practice) |

## Topology

```
12 V --[2 A fuse]--+--> SYNC BUCK --> 5 V intermediate
                   |                     |
                   |                     +--> SYNC BUCK --> 1.1 V core (VCC)
                   |                     +--> 2.5 V aux (VCC_AUX, VCCPD on 2.5 V
                   |                     |        banks; ferrite branch to
                   |                     |        VCCA_FPLL; VCMOS; VCCBAT)
                   |                     +--> 3.3 V (VCCIO of 3.3 V banks and
                   |                     |        translator high side per D17)
                   |                     +--> 1.8 V (VCCPGM)
                   |                     +--> SYNC BUCK --> 1.35 V VDDR3
                   |                              +--> 0.675 V VTTDDR (source/sink)
                   |
                   +--> (socket VTT contacts: AGTL+ termination + VREF divider)
                   +--> (socket VCCCORE contacts: TESTHI tie only)
```

Rail plan (D23: parts already on the FPGAmotherboard boards):
- 12 V -> 5 V intermediate: TPS54620, 4.5-17 V in, 6 A [tps54620 p.1]
  (covers the FPGA front end + RAM).
- 5 V -> 1.1 V core (VCC), >= 4 A capable for the CV POR reserve [cvds p.9]
  (exact current via NM9): a second TPS54620, PVIN 1.6-17 V, 6 A
  [tps54620 p.1]; a 3 A TPS62130 is too small here.
- 5 V -> 2.5 V aux, 3.3 V rail, 1.8 V (VCCPGM) and 1.35 V VDDR3: one
  TPS62130 each, 3-17 V in, 3 A, 0.9-6 V out [tps62130 p.1]; from 5 V the
  lowest rail (1.35 V) keeps its on-time above the ~80 ns minimum
  [tps62130 p.11]. VDDR3's 3 A matches its >= 3 A class (4 x8 Gb x16 dies,
  NM24): S7 re-checks it against the die IDD tables.
- 0.675 V VTTDDR: TPS51200 sink/source tracker on VDDR3 (VLDOIN 1.1-3.5 V,
  source limit >= 3 A, sink >= 3.5 A) [tps51200 p.1, p.5]; its REFOUT can
  replace U7's reference role (S7 decides, one part either way).

Implemented on the board (D23, 2026-10-31): `hw/tools/slot1_pdn.py`
computes every regulator value from the datasheet equations (printed by
gen_slot1_s6.py, list in `pdn.csv`). One net per physical rail: VCMOS and
VCCPD of the 1.35 V banks are the VCC_AUX25 net, VCCPD of the 3.3 V banks
is VCCIO33, the 1.35 V banks' VCCIO is VDDR3. Enables per Sequencing
below. Inductors checked in code at the design maximum current: peak <=
Isat at 20 % drop and Iout <= Irms [Coilcraft Doc 462-1 MSS1048, Doc 745-1
XFL4020]; TI's most conservative rule (Isat >= switch current limit,
[tps54620 p.25]) is not met by these parts. VTTDDR stays the generic U7
tracker.

## VTT draw from the socket (unchanged load class, ours to validate)

- One 56 Ohm resistor per AGTL+ net: a fully-low net draws about 20 mA
  (VTT 1.5 V down to the ~0.4 V low window). The pathological worst case is
  every AGTL+ net parked low: 64 D + 8 DEP + 33 A + 5 REQ + the remaining
  ~30 singles = 3.7 A - no protocol state drives that; the spec'd original
  total was IVTT 2.7 A [p2 Table 5 p23] with dI/dt 8 A/µs. Our end must
  stay inside the same envelope (NM10: measure the driven-low concurrent
  count against 8 A/µs on real traces).
- VREF divider: 2/3 VTT from a resistive divider, a few mA [p2 Table 8
  note 2 p25].

## Sequencing

- FPGA rails: all supplies strictly monotonic 200 µs-100 ms [cvds p.9
  Table 4]; recommended order [cvhb p.10-4 Fig 10-3]: group 1 (VCC 1.1 V)
  to >= 80 % before group 2 (VCCPGM, VCCIO, VCCPD, VCCA_FPLL, VCC_AUX)
  starts, VCCIO together with VCCPD (else up to 1 A VCCPD / 250 mA VCCIO
  transients, Table 10-1), VCCBAT any time. The cartridge: 5 V first, its
  PWRGD enables the core 1.1 V, whose PWRGD (94 % Vref [tps54620 p.6])
  enables the four group-2 converters (2.5, 3.3, 1.8, 1.35 V) together;
  then the 4-12 ms fast / 100-300 ms standard POR [cvds p.69 Table 55]
  before configuration; CONF_DONE gating is the S4 reset design ([notes]
  R6).
- RAM rails: VDDR3 must ramp strictly monotonic per DDR3L; its controller
  is released only after CONF_DONE together with the rest of the user
  design (S6).
- Board-side rails are untouched: VTT/VCCCORE/VCCL2 keep their own
  board-generated sequence (out of our hands, NM3 of [notes]).

## Budget check

- Socket VRM budget stays free: the cartridge draws no core/L2 current -
  the socket was sized for up to the P III SECC2 class (26-33 W per
  [plan]); our draw on it: IVTT-class termination 2.7 A max as the
  original cartridge did, plus the TESTHI tie (~2 mA).
- External-supply budget: AGENTS prefers FPGA < 10 W. Estimate: FPGA core
  1-2 W class + I/O banks <= 2 W + translators and CMOS regeneration
  < 1 W + DDR3L ram at bus-class bandwidth (x32 at <= 100-133 MT/s =
  <= 0.5 GB/s: well under 1 W) => cartridge total < 6 W, 12 V input draw
  < 0.6 A at 90% efficiency, inside the 2 A fuse.
- Exact FPGA current waits for the RTL power estimator on real RTL (NM9);
  the termination envelope check is NM10.
- Open items of [notes] relevant here: NM2 (which rail each board pulls the
  CMOS-class CPU inputs to - decides the VCMOS-regenerated levels),
  NM3 (VRM behaviour with the strapped VID but no core load).
"""

fails = []
def check(name, ok, detail=""):
    print(("PASS" if ok else "FAIL"), name, detail)
    if not ok:
        fails.append(name)

source_rows = [(t, p) for t, p in
               re.findall(r"^\| (\w+) \| ([^|\n]+) \|$", REPORT, re.M)
               if t != "tag"]
for tag, path in source_rows:
    check(f"source [{tag}] exists", (ROOT / path).is_file(), path)
cited = set(re.findall(r"\[([a-z][a-z0-9]*)(?:[ .^][^\]]*)?\]", REPORT))
for t in sorted(cited):
    check(f"cite [{t}] defined", t in {t_ for t_, _ in source_rows})
for section in ("## Rails", "## Topology", "## Sequencing", "## Budget check"):
    check(f"section {section}", section in REPORT)
for token in ("VID[4:0] = 00001", "VTT 1.5 V +/-9%", "VDDR3", "VTTDDR",
              "0.675", "12 V barrel jack", "2 A fuse"):
    check(f"content: {token}", token in REPORT)
check("no drafting flags left", not re.search(r"TODO|FIXME|ND\b|\bNM0\b",
                                              REPORT))

if fails:
    sys.exit(1)
OUT.parent.mkdir(exist_ok=True)
OUT.write_text(REPORT)
print(f"wrote {OUT} ({len(REPORT.splitlines())} lines)")
