#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S8c signal routing for the slot 1 cartridge (phase 1: DDR3 die nets).

Topology on the D22 stack (F/In1/In2/B signal+planes), decisions NM28/NM29:
- every U1/die ball gets a via-in-pad land: U1 (1.0 mm pitch) signal lands
  0.45 with a 0.45/0.30 via, U1 power lands 0.50 with a 0.50/0.30 via;
  dies (0.8 mm pitch) signal lands 0.45 with a 0.35/0.20 via (a 0.3 drill
  ring leaves less than a track+clearance in the 0.8 corridor), die power
  lands 0.50 with a 0.50/0.30 via,
- all escaping happens on B.Cu through the corridors between the via
  rings: a 0.15 mm track centered in the ring gap keeps 0.15 mm from the
  ring edges (U1: 0.55 gap -> 0.2 to spare; dies: 0.45 gap -> exact) and
  0.225 mm from the hole edges,
- the first leg out of a pad via is a 45-degree hop toward the corridor
  junction at (+ or - 0.5, + or - 0.5), so the router grid is 8-connected,
- F.Cu routing is added in later phases (socket/translator nets only, no
  planar obstructions inside the BGA fields).

Gate: kicad-cli DRC 0 error-level rows and the pcbnew unconnected count
drops below the pre-routing baseline (499 before S8c).
"""
import json
import math
import subprocess
from collections import defaultdict
from heapq import heappush, heappop
from pathlib import Path

import pcbnew

ROOT = Path(__file__).resolve().parent.parent.parent
PCB = ROOT / "hw/slot1-cyclonev/slot1-cyclonev.kicad_pcb"
GATE = ROOT / "hw/slot1-cyclonev/slot1-cyclonev.drc.json"

TRACK = 0.15            # escape track width
CLEAR = 0.15            # copper clearance (Default class)
GRID = 0.05             # router resolution
# U1 (1.0 mm pitch)
SIG_LAND, SIG_VIA, DRILL = 0.45, 0.45, 0.30
PWR_LAND, PWR_VIA = 0.50, 0.50
# dies (0.8 mm pitch; D24: 0.35/0.20 vias; 0.35 lands leave a legal
# F-corridor midline: 0.45 lands leave only 0.05 mm of span)
DIE_LAND, DIE_VIA, DIE_DRILL = 0.35, 0.35, 0.20
# die power pins use the same 0.35/0.20 geometry: a 0.6/0.30 power via's
# ring (0.525 radius) seals every 0.8-lattice corridor cell (0.4 mm from
# two neighbouring pins < 0.525), which killed the die-side escapes
# (>= 28 mA/pin of the ~0.5 A die VDD makes this electrically safe)
DIE_PWR_LAND, DIE_PWR_VIA = 0.35, 0.35
MARGIN = CLEAR + TRACK / 2            # 0.225 block growth around rings
BGAS = ("U1", "U3", "U4", "U5", "U6")


def is_power(netname):
    return (netname == "/GND" or any(t in netname for t in (
        "VCC", "VDD", "VTT", "VREF", "VPD", "VCCA")))


def pad_side(pad):
    """router map of an SMD land: "b" when it sits on B.Cu only (D25
    capacitors), else "f" (F.Cu lands; PTH annuli keep the old F-only
    view)"""
    return "b" if pad.IsOnLayer(pcbnew.B_Cu) and \
        not pad.IsOnLayer(pcbnew.F_Cu) else "f"


def as_rect(pad):
    pos, sz = pad.GetPosition(), pad.GetSize()
    return (pos.x / 1e6 - sz.x / 2e6, pos.y / 1e6 - sz.y / 2e6,
            pos.x / 1e6 + sz.x / 2e6, pos.y / 1e6 + sz.y / 2e6)


def key(x, y):
    return (round(x, 3), round(y, 3))


def reroute_prep(bd):
    """rescale lands, add signal via-in-pads, shrink S8b power vias"""
    vis = [t for t in bd.GetTracks() if t.GetClass() == "PCB_VIA"]
    bypos = defaultdict(list)
    for t in vis:
        bypos[key(t.GetPosition().x / 1e6, t.GetPosition().y / 1e6)].append(t)
    counts = defaultdict(int)
    for fp in bd.GetFootprints():
        ref = fp.GetReference()
        if ref not in BGAS:
            continue
        die = ref != "U1"
        for p in fp.Pads():
            x, y = p.GetPosition().x / 1e6, p.GetPosition().y / 1e6
            pw = is_power(p.GetNetname())
            land = (DIE_PWR_LAND if pw else DIE_LAND) if die else \
                (PWR_LAND if pw else SIG_LAND)
            if abs(p.GetSize().x / 1e6 - land) > 1e-4:
                p.SetSize(pcbnew.VECTOR2I(int(land * 1e6), int(land * 1e6)))
                counts["lands"] += 1
            vias = bypos.get(key(x, y))
            if vias:
                v = vias[0]
                want = DIE_PWR_VIA if (die and pw) else \
                    (PWR_VIA if pw else (SIG_VIA if not die else DIE_VIA))
                drill = DRILL if not die else DIE_DRILL
                if abs(v.GetWidth() / 1e6 - want) > 1e-4:
                    v.SetWidth(int(want * 1e6))
                    v.SetDrill(int(drill * 1e6))
                    counts["via-shrunk"] += 1
                continue
            if not pw:
                v = pcbnew.PCB_VIA(bd)
                v.SetPosition(p.GetPosition())
                v.SetWidth(int((SIG_VIA if not die else DIE_VIA) * 1e6))
                v.SetDrill(int((DRILL if not die else DIE_DRILL) * 1e6))
                v.SetNet(p.GetNet())
                v.SetViaType(pcbnew.VIATYPE_THROUGH)
                v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
                bd.Add(v)
                counts["vias-added"] += 1
    return counts


# router layer indices: 0 = B.Cu, 1 = In3.Cu, 2 = In5.Cu (inner signal
# mids, D22 amended 2026-10-22 to 8 copper layers), 3 = F.Cu. In1/In2/In4/
# In6 are poured (GND planes, rail strips) and are never routed.
LAY_NAME = {0: "b", 1: "g", 2: "h", 3: "f"}
LAY_KICAD = {0: None, 1: None, 2: None, 3: None}   # filled in module scope
NL = 4


def _init_layer_tables():
    LAY_KICAD[0] = pcbnew.B_Cu
    LAY_KICAD[1] = pcbnew.In3_Cu
    LAY_KICAD[2] = pcbnew.In5_Cu
    LAY_KICAD[3] = pcbnew.F_Cu


_init_layer_tables()


class Grid:
    """cell occupancy per routing layer + sites"""

    def __init__(self, w_mm, h_mm):
        self.w = int(round(w_mm / GRID))
        self.h = int(round(h_mm / GRID))
        self.L = {name: bytearray(self.w * self.h)
                  for name in LAY_NAME.values()}
        self.L["s"] = bytearray(self.w * self.h)   # via-site exclusion

    def idx(self, x, y):
        cx = int(round(x / GRID))
        cy = int(round(y / GRID))
        if 0 <= cx < self.w and 0 <= cy < self.h:
            return cy * self.w + cx
        return None

    def xy(self, i):
        return (i % self.w) * GRID, (i // self.w) * GRID

    def mark(self, layer, i):
        self.L[layer][i] = 1

    def disk(self, x, y, r, layer="b"):
        """mark cells whose centre lies strictly inside radius r; a cell at
        exactly r stays free (track centre on the legal clearance limit)"""
        arr = self.L[layer]
        n = int(r / GRID)
        ci, cj = int(round(x / GRID)), int(round(y / GRID))
        for j in range(cj - n - 1, cj + n + 2):
            if not 0 <= j < self.h:
                continue
            dy = (j - cj) * GRID
            span = int(math.ceil((math.sqrt(max(r * r - dy * dy, 0))
                                  ) / GRID)) - 1
            for i in range(ci - max(span, 0), ci + max(span, 0) + 1):
                if not 0 <= i < self.w:
                    continue
                dx = (i - ci) * GRID
                if dx * dx + dy * dy < r * r - 1e-12:
                    arr[j * self.w + i] = 1

    def seg(self, x0, y0, x1, y1, band, layer="b"):
        """mark a band around a segment (foreign tracks), strict boundary"""
        steps = int(1 + (abs(x1 - x0) + abs(y1 - y0)) / (GRID / 2))
        for k in range(steps + 1):
            t = k / steps if steps else 0
            px = x0 + (x1 - x0) * t
            py = y0 + (y1 - y0) * t
            self.disk(px, py, band, layer)

    def rect(self, x0, y0, x1, y1, layer="b"):
        arr = self.L[layer]
        i0, i1 = max(0, int(x0 / GRID)), min(self.w - 1, int(x1 / GRID))
        j0, j1 = max(0, int(y0 / GRID)), min(self.h - 1, int(y1 / GRID))
        for j in range(j0, j1 + 1):
            arr[j * self.w + i0:j * self.w + i1 + 1] = [1] * (i1 - i0 + 1)

    def srect(self, x0, y0, x1, y1, layer="b"):
        """strict pad-rect marking: only cells whose centre lies strictly
        inside the grown rect get blocked, so a track centre sitting on an
        exactly-legal clearance boundary stays routable"""
        arr = self.L[layer]
        for j in range(max(0, int(y0 / GRID)),
                       min(self.h, int(y1 / GRID) + 2)):
            cy = j * GRID
            if not y0 < cy < y1:
                continue
            for i in range(max(0, int(x0 / GRID)),
                           min(self.w, int(x1 / GRID) + 2)):
                cx = i * GRID
                if x0 < cx < x1:
                    arr[j * self.w + i] = 1


def own_cells(bd, grid, nets, skip=frozenset()):
    """cells inside each net's own pads/in-pad vias stay passable (the
    escape track starts under the ring); coverage mirrors the block
    geometry. Pads block F only, via rings block every routing layer.
    skip: uuid-strings of items omitted (pass-4 isolated solves).
    Returns {net: {layer key: set of cells}} (keys = LAY_NAME values)."""
    w = grid.w
    keys = set(LAY_NAME.values())
    out = {n: {k: set() for k in keys} for n in nets}
    for fp in bd.GetFootprints():
        for p in fp.Pads():
            if p.GetNetCode() == 0 or p.GetNetname() not in nets:
                continue
            r = as_rect(p)
            i0 = max(0, int((r[0] - MARGIN + GRID) / GRID))
            i1 = min(w - 1, int((r[2] + MARGIN - GRID) / GRID))
            j0 = max(0, int((r[1] - MARGIN + GRID) / GRID))
            j1 = min(grid.h - 1, int((r[3] + MARGIN - GRID) / GRID))
            mine = out[p.GetNetname()]
            side = pad_side(p)
            for j in range(j0, j1 + 1):
                for i in range(i0, i1 + 1):
                    mine[side].add(j * w + i)
            cx, cy = int(round(p.GetPosition().x / 1e6 / GRID)), \
                int(round(p.GetPosition().y / 1e6 / GRID))
            mine[side].add(cy * w + cx)
    for t in bd.GetTracks():
        if skip and t.m_Uuid.AsString() in skip:
            continue
        if t.GetClass() != "PCB_VIA":
            continue
        net = t.GetNetname()
        if net not in nets:
            continue
        mine = out[net]
        x, y = t.GetPosition().x / 1e6, t.GetPosition().y / 1e6
        ring_v = t.GetWidth(t.GetLayer()) / 1e6 / 2
        ring = ring_v + MARGIN - GRID
        gx, gy = int(round(x / GRID)), int(round(y / GRID))
        n = int(round(ring / GRID))
        for kk in keys:
            cells = mine[kk]
            cells.add(gy * w + gx)
            for j in range(gy - n, gy + n + 1):
                if not 0 <= j < grid.h:
                    continue
                for i in range(gx - n, gx + n + 1):
                    # integer cell distances only: float ring*ring compares
                    # misjudge the exact boundary cell
                    if 0 <= i < w and (i - gx) ** 2 + (j - gy) ** 2 <= n * n:
                        cells.add(j * w + i)
    # a foreign via's block disk must not be crossed just because the
    # cell sits in this net's pad funnel (run22: /DDR3_RESET# cap at
    # d 0.4472 vs /DDR3_A3 via ring): subtract every OTHER net's via
    # disk from each own set, mirrored on all routing layers
    disks = []                      # (via_net, [(cell, ...)] per radius)
    for t in bd.GetTracks():
        if skip and t.m_Uuid.AsString() in skip:
            continue
        if t.GetClass() != "PCB_VIA":
            continue
        x, y = t.GetPosition().x / 1e6, t.GetPosition().y / 1e6
        dial = t.GetWidth(t.GetLayer()) / 1e6 / 2
        r = dial + MARGIN
        gx, gy = x / GRID, y / GRID
        rg = int(math.ceil(r / GRID))
        base_i, base_j = int(x // GRID), int(y // GRID)
        cells = []
        for j in range(base_j - rg, base_j + rg + 1):
            if not 0 <= j < grid.h:
                continue
            for i in range(base_i - rg, base_i + rg + 1):
                if not 0 <= i < w:
                    continue
                dx, dy = i * GRID - x, j * GRID - y
                if dx * dx + dy * dy < r * r - 1e-12:
                    cells.append(j * w + i)
        disks.append((net if (net := t.GetNetname()) in nets else None,
                      cells))
    for vnet, cells in disks:
        for n2, sets in out.items():
            if n2 == vnet:
                continue            # own vias stay passable
            for kk in keys:
                sets[kk].difference_update(cells)
    return out


ROUTE_DEBUG = {}


def astar(grid, start, goal, owner, me, own, vkill, placed=None,
          real=None, ban=frozenset(), via_cost=80):
    """multi-layer A* over states (layer, cell); layer indices follow
    LAY_NAME (0 = B.Cu, 1 = In3.Cu, 2 = In5.Cu, 3 = F.Cu). Track moves cost 10 per
    cell and check that layer's blocks; a crossover via may only sit
    where the static site bitmap is clear and no route (own or foreign)
    reserved the surroundings (vkill bitmaps, Chebyshev-9 = every cell
    within 0.45+ mm of a reserved track); one drill carries the net
    between ANY two routing layers. The pads' own in-pad vias make the
    first/last flip free (all layers seeded). Where this net already
    has a via (placed bitmap: in-pad vias + previously emitted flip
    cells) the layer flip is free and stacks no copper."""
    w = grid.w
    ROUTE_DEBUG.clear()
    ROUTE_DEBUG["pops"] = 0
    ROUTE_DEBUG["far"] = 0
    ROUTE_DEBUG["viaok"] = 0
    site = grid.L["s"]
    mine = (placed or {}).get(me, ())
    # multi-source seeds over REAL copper only: the net's placed vias
    # (in-pad vias from the board + emitted flips, `_PLACED_VIA`) carry
    # copper on both layers, plus the job's own U1 pad. Reserved raster
    # cells of `own` are NOT seeds - an earlier attempt that seeded
    # those emitted nothing and the ratsnest wallowed.
    gx, gy = goal % w, goal // w
    seeds = []
    for layer, cell in (real or {}).get(me, ()):
        if cell != goal:
            seeds.append((layer, cell))
    seeds.append((0, start))
    for ldx in range(1, NL):
        seeds.append((ldx, start))
    g = {}
    parent = {}
    heap = []
    for node in seeds:
        g[node] = 0
        heappush(heap, (0,) + node)
    myown_raw = own.get(me)
    myown = ({idx: myown_raw[LAY_NAME[idx]] for idx in range(NL)}
             if myown_raw else {})

    def free(layer, i):
        if (layer, i) in ban:       # cells of guard-rejected plans
            return False
        block = grid.L[LAY_NAME[layer]]
        cells = myown.get(layer, ())
        if block[i]:
            return i in cells
        o = owner.get((layer, i))
        return o is None or o == me

    def via_ok(c):
        return not site[c] and all(vk[c] == 0 for vk in vkill)

    while heap:
        f, layer, cur = heappop(heap)
        if cur == goal:
            path = []
            node = (layer, cur)
            while node in parent:
                path.append(node)
                node = parent[node]
            path.append(node)
            path.reverse()
            ROUTE_DEBUG["pops"] += 1
            return path
        st = g[(layer, cur)]
        if f > st + (abs(cur % w - gx) + abs(cur // w - gy)) * 10:
            continue
        cx, cy = cur % w, cur // w
        for dx, dy, step in ((1, 0, 10), (-1, 0, 10), (0, 1, 10), (0, -1, 10)):
            nx, ny = cx + dx, cy + dy
            if not 0 <= nx < w or not 0 <= ny < grid.h:
                continue
            ni = ny * w + nx
            if not free(layer, ni):
                continue
            ng = st + step
            if ng < g.get((layer, ni), 1 << 30):
                g[(layer, ni)] = ng
                parent[(layer, ni)] = (layer, cur)
                hy = (abs(nx - gx) + abs(ny - gy)) * 10
                heappush(heap, (ng + hy, layer, ni))
        for other in range(NL):
            if other == layer:
                continue
            if cur in mine:             # own via here: flip is free
                ROUTE_DEBUG["viaok"] += 1
                ng = st + 1
            elif via_ok(cur):
                ROUTE_DEBUG["viaok"] += 1
                ng = st + via_cost
            else:
                continue
            if ng < g.get((other, cur), 1 << 30):
                g[(other, cur)] = ng
                parent[(other, cur)] = (layer, cur)
                hh = (abs(cx - gx) + abs(cy - gy)) * 10
                heappush(heap, (ng + hh, other, cur))
        ROUTE_DEBUG["pops"] += 1
        ROUTE_DEBUG["far"] = max(ROUTE_DEBUG["far"], st)
    return None


# every crossover via position this run has placed (or inherited from the
# board), per net: flips there reuse the existing via instead of stacking
# a second 0.30 drill on top of it
_PLACED_VIA = defaultdict(set)


def runs_of(path):
    """[(layer, [cells])] with the shared flip cell in both neighbour runs"""
    runs = []
    for lay, i in path:
        if runs and runs[-1][0] == lay:
            runs[-1][1].append(i)
        else:
            if runs:
                runs[-1][1].append(i)
            runs.append([lay, [i]])
    return runs


def segs_of(runs, grid):
    """straight segments of the emit geometry: [(layer, (x0, y0, x1, y1))]"""
    plan = []
    for lay, cells in runs:
        if len(cells) < 2:
            continue
        pts = [grid.xy(i) for i in cells]
        segpts = [pts[0]]
        for a, b, c in zip(pts, pts[1:], pts[2:]):
            d1 = (b[0] - a[0], b[1] - a[1])
            d2 = (c[0] - b[0], c[1] - b[1])
            if d1[0] * d2[1] - d1[1] * d2[0]:
                segpts.append(b)
        segpts.append(pts[-1])
        for a, b in zip(segpts, segpts[1:]):
            plan.append((lay, (a[0], a[1], b[0], b[1])))
    return plan


def emit(bd, net, path, grid, runs=None, log=None):
    """path: [(layer, cell)]; consecutive same-layer cells become polyline
    tracks on that layer, a layer change places a 0.45/0.30 via; flip
    cells are cross-checked against the site bitmap. log: list to record
    every created object (pass-4 rip-up bookkeeping)"""
    me = net.GetNetname()
    if runs is None:
        runs = runs_of(path)
    bad = [i for k, (l, i) in enumerate(path)
           if k and l != path[k - 1][0] and grid.L["s"][i]
           and i not in _PLACED_VIA[me]]
    if bad:
        print("VIA-BUG at", [grid.xy(i) for i in bad])
    n = 0
    for lay, (x0, y0, x1, y1) in segs_of(runs, grid):
        t = pcbnew.PCB_TRACK(bd)
        t.SetStart(pcbnew.VECTOR2I(int(x0 * 1e6), int(y0 * 1e6)))
        t.SetEnd(pcbnew.VECTOR2I(int(x1 * 1e6), int(y1 * 1e6)))
        t.SetWidth(int(TRACK * 1e6))
        t.SetLayer(LAY_KICAD[lay])
        t.SetNet(net)
        bd.Add(t)
        if log is not None:
            log.append(t)
        n += 1
    for lay, cells in runs[1:]:
        if cells[0] in _PLACED_VIA[me]:
            continue          # own via already exists here: reuse, no stack
        x, y = grid.xy(cells[0])
        v = pcbnew.PCB_VIA(bd)
        v.SetPosition(pcbnew.VECTOR2I(int(x * 1e6), int(y * 1e6)))
        v.SetWidth(int(SIG_VIA * 1e6))
        v.SetDrill(int(DRILL * 1e6))
        v.SetNet(net)
        v.SetViaType(pcbnew.VIATYPE_THROUGH)
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        bd.Add(v)
        if log is not None:
            log.append(v)
        _PLACED_VIA[me].add(cells[0])
        n += 1
    return n


# track reservations: Chebyshev-6 reserves every cell within 0.30 mm of a
# track cell; the DRC-legal closest approach for a foreign 0.15-mm track
# centre is 0.30 mm, so routes pass one lane cell wider (0.35 mm)
OFFSETS = [(dx, dy) for dx in range(-7, 8) for dy in range(-7, 8)
           if abs(dx) <= 6 and abs(dy) <= 6 and (dx or dy)]
# via kill: Chebyshev-8 covers every cell within 0.40 mm of a track cell;
# the legal closest approach for a crossover-via ring (0.225) to a foreign
# track centre is 0.45 mm, so vias sit one cell clear (0.45 mm)
VK_OFFS = [(dx, dy) for dx in range(-8, 9) for dy in range(-8, 9)
           if abs(dx) <= 8 and abs(dy) <= 8 and (dx or dy)]

GUARD_TT = TRACK + CLEAR          # track-track: centre-to-centre >= 0.30
GUARD_EPS = 0.006                 # float fuzz at exact DRC boundaries
GUARD_VEPS = 0.0025               # via fuzz: the 0.05 lattice's nearest
                                  # illegal via distance is 0.4472 (cap at
                                  # hypot(0.4, 0.2)), 0.0028 under 0.45; abs
                                  # exactness rejects legal 0.400 rings
GUARD_TRACE = []                  # [(net, seg, why)] of last rejections


def _seg_d(ax, ay, bx, by, px, py):
    """distance from point (px, py) to segment (ax..bx, ay..by)"""
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    if L == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def _seg_seg_d(a, b, p, q):
    """minimum distance between two segments (a-b, p-q)"""
    return min(_seg_d(*a, *b, *p), _seg_d(*a, *b, *q),
               _seg_d(*p, *q, *a), _seg_d(*p, *q, *b))


def _seg_rect_d(x0, y0, x1, y1, r):
    """exact distance between segment and axis-aligned rect r via its 4
    edges (segment inside the rect -> 0 via endpoint containment)"""
    xlo, ylo, xhi, yhi = r
    if (xlo <= x0 <= xhi and ylo <= y0 <= yhi) or \
       (xlo <= x1 <= xhi and ylo <= y1 <= yhi):
        return 0.0
    edges = (
        (( xlo,  ylo), (xhi,  ylo)), ((xhi,  ylo), (xhi,  yhi)),
        ((xhi,  yhi), ( xlo,  yhi)), (( xlo,  yhi), ( xlo,  ylo)))
    return min(_seg_seg_d((x0, y0), (x1, y1), a, b) for a, b in edges)


def guard_ok(bd, netname, plan, flips=(), skip=frozenset()):
    """plan: [(layer, (x0, y0, x1, y1))] straight segments of a route that
    is about to be emitted; flips: [(x, y)] of the run joints where NEW
    0.45/0.30 vias will be created (reused own vias must NOT be listed);
    skip: uuid-strings of items omitted (pass-4 isolated solves check
    static geometry only). None unless a foreign item on the same layer
    sits closer than DRC clearance (then: the reason string). The raster
    may model a corner as free while KiCad's round end caps (radius 0.075)
    still overlap - this is the hard gate against that."""
    for lay, (x0, y0, x1, y1) in plan:
        def why(msg):
            GUARD_TRACE.append((netname, lay, (x0, y0, x1, y1), msg))
            return msg
        xlo, xhi = min(x0, x1) - 0.8, max(x0, x1) + 0.8
        ylo, yhi = min(y0, y1) - 0.8, max(y0, y1) + 0.8
        for t in bd.GetTracks():
            if t.GetNetname() == netname:
                continue
            if skip and t.m_Uuid.AsString() in skip:
                continue
            if t.GetClass() == "PCB_VIA":
                x, y = t.GetPosition().x / 1e6, t.GetPosition().y / 1e6
                if not (xlo <= x <= xhi and ylo <= y <= yhi):
                    continue
                r = t.GetWidth(t.GetLayer()) / 1e6 / 2
                d = _seg_d(x0, y0, x1, y1, x, y)
                # GUARD_VEPS, not 0: exact-boundary rings (d = 0.400/0.450)
                # are legal and common
                if d < r + TRACK / 2 + CLEAR - GUARD_VEPS:
                    return why(f"VIA {t.GetNetname()} r{r:.2f} d{d:.3f} "
                               f"@{x:.2f},{y:.2f}")
                continue
            tl = next((i for i in range(NL)
                       if t.GetLayer() == LAY_KICAD[i]), None)
            if tl != lay:
                continue
            a = (t.GetStart().x / 1e6, t.GetStart().y / 1e6)
            b = (t.GetEnd().x / 1e6, t.GetEnd().y / 1e6)
            if not (min(a[0], b[0]) <= xhi and max(a[0], b[0]) >= xlo and
                    min(a[1], b[1]) <= yhi and max(a[1], b[1]) >= ylo):
                continue
            d = _seg_seg_d((x0, y0), (x1, y1), a, b)
            if d < GUARD_TT - GUARD_EPS:
                return why(f"TRK {t.GetNetname()} d{d:.3f} "
                           f"@{a[0]:.2f},{a[1]:.2f}..{b[0]:.2f},{b[1]:.2f}")
        for fp in bd.GetFootprints():
            for p in fp.Pads():
                if p.GetNetname() == netname or p.GetNetCode() == 0:
                    continue
                r = as_rect(p)
                if r[2] < xlo or r[0] > xhi or r[3] < ylo or r[1] > yhi:
                    continue
                # SMD lands sit on one outer layer; inner tracks never
                # see them
                if lay != (0 if pad_side(p) == "b" else NL - 1):
                    continue
                d = _seg_rect_d(x0, y0, x1, y1, r)
                if d < TRACK / 2 + CLEAR - GUARD_EPS:
                    return why(f"PAD {fp.GetReference()}/{p.GetNetname()} "
                               f"d{d:.3f} rect{r}")
    # new-via ring vs foreign-via ring: centre distance must cover
    # both annuli + clearance (0.60 for two 0.45 vias) - not covered by
    # the segment rule above (run24: CS#1/BA2 at 0.559)
    for fx, fy in flips:
        for t in bd.GetTracks():
            if t.GetClass() != "PCB_VIA" or t.GetNetname() == netname:
                continue
            if skip and t.m_Uuid.AsString() in skip:
                continue
            x, y = t.GetPosition().x / 1e6, t.GetPosition().y / 1e6
            r = t.GetWidth(t.GetLayer()) / 1e6 / 2
            d = math.hypot(fx - x, fy - y)
            if d < r + SIG_VIA / 2 + CLEAR - GUARD_VEPS:
                return why(f"VIA-V {t.GetNetname()} r{r:.2f} d{d:.3f} "
                           f"@{x:.2f},{y:.2f}")
    return None


def main():
    bd = pcbnew.LoadBoard(str(PCB))
    NC = bd.GetNetCount()
    netobj = {}
    for i in range(NC):
        n = bd.FindNet(i)
        if n:
            netobj[n.GetNetname()] = n
    counts = reroute_prep(bd)
    print("prep:", dict(counts))

    # ---- two-layer block map ----------------------------------------------
    # B map: in-pad via rings (both layers: a via exists on every layer it
    # crosses), foreign B.Cu tracks. F map: same via rings, foreign F.Cu
    # tracks, SMD pad lands (F copper). Both: Z4 notch keep-out, edges.
    # Rebuilt between passes so emitted tracks/vias become obstacles.
    W_MM, H_MM = 127.0, 57.8                  # S7 outline (D16)

    def build_maps(skip=frozenset()):
        """skip: uuid-strings of items that stay unrasterized (pass-4
        rip-up: the s8c-emitted copper is 'transparent' while solving a
        leftover job against the static S8b geometry)"""
        grid = Grid(W_MM, H_MM)
        # via-site bitmap: a crossover via (0.45/0.30) may only be placed
        # where no foreign copper and no drill sits inside ring+clearance
        # +hole rules
        for t in bd.GetTracks():
            if skip and t.m_Uuid.AsString() in skip:
                continue
            if t.GetClass() == "PCB_VIA":
                pos = t.GetPosition()
                dial = t.GetWidth(t.GetLayer()) / 1e6 / 2
                # foreign ring: track centre must be >= ring + track/2 +
                # clear; strict inequality so an exactly-min margin stays
                # routable; a TH via shows its ring on every routing layer
                for layer in LAY_NAME.values():
                    grid.disk(pos.x / 1e6, pos.y / 1e6, dial + MARGIN,
                              layer)
                # via-site kill: ring-to-ring (sits at ring + our ring +
                # clear, NOT at the drill: run24 paired CS#1/BA2 vias at
                # 0.559 < 0.60), hole-to-copper and hole-to-hole margins
                # against our 0.45/0.30 vias
                r_site = max(dial + SIG_VIA / 2 + CLEAR,
                             t.GetDrill() / 1e6 / 2 + 0.25 + DRILL / 2)
                grid.disk(pos.x / 1e6, pos.y / 1e6, r_site, "s")
        for fp in bd.GetFootprints():
            for p in fp.Pads():
                r = as_rect(p)
                grid.srect(r[0] - MARGIN, r[1] - MARGIN,
                           r[2] + MARGIN, r[3] + MARGIN, pad_side(p))
                grid.srect(r[0] - 0.375, r[1] - 0.375,
                           r[2] + 0.375, r[3] + 0.375, "s")
        for t in bd.GetTracks():
            if skip and t.m_Uuid.AsString() in skip:
                continue
            if t.GetClass() != "PCB_TRACK":
                continue
            layk = t.GetLayer()
            layer = next((LAY_NAME[i] for i in range(NL)
                          if layk == LAY_KICAD[i]), None)
            a, b = t.GetStart(), t.GetEnd()
            seg_band = t.GetWidth() / 1e6 / 2 + CLEAR + TRACK / 2
            grid.seg(a.x / 1e6, a.y / 1e6, b.x / 1e6, b.y / 1e6,
                     seg_band, layer)
            grid.seg(a.x / 1e6, a.y / 1e6, b.x / 1e6, b.y / 1e6,
                     seg_band + 0.15, "s")
        for layer in tuple(LAY_NAME.values()) + ("s",):
            grid.rect(75.5, 0.0, 77.5, 2.49, layer)   # Z4 notch keep-out
            grid.rect(0.0, 0.0, W_MM, 0.25, layer)
            grid.rect(0.0, H_MM - 0.25, W_MM, H_MM, layer)
            grid.rect(0.0, 0.0, 0.25, H_MM, layer)
            grid.rect(W_MM - 0.25, 0.0, W_MM, H_MM, layer)
        return grid

    grid = build_maps()
    chk = [grid.idx(61.5, 16.0), grid.idx(70.45, 29.0), grid.idx(90.0, 22.5)]
    print("site-check:", {grid.xy(i): grid.L["s"][i] for i in chk})

    # ---- route die nets (fan-out pairs) ---------------------------------
    die = {"U3", "U4", "U5", "U6"}
    padded = defaultdict(list)
    for fp in bd.GetFootprints():
        ref = fp.GetReference()
        for p in fp.Pads():
            if p.GetNetCode() == 0 or is_power(p.GetNetname()):
                continue
            x, y = p.GetPosition().x / 1e6, p.GetPosition().y / 1e6
            padded[p.GetNetname()].append((ref, x, y))
    jobs = []            # (net, u1pad, diepad)
    for name, v in padded.items():
        if "U1" not in {a[0] for a in v}:
            continue
        for p in v:
            if p[0] in die:
                jobs.append((name, next(a for a in v if a[0] == "U1"), p))
    print("die jobs:", len(jobs))

    # escape order (NM29 phase-2 lesson): deepest ball first, like the
    # classic 2-layer BGA funnel - an interior pad must cross every ring
    # on its way out, so it takes corridor capacity BEFORE the shallow
    # ones spend it. Depth = min rings-to-edge of the two endpoints'
    # footprints (ball lattices are 1.0/0.8 mm pitch). NM40 experiment:
    # net-grouped ordering (spine first, branches riding) scored WORSE
    # (136/184 vs 162/184) - reverted; the depth order stays interleaved.
    bbox = {fp.GetReference(): (min(p.GetPosition().x / 1e6 - p.GetSize().x / 2e6
                                    for p in fp.Pads()),
                                min(p.GetPosition().y / 1e6 - p.GetSize().y / 2e6
                                    for p in fp.Pads()),
                                max(p.GetPosition().x / 1e6 + p.GetSize().x / 2e6
                                    for p in fp.Pads()),
                                max(p.GetPosition().y / 1e6 + p.GetSize().y / 2e6
                                    for p in fp.Pads()))
            for fp in bd.GetFootprints() if fp.GetReference() in BGAS}

    def depth(ref, x, y):
        x0, y0, x1, y1 = bbox[ref]
        pitch = 1.0 if ref == "U1" else 0.8
        return min(x - x0, x1 - x, y - y0, y1 - y) / pitch

    def length_key(j):
        d1 = max(depth(j[1][0], j[1][1], j[1][2]),
                 depth(j[2][0], j[2][1], j[2][2]))
        far = ((j[1][1] - j[2][1]) ** 2 + (j[1][2] - j[2][2]) ** 2)
        return (-d1, far, j[0])

    todo = sorted(jobs, key=length_key)
    jobnets = {j[0] for j in jobs}
    for t in bd.GetTracks():     # in-pad vias of routeable nets
        if t.GetClass() == "PCB_VIA" and t.GetNetname() in jobnets:
            c = grid.idx(t.GetPosition().x / 1e6, t.GetPosition().y / 1e6)
            if c is not None:
                _PLACED_VIA[t.GetNetname()].add(c)
    # NM41: static in-pad via cell sets (never emitted, never ripped)
    static_pv = {n: set(v) for n, v in _PLACED_VIA.items()}
    EMITTED_UUIDS = set()   # uuid-strings of s8c-created tracks/vias
    EMITTED_JOBS = []       # {"key": (net, die), "net", "objs", "uuids",
    #                        "path", "job": (name, u1p, diep)} per emitted

    def merge_own(own, name, path):
        """a successfully routed path's cells stay passable for the SAME
        net's later jobs (multi-drop branches ride the earlier route);
        flip cells go on every routing layer"""
        if name not in own:
            return
        sets = own[name]
        prev = None
        for l, i in path:
            if prev is not None and l != prev:
                for ldx in range(NL):
                    sets[LAY_NAME[ldx]].add(i)
            sets[LAY_NAME[l]].add(i)
            prev = l

    selfpaths = defaultdict(list)   # net -> emitted paths (all branches)
    # net -> [(layer, cell)] of REAL copper: every emitted path's cells
    # (a flip cell exists on both layers). These seed astar's
    # multi-source search (NM36) - reserved raster of `own` is NOT real
    # copper, and the board's pre-existing in-pad vias are NOT seeds
    # either: a die pad's own floating via would make the job a no-op
    # (run19: routed 158 but unconnected only 458 instead of ~383).
    realcopper = defaultdict(list)
    tot_ok = 0
    n_victims = 0
    for pass_no in (1, 2, 3, 4):
        if pass_no == 4:
            # ---- NM41 deterministic rip-up (single wave) ----------------
            # The current todo's jobs are solved against the static
            # raster below the emitted copper (emitted items
            # transparent: build_maps(skip)); every emitted job-path
            # whose real geometry conflicts with such a solution is
            # RIPPED whole (objects deleted; _PLACED_VIA flip cells -
            # never the static in-pad cells - and selfpaths entries
            # reverted), the jobs route first on the rebuilt raster,
            # the ripped family re-routes after them. Cap 1 wave: the
            # NM42 wave-5 fixpoint re-rip landed work and collapsed to
            # 156/390 (run41) - iterated family rips never converge
            # under this congestion profile.
            if not todo or not EMITTED_UUIDS:
                break
            # NM41: emit-time proxies go STALE after bd.Add (the board's
            # track container reallocates; run36 bound: deleted proxies
            # destroyed neighbour nets' copper). Resolve all reads and
            # deletes through the board's LIVE items, looked up by uuid.
            live = {}
            for t in bd.GetTracks():
                live[t.m_Uuid.AsString()] = t
            skip = frozenset(EMITTED_UUIDS)
            grid_s = build_maps(skip)
            own_s = own_cells(bd, grid_s, {j[0] for j in todo}, skip)
            crit = []          # (name, u1p, diep, plan, flips)
            for name, u1p, diep in todo:
                s = grid_s.idx(u1p[1], u1p[2])
                g = grid_s.idx(diep[1], diep[2])
                if s is None or g is None:
                    continue
                ps = astar(grid_s, s, g, {}, name, own_s,
                           [bytearray(grid_s.w * grid_s.h)
                            for _ in range(NL)],
                           _PLACED_VIA, real=realcopper, via_cost=80)
                if ps is None:
                    print("  ripup: no isolated path", name, diep[0])
                    continue
                runs = runs_of(ps)
                plan = segs_of(runs, grid_s)
                flips = tuple(grid_s.xy(r[1][0]) for r in runs[1:]
                              if r[1][0] not in _PLACED_VIA[name])
                crit.append((name, u1p, diep, plan, flips))
            victims = {}       # key -> emitted-job entry to rip
            for name, u1p, diep, plan, flips in crit:
                for ej in EMITTED_JOBS:
                    if ej["key"] in victims or ej["net"] == name or \
                            ej.get("root"):
                        # roots carry their net's only U1-side copper;
                        # ripping one dismembers the net (run34/36)
                        continue
                    hit = False
                    for lay, (x0, y0, x1, y1) in plan:
                        for u in ej["uuids"]:
                            o = live.get(u)
                            if o is None:
                                continue
                            if o.GetClass() == "PCB_VIA":
                                d = _seg_d(x0, y0, x1, y1,
                                           o.GetPosition().x / 1e6,
                                           o.GetPosition().y / 1e6)
                                if d < (o.GetWidth(o.GetLayer())
                                        / 1e6 / 2 + TRACK / 2 + CLEAR
                                        - GUARD_VEPS):
                                    hit = True
                            else:
                                d = _seg_seg_d(
                                    (x0, y0), (x1, y1),
                                    (o.GetStart().x / 1e6,
                                     o.GetStart().y / 1e6),
                                    (o.GetEnd().x / 1e6,
                                     o.GetEnd().y / 1e6))
                                if d < GUARD_TT - GUARD_EPS:
                                    hit = True
                            if hit:
                                break
                        if hit:
                            break
                    if not hit:
                        # the isolated solution's new vias vs this path
                        for fx, fy in flips:
                            for u in ej["uuids"]:
                                o = live.get(u)
                                if o is None:
                                    continue
                                if o.GetClass() == "PCB_VIA":
                                    d = math.hypot(
                                        fx - o.GetPosition().x / 1e6,
                                        fy - o.GetPosition().y / 1e6)
                                    if d < (o.GetWidth(o.GetLayer())
                                            / 1e6 / 2 + SIG_VIA / 2
                                            + CLEAR - GUARD_VEPS):
                                        hit = True
                                else:
                                    d = _seg_d(
                                        o.GetStart().x / 1e6,
                                        o.GetStart().y / 1e6,
                                        o.GetEnd().x / 1e6,
                                        o.GetEnd().y / 1e6, fx, fy)
                                    if d < (SIG_VIA / 2 + TRACK / 2
                                            + CLEAR - GUARD_EPS):
                                        hit = True
                                if hit:
                                    break
                            if hit:
                                break
                    if hit:
                        # NM41 family rip: a rider's spur may anchor on
                        # an EARLIER RIDER's cell, so deleting one path
                        # orphans every same-net path whose start cell
                        # lies on it. Take the transitive descendant
                        # closure of the victim (registration order is
                        # topological: an anchor is always emitted
                        # before its dependents) - all of them re-route.
                        fam = {ej["key"]: ej}
                        frontier = {c for _, c in ej["path"]}
                        grew = True
                        while grew:
                            grew = False
                            for ej2 in EMITTED_JOBS:
                                if ej2["net"] != ej["net"] or \
                                        ej2["key"] in fam or \
                                        ej2.get("root"):
                                    continue
                                if ej2["path"][0][1] in frontier:
                                    fam[ej2["key"]] = ej2
                                    grew = True
                                    frontier |= {c for _, c
                                                 in ej2["path"]}
                        victims.update(fam)
                        # no break: one solution may rip several paths
            if victims:
                # snapshot the victims' flip-via positions BEFORE the
                # deletes (with LIVE items only: proxies go stale)
                pre_delete = []
                for ej in victims.values():
                    nm = ej["net"]
                    for u in ej["uuids"]:
                        o = live.get(u)
                        if o is None or o.GetClass() != "PCB_VIA":
                            continue
                        gc = grid_s.idx(o.GetPosition().x / 1e6,
                                        o.GetPosition().y / 1e6)
                        if gc is not None and \
                                gc not in static_pv.get(nm, ()):
                            pre_delete.append((nm, gc))
                # NM41: victim listing (pre-rip board snapshot removed;
                # the frozen forensics copy lives in /tmp/opencode)
                print("  ripup victims:", ", ".join(
                    k[0] + "@" + k[1] for k in sorted(victims)))
                for ej in victims.values():
                    for u in ej["uuids"]:
                        o = live.get(u)
                        if o is not None:
                            bd.Delete(o)
                    EMITTED_UUIDS.difference_update(ej["uuids"])
                ejset = set(victims)
                EMITTED_JOBS[:] = [e for e in EMITTED_JOBS
                                   if e["key"] not in ejset]
                for ej in victims.values():
                    nm = ej["net"]
                    selfpaths[nm] = [p for p in selfpaths[nm]
                                     if p is not ej["path"]]
                for nm, gc in pre_delete:
                    _PLACED_VIA[nm].discard(gc)
                # rebuild the nets' real-copper seeds from the surviving
                # paths only: a stale cell would seed a phantom start
                # (floating copper: DRC-legal, ratsnest-wrong)
                for nm2 in {v["net"] for v in victims.values()}:
                    out = []
                    for p in selfpaths[nm2]:
                        for k, (l, i) in enumerate(p):
                            if k and l != p[k - 1][0]:
                                for ldx in range(NL):
                                    out.append((ldx, i))
                            else:
                                out.append((l, i))
                    realcopper[nm2] = out
                n_victims = len(victims)
                # the victims' earlier successes lose their credit; the
                # pass-4 sweep re-earns them (or shows up as fails)
                tot_ok -= n_victims
                print("  ripup: ripped", n_victims, "job-paths;",
                      len(crit), "leftovers have isolated paths")
                todo = [c[:3] for c in crit]
                # family members re-route in emission order: parents
                # (anchors) before the descendants that anchored on them
                todo += [v["job"] for v in
                         sorted(victims.values(),
                                key=lambda e: e["ord"])]
            else:
                print("  ripup: nothing recoverable")
                break
        grid = build_maps()      # includes tracks/vias emitted so far
        own = own_cells(bd, grid, {j[0] for j in todo} | set(selfpaths))
        for name, ps in selfpaths.items():
            for p in ps:
                merge_own(own, name, p)
        owner = {}       # (layer, cell) -> owning net (track reservations)
        vkill = [bytearray(grid.w * grid.h) for _ in range(NL)]
        ok = fail = 0
        remaining = []
        todo = list(reversed(todo)) if pass_no == 2 else todo
        vcost = 30 if pass_no == 3 else 80
        for name, u1p, diep in todo:
            s = grid.idx(u1p[1], u1p[2])
            g = grid.idx(diep[1], diep[2])
            if s is None or g is None:
                fail += 1
                continue
            path = astar(grid, s, g, owner, name, own, vkill, _PLACED_VIA,
                         real=realcopper, via_cost=vcost)
            if path is None:
                fail += 1
                if fail <= 3 and pass_no == 2:
                    print("  fail:", name, diep[0], dict(ROUTE_DEBUG))
                remaining.append((name, u1p, diep))
                continue
            runs = runs_of(path)
            plan = segs_of(runs, grid)
            flips = tuple(grid.xy(r[1][0]) for r in runs[1:]
                          if r[1][0] not in _PLACED_VIA[name])
            gv = guard_ok(bd, name, plan, flips)
            if gv:
                # the raster's ownership hole (a foreign branch riding the
                # same 0.35-mm corridor) - fail the job, no rip-up
                fail += 1
                print("  guard-reject:", name, diep[0], gv)
                remaining.append((name, u1p, diep))
                continue
            ok += 1
            log = []                 # NM41: pass-4 rip-up bookkeeping
            emit(bd, netobj[name], path, grid, runs, log)
            uuids = frozenset(o.m_Uuid.AsString() for o in log)
            EMITTED_UUIDS.update(uuids)
            # a path that BEGINS at the net's U1 pad is the ROOT: pass 1
            # seeded every later rider from real copper, so the root is
            # the ONLY job carrying the U1-side copper of the net - no
            # neighbour job's reroute can replace it. root entries are
            # exempt from rip-up (NM41: ripping one left ~26 nets with a
            # floating U1 pad in run34/36).
            c_u1 = grid.idx(u1p[1], u1p[2])
            EMITTED_JOBS.append({"key": (name, diep[0]), "net": name,
                                 "objs": log, "uuids": uuids,
                                 "path": path, "job": (name, u1p, diep),
                                 "root": path[0][1] == c_u1,
                                 "ord": len(EMITTED_JOBS)})
            selfpaths[name].append(path)
            merge_own(own, name, path)
            for k, (l, i) in enumerate(path):    # grow real-copper seeds
                if k and l != path[k - 1][0]:
                    for ldx in range(NL):        # flip: copper on all layers
                        realcopper[name].append((ldx, i))
                else:
                    realcopper[name].append((l, i))
            # flips exist on both layers; track cells reserve their layer
            flips = {i for k, (l, i) in enumerate(path)
                     if k and l != path[k - 1][0]}
            for i in flips:                 # new vias block later routes
                x, y = grid.xy(i)
                for lname in LAY_NAME.values():
                    grid.disk(x, y, SIG_VIA / 2 + MARGIN, lname)
                grid.disk(x, y, max(SIG_VIA + CLEAR, DRILL + 0.25), "s")
            for lay, i in path:
                lays = tuple(range(NL)) if i in flips else (lay,)
                cx, cy = i % grid.w, i // grid.w
                for layer in lays:
                    for dx, dy in OFFSETS:      # track corridor reservation
                        px, py = cx + dx, cy + dy
                        if not 0 <= px < grid.w or not 0 <= py < grid.h:
                            continue
                        kk = (layer, py * grid.w + px)
                        if kk not in owner or owner[kk] == name:
                            owner[kk] = name
                    harr = vkill[layer]
                    for dx, dy in VK_OFFS:      # via kill zone
                        px, py = cx + dx, cy + dy
                        if 0 <= px < grid.w and 0 <= py < grid.h:
                            harr[py * grid.w + px] = 1
        tot_ok += ok
        todo = remaining
        print(f"pass {pass_no}: routed {ok} failed {fail} left {len(todo)}")
        if not todo:
            break
    print("routed:", tot_ok, "failed:", len(todo))

    # ---- refill + save + gates -------------------------------------------
    pcbnew.ZONE_FILLER(bd).Fill(bd.Zones())
    pcbnew.SaveBoard(str(PCB), bd)
    print("saved + filled")
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json",
                    "-o", str(GATE), str(PCB)], capture_output=True)
    rep = json.loads(GATE.read_text())
    errs = [v for v in rep["violations"] if v["severity"] == "error"]
    print("DRC errors:", len(errs))
    for v in errs[:12]:
        print("   ", v["type"], v["description"][:100])
    bd2 = pcbnew.LoadBoard(str(PCB))
    print("unconnected:", bd2.GetConnectivity().GetUnconnectedCount(True))


if __name__ == "__main__":
    main()
