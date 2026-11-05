#!/usr/bin/env python3
"""Slot 1 C2 Mu cartridge: planes, U1 via-in-pad and autorouting, the S8 step
for hw/slot1-c2mu.

Usage: python3 hw/tools/gen_c2mu_s8.py   (after gen_c2mu_s7.py; long: freerouting)
Output: hw/slot1-c2mu/slot1-c2mu.kicad_pcb routed, .drc.json; the
freerouting DSN / SES / log in hw/slot1-c2mu/route/.

Stack (JLCPCB 6-layer, JLC06161H-3313): F.Cu signal, In1 GND, In2 signal,
In3 VCC_3V3 plane with a VTT15 strip along the fingers (the GTL termination
arrays: routed as a track it walled the band in), In4 GND, B.Cu signal.
Every netted U1 ball gets a filled via in its pad (0.45 / 0.25, JLCPCB POFV, free on 6 layers; not the unused IO
balls); every other SMD
pad of a plane net a via in / at the pad, a track to a near same-net via or a
dogbone (plane_vias: freerouting is slow at plane fanout); DRC 0 errors is
checked on this generated copper before routing. The rest is
routed by freerouting with the net classes of gen_c2mu_s7.py: the FPGAcommon
fork (freerouting-2.3.0-fpga.jar: serial, same routes as upstream, ~3x faster;
FPGAcommon/tools/freerouting/README-fpga-jar.md) on Java 25, headless (no
window, no display), without network (unshare -rn; analytics off), with the
board's hole clearance (freerouting's default is 0), optimizer off, plane
layers typed power (not routed). Iterations of PASSES passes, each session
imported and saved, until nothing is unrouted or an iteration gains nothing.
Checks (exit 1): every connection routed, kicad-cli DRC 0 errors; PCIe
intra-pair length mismatch printed.
"""
import json
import math
import os
import pathlib
import re
import subprocess
import sys

import pcbnew

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT, NAME = ROOT / "hw/slot1-c2mu", "slot1-c2mu"
ROUTE = OUT / "route"
FREEROUTING = ROOT.parent / "FPGAcommon/tools/freerouting/freerouting-2.3.0-fpga.jar"
JAVA = "/opt/openjdk-bin-25/bin/java"     # the fork is built for Java 25
PASSES, ITERATIONS = 2, 20
Y_VTT = 10.0                             # VTT15 strip / VCC_3V3 split: below the RN row, above the band chips
PLANES = [("GND", pcbnew.In1_Cu, (None, None)), ("VCC_3V3", pcbnew.In3_Cu, (Y_VTT, None)),
          ("VTT15", pcbnew.In3_Cu, (None, Y_VTT)), ("GND", pcbnew.In4_Cu, (None, None))]   # y top, bottom
PLANE_MARGIN = 0.5                       # a plane via keeps via radius + zone clearance from the split
FANOUT = ["V5"]                          # no plane, pins in the dense band: a via at each pin too
VIA = (0.45, 0.25)
TRACK = 0.25                             # pad -> plane via
CLEARANCE = pcbnew.FromMM(0.1)           # Default net class (the board minimum is 0)
INSET = 0.3                              # plane pull-back from the board outline


def mm(x, y):
    return pcbnew.VECTOR2I_MM(x, y)


def net(board, name):
    n = board.FindNet("/" + name)
    if n is None:
        sys.exit(f"FAIL: net {name} missing")
    return n


def planes(board):
    for _, layer, _ in PLANES:
        board.SetLayerType(layer, pcbnew.LT_POWER)
    box = board.GetBoardEdgesBoundingBox()
    x0, x1 = box.GetX() / 1e6 + INSET, box.GetRight() / 1e6 - INSET
    for name, layer, (top, bottom) in PLANES:
        y0 = box.GetY() / 1e6 + INSET if top is None else top
        y1 = box.GetBottom() / 1e6 - INSET if bottom is None else bottom
        z = pcbnew.ZONE(board)
        z.SetLayer(layer)
        z.SetNet(net(board, name))
        z.SetLocalClearance(pcbnew.FromMM(0.2))
        z.SetMinThickness(pcbnew.FromMM(0.15))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
        z.SetThermalReliefGap(pcbnew.FromMM(0.2))
        z.SetThermalReliefSpokeWidth(pcbnew.FromMM(0.25))
        ol = z.Outline()
        ol.NewOutline()
        for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
            ol.Append(pcbnew.FromMM(x), pcbnew.FromMM(y))
        board.Add(z)


