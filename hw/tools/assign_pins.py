#!/usr/bin/env python3
"""Task T5 (plan/interposers.md): assign socket 370 signals to FPGA balls.

Usage: python3 hw/tools/assign_pins.py <variant>
Outputs:
  hw/<variant>/pins.csv
  hw/socket370-cyclonev/assignment_quartus.qsf / assignment_efinity.csv

Bank plans: every bus signal lands on the FPGA side of a level translator
(D3), so those banks run 3.3 V; BCLK and PICCLK are direct receivers whose
socket levels are 2.5 V (hw/common/socket370_notes.md R5; 245264-008
Tables 12/14; ics94241 pp.4-11), so they share the one 2.5 V bank. On the
Cyclone V that bank is 5B (own VCCPD5B ball, BCLK on N16 = CLK6p): 3B
shares VCCPD3B4A with 4A and so runs 3.3 V like 4A (cvds p.8 Table 4
note 4; operator 2026-10-31). Ti180 HSIO banks (BANK2A-4C) stop at 1.8 V
(hw/socket370-ti180/power.md, tids p.84 Table 62): their translators run
a 1.8 V A side; only the HVIO banks TL/TR/BL/BR take 2.5/3.3 V.

Checks (exit 1 on failure): every ball a user I/O; no ball used twice; every T1 signal marked
required=yes assigned; per-bank VCCIO consistent; BCLK on a clock-capable
ball; every D byte fully inside one bank; used/free I/O report.
"""
import collections
import csv
import fnmatch
import math
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
T1 = ROOT / "hw/common/socket370_signals.csv"
OUTDIR = {"socket370-cyclonev": ROOT / "hw/socket370-cyclonev",
          "socket370-ti180": ROOT / "hw/socket370-ti180"}
FPGACSV = {
    "socket370-cyclonev":
        ROOT / "FPGAlist/CycloneV_A9/pins/5ceba9_f484.csv",
    "socket370-ti180": ROOT / "FPGAlist/Ti180_G400/pins/ti180g400.csv",
}
SIZE = {"socket370-cyclonev": (22, 22), "socket370-ti180": (20, 20)}
PITCH = {"socket370-cyclonev": 1.0, "socket370-ti180": 0.8}
DIRECT = ("BCLK", "PICCLK")          # socket nets that skip translators

CV_PLAN = [
    ("BCLK", "5B:N16"), ("PICCLK", "5B"),
    ("D[0-9]#", "4A"), ("D1[0-5]#", "4A"),
    ("D1[6-9]#", "7A"), ("D[2-6][0-9]#", "7A"),
    ("A[3-9]#", "7A"), ("A1[0-4]#", "7A"), ("A1[56]#", "3B"),
    ("DEP[0-7]#", "4A"), ("PICD[01]", "4A"),
    ("REQ[0-4]#", "4A"), ("RP#", "4A"), ("SLP#", "4A"),
    ("BPM[0-1]#", "4A"), ("AP[0-1]#", "4A"), ("BP[2-3]#", "4A"),
    ("A2[0-4]#", "8A"), ("A1[7-9]#", "8A"),
    ("RS[0-2]#", "8A"), ("RSP#", "8A"), ("DBSY#", "8A"),
    ("DRDY#", "8A"), ("TRDY#", "8A"), ("DEFER#", "8A"),
    ("BPRI#", "8A"), ("BR[0-1]#", "8A"), ("BINIT#", "8A"),
    ("AERR#", "8A"), ("BERR#", "8A"), ("RESET#", "8A"),
    ("ADS#", "8A"), ("BNR#", "8A"), ("LOCK#", "8A"),
    ("HIT#", "8A"), ("HITM#", "8A"),
    ("A2[5-9]#", "4A"),
    ("A3[0-5]#", "3B"), ("BSEL[01]", "3B"), ("VID[0-3]", "3B"),
    ("SLEWCTRL", "3B"), ("RTTCTRL", "3B"), ("CPUPRES#", "3B"),
    ("LINT[01]", "5A"), ("PWRGOOD", "5A"), ("A20M#", "5A"),
    ("FLUSH#", "5A"), ("IGNNE#", "5A"), ("INIT#", "5A"),
    ("STPCLK#", "5A"), ("SMI#", "5A"),
    ("FERR#", "3B"), ("IERR#", "3B"), ("THERMTRIP#", "3B"),
    ("TCK", "5B"), ("TMS", "5B"), ("TDI", "5B"), ("TDO", "5B"),
    ("TRST#", "5B"), ("PREQ#", "5B"), ("PRDY#", "5B"),
]

