#!/usr/bin/env python3
"""Task S5 (plan/slot1.md): assign slot 1 signals and the DDR3L bus to FPGA balls.

Usage: python3 hw/tools/gen_slot1_assign.py

Outputs (hw/slot1-cyclonev/):
  pins.csv          slot 1 contact -> FPGA ball map (translator channel per signal)
  ddr3.csv          DDR3L x32 ball map (per-designator capability table 5cefa9[.txt])
  parked.csv        contacts left unconnected / tied on the cartridge (no FPGA pin)
  assignment_quartus.qsf

Source of truth for the FPGA pins is the official pin table
(FPGAlist/CycloneV_A9/pins/5cefa9.txt, F484 block = lines 497..990): the
converted 5cefa9_f484.csv drops the DQS-for-X8/X16 and HMC DDR3 columns that
the DDR3 reservation needs.

Bank plan (D18/D19/D20 in plan/slot1.md):
  7A + 8A = 1.35 V (DDR3L data, DQS, control, address/command) plus AGTL+
  overflow channels; 3A/3B/4A/5A/5B = 3.3 V (translator periphery banks).
  BCLK (A75) is the only direct receiver and lands on the CLK0 pair M9/M8,
  bank 3B; M8 (CLK0n) is held unused for the pair.

Parked contacts (no FPGA pin, component ties on the cartridge):
  CPU test port TCK/TMS/TDI/TDO/TRST# + PREQ#/PRDY# (debug, tie per
  24365703 Table 35 / CPU test port notes), VID[4:0] divider (2.00 V,
  hw/slot1-cyclonev/power.md), 100/66# left floating (slot1_notes "80"),
  TESTHI, BP[3:2]#/BPM[1:0]# inactive ties, IERR#/FERR# undriven high
  (AGTL+ idle = high via the board terminators), PICCLK (APIC timer clocked
  internally; NM21). DDR3 has no socket contact: its rank controls are FPGA
  balls (ddr3.csv).

Checks (exit 1 on failure): pin-table parse completeness; every non-parked
required contact assigned; no FPGA ball used twice; all 32 DDR3 DQ + 4 DM in
their DQS-for-X8 group with the group's DQS pair; DDR3 control/designator
balls match the F484 HMC DDR3 capability column; BCLK on a clock-capable ball
in a 3.3 V bank; CMOS nets never on a 1.35 V bank; per-bank VCCIO consistent;
used/free report.
"""
import collections
import csv
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
SLOT1CSV = ROOT / "hw/common/slot1_signals.csv"
PINSRC = ROOT / "FPGAlist/CycloneV_A9/pins/5cefa9.txt"
OUT = ROOT / "hw/slot1-cyclonev"

# ---------------------------------------------------------------- FPGA table
# F484 block: the .txt has one block per package (U484, F484, F672, F896).
def parse_f484():
    lines = PINSRC.read_text(encoding="latin-1").replace("\r\n", "\n").split("\n")
    start = end = None
    for i, l in enumerate(lines):
        if "\tF484\t" in l and "Pin Name/Function" in l:
            start = i + 1
        elif start and ("\tF672\t" in l and "Pin Name/Function" in l):
            end = i
            break
    if not start or not end:
        sys.exit("F484 block not found in " + str(PINSRC))
    balls = {}
    for l in lines[start:end]:
        f = l.split("\t")
        if len(f) < 12:
            continue
        ball = f[7].strip()
        if not re.match(r"^[A-Z]+\d+$", ball):
            continue
        if ball in balls:
            continue  # one row per ball is enough (bank/func repeat)
        balls[ball] = {
            "ball": ball,
            "bank": f[0].strip(),
            "func": f[2].strip(),
            "opt": f[3].strip(),
            "conf": f[4].strip(),
            "tx": f[5].strip(),
            "hmc": f[10].strip(),
            "dqs_x8": f[8].strip(),
            "dqs_x16": f[9].strip(),
        }
    io = [b for b in balls.values() if b["func"] == "IO"]
    if len(io) != 224:
        sys.exit(f"expected 224 IO balls in F484 block, got {len(io)}")
    return balls, io

BALLS, IO = parse_f484()
BY_HMC = collections.defaultdict(list)
for b in IO:
    if re.match(r"^(T|B)_[A-Z#0-9_]+$", b["hmc"]):
        BY_HMC[b["hmc"]].append(b["ball"])

