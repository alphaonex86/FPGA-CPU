"""Shared T5 (plan/interposers.md) pin assignment for the Cyclone V F484
variants that land every socket signal on 3.3 V banks: plan-driven bank
fill, checks, pins.csv + assignment_quartus.qsf. Used by
gen_socket7_assign.py (direct landing); gen_socket3_assign.py takes
write_outputs() only.

Checks (exit 1 on failure): every ball a user I/O (VREFB pins are supply
pins [cvpcg p.19]); no ball used twice; every T1 signal with
required=yes assigned; per-bank VCCIO consistent; the clock on a
clock-capable ball; every D byte and its DP bit in one bank.
"""
import collections
import csv
import fnmatch
import math
import re
import sys

ROOT_FPGACSV = "FPGAlist/CycloneV_A9/pins/5ceba9_f484.csv"
SIZE = (22, 22)
PITCH = 1.0
CHANNELS = 8


def ball_key(b):
    m = re.match(r"^([A-Za-z]+)([0-9]+)$", b)
    return (len(m.group(1)), m.group(1), int(m.group(2)))


# AS x4 from the MT25QL01G (MSEL 10011, gen_socket3_t6.py); Quartus checks the device name only at assembly
AS_X4_QSF = ['set_global_assignment -name STRATIXV_CONFIGURATION_SCHEME "ACTIVE SERIAL X4"',
             "set_global_assignment -name USE_CONFIGURATION_DEVICE ON",
             "set_global_assignment -name STRATIXII_CONFIGURATION_DEVICE MT25QL01G"]


def write_outputs(out, rows, pullup, qsf=()):
    """pins.csv and assignment_quartus.qsf; rows: [signal, ball, bank, vccio,
    io_standard, translator, distance_mm, socket_pin, source]; pullup: signals
    given the FPGA weak pull-up; qsf: extra global .qsf lines"""
    out.mkdir(parents=True, exist_ok=True)
    with (out / "pins.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["signal", "ball", "bank", "vccio", "io_standard",
                    "translator", "distance_mm", "socket_pin", "source"])
        w.writerows(rows)
    q = ['set_global_assignment -name FAMILY "Cyclone V"', *qsf]
    for r in rows:
        q.append(f'set_location_assignment PIN_{r[1]} -to "{r[0]}"')
        q.append(f'set_instance_assignment -name IO_STANDARD "{r[4]}"'
                 f' -to "{r[0]}"')
    for name in pullup:
        if name not in {r[0] for r in rows}:
            sys.exit(f"pull-up on unassigned signal {name}")
        q.append(f'set_instance_assignment -name WEAK_PULL_UP_RESISTOR ON'
                 f' -to "{name}"')
    (out / "assignment_quartus.qsf").write_text("\n".join(q) + "\n")


