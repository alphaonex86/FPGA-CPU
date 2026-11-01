#!/usr/bin/env python3
"""Task T3 (plan/interposers.md): generate hw/socket7-cyclonev/power.md
(socket7-ti180 dropped: D9). Source is D1 (socket 7: power from the
socket's own rails, decided 2026-10-21). Rail requirements are cited from
the FPGA datasheet (Cyclone V CV-51002); regulator part numbers are T9
BOM items (no regulator datasheets in repo). Regenerate with this
script."""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]

SOURCES = """Sources:

| tag | file |
|---|---|
| cvds | FPGAlist/CycloneV_A9/docs/cv_51002_device_datasheet.pdf |
| cvhb | FPGAlist/CycloneV_A9/docs/cv_5v2_device_handbook_vol1.pdf |
| mmx | sockets/socket7/pentium_mmx_datasheet_243185-004.pdf |
| fmb | sockets/socket7/intel_430hx_pcsiset_design_guide_297467-002.pdf |
| spec | sockets/socket7/board/biostar_mb-8500ttd_spec.pdf |
| jumpers | sockets/socket7/board/biostar_mb-8500ttd_undocumented_jumpers.pdf |
| mmpins | sockets/parts/mill-max_catalog_metric.pdf |
| notes | hw/common/socket7_notes.md |
| plan | plan/interposers.md |
| agents | AGENTS.md |
"""

HEAD = """# Socket 7 + {fpga} interposer power (plan/interposers.md task T3)

Source per D1 (decided 2026-10-21 for socket 7, `plan/interposers.md`):
the interposer takes its power from the socket's own rails through the
Mill-Max header - VCC2 (core, 2.8 V on this board [spec p.5]) and VCC3
(I/O, 3.4 V on this board [spec p.5]). No external supply, no barrel jack.
No module RAM (D4). Page numbers are the printed pages of the cited PDFs.

Socket-side envelope ([notes] R2): VCC2 2.7/2.8/2.9 V +/-3.57 % on 25 pins,
VCC3 3.135-3.6 V on 28 pins, ICC2 max 6.5 A, ICC3 max 750 mA, active max
17.0 W [mmx p.31-32 Tables 10/12/13]. No VCC2/VCC3 sequencing: "no specific
power sequence required", both ON or both OFF within one second
recommended [mmx p.28 sec. 3.1.1.1]. Our loads are attached to rails the
board VRM raises together, so this holds by construction. All converter
outputs are strictly monotonic ramps (see Sequencing).
"""

BUDGET = """## Budget check (D1: total within the socket budget)

Numbers below are an **estimate** until the vendor power estimator runs on
real RTL (replaces this section then); this design uses no DDR PHY, no
transceivers and no HSIO/MIPI, so the class is "fabric + light I/O".

- Total interposer draw (estimate): core rail {core_w} W + I/O and aux
  {io_w} W + converters at ~90 % efficiency => <= {total_w} W against the
  17.0 W the board VRM was built for [mmx p.32 Table 13; agents]. PASS.
- VCC2 branch (feeds only the {core_buck} core buck): {vcc2_a} A at
  2.8 V against ICC2 6.5 A [mmx p.31 Table 12]; {per_pin} A average per
  VCC2 pin against the 1 A Mill-Max 550 rating [mmpins p.188-189]. PASS.
- VCC3 branch: VCCIO/VCCPD/VCCPGM{pgm_extra} through the load switch + the aux buck:
  {vcc3_a} A estimate against ICC3 750 mA [mmx p.31 Table 12] - the
  binding limit of the three. PASS if the estimator confirms; if it comes
  back over, the VCCIO dynamic estimate must be refined per-bank before
  any rail re-planning.
- Board VCC3 sits at 3.4 V [spec p.5]: inside the 3.3 V band max 3.465 V
  of both FPGAs ({vio_band_src}) and inside VCC3 max 3.6 V [mmx p.31
  Table 10]. PASS.
- FMB rule "HCLK begins toggling within 150 ms after VCC reaches its
  operating level" [fmb p.2-2] is about the CPU seeing the clock: the
  board clock runs from power-on independent of our rails, and our
  converters start as soon as VCC2/VCC3 come up, so the FPGA is powered
  long before the board releases CPURST; the config-vs-reset timing is
  closed in [notes] R6.
"""