# ---------------------------------------------------------------- bank plan
bank_vccio = {"7A": "1.35 V", "8A": "1.35 V",
              "3A": "3.3 V", "3B": "3.3 V", "4A": "3.3 V",
              "5A": "3.3 V", "5B": "3.3 V"}
for b in IO:
    if b["bank"] not in bank_vccio:
        sys.exit(f"no VCCIO plan for bank {b['bank']} (ball {b['ball']})")

# ---------------------------------------------------------------- DDR3L x32
# One x8 DQ/DQS group per SAC byte lane; groups chosen from the F484
# "DQS for X8" column (DQ4T, DQ3T, DQ2T, DQ1T = HMC T_DQS_0/1/2/4).
# Rank structure (D18 adapted in S6 for real DDR3L parts, see NM24): 4 x 8 Gb
# x16 dies = 2 ranks; rank 0 = die0 (bytes 0-1) + die1 (bytes 2-3), rank 1 =
# die2 + die3 on the same byte-lane balls. Rank controls on the HMC-
# provisioned pair balls: CS#_0/1 = E9/D9, CKE_0/1 = F14/B13, ODT_0/1 =
# L8/A12; RESET# = J19 shared; RZQ_2 = B11 (240 Ohm to GND).
# T_DQ_3..7 etc: "T_DQ_n" = F484 HMC Pin Assignment for DDR3/DDR2 column.
DDR3_MAP = [
    # (ball, designator/role, byte, group, note)
    ("E12", "T_DQ_0", 0, "DQ4T", "SAC byte 0 DQ0"), ("D12", "T_DQ_1", 0, "DQ4T", ""),
    ("C11", "T_DQ_2", 0, "DQ4T", ""), ("K9", "T_DQ_3", 0, "DQ4T", ""),
    ("C13", "T_DQ_4", 0, "DQ4T", ""), ("D13", "T_DQ_5", 0, "DQ4T", ""),
    ("B12", "T_DQ_6", 0, "DQ4T", ""), ("F12", "T_DQ_7", 0, "DQ4T", ""),
    ("G11", "T_DM_0", 0, "DQ4T", ""), ("L8", "T_ODT_0", 0, "DQ4T", "ODT rank 0"),
    ("H11", "T_DQS_0", 0, "DQ4T", "DQS byte 0 p"), ("G12", "T_DQS#_0", 0, "DQ4T", "DQS byte 0 n"),
    ("F13", "T_DQ_8", 1, "DQ3T", "SAC byte 1 DQ8"), ("E14", "T_DQ_9", 1, "DQ3T", ""),
    ("J11", "T_DQ_10", 1, "DQ3T", ""), ("A13", "T_DQ_11", 1, "DQ3T", ""),
    ("B15", "T_DQ_12", 1, "DQ3T", ""), ("C15", "T_DQ_13", 1, "DQ3T", ""),
    ("G15", "T_DQ_14", 1, "DQ3T", ""), ("K16", "T_DQ_15", 1, "DQ3T", ""),
    ("J17", "T_DM_1", 1, "DQ3T", ""), ("F14", "T_CKE_0", 1, "DQ3T", "CKE rank 0"),
    ("H14", "T_DQS_1", 1, "DQ3T", "DQS byte 1 p"), ("J13", "T_DQS#_1", 1, "DQ3T", "DQS byte 1 n"),
    ("F15", "T_DQ_16", 2, "DQ2T", "SAC byte 2 DQ16"), ("E15", "T_DQ_17", 2, "DQ2T", ""),
    ("A15", "T_DQ_18", 2, "DQ2T", ""), ("J18", "T_DQ_19", 2, "DQ2T", ""),
    ("E16", "T_DQ_20", 2, "DQ2T", ""), ("D17", "T_DQ_21", 2, "DQ2T", ""),
    ("G17", "T_DQ_22", 2, "DQ2T", ""), ("C16", "T_DQ_23", 2, "DQ2T", ""),
    ("B16", "T_DM_2", 2, "DQ2T", ""),
    ("G18", "T_DQS_2", 2, "DQ2T", "DQS byte 2 p"), ("H18", "T_DQS#_2", 2, "DQ2T", "DQS byte 2 n"),
    ("B21", "T_DQ_32", 3, "DQ1T", "SAC byte 3 DQ32"), ("C21", "T_DQ_33", 3, "DQ1T", ""),
    ("G22", "T_DQ_34", 3, "DQ1T", ""), ("B17", "T_DQ_35", 3, "DQ1T", ""),
    ("D19", "T_DQ_36", 3, "DQ1T", ""), ("E19", "T_DQ_37", 3, "DQ1T", ""),
    ("C20", "T_DQ_38", 3, "DQ1T", ""), ("D21", "T_DQ_39", 3, "DQ1T", ""),
    ("E21", "T_DM_4", 3, "DQ1T", ""),
    ("J21", "T_DQS_4", 3, "DQ1T", "DQS byte 3 p"), ("J22", "T_DQS#_4", 3, "DQ1T", "DQS byte 3 n"),
    ("J19", "T_RESET#", None, "", "DDR3 RESET# all dies"),
    ("B11", "RZQ_2", None, "", "RZQ 240 ohm to GND"),
    ("A12", "T_ODT_1", None, "", "ODT rank 1"),
    ("B13", "T_CKE_1", None, "", "CKE rank 1"),
    # address / command, bank 8A (SSTL-135, shared by all 4 dies)
    ("L7", "T_A_0", None, "", ""), ("K7", "T_A_1", None, "", ""),
    ("H8", "T_A_2", None, "", ""), ("G8", "T_A_3", None, "", ""),
    ("J7", "T_A_4", None, "", ""), ("J8", "T_A_5", None, "", ""),
    ("A10", "T_A_6", None, "", ""), ("A9", "T_A_7", None, "", ""),
    ("A8", "T_A_8", None, "", ""), ("A7", "T_A_9", None, "", ""),
    ("C6", "T_A_10", None, "", ""), ("D6", "T_A_11", None, "", ""),
    ("D7", "T_A_12", None, "", ""), ("C8", "T_A_13", None, "", ""),
    ("G6", "T_A_14", None, "", ""), ("H6", "T_A_15", None, "", ""),
    ("A5", "T_BA_0", None, "", ""), ("B10", "T_BA_1", None, "", ""),
    ("C9", "T_BA_2", None, "", ""),
    ("B7", "T_RAS#", None, "", ""), ("B6", "T_CAS#", None, "", ""),
    ("F7", "T_WE#", None, "", ""),
    ("E9", "T_CS#_0", None, "", "CS# rank 0"),
    ("D9", "T_CS#_1", None, "", "CS# rank 1"),
    ("J9", "T_CK", None, "", "DDR3 CK p"), ("H9", "T_CK#", None, "", "DDR3 CK n"),
]
used = set()
for ball, desig, byte, group, note in DDR3_MAP:
    if ball not in BALLS:
        sys.exit(f"DDR3 ball {ball} not in F484 table")
    info = BALLS[ball]
    if info["func"] != "IO":
        sys.exit(f"DDR3 ball {ball} is not user IO ({info['func']})")
    if info["bank"] not in ("7A", "8A"):
        sys.exit(f"DDR3 ball {ball} is not in a 1.35 V bank")
    # designator cross-check: group members against the F484 HMC DDR3 column
    if desig.startswith("T_") or desig.startswith("RZQ_"):
        expect = ("T_" + desig[2:]) if desig.startswith("T_") and desig[2] not in "_#" else desig
        # exact match pass (RZQ_2 lives in the optional-function column)
        if desig.startswith("RZQ_"):
            if info["opt"] != desig:
                sys.exit(f"{ball} optional function is {info['opt']!r}, expected {desig}")
        else:
            if info["hmc"] != desig:
                sys.exit(f"{ball} HMC DDR3 designation is {info['hmc']!r}, expected {desig}")
    if ball in used:
        sys.exit(f"DDR3 ball {ball} reserved twice")
    used.add(ball)

