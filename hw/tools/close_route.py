#!/usr/bin/env python3
"""Close the open connections freerouting leaves: a windowed A* over the signal layers with the
net-class clearances, the hole rules and the keepouts; KiCad DRC stays the judge (autoroute.py).
    close_route.py <board.kicad_pcb> <drc.json> <out.kicad_pcb>"""
import heapq
import json
import math
import sys

import numpy as np
import pcbnew
from PIL import Image, ImageDraw
from scipy import ndimage

G = 0.05                                 # grid (mm)
WINDOW = 5.0                             # around the two ends
MAX_SPAN = 40.0
LAYERS, LAYER_COST = (), ()             # the board's signal layers, outer ones dearer: set by close()
OUTER_COST = 1.3
VIA_D, VIA_DRILL, VIA_COST = 0.45, 0.25, 30          # via cost in grid steps
HOLE_CLR, HOLE_TO_HOLE, EDGE, MARGIN = 0.2, 0.25, 0.3, G     # MARGIN: raster offset and staircase
MAX_EXPAND = 1500000
MM = 1e6
STEPS = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
         (1, 1, math.sqrt(2)), (1, -1, math.sqrt(2)), (-1, 1, math.sqrt(2)), (-1, -1, math.sqrt(2))]


def copper_layers(board):
    """the copper layers in stack order"""
    n = board.GetCopperLayerCount()
    return (pcbnew.F_Cu, *(getattr(pcbnew, f"In{k}_Cu") for k in range(1, n - 1)), pcbnew.B_Cu)


