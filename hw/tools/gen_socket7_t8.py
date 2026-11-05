#!/usr/bin/env python3
"""Task T8 (plan/interposers.md) for socket7-cyclonev: planes, via in every U1 ball and autorouting
(autoroute.py, as gen_c2mu_s8.py).

Usage: python3 hw/tools/gen_socket7_t8.py [--pre]   (after gen_socket7_t7.py; long: freerouting;
--pre stops before routing)
Output: hw/socket7-cyclonev/socket7-cyclonev.kicad_pcb routed, .drc.json; the freerouting DSN /
SES / log in hw/socket7-cyclonev/route/.

Stack (JLCPCB 6-layer JLC06161H-2116, sockets/parts/jlcpcb_JLC06161H-2116.json; operator 2026-11-05:
on 4 layers the core current reached U1 through a split-plane corridor, ~30 mV drop against a
~14 mV margin): F.Cu signal, In1 GND, In2 VCC_1V1 whole, In3 split, In4 GND, B.Cu signal. In3: the
socket rails over the pin ring, S_VCC2 west of the 2 / 3 boundary of the north and south pin rows
(and the band west: PS1's input), S_VCC3 east of it; VCCIO33 in the window inside the ring and in
the south band east (U3's output, the flash, the pulls; the router joins the two). VCC_AUX25 and
VCCA_FPLL25 (low current) are routed. Vias and socket pins keep no pad on a layer they do not
connect, so the planes stay whole between the 1.0 mm ball vias.
Checks (exit 1): every connection routed, kicad-cli DRC 0 errors.
"""
import pathlib
import sys

import pcbnew

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import autoroute as ar

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT, NAME = ROOT / "hw/socket7-cyclonev", "socket7-cyclonev"
ROUTERS = ar.routers({"F x2": "0:2", "B x2": "5:2"})
SPLIT_X = 31.25                          # south / north rows: last VCC2 pin x 30.0, first VCC3 pin x 32.5
WINDOW = (14.0, 14.0, 46.0, 46.0)        # inside the pin ring (inner rows x / y 12.2 and 47.8)
BAND = (24.5, 54.4)                      # south band east of PS1's parts, past the last pin row (y 52.86)
# (net, layer, (x0, y0, x1, y1): None = board edge, priority): a higher priority area is cut out of a lower one
PLANES = [("GND", pcbnew.In1_Cu, (None, None, None, None), 0),
          ("VCC_1V1", pcbnew.In2_Cu, (None, None, None, None), 0),
          ("S_VCC2", pcbnew.In3_Cu, (None, None, SPLIT_X, None), 0),
          ("S_VCC3", pcbnew.In3_Cu, (SPLIT_X, None, None, None), 0),
          ("VCCIO33", pcbnew.In3_Cu, WINDOW, 1),
          ("VCCIO33", pcbnew.In3_Cu, (*BAND, None, None), 1),
          ("GND", pcbnew.In4_Cu, (None, None, None, None), 0)]


def thin_pads(board):
    """vias and the socket pins: no pad on a copper layer they do not connect"""
    for t in board.GetTracks():
        if isinstance(t, pcbnew.PCB_VIA):
            t.SetRemoveUnconnected(True)
            t.SetKeepStartEnd(True)
    for p in board.FindFootprintByReference("U2").Pads():
        p.SetRemoveUnconnected(True)
        p.SetKeepTopBottom(True)


def main():
    path = OUT / f"{NAME}.kicad_pcb"
    board = pcbnew.LoadBoard(str(path))
    if len(board.GetTracks()) or len(board.Zones()):
        sys.exit("FAIL: board already routed: rerun gen_socket7_t7.py first")
    if board.GetCopperLayerCount() != 6:
        sys.exit("FAIL: not a 6-layer board: rerun gen_socket7_t7.py")
    ar.planes(board, PLANES)
    ar.via_in_pad(board, PLANES)
    ar.plane_vias(board, PLANES)
    thin_pads(board)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(str(path), board)
    if ar.drc(path)[0]:
        sys.exit("FAIL: the generated copper has DRC errors: fix them before routing")
    if "--pre" in sys.argv:
        return
    ar.freeroute(board, path, ROUTERS)
    thin_pads(board)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(str(path), board)
    if ar.drc(path) != (0, 0):
        sys.exit(1)
    print("PASS  socket7 T8: routed, DRC 0 errors")


if __name__ == "__main__":
    main()
