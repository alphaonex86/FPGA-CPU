#!/usr/bin/env python3
"""LattePanda Mu edge (SO-DIMM 260) schematic symbol from the vendor pinout.

Usage: python3 -I hw/tools/gen_mu_sym.py
Input: sockets/slot1/lattepanda_mu/edge_connector_pinout.xlsx (sheet 2 odd,
sheet 3 even pins). The vendor KiCad symbol (MCU_Module_LattePanda.kicad_sym)
is not used: its pin numbers do not match this table (REFCLK2 on 2/4 instead
of 97/99, one GND and one VIN pin).
Output: sockets/slot1/lattepanda_mu/edge_pinout.csv (pin, signal, direction,
io_level, description, notes) and hw/lib/LattePanda_Mu_SODIMM260.kicad_sym
(unit 1 odd pins, unit 2 even pins; pin name = signal).
Checks (exit 1): pins 1..260 each once.
"""
import csv
import pathlib
import re
import sys
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from gen_slot1_cpu_sym import pin, rect_sym

ROOT = pathlib.Path(__file__).resolve().parents[2]
MU = ROOT / "sockets/slot1/lattepanda_mu"
XLSX = MU / "edge_connector_pinout.xlsx"
OUT_SYM = ROOT / "hw/lib/LattePanda_Mu_SODIMM260.kicad_sym"
FIELDS = ["pin", "signal", "direction", "io_level", "description", "notes"]


def xlsx_rows(path):
    z = zipfile.ZipFile(path)
    strings = [re.sub(r"<[^>]+>", "", s)
               for s in re.findall(r"<si>(.*?)</si>", z.read("xl/sharedStrings.xml").decode(), re.S)]
    for sheet in ("xl/worksheets/sheet2.xml", "xl/worksheets/sheet3.xml"):
        for row in re.findall(r"<row[^>]*>(.*?)</row>", z.read(sheet).decode(), re.S):
            cells = {}
            for col, attrs, body in re.findall(r'<c r="([A-Z]+)\d+"([^>]*?)(?:/>|>(.*?)</c>)', row, re.S):
                v = re.search(r"<v>(.*?)</v>", body or "")
                if v:
                    cells[col] = strings[int(v.group(1))] if 't="s"' in attrs else v.group(1)
            if cells.get("A", "").isdigit():
                yield cells


def main():
    pins = {}
    for c in xlsx_rows(XLSX):
        clean = lambda s: " ".join(s.replace("&quot;", '"').replace("&#10;", " ").replace("；", "; ").split())
        r = {"pin": c["A"], "signal": clean(c.get("B", "")), "direction": c.get("C", ""),
             "io_level": c.get("D", ""), "description": clean(c.get("E", "")), "notes": clean(c.get("G", ""))}
        if pins.setdefault(r["pin"], r) != r:
            sys.exit(f"pin {r['pin']} listed twice with different rows")
    if sorted(pins, key=int) != [str(k) for k in range(1, 261)]:
        sys.exit(f"pins not 1..260: {len(pins)}")
    rows = [pins[str(k)] for k in range(1, 261)]
    with open(MU / "edge_pinout.csv", "w", newline="") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        w.writerows(rows)
    units = []
    for side, part in (("odd pins", rows[0::2]), ("even pins", rows[1::2])):
        per = (len(part) + 1) // 2
        pl = []
        for k, r in enumerate(part):
            at = "(at -17.78 %.2f 0)" % (-2.54 * (k % per + 1)) if k < per else \
                 "(at 17.78 %.2f 180)" % (-2.54 * (k % per + 1))
            pl.append(pin(r, "passive", at, r["signal"].split(" ")[0]))
        units.append((side, pl, (-15.24, -2.54 * (per + 1), 15.24, 2.54)))
    text = rect_sym("LattePanda_Mu_SODIMM260", "J", units, "sockets/slot1/lattepanda_mu/edge_pinout.csv",
                    footprint="Slot1:LattePanda_Mu_LOTES_ADDR0110_9.2H")
    OUT_SYM.write_text('(kicad_symbol_lib (version 20241209) (generator "gen_mu_sym.py")\n%s\n)\n' % text)
    print(f"wrote {OUT_SYM.relative_to(ROOT)}, edge_pinout.csv: 260 pins")


if __name__ == "__main__":
    main()
