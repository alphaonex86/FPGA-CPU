#!/usr/bin/env python3
"""Interposer base for each socket: the CPU-side PGA pins, as a KiCad footprint,
its STEP model, and a check board that sits the base on the ZIF socket.

Pin positions are taken from the verified ZIF footprints in Sockets.pretty (same
top view, so the base footprint goes unmirrored on the interposer's F.Cu) and
must match the pin map exactly. The pins are a Mill-Max PGA header soldered under
the interposer: series 551 on the 2.54 mm grid, 550 on the interstitial grid
(Mill-Max metric catalog p.140; insulator size p.137, configured per pattern at
www.mill-max.com/pga).

    python3 sockets/kicad/tools/gen_base.py
"""
import csv
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import step_writer as sw

KICAD = os.path.dirname(HERE)
PCB = 1.6        # interposer board thickness
GRID = 2.54      # Mill-Max header lattice (interstitial pins sit on its half points)
GOLD = (0.76, 0.68, 0.38)
BLACK = (0.12, 0.12, 0.12)

# Mill-Max header pin, z in mm up from the seating face (the header's lowest
# rigid face, resting on the socket): male plug 0.48 x 3.91 below it on both.
# drill: tail diameter + ~0.22 mm; board: where the interposer's bottom sits.
HEADERS = {
    "550": dict(part="550-10-XXX-XX-XXX012 (pin #5012)", drill=0.80, pad=1.25, board=3.99,
                insulator=(0.0, 1.91), segments=[(0.48, -3.91, 0.0), (1.17, 1.91, 3.99), (0.58, 3.99, 8.16)]),
    "551": dict(part="551-10-XXX-XX-XXX003 (pin #5503)", drill=0.90, pad=1.50, board=6.40,
                insulator=(0.64, 3.43), segments=[(0.48, -3.91, 0.0), (1.6, 0.0, 5.61), (1.83, 5.61, 6.40),
                                                  (0.64, 6.40, 9.60)]),
}

# base name, ZIF footprint (= its STEP name), pin map, CPU package side (mm), header series, socket
SOCKETS = [
    ("Socket3_Base_PGA168", "Socket3_Am5x86_237", "am5x86_pga168.csv", 44.45, "551", "socket3"),      # AMD 19751C p66
    ("Socket7_Base_PGA296", "Socket7_P55C_296", "socket7_p55c.csv", 49.53, "550", "socket7"),          # Intel 243185-004 T17
    ("Socket370_Base_PGA370", "PGA370_Socket_ZIF", "pga370_coppermine.csv", 49.53, "550", "socket370"),  # Intel 245264-008 T35
]


def zif_pads(path):
    pads = {}
    for name, x, y, func in re.findall(r'\(pad "([^"]+)" thru_hole \w+ \(at ([-\d.]+) ([-\d.]+)\)'
                                       r'[^\n]*?(?:\(pinfunction "([^"]*)"\))?\)\s*$', open(path).read(), re.M):
        pads[name] = (float(x), float(y), func)
    return pads


def pin1_corner(pads):
    """Sign (sx, sy) of the package corner next to row A / the lowest column."""
    cells = {n: re.match(r"([A-Z]+)(\d+)$", n).groups() for n in pads}
    col1 = min(int(c) for _, c in cells.values())
    row_a = [pads[n][:2] for n, (r, _) in cells.items() if r == "A"]
    col_1 = [pads[n][:2] for n, (_, c) in cells.items() if int(c) == col1]
    corner = [0.0, 0.0]
    for group in (row_a, col_1):
        axis = 0 if len({p[0] for p in group}) == 1 else 1
        if len({p[axis] for p in group}) != 1:
            raise SystemExit("ERROR: row A / column %d is not a straight line" % col1)
        corner[axis] = math.copysign(1.0, group[0][axis])
    if 0.0 in corner:
        raise SystemExit("ERROR: pin-1 corner not found")
    return corner


def insulator(pins):
    """Mill-Max p.137: outer side A = N1 x 2.54, window C = N2 x 2.54 - 0.41."""
    field = max(max(abs(x), abs(y)) for x, y, _ in pins.values())
    inner = min(max(abs(x), abs(y)) for x, y, _ in pins.values())
    window = 2 * math.floor(inner / GRID + 1e-6) - 1
    return field * 2 + GRID, window * GRID - 0.41, field, inner


