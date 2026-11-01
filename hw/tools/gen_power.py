#!/usr/bin/env python3
"""Task T3 (plan/interposers.md): generate hw/<variant>/power.md for the
socket370-cyclonev and socket3-cyclonev (socket370-ti180 dropped: D10).
Rail requirements are cited from the FPGA datasheet (Cyclone V CV-51002);
regulator part numbers are proposals left to
the T9 BOM (no regulator datasheets in repo). Regenerate with this script.
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUTDIR = ROOT / "hw"

INTRO_370 = """Source per D1 (decided 2026-10-20, `plan/interposers.md`): external supply on
the interposer; the socket rails stay untouched (the board's VRM still feeds
VCCCORE/VTT through the Mill-Max header, VID straps code <=1.7 V per the
operator). No module RAM (D4). Page numbers are the printed pages of the
cited PDFs.

Socket-side rails (unchanged by D1): VCCCORE straps to a code at or below
1.7 V; VTT 1.5 V AGTL+ is the board's termination/reference rail
(`hw/common/socket370_notes.md` R2/R3); VCCCMOS 1.5 V is generated inside
the package (`hw/common/socket370_notes.md` R4); EDGCTRL gets its 51 ohm
pull-up to the socket's VCCCORE; RTTCTRL/SLEWCTRL straps as in R4. These
are socket nets, not FPGA loads.

Input: 12 V barrel jack 5.5x2.1 mm, centre-positive, 2 A fuse. All
converter outputs are strictly monotonic ramps (see sequencing).
"""

HEAD = """# {name} power (plan/interposers.md task T3)

{intro}
FPGA tags: cvds = `FPGAlist/CycloneV_A9/docs/cv_51002_device_datasheet.pdf`,
cvhb = `FPGAlist/CycloneV_A9/docs/cv_5v2_device_handbook_vol1.pdf`.

## Rails

{rails}

## Topology

```
12 V --[2 A fuse]--+--> SYNC BUCK --> 5 V intermediate
                   |                     |
                   |                     +--> SYNC BUCK --> {core} V core rail
                   |                     +--> aux rail
                   |                     +--> I/O rail
                   |
                   +--> (nothing else from 12 V)
```

{topo}

## Sequencing

{seq}

## Budget check (D1)

- {budget}
- Estimate - to be replaced by the vendor power estimator on real RTL
  ({est_ref}): {est}
- Connector sized 12 V / 2 A with 2 A fuse; AGENTS prefers FPGA < 10 W.
"""

CV_RAILS = """| rail | where | required band | source |
|---|---|---|---|
| VCC | core, periphery, PCS, PCIe hard IP digital | 1.07-1.13 V (typ 1.1 V, non-scrubbing part) | cvds p.8 Table 4 |
| VCC_AUX | auxiliary supply | 2.375-2.625 V (typ 2.5 V) | cvds p.8 Table 4 |
| VCCPD | I/O pre-driver | 2.5 V when VCCIO is 2.5/1.8/1.5/1.35/1.25/1.2 V; 3.3 V when VCCIO 3.3 | cvds p.8 Table 4 notes 4 |
| VCCIO | per bank | chosen per bank in T5: 2.5 V on the BCLK bank (R5), 3.3 V on default CMOS banks | cvds p.8-9 Table 4 |
| VCCPGM | configuration pins | 1.8/2.5/3.0/3.3 V band per chosen class | cvds p.9 Table 4 |
| VCCA_FPLL | PLL analog regulator supply | 2.375-2.625 V | cvds p.9 Table 4 |
| VCCBAT | battery back-up (volatile security key) | 1.2-3.0 V | cvds p.9 Table 4 |
| tRAMP | all supplies strictly monotonic, no plateaus | 200 us-100 ms (standard POR) | cvds p.9 Table 4 / p.69 Table 55 |
"""

CV_TOPO = """Rail plan (regulator part numbers are T9 BOM items, no datasheets in repo):
- 12 V -> 5 V intermediate buck (2 A class).
- 5 V -> 1.1 V core buck (VCC), >= 3 A capable (power-up current reserve
  for the CV POR; exact current NM9).
- 5 V -> 2.5 V "aux rail" (VCC_AUX + VCCPD + VCCA_FPLL; ferrite-filtered
  branch to VCCA_FPLL), 500 mA LDO/buck class.
- 5 V -> 3.3 V "I/O rail" (translator high side + VCCIO of 3.3 V banks),
  1 A class.
- 5 V -> 1.8 V (VCCPGM), 300 mA class.
- VCCBAT: tied to the aux rail (band 1.2-3.0 V covers 2.5 V).
"""

CV_BUDGET_T = """D1 moved to external supply, so the socket 32 W budget no longer bounds
  the FPGA; the limit that applies is the AGENTS preference (< 10 W FPGA
  power) converted at ~85% buck efficiency: 12 V input draw stays below
  1.5 A"""

def cv_seq(core_pg, group2):
    """Cyclone V order; core_pg: the core PGOOD threshold, group2: the
    converters it enables"""
    return f"""All supplies strictly monotonic (200 us-100 ms ramp) [cvds p.9 Table 4].