def rails_cv():
    return """## Rails (Cyclone V E A9, 5CEBA9/5CEFA9F23C8N)

| rail | where | required band | source |
|---|---|---|---|
| VCC | FPGA core, periphery | 1.07-1.13 V (typ 1.1 V) | cvds p.8 Table 4 |
| VCC_AUX (VCCAUX) | auxiliary supply | 2.375-2.625 V (typ 2.5 V) | cvds p.8 Table 4 |
| VCCPD | I/O pre-driver | 3.3 V: every used bank is a 3.3 V VCCIO bank ([notes] R1, no 2.5 V net on this socket) | cvds p.8 Table 4 note 4 |
| VCCIO | per bank | 3.3 V (3.135-3.465 V), all banks: host bus and straps are 3.3 V TTL [notes R1] | cvds p.8-9 Table 4 |
| VCCPGM | configuration pins | 3.3 V class | cvds p.9 Table 4 |
| VCCA_FPLL | PLL analog regulator supply | 2.375-2.625 V | cvds p.9 Table 4 |
| VCCBAT | battery back-up (volatile security key) | 1.2-3.0 V | cvds p.9 Table 4 |
| tRAMP | all supplies strictly monotonic, no plateaus | 200 us-100 ms (standard POR) | cvds p.9 Table 4 / p.69 Table 55 |
"""


def topo_cv():
    return """## Topology

```
VCC2 2.8 V (25 header pins) --[bulk+bulk]--> SYNC BUCK --> VCC 1.1 V
VCC3 3.4 V board (28 header pins) --+--> LOAD SWITCH (EN = core PGOOD)
                                    |      --> VCCIO33: VCCIO / VCCPD / VCCPGM
                                    +--> 2.5 V aux (VCCAUX; ferrite
                                             branch to VCCA_FPLL;
                                             VCCBAT tied here)
```

Rail plan (regulator part numbers are T9 BOM items; no regulator
datasheets in repo):
- VCC2 -> 1.1 V core buck, >= 3 A class: input must tolerate the 2.70-
  2.90 V window at ~40 % duty (a 3-6 V input part does NOT qualify; this
  is the one part whose Vin range is a hard requirement). Power-up
  current reserve for the CV POR [cvds p.9].
- VCC3 -> 2.5 V aux, 1 A class (input covers 3.135-3.6 V).
- VCC3 -> load switch -> VCCIO33 (VCCIO/VCCPD/VCCPGM): the board's 3.4 V
  is inside the 3.465 V band max [cvds p.8-9 Table 4]; decouple per bank.
  Switch class: input 3.135-3.6 V, >= 1 A, on-resistance <= 80 mOhm
  (<= 50 mV drop at the 0.6 A VCC3 estimate, 3.35 V left), controlled
  monotonic rise inside 200 us-100 ms [cvds p.9 Table 4], output
  discharge when off; EN from the core buck PGOOD (open drain, pull-up to
  S_VCC3).
- VCCBAT: tied to the 2.5 V aux rail (1.2-3.0 V band) [cvds p.9 Table 4].
"""


