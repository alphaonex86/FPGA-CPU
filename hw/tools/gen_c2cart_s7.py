#!/usr/bin/env python3
"""Dedicated C2 cartridges (plan/slot1_c2.md D33, D34): PCB placement +
outline, the S7 step of hw/slot1-cyclonev for these boards.

Usage: python3 hw/tools/gen_c2cart_s7.py [c2cart|c2pcie]   (after gen_c2cart_s6.py; default both)
Output: hw/slot1-<board>/slot1-<board>.kicad_pcb (+ .drc.json, fp-lib-table,
the board settings in .kicad_pro).

Variant A's substrate, card edge, keep-outs and power strip
(gen_slot1_s7.py). F.Cu: the eight bus chips in one band between the
cavity band and U1, in the order of their FPGA balls (DATA0-3, CY2309,
ADDR0-1, TX; pin 1 rows vertical), U1 centred under them, J5 + the
CB3T3245s left of U1 (link and CMOS balls), EPCQ128A + J1 right (AS and
JTAG balls), the small parts packed around them. c2pcie: J6 (OCuLink,
land pattern from SFF-8612 Figure 5-8 / A-3) mouth on the top edge under
U1's GXB balls, the power strip split around it, the TX capacitors on
B.Cu under it. B.Cu: the 56 R packs in
one row along the card edge, each at its four contacts' x; every chip's
supply capacitors under its pins; the CY2309 series resistors under it;
U1's via-pair capacitors; the regulator 0402 parts under the strip.
Stock footprints keep their stock orientation, so the stock 3D models
fit. Pads are unnetted (routing is the next step).
Checks (exit 1): every netlist reference placed, no courtyard overlap,
kicad-cli pcb drc --severity-error: 0.
"""
import csv
import json
import pathlib
import re
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import models3d
from gen_t6_schematic import block
from gen_slot1_s7 import (A1_X, H, KEY_C, KEY_D, KEY_W, CHAM, RET, STRIP, W, conn_pads, edge_pads,
                          emit_lib, footprint_boxes, fp, keepout, keepout_no_tracks, module_pads, orient,
                          overlaps, pdn_footprint, stock_pads)

ROOT = pathlib.Path(__file__).resolve().parents[2]
U1_FP = {"c2cart": "FPGA_CycloneV_5CEFA9_F484_BGA", "c2pcie": "FPGA_CycloneV_5CGXFC5_F484_BGA"}
J6_AT = (69.0, H - 7.78)                 # shell front (locating pegs + C13 5.97) on the top edge
STRIP_PCIE = [(28.3, 47.0, 60.2, 57.6, "+x"), (77.9, 47.0, 110.7, 57.6, "+x"), (37.3, 30.2, 51.4, 46.8, "+x"),
              (75.6, 22.6, 110.7, 34.3, "+x")]
U1_AT = (63.5, 34.3)                     # courtyard 22.55..46.05: under the chip band
BAND_Y = 7.1                             # chip band top: the cavity band ends at 7.0
BAND = ["U5", "U6", "U7", "U8", "U12", "U3", "U4", "U9"]   # DATA0-3, CY2309, ADDR0-1, TX
IC_FP = {"U3": "TSSOP-56_6.1x14mm_P0.5mm", "U10": "TSSOP-20_4.4x6.5mm_P0.65mm",
         "U12": "SOIC-16_3.9x9.9mm_P1.27mm", "U13": "SOIC-16W_7.5x10.3mm_P1.27mm"}
for r in ("U4", "U5", "U6", "U7", "U8", "U9"):
    IC_FP[r] = IC_FP["U3"]
IC_FP["U11"] = IC_FP["U10"]
IC_AT = {"U10": (24.0, 37.5), "U11": (33.0, 37.5), "U13": (82.0, 40.0)}
F_SMALL = [(75.6, 22.6, 110.7, 34.3, "+x"), (88.3, 34.6, 110.7, 42.2, "+x"),
           (37.3, 30.2, 51.4, 46.8, "+x")]
B_ENDS = [(16.2, 9.9, 25.6, 21.6, "+x"), (101.4, 9.9, 110.7, 21.6, "+x")]
STAGES = ["F1", "PS1", "PS2", "PS4", "PS5", "PS3"]


