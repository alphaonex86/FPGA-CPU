#!/usr/bin/env python3
"""Task S6 (plan/slot1.md): generate the SC242 CPU schematic symbol.

sockets/kicad/CPU_SC242.kicad_sym: the 242-contact card edge as a 4-unit
symbol mirroring the CPU_Intel_PGA370 shape (pin name = signal text,
pin number = contact A* / B*). Units by signal family (from
hw/common/slot1_signals.csv):
  1 FSB address, request & arbitration   (bus minus data/parity)
  2 FSB data & parity                    (D[63:0], DEP[7:0])
  3 control, clocks, test port & straps  (+ sideband)
  4 power and reserved contacts
All logic pins are bidirectional (the cartridge peers both directions);
power/nc contacts are passive.

Checks (exit 1 on failure): totals add to 242; every contact has exactly
one unit; pin numbers unique; s-expression balanced.
"""
import collections
import csv
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
CSV = ROOT / "hw/common/slot1_signals.csv"
OUT = ROOT / "sockets/kicad/CPU_SC242.kicad_sym"


def pin(r, el, at, name):
    return ('(pin %s line %s (length 2.54) (name "%s" '
            '(effects (font (size 1.27 1.27)) (hide yes))) (number '
            '"%s" (effects (font (size 1.27 1.27)))))' % (el, at, name,
                                                          r["pin"]))


def rect_sym(name, ref, units, datasheet, footprint="Slot1:SC242_CardEdge_242"):
    """units: list of (unit_name, pins, box)"""
    head = [
        '\t(symbol "%s"' % name,
        '\t\t(pin_numbers (hide yes))',
        '\t\t(pin_names (offset 0.254))',
        '\t\t(exclude_from_sim no) (in_bom yes) (on_board yes)',
        '\t\t(property "Reference" "%s" (at 0 %.2f 0) (effects '
        '(font (size 1.27 1.27))))' % (ref, min(b[2][1] for b in units) - 1.27),
        '\t\t(property "Value" "%s" (at 0 %.2f 0) (effects '
        '(font (size 1.27 1.27))))' % (name, max(b[2][3] for b in units) + 1.27),
        '\t\t(property "Footprint" "%s" (at 0 0 0) '
        '(hide yes) (effects (font (size 1.27 1.27))))' % footprint,
        '\t\t(property "Datasheet" "%s" (at 0 0 0) (hide yes) (effects '
        '(font (size 1.27 1.27))))' % datasheet,
        '\t\t(embedded_fonts no)',
    ]
    body = []
    for uid, (uname, pins, box) in enumerate(units, 1):
        x0, y0, x1, y1 = box
        body += [
            '\t\t(symbol "%s_%d_1"' % (name, uid),
            '\t\t\t(unit_name "%s")' % uname,
            '\t\t\t(rectangle (start %.2f %.2f) (end %.2f %.2f) '
            '(stroke (width 0.254) (type default)) (fill (type background)))'
            % (x0, y0, x1, y1),
        ] + list(pins) + ['\t\t)']
    head += body + ['\t)']
    return "\n".join(head)


def unit_pins(rows, colsplit=True):
    rows = sorted(rows, key=lambda r: (r["pin"][0], int(r["pin"][1:])))
    cols = 2 if colsplit else 1
    per = (len(rows) + cols - 1) // cols
    cols = (len(rows) + per - 1) // per
    pins = []
    for k, r in enumerate(rows):
        col1 = min(k // per, cols - 1)
        row = k % per
        if col1 == 0:
            at = "(at -17.78 %.2f 0)" % (-2.54 * (row + 1))
        else:
            at = "(at 17.78 %.2f 180)" % (-2.54 * (row + 1))
        el = ("passive" if r["class"] in ("power", "nc", "sideband")
              else "bidirectional")
        pins.append(pin(r, el, at, r["signal"]))
    ys = [-2.54 * (per + 1), 2.54]
    return pins, (-15.24, ys[0], 15.24, ys[1])


def main():
    rows = list(csv.DictReader(open(CSV)))
    bus = [r for r in rows if r["class"] == "bus"]
    u2 = [r for r in bus if r["signal"].startswith(("D[", "DEP["))]
    u1 = [r for r in bus if r not in u2]
    u3 = [r for r in rows if r["class"] in ("control", "clock", "debug",
                                            "strap", "sideband")]
    u4 = [r for r in rows if r["class"] in ("power", "nc")]
    groups = [("FSB address, request and arbitration", u1),
              ("FSB data and parity", u2),
              ("Control, clocks, test port and straps", u3),
              ("Power and reserved contacts", u4)]
    n = sum(len(g[1]) for g in groups)
    if n != 242:
        sys.exit(f"unit totals {n} != 242")
    units, allnum = [], collections.Counter()
    for i, (uname, g) in enumerate(groups, 1):
        pl, box = unit_pins(g)
        units.append((uname, pl, box))
        for r in g:
            allnum[r["pin"]] += 1
    dups = [k for k, v in allnum.items() if v != 1]
    if dups:
        sys.exit(f"contact in more than one unit: {dups[:5]}")
    contacts = collections.Counter(r["pin"] for r in rows)
    if set(allnum) != set(contacts):
        sys.exit("units do not cover every contact")
    text = ('(kicad_symbol_lib (version 20241209) '
            '(generator "gen_slot1_cpu_sym.py")\n%s\n)\n'
            % rect_sym("Intel_SC242_CardEdge", "U", units,
                       "hw/common/slot1_signals.csv; "
                       "sockets/slot1/pentium2_350-450_sc242_24365703.pdf "
                       "Table 35"))
    OUT.write_text(text)
    d = 0
    q = False
    for ch in text:
        if ch == '"':
            q = not q
        elif ch == "(" and not q:
            d += 1
        elif ch == ")" and not q:
            d -= 1
        if d < 0:
            sys.exit("unbalanced")
    if d:
        sys.exit(f"parens balanced check failed at end: {d}")
    pins_total = (text.count('(pin bidirectional') +
                  text.count('(pin passive'))
    if pins_total != 242:
        sys.exit(f"pin instances {pins_total} != 242")
    print(f"wrote {OUT.relative_to(ROOT)} "
          f"(units: {[(g[0], len(g[1])) for g in groups]})")


if __name__ == "__main__":
    main()
