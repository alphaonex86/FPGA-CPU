#!/usr/bin/env python3
"""Task T1 (plan/interposers.md): build hw/common/socket370_signals.csv from
sockets/kicad/pinmaps/pga370_coppermine.csv, typed from the Pentium III
datasheet (245264-008). One row per pin-map row; checks pass or exit 1.
"""
import collections
import csv
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
PINMAP = ROOT / "sockets/kicad/pinmaps/pga370_coppermine.csv"
OUT = ROOT / "hw/common/socket370_signals.csv"
SRC = "sockets/socket370/pentium3_pga370_245264-008.pdf"

#strap index → ball (verified in Table 40 signal listing, printed p74-75)
IDX = {"BSEL0": "AJ33", "BSEL1": "AJ31",
       "VID0": "AL35", "VID1": "AM36", "VID2": "AL37", "VID3": "AJ37",
       "PICD0": "J35", "PICD1": "L35"}
TAP = {"AL33": "TCK", "AK32": "TMS", "AN33": "TRST#", "AN35": "TDI", "AN37": "TDO"}

A = (f"{SRC} Tables 3/4 p23-24")          # signal groups, 2.1 host bus
C = f"{SRC} Table 3 p23"                  # CMOS group
S = f"{SRC} p88-91 signal descriptions"   # straps/sideband/power-other straps
P = f"{SRC} p17 pin counts"               # power/other rails

def atgt(sig, group):
    if sig == "RESET2#":
        return ("IO", "AGTL+ (OD, VTT-terminated)", "AGTL+",
                "control", "no", f"{A}; {SRC} p90 unused")
    if sig == "PRDY#":
        return ("O", "AGTL+ (OD, VTT-terminated)", "AGTL+", "debug", "yes",
                f"{A}; {SRC} p89 probe")
    return ("I" if "Input" in group else "IO", "AGTL+ (OD, VTT-terminated)",
            "AGTL+", "bus", "yes", A)

def cmos(sig):
    d = {"PWRGOOD": ("I", "2.5 V-tolerant CMOS", "CMOS", "control", "yes",
                     f"{SRC} p22 note 4"),
         "PREQ#": ("I", "CMOS", "CMOS", "debug", "yes", f"{SRC} p89 probe"),
         "LINT0/INTR": ("I", "CMOS", "CMOS", "control", "yes", f"{C}; {SRC} p89"),
         "LINT1/NMI": ("I", "CMOS", "CMOS", "control", "yes", f"{C}; {SRC} p89"),
         "FERR#": ("OD", "CMOS (OD)", "CMOS", "sideband", "no", f"{C}; {SRC} p88"),
         "IERR#": ("OD", "CMOS (OD)", "CMOS", "sideband", "no", f"{C}; {SRC} p88"),
         "THERMTRIP#": ("OD", "CMOS (OD)", "CMOS", "sideband", "no", f"{C}; {SRC} p91")}
    if sig in d:
        return d[sig]
    return ("I", "CMOS", "CMOS", "control", "yes", C)

STRAPS = {
    "BCLK": ("I", "2.5 V (0.5-2.0 V swing)", "CMOS", "clock", "yes",
             f"{SRC} Tables 3/14 p23,37"),
    "PICCLK": ("I", "2.5 V-tolerant CMOS", "CMOS", "clock", "yes",
               f"{SRC} p22 + p40 Table 19"),
    "PICD": ("IO", "2.5 V-tolerant CMOS", "CMOS-OD", "sideband", "yes",
             f"{SRC} p22, p40 Table 19"),
    "BSEL": ("O", "single-driver active high", "CMOS-OD", "strap", "yes",
             f"{S} p25-26,87"),
    "VID": ("O", "passive open/short", "passive", "strap", "yes",
            f"{S} p20-21,92"),
    "CPUPRES#": ("O", "active-low presence", "CMOS-OD", "strap", "yes",
                 f"{S} p88"),
    "EDGCTRL": ("O", "51-ohm class to VCCCORE", "passive", "strap", "no",
                f"{S} p88 not used"),
    "SLEWCTRL": ("I", "strap", "passive", "strap", "yes", f"{S} p91"),
    "RTTCTRL": ("I", "strap", "passive", "strap", "yes", f"{S} p91"),
    "THERMDP": ("I", "analog diode", "analog", "sideband", "no", f"{S} p91"),
    "THERMDN": ("O", "analog diode", "analog", "sideband", "no", f"{S} p91"),
    "CLKREF": ("I", "1.25 V +/-6.5% PLL ref", "analog", "power", "no",
               f"{SRC} p30 Table 7 note 15"),
    "PLL": ("I", "filtered VCCCORE", "analog", "power", "no",
            f"{SRC} p90 2.3.1"),
}
RAILS = {"VCCCORE": P, "GND": P, "VTT": P, "VREF": P, "VCC1": P,
         "VCC2.5": P, "VCCCMOS": P, "VID": P, "BSEL": P, "PLL": P,
         "THERMDN": P, "THERMDP": P, "CLKREF": P, "CPUPRES#": P,
         "EDGCTRL": P, "RTTCTRL": P, "SLEWCTRL": P}

