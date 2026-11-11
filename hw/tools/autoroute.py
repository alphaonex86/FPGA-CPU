#!/usr/bin/env python3
"""Board routing common to the generated boards (gen_c2mu_s8.py, gen_socket*_t8.py, route_search.py):
planes, via in every netted BGA ball, plane fanout of the SMD pads, supervised freerouting runs, KiCad
DRC as the judge. Every function takes the board and its .kicad_pcb path: the .drc.json sits next to
it."""
import fcntl
import json
import math
import os
import pathlib
import re
import shutil
import signal
import subprocess
import sys
import time

import pcbnew

import close_route

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT.parent / "FPGAcommon/hw"))
import claude_slice
FREEROUTING = ROOT.parent / "FPGAcommon/tools/freerouting/freerouting-2.3.0-fpga.jar"
FREEROUTING_PAR = FREEROUTING.with_name("freerouting-2.3.0-fpga-parallel.jar")
FREEROUTING_MAIN = FREEROUTING.with_name("freerouting-2.3.0.jar")      # upstream, without the fork's changes
JAVA = "/opt/openjdk-bin-25/bin/java"     # the fork is built for Java 25
# the freerouting builds: upstream, the serial fork (deterministic), and the parallel fork (each run
# differs: thread timing decides which speculative routes it keeps; ~4x faster) plain and with layer
# cost variants. The net order of the DSN changes nothing (measured: 6 shuffled orders, 6 identical
# sessions)
CPUS = 4                                 # operator 2026-11-11: never more than 4 CPUs for all of this project's
                                         # heavy jobs together: the quota of claude-route.slice
PARALLEL = {"FREEROUTING__ROUTER__PARALLEL_THREADS": str(CPUS)}
HEAP_GB = 8                              # per run; a run's RSS reaches ~7.5 GB
# operator 2026-11-08/09: one routing script at a time, the others wait; everything Claude runs within
# 25 % of the PC's RAM, no swap (claude_slice: the routing scripts in claude-route.slice)
ROUTE_LOCK = ROOT / "hw/.route.lock"
POLL = 20                                # watchdog period (s)
CRASH = re.compile(rb"OutOfMemoryError|StackOverflowError|fatal error has been detected")
JOB_END = b"finished with state"

PLANE_MARGIN = 0.5                       # a plane via keeps via radius + zone clearance from the split
VIA = (0.45, 0.25)
TRACK = 0.25                             # pad -> plane via
CLEARANCE = pcbnew.FromMM(0.1)           # Default net class (the board minimum is 0)
INSET = 0.3                              # plane pull-back from the board outline
POWER_PAD = 0.8                          # a pad this wide (0603 and up, coils) carries a rail's current


def contain(routing=True):
    """first call of a routing script: re-run it in claude-route.slice (CPUS CPUs for the whole slice,
    under claude.slice's RAM cap), then, when it routes, wait until no other routing script runs: the
    lock, kept open until exit (None without routing)"""
    if "/claude-route.slice/" not in open("/proc/self/cgroup").read():
        claude_slice.run_in("route", [sys.executable] + sys.argv, cpus=CPUS)     # the slice's quota
    free, limit = claude_slice.budget()
    if limit is None:
        sys.exit("FAIL: claude-route.slice has no memory limit above it")
    if not routing:
        return None
    lock = open(ROUTE_LOCK, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"waiting for the other routing script ({ROUTE_LOCK})", flush=True)
        fcntl.flock(lock, fcntl.LOCK_EX)
    print(f"claude-route.slice: memory limit {limit >> 30} GB ({free >> 30} GB free), {CPUS} CPUs", flush=True)
    return lock


def routers(layer_costs):
    """{label: freerouting layer cost multipliers (DSN layer index: stack order)} -> the run list"""
    return [("upstream", FREEROUTING_MAIN, {}), ("serial", FREEROUTING, {}), ("parallel", FREEROUTING_PAR, PARALLEL)] + \
        [(label, FREEROUTING_PAR, dict(PARALLEL, FREEROUTING__ROUTER__LAYER_COST_MULTIPLIERS=c))
         for label, c in layer_costs.items()]


