#!/usr/bin/env python3
"""Check hw/common/<socket>_notes.md (plan/interposers.md task T2).

Checks: R1-R6 all answered; every [tag] citation is defined in the Sources
table and its file exists in the repo; every A..W-number pin/ball reference
appears in the Socket 3 pin map or an FPGA pin table (board jumpers and the
R1-R6 labels are excepted); R5 answers for both FPGAs with real balls; R6
covers the config-done signals; and in tables every CPU-pin reference sits on
a line naming the signal the pinmap gives that pin.
"""
import pathlib
import re
import sys

socket = sys.argv[1]
ROOT = pathlib.Path(__file__).resolve().parents[2]
md = (ROOT / "hw" / "common" / f"{socket}_notes.md").read_text()

CFG = {
    "socket3": {"pinmap": "sockets/kicad/pinmaps/am5x86_pga168.csv",
                "allowed": {f"R{r}" for r in "123456"}
                           | {"J12", "J13", "J21", "J26", "J27"}
                           | {f"T{i}" for i in range(1, 11)}
                           | {f"D{i}" for i in range(1, 8)}
                           | {f"M{i}" for i in range(1, 4)},
                "pinre": [r"\b[A-TV-W][0-9]{1,2}\b"],
                # table lines where a coordinate is not a CPU-pin reference:
                # chipset pin C10 of the UMC doc, board jumper names J15/J17
                "xskip": [r"CPURSTO documented", r"J15 INV"]},
    "socket7": {"pinmap": "sockets/kicad/pinmaps/socket7_p55c.csv",
                "allowed": {f"R{r}" for r in "123456"}
                           | {f"D{i}" for i in range(1, 8)} | {f"M{i}" for i in range(1, 4)}
                           | {f"NM{i}" for i in range(1, 9)} | {f"T{i}" for i in range(0, 11)}
                           | {"JP7", "JP8", "JP9", "JP11", "P5", "P6"}
                           | {"BF0", "BF1", "BP0", "BP1", "BP2", "BP3",
                              "PM0", "PM1"},  # pinmap signal names: [BF0], PM0/BP0 ...
                "pinre": [r"(?<![A-Z0-9])[A-Z][0-9]{1,2}(?![A-Z0-9])",
                          r"(?<![A-Z0-9])[A-Z]{2}[0-9]{1,2}(?![A-Z0-9])"]},
    "socket370": {"pinmap": "sockets/kicad/pinmaps/pga370_coppermine.csv",
                  "allowed": {f"R{r}" for r in "123456"}
                             | {f"T{i}" for i in range(1, 11)}
                             | {f"D{i}" for i in range(1, 8)}
                             | {f"M{i}" for i in range(1, 4)}
                             | {"J12", "J13", "J21", "J26", "J27"},
                  "pinre": [r"\b[A-TV-W][0-9]{1,2}\b"]},
}
cfg = CFG[socket]

fails = []
def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")
    if not ok:
        fails.append(name)

# 1. all six questions answered
for r in "123456":
    m = re.search(rf"^## R{r} -.*?(?=^## |\Z)", md, re.M | re.S)
    check(f"R{r} section", bool(m), f"{len(m.group(0).split())} words" if m else "missing")
sections = {r: re.search(rf"^## R{r} -.*?(?=^## |\Z)", md, re.M | re.S) for r in "123456"}

# 2. citations: [tag ...] -> Sources table -> file exists in repo
tags = dict(re.findall(r"^\| (\w+) \| ([^|\n]+) \|$", md, re.M))
cited = sorted(set(re.findall(r"\[([a-z][a-z0-9]*)(?: [^\]]*)?\]", md)))
for t in cited:
    ok = t in tags and (ROOT / tags[t].strip()).is_file()
    check(f"cite [{t}]", ok, tags.get(t, "not in Sources table"))

# 3. pin/ball references exist in a pin table
known = set()
for csvf in [cfg["pinmap"],
             "sockets/kicad/pinmaps/pga370_coppermine.csv",
             "FPGAlist/CycloneV_A9/pins/5ceba9_f484.csv",
             "FPGAlist/Ti180_G400/pins/ti180g400.csv"]:
    for line in (ROOT / csvf).read_text().splitlines()[1:]:
        known.add(line.split(",")[0])
# board jumper refs from the UMC trace, plan task ids, decision ids, probe
# ids: R1-R6 labels and Open-items NM tags never match the ref regex anyway
refs = set()
for rex in cfg["pinre"]:
    refs |= set(re.findall(rex, md))
unknown = sorted(refs - known - cfg["allowed"])
check("pin/ball refs in tables", not unknown, f"{len(refs)} refs, unknown: {unknown}")

# 4. R5 answers both FPGAs with real clock balls
r5 = sections["5"].group(0) if sections["5"] else ""
cv_balls = {l.split(",")[0] for l in
            (ROOT / "FPGAlist/CycloneV_A9/pins/5ceba9_f484.csv").read_text().splitlines()[1:]
            if ",CLK" in l and l.split(",")[6]}
ti_balls = {l.split(",")[0] for l in
            (ROOT / "FPGAlist/Ti180_G400/pins/ti180g400.csv").read_text().splitlines()[1:]
            if "_CLK" in l}
cv_in = sorted(b for b in cv_balls if re.search(rf"\b{b}\b", r5))
ti_in = sorted(b for b in ti_balls if re.search(rf"\b{b}\b", r5))
ok = "[Cv]" in r5 and "[Ti]" in r5 and cv_in and ti_in
check("R5 per-FPGA clock inputs", ok, f"cv balls in R5: {cv_in}, ti balls in R5: {ti_in}")

# 5. R6 covers config-done gating of both FPGAs and the unsafe-output list
r6 = sections["6"].group(0) if sections["6"] else ""
ok = all(s in r6 for s in ("CONF_DONE", "CDONE", "weak pull-up", "pull-down"))
check("R6 reset/config handling", ok)

# 6. in tables, every CPU-pin reference must sit on a line that names the
# signal the pinmap gives that pin (catches wrong-but-existing coordinates)
psig = {}
pr = (ROOT / cfg["pinmap"]).read_text().splitlines()
si = pr[0].split(",").index("signal")
for line in pr[1:]:
    p = line.split(",")
    if len(p) > si:
        psig[p[0]] = p[si]
xskip = cfg.get("xskip", [])
mism = []
for line in md.splitlines():
    if not line.startswith("|") or set(line) <= set("|-: "):
        continue
    if re.search(r"ticsv|cvcsv|\bball", line) or any(re.search(x, line) for x in xskip):
        continue
    line_n = line.replace("_", "/")
    for rex in cfg["pinre"]:
        for tk in set(re.findall(rex, line)):
            s = psig.get(tk)
            if s is None or tk in cfg["allowed"]:
                continue
            s = s.strip("[]").replace("_", "/")
            if re.search(r"VCC|VSS|GND|NC|Reserved", s, re.I):
                continue
            stems = [re.sub(r"[0-9]+$", "", x) for x in s.split("/")]
            if s in line_n or any(len(st) >= 2 and st in line_n for st in stems):
                continue
            mism.append(f"{tk}={s}")
check("table pins match pinmap signals", not mism, f"mismatched: {sorted(set(mism))[:6]}")

print("FAIL" if fails else "PASS", "-", len(fails), "failed")
sys.exit(1 if fails else 0)