Recommended order [cvhb p.10-4 Fig 10-3]: group 1 (VCC 1.1 V) to >= 80 %
before group 2 (VCCPGM, VCCIO, VCCPD, VCCA_FPLL, VCC_AUX) starts, VCCIO
together with VCCPD (else up to 1 A VCCPD / 250 mA VCCIO transients,
cvhb Table 10-1); VCCBAT any time. PGOOD cascade: 5 V first, its PGOOD
enables the core 1.1 V, whose PGOOD ({core_pg}) enables the {group2}
converters together; then the 4-12 ms (fast) / 100-300 ms (standard) POR
[cvds p.69 Table 55] before configuration; CONF_DONE gating is T6's job
(`{{notes}}` R6).
"""

S3_INTRO = """Source per D1 (decided 2026-10-31, `plan/interposers.md`): external 12 V
supply on the interposer. The socket's 23 VCC pins feed only the
VCORE-present detector divider (78.1 k, 44 uA at 3.45 V): the board's
PQ30RV21 LDO (2 A abs max, `hw/common/socket3_notes.md` R2) sees no other
load. The 28 VSS pins join the interposer GND (common reference for the
5 V TTL bus). No module RAM (D4). Page numbers are the printed pages of the
cited PDFs; regulator parts are the ones already on the FPGAmotherboard
boards (datasheets in `sockets/parts/`).

Socket-side nets: VOLDET (S4) is tied to VSS; the pull-ups (C11, DP3-DP0)
sit on the FPGA side of the switches (`hw/common/socket3_notes.md` R4/R6);
the 16 translators run from the 3.3 V rail (T5, D2) and stay open while the
socket rail is down: TLV6700 detector on V5 (`hw/tools/socket3_pdn.py`,
plan/interposers.md FPGAmotherboard compatibility).

Input: 12 V barrel jack CUI PJ-063AH (2.0 mm centre pin), centre-positive,
2 A fuse. All converter outputs are strictly monotonic ramps (see sequencing).
"""

S3_CV_RAILS = CV_RAILS.replace(
    "chosen per bank in T5: 2.5 V on the BCLK bank (R5), 3.3 V on default CMOS banks",
    "3.3 V on every used bank 3B/4A/7A (T5 `pins.csv`, notes R5)").replace(
    "| 1.8/2.5/3.0/3.3 V band per chosen class |",
    "| 3.3 V (band 1.8/2.5/3.0/3.3 V; host passive-serial levels, D7) |")

S3_CV_TOPO = """Rail plan (tps54620 = sockets/parts/ti_tps54620_6a_buck.pdf, tps62130 =
sockets/parts/ti_tps62130_3a_buck.pdf, jack = sockets/parts/cui_pj-063ah_barrel_jack.pdf):
- 12 V input: CUI PJ-063AH, 2.0 mm centre pin, rated 24 V / 8 A [jack p.1].
- 12 V -> 5 V intermediate: TPS54620, 4.5-17 V in, 6 A [tps54620 p.1].
- 5 V -> 1.1 V core (VCC): TPS62130, 3-17 V in, 3 A, 0.9-6 V out [tps62130
  p.1]. From 12 V the 1.1 V on-time (D/fsw = 37 ns at 2.5 MHz) would sit
  under its ~80 ns minimum on-time [tps62130 p.11]; from 5 V it is 88 ns,
  hence the intermediate rail.
- 5 V -> 2.5 V (VCC_AUX, VCCA_FPLL through a ferrite, VCCBAT): TPS62130.
- 5 V -> 3.3 V (VCCIO 3B/4A/7A, VCCPD, VCCPGM, 16 translators): TPS62130.
- VCCPD = 3.3 V because every used bank is 3.3 V [cvds p.8 Table 4 note 4];
  VCCPGM on the same rail: no 1.8 V regulator.
"""

S3_BUDGET = """D1 is an external supply, so the DX4's 4.3 W socket budget no longer
  bounds the FPGA; the limit that applies is the AGENTS preference (< 10 W
  FPGA power) converted at ~85% buck efficiency: 12 V input draw stays below
  1.5 A, inside the 8 A jack [jack p.1] and the 6 A TPS54620"""

FILES = {
 "socket3-cyclonev": {
    "name": "Socket 3 + Cyclone V E A9 (5CEBA9/5CEFA9F23C8N) interposer",
    "intro": S3_INTRO, "notes": "hw/common/socket3_notes.md",
    "est_ref": "Quartus power estimate once T6 compiles",
    "rails": S3_CV_RAILS, "core": "1.1", "topo": S3_CV_TOPO,
    "seq": cv_seq("92-98 % Vout rising [tps62130 p.5]", "2.5 and 3.3 V"),
    "budget": S3_BUDGET,
    "est": "Cyclone V E A9 in this role (no transceivers) core ~1-2 W class\n  + banks + 16 translators; all converted power < 10 W => true"},
 "socket370-cyclonev": {
    "name": "Socket 370 + Cyclone V E A9 (5CEBA9/5CEFA9F23C8N) interposer",
    "intro": INTRO_370, "notes": "hw/common/socket370_notes.md",
    "est_ref": "NM9, `hw/common/socket370_notes.md`",
    "rails": CV_RAILS, "core": "1.1", "topo": CV_TOPO,
    "seq": cv_seq("threshold per the T9 part", "2.5, 3.3 and 1.8 V")
           + "No load switch (operator, 2026-11-01; socket 7 needs one, its I/O\n"
           "rail is the board's VCC3): VCCIO33, which also powers the translators'\n"
           "A side, comes from our 3.3 V converter that the core PGOOD already\n"
           "enables, so a switch in series would add nothing.\n",
    "budget": CV_BUDGET_T,
    "est": "Cyclone V E A9 in this role (no transceivers, low-density logic)\n  core ~1-2 W class + banks; all converted power < 10 W => true"},
}

for variant, spec in FILES.items():
    text = HEAD.format(**{**spec, "seq": spec["seq"].format(notes=spec["notes"])})
    out = OUTDIR / variant / "power.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    print(f"wrote {out} ({len(text.splitlines())} lines)")
