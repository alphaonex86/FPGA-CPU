#!/usr/bin/env python3
"""Slot 1 C2 Mu cartridge (plan/slot1_c2.md D40): PCB placement, the S7 step
for hw/slot1-c2mu, with the pcbnew API (pads carry their nets for routing).

Usage: python3 hw/tools/gen_c2mu_s7.py   (after gen_c2mu_s6.py)
Output: hw/slot1-c2mu/slot1-c2mu.kicad_pcb, .drc.json, fp-lib-table, the
board rules in .kicad_pro; stock 3D models copied to hw/lib/3dmodels.

Board 127 x 75 mm, 8 layers, the SC242 card edge of gen_slot1_s7.py (no
paste on the fingers). J4 (Mu socket) on the top edge, turned 180 deg: the
module covers x 33.3..110.7, y 9.3..74.7 (viability.md); under it only
parts <= 4 mm (Mu bottom parts 2.0 mm, 6.6 mm standoff): the tall parts
and everything the user touches stay in the free column x 16..33.3. H1/H2
(M2 standoffs) at the Mu holes split the transceiver band: DATA0 left of
H1, DATA1-3 / CY2309 / ADDR0-1 between, TX (7 channels) right of U1 at its
balls. U1 under the band, GTP quad towards the socket's HSIO8-11 pins.
B.Cu: 0402 class parts only (terminations along the edge at their
contacts, their VTT decoupling (0805 too) at the row's left end, U1 via-pair
capacitors, chip decoupling under the chips).
Checks (exit 1): every netlist part placed with its nets, every footprint
with a 3D model file (U2 exempt), kicad-cli DRC 0 errors apart
from the unrouted nets.
"""
import csv
import json
import pathlib
import re
import shutil
import subprocess
import sys

import numpy as np
import pcbnew

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import gen_t6_schematic as t6
import models3d
from gen_c2cart_s6 import GTL_REFS
from gen_mu_lib import STANDOFF_R
from gen_slot1_s7 import A1_X, CHAM, KEY_C, KEY_D, KEY_W, RET, W

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT, NAME = ROOT / "hw/slot1-c2mu", "slot1-c2mu"
H = 75.0
LIB = ROOT / "hw/lib"
STOCK_FP, STOCK_3D = pathlib.Path("/usr/share/kicad/footprints"), pathlib.Path("/usr/share/kicad/3dmodels")
MU_AT = (72.0, 69.5)                     # J4 origin (contact centre line), 180 deg
MU_HOLES = [(31.8, 57.0), (-31.8, 57.0)]  # Mu M2 holes, J4 local [vendor footprint F.Fab]
MU_AREA = (33.26, 9.26, 110.74, H)       # module shadow: parts <= 4 mm
COLUMN = (RET + 0.2, 7.1, 33.2, H)       # free column: tall and user-touched parts
U1_AT = (58.0, 34.0)
PCIE_CORRIDOR = (45.5, 45.5, 64.5, 64.0)  # GTP corner of U1 -> HSIO8-11 / REFCLK2 pins: AC caps only
BAND_Y = 7.1                             # chip band top (the cavity band ends at 7.0)
FIXED_FP = {"U1": "Interposer:FPGA_Artix7_XC7A100T_FGG484_BGA", "U2": "Slot1:SC242_CardEdge_242"}
NO_MODEL = {"U2"}                        # card edge
TALL = {"J1", "J3", "J5", "J6", "J7", "J8", "SW1", "D1"}
TALL_FP = ("L_Changjiang_FXL1040", "CP_Elec_")         # > 4 mm, never under the Mu
RES = 0.1                                # occupancy grid (mm)
NET_CLASSES = {"PWR": ["VCC_3V3", "V5", "VTT15", "USB_VBUS", "FT_VPHY", "FT_VCORE", "FT_VCCA", "PS*_SW"],
               "CORE": ["VCC_1V0", "VCC_1V8", "VCC_MGT*"],
               "VIN": ["V12", "V12_IN"],
               "PCIE": ["MU_TX*", "MU_RX*", "PCIE_TX*", "PCIE_RX*", "MU_REFCLK_*", "PCIE_REFCLK_*"]}


