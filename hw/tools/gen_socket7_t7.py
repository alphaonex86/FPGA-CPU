#!/usr/bin/env python3
"""Task T7 (plan/interposers.md) for socket7-cyclonev: PCB placement with the pcbnew API (pads
carry their nets for routing).

Usage: python3 hw/tools/gen_socket7_t7.py   (after gen_socket7_assign.py and gen_socket7_t6.py)
Output: hw/socket7-cyclonev/socket7-cyclonev.kicad_pcb, .drc.json, fp-lib-table, the board
rules in .kicad_pro.

Outline (D6 provisional): all four edges 0.5 mm inside the ZIF body, which is ASSUMED from the
PGA370 envelope (sockets/kicad/README.md, M1 not measured): 51.6 x 62.2 mm, the lever band west
stays free. The PGA296 base (U2, header under the board) leaves a 31.3 mm window on F.Cu inside
its tail ring and 27.0 mm on B.Cu inside its insulator: U1 (22.7 mm courtyard) sits in the
centre, so every socket net runs inward once (direct 3.3 V bus, no translators). Its supply
capacitors go under it on B.Cu; the power tree, the flash, the pull resistors and the JTAG
header take the band between the ring and the cam-housing (south) edge, the only free area.
The pin map (gen_socket7_assign.py) is a least total length matching on this layout, so no two
socket legs cross.
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
OUT, NAME = ROOT / "hw/socket7-cyclonev", "socket7-cyclonev"
LIBS = {"SocketBase": ROOT / "sockets/kicad/Interposer.pretty"}
CX, CY = 30.0, 30.0                      # pin field centre (U2 origin)
# ZIF body F.Fab -26.29..26.29 (x), -26.26..36.99 (y) [Sockets.pretty/Socket7_P55C_296], 0.5 mm in
WEST, EAST, NORTH, SOUTH = CX - 25.79, CX + 25.79, CY - 25.76, CY + 36.49
RING_F, RING_B = 23.735, 24.38           # base tail ring / insulator outer courtyards (half sides)
U1_AT = (CX, CY)
FPS = {"U1": "Interposer:FPGA_CycloneV_5CEFA9_F484_BGA", "U2": "SocketBase:Socket7_Base_PGA296"}
BASE_MODEL = "${KIPRJMOD}/../../sockets/kicad/3dmodels/Socket7_Base_PGA296.step"
NET_CLASSES = {"PWR": ["S_VCC3", "VCCIO33", "VCC_AUX25", "VCCA_FPLL25", "PS*_SW"],
               "CORE": ["VCC_1V1", "S_VCC2"]}
SUPPLY = {"GND", "S_VCC2", "S_VCC3", "VCCIO33", "VCC_1V1", "VCC_AUX25", "VCCA_FPLL25"}


def layout(u1_rot):
    """{ref: (x, y, rot, side)} of U1 and U2, and their pad positions {ref: {pad: (x, y)}}"""
    at = {"U1": (*U1_AT, u1_rot, "F"), "U2": (CX, CY, 0.0, "F")}
    return at, {ref: placer.pads(placer.placed(FPS[ref], *v, LIBS)) for ref, v in at.items()}


def outline(board):
    for a, b in (((WEST, NORTH), (EAST, NORTH)), ((EAST, NORTH), (EAST, SOUTH)),
                 ((EAST, SOUTH), (WEST, SOUTH)), ((WEST, SOUTH), (WEST, NORTH))):
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
    board.SetCopperLayerCount(6)                 # JLC06161H-2116 (operator 2026-11-05: 6 layers)
    region = (WEST + 0.3, NORTH + 0.3, EAST - 0.3, SOUTH - 0.3)
    P = placer.Placer(board, comps, nets, full, (EAST + 1.0, SOUTH + 1.0), region, shaped=("U2",), libs=LIBS)
    P.put("U2", CX, CY)
    models = P.fp["U2"].Models()
    models[0].m_Filename = BASE_MODEL
    r = lay["U1"]                                 # the spot the pin map assumed
    P.put("U1", float(r["x"]), float(r["y"]), float(r["rot"]), r["side"])

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
    # the F.Cu window around U1 is the socket legs' way in: no parts there
    window = P.cells((CX - RING_F, CY - RING_F, CX + RING_F, CY + RING_F))
    P.grid["F"][window] = True

    band = (region[0], CY + RING_B + 0.2, region[2], region[3])    # south of the ring, both sides
    near_u1 = (CX - 13.4, CY - 13.4, CX + 13.4, CY + 13.4)        # the B.Cu window

    def ball(net):
        return P.pad_xy("U1", next(p for ref, p in nets[net] if ref == "U1"))
    P.near("U4", ball("AS_DCLK")[0], band[1] + 6.0, region=band, rots=(0.0, 90.0), reach=30.0)
    P.near("J1", CX + 19.0, band[3] - 3.0, region=band, rots=(0.0, 90.0), reach=20.0)
    P.near("PS1", CX - 16.0, band[1] + 4.0, region=band, rots=(0.0, 90.0, 180.0, 270.0), reach=20.0)
    for ref in ("PS2", "U3"):
        P.near(ref, CX - 4.0, band[1] + 3.0, region=band, rots=(0.0, 90.0, 180.0, 270.0), reach=25.0)

    def anchor(r):
        """pad b of part a (b: a pad number), else a's pad on the row's first net that reaches it"""
        a, b = r["a"], r["b"]
        if a in P.fp:
            numbers = {q.GetNumber() for q in P.fp[a].Pads()}
            pin = b if b in numbers else next((p for n in r["nets"].split("|") for ref, p in nets.get(n, [])
                                               if ref == a), None)
            if pin:
                return P.pad_xy(a, pin)
        return P.where[a][:2] if a in P.where else U1_AT
    order = sorted((r for r in rows.values() if r["ref"] not in P.where),
                   key=lambda r: ("stage pin u1bulk".split().index(r["kind"]), r["ref"]))
    for r in order:
        u1bulk = r["kind"] == "u1bulk" and "0402" in r["footprint"]
        P.near(r["ref"], *anchor(r), "B" if u1bulk else "F", region=near_u1 if u1bulk else band, reach=60.0)
    # pull resistors: in the band, nearest the signal pin they serve
    for ref in sorted(set(comps) - set(P.where)):
        signal = [n for n, nodes in nets.items() if n not in SUPPLY and any(r == ref for r, _ in nodes)]
        at = next((P.pad_xy(r, pin) for n in signal for r, pin in nets[n] if r in P.fp and r != ref), U1_AT)
        P.near(ref, at[0], max(at[1], band[1]), region=band, reach=60.0)

    fails = []
    missing = sorted(set(comps) - set(P.fp))
    if missing:
        fails.append(f"not placed: {missing}")
    if P.unmatched(nets):
        fails.append(f"netlist pins without a pad: {P.unmatched(nets)}")
    for f in board.GetFootprints():
        placer.localize_models(f, fails, OUT)
    outline(board)
    path = OUT / f"{NAME}.kicad_pcb"
    pcbnew.SaveBoard(str(path), board)
    (OUT / "fp-lib-table").write_text("(fp_lib_table\n  (version 7)\n" + "".join(
        '  (lib (name "%s")(type "KiCad")(uri "${KIPRJMOD}/%s")(options "")(descr "socket7 footprint set"))\n'
        % (n, u) for n, u in (("Interposer", "../lib/Interposer.pretty"), ("Pwr", "../lib/Pwr.pretty"),
                              ("SocketBase", "../../sockets/kicad/Interposer.pretty"))) + ")\n")
    placer.write_rules(OUT / f"{NAME}.kicad_pro", [("PWR", 0.15, 0.4), ("CORE", 0.15, 0.6)], NET_CLASSES)
    if fails:
        print("FAIL", *fails, sep="\n  ")
        sys.exit(1)
    placer.drc(path, OUT / f"{NAME}.drc.json")
    print(f"PASS  socket7 T7: {len(P.fp)} footprints placed, board {EAST - WEST:.1f} x {SOUTH - NORTH:.1f} mm, "
          f"DRC 0 errors")


if __name__ == "__main__":
    main()
