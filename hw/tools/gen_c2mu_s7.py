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
balls. U1 under the band, GTP quad towards the socket's HSIO8-11 pins; the
PCIe pairs and their AC capacitors where c2mu_pcie.py's template puts them,
other parts off its copper.
B.Cu: 0402 class parts only (terminations along the edge at their
contacts, their VTT decoupling (0805 too) at the row's left end, U1 via-pair
capacitors, chip decoupling under the chips).
Checks (exit 1): every netlist part placed with its nets, every footprint
with a 3D model file (U2 exempt), kicad-cli DRC 0 errors apart
from the unrouted nets.
"""
import csv
import math
import pathlib
import re
import sys

import pcbnew

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import c2mu_pcie
import placer
from gen_c2cart_s6 import GTL_REFS
from placer import Placer, mm
from gen_mu_lib import STANDOFF_R
from gen_slot1_s7 import A1_X, CHAM, KEY_C, KEY_D, KEY_W, RET, W

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT, NAME = ROOT / "hw/slot1-c2mu", "slot1-c2mu"
H = 75.0
MU_AT = (72.0, 69.5)                     # J4 origin (contact centre line), 180 deg
MU_HOLES = [(31.8, 57.0), (-31.8, 57.0)]  # Mu M2 holes, J4 local [vendor footprint F.Fab]
MU_AREA = (33.26, 9.26, 110.74, H)       # module shadow: parts <= 4 mm
COLUMN = (RET + 0.2, 7.1, 33.2, H)       # free column: tall and user-touched parts
KEEP = 0.25                              # other parts' courtyards this far from the PCIe template copper
U1_AT = (58.0, 34.0)
BAND_Y = 7.1                             # chip band top (the cavity band ends at 7.0)
FIXED_FP = {"U1": "Interposer:FPGA_Artix7_XC7A100T_FGG484_BGA", "U2": "Slot1:SC242_CardEdge_242"}
NO_MODEL = {"U2"}                        # card edge
TALL = {"J1", "J3", "J5", "J6", "J7", "J8", "SW1", "D1"}
TALL_FP = ("L_Changjiang_FXL1040", "CP_Elec_")         # > 4 mm, never under the Mu
NET_CLASSES = {"PWR": ["VCC_3V3", "V5", "VTT15", "USB_VBUS", "FT_VPHY", "FT_VCORE", "FT_VCCA", "PS*_SW"],
               "CORE": ["VCC_1V0", "VCC_1V8", "VCC_MGT*"],
               "VIN": ["V12", "V12_IN"],
               "PCIE": ["MU_TX*", "MU_RX*", "PCIE_TX*", "PCIE_RX*", "MU_REFCLK_*", "PCIE_REFCLK_*"]}


def keep_off(P, sides, p, q, r):
    """mark the occupancy grid on sides along segment p-q, r around it"""
    n = 1 + int(math.dist(p, q) / 0.2)
    for k in range(n + 1):
        x, y = p[0] + (q[0] - p[0]) * k / n, p[1] + (q[1] - p[1]) * k / n
        for s in sides:
            P.grid[s][P.cells((x - r, y - r, x + r, y + r))] = True


def tall_under_mu(comps):
    """forbid(): a part over 4 mm in the module's shadow"""
    return lambda ref, b: (ref in TALL or any(k in comps[ref][1] for k in TALL_FP)) and \
        b[2] > MU_AREA[0] and b[3] > MU_AREA[1]


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
    comps, nets, full = placer.netlist(OUT / f"{NAME}.net", FIXED_FP)
    rows = {r["ref"]: r for r in csv.DictReader(open(OUT / "pdn.csv"))}
    board = pcbnew.BOARD()
    board.SetCopperLayerCount(8)
    P = Placer(board, comps, nets, full, (W, H), (RET + 0.2, BAND_Y, W - RET - 0.2, H - 0.2), shaped=("J4",),
               forbid=tall_under_mu(comps))

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

    # PCIe pair template (c2mu_pcie.py): its AC capacitors at their spots, other parts off its copper
    pcie = c2mu_pcie.plan(lambda b: P.pad_xy("U1", b), lambda n: P.pad_xy("J4", n))
    cap_row = {r["b"]: r for r in rows.values() if r["kind"] == "pcie"}
    for t in (t for pair in pcie.values() for t in pair):
        _, fpga_xy, mu_xy, side = t.cap
        ref = cap_row[t.ball]["ref"]
        mid = ((fpga_xy[0] + mu_xy[0]) / 2, (fpga_xy[1] + mu_xy[1]) / 2)
        for rot in (0.0, 90.0, 180.0, 270.0):
            P.put(ref, *mid, rot, side, mark=False)
            if all(abs(a - b) < 0.01 for a, b in zip(P.pad_xy(ref, "1"), fpga_xy)):
                P.put(ref, *mid, rot, side)
                break
        else:
            sys.exit(f"FAIL: {ref} pads do not land on the PCIe template")
        for _, p, q, _ in t.segments():       # on any layer: a part over a pair gets no via to its planes
            keep_off(P, "FB", p, q, c2mu_pcie.W / 2 + KEEP)
        for v, _ in t.vias():
            keep_off(P, "FB", v, v, c2mu_pcie.VIA[0] / 2 + KEEP)

    # ICs near the balls / pins they serve
    def ball(net):
        return P.pad_xy("U1", next(p for ref, p in nets[net] if ref == "U1"))
    P.near("U11", *ball("SPI_CLK"), reach=30.0)
    P.near("U12", *ball("OSC50"), reach=30.0)
    for ref, net in (("U13", "VCC_MGT10"), ("U14", "VCC_MGT12")):
        P.near(ref, *ball(net), reach=30.0)
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
    if P.unmatched(nets):
        fails.append(f"netlist pins without a pad: {P.unmatched(nets)}")
    for f in board.GetFootprints():
        placer.localize_models(f, fails, OUT, NO_MODEL)
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
    placer.drc(path, OUT / f"{NAME}.drc.json")
    print(f"PASS  c2mu S7: {len(P.fp)} footprints placed, DRC 0 errors")


def write_rules():
    """JLCPCB 6 / 8-layer class rules: 0.09 mm track / space floor, kept at 0.1"""
    placer.write_rules(OUT / f"{NAME}.kicad_pro", [
        ("PWR", 0.15, 0.4),
        ("CORE", 0.1, 0.25),     # FPGA rails (<= 0.25 A each, rtl/build/c2mu/power.rpt): between U1's via-in-pads
        ("VIN", 0.2, 1.0),       # Mu ~2 A at 12 V
        # 0.2 mm on F.Cu over In1 (0.116 mm 2116 prepreg, er 4.16): ~47 ohm, ~90 ohm loosely coupled
        # clearance 0.15: the pair escapes between U1's via-in-pads (0.2 + 2 x 0.15 <= 0.55 mm)
        ("PCIE", 0.15, 0.2)], NET_CLASSES)


if __name__ == "__main__":
    main()
