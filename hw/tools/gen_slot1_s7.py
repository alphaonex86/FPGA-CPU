#!/usr/bin/env python3
"""Task S7 (plan/slot1.md): PCB placement + outline + clip keep-outs.

hw/slot1-cyclonev/slot1-cyclonev.kicad_pcb: the substrate per D16
(127.0 mm x 57.8 mm = 5.000 x 2.275 in [celeron_sepp Fig 17 p 44],
1.57 mm thick) with footprints placed:
card edge (U2) on the insertion edge with its A1 station 4.0 mm from the
left end [DG Fig 1: A1 offset 0.157 in], FPGA (U1) centre, 4 DDR3L dies
(NM24 2-rank tetra grid), 20 translators in four columns, VTT tracker
and headers (F-JTAG, passive-serial config, 12 V barrel, board rail
feed), and the D23 power tree + decoupling of pdn.csv (S6): regulator
stages column-packed in the strip y 47.0..57.8 the D16 growth added, U1
small capacitors on B.Cu over its supply/GND via-in-pad pairs (D25),
the rest below U1, translator capacitors on B.Cu on the VCCA/VCCB stitch
vias, DDR3 die capacitors in the free F.Cu right of and below the dies
(B.Cu under the dies is their escape layer).  Keep-out zones: the connector cavity band (y 3.5..7.0, no
footprints: finger faces reach y 3.5, and the connector plastic shadows
the band above them per DG Fig 4/6), the key notch mouth (no
tracks/vias, finger necks per DG Detail A) and the SECC retention bands
at both ends x<16/x>111 (no footprints; exact engagement numbers pending
D16/NM11).  Pads are unnetted here; the S8 router starts from this file.

For the DRC gate kicad-cli honours a COMPLETE .kicad_pro next to the
board (KiCad 10.0.3 verified: edge clearance follows
board.design_settings.rules.min_copper_edge_clearance; 0.0 means
"unset").  The pro comes from the Edgeberry template with
min_copper_edge_clearance = 0.001 mm and the card edge (U2) is placed
2 um off the insertion edge (electro-optically identical to the DG242
flush land, inside the fab's edge tolerance; NM25).  A project
fp-lib-table registers the five footprint libraries so the inlined
S7/S8 footprints pass the library DRC check.

Checks (exit 1 on failure): 242 card-edge pads; A1 at 4.0 mm; key notch
stations 76/77 when milled; every S6 footprint reference placed; and
kicad-cli pcb drc --severity-error: 0 violations.
"""
import csv
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "hw/slot1-cyclonev"
W, H = 127.0, 57.8                     # D16: 5.000 x 2.275 in
A1_X = 4.000                           # DG Fig 1: 0.157 in from the left end
KEY_C = A1_X + 72.5                    # key centre: Fig 1 2.992 - 0.157 in
KEY_W, KEY_D = 2.0, 2.49               # key slot width, 0.098 in depth
CHAM = 2.49                            # lead-in chamfer (0.098 in, Fig 2)
RET = 16.0                             # retention band width (NM11 pending)


def module_pads(path, head=r"\(pad \""):
    """(pad ...) blocks (or other blocks matching head) of a footprint file"""
    t = path.read_text()
    out = []
    for m in re.finditer(head, t):
        d, i, e = 0, m.start(), 0
        while i < len(t):
            if t[i] == "(":
                d += 1
            elif t[i] == ")":
                d -= 1
                if d == 0:
                    e = i + 1
                    break
            i += 1
        out.append(t[m.start():e].strip())
    return out


def fp(name, refdes, x, y, pads, cyd, attr="smd", side="F"):
    """inline footprint; reference text on F.Fab kept inside the outline
    (references on F.SilkS raised silk-over-copper DRC errors when a text
    crossed a zone outline; this flat board carries no silkscreen yet --
    silk labels are the S9 polish)."""
    ref_y = cyd[3] + 0.8
    mirror = " (justify mirror)" if side == "B" else ""
    lines = [
        '\t(footprint "%s"' % name,
        '\t\t(layer "%s.Cu")' % side,
        '\t\t(at %f %f)' % (x, y),
        '\t\t(descr "S7 placement; nets assigned by S8")',
        '\t\t(attr %s)' % attr,
        '\t\t(fp_text reference "%s" (at 0.0 %f) (layer "%s.Fab") '
        '(effects (font (size 1 1) (thickness 0.15))%s))'
        % (refdes, ref_y, side, mirror),
        '\t\t(fp_text value "%s" (at 0.0 %f) (layer "%s.Fab") '
        '(effects (font (size 1 1) (thickness 0.15))%s))'
        % (refdes, ref_y + 1.4, side, mirror),
    ]
    lines.append('\t\t(fp_rect (start %f %f) (end %f %f) (layer "%s.CrtYd") '
                 '(width 0.05))' % (*cyd, side))
    for p in pads:
        lines.append("\t\t" + p)
    lines.append("\t)")
    return "\n".join(lines)