class Board:
    """placed footprint texts + courtyards per side (through-hole on both)"""
    def __init__(self):
        self.texts, self.boxes, self.protos = [], {"F": [], "B": []}, {}

    def add(self, text):
        cyd = footprint_boxes([text])[0]
        for sd in "FB":
            self.boxes[sd] += cyd[sd]
        self.texts.append(text)

    def free(self, box, side):
        return not any(overlaps(box, b, 0.05) for b in self.boxes[side])

    def stock(self, lib, name, ref, x, y, side="F"):
        """stock footprint at its stock orientation, prototype kept for the library"""
        pads, cyd = stock_pads(lib, name)
        libname = "Stock:" + name
        self.protos.setdefault(libname, fp(libname, "REF", 0.0, 0.0, pads, cyd))
        pads, cyd = orient(pads, cyd, "+x", side)
        self.add(fp(libname, ref, x, y, pads, cyd, side=side))
        return cyd

    def row(self, row, x, y, side=None, d="+x"):
        pads, cyd = pdn_footprint(row["footprint"])
        name = "Pwr:" + row["footprint"].split(":")[1]
        self.protos.setdefault(name, fp(name, "REF", 0.0, 0.0, pads, cyd))
        pads, cyd = orient(pads, cyd, d, side or row["side"])
        self.add(fp(name, row["ref"], x, y, pads, cyd, side=side or row["side"]))

    def pack(self, rows, regions, side=None, filler=None):
        """each row at the first free spot of the regions (or a running filler)"""
        for row in rows:
            sd = side or row["side"]
            f = filler or Filler(self, regions, sd)
            cyd = pdn_footprint(row["footprint"])[1]
            cx, cy = f.put(cyd[2] - cyd[0], cyd[3] - cyd[1])
            self.row(row, cx - (cyd[0] + cyd[2]) / 2, cy - (cyd[1] + cyd[3]) / 2, sd)
            filler = filler or f


class Filler:
    """first free courtyard spot, column by column in 0.25 mm steps, from the last placement on"""
    def __init__(self, board, regions, side):
        self.bd, self.regions, self.side, self.ri, self.x = board, regions, side, 0, regions[0][0]

    def put(self, w, h):
        while self.ri < len(self.regions):
            x0, y0, x1, y1, _ = self.regions[self.ri]
            x = max(self.x, x0)
            while x + w <= x1:
                y = y0
                while y + h <= y1:
                    if self.bd.free((x, y, x + w, y + h), self.side):
                        self.x = x
                        return x + w / 2, y + h / 2
                    y += 0.25
                x += 0.25
            self.ri += 1
            self.x = self.regions[self.ri][0] if self.ri < len(self.regions) else 0
        raise SystemExit("FAIL: no room left for a %.2f x %.2f part on %s.Cu" % (w, h, self.side))


def pad_at(text, num):
    """world centre of pad num of a placed inline footprint"""
    x, y = map(float, re.search(r"\(at (-?[\d.]+) (-?[\d.]+)\)", text).groups())
    m = re.search(r'\(pad "%s"\s+\w+\s+\w+\s+\(at (-?[\d.]+) (-?[\d.]+)' % num, text)
    return x + float(m.group(1)), y + float(m.group(2))


def spread(targets, width, lo, hi, gap=0.15):
    """1-D placement: centres as near their targets as possible, no overlap, inside lo..hi"""
    xs = []
    for t in targets:
        xs.append(max(t, lo + width / 2, (xs[-1] + width + gap) if xs else -1e9))
    shift = xs[-1] - (hi - width / 2) if xs else 0
    for k in range(len(xs) - 1, -1, -1):
        if shift <= 0:
            break
        xs[k] -= shift
        shift = xs[k - 1] + width + gap - xs[k] if k else 0
    assert not xs or xs[0] >= lo + width / 2 - 1e-6, "termination row does not fit"
    return xs