def mm(x, y):
    return pcbnew.VECTOR2I_MM(x, y)


def netlist():
    t = (OUT / f"{NAME}.net").read_text()
    comps = {}
    for m in re.finditer(r'\(comp\s*\(ref "([^"]+)"\)\s*\(value "([^"]*)"\)(?:\s*\(footprint "([^"]*)"\))?', t):
        comps[m.group(1)] = (m.group(2), m.group(3) or FIXED_FP.get(m.group(1), ""))
    nets, full = {}, {}                 # plain name (as in pdn.csv) -> nodes / netlist name
    for m in re.finditer(r'\(net\s*\(code "[^"]+"\)\s*\(name "([^"]*)"\)', t):
        plain = m.group(1).lstrip("/").replace("{slash}", "/")
        nets[plain] = re.findall(r'\(ref "([^"]*)"\)\s*\(pin "([^"]*)"\)', t[m.end():t6.block(t, m.start())])
        full[plain] = m.group(1)
    return comps, nets, full


def load(fpid):
    lib, name = fpid.split(":")
    own = LIB / f"{lib}.pretty"
    f = pcbnew.FootprintLoad(str(own if (own / f"{name}.kicad_mod").exists() else STOCK_FP / f"{lib}.pretty"), name)
    if f is None:
        sys.exit(f"FAIL: footprint {fpid} not found")
    return f


def localize_models(f, fails):
    """stock model -> hw/lib/3dmodels copy, path relative to the project"""
    ref = f.GetReference()
    models = list(f.Models())
    if not models and ref not in NO_MODEL:
        fails.append(f"{ref}: no 3D model")
    for m in models:
        name = m.m_Filename
        if name.startswith("${KIPRJMOD}"):
            path = OUT / name.replace("${KIPRJMOD}/", "")
        else:
            src = STOCK_3D / re.sub(r"^\$\{KICAD\d*_3DMODEL_DIR\}/", "", name)
            if not src.exists() and f.GetFPID().GetLibItemName().wx_str() in models3d.MODELS:
                src = STOCK_3D / models3d.MODELS[f.GetFPID().GetLibItemName().wx_str()][0]
            path = LIB / "3dmodels" / src.name
            if src.exists() and not path.exists():
                shutil.copy(src, path)
            m.m_Filename = "${KIPRJMOD}/../lib/3dmodels/" + src.name
        if not path.resolve().exists():
            fails.append(f"{ref}: 3D model file missing {path}")


