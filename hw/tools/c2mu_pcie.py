"""C2 Mu PCIe x4 + REFCLK2 pair template (plan/slot1_c2.md): every pair drawn from computed straight
and 45 deg segments, P and N matched in length, locked. gen_c2mu_s6.py wires the AC capacitors by
LINKS, gen_c2mu_s7.py places them at the template spots and keeps other parts off its copper,
gen_c2mu_s8.py draws it before the rest is autorouted and checks the skew on the board.
Rules [design_guide_pcie]: 85 ohm differential: 0.2 mm tracks, 0.2 mm gap on F.Cu / B.Cu over the
0.116 mm 2116 prepreg (IPC-2141: 47 ohm single, 85 ohm coupled); intra-pair skew < 5 mil (REFCLK
15 mil); AC capacitors on the FPGA TX lanes within 8 mm of the chip, on the Mu TX lanes near its
connector; P and N may swap in any pair (polarity inversion, REFCLK too); lane order fixed.
Topology (U1 ball A1 at its south-west corner, rows count north, J4 south of U1):
- FPGA TX (rows 4-7, columns A-D) on F.Cu: every pair leaves west, the deeper row the further
  north, so after the turn south the order west -> east is lane 0..3 with no crossing; capacitors
  just west of U1; then south, 45 deg south-east and into the J4 even row (Mu RX) from the north.
- FPGA RX (rows 8-11) and REFCLK leave south on In5 (RX0 around RX3's west, RX3, REFCLK) and In2
  (RX1, RX2): one layer cannot keep their order; a via row south of U1 takes them to B.Cu, down between the even
  row's ground vias to the capacitors near J4, then vias up to the J4 odd row (Mu TX) pins.
Length: 45 deg bumps on the shorter track's long vertical, away from its partner.
"""
import math

W, GAP = 0.2, 0.2                        # track, pair gap
D = (W + GAP) / 2                        # pair centre line -> track centre
CAP = 0.48                               # 0402: pad centre from the part centre
VIA = (0.45, 0.25)                       # gen_c2mu_s8.VIA
SKEW_MAX = {"REFCLK": 0.38}              # mm; data pairs 0.127 (5 mil)
HMAX, TOP, SPACE, END = 0.65, 0.15, 0.2, 0.5  # length bumps: height, top, between, kept free at segment ends
F, IN2, IN5, B = "F.Cu", "In2.Cu", "In5.Cu", "B.Cu"

# per pair: (west track's U1 ball, its J4 pin), (east track's ball, pin): the template's geometry
# decides which ball reaches which pin, gen_c2mu_s6.py wires the capacitors to match
PAIRS = {"TX0": (("D7", "40"), ("C7", "42")), "TX1": (("B6", "46"), ("A6", "48")),
         "TX2": (("D5", "52"), ("C5", "54")), "TX3": (("A4", "58"), ("B4", "60")),
         "RX0": (("C9", "37"), ("D9", "39")), "RX1": (("A10", "43"), ("B10", "45")),
         "RX2": (("C11", "49"), ("D11", "51")), "RX3": (("A8", "55"), ("B8", "57")),
         "REFCLK": (("E10", "97"), ("F10", "99"))}
LINKS = [t for pair in PAIRS.values() for t in pair]


class Track:
    """one net path ball -> capacitor -> J4 pin: runs of points on a layer, a via between two runs,
    the capacitor between the run ending on its FPGA pad and the next starting on its Mu pad"""
    def __init__(self, ball, pin, layer, *pts):
        self.ball, self.pin, self.runs, self.cap = ball, pin, [[layer, list(pts)]], None

    def to(self, *pts):
        self.runs[-1][1].extend(pts)

    def via(self, layer):
        self.runs.append([layer, [self.runs[-1][1][-1]]])

    def capacitor(self, fpga_pad, mu_pad):
        self.to(fpga_pad)
        self.cap = (len(self.runs), fpga_pad, mu_pad, "F" if self.runs[-1][0] == F else "B")
        self.runs.append([self.runs[-1][0], [mu_pad]])

    def length(self):
        return sum(math.dist(p, q) for _, pts in self.runs for p, q in zip(pts, pts[1:]))

    def segments(self):
        """(layer, p, q, past the capacitor)"""
        return [(layer, p, q, k >= self.cap[0]) for k, (layer, pts) in enumerate(self.runs)
                for p, q in zip(pts, pts[1:]) if math.dist(p, q) > 1e-6]

    def vias(self):
        """(point, past the capacitor)"""
        return [(pts[0], k >= self.cap[0]) for k, (layer, pts) in enumerate(self.runs)
                if k and layer != self.runs[k - 1][0]]