def assign(root, t1_path, out, plan, vccio, clock, translated, local=(),
           pullup=(), qsf=()):
    """local: (signal, bank) board-only FPGA inputs, no socket pin or
    translator; pullup: signals given the FPGA weak pull-up in the .qsf;
    qsf: extra global .qsf lines"""
    rows = list(csv.reader(open(root / ROOT_FPGACSV)))[1:]
    ncols, nrows = SIZE
    cols = sorted({re.match(r"^([A-Za-z]+)([0-9]+)$", r[0]).group(1)
                   for r in rows}, key=lambda c: (len(c), c))
    rws = sorted({int(re.match(r"^([A-Za-z]+)([0-9]+)$", r[0]).group(2))
                  for r in rows})

    def dist(ball):
        m = re.match(r"^([A-Za-z]+)([0-9]+)$", ball)
        x, y = cols.index(m.group(1)), rws.index(int(m.group(2)))
        return math.hypot(x - (ncols - 1) / 2, y - (nrows - 1) / 2) * PITCH

    banked = collections.defaultdict(list)
    reserved = set()
    clockcap = set()
    userio = {r[0] for r in rows if r[7] == "1"}
    for ball, bank, func, conf, _vref, clk, _pair, _uio in rows:
        if clk:
            clockcap.add(ball)
        if ball in userio:
            if conf or clk or re.search(r"_CLK[0-9]|PLL", func):
                reserved.add(ball)
            else:
                banked[bank].append(ball)

    t1 = list(csv.reader(open(t1_path)))[1:]
    used = {}
    out_rows, missing = [], []
    for pin, signal, dir_, level, std, cls, req, source in t1:
        if req != "yes":
            continue
        name = signal[1:-1] if signal.startswith("[") else signal
        placed = None
        for tag, spec in plan:
            if not fnmatch.fnmatchcase(name, tag):
                continue
            bank, _, exact = spec.partition(":")
            pool = banked.get(bank, [])
            if exact:
                cand = [exact] if exact not in used else []
            else:
                cand = [b for b in sorted(pool, key=ball_key)
                        if b not in used and b not in reserved]
            if cand:
                placed = (cand[0], bank)
                break
        if not placed:
            missing.append(signal)
            continue
        ball, bank = placed
        used[ball] = name
        out_rows.append([name, ball, bank, vccio[bank], "3.3-V LVTTL",
                         "", f"{dist(ball):.1f}", pin, source])

    if missing:
        sys.exit("unassigned T1 signals: " + ", ".join(missing))
    notio = [r[:2] for r in out_rows if r[1] not in userio]
    if notio:
        sys.exit(f"signal on a non user-I/O ball: {notio}")
    dupes = [b for b, n in collections.Counter(r[1] for r in
                                               out_rows).items() if n > 1]
    if dupes:
        sys.exit(f"duplicate ball assignment: {dupes}")
    clk = next(r for r in out_rows if r[0] == clock)
    if clk[1] not in clockcap:
        sys.exit(f"{clock} ball {clk[1]} is not clock-capable")

    dmap = collections.defaultdict(set)
    for r in out_rows:
        m = re.match(r"^D([0-9]{1,2})$", r[0])
        if m:
            dmap[int(m.group(1)) // 8].add(r[2])
        m = re.match(r"^DP([0-9])$", r[0])
        if m:
            dmap[int(m.group(1))].add(r[2])
    bad = {k: v for k, v in dmap.items() if len(v) != 1}
    if bad:
        sys.exit(f"D byte / DP bit not in one bank: {bad}")
    perbank = collections.defaultdict(set)
    for r in out_rows:
        perbank[r[2]].add(r[3])
    mixed = {b: v for b, v in perbank.items() if len(v) > 1}
    if mixed:
        sys.exit(f"bank with mixed VCCIO: {mixed}")

    chips = 0
    if translated:
        # chips never straddle a bank, so a chip sits beside its bank
        for bank in vccio:
            grp = [r for r in out_rows if r[2] == bank]
            for i, r in enumerate(grp):
                r[5] = f"T{chips + i // CHANNELS + 1:02d}c{i % CHANNELS + 1}"
            chips += -(-len(grp) // CHANNELS)
    for name, bank in local:
        ball = next(b for b in sorted(banked[bank], key=ball_key)
                    if b not in used and b not in reserved)
        used[ball] = name
        out_rows.append([name, ball, bank, vccio[bank], "3.3-V LVTTL", "",
                         f"{dist(ball):.1f}", "", "board-local"])

    write_outputs(out, out_rows, pullup, qsf)

    freeio = sum(len([b for b in pool if b not in used and b not in reserved])
                 for pool in banked.values())
    print(f"{out.name}: {len(out_rows)} signals, {len(used)} balls "
          f"used, ~{freeio} I/O still free")
    for b in vccio:
        print(f"  bank {b:4} vccio {vccio[b]} balls {len(banked.get(b, [])):3}"
              f" used {sum(1 for r in out_rows if r[2] == b):3}")
    print(f"  {clock} on {clk[1]} bank {clk[2]} (clock-capable, notes R5)")
    print("  D byte -> bank:", {k: sorted(v)[0] for k, v in dmap.items()})
    return out_rows, chips