def emit_lib(out_text):
    """write hw/lib/<Lib>.pretty/<Footprint>.kicad_mod from an inline
    footprint so the library that kicad-cli resolves contains the same
    pad geometry the board carries (S8 verifies pad-to-pin match)"""
    lib, name = (out_text.split('(footprint "')[-1].split('"')[0]).split(":")
    path = ROOT / "hw/lib" / ("%s.pretty" % lib) / ("%s.kicad_mod" % name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(out_text.replace('(footprint "%s:%s"' % (lib, name),
                                     '(footprint "%s"' % name) + "\n")


def bga96_pads():
    """generic 96-land die grid: 6 columns x 16 rows, 0.8 mm pitch (the
    real MT41K512M16HA FBGA ball map, Fig 7 of the 8Gb datasheet, is the
    S8 refinement).  Land names are unique ball codes; the S6 die-symbol
    pins get their nets at S8."""
    rows = "ABCDEFGHJKLMNPRT"
    out = []
    k = 0
    for ri, r in enumerate(rows):
        for c in range(6):
            k += 1
            out.append('\t(pad "B%02d" smd circle (at %.2f %.2f) '
                       '(size 0.45 0.45) (layers "F.Cu" "F.Mask"))'
                       % (k, (c - 2.5) * 0.8, (ri - 7.5) * 0.8))
    return out


def tssop20_pads():
    pins = ["A8", "A7", "A6", "A5", "A4", "A3", "A2", "A1", "GND", "VCCA",
            "VCCB", "NC", "B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8"]
    out = []
    for k, p in enumerate(pins):
        side, r = (0, k) if k < 10 else (1, 19 - k)
        px = (-3.845 + r * 0.65) if side == 0 else (3.845 - r * 0.65)
        py = -2.675 if side == 0 else 2.675
        out.append('\t(pad "%s" smd rect (at %.2f %.2f) (size 0.32 1.1) '
                   '(layers "F.Cu" "F.Paste" "F.Mask"))' % (p, px, py))
    return out


def conn_pads(n, two_rows=True, pitch=2.54):
    """header lands laid sideways: columns along X, two rows at Y = +-
    pitch/2 (odd/even), pin numbers column-major as in the schematic;
    columns centred on X (odd row counts span k*pitch - (n-1)*pitch/2)"""
    out = []
    for num in range(1, n + 1):
        k = num - 1
        if two_rows:
            C = (n + 1) // 2
            px = (k // 2 - (C - 1) / 2) * pitch
            py = (k % 2 - 0.5) * pitch
        else:
            px = k * pitch - (n - 1) * pitch / 2
            py = 0.0
        out.append('\t(pad "%d" thru_hole circle (at %.2f %.2f) '
                   '(size 1.5 1.5) (drill 0.9) (layers "*.Cu" "*.Mask"))'
                   % (num, px, py))
    return out


def tracker_pads():
    """VTT tracker lands, single row 2.54 pitch, named as the S6 symbol"""
    out = []
    for k, p in enumerate(["VIN", "VTT", "VTTSNS", "VDDQ_REF", "GND"]):
        px = k * 2.54 - 5.08
        out.append('\t(pad "%s" thru_hole circle (at %.2f 0.00) '
                   '(size 1.5 1.5) (drill 0.9) (layers "*.Cu" "*.Mask"))'
                   % (p, px))
    return out


def edge_pads():
    """card edge pads from the S4 footprint, with stations 73/74 stepped
    (head+neck per DG Detail A: the key notch cuts their face tip)"""
    src = module_pads(ROOT / "hw/lib/Slot1.pretty/"
                      "SC242_CardEdge_242.kicad_mod")
    out = []
    for p in src:
        m = re.match(r'\(pad "([AB](73|74))"', p)
        if m:
            face = m.group(1)[0]                 # A = top face (F.Cu),
            cu = "F" if face == "A" else "B"     # B = bottom face (B.Cu)
            x = 72.0 if m.group(2) == "73" else 73.0
            p = ('(pad "%s" smd rect\n\t\t(at %.3f 3.00)\n'
                 '\t\t(size 0.60 1.00)\n'
                 '\t\t(layers "%s.Cu" "%s.Paste" "%s.Mask")\n'
                 '\t\t(remove_unused_layers no))'
                 % (m.group(1), x, cu, cu, cu))
        out.append(p)
    return out


def tr_stitch(pads):
    """S8b translator stitch-via points, local: per pad row the power pads
    in x order get a via 0.675 mm inboard, each next one 0.8 mm deeper.
    pads = [(name, lx, ly)]; returns {name: (vx, vy)}"""
    rows = {}
    for name, lx, ly in sorted(pads, key=lambda p: p[1]):
        rows.setdefault(round(ly / 2.675), []).append((name, lx))
    out = {}
    for rowk, pins in rows.items():
        sgn = 1 if rowk < 0 else -1
        for k, (name, lx) in enumerate(pins):
            out[name] = (lx, rowk * 2.675 + sgn * (0.675 + 0.8 * k))
    return out


def stock_pads(lib, name):
    """named pads + courtyard bbox of a stock KiCad footprint"""
    path = pathlib.Path("/usr/share/kicad/footprints/%s.pretty/%s.kicad_mod"
                        % (lib, name))
    pads = [p for p in module_pads(path)            # drop paste-only pads
            if not re.match(r'\(pad "" smd', p)]
    pts = [(float(a), float(b))
           for blk in module_pads(path, r"\(fp_(?:line|rect|poly)")
           if '"F.CrtYd"' in blk
           for a, b in re.findall(r'\((?:start|end|xy) (-?[\d.]+) (-?[\d.]+)\)',
                                  blk)]
    assert pts and pads, (lib, name)
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return pads, (min(xs), min(ys), max(xs), max(ys))


def cap_pair_pads():
    """0402 on two via-in-pads at the 1.0 mm BGA / stitch-via pitch"""
    return (['(pad "%d" smd rect (at %.2f 0) (size 0.50 0.55) '
             '(layers "F.Cu" "F.Paste" "F.Mask"))' % (k + 1, x)
             for k, x in enumerate((-0.5, 0.5))], (-0.8, -0.4, 0.8, 0.4))


def rhl0014a_pads():
    """TPS54620 RHL0014A land pattern [tps54620 p.45]: 14 x 0.6 x 0.24
    pads on a 3.3 mm centre square, 0.5 mm pitch, corner pins 1/14 (top)
    and 7/8 (bottom) at x -/+0.75; exposed pad 15 2.05 x 2.05"""
    pos = {"1": (-0.75, -1.65, 0.24, 0.6), "14": (0.75, -1.65, 0.24, 0.6),
           "7": (-0.75, 1.65, 0.24, 0.6), "8": (0.75, 1.65, 0.24, 0.6)}
    for k in range(5):
        pos[str(2 + k)] = (-1.65, -1.0 + 0.5 * k, 0.6, 0.24)
        pos[str(9 + k)] = (1.65, 1.0 - 0.5 * k, 0.6, 0.24)
    pos["15"] = (0.0, 0.0, 2.05, 2.05)
    return (['(pad "%s" smd rect (at %.2f %.2f) (size %.2f %.2f) '
             '(layers "F.Cu" "F.Paste" "F.Mask"))' % (n, *v)
             for n, v in pos.items()], (-2.25, -2.25, 2.25, 2.25))


CUSTOM = {"C_0402_P1.00": cap_pair_pads, "TI_RHL0014A": rhl0014a_pads}


def orient(pads, cyd, d, side):
    """rotate so pad 1 -> pad 2 points along d (+x, -x, +y, -y), move to
    side (F/B); returns pads, courtyard"""
    def rot(x, y):
        return {"+x": (x, y), "-x": (-x, -y), "+y": (-y, x),
                "-y": (y, -x)}[d]
    out = []
    for p in pads:
        m = re.search(r"\(at (-?[\d.]+) (-?[\d.]+)( -?[\d.]+)?\)", p)
        x, y = rot(float(m.group(1)), float(m.group(2)))
        p = p.replace(m.group(0), "(at %.4f %.4f%s)" % (x, y, m.group(3) or ""))
        s = re.search(r"\(size ([\d.]+) ([\d.]+)\)", p)
        if d in ("+y", "-y") and not m.group(3):
            p = p.replace(s.group(0), "(size %s %s)" % (s.group(2), s.group(1)))
        if side == "B":
            p = re.sub(r'"F\.(Cu|Paste|Mask)"', r'"B.\1"', p)
        out.append(p)
    c = [rot(cyd[0], cyd[1]), rot(cyd[2], cyd[3])]
    return out, (min(c[0][0], c[1][0]), min(c[0][1], c[1][1]),
                 max(c[0][0], c[1][0]), max(c[0][1], c[1][1]))


def pdn_footprint(fpname):
    lib, name = fpname.split(":")
    return CUSTOM[name]() if lib == "Pwr" else stock_pads(lib, name)


class Packer:
    """column fill of courtyard boxes over regions (x0, y0, x1, y1, dir):
    every part in a region is oriented along its dir"""
    def __init__(self, regions, gap=0.1):
        self.regions, self.gap, self.ri = regions, gap, 0
        self.x, self.y, self.colw = regions[0][0], regions[0][1], 0.0

    def newcol(self):
        if self.colw:
            self.x += self.colw + self.gap
            self.y, self.colw = self.regions[self.ri][1], 0.0

    def put(self, size_of, ok=lambda at, d: True):
        """size_of(dir) -> (w, h); returns centre, dir; spots where
        ok(centre, dir) is false are skipped"""
        while True:
            x0, y0, x1, y1, d = self.regions[self.ri]
            w, h = size_of(d)
            if self.y + h <= y1 and self.x + w <= x1:
                if ok((self.x + w / 2, self.y + h / 2), d):
                    break
                self.y += 0.2
                continue
            if self.colw and self.x + self.colw + self.gap + w <= x1:
                self.newcol()
                continue
            self.ri += 1
            if self.ri == len(self.regions):
                raise SystemExit("FAIL: no room left for a %.2f x %.2f part"
                                 % (w, h))
            self.x, self.y, self.colw = (self.regions[self.ri][0],
                                         self.regions[self.ri][1], 0.0)
        at = (self.x + w / 2, self.y + h / 2)
        self.y += h + self.gap
        self.colw = max(self.colw, w)
        return at, d


STAGES = ["F1", "PS1", "PS2", "PS4", "PS5", "PS3", "PS6"]   # 12 V side first
STRIP = [(28.3, 47.0, 110.7, 57.6, "+x")]          # right of J3, retention clear
BELOW_U1 = [(58.3, 39.1, 83.6, 46.95, "+x")]
DIE_FREE = [(108.6, 7.6, 110.95, 40.6, "+y"), (84.0, 41.0, 97.8, 46.95, "+x")]


def pdn_place(u1_xy, u1_local, tr_at, tss):
    """footprint texts + library prototypes of every pdn.csv row"""
    rows = list(csv.DictReader(open(OUT / "pdn.csv")))
    out, protos = [], {}
    tr_power = [(n, float(x), float(y)) for n, x, y in re.findall(
        r'\(pad "(GND|VCCA|VCCB)" smd rect \(at (-?[\d.]+) (-?[\d.]+)\)',
        "\n".join(tss))]
    tr_via = tr_stitch(tr_power)

    copper = {"F": [], "B": []}           # placed pad boxes per side

    def pad_boxes(pads, x, y):
        """(cx, cy, half w, half h); a rotated stock pad counts square"""
        for p in pads:
            m = re.search(r"\(at (-?[\d.]+) (-?[\d.]+)( -?[\d.]+)?\)", p)
            w, h = (float(v) / 2 for v in re.search(
                r"\(size ([\d.]+) ([\d.]+)\)", p).groups())
            if m.group(3):
                w = h = max(w, h)
            yield x + float(m.group(1)), y + float(m.group(2)), w, h

    def via_clear(pads, x, y, side):
        """S8b drills a through via in pad centres: no via of one side may
        land within 0.45 mm (via radius + clearance) of the other's pads"""
        other = copper["B" if side == "F" else "F"]
        return not any(abs(px - qx) < max(pw, qw) + 0.45
                       and abs(py - qy) < max(ph, qh) + 0.45
                       for px, py, pw, ph in pad_boxes(pads, x, y)
                       for qx, qy, qw, qh in other)

    def emit(row, x, y, d, side=None):
        side = side or row["side"]
        pads, cyd = pdn_footprint(row["footprint"])
        name = "Pwr:" + row["footprint"].split(":")[1]
        protos.setdefault(name, fp(name, "REF", 0.0, 0.0, pads, cyd))
        pads, cyd = orient(pads, cyd, d, side)
        copper[side] += pad_boxes(pads, x, y)
        out.append(fp(name, row["ref"], x, y, pads, cyd, side=side))

    def packed(group, packer, side=None):
        for row in group:
            def box(d):
                return orient(*pdn_footprint(row["footprint"]), d, "F")[1]

            def ok(at, d):
                cyd = box(d)
                return via_clear(
                    orient(*pdn_footprint(row["footprint"]), d, "F")[0],
                    at[0] - (cyd[0] + cyd[2]) / 2,
                    at[1] - (cyd[1] + cyd[3]) / 2, side or row["side"])

            (cx, cy), d = packer.put(lambda d: (box(d)[2] - box(d)[0],
                                                box(d)[3] - box(d)[1]), ok)
            cyd = box(d)
            emit(row, cx - (cyd[0] + cyd[2]) / 2, cy - (cyd[1] + cyd[3]) / 2, d,
                 side)

    def area(row):
        cyd = pdn_footprint(row["footprint"])[1]
        return -(cyd[2] - cyd[0]) * (cyd[3] - cyd[1])

    # each stage: power parts on F.Cu, its 0402 parts (and F1) on B.Cu
    # below them (D16 amendment: both sides)
    strip, bstrip = Packer(STRIP), Packer(STRIP)
    for st in STAGES:
        strip.newcol()
        bstrip.newcol()
        bstrip.x = max(bstrip.x, strip.x)
        group = sorted((r for r in rows if r["kind"] == "stage"
                        and r["a"] == st), key=area)
        back = st == "F1" or None             # the fuse rides B.Cu too
        packed([r for r in group if "0402" not in r["footprint"]
                and not back], strip)
        packed([r for r in group if "0402" in r["footprint"] or back],
               bstrip, "B")
    packed([r for r in rows if r["kind"] == "u1bulk"], Packer(BELOW_U1))
    packed([r for r in rows if r["kind"] == "die"], Packer(DIE_FREE))
    for r in rows:
        if r["kind"] == "u1pair":
            (sx, sy), (gx, gy) = u1_local[r["a"]], u1_local[r["b"]]
            d = "+x" if gx > sx else "-x" if gx < sx else "+y" if gy > sy else "-y"
            emit(r, u1_xy[0] + (sx + gx) / 2, u1_xy[1] + (sy + gy) / 2, d)
        elif r["kind"] == "trpin":
            tx, ty = tr_at[r["a"]]
            vx, vy = tr_via[r["b"]]
            d = "+y" if vy < 0 else "-y"              # pad 2 (GND) inboard
            emit(r, tx + vx, ty + vy + (0.5 if vy < 0 else -0.5), d)
    assert len(out) == len(rows), (len(out), len(rows))
    return out, list(protos.values())


def keepout(x0, y0, x1, y1, footprints, uid):
    return (
        '\t(zone (net 0) (net_name "") (layers "F.Cu") (uuid "%s")\n'
        '\t\t(hatch edge 0.5)\n'
        '\t\t(connect_pads (clearance 0))\n'
        '\t\t(min_thickness 0.25) (filled_areas_thickness no)\n'
        '\t\t(keepout (tracks allowed) (vias allowed) (pads allowed) '
        '(copperpour not_allowed) (footprints %s))\n'
        '\t\t(placement (enabled yes))\n'
        '\t\t(fill (thermal_gap 0.5) (thermal_bridge_width 0.5))\n'
        '\t\t(polygon (pts (xy %f %f) (xy %f %f) (xy %f %f) (xy %f %f)))\n'
        '\t)\n' % (uid, footprints, x0, y0, x1, y1, x1, y1, x0, y1))


def keepout_no_tracks(x0, y0, x1, y1, uid):
    return (
        '\t(zone (net 0) (net_name "") (layers "F.Cu") (uuid "%s")\n'
        '\t\t(hatch edge 0.5)\n'
        '\t\t(connect_pads (clearance 0))\n'
        '\t\t(min_thickness 0.25) (filled_areas_thickness no)\n'
        '\t\t(keepout (tracks not_allowed) (vias not_allowed) (pads allowed) '
        '(copperpour not_allowed) (footprints allowed))\n'
        '\t\t(placement (enabled yes))\n'
        '\t\t(fill (thermal_gap 0.5) (thermal_bridge_width 0.5))\n'
        '\t\t(polygon (pts (xy %f %f) (xy %f %f) (xy %f %f) (xy %f %f)))\n'
        '\t)\n' % (uid, x0, y0, x1, y1, x1, y1, x0, y1))


def main():
    # ---- card edge (U2) ----------------------------------------------
    edge = edge_pads()
    nedge = sum(1 for p in edge if p.startswith("(pad"))
    # 55 um recess of the whole land pattern off the insertion edge: the
    # donor footprint is flush (tips at y=0) but kicad-cli measures the
    # edge DRC to the Edge.Cuts stroke edge (0.1 mm stroke -> +0.05 mm
    # onto the board), so the gate needs tips above the stroke plus the
    # 0.001 mm rule (0.055 - 0.05 = 0.005 mm gap).  Inside every PCB fab's
    # edge tolerance and invisible against the DG242 flush land (NM25).
    u2 = fp("Slot1:SC242_CardEdge_242", "U2", A1_X, 0.055, edge,
            (-2.0, -2.0, 123.0, 3.4))

    # ---- FPGA ---------------------------------------------------------
    fq = module_pads(ROOT / "hw/lib/Interposer.pretty/"
                     "FPGA_CycloneV_5CEFA9_F484_BGA.kicad_mod")
    u1 = fp("Interposer:FPGA_CycloneV_5CEFA9_F484_BGA", "U1", 71.0, 27.0,
            fq, (-11.75, -11.75, 11.75, 11.75))

    # ---- dies, tracker, translators, headers --------------------------
    # DDR3 rows clear the cavity zone (courtyard top >= 7.0 and <= 40.0)
    dies = []
    # courtyard = HA body 9 x 14 mm + 0.25 [Micron 8Gb DDR3L Fig 9 p 24];
    # columns 9.75 apart so the courtyards never touch
    for k, (X, Y) in enumerate([(94.0, 15.5), (94.0, 32.5),
                                (103.75, 15.5), (103.75, 32.5)]):
        dies.append(fp("DDR3:FBGA96_x16", "U%d" % (3 + k), X, Y,
                       bga96_pads(), (-4.75, -7.25, 4.75, 7.25)))
    u7 = fp("TPS:VTT_tracker", "U7", 104.0, 43.6, tracker_pads(), (
        -6.0, -2.5, 6.0, 2.5), attr="through_hole")
    tss = tssop20_pads()
    translators = []
    tr_at = {}
    tk = 0
    for cc in range(4):
        for rr in range(5):
            tk += 1
            tr_at["TR%02d" % tk] = ([22.0, 32.0, 42.0, 52.0][cc],
                                    10.4 + 6.85 * rr)
            translators.append(fp(
                "TPS:Translator_TSSOP20", "TR%02d" % tk, *tr_at["TR%02d" % tk],
                tss, (-5.0, -3.25, 5.0, 3.25)))
    u1_local = {m.group(1): (float(m.group(2)), float(m.group(3))) for m in (
        re.match(r'\(pad "(\w+)" smd \w+ \(at (-?[\d.]+) (-?[\d.]+)\)', p)
        for p in fq)}
    pdn, protos = pdn_place((71.0, 27.0), u1_local, tr_at, tss)
    js = []
    js.append(fp("Conn:Header_2x03", "J1", 32.0, 44.0,
                 conn_pads(6, True), (-3.8, -1.6, 3.8, 1.6),
                 attr="through_hole"))
    js.append(fp("Conn:Header_2x05", "J2", 42.5, 44.0,
                 conn_pads(10, True), (-6.3, -1.6, 6.3, 1.6),
                 attr="through_hole"))
    # 12 V jack, mouth (body y +12) flush with the top edge, the only edge
    # reachable with the card in the slot
    js.append(fp("Conn:BarrelJack_CUI_PJ-063AH_Horizontal", "J3", 22.1,
                 H - 12.0, *stock_pads("Connector_BarrelJack",
                                       "BarrelJack_CUI_PJ-063AH_Horizontal"),
                 attr="through_hole"))
    js.append(fp("Conn:Header_1x03", "J4", 53.0, 44.0,
                 conn_pads(3, False), (-3.8, -2.9, 3.8, 2.9),
                 attr="through_hole"))

    # ---- outline -------------------------------------------------------
    o = [(0.0, 0.0), (KEY_C - KEY_W / 2, 0.0), (KEY_C - KEY_W / 2, KEY_D),
         (KEY_C + KEY_W / 2, KEY_D), (KEY_C + KEY_W / 2, 0.0),
         (W - CHAM, 0.0), (W, CHAM), (W, H), (CHAM, H), (0.0, H - CHAM)]
    seg = []
    for k in range(len(o)):
        x0, y0 = o[k]
        x1, y1 = o[(k + 1) % len(o)]
        seg.append('\t(gr_line (start %f %f) (end %f %f) '
                   '(layer "Edge.Cuts") (width 0.1))' % (x0, y0, x1, y1))

    # connector cavity band y 3.5..7.0: finger faces end at y 3.5 and
    # the connector body shadows the band above them (DG Fig 4/6)
    text = "\n".join(
        ['(kicad_pcb (version 20240108) (generator "gen_slot1_s7")',
         '\t(general (thickness 1.57))',
         '\t(paper "A4")',
         '\t(layers (0 "F.Cu" signal) (31 "B.Cu" signal) (36 "B.SilkS" user)'
         ' (37 "F.SilkS" user) (38 "B.Mask" user) (39 "F.Mask" user)'
         ' (44 "Edge.Cuts" user) (46 "B.CrtYd" user) (47 "F.CrtYd" user)'
         ' (48 "B.Fab" user) (49 "F.Fab" user))',
         '\t(setup (pad_to_mask_clearance 0))',
         '\t(net 0 "")']) + "\n" + \
        keepout(0.0, 3.5, W, 7.0, "not_allowed",
                "10000000-0007-4000-8000-000000000001") + \
        keepout(0.0, 7.0, RET, H, "not_allowed",
                "10000000-0007-4000-8000-000000000002") + \
        keepout(W - RET, 7.0, W, H, "not_allowed",
                "10000000-0007-4000-8000-000000000003") + \
        keepout_no_tracks(KEY_C - 1.0, 0.0, KEY_C + 1.0, KEY_D,
                          "10000000-0007-4000-8000-000000000004") + \
        "\n".join(seg) + "\n" + "\n".join(
            [u1, u2, u7] + dies + translators + js + pdn) + "\n)\n"
    path = OUT / "slot1-cyclonev.kicad_pcb"
    path.write_text(text)

    # ---- footprint libraries (kicad-cli DRC resolves nicknames) -------
    # Slot1 / Interposer come from S4 and are untouched; the placeholder
    # libs get one .kicad_mod per unique footprint, emitted from the
    # same inline body so library and board never drift.
    for out_text in [u7] + translators + js + dies + protos:
        emit_lib(out_text)
    (OUT / "fp-lib-table").write_text(
        "(fp_lib_table\n  (version 7)\n" + "".join(
            '  (lib (name "%s")(type "KiCad")(uri "${KIPRJMOD}/../lib/%s.pretty")'
            '(options "")(descr "Slot 1 interposer footprint set"))\n'
            % (L, L) for L in ("Slot1", "Interposer", "DDR3", "TPS", "Conn", "Pwr")
        ) + ")\n")

    # ---- project settings (kicad-cli DRC rule source) ------------------
    # kicad-cli honours board.design_settings.rules from the sibling
    # .kicad_pro only when the FULL settings tree is present; start from
    # the KiCad template and keep any S6 project keys.
    pro_path = OUT / "slot1-cyclonev.kicad_pro"
    pro = json.loads(pro_path.read_text()) if pro_path.exists() else {}
    tmpl = json.loads((pathlib.Path("/usr/share/kicad/template/"
                       "Edgeberry_Cartridge/"
                       "Edgeberry_cartridge_template.kicad_pro")).read_text())
    pro.setdefault("meta", tmpl["meta"])
    pro["meta"]["filename"] = "slot1-cyclonev.kicad_pro"
    pro.setdefault("board", {})
    pro["board"]["design_settings"] = tmpl["board"]["design_settings"]
    pro["board"]["design_settings"]["rules"]["min_copper_edge_clearance"] = \
        0.001                      # DRC gate for the 2 um edge recess
    # D23 (S8c BGA escape world): the fill lattice walks need 0.15 tracks
    # and 0.15 hole clearance inside the 1.0 mm U1 / 0.8 mm die fields;
    # the floors are the only absolute values, tracks away from the BGA
    # fields stay 0.2 by convention (Default class keeps track_width 0.2,
    # clearance drops to 0.15 so an esc route never inherits a stricter
    # neighbour class).
    rules = pro["board"]["design_settings"]["rules"]
    rules["min_track_width"] = 0.15
    rules["min_hole_clearance"] = 0.15
    rules["min_clearance"] = 0.0
    # D24 (die escape world): the 0.8 mm die lattice corridor needs a ring
    # gap of dia + 2*0.15 + 0.15 <= 0.8 mm, so die via-in-pads are 0.35/0.2
    # (ring 0.075 >= min annular 0.05); floors relax to match the fab
    # (0.2 drill = 8 mil).
    rules["min_through_hole_diameter"] = 0.2
    rules["min_via_diameter"] = 0.3
    # the S6 pro is minimal (no net classes): KiCad would then apply its
    # built-in 0.2 mm Default clearance, so the Default class is always
    # (re)written from the template
    default = next(c for c in tmpl["net_settings"]["classes"]
                   if c["name"] == "Default")
    pro.setdefault("net_settings", {"meta": tmpl["net_settings"]["meta"]})
    pro["net_settings"]["classes"] = [dict(default, clearance=0.15,
                                           track_width=0.2)]
    pro_path.write_text(json.dumps(pro, indent=2))

    # ---- checks -------------------------------------------------------
    fails = []
    refs = re.findall(r'fp_text reference "([^"]+)"', text)
    want = re.findall(r'\(comp\s*\(ref "([^"#][^"]*)"\)',
                      (OUT / "slot1-cyclonev.net").read_text())
    if sorted(refs) != sorted(want):
        fails.append(f"refs mismatch: {sorted(refs)}")
    if nedge != 242:
        fails.append(f"card edge pads {nedge} != 242")
    a1 = next(p for p in edge if p.startswith('(pad "A1"'))
    m = re.search(r"\(at ([\d.]+) ([\d.]+)\)", a1)
    if abs(A1_X + float(m.group(1)) - 4.0) > 0.01:
        fails.append(f"A1 world x {A1_X + float(m.group(1))}")
    stations = sorted(
        round(float(re.search(r"\(at ([\d.]+)", p).group(1)), 3) for p in edge
        if re.match(r'\(pad "[AB](73|74)"', p))
    if stations != [72.0, 72.0, 73.0, 73.0]:
        fails.append(f"notch stations {stations}")
    if fails:
        for f in fails:
            print("FAIL:", f)
        sys.exit(1)

    r = subprocess.run(["kicad-cli", "pcb", "drc", "--severity-error",
                        "--exit-code-violations", "--format", "json",
                        "-o", str(OUT / "slot1-cyclonev.drc.json"),
                        str(path)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        j = json.load(open(OUT / "slot1-cyclonev.drc.json"))
        viol = j.get("violations", [])
        print(f"DRC ERRORS ({len(viol)}):")
        for v in viol[:20]:
            print("  ", v.get("type"), str(v.get("description"))[:110])
            for it in v.get("items", [])[:2]:
                print("      -", str(it.get("description"))[:100])
        sys.exit(1)
    print(f"wrote {path.relative_to(ROOT)} ({nedge} card pads, "
          f"{len(want)} footprints)")
    print("PASS  S7 checks (placement + outline + keep-outs + DRC)")


if __name__ == "__main__":
    main()