# group integrity: 8 DQ + DM share one "DQS for X8" group; DQS pair of that group
groups = collections.defaultdict(list)
for ball, desig, byte, group, note in DDR3_MAP:
    if byte is not None:
        groups[(byte, group)].append(ball)
for k, blist in groups.items():
    def gid(x):
        return re.sub(r"^(DQSn|DQS|DQ)", "", x)
    core = [b for b in blist if BALLS[b]["hmc"].startswith(("T_DQ_", "T_DM_"))]
    ids = {gid(BALLS[b]["dqs_x8"]) for b in core}
    if len(ids) != 1 or gid(k[1]) not in ids:
        sys.exit(f"byte group {k}: members not all in X8 group {k[1]} (saw {ids})")
    dq = core
    if len(dq) != 9:
        sys.exit(f"byte group {k}: expected 8 DQ + 1 DM, got {len(dq)}")

# DQS pairs bank and bank-locality check
for byte in range(4):
    p = [m for m in DDR3_MAP if m[2] == byte and m[1].startswith("T_DQS")]
    if len(p) != 2:
        sys.exit(f"byte {byte}: DQS pair not complete")
    balls_p = [m[0] for m in p]
    if {BALLS[b]["bank"] for b in balls_p} != {BALLS[balls_p[0]]["bank"]}:
        sys.exit(f"byte {byte}: DQS pair split across banks")



