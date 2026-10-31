#!/usr/bin/env python3
"""Task T1 (plan/interposers.md): build hw/common/socket3_signals.csv from
sockets/kicad/pinmaps/am5x86_pga168.csv, typed from the Write-Back Enhanced
IntelDX4 datasheet (Table 8 pp.16-23, Tables 9-12 pp.24-26) and the Am5x86
(19751C). One row per pin-map row; checks pass or exit 1.
"""
import collections
import csv
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
PINMAP = ROOT / "sockets/kicad/pinmaps/am5x86_pga168.csv"
OUT = ROOT / "hw/common/socket3_signals.csv"
DX4 = "sockets/socket3/intel_dx4_write_back_enhanced.pdf"
AM5 = "sockets/socket3/amd_am5x86_19751C.pdf"
NOTES = "hw/common/socket3_notes.md"

LEVEL = "5 V TTL from the chipset (CPU: VIL 0.8 V, VIH 2.0 V, VOH 2.4 V)"
STD = "TTL"
DC = f"{DX4} Table 18 p.31; {NOTES} R1"
RAIL = {"VCC": f"3.3 V +/-0.3 V (board jumper 3.45 V), {DX4} Table 17 p.30; {AM5} p.58",
        "VSS": "0 V"}

ACTIVE_LOW = {"HITM", "IGNNE", "SMI", "CACHE", "EADS", "SMIACT", "FERR",
              "FLUSH", "BS16", "BS8", "A20M", "BOFF", "KEN", "RDY", "BRDY",
              "STPCLK", "LOCK", "PLOCK", "PCHK", "BLAST", "ADS", "UP",
              "BE0", "BE1", "BE2", "BE3"}
RENAME = {"WB_WT": "WB/WT#", "D_C": "D/C#", "M_IO": "M/IO#", "W_R": "W/R#"}

# signal -> (dir, class, source page in DX4 Table 8)
SIG = {
    "CLK": ("I", "clock", "p.16"),
    "PCHK#": ("O", "bus", "p.16"),
    "M/IO#": ("O", "bus", "p.17"), "D/C#": ("O", "bus", "p.17"),
    "W/R#": ("O", "bus", "p.17"), "LOCK#": ("O", "bus", "p.17"),
    "PLOCK#": ("O", "bus", "p.17"), "ADS#": ("O", "bus", "p.17"),
    "RDY#": ("I", "bus", "p.18"), "BRDY#": ("I", "bus", "p.18"),
    "BLAST#": ("O", "bus", "p.18"),
    "RESET": ("I", "control", "p.18"), "INTR": ("I", "control", "p.18"),
    "NMI": ("I", "control", "p.18"), "SRESET": ("I", "control", "p.19"),
    "SMI#": ("I", "control", "p.19"), "SMIACT#": ("O", "control", "p.19"),
    "STPCLK#": ("I", "control", "p.19"), "BREQ": ("O", "bus", "p.19"),
    "HOLD": ("I", "bus", "p.19"), "HLDA": ("O", "bus", "p.19"),
    "BOFF#": ("I", "bus", "p.20"), "AHOLD": ("I", "bus", "p.20"),
    "EADS#": ("I", "bus", "p.20"), "KEN#": ("I", "bus", "p.20"),
    "FLUSH#": ("I", "control", "p.20"), "PWT": ("O", "bus", "p.20"),
    "PCD": ("O", "bus", "p.20"), "BS16#": ("I", "bus", "p.21"),
    "BS8#": ("I", "bus", "p.21"), "A20M#": ("I", "control", "p.21"),
    "TCK": ("I", "debug", "p.21"), "TDI": ("I", "debug", "p.21"),
    "TDO": ("O", "debug", "p.21"), "TMS": ("I", "debug", "p.21"),
    "FERR#": ("O", "sideband", "p.22"), "IGNNE#": ("I", "sideband", "p.22"),
    "CACHE#": ("O", "bus", "p.22"), "HITM#": ("O", "bus", "p.22"),
    "INV": ("I", "bus", "p.22"),
    "WB/WT#": ("I", "strap", "p.23"), "CLKMUL": ("I", "strap", "p.23"),
    "VOLDET": ("O", "strap", f"p.23; {AM5} p.9, p.17"),
    "UP#": ("I", "strap", f"p.23 (RESERVED#); {AM5} p.17 (UP#)"),
}
# VOLDET is a passive pull-down on the interposer, not an FPGA pin [NOTES R6]
NOT_REQUIRED = {"VOLDET"}


