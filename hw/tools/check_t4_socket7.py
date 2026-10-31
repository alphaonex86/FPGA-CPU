#!/usr/bin/env python3
"""Task T4 (plan/interposers.md) for the socket 7 variants: verify the
library pieces the T6 schematic will use - base CPU symbol and header
footprint match hw/common/socket7_signals.csv, and the two FPGA symbols
match their ball CSVs. Checks pass or exit 1.
"""
import csv
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
T1 = ROOT / "hw/common/socket7_signals.csv"
SYM = ROOT / "sockets/kicad/CPU_Intel_Socket7.kicad_sym"
MOD = ROOT / "sockets/kicad/Interposer.pretty/Socket7_Base_PGA296.kicad_mod"
FPGA = [("FPGA_CycloneV_5CEFA9_F484_FPGA", "FPGAlist/CycloneV_A9/pins/5ceba9_f484.csv"),
        ("FPGA_Ti180_TI180G400_FPGA", "FPGAlist/Ti180_G400/pins/ti180g400.csv")]

fails = []
def check(name, ok, detail=""):
    print(("PASS" if ok else "FAIL"), name, detail)
    if not ok:
        fails.append(name)

t1 = {(r["pin"], r["signal"].strip("[]"))
      for r in csv.DictReader(T1.open())}
check("T1 rows = 296", len(t1) == 296, f"{len(t1)} rows")

sym = SYM.read_text()
pins = set()
for m in re.finditer(r'\(pin\s+\w+\s+line[^\n]*', sym):
    blk = sym[m.start():m.start() + 2000]
    nm = re.search(r'\(name "([^"]*)"', blk)
    nu = re.search(r'\(number "([^"]*)"', blk)
    if nm and nu:
        pins.add((nu.group(1), nm.group(1).strip('"')))
check("symbol pin count = T1", len(pins) == len(t1),
      f"symbol {len(pins)} vs T1 {len(t1)}")
check("symbol pins match T1 pin+signal", pins == t1,
      f"diff: {sorted(pins ^ t1)[:8]}")

pads = set(re.findall(r'\(pad "([^"]+)"', MOD.read_text()))
check("footprint pads = symbol pin numbers",
      pads == {p for p, _ in t1}, f"footprint {len(pads)} pads")

for name, csvp in FPGA:
    balls = {l.split(",")[0]
             for l in (ROOT / csvp).read_text().splitlines()[1:] if l}
    sy = (ROOT / "hw/lib" / f"{name}.kicad_sym")
    ok = sy.is_file()
    check(f"FPGA symbol {name} exists", ok)
    if ok:
        n = set(re.findall(r'\(number "([^"]+)"', sy.read_text()))
        check(f"FPGA symbol {name} pins = ball CSV", n == balls,
              f"sym {len(n)} vs csv {len(balls)}")

sys.exit(1 if fails else 0)
