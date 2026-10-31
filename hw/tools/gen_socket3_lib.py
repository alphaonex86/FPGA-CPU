#!/usr/bin/env python3
"""Task T4 (plan/interposers.md) for the socket 3 variants: generate the
base CPU symbol sockets/kicad/CPU_Socket3_Am5x86.kicad_sym from
hw/common/socket3_signals.csv (shape of gen_slot1_cpu_sym.py), the
SN74CB3T3245 bus switch (D2 translator) in hw/lib/Socket3_Parts.kicad_sym,
and verify
the library pieces T6 will use: symbol = T1, base footprint pads = symbol
pins, FPGA symbols = their ball CSVs. Checks pass or exit 1.
"""
import csv
import pathlib
import re
import sys

from gen_slot1_cpu_sym import rect_sym, unit_pins

ROOT = pathlib.Path(__file__).resolve().parents[2]
T1 = ROOT / "hw/common/socket3_signals.csv"
OUT = ROOT / "sockets/kicad/CPU_Socket3_Am5x86.kicad_sym"
PARTS = ROOT / "hw/lib/Socket3_Parts.kicad_sym"
MOD = ROOT / "sockets/kicad/Interposer.pretty/Socket3_Base_PGA168.kicad_mod"
FPGA = [("FPGA_CycloneV_5CEFA9_F484_FPGA", "FPGAlist/CycloneV_A9/pins/5ceba9_f484.csv"),
        ("FPGA_Ti180_TI180G400_FPGA", "FPGAlist/Ti180_G400/pins/ti180g400.csv")]

rows = list(csv.DictReader(T1.open()))
bus = [r for r in rows if r["class"] == "bus"]
data = [r for r in bus if re.fullmatch(r"DP?\d+", r["signal"])]
groups = [("Address, cycle definition and arbitration", [r for r in bus if r not in data]),
          ("Data and parity", data),
          ("Control, clock, test port and straps",
           [r for r in rows if r["class"] in ("control", "clock", "debug", "strap", "sideband")]),
          ("Power and internal NC", [r for r in rows if r["class"] in ("power", "nc")])]
units = [(name, *unit_pins(g)) for name, g in groups]
text = ('(kicad_symbol_lib (version 20241209) (generator "gen_socket3_lib.py")\n%s\n)\n'
        % rect_sym("Socket3_Am5x86_PGA168", "U", units,
                   "hw/common/socket3_signals.csv; sockets/socket3/amd_am5x86_19751C.pdf pp.8-9",
                   "Interposer:Socket3_Base_PGA168"))
OUT.write_text(text)

# SN74CB3T3245 pin numbers and functions [sockets/parts/ti_sn74cb3t3245.pdf
# p.3 Table 4-1], 20-pin TSSOP (PW)
CB3T = ([("NC", 1, "no_connect", "(at 12.7 -25.40 180)")]
        + [(f"A{k}", 1 + k, "passive", f"(at -12.7 {22.86 - 5.08 * k:.2f} 0)")
           for k in range(1, 9)]
        + [(f"B{k}", 19 - k, "passive", f"(at 12.7 {22.86 - 5.08 * k:.2f} 180)")
           for k in range(1, 9)]
        + [("GND", 10, "power_in", "(at 0 -30.48 90)"),
           ("OE#", 19, "input", "(at -12.7 -25.40 0)"),
           ("VCC", 20, "power_in", "(at 0 30.48 270)")])
cb3t = "\n".join(
    ['\t(symbol "SN74CB3T3245"', '\t\t(pin_names (offset 0.254))',
     '\t\t(exclude_from_sim no) (in_bom yes) (on_board yes)',
     '\t\t(property "Reference" "TR" (at 0 29.21 0) (effects (font (size 1.27 1.27))))',
     '\t\t(property "Value" "SN74CB3T3245" (at 0 -29.21 0) (effects (font (size 1.27 1.27))))',
     '\t\t(property "Footprint" "Package_SO:TSSOP-20_4.4x6.5mm_P0.65mm" (at 0 0 0) '
     '(hide yes) (effects (font (size 1.27 1.27))))',
     '\t\t(property "Datasheet" "sockets/parts/ti_sn74cb3t3245.pdf" (at 0 0 0) '
     '(hide yes) (effects (font (size 1.27 1.27))))',
     '\t\t(embedded_fonts no)', '\t\t(symbol "SN74CB3T3245_1_1"',
     '\t\t\t(rectangle (start -10.16 27.94) (end 10.16 -27.94) '
     '(stroke (width 0.254) (type default)) (fill (type background)))']
    + [f'\t\t\t(pin {el} line {at} (length 2.54) (name "{n}" (effects (font '
       f'(size 1.27 1.27)))) (number "{num}" (effects (font (size 1.27 1.27)))))'
       for n, num, el, at in CB3T]
    + ['\t\t)', '\t)'])
parts_text = ('(kicad_symbol_lib (version 20241209) (generator "gen_socket3_lib.py")\n'
              f'{cb3t}\n)\n')
PARTS.write_text(parts_text)


def balanced(s):
    depth, quoted = 0, False
    for ch in s:
        if ch == '"':
            quoted = not quoted
        elif not quoted and ch in "()":
            depth += 1 if ch == "(" else -1
            if depth < 0:
                return False
    return depth == 0


fails = []


def check(name, ok, detail=""):
    print("PASS" if ok else "FAIL", name, detail)
    if not ok:
        fails.append(name)


t1 = {(r["pin"], r["signal"]) for r in rows}
check("T1 rows = 168", len(t1) == 168, f"{len(t1)} rows")
check("units cover every T1 row once", sum(len(g) for _, g in groups) == len(rows),
      str([(n, len(g)) for n, g in groups]))
check("symbol s-expression balanced", balanced(text))
check("SN74CB3T3245: 20 distinct pins 1..20", sorted(c[1] for c in CB3T) == list(range(1, 21)))
check("SN74CB3T3245 library balanced", balanced(parts_text))
pins = set(re.findall(r'\(name "([^"]*)".*?\(number "([^"]*)"', text))
pins = {(num, name) for name, num in pins}
check("symbol pins match T1 pin+signal", pins == t1, f"diff: {sorted(pins ^ t1)[:8]}")
pads = set(re.findall(r'\(pad "([^"]+)"', MOD.read_text()))
check("footprint pads = symbol pin numbers", pads == {p for p, _ in t1},
      f"footprint {len(pads)} pads")
for name, csvp in FPGA:
    balls = {line.split(",")[0] for line in (ROOT / csvp).read_text().splitlines()[1:] if line}
    sym = ROOT / "hw/lib" / f"{name}.kicad_sym"
    numbers = set(re.findall(r'\(number "([^"]+)"', sym.read_text())) if sym.is_file() else set()
    check(f"FPGA symbol {name} pins = ball CSV", numbers == balls,
          f"sym {len(numbers)} vs csv {len(balls)}")
print(f"wrote {OUT.relative_to(ROOT)}, {PARTS.relative_to(ROOT)}")
sys.exit(1 if fails else 0)
