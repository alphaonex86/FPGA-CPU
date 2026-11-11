#!/usr/bin/env python3
"""Task T5 (plan/interposers.md): assign socket 3 signals to translator
channels and Cyclone V balls -> hw/socket3-cyclonev/pins.csv +
assignment_quartus.qsf.

Every CPU net crosses an 8-channel CB3T3245 (D2: the UMC chipset drives
5 V TTL, hw/common/socket3_notes.md R1), so every bank runs VCCIO 3.3 V and
any user I/O ball serves any signal. Both matchings are of least total
length on the T7 layout (gen_socket3_t7.py: U1 north of the pin ring, the
translators in columns beside it), and a least length matching has no two
crossing lines (swap argument; a per spot term survives it):
1. socket pin -> translator channel (its B pin), all 16 chips together;
2. A pin -> ball, plus DEPTH_MM per ring in from the BGA edge (no ball deeper
   than F.Cu / B.Cu escape needs), over the user I/O balls that carry no
   configuration or clock function; CLK first, on the clock input (CLKnp)
   (notes R5) with the fewest crossings, then the least length. U1 takes the
   rotation of the fewest CLK crossings, then the least total length.
FAST (2026-11-11): RDY# / BRDY# and the outputs that answer them within the clock (BLAST#, the
burst's A3-A2: rtl/s3/s3_bus.sv) take balls FAST_RADIUS around one ball, the ball of the least
total length (their legs cross others: the price): the Quartus build of the first map
(RDY# / BRDY# on U1's east edge, BLAST# / A2 / A3 on its south edge) missed the 486's 14 ns by 3 to
11 ns on these pin -> logic -> pin paths across the die.
VCORE_OK (board-local, the VCORE-present detector output) takes the free ball
nearest the U1 edge middle facing the ring; CLKMUL has only the FPGA weak
pull-up (the FPGAmotherboard ties R17 to GND).
A chip left without a channel is dropped and the others renumbered (T01..),
in slot order; layout.csv keeps U1 and each chip at its T7 spot.
Checks (exit 1): every required T1 signal assigned, no ball or channel
used twice, CLK clock-capable.
"""
import csv
import math
import pathlib
import sys

import numpy as np
from scipy.optimize import linear_sum_assignment

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import gen_socket3_t7 as t7
import placer
from assign_common import AS_X4_QSF, write_outputs

ROOT = pathlib.Path(__file__).resolve().parents[2]
T1 = ROOT / "hw/common/socket3_signals.csv"
FCSV = ROOT / "FPGAlist/CycloneV_A9/pins/5ceba9_f484.csv"
OUT = ROOT / "hw/socket3-cyclonev"
DEPTH_MM = 6.0                           # a ring deeper costs as much as 6 mm of trace
CHANNELS = 8
FAST = ("RDY#", "BRDY#", "BLAST#", "A2", "A3")
FAST_RADIUS = 2.3                        # mm between ball centres (1.0 mm pitch: two balls away)
BARRED = 1e6


def least_length(targets, spots, extra=lambda spot: 0.0, fast=lambda spot: True):
    """[(key, xy)], [(spot, xy)] -> ({key: spot}, total cost); the FAST keys only on fast(spot) spots"""
    cost = np.array([[math.dist(t, xy) + extra(sp) + (BARRED if key in FAST and not fast(sp) else 0.0)
                      for sp, xy in spots] for key, t in targets])
    rows, cols = linear_sum_assignment(cost)
    return {targets[r][0]: spots[c][0] for r, c in zip(rows, cols)}, cost[rows, cols].sum()


def assign(u1_rot, signals, balls, clocks):
    """signals [(name, socket pin)] -> ({name: (slot, channel)}, {name: ball}, cost, CLK crossings)"""
    at, xy = t7.layout(u1_rot)
    slots = [k for k in at if isinstance(k, int)]
    socket = xy["U2"]
    b_pins = [((k, ch), xy[k][str(19 - ch)]) for k in slots for ch in range(1, CHANNELS + 1)]
    u1, centre = xy["U1"], t7.U1_AT
    chan, c1 = least_length([(n, socket[pin]) for n, pin in signals], b_pins)
    a_pin = {n: xy[k][str(1 + ch)] for n, (k, ch) in chan.items()}
    depth = lambda b: DEPTH_MM * placer.ring_depth(u1[b], centre)
    # CLK is held to the clock inputs, outside the swap argument: each one tried, the fewest crossings
    # of its A leg with the others of its side first, then the least length
    others = [(n, a_pin[n]) for n in a_pin if n != "CLK"]
    best = None
    for c in clocks:
        spots = [(b, u1[b]) for b in balls if b != c]
        near = {b: {q for q, at_q in spots if math.dist(at_b, at_q) <= FAST_RADIUS} for b, at_b in spots}
        ball, c2 = min((least_length(others, spots, depth, fast=near[b].__contains__)
                        for b in near if len(near[b]) >= len(FAST)), key=lambda m: m[1])
        leg = (a_pin["CLK"], u1[c])
        face = lambda n: at[chan[n][0]][3]             # B.Cu chips reach their balls on B.Cu, through the via in pad
        n_cross = sum(crossing(leg, (a_pin[n], u1[b])) for n, b in ball.items() if face(n) == face("CLK"))
        cost = c1 + c2 + math.dist(*leg) + depth(c)
        if best is None or (n_cross, cost) < best[0]:
            best = ((n_cross, cost), dict(ball, CLK=c))
    (n_cross, cost), ball = best
    return chan, ball, cost, n_cross


