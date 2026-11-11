#!/usr/bin/env python3
"""Task T8 (plan/interposers.md) for socket3-cyclonev: planes, via in every U1 ball and autorouting
(autoroute.py, as gen_c2mu_s8.py).

Usage: python3 hw/tools/gen_socket3_t8.py            (after gen_socket3_t7.py) the generated copper
       python3 hw/tools/route_search.py <board>     the routing (days; --service: in the background)
       python3 hw/tools/gen_socket3_t8.py --finish   (route_search.py runs it on a complete board)
Output: hw/socket3-cyclonev/socket3-cyclonev.kicad_pcb, .drc.json; the routing files in
hw/socket3-cyclonev/route/.

Stack (JLCPCB 8-layer JLC08161H-2116 as socket 7, operator 2026-11-05: on 2 signal layers ~100
socket legs to the translators stayed open): F.Cu signal, In1 GND, In2 signal, In3 VCC_1V1 whole,
In4 V3V3 whole (U1's VCCIO, the translators, the flash), In5 signal, In6 GND, B.Cu signal. V5 (PS1's
output, the PS2-PS4 inputs) is an area of In6 over the regulator row of the north band: on In4 it cut
PS4's output (L4, C17) off the V3V3 plane, the whole 3.3 V current on a router track. S_VCC (the socket's
Vcc pins, only sensed by the VCORE detector), V12, VCC_AUX25 and VCCA_FPLL25 are routed: an S_VCC
plane over the pin ring split V3V3 in two islands, which freerouting never joins. Vias and
socket pins keep no pad on a layer they do not connect, so the planes stay whole between the
1.0 mm ball vias.
Checks (exit 1): the generated copper DRC 0 errors; --finish: every connection routed, DRC 0 errors.
"""
import pathlib
import sys

import pcbnew

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import autoroute as ar
from gen_socket7_t8 import thin_pads

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT, NAME = ROOT / "hw/socket3-cyclonev", "socket3-cyclonev"
# (net, layer, (x0, y0, x1, y1): None = board edge, priority): a higher priority area is cut out of a lower one
PLANES = [("GND", pcbnew.In1_Cu, (None, None, None, None), 0),
          ("VCC_1V1", pcbnew.In3_Cu, (None, None, None, None), 0),
          ("V3V3", pcbnew.In4_Cu, (None, None, None, None), 0),
          ("GND", pcbnew.In6_Cu, (None, None, None, None), 0),
          ("V5", pcbnew.In6_Cu, (17.0, 10.0, 47.0, 29.0), 1)]       # V5 pads x 18.0-46.2, y 12.0-28.3


def main():
    ar.contain(routing=False)
    path = OUT / f"{NAME}.kicad_pcb"
    board = pcbnew.LoadBoard(str(path))
    if "--finish" in sys.argv:
        thin_pads(board)
        ar.finish(board, path)
        print("PASS  socket3 T8: routed, DRC 0 errors")
        return
    if len(board.GetTracks()) or len(board.Zones()):
        sys.exit("FAIL: board already routed: rerun gen_socket3_t7.py first")
    if board.GetCopperLayerCount() != 8:
        sys.exit("FAIL: not an 8-layer board: rerun gen_socket3_t7.py")
    ar.planes(board, PLANES)
    ar.via_in_pad(board, PLANES)
    ar.plane_vias(board, PLANES)
    thin_pads(board)
    ar.generated(board, path)


if __name__ == "__main__":
    main()