def ocu_pads():
    """SFF-8612 4X right-angle receptacle, origin = datums L x M, mating face +y
    [snia_sff8612 Table 5-4 D02-D21, Table A-1 DD01-DD09]: rows B (y -D10/2, x from
    -D03) and A (y +D10/2, x from -D04), 21 x 0.31 x 0.91 at 0.50; locating holes
    D18 1.00 at (-D14, +D07), (+D15, +D07); shell pads 1.81 wide at +-DD06, small
    (1.38) at -DD04, large (1.80) at +DD05; courtyard = the keep-out"""
    pads = ['(pad "%s%d" smd rect (at %.3f %.3f) (size 0.31 0.91) (layers "F.Cu" "F.Paste" "F.Mask"))'
            % (row, k + 1, x0 + 0.5 * k, y) for row, x0, y in (("B", -5.25, -1.095), ("A", -4.75, 1.095))
            for k in range(21)]
    pads += ['(pad "" np_thru_hole circle (at %.2f 1.81) (size 1.0 1.0) (drill 1.0) (layers "*.Cu" "*.Mask"))'
             % x for x in (-5.41, 5.94)]
    pads += ['(pad "SH" smd rect (at %.2f %.2f) (size 1.81 %.2f) (layers "F.Cu" "F.Paste" "F.Mask"))'
             % (sx * 6.91, y, h) for sx in (-1, 1) for y, h in ((-0.71, 1.38), (4.01, 1.80))]
    return pads, (-8.63, -1.64, 8.63, 8.78)