def crossing(p, q):
    """segments p, q cross (not at an end)"""
    side = lambda a, b, c: (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    return side(*p, q[0]) * side(*p, q[1]) < 0 and side(*q, p[0]) * side(*q, p[1]) < 0


def main():
    t1 = [r for r in csv.DictReader(open(T1)) if r["required"] == "yes"]
    signals = [(r["signal"].strip("[]"), r["pin"]) for r in t1]
    fpga = list(csv.DictReader(open(FCSV)))
    bank = {r["ball"]: r["bank"] for r in fpga}
    user = [r for r in fpga if r["user_io"] == "1"]
    clocks = [r["ball"] for r in user if r["clock"].startswith("CLK") and r["clock"].endswith("p")]
    balls = [r["ball"] for r in user if not r["config"] and not r["clock"] and "PLL" not in r["function"]]

    tries = [assign(rot, signals, balls, clocks) + (rot,) for rot in (0.0, 90.0, 180.0, 270.0)]
    for _, _, cost, n_cross, rot in tries:
        print(f"  U1 rotation {rot:3.0f}: length + depth {cost:.0f} mm, CLK crossings {n_cross}")
    chan, ball, cost, n_cross, rot = min(tries, key=lambda a: (a[3], a[2]))

    used_slots = sorted({k for k, _ in chan.values()})
    tid = {k: i + 1 for i, k in enumerate(used_slots)}
    _, xy = t7.layout(rot)
    u1 = xy["U1"]
    # VCORE_OK: the free ball nearest the middle of U1's south edge (the detector sits by the ring)
    taken = set(ball.values())
    south = (t7.U1_AT[0], t7.U1_AT[1] + 11.0)
    ball["VCORE_OK"] = min((b for b in balls if b not in taken), key=lambda b: math.dist(u1[b], south))

    fails = []
    if len(set(ball.values())) != len(ball):
        fails.append("a ball used twice")
    if len(set(chan.values())) != len(chan):
        fails.append("a channel used twice")
    if ball["CLK"] not in clocks:
        fails.append(f"CLK on {ball['CLK']}, not a clock input")
    missing = [n for n, _ in signals if n not in ball]
    if missing:
        fails.append(f"unassigned: {missing}")
    spread = max(math.dist(u1[ball[a]], u1[ball[b]]) for a in FAST for b in FAST)
    if spread > 2 * FAST_RADIUS:
        fails.append(f"FAST group: balls {spread:.1f} mm apart")
    if fails:
        print("FAIL", *fails, sep="\n  ")
        sys.exit(1)

    src = {r["signal"].strip("[]"): r["source"] for r in t1}
    rows = []
    for n, pin in signals:
        k, ch = chan[n]
        b = ball[n]
        rows.append([n, b, bank[b], "3.3 V", "3.3-V LVTTL", f"T{tid[k]:02d}c{ch}",
                     f"{math.dist(u1[b], xy[k][str(1 + ch)]):.1f}", pin, src[n]])
    b = ball["VCORE_OK"]
    rows.append(["VCORE_OK", b, bank[b], "3.3 V", "3.3-V LVTTL", "", "", "", "board-local"])
    write_outputs(OUT, rows, ["CLKMUL"], AS_X4_QSF)
    with open(OUT / "layout.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ref", "x", "y", "rot", "side"])
        at, _ = t7.layout(rot)
        w.writerow(["U1", *at["U1"]])
        for k in used_slots:
            w.writerow([f"TR{tid[k]:02d}", *at[k]])
    per_bank = {}
    for r in rows:
        per_bank[r[2]] = per_bank.get(r[2], 0) + 1
    print(f"socket3-cyclonev: {len(rows)} signals via {len(used_slots)} CB3T3245; per bank {sorted(per_bank.items())}; "
          f"CLK on {ball['CLK']}")
    print(f"  wrote {OUT.relative_to(ROOT)}/pins.csv, layout.csv, assignment_quartus.qsf")


if __name__ == "__main__":
    main()
