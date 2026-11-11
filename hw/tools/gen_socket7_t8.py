#!/usr/bin/env python3
"""Task T8 (plan/interposers.md) for socket7-cyclonev: planes, via in every U1 ball and autorouting
(autoroute.py, as gen_c2mu_s8.py).

Usage: python3 hw/tools/gen_socket7_t8.py            (after gen_socket7_t7.py) the generated copper
       python3 hw/tools/route_search.py <board>     the routing (days; --service: in the background)
       python3 hw/tools/gen_socket7_t8.py --finish   (route_search.py runs it on a complete board)
Output: hw/socket7-cyclonev/socket7-cyclonev.kicad_pcb, .drc.json; the routing files in
hw/socket7-cyclonev/route/.

Stack (JLCPCB 8-layer JLC08161H-2116 as the C2 Mu, operator 2026-11-05: on 4 layers the core current
reached U1 through a split-plane corridor, ~30 mV drop against a ~14 mV margin; on 2 signal layers
the ~40 signals on U1 rings 5-7 cannot leave the ball field, the F484 has 125 user I/O in rings 0-4
for 166 signals): F.Cu signal, In1 GND, In2 signal, In3 VCC_1V1 whole, In4 split, In5 signal, In6
GND, B.Cu signal. In4: the
socket rails, S_VCC2 west of the 2 / 3 boundary of the pin rows (x 31.25 south, 28.73 north) (and
the band west: PS1's input), S_VCC3 east of it. In6: VCCIO33 in one area inside GND (the window
inside the ring, the south band east: U3's output, the flash, the pulls, and the strip across the
south pin rows joining them: freerouting never joins two islands of a plane net). VCC_AUX25 and
VCCA_FPLL25 (low current) are routed. Vias and socket pins keep no pad on a layer they do not
connect, so the planes stay whole between the 1.0 mm ball vias.
Checks (exit 1): the generated copper DRC 0 errors; --finish: every connection routed, DRC 0 errors.
"""
import pathlib
import sys

import pcbnew

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import autoroute as ar

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT, NAME = ROOT / "hw/socket7-cyclonev", "socket7-cyclonev"
SPLIT_S = 31.25                          # south pin row: last VCC2 pin x 30.0, first VCC3 pin x 32.54
SPLIT_N = 28.73                          # north pin row: last VCC2 pin x 27.46, first VCC3 pin x 30.0
WINDOW = (14.0, 14.0, 46.0, 46.0)        # inside the pin ring (inner rows x / y 12.2 and 47.8)
BAND = (24.5, 54.4)                      # south band east of PS1's parts, past the last pin row (y 52.86)
# (net, layer, (x0, y0, x1, y1): None = board edge, priority): a higher priority area is cut out of a lower one
PLANES = [("GND", pcbnew.In1_Cu, (None, None, None, None), 0),
          ("VCC_1V1", pcbnew.In3_Cu, (None, None, None, None), 0),
          ("S_VCC2", pcbnew.In4_Cu, (None, None, SPLIT_S, None), 0),
          ("S_VCC3", pcbnew.In4_Cu, (SPLIT_S, None, None, None), 0),
          ("S_VCC3", pcbnew.In4_Cu, (SPLIT_N, None, SPLIT_S, WINDOW[1]), 1),
          ("GND", pcbnew.In6_Cu, (None, None, None, None), 0),
          ("VCCIO33", pcbnew.In6_Cu, WINDOW, 1),
          ("VCCIO33", pcbnew.In6_Cu, (BAND[0], WINDOW[3], WINDOW[2], BAND[1]), 2),   # overlapping zones:
          ("VCCIO33", pcbnew.In6_Cu, (*BAND, None, None), 3)]                       # distinct priorities


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
    ar.contain(routing=False)
    path = OUT / f"{NAME}.kicad_pcb"
    board = pcbnew.LoadBoard(str(path))
    if "--finish" in sys.argv:
        thin_pads(board)
        ar.finish(board, path)
        print("PASS  socket7 T8: routed, DRC 0 errors")
        return
    if len(board.GetTracks()) or len(board.Zones()):
        sys.exit("FAIL: board already routed: rerun gen_socket7_t7.py first")
    if board.GetCopperLayerCount() != 8:
        sys.exit("FAIL: not an 8-layer board: rerun gen_socket7_t7.py")
    ar.planes(board, PLANES)
    ar.via_in_pad(board, PLANES)
    ar.plane_vias(board, PLANES)
    thin_pads(board)
    ar.generated(board, path)


if __name__ == "__main__":
    main()