def outline(half, corner, chamfer):
    """Closed square with the pin-1 corner chamfered, as a point list."""
    sx, sy = corner
    pts = [(sx * half, sy * (half - chamfer)), (sx * half, -sy * half), (-sx * half, -sy * half),
           (-sx * half, sy * half), (sx * (half - chamfer), sy * half)]
    return pts + pts[:1]


def rect(half, layer, width):
    return ('  (fp_rect (start %.3f %.3f) (end %.3f %.3f) (layer "%s") (width %.2f) (fill none))'
            % (-half, -half, half, half, layer, width))


def footprint(name, zif, side, series, pins, corner, lib="", at="", models=()):
    h = HEADERS[series]
    half = side / 2.0
    outer, window, field, inner = insulator(pins)
    version = '' if lib else ' (version 20240108) (generator "gen_base.py")'
    out = ['(footprint "%s%s"%s' % (lib, name, version),
           '  (layer "F.Cu")' + at,
           '  (descr "Interposer base for %s: %d CPU pins on a Mill-Max %s header under the board '
           '(insulator %.2f mm, window %.2f mm), positions from Sockets.pretty/%s. F.Fab: CPU package %.2f mm.")'
           % (zif, len(pins), h["part"], outer, window, zif, side),
           '  (tags "interposer PGA base Mill-Max %s %s")' % (series, zif),
           '  (attr through_hole)',
           '  (fp_text reference "REF**" (at 0 %.3f) (layer "F.SilkS") (effects (font (size 1.5 1.5) (thickness 0.25))))'
           % (-half - 1.5),
           '  (fp_text value "%s" (at 0 %.3f) (layer "F.Fab") (effects (font (size 1.5 1.5) (thickness 0.25))))'
           % (name, half + 1.5),
           # tails stand above F.Cu over the pin ring only; the header body fills B side
           rect(field + h["pad"] / 2 + 0.25, "F.CrtYd", 0.05), rect(inner - h["pad"] / 2 - 0.25, "F.CrtYd", 0.05),
           rect(outer / 2 + 0.25, "B.CrtYd", 0.05), rect(window / 2 - 0.25, "B.CrtYd", 0.05),
           rect(outer / 2, "B.Fab", 0.1), rect(window / 2, "B.Fab", 0.1)]
    for layer, width in (("F.SilkS", 0.12), ("F.Fab", 0.1)):
        pts = outline(half, corner, 2.0)
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            out.append('  (fp_line (start %.3f %.3f) (end %.3f %.3f) (layer "%s") (width %.2f))'
                       % (x1, y1, x2, y2, layer, width))
    for pin, (x, y, func) in sorted(pins.items()):
        func = ' (pinfunction "%s")' % func if func else ''
        out.append('  (pad "%s" thru_hole circle (at %.4f %.4f) (size %.3f %.3f) (drill %.3f) '
                   '(layers "*.Cu" "*.Mask")%s)' % (pin, x, y, h["pad"], h["pad"], h["drill"], func))
    for step, z in models:
        out.append('  (model "${KIPRJMOD}/3dmodels/%s.step" (offset (xyz 0 0 %.3f)) '
                   '(scale (xyz 1 1 1)) (rotate (xyz 0 0 0)))' % (step, z))
    return "\n".join(out) + "\n)\n"


def cylinder(x, y, diameter, z0, z1, sides=8):
    r = diameter / 2.0
    return sw.prism([(x + r * math.cos(2 * math.pi * i / sides), y + r * math.sin(2 * math.pi * i / sides))
                     for i in range(sides)], z0, z1)


def header_solids(series, pins):
    """STEP solids in footprint z (0 = board top): pins, then the insulator ring."""
    h = HEADERS[series]
    seat = -(PCB + h["board"])
    solids = [(cylinder(x, -y, d, seat + z0, seat + z1), GOLD, "pin_%s_%d" % (n, i))
              for n, (x, y, _) in sorted(pins.items()) for i, (d, z0, z1) in enumerate(h["segments"])]
    outer, window, _, _ = insulator(pins)
    a, c = outer / 2, window / 2
    z0, z1 = seat + h["insulator"][0], seat + h["insulator"][1]
    for i, (x0, x1, y0, y1) in enumerate(((-a, a, c, a), (-a, a, -a, -c), (-a, -c, -c, c), (c, a, -c, c))):
        solids.append((sw.box(x0, x1, y0, y1, z0, z1), BLACK, "insulator_%d" % i))
    return solids, seat