# ---------------------------------------------------------------- parked
PARKED = [
    # signal, reason (short), where cited
    ("TCK", "cartridge tie: CPU test port, not routed to FPGA"),
    ("TMS", "cartridge tie: CPU test port"),
    ("TDI", "cartridge tie: CPU test port"),
    ("TDO", "no connect: test port output, board never listens"),
    ("TRST#", "cartridge tie: TAP held reset (test port docs 24365703)"),
    ("PREQ#", "no connect: debug port request, inactive"),
    ("PRDY#", "no connect: debug port ready"),
    ("VID0", "strap divider 00001 = 2.00 V (hw/slot1-cyclonev/power.md)"),
    ("VID1", "strap divider 00001 = 2.00 V"),
    ("VID2", "strap divider 00001 = 2.00 V"),
    ("VID3", "strap divider 00001 = 2.00 V"),
    ("VID4", "strap divider 00001 = 2.00 V"),
    ("100/66#", "left floating: high = 100 MHz capable (slot1_notes.md line 88, NM4)"),
    ("TESTHI", "cartridge tie per Table 35 (test mode strap)"),
    ("BP[2]#", "no connect: breakpoint output, unused"),
    ("BP[3]#", "no connect: breakpoint output, unused"),
    ("BPM[0]#", "tie inactive high: breakpoint enable ignored"),
    ("BPM[1]#", "tie inactive high: breakpoint enable ignored"),
    ("IERR#", "undriven: board terminator keeps it high (no internal error report)"),
    ("FERR#", "undriven: board terminator keeps it high (FPU reported internally)"),
    ("PICCLK", "no pin: local APIC timer clocked internally (NM21)"),
    ("SLOTOCC#", "cartridge tie low: CPU presence sampled by board (3.3 V OBD rail)"),
    ("PICD0", "cartridge tie: APIC ID 0"),
    ("PICD1", "cartridge tie: APIC ID 0"),
    ("THERMDP", "no connect: analog thermal diode (NM11 followup in S7)"),
    ("THERMDN", "no connect: analog thermal diode"),
]
rows1 = list(csv.DictReader(open(SLOT1CSV)))
sig_by_name = collections.defaultdict(list)
for r in rows1:
    sig_by_name[r["signal"]].append(r)
for sig, *_ in PARKED:
    if sig not in sig_by_name:
        sys.exit(f"parked signal {sig} not in slot1_signals.csv")

# ---------------------------------------------------------------- assignment
def famkey(sig):
    m = re.match(r"^(A|D|DEP|AP|REQ|RS)\[(\d+)\]#$", sig)
    if m:
        return (0, m.group(1), int(m.group(2)))
    return (1, sig, 0)

# RESET# is AGTL+ like the bus; CMOS control after it.
CMOS = sorted(s for s in ("A20M#", "FLUSH#", "IGNNE#", "INIT#", "LINT[0]/INTR",
                          "LINT[1]/NMI", "PWRGOOD", "SLP#", "SMI#", "STPCLK#",
                          "THERMTRIP#"))
AGTL_CTL = ["RESET#"]
BCLK = ("BCLK", "M9", "3B")   # reserved before distribution

parked_names = set(p for p, *_ in PARKED)
to_assign_bus = [r["signal"] for r in rows1
                 if r["required"] == "yes" and r["class"] == "bus"
                 and r["signal"] not in parked_names]