TI_PLAN = [
    ("BCLK", "TL:P11"), ("PICCLK", "TL"),
    ("D[0-9]#", "BANK2C"), ("D1[0-5]#", "BANK2C"),
    ("D1[6-9]#", "BANK2A"), ("D2[0-9]#", "BANK2A"), ("D3[0-1]#", "BANK2A"),
    ("D3[2-9]#", "BANK3A"), ("D4[0-7]#", "BANK3A"),
    ("D4[8-9]#", "BANK3C"), ("D5[0-9]#", "BANK3C"), ("D6[0-9]#", "BANK3C"),
    ("A[3-9]#", "BANK3B"), ("A1[0-5]#", "BANK3B"),
    ("A1[6-9]#", "BL"), ("A2[0-9]#", "BL"), ("A3[0-4]#", "BL"),
    ("AP[0-1]#", "TR"), ("BP[2-3]#", "TR"),
    ("BPM[0-1]#", "TR"), ("SLP#", "TR"), ("RP#", "TR"),
    ("DEP[0-7]#", "BANK2B"),
    ("REQ[0-4]#", "TL"), ("A35#", "TL"), ("LOCK#", "TL"), ("HIT#", "TL"),
    ("HITM#", "TL"), ("PICD[01]", "TL"),
    ("RS[0-2]#", "BANK4C"), ("RSP#", "BANK4C"), ("DBSY#", "BANK4C"),
    ("DRDY#", "BANK4C"), ("TRDY#", "BANK4C"), ("DEFER#", "BANK4C"),
    ("BPRI#", "BANK4C"), ("BR0#", "BANK4C"),
    ("BR1#", "BANK4B"), ("BINIT#", "BANK4B"), ("AERR#", "BANK4B"),
    ("BERR#", "BANK4A"), ("RESET#", "BANK4A"), ("ADS#", "BANK4A"),
    ("BNR#", "BANK4A"),
    ("LINT[01]", "BANK2C"), ("PWRGOOD", "BANK2C"), ("A20M#", "BANK2C"),
    ("FLUSH#", "BANK2A"), ("IGNNE#", "BANK2A"), ("INIT#", "BANK2A"),
    ("STPCLK#", "BANK2A"),
    ("SMI#", "BANK3A"), ("FERR#", "BANK3A"), ("IERR#", "BANK3A"),
    ("THERMTRIP#", "BANK3A"),
    ("BSEL[01]", "TL"), ("VID[0-3]", "TL"), ("SLEWCTRL", "TL"),
    ("RTTCTRL", "TL"), ("CPUPRES#", "TL"),
    ("TCK", "BR"), ("TMS", "BR"), ("TDI", "BR"), ("TDO", "BR"),
    ("TRST#", "BR"), ("PREQ#", "BR"), ("PRDY#", "BR"),
    # overflow: the REF_RES_* balls are not GPIO
    ("IGNNE#", "BANK3A"), ("PWRGOOD", "BANK3A"), ("DEP[0-7]#", "BANK3C"),
    ("A[3-9]#", "BANK3C"), ("ADS#", "BANK3C"), ("AERR#", "BR"),
    ("BR0#", "BR"),
]

VCCIO = {
    "socket370-cyclonev": {"3A": "3.3 V", "3B": "3.3 V", "4A": "3.3 V",
                           "5A": "3.3 V", "5B": "2.5 V", "7A": "3.3 V",
                           "8A": "3.3 V", "9A": "3.3 V"},
    "socket370-ti180": {"TL": "2.5 V", "BANK2A": "1.8 V", "BANK2B": "1.8 V",
                        "BANK2C": "1.8 V", "BANK3A": "1.8 V",
                        "BANK3B": "1.8 V", "BANK3C": "1.8 V",
                        "BANK4A": "1.8 V", "BANK4B": "1.8 V",
                        "BANK4C": "1.8 V",
                        "BL": "3.3 V", "BR": "3.3 V", "TR": "3.3 V"},
}


def ball_key(b):
    m = re.match(r"^([A-Za-z]+)([0-9]+)$", b)
    return (len(m.group(1)), m.group(1), int(m.group(2)))