def main(board):
    OUT, NAME = ROOT / f"hw/slot1-{board}", f"slot1-{board}"
    pcie = board == "c2pcie"
    rows = list(csv.DictReader(open(OUT / "pdn.csv")))
    net = (OUT / f"{NAME}.net").read_text()
    contact_x = {}                      # net -> contact x (contact number - 1 from A1)
    for m in re.finditer(r'\(net\s*\(code "[^"]+"\)\s*\(name "/?([^"]*)"\)', net):
        for ref, pin in re.findall(r'\(ref "([^"]*)"\)\s*\(pin "([^"]*)"\)', net[m.end():block(net, m.start())]):
            if ref == "U2":
                contact_x[m.group(1)] = A1_X + int(pin[1:]) - 1
    bd = Board()

    edge = edge_pads()
    bd.add(fp("Slot1:SC242_CardEdge_242", "U2", A1_X, 0.055, edge, (-2.0, -2.0, 123.0, 3.4)))
    fq = module_pads(ROOT / f"hw/lib/Interposer.pretty/{U1_FP[board]}.kicad_mod")
    bd.add(fp(f"Interposer:{U1_FP[board]}", "U1", *U1_AT, fq, (-11.75, -11.75, 11.75, 11.75)))
    u1_local = {m.group(1): (float(m.group(2)), float(m.group(3))) for m in (
        re.match(r'\(pad "(\w+)" smd \w+ \(at (-?[\d.]+) (-?[\d.]+)\)', p) for p in fq)}

    ics = {}
    widths = [stock_pads("Package_SO", IC_FP[r])[1] for r in BAND]
    gap = 0.3
    x = U1_AT[0] - (sum(c[2] - c[0] for c in widths) + gap * (len(BAND) - 1)) / 2
    for ref, c in zip(BAND, widths):
        IC_AT[ref] = (x - c[0], BAND_Y - c[1])
        x += c[2] - c[0] + gap
    for ref, (x, y) in IC_AT.items():
        bd.stock("Package_SO", IC_FP[ref], ref, x, y)
        ics[ref] = bd.texts[-1]

    nc = "Conn:PinHeader_2x20_P1.27mm_Vertical_SMD"
    j5p = orient(*stock_pads("Connector_PinHeader_1.27mm", "PinHeader_2x20_P1.27mm_Vertical_SMD"), "-y", "F")[0]
    j5b = footprint_boxes([fp("Conn:J5", "J5", 0.0, 0.0, j5p, (0, 0, 0, 0))])[1]["F"]
    j5c = (min(b[0] for b in j5b) - 0.5, min(b[1] for b in j5b) - 0.5,
           max(b[2] for b in j5b) + 0.5, max(b[3] for b in j5b) + 0.5)
    conns = [fp("Stock:OCuLink_4i_SFF-8612_RA", "J6", *J6_AT, *ocu_pads()) if pcie else
             fp(nc, "J5", 33.5, 22.0 - j5c[1], j5p, j5c),
             fp("Conn:Header_2x05", "J1", 100.0, 44.0, conn_pads(10, True), (-6.3, -1.6, 6.3, 1.6),
                attr="through_hole"),
             fp("Conn:BarrelJack_CUI_PJ-063AH_Horizontal", "J3", 22.1, H - 12.0,
                *stock_pads("Connector_BarrelJack", "BarrelJack_CUI_PJ-063AH_Horizontal"), attr="through_hole")]
    for c in conns:
        bd.add(c)

    # B.Cu termination row: each pack at the mean x of its contacts
    term = [r for r in rows if r["kind"] == "term" and r["ref"].startswith("RN")]
    tx = [sum(contact_x[n] for n in r["nets"].split("|")[:4] if n in contact_x) /
          sum(1 for n in r["nets"].split("|")[:4] if n in contact_x) for r in term]
    order = sorted(range(len(term)), key=lambda k: tx[k])
    cyd = pdn_footprint(term[0]["footprint"])[1]
    xs = spread([tx[k] for k in order], cyd[2] - cyd[0], RET + 0.2, W - RET - 0.3)
    for k, x in zip(order, xs):
        bd.row(term[k], x, BAND_Y - cyd[1], "B")

    for r in rows:                       # chip supply caps under their pins
        if r["kind"] == "pin":
            ic = ics[r["a"]]
            icx = float(re.search(r"\(at (-?[\d.]+)", ic).group(1))
            px, py = pad_at(ic, r["b"])
            bd.row(r, icx + 0.45 * (px - icx), py, "B")
        elif r["kind"] == "u1pair":
            (sx, sy), (gx, gy) = u1_local[r["a"]], u1_local[r["b"]]
            d = "+x" if gx > sx else "-x" if gx < sx else "+y" if gy > sy else "-y"
            bd.row(r, U1_AT[0] + (sx + gx) / 2, U1_AT[1] + (sy + gy) / 2, d=d)
    u12 = IC_AT["U12"]
    bd.pack([r for r in rows if r["kind"] == "clk"], [(u12[0] - 3.7, BAND_Y + 2.8, u12[0] + 3.7, 21.6, "+x")], "B")
    bd.pack([r for r in rows if r["kind"] in ("strap",) or (r["kind"] == "term" and r["ref"][0] == "C")],
            B_ENDS, "B")
    bd.pack([r for r in rows if r["kind"] in ("u1bulk", "pullup", "vref")], F_SMALL, "F")
    bd.pack([r for r in rows if r["kind"] == "pcie"],
            [(J6_AT[0] - 8.5, J6_AT[1] - 1.5, J6_AT[0] + 8.5, H - 0.3, "+x")], "B")

    # regulator stages: power parts on F.Cu, their 0402 parts (and F1) on B.Cu below (variant A)
    def area(row):
        c = pdn_footprint(row["footprint"])[1]
        return -(c[2] - c[0]) * (c[3] - c[1])
    regions = STRIP_PCIE if pcie else STRIP
    strip, bstrip = Filler(bd, regions, "F"), Filler(bd, regions, "B")
    for st in STAGES:
        bstrip.x = max(bstrip.x, strip.x) if bstrip.ri == strip.ri else bstrip.x
        group = sorted((r for r in rows if r["kind"] == "stage" and r["a"] == st), key=area)
        back = [r for r in group if "0402" in r["footprint"] or st == "F1"]
        bd.pack([r for r in group if r not in back], None, "F", strip)
        bd.pack(back, None, "B", bstrip)

    o = [(0.0, 0.0), (KEY_C - KEY_W / 2, 0.0), (KEY_C - KEY_W / 2, KEY_D), (KEY_C + KEY_W / 2, KEY_D),
         (KEY_C + KEY_W / 2, 0.0), (W - CHAM, 0.0), (W, CHAM), (W, H), (CHAM, H), (0.0, H - CHAM)]
    seg = ['\t(gr_line (start %f %f) (end %f %f) (layer "Edge.Cuts") (width 0.1))'
           % (*o[k], *o[(k + 1) % len(o)]) for k in range(len(o))]
    text = "\n".join(
        [f'(kicad_pcb (version 20240108) (generator "gen_c2cart_s7")', '\t(general (thickness 1.57))',
         '\t(paper "A4")',
         '\t(layers (0 "F.Cu" signal) (31 "B.Cu" signal) (36 "B.SilkS" user) (37 "F.SilkS" user)'
         ' (38 "B.Mask" user) (39 "F.Mask" user) (44 "Edge.Cuts" user) (46 "B.CrtYd" user)'
         ' (47 "F.CrtYd" user) (48 "B.Fab" user) (49 "F.Fab" user))',
         '\t(setup (pad_to_mask_clearance 0))', '\t(net 0 "")']) + "\n" + \
        keepout(0.0, 3.5, W, 7.0, "not_allowed", "10000000-0033-4000-8000-000000000001") + \
        keepout(0.0, 7.0, RET, H, "not_allowed", "10000000-0033-4000-8000-000000000002") + \
        keepout(W - RET, 7.0, W, H, "not_allowed", "10000000-0033-4000-8000-000000000003") + \
        keepout_no_tracks(KEY_C - 1.0, 0.0, KEY_C + 1.0, KEY_D, "10000000-0033-4000-8000-000000000004") + \
        "\n".join(seg + bd.texts) + "\n)\n"
    path = OUT / f"{NAME}.kicad_pcb"
    models3d.copy_models()
    path.write_text(models3d.with_models(text, strict=True))
    for t in list(bd.protos.values()) + [c for c in conns if "Stock:" in c]:   # Conn: variant A emits those
        emit_lib(t)
    (OUT / "fp-lib-table").write_text("(fp_lib_table\n  (version 7)\n" + "".join(
        '  (lib (name "%s")(type "KiCad")(uri "${KIPRJMOD}/../lib/%s.pretty")(options "")'
        '(descr "C2 cartridge footprint set"))\n' % (L, L)
        for L in ("Slot1", "Interposer", "Conn", "Pwr", "Stock")) + ")\n")

    # board settings: variant A's (Edgeberry template, 2 um edge recess rule)
    pro_path = OUT / f"{NAME}.kicad_pro"
    pro = json.loads(pro_path.read_text())
    tmpl = json.loads(pathlib.Path("/usr/share/kicad/template/Edgeberry_Cartridge/"
                                   "Edgeberry_cartridge_template.kicad_pro").read_text())
    pro["board"] = {"design_settings": tmpl["board"]["design_settings"]}
    rules = pro["board"]["design_settings"]["rules"]
    rules.update(min_copper_edge_clearance=0.001, min_clearance=0.0)
    default = next(c for c in tmpl["net_settings"]["classes"] if c["name"] == "Default")
    pro["net_settings"] = {"meta": tmpl["net_settings"]["meta"],
                           "classes": [dict(default, clearance=0.15, track_width=0.2)]}
    if pcie:                             # SFF-8612 Table 5-4 puts the pegs 0.07 mm from A1 / A21
        hole = rules["min_hole_clearance"]
        rules["min_hole_clearance"] = 0.05   # board floor; the .kicad_dru keeps the template value elsewhere
        (OUT / f"{NAME}.kicad_dru").write_text(
            f'(version 1)\n(rule "hole clearance"\n  (constraint hole_clearance (min {hole})))\n'
            '(rule "J6 SFF-8612 locating holes"\n'
            '  (condition "A.memberOfFootprint(\'J6\') && B.memberOfFootprint(\'J6\')")\n'
            '  (constraint hole_clearance (min 0.05)))\n')
    pro_path.write_text(json.dumps(pro, indent=2))

    fails = []
    refs = re.findall(r'fp_text reference "([^"]+)"', text)
    want = re.findall(r'\(comp\s*\(ref "([^"#][^"]*)"\)', net)
    if sorted(refs) != sorted(want):
        fails.append("refs: missing %s, extra %s" % (sorted(set(want) - set(refs)), sorted(set(refs) - set(want))))
    cyd, _ = footprint_boxes(bd.texts)
    for sd in "FB":
        b = cyd[sd]
        hits = [(i, j) for i in range(len(b)) for j in range(i + 1, len(b)) if overlaps(b[i], b[j], -0.001)]
        if hits:
            fails.append(f"{sd}: {len(hits)} courtyard overlaps")
    if fails:
        print("FAIL", *fails, sep="\n  ")
        sys.exit(1)
    drc = OUT / f"{NAME}.drc.json"
    r = subprocess.run(["nice", "-n", "19", "kicad-cli", "pcb", "drc", "--severity-error",
                        "--exit-code-violations", "--format", "json", "-o", str(drc), str(path)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        viol = json.load(open(drc)).get("violations", []) if drc.exists() else []
        print(r.stderr[-500:], f"DRC ERRORS ({len(viol)}):")
        for v in viol[:20]:
            print("  ", v.get("type"), str(v.get("description"))[:100],
                  [str(i.get("description"))[:60] for i in v.get("items", [])[:2]])
        sys.exit(1)
    print(f"PASS  {board} S7: {len(refs)} footprints placed, DRC 0 errors")


if __name__ == "__main__":
    for b in sys.argv[1:] or ("c2cart", "c2pcie"):
        main(b)