class Window:
    """per layer: where a track centre may go, where a via may go, and this net's own copper"""
    def __init__(self, board, net, box, width, clr_of):
        self.x0, self.y0 = box[0] - WINDOW, box[1] - WINDOW
        self.nx = int((box[2] - box[0] + 2 * WINDOW) / G) + 1
        self.ny = int((box[3] - box[1] + 2 * WINDOW) / G) + 1
        track, own, via = [self.blank() for _ in LAYERS], [self.blank() for _ in LAYERS], self.blank()
        w, r = width / 2, VIA_D / 2
        items = [t for t in board.GetTracks() if self.touches(t)] + \
                [p for f in board.GetFootprints() for p in f.Pads() if self.touches(p)]
        for it in items:
            same = it.GetNetname() == net and it.GetNetCode() > 0
            clr = clr_of(it)
            for k, L in enumerate(LAYERS):
                if not it.IsOnLayer(L):
                    continue
                if same:
                    self.draw(own[k], it, L, 0.0)
                else:
                    self.draw(track[k], it, L, clr + w + MARGIN)
                    self.draw(via, it, L, clr + r + MARGIN)
            drill = it.GetDrillValue() if isinstance(it, pcbnew.PCB_VIA) else \
                max(it.GetDrillSizeX(), it.GetDrillSizeY()) if isinstance(it, pcbnew.PAD) else 0
            if drill:
                x, y, d = it.GetPosition().x / MM, it.GetPosition().y / MM, drill / MM / 2
                self.circle(via, x, y, d + max(HOLE_TO_HOLE + VIA_DRILL / 2, HOLE_CLR + r) + MARGIN)
                if not same:
                    for t in track:
                        self.circle(t, x, y, d + HOLE_CLR + w + MARGIN)
        for z in board.Zones():
            if z.GetIsRuleArea():
                for k, L in enumerate(LAYERS):
                    if z.GetDoNotAllowTracks() and z.IsOnLayer(L):
                        self.poly(track[k], z.Outline())
                if z.GetDoNotAllowVias():
                    self.poly(via, z.Outline())
        e = board.GetBoardEdgesBoundingBox()
        for im, keep in [(t, EDGE + w) for t in track] + [(via, EDGE + r)]:
            inside = Image.new("1", im.size, 1)
            ImageDraw.Draw(inside).rectangle(
                [(e.GetLeft() / MM + keep - self.x0) / G, (e.GetTop() / MM + keep - self.y0) / G,
                 (e.GetRight() / MM - keep - self.x0) / G, (e.GetBottom() / MM - keep - self.y0) / G], fill=0)
            im.paste(1, mask=inside)
        self.inset = int(math.ceil(w / G)) + 1       # cells: a track (half width w) centred this deep stays inside
        self.own = [ndimage.binary_erosion(np.array(o, bool), iterations=self.inset) for o in own]
        self.track = [np.array(t, bool) & ~o for t, o in zip(track, self.own)]
        self.via = np.array(via, bool)

    def blank(self):
        return Image.new("1", (self.nx, self.ny), 0)

    def touches(self, it):
        b = it.GetBoundingBox()
        return not (b.GetRight() / MM < self.x0 - 1 or b.GetLeft() / MM > self.x0 + self.nx * G + 1 or
                    b.GetBottom() / MM < self.y0 - 1 or b.GetTop() / MM > self.y0 + self.ny * G + 1)

    def poly(self, im, ps):
        d = ImageDraw.Draw(im)
        for k in range(ps.OutlineCount()):
            d.polygon(self.pix(ps.Outline(k)), fill=1)
            for h in range(ps.HoleCount(k)):
                d.polygon(self.pix(ps.Hole(k, h)), fill=0)

    def pix(self, chain):
        return [((chain.CPoint(i).x / MM - self.x0) / G, (chain.CPoint(i).y / MM - self.y0) / G)
                for i in range(chain.PointCount())]

    def draw(self, im, it, layer, inflate):
        ps = pcbnew.SHAPE_POLY_SET()
        it.TransformShapeToPolygon(ps, layer, int(inflate * MM), 2000, pcbnew.ERROR_OUTSIDE)
        self.poly(im, ps)

    def circle(self, im, x, y, rad):
        cx, cy, rr = (x - self.x0) / G, (y - self.y0) / G, rad / G
        ImageDraw.Draw(im).ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=1)

    def xy(self, j, i):
        return pcbnew.VECTOR2I(int(round((self.x0 + i * G) * MM)), int(round((self.y0 + j * G) * MM)))

    def cells(self, items):
        """the cells a track of this width may start or end on, per layer: inside the copper, and
        the centre of each pad / via (a pad narrower than the track: DRC judges the overhang)"""
        out = []
        for L in LAYERS:
            im = self.blank()
            for it in items:
                if it.IsOnLayer(L) and self.touches(it):
                    self.draw(im, it, L, 0.0)
            c = ndimage.binary_erosion(np.array(im, bool), iterations=self.inset)
            for it in items:
                j, i = self.cell(it.GetPosition())
                if not isinstance(it, pcbnew.PCB_TRACK) or isinstance(it, pcbnew.PCB_VIA):
                    if it.IsOnLayer(L) and 0 <= j < self.ny and 0 <= i < self.nx:
                        c[j, i] = True
            out.append(c)
        return out

    def cell(self, p):
        return int(round((p.y / MM - self.y0) / G)), int(round((p.x / MM - self.x0) / G))


def search(win, src, dst):
    tj, ti = np.nonzero(np.any(dst, axis=0))
    if not len(tj) or not any(s.any() for s in src):
        return None
    by0, by1, bx0, bx1 = tj.min(), tj.max(), ti.min(), ti.max()
    h = lambda j, i: math.hypot(max(bx0 - i, 0, i - bx1), max(by0 - j, 0, j - by1))
    dist, prev, heap = {}, {}, []
    for k in range(len(LAYERS)):
        for j, i in zip(*np.nonzero(src[k])):
            s = (k, int(j), int(i))
            dist[s] = 0.0
            heapq.heappush(heap, (h(j, i), 0.0, s))
    for n in range(MAX_EXPAND):
        if not heap:
            return None
        _, d, s = heapq.heappop(heap)
        if d > dist[s]:
            continue
        k, j, i = s
        if dst[k][j, i]:
            path = [s]
            while path[-1] in prev:
                path.append(prev[path[-1]])
            return path[::-1]
        nbrs = [((k, j + dj, i + di), c * LAYER_COST[k]) for di, dj, c in STEPS
                if 0 <= j + dj < win.ny and 0 <= i + di < win.nx and not win.track[k][j + dj, i + di]]
        if not win.via[j, i]:
            nbrs += [((q, j, i), VIA_COST) for q in range(len(LAYERS)) if q != k and not win.track[q][j, i]]
        for t, c in nbrs:
            if d + c < dist.get(t, 1e18):
                dist[t], prev[t] = d + c, s
                heapq.heappush(heap, (d + c + h(t[1], t[2]), d + c, t))
    return None