to_assign_ctl = [r["signal"] for r in rows1
                 if r["required"] == "yes" and r["class"] == "control"
                 and r["signal"] not in parked_names]
missing = set(to_assign_ctl) - set(CMOS + AGTL_CTL)
if missing:
    sys.exit(f"control signals not in the CMOS/AGTL plan: {sorted(missing)}")

order = ([f"A[{i}]#" for i in range(3, 36)]
         + [f"D[{i}]#" for i in range(64)]
         + [f"DEP[{i}]#" for i in range(8)]
         + ["AP[0]#", "AP[1]#"]
         + sorted(s for s in to_assign_bus
                  if not re.match(r"^(A|D|DEP|AP)\[\d+\]#$", s))
         + AGTL_CTL)
if sorted(order) != sorted(set(to_assign_bus + AGTL_CTL)):
    got = collections.Counter([s for s in order])
    want = collections.Counter(to_assign_bus + AGTL_CTL)
    diff = {k: (got[k], want.get(k, 0)) for k in set(got) | set(want) if got[k] != want.get(k, 0)}
    sys.exit(f"order list does not match required bus+RESET# set: {diff}")

# pools: 3.3 V banks first (deterministic order), then 1.35 V overflow.
pool33 = [b["ball"] for b in IO if bank_vccio[b["bank"]] == "3.3 V"
          and b["ball"] not in ("M9", "M8")]
pool33.sort()
pool_ovf = [b["ball"] for b in IO if b["bank"] in ("7A", "8A") and b["ball"] not in used]
pool_ovf.sort()

assignment = []   # (contact, signal, ball, bank, kind)
i33 = iovf = 0
def take(name, agtl):
    global i33, iovf
    if i33 < len(pool33):
        ball = pool33[i33]; i33 += 1
    elif agtl and iovf < len(pool_ovf):
        ball = pool_ovf[iovf]; iovf += 1
    else:
        sys.exit(f"out of balls at signal {name}")
    return ball

def trid_seq():
    """translator ids with supply-pair boundaries: a physical Translator_8ch
    chip has ONE VCCA/VCCB pair, so a chip breaks when either the FPGA-side
    bank VCCIO (3.3 vs 1.35 V) or the socket-side rail (AGTL+ -> VTT 1.5 V,
    CMOS -> 2.5 V) changes, in addition to the 8-channel limit.  S5's flat
    fill wrongly mixed rails inside one chip (S6 fix, D21)."""
    out = []
    chip_key, nch, ncid = None, 0, 0
    for a in assignment:
        bank, kind = BALLS[a[2]]["bank"], a[4]
        if kind == "clock":
            out.append("")
            continue
        key = (bank_vccio[bank], kind)
        if key != chip_key or nch == 8:
            ncid += 1
            chip_key = key
            nch = 0
        nch += 1
        out.append(f"T{ncid:02d}c{nch}")
    return out, ncid

assignment.append(("A75", "BCLK", BCLK[1], BCLK[2], "clock"))
# CMOS control lands first (pool33 only); AGTL+ bus + RESET# spill to the
# 1.35 V banks once the 3.3 V pools are exhausted (D20).
for signal in CMOS:
    ball = take(signal, agtl=False)
    assignment.append((sig_by_name[signal][0]["pin"], signal, ball,
                       BALLS[ball]["bank"], "cmos"))
for signal in order:
    r = sig_by_name[signal][0]
    agtl = "AGTL+" in r["level"] or signal == "RESET#"
    ball = take(signal, agtl)
    assignment.append((r["pin"], signal, ball, BALLS[ball]["bank"],
                       "agtl" if agtl else "cmos"))

used |= {a[2] for a in assignment}
for a in assignment:
    if BALLS[a[2]]["bank"] in ("7A", "8A") and a[4] != "agtl":
        sys.exit(f"{a[1]} = {a[2]}: non-AGTL+ net on a 1.35 V bank")

# BCLK clock-capable check: clk pair col from the converted CSV
clock_ok = set()
clcsv = ROOT / "FPGAlist/CycloneV_A9/pins/5cefa9_f484.csv"
for r in csv.DictReader(open(clcsv)):
    if r["clock"].startswith("CLK") and not r["clock"].endswith("n"):
        clock_ok.add(r["ball"])