def mm(x, y):
    return pcbnew.VECTOR2I_MM(x, y)


def net(board, name):
    n = board.FindNet("/" + name)
    if n is None:
        sys.exit(f"FAIL: net {name} missing")
    return n


def by_ref(board):
    """the footprints by reference and their pads by number and spot: KiCad saves them by UUID, random
    at each generation, and a greedy step that follows the file order gives another board each time"""
    return [(f, sorted(f.Pads(), key=lambda p: (p.GetNumber(), p.GetPosition().x, p.GetPosition().y)))
            for f in sorted(board.GetFootprints(), key=lambda f: f.GetReference())]


def plane_rect(board, rect):
    """None -> the board edge pulled back by INSET"""
    box = board.GetBoardEdgesBoundingBox()
    edge = (box.GetX() / 1e6 + INSET, box.GetY() / 1e6 + INSET, box.GetRight() / 1e6 - INSET,
            box.GetBottom() / 1e6 - INSET)
    return tuple(e if v is None else v for v, e in zip(rect, edge))


def planes(board, spec):
    """spec [(net, layer, (x0, y0, x1, y1): None = board edge, priority)]: a higher priority area is
    cut out of a lower one; plane layers typed power (freerouting does not route them)"""
    for _, layer, _, _ in spec:
        board.SetLayerType(layer, pcbnew.LT_POWER)
    for name, layer, rect, priority in spec:
        x0, y0, x1, y1 = plane_rect(board, rect)
        z = pcbnew.ZONE(board)
        z.SetLayer(layer)
        z.SetAssignedPriority(priority)
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
    areas = {}
    for z, area in poured(board):
        areas.setdefault((z.GetNetname(), board.GetLayerName(z.GetLayer())), pcbnew.SHAPE_POLY_SET()).BooleanAdd(area)
    whole = {n for (n, L), a in areas.items() if a.OutlineCount() == 1}
    split = [f"{n} {L}: {a.OutlineCount()}" for (n, L), a in areas.items() if a.OutlineCount() > 1 and n not in whole]
    if split:                        # freerouting takes all copper touching a net's planes as joined; one
                                     # whole layer joins a net's islands on the others through their vias
        sys.exit(f"FAIL: plane net in several islands on one layer (never joined by freerouting): {split}")


def poured(board):
    """[(zone, its area: the outline less the higher priority zones of its layer)]"""
    zones = [z for z in board.Zones() if not z.GetIsRuleArea() and z.GetNetCode() > 0]
    out = []
    for z in zones:
        area = pcbnew.SHAPE_POLY_SET(z.Outline())
        for o in zones:
            if o.GetLayer() == z.GetLayer() and o.GetAssignedPriority() > z.GetAssignedPriority():
                area.BooleanSubtract(o.Outline())
        out.append((z, area))
    return out

def via_in_pad(board, spec, ref="U1"):
    """a locked via in every ball of ref on a net with other pads or a plane (spec as planes())"""
    u1, plane_nets = board.FindFootprintByReference(ref), {"/" + n for n, _, _, _ in spec}
    pads = {}
    for f in board.GetFootprints():
        for p in f.Pads():
            pads[p.GetNetCode()] = pads.get(p.GetNetCode(), 0) + 1
    n = 0
    for p in sorted(u1.Pads(), key=lambda p: p.GetNumber()):
        if p.GetNetCode() <= 0 or (pads[p.GetNetCode()] == 1 and p.GetNetname() not in plane_nets):
            continue                     # an unused IO: a via there only blocks escape channels
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(p.GetPosition())
        v.SetWidth(pcbnew.FromMM(VIA[0]))
        v.SetDrill(pcbnew.FromMM(VIA[1]))
        v.SetNet(p.GetNet())
        v.SetLocked(True)
        board.Add(v)
        n += 1
    print(f"{ref}: {n} vias in pad")