def commit(board, win, path, net, width):
    """the path as straight tracks between its corners, a via at each layer change"""
    def tracks(run):
        corners = [run[0]] + [b for a, b, c in zip(run, run[1:], run[2:]) if (b[1] - a[1], b[2] - a[2]) !=
                              (c[1] - b[1], c[2] - b[2])] + [run[-1]]
        for a, b in zip(corners, corners[1:]):
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(win.xy(a[1], a[2]))
            t.SetEnd(win.xy(b[1], b[2]))
            t.SetWidth(pcbnew.FromMM(width))
            t.SetLayer(LAYERS[a[0]])
            t.SetNet(net)
            board.Add(t)
    run = [path[0]]
    for s in path[1:]:
        if s[0] == run[-1][0]:
            run.append(s)
            continue
        if len(run) > 1:
            tracks(run)
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(win.xy(s[1], s[2]))
        v.SetWidth(pcbnew.FromMM(VIA_D))
        v.SetDrill(pcbnew.FromMM(VIA_DRILL))
        v.SetNet(net)
        board.Add(v)
        run = [s]
    if len(run) > 1:
        tracks(run)


def close(board, report):
    """route each open pair of the DRC report, shortest first (a PCIe pair as two nets: the skew
    is gen_c2mu_s8.py's check): (routed, tried)"""
    global LAYERS, LAYER_COST
    LAYERS = tuple(L for L in copper_layers(board) if board.GetLayerType(L) != pcbnew.LT_POWER)
    LAYER_COST = tuple(OUTER_COST if L in (pcbnew.F_Cu, pcbnew.B_Cu) else 1.0 for L in LAYERS)
    ns = board.GetDesignSettings().m_NetSettings
    planes = {z.GetNetname() for z in board.Zones() if not z.GetIsRuleArea()}
    byid = {p.m_Uuid.AsString(): p for f in board.GetFootprints() for p in f.Pads()}
    byid.update({t.m_Uuid.AsString(): t for t in board.GetTracks()})
    pairs = []
    for u in report["unconnected_items"]:
        a, b = (byid.get(i["uuid"]) for i in u["items"][:2])
        if a is not None and b is not None and a.GetNetname() not in planes:
            pairs.append((a, b))
    pairs.sort(key=lambda ab: (ab[0].GetPosition() - ab[1].GetPosition()).EuclideanNorm())
    routed = 0
    for a, b in pairs:
        board.BuildConnectivity()
        conn = board.GetConnectivity()
        island = lambda it: [it] + [q for q in conn.GetConnectedItems(it)
                                    if isinstance(q, (pcbnew.PAD, pcbnew.PCB_TRACK))]
        ia, ib = island(a), island(b)
        if any(q.m_Uuid == b.m_Uuid for q in ia):
            continue                                      # joined by an earlier route
        pa, pb = a.GetPosition(), b.GetPosition()
        box = (min(pa.x, pb.x) / MM, min(pa.y, pb.y) / MM, max(pa.x, pb.x) / MM, max(pa.y, pb.y) / MM)
        if box[2] - box[0] > MAX_SPAN or box[3] - box[1] > MAX_SPAN:
            continue
        net = a.GetNetname()
        cls = ns.GetEffectiveNetClass(net)
        width = cls.GetTrackWidth() / MM
        clr_of = lambda it: max(cls.GetClearance(), ns.GetEffectiveNetClass(it.GetNetname()).GetClearance()) / MM
        win = Window(board, net, box, width, clr_of)
        path = search(win, win.cells(ia), win.cells(ib))
        if path is not None:
            commit(board, win, path, a.GetNet(), width)
            routed += 1
    return routed, len(pairs)


def main():
    board = pcbnew.LoadBoard(sys.argv[1])
    routed, tried = close(board, json.load(open(sys.argv[2])))
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(sys.argv[3], board)
    print(f"routed {routed} of {tried}")


if __name__ == "__main__":
    main()