def write_if_changed(path, text, compare=lambda t: t):
    if os.path.isfile(path) and compare(open(path).read()) == compare(text):
        return
    with open(path, "w") as f:
        f.write(text)


def step_top(path):
    """Highest z of a STEP model: where the base rests on the socket."""
    return max(float(m) for m in re.findall(r"CARTESIAN_POINT\('[^']*',\([^,]+,[^,]+,([^)]+)\)\)",
                                            open(path).read()))


def check_board(name, zif, side, series, pins, corner, socket_z):
    x0, y0 = 150.0, 100.0
    fp = footprint(name, zif, side, series, pins, corner, lib="Interposer:", at=" (at %.1f %.1f)" % (x0, y0),
                   models=((name, 0.0), (zif, socket_z)))
    half = side / 2.0 + 0.5  # board edge just outside the package silk
    return ('(kicad_pcb (version 20240108) (generator "gen_base.py")\n'
            '  (general (thickness %.2f))\n  (paper "A4")\n'
            '  (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (36 "B.SilkS" user) (37 "F.SilkS" user)\n'
            '    (38 "B.Mask" user) (39 "F.Mask" user) (44 "Edge.Cuts" user) (46 "B.CrtYd" user)\n'
            '    (47 "F.CrtYd" user) (48 "B.Fab" user) (49 "F.Fab" user))\n'
            '  (setup (pad_to_mask_clearance 0))\n  (net 0 "")\n'
            '  (gr_rect (start %.3f %.3f) (end %.3f %.3f) (layer "Edge.Cuts") (width 0.1) (fill none))\n'
            % (PCB, x0 - half, y0 - half, x0 + half, y0 + half)
            + fp.replace("\n  ", "\n    ").replace("(footprint", "  (footprint", 1).rstrip() + "\n)\n")


def main():
    for name, zif, pinmap, side, series, socket in SOCKETS:
        pins_csv = {r["pin"] for r in csv.DictReader(open(os.path.join(KICAD, "pinmaps", pinmap)))}
        pads = zif_pads(os.path.join(KICAD, "Sockets.pretty", zif + ".kicad_mod"))
        pins = {n: p for n, p in pads.items() if n in pins_csv}
        if set(pins) != pins_csv:
            raise SystemExit("ERROR: %s: pins missing from %s: %s" % (name, zif, sorted(pins_csv - set(pins))))
        outer, window, field, inner = insulator(pins)
        if window / 2 > inner - HEADERS[series]["pad"] / 2:
            raise SystemExit("ERROR: %s: the insulator window cuts into the pin ring" % name)
        corner = pin1_corner(pins)
        os.makedirs(os.path.join(KICAD, "Interposer.pretty"), exist_ok=True)
        write_if_changed(os.path.join(KICAD, "Interposer.pretty", name + ".kicad_mod"),
                         footprint(name, zif, side, series, pins, corner, models=((name, 0.0),)))
        solids, seat = header_solids(series, pins)
        step = os.path.join(KICAD, "3dmodels", name + ".step")
        tmp = step + ".new"
        sw.write_step(tmp, solids, name, "%s interposer base: Mill-Max %s header under a %.1f mm board"
                      % (zif, HEADERS[series]["part"], PCB))
        write_if_changed(step, open(tmp).read(), sw._destamp)
        os.remove(tmp)
        top = step_top(os.path.join(KICAD, "3dmodels", zif + ".step"))
        write_if_changed(os.path.join(KICAD, "%s-base-check.kicad_pcb" % socket),
                         check_board(name, zif, side, series, pins, corner, seat - top))
        print("%s: %d pins, Mill-Max %s, insulator %.2f / window %.2f mm, board %.2f mm above the socket, "
              "pin 1 corner %s" % (name, len(pins), series, outer, window, -seat - PCB, corner))


if __name__ == "__main__":
    main()