class Placer:
    """footprints on the board, courtyard occupancy per side"""
    def __init__(self, board, comps, nets, full):
        self.board, self.comps = board, comps
        self.grid = {s: np.zeros((int(W / RES) + 1, int(H / RES) + 1), bool) for s in "FB"}
        self.netinfo, self.pin_net = {}, {}
        for n, nodes in nets.items():
            ni = pcbnew.NETINFO_ITEM(board, full[n])
            board.Add(ni)
            self.netinfo[n] = ni
            for ref, pin in nodes:
                self.pin_net[(ref, pin)] = n
        self.fp, self.where = {}, {}

    def make(self, ref):
        value, fpid = self.comps[ref]
        f = load(fpid)
        f.SetReference(ref)
        f.SetValue(value)
        self.board.Add(f)
        for p in f.Pads():
            n = self.pin_net.get((ref, p.GetNumber()))
            if n:
                p.SetNet(self.netinfo[n])
        self.fp[ref] = f
        return f

    def box(self, f, side):
        f.BuildCourtyardCaches()
        poly = f.GetCourtyard(pcbnew.F_CrtYd if side == "F" else pcbnew.B_CrtYd)
        b = poly.BBox() if poly.OutlineCount() else f.GetBoundingBox(False)
        return b.GetX() / 1e6, b.GetY() / 1e6, b.GetRight() / 1e6, b.GetBottom() / 1e6

    def shape(self, f, side, b):
        """courtyard polygon rasterised over its bbox cells (J4: socket body and latches only)"""
        poly = f.GetCourtyard(pcbnew.F_CrtYd if side == "F" else pcbnew.B_CrtYd)
        xs, ys = self.cells(b)
        return np.array([[poly.Contains(mm(i * RES, j * RES), -1, pcbnew.FromMM(RES))
                          for j in range(ys.start, ys.stop)] for i in range(xs.start, xs.stop)])

    def sides(self, f, side):
        return "FB" if f.GetAttributes() & pcbnew.FP_THROUGH_HOLE else side

    def cells(self, b):
        return (slice(max(0, int(b[0] / RES)), int(np.ceil(b[2] / RES)) + 1),
                slice(max(0, int(b[1] / RES)), int(np.ceil(b[3] / RES)) + 1))

    def put(self, ref, x, y, rot=0.0, side="F", mark=True):
        f = self.fp.get(ref) or self.make(ref)
        if side == "B" and not f.IsFlipped():
            f.Flip(f.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
        f.SetPosition(mm(x, y))
        f.SetOrientationDegrees(rot)
        if mark:
            f.BuildCourtyardCaches()
            for s in self.sides(f, side):
                own = f.GetCourtyard(pcbnew.F_CrtYd if s == "F" else pcbnew.B_CrtYd).OutlineCount()
                b = self.box(f, s if own else side)
                self.grid[s][self.cells(b)] |= self.shape(f, side, b) if ref == "J4" else True
        self.where[ref] = (x, y, side)
        return f

    def ok(self, b, f, side, tall, region):
        if b[0] < region[0] or b[1] < region[1] or b[2] > region[2] or b[3] > region[3]:
            return False
        if tall and b[2] > MU_AREA[0] and b[3] > MU_AREA[1]:
            return False
        return not any(self.grid[s][self.cells(b)].any() for s in self.sides(f, side))

    def near(self, ref, tx, ty, side="F", region=None, rots=(0.0, 90.0), reach=40.0, top=0.0):
        """nearest free spot to (tx, ty), square spiral in 0.25 mm steps; top: a strip that deep above
        the part kept free too (its fanout vias; the region may exclude it, vias may go there)"""
        f = self.fp.get(ref) or self.make(ref)
        tall = ref in TALL or any(k in self.comps[ref][1] for k in TALL_FP)
        region = region or (RET + 0.2, BAND_Y, W - RET - 0.2, H - 0.2)
        local = {}
        for rot in rots:
            self.put(ref, 0.0, 0.0, rot, side, mark=False)
            local[rot] = self.box(f, side)
        step, k = 0.25, 0
        while k * step <= reach:
            d = k * step
            ring = [(0.0, 0.0)] if k == 0 else \
                [(-d + i * step, -d) for i in range(2 * k)] + [(d, -d + i * step) for i in range(2 * k)] + \
                [(d - i * step, d) for i in range(2 * k)] + [(-d, d - i * step) for i in range(2 * k)]
            for dx, dy in sorted(ring, key=lambda p: p[0] ** 2 + p[1] ** 2):
                for rot, lb in local.items():
                    x, y = tx + dx, ty + dy
                    b = (lb[0] + x, lb[1] + y, lb[2] + x, lb[3] + y)
                    strip = self.cells((b[0], b[1] - top, b[2], b[1]))
                    if self.ok(b, f, side, tall, region) and not (top and self.grid[side][strip].any()):
                        if top:
                            self.grid[side][strip] = True
                        return self.put(ref, x, y, rot, side)
            k += 1
        around = sorted(r for r, (x, y, sd) in self.where.items() if abs(x - tx) < reach and abs(y - ty) < reach)
        sys.exit(f"FAIL: no room for {ref} within {reach} mm of ({tx:.1f}, {ty:.1f}) on {side}.Cu; placed there: "
                 + " ".join(f"{r}@({self.where[r][0]:.1f},{self.where[r][1]:.1f})" for r in around))

    def pad_xy(self, ref, num):
        p = next(p for p in self.fp[ref].Pads() if p.GetNumber() == num)
        return p.GetPosition().x / 1e6, p.GetPosition().y / 1e6


def outline(board):
    o = [(0.0, 0.0), (KEY_C - KEY_W / 2, 0.0), (KEY_C - KEY_W / 2, KEY_D), (KEY_C + KEY_W / 2, KEY_D),
         (KEY_C + KEY_W / 2, 0.0), (W - CHAM, 0.0), (W, CHAM), (W, H), (CHAM, H), (0.0, H - CHAM)]
    for k in range(len(o)):
        s = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(mm(*o[k]))
        s.SetEnd(mm(*o[(k + 1) % len(o)]))
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(pcbnew.FromMM(0.1))
        board.Add(s)
    # cavity band and retention bands: no parts (copper and planes allowed); key notch: no copper
    for x0, y0, x1, y1, parts_only in ((0.0, 3.5, W, 7.0, True), (0.0, 7.0, RET, H, True),
                                       (W - RET, 7.0, W, H, True), (KEY_C - 1.0, 0.0, KEY_C + 1.0, KEY_D, False)):
        z = pcbnew.ZONE(board)
        z.SetIsRuleArea(True)
        z.SetLayerSet(pcbnew.LSET.AllCuMask())
        z.SetDoNotAllowFootprints(parts_only)
        z.SetDoNotAllowTracks(not parts_only)
        z.SetDoNotAllowVias(not parts_only)
        z.SetDoNotAllowPads(False)
        z.SetDoNotAllowZoneFills(not parts_only)
        ol = z.Outline()
        ol.NewOutline()
        for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
            ol.Append(pcbnew.FromMM(x), pcbnew.FromMM(y))
        board.Add(z)


def band_centres():
    """the transceivers and U10, pin 1 rows vertical (stock orientation): {ref: centre}; DATA0 left
    of H1, the rest spread between the Mu standoffs, TX right of U1 (gen_c2mu_assign.py: ball targets)"""
    tw, sw = 9.49, 7.49                  # TSSOP-56 / SOIC-16 courtyard widths
    h1, h2 = (MU_AT[0] - lx for lx, _ in MU_HOLES)
    at = {GTL_REFS["DATA0"]: (h1 - STANDOFF_R - tw / 2, BAND_Y + 14.59 / 2)}
    mid = [GTL_REFS[c] for c in ("DATA1", "DATA2", "DATA3")] + ["U10"] + [GTL_REFS[c] for c in ("ADDR0", "ADDR1")]
    widths = [sw if r == "U10" else tw for r in mid]
    lo, hi = h1 + STANDOFF_R, h2 - STANDOFF_R
    gap = (hi - lo - sum(widths)) / (len(mid) + 1)
    if gap < 0.1:
        sys.exit("FAIL: band does not fit between the Mu standoffs")
    x = lo + gap
    for r, w in zip(mid, widths):
        at[r] = (x + w / 2, BAND_Y + (10.49 if r == "U10" else 14.59) / 2)
        x += w + gap
    at[GTL_REFS["TX"]] = (U1_AT[0] + 11.35 + 0.4 + tw / 2, U1_AT[1])
    return at


def main():
    comps, nets, full = netlist()
    rows = {r["ref"]: r for r in csv.DictReader(open(OUT / "pdn.csv"))}
    board = pcbnew.BOARD()
    board.SetCopperLayerCount(8)
    P = Placer(board, comps, nets, full)

    # card edge: stations 73/74 stepped (key notch, gen_slot1_s7.edge_pads), no paste on the fingers
    edge = P.make("U2")
    for p in edge.Pads():
        m = re.fullmatch(r"[AB](73|74)", p.GetNumber())
        if m:
            p.SetPosition(mm(72.0 if m.group(1) == "73" else 73.0, 3.0))
            p.SetSize(mm(0.6, 1.0))
        front = p.GetNumber().startswith("A")
        layers = pcbnew.LSET()
        layers.AddLayer(pcbnew.F_Cu if front else pcbnew.B_Cu)
        layers.AddLayer(pcbnew.F_Mask if front else pcbnew.B_Mask)
        p.SetLayerSet(layers)
    for g in list(edge.GraphicalItems()):          # the library courtyard is open: D33's rectangle instead
        if g.GetLayer() in (pcbnew.F_CrtYd, pcbnew.B_CrtYd):
            edge.Remove(g)
    for layer in (pcbnew.F_CrtYd, pcbnew.B_CrtYd):
        r = pcbnew.PCB_SHAPE(edge, pcbnew.SHAPE_T_RECTANGLE)
        r.SetStart(mm(-2.0, -2.0))
        r.SetEnd(mm(123.0, 3.4))
        r.SetLayer(layer)
        r.SetWidth(pcbnew.FromMM(0.05))
        edge.Add(r)
    P.put("U2", A1_X, 0.055, mark=False)

    P.put("J4", *MU_AT, 180.0)
    for ref, (lx, ly) in zip(("H1", "H2"), MU_HOLES):
        P.put(ref, MU_AT[0] - lx, MU_AT[1] - ly)
    P.put("U1", *U1_AT)

    for ref, at in band_centres().items():
        P.put(ref, *at)

    # free column: power entry on the top edge, then the tall parts
    P.put("J3", 22.1, H - 12.0)
    l_ps1 = next(r for r, v in rows.items() if v["a"] == "PS1" and "FXL1040" in v["footprint"])
    # (column 17 mm: L1 standing under J3, then J1 | J6 | J5 side by side, then J8 | SW1;
    # targets are footprint origins, pin 1 on the headers)
    any_rot = (0.0, 90.0, 180.0, 270.0)
    for ref, tx, ty, rots in (("J7", 30.8, 68.0, any_rot), ("F1", 30.6, 61.0, (90.0,)), (l_ps1, 21.6, 54.2, (90.0,)),
                              ("PS1", 30.6, 51.5, any_rot), ("J1", 17.75, 33.5, (0.0,)), ("J6", 23.2, 35.0, (0.0,)),
                              ("J5", 29.85, 44.5, (90.0,)), ("J8", 19.95, 26.8, (90.0,)),
                              ("SW1", 26.4, 27.8, any_rot), ("D1", 31.0, 27.0, any_rot)):
        P.near(ref, tx, ty, region=COLUMN, rots=rots, reach=15.0)

    # terminations: one B.Cu row along the edge, each pack at the mean x of its contacts
    contact_x = {}
    for n, nodes in nets.items():
        for ref, pin in nodes:
            if ref == "U2":
                contact_x[n] = A1_X + int(pin[1:]) - 1
    for r in sorted((r for r in rows.values() if r["ref"].startswith("RN")),
                    key=lambda r: sum(contact_x.get(n, 0) for n in r["nets"].split("|")[:4])):
        xs = [contact_x[n] for n in r["nets"].split("|")[:4] if n in contact_x]
        # 270: the signal pads face the fingers, their fanout vias (gen_c2mu_s8) above the row
        P.near(r["ref"], sum(xs) / len(xs), BAND_Y + 1.4, "B", rots=(270.0,), top=1.9)

    # U1 via-pair capacitors: pad 1 (rail) on the supply ball, pad 2 on the GND ball
    for r in (r for r in rows.values() if r["kind"] == "u1pair"):
        (sx, sy), (gx, gy) = P.pad_xy("U1", r["a"]), P.pad_xy("U1", r["b"])
        for rot in (0.0, 90.0, 180.0, 270.0):
            P.put(r["ref"], (sx + gx) / 2, (sy + gy) / 2, rot, "B", mark=False)
            px, py = P.pad_xy(r["ref"], "1")
            if abs(px - sx) < 0.01 and abs(py - sy) < 0.01:
                P.put(r["ref"], (sx + gx) / 2, (sy + gy) / 2, rot, "B")
                break
        else:
            sys.exit(f"FAIL: {r['ref']} pads do not land on {r['a']} / {r['b']}")
    P.grid["B"][P.cells(P.box(P.fp["U1"], "F"))] = True    # every ball gets a via in pad (gen_c2mu_s8.py)

    # PCIe AC capacitors at the receiver ends (< 8 mm [design_guide_pcie]), along the lanes; then the
    # corridor between the GTP corner and the socket stays free of other F.Cu parts
    for r in sorted((r for r in rows.values() if r["kind"] == "pcie"), key=lambda r: r["ref"]):
        a = r["a"]
        P.near(r["ref"], *P.pad_xy(a, next(p for ref, p in nets[r["nets"].split("|")[1]] if ref == a)),
               rots=(90.0,))
    P.grid["F"][P.cells(PCIE_CORRIDOR)] = True

    # ICs near the balls / pins they serve
    def ball(net):
        return P.pad_xy("U1", next(p for ref, p in nets[net] if ref == "U1"))
    P.near("U11", *ball("SPI_CLK"), reach=30.0)
    P.near("U12", *ball("OSC50"), reach=30.0)
    for ref, net in (("U13", "VCC_MGT10"), ("U14", "VCC_MGT12")):
        P.near(ref, *ball(net), region=(MU_AREA[0], 46.0, PCIE_CORRIDOR[0], 63.0))
    for ref, anchor in (("Q1", ("J4", "1")), ("Q2", ("J4", "3")), ("U16", ("J4", "73")), ("Y1", ("J4", "73"))):
        P.near(ref, P.pad_xy(*anchor)[0], 56.0)
    for ref, at in (("U15", ("J6", "3")), ("U17", ("J6", "4")), ("F2", ("J6", "1")), ("D2", ("J5", "3"))):
        P.near(ref, *P.pad_xy(*at))                               # USB protection at the header, fan clamp
    for k, ps in enumerate(("PS2", "PS3", "PS4")):
        P.near(ps, 80.0 + 10.0 * k, 52.0)

    # the remaining passives near what they serve; VTT decoupling at the left end of the termination row
    term_end = (min(P.where[ref][0] for ref in P.where if ref.startswith("RN")) - 4.0, BAND_Y + 1.4)

    def anchor(r):
        a, b = r["a"], r["b"]
        if r["kind"] == "term" and not a:
            return term_end
        if a == "J4" and r["kind"] == "stage":           # Mu VIN bulk
            return P.pad_xy("J4", "255")
        pin = b or next((p for n in r["nets"].split("|") for ref, p in nets.get(n, []) if ref == a), None)
        if a in P.fp and pin:                            # the given pin, else the one on a shared net
            return P.pad_xy(a, pin)
        if a in P.where:
            return P.where[a][:2]
        return U1_AT
    order = sorted((r for r in rows.values() if r["ref"] not in P.where),
                   key=lambda r: ("stage pcie pin u1bulk term clk vref pullup strap mu".split().index(r["kind"]),
                                  r["ref"]))
    for r in order:
        x, y = anchor(r)
        small = "0402" in r["footprint"] or "R_Array" in r["footprint"]
        side = "B" if (small and r["kind"] in ("pin", "u1bulk")) or r["kind"] == "term" else "F"
        P.near(r["ref"], x, y, side, reach=60.0)

    fails = []
    missing = sorted(set(comps) - set(P.fp))
    if missing:
        fails.append(f"not placed: {missing}")
    for f in board.GetFootprints():
        localize_models(f, fails)
    outline(board)
    path = OUT / f"{NAME}.kicad_pcb"
    pcbnew.SaveBoard(str(path), board)
    (OUT / "fp-lib-table").write_text("(fp_lib_table\n  (version 7)\n" + "".join(
        '  (lib (name "%s")(type "KiCad")(uri "${KIPRJMOD}/../lib/%s.pretty")(options "")'
        '(descr "C2 cartridge footprint set"))\n' % (L, L) for L in ("Slot1", "Interposer", "Pwr")) + ")\n")
    write_rules()
    if fails:
        print("FAIL", *fails, sep="\n  ")
        sys.exit(1)
    drc(path)
    print(f"PASS  c2mu S7: {len(P.fp)} footprints placed, DRC 0 errors")


def write_rules():
    """JLCPCB 6 / 8-layer class rules: 0.09 mm track / space floor, kept at 0.1; vias 0.45 / 0.25"""
    pro_path = OUT / f"{NAME}.kicad_pro"
    pro = json.loads(pro_path.read_text())
    tmpl = json.loads(pathlib.Path("/usr/share/kicad/template/Edgeberry_Cartridge/"
                                   "Edgeberry_cartridge_template.kicad_pro").read_text())
    pro["board"] = {"design_settings": tmpl["board"]["design_settings"]}
    rules = pro["board"]["design_settings"]["rules"]
    rules.update(min_copper_edge_clearance=0.001, min_clearance=0.1, min_track_width=0.1, min_via_diameter=0.45,
                 min_through_hole_diameter=0.25, min_via_annular_width=0.1, min_hole_clearance=0.2)
    default = next(c for c in tmpl["net_settings"]["classes"] if c["name"] == "Default")
    via = dict(via_diameter=0.45, via_drill=0.25)
    pro["net_settings"] = {"meta": tmpl["net_settings"]["meta"], "classes": [
        dict(default, clearance=0.1, track_width=0.1, **via),
        dict(default, name="PWR", clearance=0.15, track_width=0.4, **via),
        # FPGA rails (<= 0.25 A each, rtl/build/c2mu/power.rpt): fits between U1's via-in-pads (0.55 mm)
        dict(default, name="CORE", clearance=0.1, track_width=0.25, **via),
        dict(default, name="VIN", clearance=0.2, track_width=1.0, **via),     # Mu ~2 A at 12 V
        # 0.2 mm on F.Cu over In1 (0.116 mm 2116 prepreg, er 4.16): ~47 ohm, ~90 ohm loosely coupled
        # clearance 0.15: the pair escapes between U1's via-in-pads (0.2 + 2 x 0.15 <= 0.55 mm)
        dict(default, name="PCIE", clearance=0.15, track_width=0.2, **via)],
        "netclass_patterns": [{"netclass": c, "pattern": "/" + p} for c, ps in NET_CLASSES.items() for p in ps]}
    pro_path.write_text(json.dumps(pro, indent=2))


def drc(path):
    out = OUT / f"{NAME}.drc.json"
    r = subprocess.run(["nice", "-n", "19", "kicad-cli", "pcb", "drc", "--severity-error", "--format", "json",
                        "-o", str(out), str(path)], capture_output=True, text=True)
    if not out.exists():
        sys.exit(f"FAIL: kicad-cli drc: {r.stderr[-400:]}")
    rep = json.load(open(out))
    viol = rep.get("violations", [])
    print(f"DRC: {len(viol)} errors, {len(rep.get('unconnected_items', []))} unrouted connections")
    if viol:
        for v in viol[:25]:
            print("  ", v.get("type"), str(v.get("description"))[:80],
                  [str(i.get("description"))[:50] for i in v.get("items", [])[:2]])
        sys.exit(1)


if __name__ == "__main__":
    main()
