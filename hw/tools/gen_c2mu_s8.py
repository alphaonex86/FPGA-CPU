#!/usr/bin/env python3
"""Slot 1 C2 Mu cartridge: planes, U1 via-in-pad and autorouting, the S8 step
for hw/slot1-c2mu.

Usage: python3 hw/tools/gen_c2mu_s8.py   (after gen_c2mu_s7.py; long: freerouting)
Output: hw/slot1-c2mu/slot1-c2mu.kicad_pcb routed, .drc.json; the
freerouting DSN / SES / log in hw/slot1-c2mu/route/.

Stack (JLCPCB 8-layer, JLC08161H-2116; operator 2026-11-05: 3 signal layers
did not route): F.Cu signal, In1 GND, In2 signal, In3 VCC_3V3 plane with a
VTT15 strip along the fingers (the GTL termination arrays: routed as a track
it walled the band in), In4 GND with V5 areas: a strip under the band (the
transceivers' 5 V pins; as a track it walled it too), the free column (PS1,
the column loads, U13/U14), a spur to U9 and the PS2-PS4 row (routed as
tracks, 8 V5 connections stayed open), In5 signal, In6 GND, B.Cu signal:
each signal layer next to a plane. The generic steps are autoroute.py's.
The PCIe pairs first: c2mu_pcie.py's template, its nets checked against
the board (ball, AC capacitor, Mu pin), locked. Every netted U1 ball gets a filled via in its pad (0.45 / 0.25, JLCPCB POFV,
free from 6 layers; not the unused IO balls); every other SMD pad of a plane
net a via in / at the pad, a track to a near same-net via or a dogbone
(plane_vias: freerouting is slow at plane fanout); every transceiver signal
pad a via under the chip body (chip_fanout); DRC 0 errors is checked on this
generated copper before routing. The rest is
routed by freerouting with the net classes of gen_c2mu_s7.py: the FPGAcommon
fork (freerouting-2.3.0-fpga.jar: serial, same routes as upstream, ~3x faster;
FPGAcommon/tools/freerouting/README-fpga-jar.md) on Java 25, headless (no
window, no display), without network (unshare -rn; analytics off), with the
board's hole clearance (freerouting's default is 0), optimizer off, plane
layers typed power (not routed). Iterations of the ROUTERS runs of PASSES
passes at the same time (serial and parallel fork, layer cost variants), the
session leaving the fewest connections open imported and saved, router copper in DRC errors dropped; when an iteration
gains nothing, close_route.py (windowed A*) closes what it can; until nothing
is unrouted or neither gains.
Checks (exit 1): every connection routed, kicad-cli DRC 0 errors, PCIe
intra-pair skew (ball to pin, on the board) within c2mu_pcie's limits.
"""
import collections
import math
import pathlib
import sys

import pcbnew

import autoroute as ar
import c2mu_pcie
from autoroute import Copper, mm, net

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT, NAME = ROOT / "hw/slot1-c2mu", "slot1-c2mu"
ROUTERS = ar.routers({"outer x2": "0:2,7:2", "inner x2": "2:2,5:2"})    # outer / inner signal layers dearer
Y_VTT = 10.0                             # VTT15 strip / VCC_3V3 split: below the RN row, above the band chips
# (net, layer, (x0, y0, x1, y1): None = board edge, priority): a higher priority area is cut out of a lower one
V5 = [(None, 7.0, None, 12.5),           # under every transceiver's VCC (5 V) pin 50 (y 10.6)
      (16.2, 7.0, 44.0, 61.0),           # free column: PS1's L1, F2, J5, D2, the column parts, U13 / U14
      (76.0, 12.5, 80.0, 46.5),          # spur: U9 pin 50 (y 30.3), on to the regulator row
      (64.5, 46.5, 110.8, 57.0)]         # PS2-PS4 inputs; east of the PCIe pairs
