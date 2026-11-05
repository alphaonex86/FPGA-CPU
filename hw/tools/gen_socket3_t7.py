#!/usr/bin/env python3
"""Task T7 (plan/interposers.md) for socket3-cyclonev: PCB placement with the pcbnew API (pads
carry their nets for routing).

Usage: python3 hw/tools/gen_socket3_t7.py   (after gen_socket3_t6.py)
Output: hw/socket3-cyclonev/socket3-cyclonev.kicad_pcb, .drc.json, fp-lib-table, the board
rules in .kicad_pro.

Outline (D6): west, south and east edges inside the ZIF body (0.5 mm in from its F.Fab outline,
the lever band east stays free); the board grows north, the only free side. The PGA168 base
(U2, header under the board) sits on the pin field; its tail ring blocks both sides. U1 sits
north of the ring (operator 2026-11-05: in the centre the translators would go north and every
net would cross the north ring twice); the 16 SN74CB3T3245 stand in four columns beside U1,
east and west, on F.Cu and on B.Cu at the same spots (no via in a chip pad), their A pins
facing U1, so each A leg is short and each socket leg crosses the ring once, through the
window or the side strips. The pin map (gen_socket3_assign.py) is a least total length
matching on this layout, so no two legs cross.
Checks (exit 1): every netlist part placed with its nets, every footprint with a 3D model
file (U2 exempt), kicad-cli DRC 0 errors apart from the unrouted nets.
"""
import csv
import pathlib
import sys

import pcbnew

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import placer

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT, NAME = ROOT / "hw/socket3-cyclonev", "socket3-cyclonev"
LIBS = {"SocketBase": ROOT / "sockets/kicad/Interposer.pretty"}
CX, CY = 30.0, 80.0                      # pin field centre (U2 origin)
# ZIF body F.Fab -26.28..26.15 (x), ..25.25 (y) [Sockets.pretty/Socket3_Am5x86_237], 0.5 mm in
WEST, EAST, SOUTH = CX - 25.78, CX + 25.65, CY + 24.75
RING_F, RING_B = 21.32, 21.84            # base tail ring / insulator courtyards (half sides)
U1_AT = (CX, CY - 33.2)                  # BGA courtyard 22.69: south edge 0.3 mm north of the ring;
                                         # its B.Cu via-pair capacitors clear the insulator
TR_FP = "Package_SO:TSSOP-20_4.4x6.5mm_P0.65mm"
TR_W, TR_H = 7.79, 7.09                  # TSSOP-20 courtyard at 0 deg
TR_X = 11.345 + 0.2 + TR_W / 2           # column centre from U1's: 0.2 mm off its courtyard
TR_Y0 = CY - RING_B - 0.1                # column south end
TR_GAP = 0.1


def slots():
    """the 16 translator spots, south to north, east column then west, F.Cu then B.Cu:
    [(x, y, side)]"""
    return [(CX + sx * TR_X, TR_Y0 - (k + 0.5) * TR_H - k * TR_GAP, side)
            for side in "FB" for sx in (1, -1) for k in range(4)]


def tr_rotation(x, side):
    """the rotation that puts the A pins (2..9) on the U1 side"""
    for rot in (0.0, 180.0):
        f = placer.placed(TR_FP, x, 0.0, rot, side, LIBS)
        ax = sum(p.GetPosition().x for p in f.Pads() if 2 <= int(p.GetNumber()) <= 9) / 8e6
        if abs(ax - CX) < abs(x - CX):
            return rot
    sys.exit("FAIL: no translator rotation faces U1")


def layout(u1_rot):
    """{ref or slot index: (x, y, rot, side)} of U1, U2 and the translator slots, and their pad
    positions {ref or slot index: {pad: (x, y)}}"""
    at = {"U1": (*U1_AT, u1_rot, "F"), "U2": (CX, CY, 0.0, "F")}
    for k, (x, y, side) in enumerate(slots()):
        at[k] = (x, y, tr_rotation(x, side), side)
    fps = {"U1": "Interposer:FPGA_CycloneV_5CEFA9_F484_BGA", "U2": "SocketBase:Socket3_Base_PGA168"}
    xy = {key: placer.pads(placer.placed(fps.get(key, TR_FP), *v, LIBS)) for key, v in at.items()}
    return at, xy


REGION = (WEST + 0.3, CY - 110.0, EAST - 0.3, SOUTH - 0.3)     # north: the outline closes on the parts
NORTH_BAND = CY - 51.0                   # north of the translator columns: power entry, regulators, headers
BASE_MODEL = "${KIPRJMOD}/../../sockets/kicad/3dmodels/Socket3_Base_PGA168.step"
NET_CLASSES = {"PWR": ["V5", "V3V3", "VCC_AUX25", "VCCA_FPLL25", "PS*_SW"], "CORE": ["VCC_1V1"],
               "VIN": ["V12", "V12_IN"]}
SUPPLY = {"GND", "V3V3", "V5", "V12", "V12_IN", "VCC_1V1", "VCC_AUX25", "VCCA_FPLL25"}


def outline(board, north):
    for a, b in (((WEST, north), (EAST, north)), ((EAST, north), (EAST, SOUTH)),
                 ((EAST, SOUTH), (WEST, SOUTH)), ((WEST, SOUTH), (WEST, north))):
        s = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(placer.mm(*a))
        s.SetEnd(placer.mm(*b))
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(pcbnew.FromMM(0.1))
        board.Add(s)


