#!/usr/bin/env python3
"""LattePanda Mu edge (SO-DIMM 260): schematic symbol from the vendor pinout,
footprint of the LOTES ADDR0110-P005A 9.2H socket.

Usage: python3 -I hw/tools/gen_mu_lib.py
Input: sockets/slot1/lattepanda_mu/edge_connector_pinout.xlsx (sheet 2 odd,
sheet 3 even pins). The vendor KiCad symbol (MCU_Module_LattePanda.kicad_sym)
is not used: its pin numbers do not match this table (REFCLK2 on 2/4 instead
of 97/99, one GND and one VIN pin).
Output: sockets/slot1/lattepanda_mu/edge_pinout.csv (pin, signal, direction,
io_level, description, notes) and hw/lib/LattePanda_Mu_SODIMM260.kicad_sym
(unit 1 odd pins, unit 2 even pins; pin name = signal);
hw/lib/Slot1.pretty/LattePanda_Mu_LOTES_ADDR0110_9.2H.kicad_mod: the vendor
LattePanda_Module_H8.0mm_Horizontal land pattern (= LOTES AP-ADDR0110 sheet 3:
rows +-4.10, pitch 0.50, pads 0.30 x 1.75, holes 1.60 / 1.10 at +-34.40)
with the hold-down pads at the LOTES +-37.75 (hole + 3.35, detail H; the
vendor footprint has 37.5); the module outline moves to F.Fab and F.CrtYd
becomes the socket body (rows, latches), so parts may sit under the module
(height there: gen_c2mu_s7.py); 3D model: the vendor H8.0 module + socket STEP
(gzip, hw/lib/3dmodels), raised 1.1 mm for the 6.6 mm standoff of the 9.2H;
hw/lib/Slot1.pretty/Standoff_SMT_M2_D5.56_H6.6.kicad_mod: the Mu's M2 standoffs,
Sinhoo SMTSO2066CTJ (LCSC C2916353, reflowed by JLCPCB; spigot 3.60 x 1.53 in
a plated 3.70 hole, body 5.56) [xhyj_smtso2066ctj]; 3D model: the stock Wuerth
M2 SMT spacer stretched from 6.0 to 6.6 mm.
Checks (exit 1): pins 1..260 each once; 260 + 2 pads, 2 holes.
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
VENDOR_FP = MU / "LattePanda_Module_H8.0mm_Horizontal.kicad_mod"
FP_NAME = "LattePanda_Mu_LOTES_ADDR0110_9.2H"
OUT_FP = ROOT / f"hw/lib/Slot1.pretty/{FP_NAME}.kicad_mod"
MODEL = "LattePanda_Mu_H8.0_Horizontal.stpZ"
MOUNT_Z = 1.1                            # 9.2H standoff 6.6 mm - 8.0H 5.5 mm
STANDOFF = "Standoff_SMT_M2_D5.56_H6.6"
STANDOFF_R = 3.4                         # courtyard radius: pad 6.3 + 0.25 each side
STANDOFF_MODEL = "Mounting_Wuerth.3dshapes/Mounting_Wuerth_WA-SMSI-M2_H6mm_9774060243.step"
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
    write_footprint()
    write_standoff()


def write_standoff():
    model = pathlib.Path("/usr/share/kicad/3dmodels") / STANDOFF_MODEL
    dst = ROOT / "hw/lib/3dmodels" / model.name
    if not dst.exists():
        dst.write_bytes(model.read_bytes())
    fp = ROOT / f"hw/lib/Slot1.pretty/{STANDOFF}.kicad_mod"
    fp.write_text(f'''(footprint "{STANDOFF}" (version 20241229) (generator "gen_mu_lib.py") (layer "F.Cu")
	(descr "SMT standoff M2, body 5.56, height 6.6, Sinhoo SMTSO2066CTJ (sockets/parts/xhyj_smtso2066ctj.pdf)")
	(property "Reference" "REF**" (at 0 -4 0) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))
	(property "Value" "{STANDOFF}" (at 0 4 0) (layer "F.Fab") (effects (font (size 1 1) (thickness 0.15))))
	(attr through_hole)
	(fp_circle (center 0 0) (end 2.78 0) (stroke (width 0.1) (type solid)) (fill no) (layer "F.Fab"))
	(fp_circle (center 0 0) (end {STANDOFF_R} 0) (stroke (width 0.05) (type solid)) (fill no) (layer "F.CrtYd"))
	(fp_circle (center 0 0) (end {STANDOFF_R} 0) (stroke (width 0.05) (type solid)) (fill no) (layer "B.CrtYd"))
	(pad "1" thru_hole circle (at 0 0) (size 6.3 6.3) (drill 3.7) (layers "*.Cu" "*.Mask" "F.Paste"))
	(model "${{KIPRJMOD}}/../lib/3dmodels/{model.name}" (offset (xyz 0 0 0)) (scale (xyz 1 1 1.1)) (rotate (xyz 0 0 0)))
)
''')
    print(f"wrote {fp.relative_to(ROOT)}")


def write_footprint():
    t = VENDOR_FP.read_text()
    t = t.replace('(footprint "LattePanda_Module_H8.0mm_Horizontal"', f'(footprint "{FP_NAME}"', 1)
    t = t.replace('"LattePanda_Module_H8.0mm_Horizontal"', f'"{FP_NAME}"')
    for old, new in (("(at -37.5 8)", "(at -37.75 8)"), ("(at 37.5 12)", "(at 37.75 12)")):
        if t.count(old) != 1:
            sys.exit(f"vendor footprint: {old} not found once")
        t = t.replace(old, new)
    if t.count('(layer "F.CrtYd")') != 10:
        sys.exit("vendor footprint: expected the 10 module courtyard items")
    t = t.replace('(layer "F.CrtYd")', '(layer "F.Fab")')
    body = [(-38.75, -5.25), (38.75, -5.25), (38.75, 14.0), (35.0, 14.0), (35.0, 5.25), (-35.0, 5.25),
            (-35.0, 14.0), (-38.75, 14.0)]
    crtyd = ('\t(fp_poly (pts %s)\n\t\t(stroke (width 0.05) (type solid)) (fill no) (layer "F.CrtYd"))\n'
             % " ".join("(xy %g %g)" % xy for xy in body))
    pads = re.findall(r'\(pad "([^"]*)" (\w+)', t)
    if len([p for p in pads if p[0].isdigit()]) != 260 or pads.count(("MP", "smd")) != 2 \
            or pads.count(("", "np_thru_hole")) != 2:
        sys.exit(f"vendor footprint: unexpected pads {len(pads)}")
    model = (f'\t(model "${{KIPRJMOD}}/../lib/3dmodels/{MODEL}"\n\t\t(offset (xyz 0 0 {MOUNT_Z}))\n'
             '\t\t(scale (xyz 1 1 1))\n\t\t(rotate (xyz 0 0 0))\n\t)\n)')
    t = t.rstrip()
    if not t.endswith(")") or "(model " in t:
        sys.exit("vendor footprint: unexpected end or a model already")
    OUT_FP.write_text(t[:-1] + crtyd + model + "\n")
    if not (ROOT / "hw/lib/3dmodels" / MODEL).exists():
        sys.exit(f"missing hw/lib/3dmodels/{MODEL}: gzip the STEP of LattePanda_Mu_H8.0_Horizontal.step.7z")
    print(f"wrote {OUT_FP.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