def main():
    variant = sys.argv[1] if len(sys.argv) > 1 else ""
    if variant not in OUTDIR:
        sys.exit("usage: assign_pins.py socket370-cyclonev|socket370-ti180")
    plan = CV_PLAN if variant == "socket370-cyclonev" else TI_PLAN
    rows = list(csv.reader(open(FPGACSV[variant])))[1:]
    (ncols, nrows) = SIZE[variant]
    pitch = PITCH[variant]

    def dist(ball):
        m = re.match(r"^([A-Za-z]+)([0-9]+)$", ball)
        cols = sorted({re.match(r"^([A-Za-z]+)([0-9]+)$", r[0]).group(1)
                       for r in rows}, key=lambda c: (len(c), c))
        rws = sorted({int(re.match(r"^([A-Za-z]+)([0-9]+)$", r[0]).group(2))
                      for r in rows})
        x, y = cols.index(m.group(1)), rws.index(int(m.group(2)))
        return math.hypot(x - (ncols - 1) / 2,
                          y - (nrows - 1) / 2) * pitch

    banked = collections.defaultdict(list)
    reserved = set()
    func_of = {}
    userio = {r[0] for r in rows if r[7] == "1"}
    for ball, bank, func, conf, _vref, clock, _pair, _uio in rows:
        func_of[ball] = func
        if ball in userio:
            # dedicated config balls and clock-capable network pins (Ti
            # *_CLK* P/N pairs, CV explicit clock column) stay out of the
            # user-I/O pools; exact plan specs bypass this on purpose
            if conf or clock or re.search(r"_CLK[0-9]|PLL", func):
                reserved.add(ball)
            else:
                banked[bank].append(ball)

    t1 = list(csv.reader(open(T1)))[1:]
    used = {}
    out_rows, missing = [], []
    clk_report = []
    for pin, signal, dir_, level, std, cls, req, source in t1:
        if req != "yes":
            continue
        placed = None
        for tag, spec in plan:
            if not fnmatch.fnmatchcase(signal, tag):
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
        used[ball] = signal
        vccio = VCCIO[variant][bank]
        direct = signal in DIRECT
        # Quartus names [cvhb p.5-7 Table 5-7]; Efinity: "<V> LVCMOS"
        if variant == "socket370-cyclonev":
            iostd = "2.5 V" if direct else "3.3-V LVTTL"
        else:
            iostd = vccio + " LVCMOS"
        n = len(out_rows) - sum(1 for r in out_rows if not r[5])
        tnum = "" if direct else f"T{n // 8 + 1:02d}c{n % 8 + 1}"
        out_rows.append([signal, ball, bank, vccio, iostd, tnum,
                         f"{dist(ball):.1f}", pin, source])
        if signal == "BCLK":
            ok = (bool(re.search(r"_CLK[0-9]", func_of.get(ball, "")))
                  or bool(next((r for r in rows
                                if r[0] == ball and r[5]), "")))
            if not ok:
                sys.exit(f"BCLK ball {ball} is not clock-capable")
            clk_report.append(f"BCLK on {ball} bank {bank}: clock-capable "
                              f"({func_of.get(ball, '')})")

    if missing:
        sys.exit("unassigned T1 signals: " + ", ".join(missing))
    notio = [r[:2] for r in out_rows if r[1] not in userio]
    if notio:
        sys.exit(f"signal on a non user-I/O ball: {notio}")
    dupes = [b for b, n in collections.Counter(r[1] for r in
                                               out_rows).items() if n > 1]
    if dupes:
        sys.exit(f"duplicate ball assignment: {dupes}")

    OUTDIR[variant].mkdir(parents=True, exist_ok=True)
    with (OUTDIR[variant] / "pins.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["signal", "ball", "bank", "vccio", "io_standard",
                    "translator", "distance_mm", "socket_pin", "source"])
        w.writerows(out_rows)

    # vendor constraint files
    dir_of = {row[1]: row[2] for row in list(csv.reader(open(T1)))[1:]}
    if variant == "socket370-cyclonev":
        q = ['set_global_assignment -name FAMILY "Cyclone V"']
        for r in out_rows:
            q.append(f'set_location_assignment PIN_{r[1]} -to "{r[0]}"')
            q.append(f'set_instance_assignment -name IO_STANDARD '
                     f'"{r[4]}" -to "{r[0]}"')
        v = OUTDIR[variant] / "assignment_quartus.qsf"
    else:
        q = ["io_name,pin,mode,io_standard"]
        for r in out_rows:
            mode = {"I": "input", "O": "output"}.get(dir_of.get(r[0], ""),
                                                     "bidir")
            q.append(f"{r[0]},{r[1]},{mode},{r[4]}")
        v = OUTDIR[variant] / "assignment_efinity.csv"
    v.write_text("\n".join(q) + "\n")

    usedn = len(used)
    freeio = sum(len([b for b in pool if b not in used and b not in reserved])
                 for pool in banked.values())
    print(f"{variant}: {len(out_rows)} signals, {usedn} balls used, "
          f"~{freeio} I/O still free")
    for b in VCCIO[variant]:
        n = len(banked.get(b, []))
        k = sum(1 for r in out_rows if r[2] == b)
        print(f"  bank {b:8} vccio {VCCIO[variant][b]:6} balls {n:3} used {k:3}")
    for line in clk_report:
        print("  " + line)
    dmap = collections.defaultdict(set)
    for r in out_rows:
        m = re.match(r"^D([0-9]{1,2})#$", r[0])
        if m:
            dmap[int(m.group(1)) // 8].add(r[2])
    bad = {k: v for k, v in dmap.items() if len(v) != 1}
    if bad:
        sys.exit(f"D byte not in one bank: {bad}")
    perbank = collections.defaultdict(set)
    for r in out_rows:
        perbank[r[2]].add(r[3])
    mixed = {b: v for b, v in perbank.items() if len(v) > 1}
    if mixed:
        sys.exit(f"bank with mixed VCCIO: {mixed}")
    print("  D byte -> bank:",
          {k: sorted(v)[0] for k, v in dmap.items()})
    ntr = sum(1 for r in out_rows if r[5])
    print(f"  translators: {ntr} channels -> {math.ceil(ntr / 8)} x 8-ch "
          f"pass-gate translator chips (NMBOM part TBD in T9)")
    print(f"  wrote {OUTDIR[variant].relative_to(ROOT)}")


if __name__ == "__main__":
    main()