class Copper:
    """pads and vias in 2 mm cells, for the clearance test of a new via"""
    CELL = pcbnew.FromMM(2.0)

    def __init__(self, board):
        self.board, self.cells = board, {}
        self.layers = close_route.copper_layers(board)
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
        return self.clear_of(copper, pt, self.layers, code, hole, rules) and \
            not any(k.Contains(pt) or k.Collide(copper) for k in self.keepouts) and \
            not any(e.Collide(copper, pcbnew.FromMM(0.3)) for e in self.edges)

    def via(self, pt, net):
        v = pcbnew.PCB_VIA(self.board)
        v.SetPosition(pt)
        v.SetWidth(pcbnew.FromMM(VIA[0]))
        v.SetDrill(pcbnew.FromMM(VIA[1]))
        v.SetNet(net)
        v.SetLocked(True)
        self.board.Add(v)
        self.add(v)

    def track(self, a, b, layer, net, width=pcbnew.FromMM(TRACK)):
        t = pcbnew.PCB_TRACK(self.board)
        t.SetStart(a)
        t.SetEnd(b)
        t.SetWidth(width)
        t.SetLayer(layer)
        t.SetNet(net)
        t.SetLocked(True)
        self.board.Add(t)
        self.add(t)

    def track_fits(self, a, b, layer, code):
        seg = pcbnew.SHAPE_SEGMENT(a, b, pcbnew.FromMM(TRACK))
        n = 1 + int((b - a).EuclideanNorm() // pcbnew.FromMM(1.0))      # near() reaches >= 2 mm
        return all(self.clear_of(seg, pcbnew.VECTOR2I(a.x + (b.x - a.x) * k // n, a.y + (b.y - a.y) * k // n),
                                 (layer,), code) for k in range(n + 1))


def pad_frame(pad):
    """pad-local mm -> board point (KiCad: y down, positive angle counter-clockwise on screen)"""
    pos, rot = pad.GetPosition(), math.radians(pad.GetOrientationDegrees())
    return lambda lx, ly: pos + pcbnew.VECTOR2I_MM(lx * math.cos(rot) + ly * math.sin(rot),
                                                   -lx * math.sin(rot) + ly * math.cos(rot))


def on_plane(pt, spans):
    """a via at pt lands inside one of its net's plane rectangles and outside the rectangles cut
    out of it, PLANE_MARGIN from their edges"""
    x, y = pt.x / 1e6, pt.y / 1e6
    inside = lambda r, m: r[0] + m <= x <= r[2] - m and r[1] + m <= y <= r[3] - m
    return any(inside(rect, PLANE_MARGIN) and not any(inside(c, -PLANE_MARGIN) for c in cuts)
               for rect, cuts in spans)


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


def plane_vias(board, spec):
    """every SMD pad of a plane net (U1's have their via-in-pad) gets to a plane: a via in or at
    the pad, else a track to a same-net via within 1.5 mm, else a dogbone; an array's common row one via
    past a row end; every via inside its net's plane span; the rest is the router's, but no power pad
    (POWER_PAD): a rail's current never depends on a router track (exit 1)"""
    spans = {}
    for n, layer, rect, prio in spec:
        cuts = [plane_rect(board, r) for m, L, r, q in spec if L == layer and q > prio and m != n]
        spans.setdefault(net(board, n).GetNetCode(), []).append((plane_rect(board, rect), cuts))
    rules, cu = board.GetDesignSettings(), Copper(board)
    nvia, ntrack, left, power = 0, 0, [], []
    row_anchor = {}                      # (footprint, net) -> the via and pads already joined of an array's common row
    fits = lambda pt, code: on_plane(pt, spans[code]) and cu.via_fits(pt, code, rules)

    for f, pads in by_ref(board):
        for p in pads:
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
                    cu.track(pos, a, layer, p.GetNet())
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
                        cu.via(pt, p.GetNet())
                        placed += 1
                nvia += placed
                if placed:
                    continue
                near = sorted((v for v in cu.near(pos) if isinstance(v, pcbnew.PCB_VIA) and v.GetNetCode() == code
                               and (v.GetPosition() - pos).EuclideanNorm() <= pcbnew.FromMM(1.5)),
                              key=lambda v: (v.GetPosition() - pos).EuclideanNorm())
                v = next((v for v in near if cu.track_fits(pos, v.GetPosition(), layer, code)), None)
                if v is not None:
                    cu.track(pos, v.GetPosition(), layer, p.GetNet())
                    ntrack += 1
                    continue
            pt = next((pt for pt in spots if fits(pt, code) and cu.track_fits(pos, pt, layer, code)), None)
            if pt is None:
                left.append(f"{f.GetReference()}.{p.GetNumber()}")
                if min(p.GetSize().x, p.GetSize().y) >= pcbnew.FromMM(POWER_PAD):
                    power.append(f"{left[-1]} {p.GetNetname()}")
                continue
            cu.via(pt, p.GetNet())
            cu.track(pos, pt, layer, p.GetNet())
            nvia, ntrack = nvia + 1, ntrack + 1
            if key:
                row_anchor[key] = [pt, pos]
    print(f"plane connections: {nvia} vias, {ntrack} tracks; pads left to the router: {len(left)} {' '.join(left)}")
    if power:
        sys.exit(f"FAIL: power pads off their plane (inside another rail's area?): {power}")



def unrouted(board):
    board.BuildConnectivity()
    return board.GetConnectivity().GetUnconnectedCount(False)


def allow_via_in_pad(dsn):
    """KiCad exports no (via_at_smd on) and via padstacks with (attach off): freerouting then
    counts every via-in-pad as a clearance violation and routes around it"""
    lines, in_via, n = dsn.read_text().split("\n"), False, 0
    for i, line in enumerate(lines):
        if line.strip() == "(structure":
            lines[i], n = line + "\n    (control (via_at_smd on))", n + 1
        elif line.lstrip().startswith("(padstack "):
            in_via = line.lstrip().startswith('(padstack "Via[')
        elif in_via and line.strip() == "(attach off)":
            lines[i], n = line.replace("off", "on"), n + 1
    if n != 2:
        sys.exit(f"FAIL: DSN via-in-pad patch matched {n} lines, not 2: export format changed")
    dsn.write_text("\n".join(lines))


def plane_areas(board, dsn):
    """the DSN planes as KiCad pours them: each zone outline less the higher priority zones of its
    layer (KiCad exports the bare outlines: freerouting took a cut-out area as the lower zone's
    copper, counted its pads joined through it and never routed them)"""
    zones = poured(board)
    text = dsn.read_text()
    old = re.findall(r"\n *\(plane ([^ ()]+) \(polygon ([^ ()]+) [^()]*\)\)", text)
    if sorted(old) != sorted((z.GetNetname(), board.GetLayerName(z.GetLayer())) for z, _ in zones):
        sys.exit(f"FAIL: DSN planes {sorted(old)} are not the board's zones: export format changed")
    planes = []
    for z, area in zones:
        area.Fracture()                   # holes into the outline: a DSN polygon has none
        for i in range(area.OutlineCount()):
            chain = area.COutline(i)
            pts = [chain.CPoint(k) for k in range(chain.PointCount())] + [chain.CPoint(0)]
            planes.append(f"    (plane {z.GetNetname()} (polygon {board.GetLayerName(z.GetLayer())} 0 "
                          + " ".join(f"{p.x / 1000:g} {-p.y / 1000:g}" for p in pts) + "))")
    first = True

    def swap(_):
        nonlocal first
        new, first = ("\n" + "\n".join(planes)) if first else "", False
        return new
    dsn.write_text(re.sub(r"\n *\(plane [^ ()]+ \(polygon [^()]*\)\)", swap, text))


def supervised(cmd, env, log, ses, seconds, cwd):
    """a router run under a watchdog; None once it left a session file, else why not. A run ends four
    ways and one looks like a failure (pcb skill): session written; a crash signature in the log; the
    process gone without a session; the wall clock. Fifth, seen 2026-11-09: the job over (TIMED_OUT:
    no session) with the JVM still up, 17 h idle. The last four kill the process group."""
    with open(log, "ab") as out:
        seen = out.tell()
        proc = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT, env=env, cwd=cwd, start_new_session=True)
    start, ended, why = time.time(), None, None
    while why is None:
        try:
            proc.wait(POLL)
            break
        except subprocess.TimeoutExpired:
            pass
        with open(log, "rb") as f:
            f.seek(max(seen - 64, 0))
            new = f.read()
            seen = f.tell()
        if CRASH.search(new):
            why = "crash signature in the log"
        elif time.time() - start > seconds:
            why = f"wall clock, {seconds / 3600:.1f} h"
        elif ended is None and JOB_END in new:
            ended = time.time()
        elif ended is not None and time.time() - ended > 120:
            why = "job over, the JVM still up"
    if why:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
    elif proc.returncode != 0:
        why = f"exit {proc.returncode}"
    if ses.exists() and ses.stat().st_size and (why is None or ended):
        return None
    return why or "no session file"


def pass_seconds(log):
    """mean duration of the passes in a freerouting log, None without a finished pass"""
    times = [float(s) for s in re.findall(rb"pass #\d+ on board \S+ was completed in ([\d.]+) seconds", log.read_bytes())]
    return sum(times) / len(times) if times else None


def freerouting(board, path, jobs, passes, seconds):
    """the jobs (routers()) of `passes` passes (each killed after `seconds`) one after the other; the
    session leaving the fewest connections open is imported into the board: its count, None when every
    run failed"""
    route, name = path.parent, path.stem            # route_search.py's working copy, in route/
    for _, jar, _ in jobs:
        if not jar.exists():
            sys.exit(f"FAIL: {jar} missing (built from FPGAcommon/tools/freerouting, README-fpga-jar.md)")
    env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY")}
    env.update({"FREEROUTING__USAGE_AND_DIAGNOSTIC_DATA__DISABLE_ANALYTICS": "true",
                "FREEROUTING__ROUTER__HOLE_CLEARANCE_UM": str(round(
                    board.GetDesignSettings().m_HoleClearance / 1000)),
                "FREEROUTING__ROUTER__AUTOMATIC_NECKDOWN": "true",     # PWR (0.4) out of 0.25 QFN pads
                "FREEROUTING__ROUTER__OPTIMIZER__ENABLED": "false"})   # no JOB_TIMEOUT: it ends without a session
    # footprint-only rule areas (cavity, retention bands) leave copper free, but the DSN
    # export makes every rule area a copper keepout: out of the board for the export only
    parts_only = [z for z in board.Zones() if z.GetIsRuleArea() and not z.GetDoNotAllowTracks()
                  and not z.GetDoNotAllowVias()]
    for z in parts_only:
        board.Remove(z)
    base = route / f"{name}.dsn"
    exported = pcbnew.ExportSpecctraDSN(board, str(base))
    for z in parts_only:
        board.Add(z)
    if not exported:
        sys.exit("FAIL: DSN export")
    allow_via_in_pad(base)
    plane_areas(board, base)
    pcbnew.SaveBoard(str(path), board)
    best = None
    for k, (label, jar, extra) in enumerate(jobs):
        dsn, ses, log = (route / f"{name}-{k}{ext}" for ext in (".dsn", ".ses", ".log"))
        shutil.copy(base, dsn)
        ses.unlink(missing_ok=True)
        log.unlink(missing_ok=True)
        cmd = ["nice", "-n", "19", "unshare", "-rn", JAVA, f"-Xmx{HEAP_GB}g", f"-XX:ActiveProcessorCount={CPUS}",
               "-Djava.awt.headless=true", "-jar", str(jar), "-de", str(dsn), "-do", str(ses), "-mp", str(passes),
               "-mt", "1", "-da", "--gui.enabled=false"]
        claude_slice.wait_for((HEAP_GB + 1) << 30, f"router {label}")    # heap + JVM overhead (RSS ~7.5 GB)
        why = supervised(cmd, dict(env, **extra), log, ses, seconds, route)
        if why:
            print(f"  router {label}: no result ({why}), see {log}", flush=True)
            continue
        trial = pcbnew.LoadBoard(str(path))
        if not pcbnew.ImportSpecctraSES(trial, str(ses)):
            sys.exit(f"FAIL: SES import {ses}")
        n = unrouted(trial)
        print(f"  router {label}: {n} unrouted", flush=True)
        if best is None or n < best[0]:
            best = (n, ses)
    if best is None:
        return None
    if not pcbnew.ImportSpecctraSES(board, str(best[1])):
        sys.exit("FAIL: SES import")
    return best[0]


def settle(board, path):
    """fill, save; the routers can leave a short or a clearance error: their copper there is dropped
    (the generated copper is locked), the connection open again, and dangling copper: (unrouted,
    dropped)"""
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(str(path), board)
    rep = drc_report(path)
    bad = {i["uuid"] for v in rep.get("violations", []) for i in v["items"]}
    drop = [t for t in board.GetTracks() if not t.IsLocked() and t.m_Uuid.AsString() in bad]
    for t in drop:
        board.Delete(t)
    if drop:
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
        pcbnew.SaveBoard(str(path), board)
    if drop_dangling(board, path) or drop:
        rep = drc_report(path)
    return len(rep.get("unconnected_items", [])), len(drop)     # the board's connectivity in memory lags

def finish(board, path):
    """a complete board: the generated ball vias no route uses go, fill, save; exit 1 unless the DRC
    has 0 errors and 0 open connections"""
    print(f"dangling copper dropped: {drop_dangling(board, path, keep_locked=False)}", flush=True)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(str(path), board)
    if drc(path) != (0, 0):
        sys.exit(1)


def drc_report(path, severity="error"):
    """kicad-cli DRC; errors into .drc.json, warnings into .warnings.json"""
    out = path.with_suffix(".drc.json" if severity == "error" else ".warnings.json")
    out.unlink(missing_ok=True)
    r = subprocess.run(["nice", "-n", "19", "kicad-cli", "pcb", "drc", f"--severity-{severity}", "--format", "json",
                        "-o", str(out), str(path)], capture_output=True, text=True)
    if r.returncode != 0 or not out.exists():
        sys.exit(f"FAIL: kicad-cli drc: {r.stderr.strip()[:300]}")
    return json.load(open(out))


def drop_dangling(board, path, keep_locked=True):
    """tracks and vias with a free end (KiCad DRC warnings: router leftovers; with keep_locked=False
    also the generated ball vias no route uses), until none is left: the number dropped"""
    n = 0
    while True:
        ids = {i["uuid"] for v in drc_report(path, "warning").get("violations", [])
               if v["type"] in ("track_dangling", "via_dangling") for i in v["items"]}
        drop = [t for t in board.GetTracks() if t.m_Uuid.AsString() in ids and not (keep_locked and t.IsLocked())]
        if not drop:
            return n
        for t in drop:
            board.Delete(t)
        n += len(drop)
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
        pcbnew.SaveBoard(str(path), board)


def drc(path):
    """kicad-cli DRC: (errors, unrouted)"""
    rep = drc_report(path)
    viol, unrouted = rep.get("violations", []), rep.get("unconnected_items", [])
    print(f"DRC: {len(viol)} errors, {len(unrouted)} unrouted")
    for v in viol[:25]:
        print("  ", v.get("type"), str(v.get("description"))[:80],
              [str(i.get("description"))[:50] for i in v.get("items", [])[:2]])
    return len(viol), len(unrouted)