PLANES = [("GND", pcbnew.In1_Cu, (None, None, None, None), 0),
          ("VCC_3V3", pcbnew.In3_Cu, (None, Y_VTT, None, None), 0),
          ("VTT15", pcbnew.In3_Cu, (None, None, None, Y_VTT), 0),
          ("GND", pcbnew.In4_Cu, (None, None, None, None), 0)] + \
         [("V5", pcbnew.In4_Cu, r, 1 + k) for k, r in enumerate(V5)] + \
         [("GND", pcbnew.In6_Cu, (None, None, None, None), 0)]     # V5: overlapping, so distinct priorities
FAN_PARTS = ("SN74GTL16612",)            # chip_fanout
TERM_FP = "R_Array_Convex_4x0402"         # chip_fanout too: vias outward, VTT pads on the plane
TERM_ROW = 1.55                          # a third via row: the chip pins on F.Cu often take the first
STAGGER = (0.35, 0.95)                   # its via columns past the pad's inner end
CENTRE = (0.35, 1.05)                    # else via columns this far from the body centre line


def chip_fanout(board):
    """every signal pad of the band transceivers: a via just inside the pad row, staggered on two
    columns (0.5 mm pitch), so the pins reach In2 / B.Cu under the body: the rows of neighbouring
    chips are only 0.85 mm apart; a pad without room there gets an L to a via near the centre line.
    The termination arrays likewise, their vias outward (above the row: s7 turns them): a pad between
    two array pads and the VTT row has one free side, which the router alone left boxed in"""
    count = collections.Counter(p.GetNetCode() for f in board.GetFootprints() for p in f.Pads())
    planes = {net(board, n).GetNetCode() for n, _, _, _ in PLANES}
    classes = board.GetDesignSettings().m_NetSettings
    rules, cu = board.GetDesignSettings(), Copper(board)
    placed, left = 0, 0
    for f in (f for f in board.GetFootprints()
              if f.GetValue() in FAN_PARTS or f.GetFPID().GetLibItemName() == TERM_FP):
        term = f.GetFPID().GetLibItemName() == TERM_FP
        ax = 1 if term and f.GetOrientationDegrees() % 180 else 0    # via columns along x, rows along y
        cx = (f.GetPosition().x, f.GetPosition().y)[ax]
        layer = pcbnew.B_Cu if f.IsFlipped() else pcbnew.F_Cu
        for k, p in enumerate(sorted(f.Pads(), key=lambda p: (p.GetPosition().x, p.GetPosition().y))):
            code, pos = p.GetNetCode(), p.GetPosition()
            if code <= 0 or code in planes or count[code] < 2:
                continue
            at = (pos.x, pos.y)[ax]
            inward = (1 if at < cx else -1) * (-1 if term else 1)
            inner = at + inward * p.GetSize().x // 2
            paths = [[pos, pcbnew.VECTOR2I(inner + inward * pcbnew.FromMM(d), pos.y) if ax == 0 else
                      pcbnew.VECTOR2I(pos.x, inner + inward * pcbnew.FromMM(d))]
                     for d in (STAGGER[k % 2], STAGGER[1 - k % 2]) + ((TERM_ROW,) if term else ())]
            if not term:                    # column spot taken (B.Cu parts): an L to the centre line
                paths += [[pos, pcbnew.VECTOR2I(x, pos.y), pcbnew.VECTOR2I(x, pos.y + pcbnew.FromMM(0.65 * j))]
                          for j in sorted(range(-12, 13), key=abs) if j
                          for x in (cx - inward * pcbnew.FromMM(d) for d in CENTRE)]
            path = next((path for path in paths if cu.via_fits(path[-1], code, rules)
                         and all(cu.track_fits(a, b, layer, code) for a, b in zip(path, path[1:]))), None)
            if path is None:
                left += 1
                continue
            cu.via(path[-1], p.GetNet())
            for a, b in zip(path, path[1:]):
                cu.track(a, b, layer, p.GetNet(), classes.GetEffectiveNetClass(p.GetNetname()).GetTrackWidth())
            placed += 1
    print(f"chip fanout: {placed} vias, pads left to the router: {left}")