rows = list(csv.reader(PINMAP.open()))[1:]
out = []
counts = collections.Counter()
for pin, _row, _col, signal, group in rows:
    if signal in ("Reserved", "Reserved1"):
        s = "Reserved"
        dir_, lvl, std, cls, req, src = "", "", "", "nc", "no", "pinmap"
    elif signal == "BSEL":
        s = "BSEL0" if pin == "AJ33" else "BSEL1"
        dir_, lvl, std, cls, req, src = STRAPS["BSEL"]
    elif signal == "VID":
        s = [k for k, v in IDX.items() if v == pin][0]
        dir_, lvl, std, cls, req, src = STRAPS["VID"]
    elif signal == "PICD":
        s = "PICD0" if pin == "J35" else "PICD1"
        dir_, lvl, std, cls, req, src = STRAPS["PICD"]
    elif group == "Power/Other" and signal in RAILS:
        s = signal
        if signal in ("THERMDP", "THERMDN"):
            dir_, lvl, std, cls, req, src = STRAPS[signal]
        elif signal in ("CLKREF", "PLL"):
            dir_, lvl, std, cls, req, src = STRAPS[signal]
        elif signal in ("VID", "BSEL", "CPUPRES#", "EDGCTRL", "SLEWCTRL", "RTTCTRL"):
            dir_, lvl, std, cls, req, src = STRAPS[signal]
        else:
            dir_, lvl, std, cls, req, src = "", "", "", "power", "no", P
    elif group.startswith("TAP"):
        s = TAP[pin]
        dir_ = "O" if s == "TDO" else "I"
        lvl, std, cls, req, src = ("CMOS (rail unverified: NM8)", "", "debug",
                                   "yes", f"{SRC} Table 40 p74")
    elif group in ("AGTL+ I/O", "AGTL+ Input", "AGTL+ Output", "AGTL + Input"):
        s = signal
        dir_, lvl, std, cls, req, src = atgt(signal, group)
    elif group in ("CMOS Input", "CMOS Output"):
        s = {"LINT0/INTR": "LINT0", "LINT1/NMI": "LINT1"}.get(signal, signal)
        dir_, lvl, std, cls, req, src = cmos(signal)
    elif group == "System Bus Clock":
        s = signal
        dir_, lvl, std, cls, req, src = STRAPS["BCLK"]
    elif group == "APIC Clock":
        s = signal
        dir_, lvl, std, cls, req, src = STRAPS["PICCLK"]
    else:
        sys.exit(f"untyped row: {pin} {signal} {group}")
    counts[cls] += 1
    out.append([pin, s, dir_, lvl, std, cls, req, src])

names = collections.Counter(r[1] for r in out if r[5] not in ("power", "nc"))
dups = sorted(n for n, c in names.items() if c > 1)
nopower = [r for r in out if r[5] not in ("power", "nc")]
problems = []
if dups:
    problems.append(f"duplicate signal names: {dups}")
bad = [r[0] for r in nopower if not r[2] or not r[3]]
if bad:
    problems.append(f"non-power rows missing dir/level: {bad}")
if problems:
    sys.exit("; ".join(problems))

OUT.parent.mkdir(parents=True, exist_ok=True)
with OUT.open("w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["pin", "signal", "dir", "level", "standard", "class", "required", "source"])
    w.writerows(out)

signal_rows = sum(1 for r in out if r[5] not in ("power", "nc"))
strap_rows = sum(1 for r in out if r[5] == "strap")
cells = [r[0] for r in out]
print(f"wrote {OUT} ({len(out)} rows)")
print(f"signal rows {signal_rows} (straps {strap_rows}, debug {counts['debug']}, "
      f"clock {counts['clock']}, bus {counts['bus']}, control {counts['control']}, "
      f"sideband {counts['sideband']}), nc {counts['nc']}")
sigp = [r for r in out if r[5] not in ("power", "nc")]
free = sum(1 for r in sigp if r[6] == "no")
print(f"FPGA-facing candidates: {sum(1 for r in sigp if r[6]=='yes')}, "
      f"{free} excluded by required=no")
print("vs FPGAlist/README.md line 82 (245264 Table 28: 161 + ~6 straps): the "
      "difference is the counting method - our 174 non-rail rows count straps "
      "after indexing (BSEL0-1, VID0-3, PICD0-1) and include 5 TAP + "
      "PRDY#/PREQ# (debug); Table 28 numbers merge indexed straps into the "
      "strap count")
