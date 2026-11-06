#!/usr/bin/env python3
"""Task T8 (plan/interposers.md) for socket3-cyclonev: planes, via in every U1 ball and autorouting
(autoroute.py, as gen_c2mu_s8.py).

Usage: python3 hw/tools/gen_socket3_t8.py [--pre]   (after gen_socket3_t7.py; long: freerouting;
--pre stops before routing)
Output: hw/socket3-cyclonev/socket3-cyclonev.kicad_pcb routed, .drc.json; the freerouting DSN /
SES / log in hw/socket3-cyclonev/route/.

Stack (JLCPCB 8-layer JLC08161H-2116 as socket 7, operator 2026-11-05: on 2 signal layers ~100
socket legs to the translators stayed open): F.Cu signal, In1 GND, In2 signal, In3 VCC_1V1 whole,
In4 split, In5 signal, In6 GND, B.Cu signal. In4: V3V3 (U1's VCCIO, the translators); V5
over the regulator row of the north band (PS1's output, the PS2-PS4 inputs); S_VCC over the pin
ring (the socket's Vcc pins, only sensed by the VCORE detector); V3V3 again in the window inside
the ring (the flash; the router joins it). V12, VCC_AUX25 and VCCA_FPLL25 are routed. Vias and
socket pins keep no pad on a layer they do not connect, so the planes stay whole between the
1.0 mm ball vias.
Checks (exit 1): every connection routed, kicad-cli DRC 0 errors.
"""
import pathlib
import sys

import pcbnew

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import autoroute as ar
from gen_socket7_t8 import thin_pads

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT, NAME = ROOT / "hw/socket3-cyclonev", "socket3-cyclonev"
ROUTERS = ar.routers({"outer x2": "0:2,7:2", "inner x2": "2:2,5:2"})    # outer / inner signal layers dearer
# (net, layer, (x0, y0, x1, y1): None = board edge, priority): a higher priority area is cut out of a lower one
PLANES = [("GND", pcbnew.In1_Cu, (None, None, None, None), 0),
          ("VCC_1V1", pcbnew.In3_Cu, (None, None, None, None), 0),
          ("V3V3", pcbnew.In4_Cu, (None, None, None, None), 0),
          ("V5", pcbnew.In4_Cu, (17.0, 10.0, 47.0, 29.0), 1),       # V5 pads x 18.0-46.2, y 12.0-28.3
          ("S_VCC", pcbnew.In4_Cu, (None, 58.3, None, None), 1),     # pin rows y 59.68-100.32 (U1 balls end y 57.3)
          ("V3V3", pcbnew.In4_Cu, (16.2, 65.9, 44.0, 93.7), 2),      # window: inner pin rows x 14.76 / 45.24, y 64.76 / 95.24
          ("GND", pcbnew.In6_Cu, (None, None, None, None), 0)]


def main():
    path = OUT / f"{NAME}.kicad_pcb"
    board = pcbnew.LoadBoard(str(path))
    if len(board.GetTracks()) or len(board.Zones()):
        sys.exit("FAIL: board already routed: rerun gen_socket3_t7.py first")
    if board.GetCopperLayerCount() != 8:
        sys.exit("FAIL: not an 8-layer board: rerun gen_socket3_t7.py")
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
    print("PASS  socket3 T8: routed, DRC 0 errors")


if __name__ == "__main__":
    main()