def via_in_pad(board):
    u1 = board.FindFootprintByReference("U1")
    pads = {}
    for f in board.GetFootprints():
        for p in f.Pads():
            pads[p.GetNetCode()] = pads.get(p.GetNetCode(), 0) + 1
    n = 0
    for p in u1.Pads():
        if p.GetNetCode() <= 0 or (pads[p.GetNetCode()] == 1 and not p.GetNetname().endswith(("GND", "VCC_3V3"))):
            continue                     # an unused IO: a via there only blocks escape channels
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(p.GetPosition())
        v.SetWidth(pcbnew.FromMM(VIA[0]))
        v.SetDrill(pcbnew.FromMM(VIA[1]))
        v.SetNet(p.GetNet())
        v.SetLocked(True)
        board.Add(v)
        n += 1
    print(f"U1: {n} vias in pad")


class Copper:
    """pads and vias in 2 mm cells, for the clearance test of a new via"""
    CELL = pcbnew.FromMM(2.0)
    LAYERS = (pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.In3_Cu, pcbnew.In4_Cu, pcbnew.B_Cu)

    def __init__(self, board):
        self.cells = {}
        for f in board.GetFootprints():
            for p in f.Pads():
                self.add(p)
        for t in board.GetTracks():
            self.add(t)
        self.keepouts = [z.Outline() for z in board.Zones() if z.GetIsRuleArea() and z.GetDoNotAllowVias()]
        self.edges = [d.GetEffectiveShape() for d in board.GetDrawings() if d.GetLayer() == pcbnew.Edge_Cuts]
        classes = board.GetDesignSettings().m_NetSettings
        self.net_clearance = {code: classes.GetEffectiveNetClass(n.GetNetname()).GetClearance()
                              for code, n in board.GetNetInfo().NetsByNetcode().items()}

    def add(self, item):
        b = item.GetBoundingBox()
        for i in range(b.GetX() // self.CELL, b.GetRight() // self.CELL + 1):
            for j in range(b.GetY() // self.CELL, b.GetBottom() // self.CELL + 1):
                self.cells.setdefault((i, j), []).append(item)

    def near(self, pt):
        i, j = pt.x // self.CELL, pt.y // self.CELL
        return {id(it): it for di in (-1, 0, 1) for dj in (-1, 0, 1) for it in self.cells.get((i + di, j + dj), [])}.values()

    def clear_of(self, shape, at, layers, code, hole=None, rules=None):
        """shape (copper on layers, optional hole) keeps every item of another net at its clearance"""
        for it in self.near(at):
            if hole and it.HasHole() and it.GetEffectiveHoleShape().Collide(hole, rules.m_HoleToHoleMin):
                return False
            if it.GetNetCode() == code:
                continue
            for layer in layers:
                if it.IsOnLayer(layer):
                    gap = max(it.GetOwnClearance(layer), self.net_clearance[code], CLEARANCE)
                    if it.GetEffectiveShape(layer).Collide(shape, gap) or \
                            (hole and it.GetEffectiveShape(layer).Collide(hole, rules.m_HoleClearance)):
                        return False
        return True

    def via_fits(self, pt, code, rules):
        copper = pcbnew.SHAPE_CIRCLE(pt, pcbnew.FromMM(VIA[0] / 2))
        hole = pcbnew.SHAPE_CIRCLE(pt, pcbnew.FromMM(VIA[1] / 2))
        return self.clear_of(copper, pt, self.LAYERS, code, hole, rules) and \
            not any(k.Contains(pt) or k.Collide(copper) for k in self.keepouts) and \
            not any(e.Collide(copper, pcbnew.FromMM(0.3)) for e in self.edges)

    def track_fits(self, a, b, layer, code):
        seg = pcbnew.SHAPE_SEGMENT(a, b, pcbnew.FromMM(TRACK))
        return all(self.clear_of(seg, pt, (layer,), code) for pt in (a, (a + b) / 2, b))


def pad_frame(pad):
    """pad-local mm -> board point (KiCad: y down, positive angle counter-clockwise on screen)"""
    pos, rot = pad.GetPosition(), math.radians(pad.GetOrientationDegrees())
    return lambda lx, ly: pos + pcbnew.VECTOR2I_MM(lx * math.cos(rot) + ly * math.sin(rot),
                                                   -lx * math.sin(rot) + ly * math.cos(rot))


def on_plane(pt, spans):
    """a via at pt lands inside one of its net's plane spans (y top, bottom; None: board edge)"""
    y = pt.y / 1e6
    return not spans or any((top is None or y >= top + PLANE_MARGIN) and (bottom is None or y <= bottom - PLANE_MARGIN)
                            for top, bottom in spans)


def row_ends(pad, fp):
    """a pad in a row of >= 3 same-net pads (a resistor array's common side): via spots just past
    both row ends, so the vias keep out of the channels between arrays"""
    pos = pad.GetPosition()
    row = [q.GetPosition() for q in fp.Pads() if q.GetNetCode() == pad.GetNetCode()
           and (q.GetPosition() - pos).EuclideanNorm() <= pcbnew.FromMM(2.0)]
    if len(row) < 3:
        return []
    a, b = max(((p, q) for p in row for q in row), key=lambda pq: (pq[0] - pq[1]).EuclideanNorm())
    gap = min(pad.GetSize().x, pad.GetSize().y) / 2e6 + VIA[0] / 2 + 0.1
    axis = (a - b).Resize(pcbnew.FromMM(gap))
    return [a + axis, b - axis]


def via_spots(pad, fp_pos):
    """groups of spots, the first fitting spot of each group taken: a 1 mm grid on an exposed
    pad, the pad centre when it is wide enough, else past either end (the outer one first)"""
    sx, sy = pad.GetSize().x / 1e6, pad.GetSize().y / 1e6
    at, pos = pad_frame(pad), pad.GetPosition()
    if min(sx, sy) >= 1.2:
        nx, ny = int((sx - VIA[0]) // 1.0) + 1, int((sy - VIA[0]) // 1.0) + 1
        return [[at((i - (nx - 1) / 2) * 1.0, (j - (ny - 1) / 2) * 1.0)] for i in range(nx) for j in range(ny)]
    if min(sx, sy) >= VIA[0]:
        return [[pos]]
    ends = [at(sx / 2 + 0.1, 0), at(-sx / 2 - 0.1, 0)] if sx > sy else [at(0, sy / 2 + 0.1), at(0, -sy / 2 - 0.1)]
    ends.sort(key=lambda e: -((e - pos).x * (pos - fp_pos).x + (e - pos).y * (pos - fp_pos).y))
    return [ends]


def dogbones(pad):
    """via spots around the pad, nearest first, each joined by a track from the pad centre"""
    sx, sy = pad.GetSize().x / 1e6, pad.GetSize().y / 1e6
    at = pad_frame(pad)
    out = []
    for d in (0.45, 0.7, 1.0, 1.4, 1.8):
        for k in range(8):
            a = math.pi * k / 4
            reach = min(abs(sx / 2 / math.cos(a)) if abs(math.cos(a)) > 1e-9 else 1e9,
                        abs(sy / 2 / math.sin(a)) if abs(math.sin(a)) > 1e-9 else 1e9)
            out.append(at((reach + d) * math.cos(a), (reach + d) * math.sin(a)))
    return out


def plane_vias(board):
    """every SMD pad of a plane net (U1's have their via-in-pad) gets to a plane: a via in or at
    the pad, else a track to a same-net via within 1.5 mm, else a dogbone; an array's common row one via
    past a row end; every via inside its net's plane span; the rest is the router's"""
    spans = {net(board, n).GetNetCode(): [] for n in FANOUT}
    for n, _, span in PLANES:
        spans.setdefault(net(board, n).GetNetCode(), []).append(span)
    rules, cu = board.GetDesignSettings(), Copper(board)
    nvia, ntrack, left = 0, 0, []
    row_anchor = {}                      # (footprint, net) -> the via and pads already joined of an array's common row
    fits = lambda pt, code: on_plane(pt, spans[code]) and cu.via_fits(pt, code, rules)

    def add_via(pt, n):
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(pt)
        v.SetWidth(pcbnew.FromMM(VIA[0]))
        v.SetDrill(pcbnew.FromMM(VIA[1]))
        v.SetNet(n)
        v.SetLocked(True)
        board.Add(v)
        cu.add(v)

    def add_track(a, b, layer, n):
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(a)
        t.SetEnd(b)
        t.SetWidth(pcbnew.FromMM(TRACK))
        t.SetLayer(layer)
        t.SetNet(n)
        t.SetLocked(True)
        board.Add(t)
        cu.add(t)

    for f in board.GetFootprints():
        for p in f.Pads():
            code, pos = p.GetNetCode(), p.GetPosition()
            if code not in spans or p.GetAttribute() != pcbnew.PAD_ATTRIB_SMD or \
                    any(isinstance(v, pcbnew.PCB_VIA) and v.GetNetCode() == code and p.HitTest(v.GetPosition())
                        for v in cu.near(pos)):
                continue
            layer = pcbnew.B_Cu if p.IsOnLayer(pcbnew.B_Cu) else pcbnew.F_Cu
            if row_ends(p, f):           # a row: one via, the other pads joined to the nearest joined one
                key = (f.GetReference(), code)
                anchors = sorted(row_anchor.get(key, []), key=lambda a: (a - pos).EuclideanNorm())
                a = next((a for a in anchors if cu.track_fits(pos, a, layer, code)), None)
                if a is not None:
                    add_track(pos, a, layer, p.GetNet())
                    row_anchor[key].append(pos)
                    ntrack += 1
                    continue
                spots = row_ends(p, f) + dogbones(p)
            else:
                key, spots = None, dogbones(p)
                placed = 0
                for group in via_spots(p, f.GetPosition()):
                    pt = next((pt for pt in group if fits(pt, code)), None)
                    if pt is not None:
                        add_via(pt, p.GetNet())
                        placed += 1
                nvia += placed
                if placed:
                    continue
                near = sorted((v for v in cu.near(pos) if isinstance(v, pcbnew.PCB_VIA) and v.GetNetCode() == code
                               and (v.GetPosition() - pos).EuclideanNorm() <= pcbnew.FromMM(1.5)),
                              key=lambda v: (v.GetPosition() - pos).EuclideanNorm())
                v = next((v for v in near if cu.track_fits(pos, v.GetPosition(), layer, code)), None)
                if v is not None:
                    add_track(pos, v.GetPosition(), layer, p.GetNet())
                    ntrack += 1
                    continue
            pt = next((pt for pt in spots if fits(pt, code) and cu.track_fits(pos, pt, layer, code)), None)
            if pt is None:
                left.append(f"{f.GetReference()}.{p.GetNumber()}")
                continue
            add_via(pt, p.GetNet())
            add_track(pos, pt, layer, p.GetNet())
            nvia, ntrack = nvia + 1, ntrack + 1
            if key:
                row_anchor[key] = [pt, pos]
    print(f"plane connections: {nvia} vias, {ntrack} tracks; pads left to the router: {len(left)} {' '.join(left)}")


def unrouted(board):
    board.BuildConnectivity()
    return board.GetConnectivity().GetUnconnectedCount(False)


def freeroute(board, path):
    if not FREEROUTING.exists():
        sys.exit(f"FAIL: {FREEROUTING} missing (built from FPGAcommon/tools/freerouting, README-fpga-jar.md)")
    ROUTE.mkdir(exist_ok=True)
    dsn, ses, log = ROUTE / f"{NAME}.dsn", ROUTE / f"{NAME}.ses", ROUTE / "freerouting.log"
    env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY")}
    env.update({"FREEROUTING__USAGE_AND_DIAGNOSTIC_DATA__DISABLE_ANALYTICS": "true",
                "FREEROUTING__ROUTER__HOLE_CLEARANCE_UM": str(round(
                    board.GetDesignSettings().m_HoleClearance / 1000)),
                "FREEROUTING__ROUTER__AUTOMATIC_NECKDOWN": "false",
                "FREEROUTING__ROUTER__OPTIMIZER__ENABLED": "false",
                "FREEROUTING__ROUTER__JOB_TIMEOUT": "12:00:00"})
    cmd = ["nice", "-n", "19", "unshare", "-rn", JAVA, "-Xmx16g", "-Djava.awt.headless=true", "-jar",
           str(FREEROUTING), "-de", str(dsn), "-do", str(ses), "-mp", str(PASSES), "-mt", "1", "-da", "--gui.enabled=false"]
    best = unrouted(board)
    print(f"unrouted before routing: {best}", flush=True)
    for it in range(1, ITERATIONS + 1):
        # footprint-only rule areas (cavity, retention bands) leave copper free, but the DSN
        # export makes every rule area a copper keepout: out of the board for the export only
        parts_only = [z for z in board.Zones() if z.GetIsRuleArea() and not z.GetDoNotAllowTracks()
                      and not z.GetDoNotAllowVias()]
        for z in parts_only:
            board.Remove(z)
        exported = pcbnew.ExportSpecctraDSN(board, str(dsn))
        for z in parts_only:
            board.Add(z)
        if not exported:
            sys.exit("FAIL: DSN export")
        ses.unlink(missing_ok=True)
        with open(log, "a") as f:
            r = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, env=env, cwd=ROUTE)
        if r.returncode != 0 or not ses.exists():
            sys.exit(f"FAIL: freerouting exit {r.returncode}, see {log}")
        if not pcbnew.ImportSpecctraSES(board, str(ses)):
            sys.exit("FAIL: SES import")
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())     # plane connectivity and the saved board
        n = unrouted(board)
        print(f"iteration {it}: {n} unrouted", flush=True)
        pcbnew.SaveBoard(str(path), board)
        if n == 0 or n >= best:
            break
        best = n


def pcie_skew(board):
    length = {}
    for t in board.GetTracks():
        if t.GetClass() == "PCB_TRACK":
            length[t.GetNetname()] = length.get(t.GetNetname(), 0.0) + t.GetLength() / 1e6
    worst = 0.0
    for n in sorted(length):
        m = re.fullmatch(r"/(MU_TX|MU_RX|PCIE_TX|PCIE_RX|MU_REFCLK|PCIE_REFCLK)(\d*)_P", n)
        if m:
            d = abs(length[n] - length.get(n[:-1] + "N", 0.0))
            worst = max(worst, d)
            print(f"  {n[1:-2]}: P {length[n]:.2f} mm, N {length.get(n[:-1] + 'N', 0.0):.2f} mm, diff {d:.2f}")
    print(f"PCIe worst intra-pair mismatch {worst:.2f} mm")


def drc(path):
    """kicad-cli DRC: (errors, unrouted)"""
    out = OUT / f"{NAME}.drc.json"
    r = subprocess.run(["nice", "-n", "19", "kicad-cli", "pcb", "drc", "--severity-error", "--format", "json",
                        "-o", str(out), str(path)], capture_output=True, text=True)
    if r.returncode != 0 or not out.exists():
        sys.exit(f"FAIL: kicad-cli drc: {r.stderr.strip()[:300]}")
    rep = json.load(open(out))
    viol, unrouted = rep.get("violations", []), rep.get("unconnected_items", [])
    print(f"DRC: {len(viol)} errors, {len(unrouted)} unrouted")
    for v in viol[:25]:
        print("  ", v.get("type"), str(v.get("description"))[:80],
              [str(i.get("description"))[:50] for i in v.get("items", [])[:2]])
    return len(viol), len(unrouted)


def main():
    path = OUT / f"{NAME}.kicad_pcb"
    board = pcbnew.LoadBoard(str(path))
    if len(board.GetTracks()) or len(board.Zones()) > 4:
        sys.exit("FAIL: board already routed: rerun gen_c2mu_s7.py first")
    planes(board)
    via_in_pad(board)
    plane_vias(board)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(str(path), board)
    if drc(path)[0]:
        sys.exit("FAIL: the generated copper has DRC errors: fix them before routing")
    freeroute(board, path)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(str(path), board)
    pcie_skew(board)
    if drc(path) != (0, 0):
        sys.exit(1)
    print("PASS  c2mu S8: routed, DRC 0 errors")


if __name__ == "__main__":
    main()