def seq_cv():
    return """## Sequencing

- All supplies strictly monotonic 200 us-100 ms [cvds p.9 Table 4].
  Recommended order [cvhb p.10-4 Fig 10-3]: group 1 (VCC 1.1 V) to
  >= 80 % before group 2 (VCCPGM, VCCIO, VCCPD, VCCA_FPLL, VCC_AUX),
  VCCIO together with VCCPD. The core buck's PGOOD enables the 2.5 V
  aux buck (VCC_AUX, VCCA_FPLL).
- The board's VCC3 rises together with VCC2 [mmx p.28], i.e. before the
  core buck fed from VCC2 is up; a direct VCCIO/VCCPD/VCCPGM feed would
  break the order and cost a VCCPD current transient up to 1000 mA, ~50 us
  typical [cvhb p.10-4/10-5 Table 10-1 note 33] on a VCC3 rated ICC3
  750 mA [mmx p.31 Table 12]. Hence the load switch (operator,
  2026-11-01): the same core PGOOD enables it and the aux buck, so all of
  group 2 starts together; VCCIO and VCCPD share VCCIO33, so they ramp
  together [cvhb Table 10-1 note 35].
- Until the switch closes, the board drives the 3.3 V bus into unpowered
  banks (direct bus, no translators): allowed, the I/O, dedicated input
  and clock pins take signals before or during power up without damage or
  back-powering [cvhb p.10-2], at most 300 uA DC / 8 mA AC per pin
  [cvds p.17 Table 13]. CONF_DONE and nSTATUS have no hot-socket circuit
  and may drive during power up [cvhb p.10-3]: they only reach our
  pull-ups and the config header.
- POR after all supplies are valid: 100-300 ms (standard POR) before
  configuration is accepted [cvds p.69 Table 55]; nSTATUS/CONF_DONE and
  the board-reset stretch handle the handshake with CPURST ([notes] R6).
"""


VARIANTS = {
    "socket7-cyclonev": dict(
        fpga="Cyclone V E A9 (5CEBA9/5CEFA9F23C8N)",
        rails=rails_cv(), topo=topo_cv(), seq=seq_cv(),
        core_w=2.5, io_w=2.0, total_w=6, core_buck="1.1",
        vcc2_a=1.0, per_pin=0.04, vcc3_a=0.6, pgm_extra="/VCCPGM",
        vio_band_src="cvds p.8-9 Table 4"),
}

fails = []
def check(name, ok, detail=""):
    print(("PASS" if ok else "FAIL"), name, detail)
    if not ok:
        fails.append(name)

for variant, v in VARIANTS.items():
    report = (HEAD.format(fpga=v["fpga"]) + "\n" + SOURCES + "\n"
              + v["rails"] + "\n" + v["topo"] + "\n" + v["seq"] + "\n"
              + BUDGET.format(core_w=v["core_w"], io_w=v["io_w"],
                              total_w=v["total_w"], core_buck=v["core_buck"],
                              vcc2_a=v["vcc2_a"], per_pin=v["per_pin"],
                              vcc3_a=v["vcc3_a"], pgm_extra=v["pgm_extra"],
                              vio_band_src=v["vio_band_src"]))
    tag_rows = re.findall(r"^\| (\w+) \| ([^|\n]+) \|$", report, re.M)
    tag_rows = [(t, p) for t, p in tag_rows if t != "tag"]
    for tag, path in tag_rows:
        check(f"[{variant}] source [{tag}] exists", (ROOT / path).is_file(), path)
    cited = set(re.findall(r"\[([a-z][a-z0-9]*)(?:[ .^][^\]]*)?\]", report))
    for t in sorted(cited):
        check(f"[{variant}] cite [{t}] defined", t in {t_ for t_, _ in tag_rows})
    for section in ("## Rails", "## Topology", "## Sequencing", "## Budget check"):
        check(f"[{variant}] section {section}", section in report)
    check(f"[{variant}] D1 socket-rail source stated",
          "takes its power from the socket" in report)
    check(f"[{variant}] estimate marked", "estimate" in report.lower())
    # the plan's T3 check: total within D1's budget (17.0 W, per-rail caps)
    est_total = (v["core_w"] + v["io_w"]) / 0.9
    check(f"[{variant}] total <= 17.0 W", est_total <= 17.0,
          f"{est_total:.1f} W est")
    check(f"[{variant}] VCC2 <= ICC2 6.5 A", v["vcc2_a"] <= 6.5,
          f"{v['vcc2_a']} A est")
    check(f"[{variant}] VCC3 <= ICC3 0.75 A", v["vcc3_a"] <= 0.75,
          f"{v['vcc3_a']} A est")
    check(f"[{variant}] per-pin <= 1 A", v["per_pin"] <= 1.0,
          f"{v['per_pin']} A/pin est")
    out = ROOT / "hw" / variant / "power.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(report)
    print(f"wrote {out} ({len(report.splitlines())} lines)")

sys.exit(1 if fails else 0)