if BCLK[1] not in clock_ok:
    sys.exit(f"BCLK ball {BCLK[1]} is not a clock input pair pin")
if bank_vccio[BCLK[2]] != "3.3 V":
    sys.exit("BCLK bank must be 3.3 V (2.5 V swing vs 1.35 V banks)")

# ---------------------------------------------------------------- reports
def io_standard(kind, ball):
    if kind == "clock":
        return "3.3-V LVTTL (2.5 V swing in, NM21)"
    if kind == "cmos":
        return "3.3-V LVTTL"
    return ("SSTL-135 CLASS I" if BALLS[ball]["bank"] in ("7A", "8A")
            else "3.3-V LVTTL")

OUT.mkdir(exist_ok=True)
srcs = {r["signal"]: r["source"] for r in rows1}
srcline = {r["signal"]: (r["pin"], r["level"]) for r in rows1}

trids, nchips = trid_seq()
row = iter(trids)
with open(OUT / "pins.csv", "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["signal", "ball", "bank", "vccio", "io_standard",
                "translator", "contact", "contact_level", "kind", "source"])
    for contact, signal, ball, bank, kind in assignment:
        w.writerow([signal, ball, bank, bank_vccio[bank],
                    io_standard(kind, ball),
                    next(row), contact,
                    srcline[signal][1], kind, srcs[signal]])

with open(OUT / "ddr3.csv", "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["ball", "designator", "byte", "x8_group", "bank", "note"])
    for ball, desig, byte, group, note in DDR3_MAP:
        w.writerow([ball, desig, "" if byte is None else byte, group,
                    BALLS[ball]["bank"], note])

with open(OUT / "parked.csv", "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["signal", "pin", "class", "required", "reason"])
    for sig, reason in PARKED:
        r = sig_by_name[sig][0]
        w.writerow([sig, r["pin"], r["class"], r["required"], reason])

with open(OUT / "assignment_quartus.qsf", "w") as fh:
    fh.write('set_global_assignment -name FAMILY "Cyclone V"\n')
    fh.write('set_global_assignment -name DEVICE 5CEFA9F23C8N\n')
    fh.write('set_global_assignment -name ERROR_CHECK_FREQUENCY_DIVISOR 1\n')
    for contact, signal, ball, bank, kind in assignment:
        q = signal.replace('"', '\\"')
        fh.write(f'set_location_assignment PIN_{ball} -to "{q}"\n')
        std = io_standard(kind, ball).split(" (")[0]
        fh.write(f'set_instance_assignment -name IO_STANDARD "{std}" -to "{q}"\n')
    fh.write('set_instance_assignment -name IOBANK_VCCIO -to "7A" "1.35 V"\n')
    fh.write('set_instance_assignment -name IOBANK_VCCIO -to "8A" "1.35 V"\n')

# counts
bybank = collections.Counter(BALLS[a[2]]["bank"] for a in assignment)
ddr_bybank = collections.Counter(BALLS[m[0]]["bank"] for m in DDR3_MAP)
per = collections.Counter(b["bank"] for b in IO)
report = ["per-bank IO: DDR3 + CPU assignment + free",
          *[f"  {b}: io={per[b]} ddr3={ddr_bybank.get(b,0)} cpu={bybank.get(b,0)} "
            f"free={per[b]-ddr_bybank.get(b,0)-bybank.get(b,0)}"
            for b in sorted(per)],
          f"DDR3 balls: {len(DDR3_MAP)}",
          f"CPU contacts assigned: {len(assignment)-1} (excl BCLK direct) +1 BCLK",
          f"parked contacts: {len(PARKED)}",
          f"translator channels: {len([t for t in trids if t])} in "
          f"{nchips} translator chips (chips padded to 8 channels; supply-"
          f"pair boundaries D21)",
          f"1.35 V overflow AGTL+ used: {iovf} of {len(pool_ovf)}"]
print("\n".join(report))

fails = 0
for cond, msg in [
    (len(assignment) == 1 + len(order) + len(CMOS), "assignment count mismatch"),
    (len(used) == len(DDR3_MAP) + len(assignment) + 0, "ball overlap/mismatch"),
    (len(used) <= 224, "ball budget exceeded"),
    (not missing, None),
]:
    if cond is False:
        print("FAIL:", msg)
        fails += 1
if fails:
    sys.exit(1)
print("S5 checks PASS")