def offset(pts, d):
    """the polyline pts shifted d to the right of its direction (y down: heading west, right is north)"""
    def right(p, q):
        n = math.dist(p, q)
        return (-(q[1] - p[1]) / n, (q[0] - p[0]) / n)
    out = []
    for k, p in enumerate(pts):
        r1 = right(pts[k - 1], p) if k else right(p, pts[1])
        r2 = right(p, pts[k + 1]) if k + 1 < len(pts) else r1
        s = d / (1 + r1[0] * r2[0] + r1[1] * r2[1])
        out.append((p[0] + s * (r1[0] + r2[0]), p[1] + s * (r1[1] + r2[1])))
    return out


def pair(a, b, centre):
    """a (right of the centre line) and b continue along it"""
    a.to(*offset(centre, D))
    b.to(*offset(centre, -D))


def tune(short, long, runs):
    """45 deg bumps on short's vertical segments in runs (longest first), away from long, until
    both are equally long"""
    need = long.length() - short.length()
    if need <= 1e-6:
        return
    segs = sorted(((pts, i) for k in runs for pts in [short.runs[k][1]] for i in range(len(pts) - 1)
                   if abs(pts[i][0] - pts[i + 1][0]) < 1e-6), key=lambda s: -math.dist(s[0][s[1]], s[0][s[1] + 1]))
    per = 2 * (math.sqrt(2) - 1)                     # length per unit bump height
    fit = [max(0, int((math.dist(pts[i], pts[i + 1]) - 2 * END + SPACE) // (2 * HMAX + TOP + SPACE)))
           for pts, i in segs]
    n = math.ceil(need / (per * HMAX))
    if n > sum(fit):
        raise ValueError(f"{short.ball}: {need:.2f} mm to tune, room for {sum(fit) * per * HMAX:.2f}")
    h = need / (per * n)
    others = [pt for _, pts in long.runs for pt in pts]
    edits = []
    for (pts, i), k in zip(segs, fit):
        k = min(k, n)
        n -= k
        if k:
            edits.append((pts, i, k))
    for pts, i, k in sorted(edits, key=lambda e: -e[1]):    # later indices first: earlier ones stay valid
        p, q = pts[i], pts[i + 1]
        L = math.dist(p, q)
        u = ((q[0] - p[0]) / L, (q[1] - p[1]) / L)
        nrm = (-u[1], u[0])
        mid = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
        o = min(others, key=lambda o: math.dist(o, mid))
        if (o[0] - mid[0]) * nrm[0] + (o[1] - mid[1]) * nrm[1] > 0:
            nrm = (-nrm[0], -nrm[1])
        step = 2 * h + TOP + SPACE
        s0 = (L - k * step + SPACE) / 2
        pts[i + 1:i + 1] = [(p[0] + u[0] * s + nrm[0] * hh, p[1] + u[1] * s + nrm[1] * hh)
                            for j in range(k) for t, hh in ((0, 0), (h, h), (h + TOP, h), (2 * h + TOP, 0))
                            for s in [s0 + j * step + t]]


def plan(ball, pin):
    """ball(name) -> (x, y) of a U1 ball, pin(number) -> (x, y) of a J4 pin:
    {pair: (west track, east track)}"""
    ax, ay = ball("A1")
    row = lambda r: ay - (r - 1)                     # ball row centre
    ch = lambda r: row(r) - 0.5                      # the channel north of row r
    xe = ax - 0.5                                    # the channel west of column A
    c = lambda name, dx, dy: (ball(name)[0] + dx, ball(name)[1] + dy)
    out = {}

    # FPGA TX on F.Cu: exits west at xe (the north track first), capacitors in two columns
    xca, xcb = ax - 2.5, ax - 4.4
    exits = {"TX0": ([c("D7", .5, -.5), c("D7", .5, -1.5), (xe, ch(8))], [c("C7", -.5, -.5), (xe, ch(7))]),
             "TX1": ([c("B6", -.5, -.5), (xe, ch(6)), (xe - .2, ch(6) - .2), (xcb + CAP + .25, ch(6) - .2)],
                     [(xe, row(6)), (xe - .3, row(6) - .3), (xcb + CAP + .35, row(6) - .3)]),
             "TX2": ([c("D5", -.5, -.5), (xe, ch(5))], [c("C5", -.5, .5), (xe, ch(4))]),
             "TX3": ([(xe, row(4)), (xe - .4, row(4)), (xe - .9, ch(3))],
                     [c("B4", -.5, .5), (xe, ch(3)), (xe - 1.0, ch(3) + 1.0)])}
    caps = {"TX0": (xca, ch(8), ch(7)), "TX1": (xcb, ch(6) - .45, ch(6) + .55),
            "TX2": (xca, ch(5), ch(4)), "TX3": (xca, ch(3), ch(3) + 1.0)}
    yd = ay + 7.0                                    # the drops turn south-east here: south of the RX via row
    for k in range(4):
        name = f"TX{k}"
        (ba, pa), (bb, pb) = PAIRS[name]
        a, b = Track(ba, pa, F, ball(ba)), Track(bb, pb, F, ball(bb))
        a.to(*exits[name][0])
        b.to(*exits[name][1])
        x, ya, yb = caps[name]
        a.capacitor((x + CAP, ya), (x - CAP, ya))
        b.capacitor((x + CAP, yb), (x - CAP, yb))
        yc, xs = (ya + yb) / 2, x - CAP - ((yb - ya) / 2 - D)
        xv = ax - 10.3 + 2.0 * k                     # the drop, lane 0 westmost; 2 mm: room for bumps
        pa_xy, pb_xy = pin(pa), pin(pb)
        xj = (pa_xy[0] + pb_xy[0]) / 2
        pair(a, b, [(xs, yc), (xv + .6, yc), (xv, yc + .6), (xv, yd), (xj, yd + xj - xv), (xj, pa_xy[1] - 2.4)])
        for t, p in ((a, pa_xy), (b, pb_xy)):
            t.to((p[0], p[1] - 2.1), p)
        tune(*sorted((a, b), key=Track.length), runs=[len(a.runs) - 1])
        out[name] = (a, b)

    # FPGA RX and REFCLK: south on In5 / In2 to a via row, then B.Cu
    ye, yv = ay + 0.5, ay + 5.0
    south = {"RX0": (IN5, [c("C9", -.5, -.5), (xe - .5, ch(9))], [c("D9", -.5, .5), (xe, ch(8))]),
             "RX1": (IN2, [c("A10", -.5, .5)], [c("B10", -.5, .5)]),
             "RX2": (IN2, [c("C11", .5, .5)], [c("D11", .5, .5)]),
             "RX3": (IN5, [c("A8", .5, .5)], [c("B8", .5, .5)]),
             "REFCLK": (IN5, [c("E10", -.5, .5)], [c("F10", -.5, .5)])}
    yg = pin(PAIRS["TX0"][0][1])[1] - 0.8            # past the even row's ground vias
    for k, name in enumerate(("RX0", "RX1", "RX2", "RX3", "REFCLK")):
        layer, ea, eb = south[name]
        (ba, pa), (bb, pb) = PAIRS[name]
        a, b = Track(ba, pa, layer, ball(ba)), Track(bb, pb, layer, ball(bb))
        cv = ax - 0.6 + 1.6 * k                      # via pair centre
        for t, e, s in ((a, ea, -1), (b, eb, 1)):
            t.to(*e)
            xx, xv = e[-1][0], cv + s * .4
            t.to((xx, ye), (xx, ye + .3), (xv, ye + .3 + abs(xv - xx)), (xv, yv))
            t.via(B)
            t.to((cv + s * D, yv + .2))
        pa_xy, pb_xy = pin(pa), pin(pb)
        cj = (pa_xy[0] + pb_xy[0]) / 2
        # under the even row: between its ground vias (the TX lane centres), REFCLK east of pin 98's
        tx = PAIRS.get(f"TX{k}")
        g = cj + 1.0 if not tx else (pin(tx[0][1])[0] + pin(tx[1][1])[0]) / 2
        y0, ys = yv + .7, yg + g - cj
        pair(a, b, [(cv, yv + .2), (cv, y0), (g, y0 + g - cv), (g, yg), (cj, ys), (cj, ys + .1)])
        yc1, yc2 = pa_xy[1] - 6.7, pa_xy[1] - 4.8    # staggered capacitors, then staggered vias
        for t, s, yc, yvia in ((a, -1, yc1, pa_xy[1] - 2.6), (b, 1, yc2, pa_xy[1] - 1.9)):
            xc, px = cj + s * .35, pin(t.pin)[0]
            t.to((xc, ys + .25))
            t.capacitor((xc, yc - CAP), (xc, yc + CAP))
            t.to((xc, yvia - .3), (px, yvia - .2), (px, yvia))
            t.via(F)
            t.to(pin(t.pin))
        short, long = sorted((a, b), key=Track.length)
        tune(short, long, runs=[short.cap[0] - 1])
        out[name] = (a, b)
    return out


def report(pairs, length=Track.length):
    """lines 'pair: west, east, skew' and the pairs over their skew limit; length(track) in mm"""
    lines, bad = [], []
    for name, (a, b) in pairs.items():
        d = abs(length(a) - length(b))
        lines.append(f"  {name}: {length(a):.3f} / {length(b):.3f} mm, skew {d:.3f}")
        if d > SKEW_MAX.get(name, 0.127):
            bad.append(name)
    return lines, bad