def main():
    comps, nets, full = placer.netlist(OUT / f"{NAME}.net", {})
    rows = {r["ref"]: r for r in csv.DictReader(open(OUT / "pdn.csv"))}
    lay = {r["ref"]: r for r in csv.DictReader(open(OUT / "layout.csv"))}
    board = pcbnew.BOARD()
    board.SetCopperLayerCount(4)
    P = placer.Placer(board, comps, nets, full, (EAST + 1.0, SOUTH + 1.0), REGION, shaped=("U2",), libs=LIBS)
    P.put("U2", CX, CY)
    models = P.fp["U2"].Models()
    models[0].m_Filename = BASE_MODEL
    for ref, r in lay.items():                    # U1 and the translators: the spots the pin map assumed
        P.put(ref, float(r["x"]), float(r["y"]), float(r["rot"]), r["side"])
    # the socket legs leave the columns outward and run south, beside the ring too: those strips stay free
    top = TR_Y0 - 4 * (TR_H + TR_GAP)
    for x0, x1 in ((CX + TR_X + TR_W / 2, EAST), (WEST, CX - TR_X - TR_W / 2)):
        for side in "FB":
            P.grid[side][P.cells((x0, top, x1, SOUTH))] = True

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
    P.grid["B"][P.cells(P.box(P.fp["U1"], "F"))] = True    # U1's ball fanout

    def ball(net):
        return P.pad_xy("U1", next(p for ref, p in nets[net] if ref == "U1"))
    P.near("U4", *ball("AS_DCLK"), reach=30.0)                # AS x4 flash at its balls
    P.near("U3", *ball("VCORE_OK"), side="B", reach=30.0)     # VCORE detector: BUS_OE# to every chip

    # north band: 12 V jack (plug from the north) and the JTAG header at the corners, the regulators between
    north = (REGION[0], REGION[1], REGION[2], NORTH_BAND)
    any_rot = (0.0, 90.0, 180.0, 270.0)
    for ref, tx, ty, rots in (("J3", CX - 18.0, CY - 64.0, (180.0,)), ("J1", CX + 19.0, CY - 60.0, (0.0, 90.0)),
                              ("PS1", CX - 8.0, CY - 58.0, any_rot), ("PS2", CX + 1.0, CY - 55.0, any_rot),
                              ("PS3", CX + 9.0, CY - 55.0, any_rot), ("PS4", CX + 17.0, CY - 55.0, any_rot)):
        P.near(ref, tx, ty, region=north, rots=rots, reach=15.0)

    def anchor(r):
        """pad b of part a (b: a pad number; a pin name falls back), else a's pad on the row's first net
        that reaches it"""
        a, b = r["a"], r["b"]
        if a in P.fp:
            numbers = {q.GetNumber() for q in P.fp[a].Pads()}
            pin = b if b in numbers else next((p for n in r["nets"].split("|") for ref, p in nets.get(n, [])
                                               if ref == a), None)
            if pin:
                return P.pad_xy(a, pin)
        return P.where[a][:2] if a in P.where else U1_AT
    order = sorted((r for r in rows.values() if r["ref"] not in P.where),
                   key=lambda r: ("stage pin u1bulk trpin".split().index(r["kind"]), r["ref"]))
    for r in order:
        side = P.where[r["a"]][2] if r["kind"] == "trpin" else "B" if r["kind"] == "u1bulk" and \
            "0402" in r["footprint"] else "F"
        P.near(r["ref"], *anchor(r), side, region=north if r["kind"] == "stage" else None, reach=60.0)
    # pull resistors: at the signal pin they serve (a U1 ball, a switch pin or a socket pin)
    for ref in sorted(set(comps) - set(P.where)):
        signal = [n for n, nodes in nets.items() if n not in SUPPLY and any(r == ref for r, _ in nodes)]
        at = next((P.pad_xy(r, pin) for n in signal for r, pin in nets[n] if r in P.fp and r != ref), U1_AT)
        P.near(ref, *at, reach=60.0)

    fails = []
    missing = sorted(set(comps) - set(P.fp))
    if missing:
        fails.append(f"not placed: {missing}")
    if P.unmatched(nets):
        fails.append(f"netlist pins without a pad: {P.unmatched(nets)}")
    for f in board.GetFootprints():
        placer.localize_models(f, fails, OUT)
    top = min(P.box(f, "B" if f.IsFlipped() else "F")[1] for f in board.GetFootprints())
    outline(board, top - 0.5)
    path = OUT / f"{NAME}.kicad_pcb"
    pcbnew.SaveBoard(str(path), board)
    (OUT / "fp-lib-table").write_text("(fp_lib_table\n  (version 7)\n" + "".join(
        '  (lib (name "%s")(type "KiCad")(uri "${KIPRJMOD}/%s")(options "")(descr "socket3 footprint set"))\n'
        % (n, u) for n, u in (("Interposer", "../lib/Interposer.pretty"), ("Pwr", "../lib/Pwr.pretty"),
                              ("SocketBase", "../../sockets/kicad/Interposer.pretty"))) + ")\n")
    placer.write_rules(OUT / f"{NAME}.kicad_pro", [("PWR", 0.15, 0.4), ("CORE", 0.15, 0.6), ("VIN", 0.2, 1.0)],
                       NET_CLASSES)
    if fails:
        print("FAIL", *fails, sep="\n  ")
        sys.exit(1)
    placer.drc(path, OUT / f"{NAME}.drc.json")
    print(f"PASS  socket3 T7: {len(P.fp)} footprints placed, board {EAST - WEST:.1f} x {SOUTH - top + 0.5:.1f} mm, "
          f"DRC 0 errors")


if __name__ == "__main__":
    main()