def pcie_pairs(board):
    """draw the PCIe template: each track's ball, AC capacitor and J4 pin checked, tracks and vias locked"""
    u1, j4 = board.FindFootprintByReference("U1"), board.FindFootprintByReference("J4")
    pad = lambda f, n: next(p for p in f.Pads() if p.GetNumber() == n)
    xy = lambda p: (p.GetPosition().x / 1e6, p.GetPosition().y / 1e6)
    pairs = c2mu_pcie.plan(lambda b: xy(pad(u1, b)), lambda n: xy(pad(j4, n)))
    caps = {frozenset(p.GetNetname() for p in f.Pads()): f for f in board.GetFootprints() if f.GetPadCount() == 2}
    layer = {c2mu_pcie.F: pcbnew.F_Cu, c2mu_pcie.IN2: pcbnew.In2_Cu, c2mu_pcie.IN5: pcbnew.In5_Cu,
             c2mu_pcie.B: pcbnew.B_Cu}
    cu = Copper(board)
    for t in (t for pair in pairs.values() for t in pair):
        fpga, mu = pad(u1, t.ball).GetNet(), pad(j4, t.pin).GetNet()
        f = caps.get(frozenset((fpga.GetNetname(), mu.GetNetname())))
        if f is None or math.dist(xy(next(p for p in f.Pads() if p.GetNetCode() == fpga.GetNetCode())), t.cap[1]) > 0.01:
            sys.exit(f"FAIL: PCIe U1 {t.ball} -> J4 {t.pin}: no AC capacitor at the template spot (rerun s6, s7)")
        for lay, p, q, past in t.segments():
            cu.track(mm(*p), mm(*q), layer[lay], mu if past else fpga, pcbnew.FromMM(c2mu_pcie.W))
        for v, past in t.vias():
            cu.via(mm(*v), mu if past else fpga)
    print(f"PCIe: {len(pairs)} pairs drawn from the template")
    return pairs


def pcie_skew(board, pairs):
    """ball -> pin length of every PCIe track on the board; exit 1 past the skew limits"""
    length = collections.Counter()
    for t in board.GetTracks():
        if t.GetClass() == "PCB_TRACK":
            length[t.GetNetname()] += t.GetLength() / 1e6
    u1, j4 = board.FindFootprintByReference("U1"), board.FindFootprintByReference("J4")
    net = lambda f, n: next(p for p in f.Pads() if p.GetNumber() == n).GetNetname()
    lines, bad = c2mu_pcie.report(pairs, lambda t: length[net(u1, t.ball)] + length[net(j4, t.pin)])
    print("PCIe ball -> pin length, west / east track:", *lines, sep="\n")
    if bad:
        sys.exit(f"FAIL: PCIe skew over the limit: {bad}")


def main():
    path = OUT / f"{NAME}.kicad_pcb"
    board = pcbnew.LoadBoard(str(path))
    if len(board.GetTracks()) or len(board.Zones()) > 4:
        sys.exit("FAIL: board already routed: rerun gen_c2mu_s7.py first")
    ar.planes(board, PLANES)
    ar.via_in_pad(board, PLANES)
    pairs = pcie_pairs(board)
    ar.plane_vias(board, PLANES)
    chip_fanout(board)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(str(path), board)
    if ar.drc(path)[0]:
        sys.exit("FAIL: the generated copper has DRC errors: fix them before routing")
    ar.freeroute(board, path, ROUTERS)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(str(path), board)
    pcie_skew(board, pairs)
    if ar.drc(path) != (0, 0):
        sys.exit(1)
    print("PASS  c2mu S8: routed, DRC 0 errors")


if __name__ == "__main__":
    main()
