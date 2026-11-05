#!/usr/bin/env python3
"""Task T5 (plan/interposers.md): assign socket 7 signals to Cyclone V
balls -> hw/socket7-cyclonev/pins.csv, layout.csv + assignment_quartus.qsf.

Socket 7 needs no translators (hw/common/socket7_notes.md R1: the 430TX
drives 3.3 V TTL), so every bank runs VCCIO 3.3 V, any user I/O ball serves
any signal and each signal is one net, socket pin -> ball. As on socket 3
(gen_socket3_assign.py, operator 2026-11-05: pins in a crossing-free order
before routing), the map is a least total length matching on the T7 layout
(gen_socket7_t7.py: U1 in the centre of the pin ring), plus DEPTH_MM per
ring in from the BGA edge, over the user I/O balls without a configuration
or clock function; a least length matching has no two crossing lines. CLK
goes first to the clock input (CLKnp) with the fewest crossings, then the
least length; U1 takes the rotation of the fewest CLK crossings, then the
least total length.
Checks (exit 1): every required T1 signal assigned, no ball used twice,
CLK clock-capable.
"""
import csv
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import gen_socket7_t7 as t7
import placer
from assign_common import AS_X4_QSF, write_outputs
from gen_socket3_assign import DEPTH_MM, crossing, least_length

ROOT = pathlib.Path(__file__).resolve().parents[2]
T1 = ROOT / "hw/common/socket7_signals.csv"
FCSV = ROOT / "FPGAlist/CycloneV_A9/pins/5ceba9_f484.csv"
OUT = ROOT / "hw/socket7-cyclonev"


def assign(u1_rot, signals, balls, clocks):
    """signals [(name, socket pin)] -> ({name: ball}, cost, CLK crossings)"""
    _, xy = t7.layout(u1_rot)
    socket, u1 = xy["U2"], xy["U1"]
    depth = lambda b: DEPTH_MM * placer.ring_depth(u1[b], t7.U1_AT)
    pin = dict(signals)
    others = [(n, socket[p]) for n, p in signals if n != "CLK"]
    best = None
    for c in clocks:
        ball, cost = least_length(others, [(b, u1[b]) for b in balls if b != c], depth)
        leg = (socket[pin["CLK"]], u1[c])
        n_cross = sum(crossing(leg, (socket[pin[n]], u1[b])) for n, b in ball.items())
        cost += math.dist(*leg) + depth(c)
        if best is None or (n_cross, cost) < best[0]:
            best = ((n_cross, cost), dict(ball, CLK=c))
    (n_cross, cost), ball = best
    return ball, cost, n_cross


def main():
    t1 = [r for r in csv.DictReader(open(T1)) if r["required"] == "yes"]
    signals = [(r["signal"], r["pin"]) for r in t1]
    fpga = list(csv.DictReader(open(FCSV)))
    bank = {r["ball"]: r["bank"] for r in fpga}
    user = [r for r in fpga if r["user_io"] == "1"]
    clocks = [r["ball"] for r in user if r["clock"].startswith("CLK") and r["clock"].endswith("p")]
    balls = [r["ball"] for r in user if not r["config"] and not r["clock"] and "PLL" not in r["function"]]

    tries = [assign(rot, signals, balls, clocks) + (rot,) for rot in (0.0, 90.0, 180.0, 270.0)]
    for _, cost, n_cross, rot in tries:
        print(f"  U1 rotation {rot:3.0f}: length + depth {cost:.0f} mm, CLK crossings {n_cross}")
    ball, cost, n_cross, rot = min(tries, key=lambda a: (a[2], a[1]))

    fails = []
    if len(set(ball.values())) != len(ball):
        fails.append("a ball used twice")
    if ball["CLK"] not in clocks:
        fails.append(f"CLK on {ball['CLK']}, not a clock input")
    missing = [n for n, _ in signals if n not in ball]
    if missing:
        fails.append(f"unassigned: {missing}")
    if fails:
        print("FAIL", *fails, sep="\n  ")
        sys.exit(1)

    at, xy = t7.layout(rot)
    src = {r["signal"]: r["source"] for r in t1}
    rows = [[n, ball[n], bank[ball[n]], "3.3 V", "3.3-V LVTTL", "",
             f"{math.dist(xy['U1'][ball[n]], xy['U2'][pin]):.1f}", pin, src[n]] for n, pin in signals]
    write_outputs(OUT, rows, [], AS_X4_QSF)
    with open(OUT / "layout.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ref", "x", "y", "rot", "side"])
        w.writerow(["U1", *at["U1"]])
    per_bank = {}
    for r in rows:
        per_bank[r[2]] = per_bank.get(r[2], 0) + 1
    print(f"socket7-cyclonev: {len(rows)} signals direct, U1 at {rot:.0f} deg, {cost:.0f} mm; "
          f"per bank {sorted(per_bank.items())}; CLK on {ball['CLK']}")
    print(f"  wrote {OUT.relative_to(ROOT)}/pins.csv, layout.csv, assignment_quartus.qsf")


if __name__ == "__main__":
    main()