def name_of(raw):
    if raw in RENAME:
        return RENAME[raw]
    return raw + "#" if raw in ACTIVE_LOW else raw


def typed(sig):
    num = sig[1:] if sig[0] in "AD" else ""
    if sig.startswith("DP"):
        return "IO", "bus", "p.16"
    if num.isdigit():
        if sig[0] == "D":
            return "IO", "bus", "p.16"
        return ("IO" if int(num) >= 4 else "O"), "bus", "p.16"
    if sig.startswith("BE"):
        return "O", "bus", "p.16"
    return SIG[sig]


rows = [r for r in csv.reader(PINMAP.open()) if r][1:]
out = []
for pin, raw, group in rows:
    if group == "Power":
        out.append([pin, raw, "", RAIL[raw], "power", "power", "no",
                    f"{AM5} pp.8-9 pin table; {DX4} Table 7 pp.14-15"])
    elif group == "NoConnect":
        out.append([pin, raw, "", "", "-", "nc", "no",
                    f"{AM5} pp.8-9 (internal NC; DX4: C13 NC, J1 VCC5) {NOTES} R4"])
    else:
        sig = name_of(raw)
        d, cls, page = typed(sig)
        req = "no" if sig in NOT_REQUIRED else "yes"
        out.append([pin, sig, d, LEVEL, STD, cls, req,
                    f"{DX4} Table 8 {page}; {DC}"])

with OUT.open("w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["pin", "signal", "dir", "level", "standard", "class",
                "required", "source"])
    w.writerows(out)

fails = []


def check(name, ok, detail=""):
    print("PASS" if ok else "FAIL", name, detail)
    if not ok:
        fails.append(name)


sigrows = [r for r in out if r[5] not in ("power", "nc")]
names = [r[1] for r in sigrows]
check("one row per pin-map row", len(out) == len(rows), f"{len(out)} vs {len(rows)}")
check("every non-power pin has dir and level",
      all(r[2] in ("I", "O", "IO", "OD") and r[3] for r in sigrows))
check("signal names unique", len(names) == len(set(names)))
check("A[31:2], D[31:0], BE[3:0]#, DP[3:0] complete",
      {f"A{i}" for i in range(2, 32)} | {f"D{i}" for i in range(32)}
      | {f"BE{i}#" for i in range(4)} | {f"DP{i}" for i in range(4)} <= set(names))
check("every typed non-bus signal used once", set(SIG) <= set(names),
      str(sorted(set(SIG) - set(names))))
check("signal count 114 (Am5x86 pin map)", len(sigrows) == 114,
      f"{len(sigrows)} signal rows; FPGAlist/README says 113 from 271329 "
      f"(not in the repo): the DX4 pin table differs from the Am5x86 only on "
      f"C11 (RESERVED#/UP#, a signal on both), C13 (NC on both) and J1 "
      f"(VCC5 reference / NC) [FPGAmotherboard socket3 design-decisions: "
      f"165 of 168 identical], so the DX4 also has 114; README is off by one")
print("class counts:", dict(collections.Counter(r[5] for r in out)))
print("dir counts:", dict(collections.Counter(r[2] for r in sigrows)))
print(f"wrote {OUT.relative_to(ROOT)} ({len(out)} rows)")
sys.exit(1 if fails else 0)
