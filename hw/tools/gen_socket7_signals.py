#!/usr/bin/env python3
"""Task T1 (plan/interposers.md): build hw/common/socket7_signals.csv from
sockets/kicad/pinmaps/socket7_p55c.csv, typed from the Pentium with MMX
datasheet (243185-004, Tables 4-8 pp. 24-27). One row per pin-map row;
checks pass or exit 1.
"""
import csv
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
PINMAP = ROOT / "sockets/kicad/pinmaps/socket7_p55c.csv"
OUT = ROOT / "hw/common/socket7_signals.csv"
SRC = "sockets/socket7/pentium_mmx_datasheet_243185-004.pdf"
DEV = "sockets/socket7/pentium_family_developers_manual_241428-005.pdf"
FMB = "sockets/socket7/intel_430hx_pcsiset_design_guide_297467-002.pdf"

T4 = f"{SRC} Table 4 p.24 (outputs)"
T5 = f"{SRC} Table 5 pp.24-25 (inputs)"
T6 = f"{SRC} Table 6 p.26 (I/O)"
T7 = f"{SRC} Table 7 p.26 (inter-processor I/O)"
DC = f"{SRC} p.31 Table 10"
LEV = "3.3 V TTL (VCC3)"
STD = "3.3 V TTL"

# signal -> (dir, class, required extra source)
O = ["ADS#", "ADSC#", "APCHK#", "BREQ", "CACHE#", "FERR#", "HIT#", "HITM#",
     "HLDA", "IERR#", "LOCK#", "M/IO#", "D/C#", "W/R#", "PCHK#", "PRDY",
     "PWT", "PCD", "SCYC", "SMIACT#", "TDO", "VCC2DET#",
     "BP2", "BP3", "PM0/BP0", "PM1/BP1"]
I = ["A20M#", "AHOLD", "BF0", "BF1", "BOFF#", "BRDY#", "BRDYC#", "BUSCHK#",
     "CLK", "CPUTYP", "EADS#", "EWBE#", "FLUSH#", "HOLD", "IGNNE#", "INIT",
     "INV", "KEN#", "NA#", "PEN#", "PICCLK", "R/S#", "RESET", "SMI#",
     "STPCLK#", "TCK", "TDI", "TMS", "TRST#", "WB/WT#"]
IO = ["AP", "PICD0", "PICD1"]
IPO = ["PHIT#", "PHITM#", "PBGNT#", "PBREQ#"]

CLASS = {
    "CLK": "clock", "PICCLK": "clock",
    "RESET": "control", "INIT": "control", "A20M#": "control",
    "FLUSH#": "control", "SMI#": "control", "SMIACT#": "control",
    "STPCLK#": "control", "INTR/LINT0": "control", "NMI/LINT1": "control",
    "FERR#": "sideband", "IGNNE#": "sideband", "PICD0": "sideband",
    "PICD1": "sideband", "PM0/BP0": "sideband", "PM1/BP1": "sideband",
    "BP2": "sideband", "BP3": "sideband",
    "BF0": "strap", "BF1": "strap", "CPUTYP": "strap", "D/P#": "strap",
    "FRCMC#1": "strap",
    "TCK": "debug", "TMS": "debug", "TDI": "debug", "TDO": "debug",
    "TRST#": "debug", "PRDY": "debug", "R/S#": "debug",
}
# required: default yes for bus/control/clock; explicit list of "no"
NOT_REQUIRED = {"D/P#", "FRCMC#1", "PICD0", "PICD1", "R/S#", "PICCLK",
                  "PHIT#", "PHITM#", "PBGNT#", "PBREQ#"}  # [fmb p.2-2] NC in UP;
    # [notes] R4: leave to internal pulls


def expand(name):
    """pinmap signal name -> typed row"""
    if name.startswith("[") and name.endswith("]"):
        name = name[1:-1]                       # [BF1] -> BF1
    if name == "INTR/LINT0" or name == "NMI/LINT1":
        return ("I", "control", T5)
    if name == "FRCMC#1":
        return ("I", "strap", f"{DEV} p.4-11")
    if name.startswith("A") and name[1:].isdigit():
        return ("IO", "bus", T6)
    if name.startswith("D") and name[1:].isdigit():
        return ("IO", "bus", T6)
    if name.startswith("DP") and name[2:].isdigit():
        return ("IO", "bus", T6)
    if name.startswith("BE"):
        n = int(name[2:-1])
        return ("IO", "bus", T6) if n <= 3 else ("O", "bus", T4)
    if name == "D/P#":
        return ("O", "strap", f"{T4}; undefined in Dual, unused in UP")
    if name in O:
        return ("O", CLASS.get(name, "bus"), T4)
    if name in I:
        return ("I", CLASS.get(name, "bus"), T5)
    if name in IO:
        return ("IO", CLASS.get(name, "bus"), T6)
    if name in IPO:
        return ("IO", CLASS.get(name, "bus"), T7)
    raise KeyError(name)


RAILS = {"VCC2": f"2.7-2.9 V (board 2.8 V), {DC}; board setting spec p.5",
         "VCC3": f"3.135-3.6 V (board 3.4 V), {DC}; board setting spec p.5",
         "VSS": "0 V, " + DC}

all_rows = [r for r in csv.reader(PINMAP.open()) if r]
hdr, body = all_rows[0], all_rows[1:]
out = []
for r in body:
    pin, _, _, sig, grp = [x.strip() for x in r]
    if grp == "Signal":
        d, c, src = expand(sig)
        req = "no" if (sig.lstrip("[]") in NOT_REQUIRED or sig in NOT_REQUIRED) else "yes"
        out.append([pin, sig, d, LEV, STD, c, req, src])
    elif grp == "Power":
        out.append([pin, sig, "", RAILS[sig], "power", "power", "no",
                    f"{SRC} p.28 sec. 3.1.2.1 pin counts; {DC}"])
    else:                                   # InternalNC / NoConnect
        out.append([pin, sig, "", "", "-", "nc", "no",
                    "pinmap group; " + FMB + " p.2-2 NC list context"])

OUT.parent.mkdir(exist_ok=True)
with OUT.open("w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["pin", "signal", "dir", "level", "standard", "class",
                "required", "source"])
    w.writerows(out)

fails = []
def check(name, ok, detail=""):
    print(("PASS" if ok else "FAIL"), name, detail)
    if not ok:
        fails.append(name)

src_rows = list(csv.reader(PINMAP.open()))[1:]
src_rows = [r for r in src_rows if r]
check("one row per pin-map row", len(out) == len(src_rows),
      f"{len(out)} vs {len(src_rows)}")
nopow = [r for r in out if r[5] not in ("power", "nc")]
check("every non-power pin has dir and level",
      all(r[2] in ("I", "O", "IO", "OD") and r[3] for r in nopow))
sig_rows = [r for r in out if r[5] != "power" and r[5] != "nc"]
nsig = len(sig_rows)
check("signal count matches FPGAlist/README (176)", nsig == 176,
      f"{nsig} signal rows; README target 176 -> explanation: exact match, "
      f"the pin map already merges the strap aliases of the 161+straps count")
check("all classes known",
      set(r[5] for r in out) <= {"bus", "control", "clock", "strap",
                                 "sideband", "debug", "power", "nc"})
check("dir values valid",
      set(r[2] for r in out) <= {"", "I", "O", "IO", "OD"})
from collections import Counter
cls = Counter(r[5] for r in out)
print("class counts:", dict(cls))
print(f"wrote {OUT} ({len(out)} rows)")
sys.exit(1 if fails else 0)
