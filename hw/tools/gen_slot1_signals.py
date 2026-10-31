#!/usr/bin/env python3
"""Task S1 (plan/slot1.md): build hw/common/slot1_signals.csv typed from
the Pentium II SC242 datasheet (24365703). One row per connector contact;
checks pass or exit 1."""
import collections, csv, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "hw/common/slot1_signals.csv"
SRC = "sockets/slot1/pentium2_350-450_sc242_24365703.pdf"
# Table 35, sheets 1-4, pp 58-60: pin -> (pin name, signal buffer type)
# extracted verbatim from the datasheet text (all 242 contacts: A1-A121, B1-B121).
PIN_A = [
    ("VCC_VTT", "AGTL+ VTT Supply"),
    ("GND", "V SS"),
    ("VCC_VTT", "AGTL+ VTT Supply"),
    ("IERR#", "CMOS Output"),
    ("A20M#", "CMOS Input"),
    ("GND", "V SS"),
    ("FERR#", "CMOS Output"),
    ("IGNNE#", "CMOS Input"),
    ("TDI", "JTAG Input"),
    ("GND", "V SS"),
    ("TDO", "JTAG Output"),
    ("PWRGOOD", "CMOS Input"),
    ("TESTHI", "CMOS Test Input"),
    ("GND", "V SS"),
    ("THERMTRIP#", "CMOS Output"),
    ("Reserved", "Reserved for Future Use"),
    ("LINT[0]/INTR", "CMOS Input"),
    ("GND", "V SS"),
    ("PICD[0]", "CMOS I/O"),
    ("PREQ#", "CMOS Input"),
    ("BP[3]#", "AGTL+ I/O"),
    ("GND", "V SS"),
    ("BPM[0]#", "AGTL+ I/O"),
    ("BINIT#", "AGTL+ I/O"),
    ("DEP[0]#", "AGTL+ I/O"),
    ("GND", "V SS"),
    ("DEP[1]#", "AGTL+ I/O"),
    ("DEP[3]#", "AGTL+ I/O"),
    ("DEP[5]#", "AGTL+ I/O"),
    ("GND", "V SS"),
    ("DEP[6]#", "AGTL+ I/O"),
    ("D[61]#", "AGTL+ I/O"),
    ("D[55]#", "AGTL+ I/O"),
    ("GND", "VSS"),
    ("D[60]#", "AGTL+ I/O"),
    ("D[53]#", "AGTL+ I/O"),
    ("D[57]#", "AGTL+ I/O"),
    ("GND", "VSS"),
    ("D[46]#", "AGTL+ I/O"),
    ("D[49]#", "AGTL+ I/O"),
    ("D[51]#", "AGTL+ I/O"),
    ("GND", "VSS"),
    ("D[42]#", "AGTL+ I/O"),
    ("D[45]#", "AGTL+ I/O"),
    ("D[39]#", "AGTL+ I/O"),
    ("GND", "VSS"),
    ("Reserved", "Reserved for Future Use"),
    ("D[43]#", "AGTL+ I/O"),
    ("D[37]#", "AGTL+ I/O"),
    ("GND", "VSS"),
    ("D[33]#", "AGTL+ I/O"),
    ("D[35]#", "AGTL+ I/O"),
    ("D[31]#", "AGTL+ I/O"),
    ("GND", "VSS"),
    ("D[30]#", "AGTL+ I/O"),
    ("D[27]#", "AGTL+ I/O"),
    ("D[24]#", "AGTL+ I/O"),
    ("GND", "VSS"),
    ("D[23]#", "AGTL+ I/O"),
    ("D[21]#", "AGTL+ I/O"),
    ("D[16]#", "AGTL+ I/O"),
    ("GND", "VSS"),
    ("D[13]#", "AGTL+ I/O"),
    ("D[11]#", "AGTL+ I/O"),
    ("D[10]#", "AGTL+ I/O"),
    ("GND", "VSS"),
    ("D[14]#", "AGTL+ I/O"),
    ("D[9]#", "AGTL+ I/O"),
    ("D[8]#", "AGTL+ I/O"),
    ("GND", "V SS"),
    ("D[5]#", "AGTL+ I/O"),
    ("D[3]#", "AGTL+ I/O"),
    ("D[1]#", "AGTL+ I/O"),
    ("GND", "V SS"),
    ("BCLK", "Processor Clock Input"),
    ("BR0#", "AGTL+ I/O"),
    ("BERR#", "AGTL+ I/O"),
    ("GND", "V SS"),
    ("A[33]#", "AGTL+ I/O"),
    ("A[34]#", "AGTL+ I/O"),
    ("A[30]#", "AGTL+ I/O"),
    ("GND", "V SS"),
    ("A[31]#", "AGTL+ I/O"),
    ("A[27]#", "AGTL+ I/O"),
    ("A[22]#", "AGTL+ I/O"),
    ("GND", "V SS"),
    ("A[23]#", "AGTL+ I/O"),
    ("Reserved", "Reserved for Future Use"),
    ("A[19]#", "AGTL+ I/O"),
    ("GND", "V SS"),
    ("A[18]#", "AGTL+ I/O"),
    ("A[16]#", "AGTL+ I/O"),
    ("A[13]#", "AGTL+ I/O"),
    ("GND", "V SS"),
    ("A[14]#", "AGTL+ I/O"),
    ("A[10]#", "AGTL+ I/O"),
    ("A[5]#", "AGTL+ I/O"),
    ("GND", "V SS"),
    ("A[9]#", "AGTL+ I/O"),
    ("A[4]#", "AGTL+ I/O"),
    ("BNR#", "AGTL+ I/O"),
    ("GND", "V SS"),
    ("BPRI#", "AGTL+ Input"),
    ("TRDY#", "AGTL+ Input"),
    ("DEFER#", "AGTL+ Input"),
    ("GND", "V SS"),
    ("REQ[2]#", "AGTL+ I/O"),
    ("REQ[3]#", "AGTL+ I/O"),
    ("HITM#", "AGTL+ I/O"),
    ("GND", "VSS"),
    ("DBSY#", "AGTL+ I/O"),
    ("RS[1]#", "AGTL+ Input"),
    ("Reserved", "Reserved for Future Use"),
    ("GND", "VSS"),
    ("ADS#", "AGTL+ I/O"),
    ("Reserved", "Reserved for Future Use"),
    ("AP[0]#", "AGTL+ I/O"),
    ("GND", "VSS"),
    ("VID[2]", "Voltage Identification"),
    ("VID[1]", "Voltage Identification"),
    ("VID[4]", "Voltage Identification"),
]

PIN_B = [
    ("EMI", "EMI Management"),
    ("FLUSH#", "CMOS Input"),
    ("SMI#", "CMOS Input"),
    ("INIT#", "CMOS Input"),
    ("VCC_VTT", "AGTL+ VTT Supply"),
    ("STPCLK#", "CMOS Input"),
    ("TCK", "JTAG Input"),
    ("SLP#", "CMOS Input"),
    ("VCC_VTT", "AGTL+ VTT Supply"),
    ("TMS", "JTAG Input"),
    ("TRST#", "JTAG Input"),
    ("Reserved", "Reserved for Future Use"),
    ("VCC_CORE", "Processor core V CC"),
    ("THERMDP", "Diode Anode"),
    ("THERMDN", "Diode Cathode"),
    ("LINT[1]/NMI", "CMOS Input"),
    ("VCC_CORE", "Processor core V CC"),
    ("PICCLK", "APIC Clock Input"),
    ("BP[2]#", "AGTL+ I/O"),
    ("Reserved", "Reserved for Future Use"),
    ("100/66#", "BCLK Frequency Select"),
    ("PICD[1]", "CMOS I/O"),
    ("PRDY#", "AGTL+ Output"),
    ("BPM[1]#", "AGTL+ I/O"),
    ("VCC_CORE", "Processor core V CC"),
    ("DEP[2]#", "AGTL+ I/O"),
    ("DEP[4]#", "AGTL+ I/O"),
    ("DEP[7]#", "AGTL+ I/O"),
    ("VCC_CORE", "Processor core VCC"),
    ("D[62]#", "AGTL+ I/O"),
    ("D[58]#", "AGTL+ I/O"),
    ("D[63]#", "AGTL+ I/O"),
    ("VCC_CORE", "Processor core VCC"),
    ("D[56]#", "AGTL+ I/O"),
    ("D[50]#", "AGTL+ I/O"),
    ("D[54]#", "AGTL+ I/O"),
    ("VCC_CORE", "Processor core VCC"),
    ("D[59]#", "AGTL+ I/O"),
    ("D[48]#", "AGTL+ I/O"),
    ("D[52]#", "AGTL+ I/O"),
    ("EMI", "EMI Management"),
    ("D[41]#", "AGTL+ I/O"),
    ("D[47]#", "AGTL+ I/O"),
    ("D[44]#", "AGTL+ I/O"),
    ("VCC_CORE", "Processor core VCC"),
    ("D[36]#", "AGTL+ I/O"),
    ("D[40]#", "AGTL+ I/O"),
    ("D[34]#", "AGTL+ I/O"),
    ("VCC_CORE", "Processor core VCC"),
    ("D[38]#", "AGTL+ I/O"),
    ("D[32]#", "AGTL+ I/O"),
    ("D[28]#", "AGTL+ I/O"),
    ("VCC_CORE", "Processor core VCC"),
    ("D[29]#", "AGTL+ I/O"),
    ("D[26]#", "AGTL+ I/O"),
    ("D[25]#", "AGTL+ I/O"),
    ("VCC_CORE", "Processor core VCC"),
    ("D[22]#", "AGTL+ I/O"),
    ("D[19]#", "AGTL+ I/O"),
    ("D[18]#", "AGTL+ I/O"),
    ("EMI", "EMI Management"),
    ("D[20]#", "AGTL+ I/O"),
    ("D[17]#", "AGTL+ I/O"),
    ("D[15]#", "AGTL+ I/O"),
    ("VCC_CORE", "Processor core VCC"),
    ("D[12]#", "AGTL+ I/O"),
    ("D[7]#", "AGTL+ I/O"),
    ("D[6]#", "AGTL+ I/O"),
    ("VCC_CORE", "Processor core VCC"),
    ("D[4]#", "AGTL+ I/O"),
    ("D[2]#", "AGTL+ I/O"),
    ("D[0]#", "AGTL+ I/O"),
    ("VCC_CORE", "Processor core V CC"),
    ("RESET#", "AGTL+ Input"),
    ("BR1#", "AGTL+ Input"),
    ("Reserved", "Reserved for Future Use."),
    ("VCC_CORE", "Processor core V CC"),
    ("A[35]#", "AGTL+ I/O"),
    ("A[32]#", "AGTL+ I/O"),
    ("A[29]#", "AGTL+ I/O"),
    ("EMI", "EMI Management"),
    ("A[26]#", "AGTL+ I/O"),
    ("A[24]#", "AGTL+ I/O"),
    ("A[28]#", "AGTL+ I/O"),
    ("VCC_CORE", "Processor core V CC"),
    ("A[20]#", "AGTL+ I/O"),
    ("A[21]#", "AGTL+ I/O"),
    ("A[25]#", "AGTL+ I/O"),
    ("VCC_CORE", "Processor core V CC"),
    ("A[15]#", "AGTL+ I/O"),
    ("A[17]#", "AGTL+ I/O"),
    ("A[11]#", "AGTL+ I/O"),
    ("VCC_CORE", "Processor core V CC"),
    ("A[12]#", "AGTL+ I/O"),
    ("A[8]#", "AGTL+ I/O"),
    ("A[7]#", "AGTL+ I/O"),
    ("VCC_CORE", "Processor core V CC"),
    ("A[3]#", "AGTL+ I/O"),
    ("A[6]#", "AGTL+ I/O"),
    ("EMI", "EMI Management"),
    ("SLOTOCC#", "SC 242 Occupied"),
    ("REQ[0]#", "AGTL+ I/O"),
    ("REQ[1]#", "AGTL+ I/O"),
    ("REQ[4]#", "AGTL+ I/O"),
    ("VCC_CORE", "Processor core V CC"),
    ("LOCK#", "AGTL+ I/O"),
    ("DRDY#", "AGTL+ I/O"),
    ("RS[0]#", "AGTL+ Input"),
    ("VCC5", "Other V CC"),
    ("HIT#", "AGTL+ I/O"),
    ("RS[2]#", "AGTL+ Input"),
    ("Reserved", "Reserved for Future Use"),
    ("VCC_L2", "Other VCC"),
    ("RP#", "AGTL+ I/O"),
    ("RSP#", "AGTL+ Input"),
    ("AP[1]#", "AGTL+ I/O"),
    ("VCC_L2", "Other V CC"),
    ("AERR#", "AGTL+ I/O"),
    ("VID[3]", "Voltage Identification"),
    ("VID[0]", "Voltage Identification"),
    ("VCC_L2", "Other V CC"),
]

B = f"{SRC} Table 35 pp 58-60"            # pin rows + buffer types
G = f"{SRC} Table 3 p18 (buffer-type tree; note 5: 2.5 V group)"      # signal groups
D = f"{SRC} Tables 6/7 pp 24-25"          # AGTL+ / non-AGTL+ DC levels
L = f"{SRC} Table 7 + note 5"             # 2.5 V group level, OD outputs

def agtlt(sig):
    # AGTL+ groups refresh per Table 6: VTT 1.5 V +/-9 %, OD, Ron <= 16.67 ohm,
    # VREF = 2/3 VTT generated on the processor substrate (Table 8 p25).
    cls = "bus"
    if sig == "RESET#":
        cls = "control"
    if sig == "PRDY#":
        cls = "debug"
    return ("AGTL+ (OD, VTT 1.5 V, VREF 2/3 VTT)", "AGTL+", cls, "yes",
            f"{B}; {G}; {D}; {SRC} Table 8 p25 VREF")

def cmos(sig):
    d = {"PREQ#": ("I", "2.5 V CMOS", "CMOS", "debug", "yes", f"{B}; {L}"),
         "TESTHI": ("I", "2.5 V via 1-100 kOhm to VCC2.5 (note 6)", "CMOS",
                    "control", "yes", f"{B}; {G}"),
         "PICD": ("IO", "2.5 V CMOS (OD drives)", "CMOS", "sideband", "no",
                  f"{B}; {L}"),
         "THERMDP": ("I", "analog diode anode", "analog", "sideband", "no",
                     f"{B}; {SRC} p79 Table 41"),
         "THERMDN": ("O", "analog diode cathode", "analog", "sideband", "no",
                     f"{B}; {SRC} p79 Table 41")}
    return d.get(sig, ("", "2.5 V CMOS", "CMOS", "control", "yes", f"{B}; {L}"))

STRAPS = {
    "BCLK": ("I", "BCLK AC per Table 10 (edge fingers)", "clock", "clock",
             "yes", f"{B}; {SRC} Table 10 p28"),
    "PICCLK": ("I", "2.5 V CMOS", "CMOS", "clock", "yes", f"{B}; {L}"),
    "100/66#": ("IO", "pull-up 3.3 V 200 ohm (board); cartridge may ground",
                "CMOS-OD (3.3 V rail)", "strap", "yes",
                f"{SRC} 2.8.2 pp 19-20 Fig. 4"),
    "SLOTOCC#": ("O", "open, board pull-up per Table 2", "CMOS-OD", "sideband",
                 "no", f"{B}; {SRC} Table 42 p81"),
    "VID": ("O", "passive short-to-VSS or open", "passive", "strap", "yes",
            f"{B}; {SRC} 2.6 pp 15-16 Table 1"),
    "EMI": ("", "", "", "nc", "no", f"{B}; {SRC} p18 note EMI"),
}
DIRS = {"AGTL+ Input": "I", "AGTL+ Output": "O", "AGTL+ I/O": "IO",
        "CMOS Input": "I", "CMOS Output": "O", "CMOS I/O": "IO",
        "JTAG Input": "I", "JTAG Output": "O", "APIC Clock Input": "I",
        "Voltage Identification": "O", "BCLK Frequency Select": "IO",
        "SC 242 Occupied": "O"}

EXTRA_NAMES = ["PICD0", "PICD1", "VID0", "VID1", "VID2", "VID3", "VID4"]

rows = []
for side in "AB":
    pins = PIN_A if side == "A" else PIN_B
    for i, (name, buftype) in enumerate(pins, 1):
        pin = f"{side}{i}"
        buftype = buftype.replace("V SS", "VSS")
        buftype = buftype.replace("V CC", "VCC").rstrip(".")
        if name in ("GND", "Reserved") :
            signal = "GND" if name == "GND" else "Reserved"
            rows.append([pin, signal, "", "", "", "power" if name == "GND"
                         else "nc", "no" if name == "GND" else "no",
                         f"{B}" if name == "GND" else f"{B} reserved"])
            continue
        if buftype in ("AGTL+ VTT Supply", "Processor core VCC", "Other VCC"):
            req = "yes" if buftype == "AGTL+ VTT Supply" else "no"
            rows.append([pin, name, "", "", "", "power", req, f"{B}"])
            continue
        if buftype == "EMI Management":
            signal = name
            dir_, lvl, std, cls, req, src = STRAPS["EMI"]
        elif buftype == "Voltage Identification":
            i0 = name.index("[") + 1
            signal = "VID" + name[i0:i0 + 1]
            dir_, lvl, std, cls, req, src = STRAPS["VID"]
        elif name == "PICD[0]" or name == "PICD[1]":
            signal = "PICD" + name[-2]
            dir_, lvl, std, cls, req, src = cmos("PICD")
        elif name == "BCLK":
            signal, dir_, lvl, std, cls, req, src = "BCLK", *STRAPS["BCLK"]
        elif name == "PICCLK":
            signal, dir_, lvl, std, cls, req, src = "PICCLK", *STRAPS["PICCLK"]
        elif name == "100/66#":
            signal = "100/66#"
            dir_, lvl, std, cls, req, src = STRAPS["100/66#"]
        elif name == "SLOTOCC#":
            signal = "SLOTOCC#"
            dir_, lvl, std, cls, req, src = STRAPS["SLOTOCC#"]
        else:
            signal = name
            if buftype.startswith("AGTL+"):
                dir_ = DIRS[buftype]
                lvl, std, cls, req, src = agtlt(name)
            elif buftype.startswith("CMOS"):
                meta = cmos(name)
                dir_ = meta[0] or DIRS.get(buftype, "")
                lvl, std, cls, req, src = meta[1], meta[2], meta[3], meta[4], meta[5]
            elif buftype.startswith("Diode"):
                dir_, lvl, std, cls, req, src = cmos(name)
            elif buftype.startswith("JTAG"):
                dir_ = DIRS[buftype]
                lvl, std, cls, req, src = ("2.5 V CMOS", "CMOS", "debug",
                                           "yes", f"{B}; {L}")
            else:
                raise ValueError(f"untyped {pin} {name} {buftype}")
        rows.append([pin, signal, dir_, lvl, std, cls, req, src])

pin_A = [f"A{i}" for i in range(1, 122)]
pin_B = [f"B{i}" for i in range(1, 122)]
c = collections.Counter(r[1] for r in rows)
fails = []
def check(name, ok, detail=""):
    print(("PASS" if ok else "FAIL"), name, detail)
    if not ok:
        fails.append(name)
check("242 contacts", len(rows) == 242, str(len(rows)))
check("A1-A121 present", [r[0] for r in rows if r[0].startswith("A")]
      == pin_A)
check("B1-B121 present", [r[0] for r in rows if r[0].startswith("B")]
      == pin_B)
# Table 3 groups used for the per-signal counts:
EXPECTED = {}
for n in range(64):
    EXPECTED[f"D[{n}]#"] = 1
for n in range(3, 36):
    EXPECTED[f"A[{n}]#"] = 1
for n in range(8):
    EXPECTED[f"DEP[{n}]#"] = 1
for n in range(5):
    EXPECTED[f"REQ[{n}]#"] = 1
for s in ("ADS#", "AERR#", "BERR#", "BINIT#", "BNR#", "BR0#", "DBSY#",
          "DRDY#", "HIT#", "HITM#", "LOCK#", "RP#"):
    EXPECTED[s] = 1
for s in ("RESET#", "BPRI#", "BR1#", "DEFER#", "RSP#", "TRDY#",
          "RS[0]#", "RS[1]#", "RS[2]#", "PRDY#"):
    EXPECTED[s] = 1
for n in range(2):
    EXPECTED[f"AP[{n}]#"] = 1
for n in range(2, 4):
    EXPECTED[f"BP[{n}]#"] = 1
for n in range(2):
    EXPECTED[f"BPM[{n}]#"] = 1
for s in ("FERR#", "IERR#", "THERMTRIP#"):
    EXPECTED[s] = 1
for s in ("A20M#", "FLUSH#", "IGNNE#", "INIT#", "LINT[0]/INTR",
          "LINT[1]/NMI", "PREQ#", "PWRGOOD", "SMI#", "SLP#", "STPCLK#",
          "TESTHI"):
    EXPECTED[s] = 1
for s in ("TCK", "TDI", "TMS", "TRST#", "TDO", "BCLK", "PICCLK",
          "100/66#", "SLOTOCC#", "THERMDP", "THERMDN"):
    EXPECTED[s] = 1
for n in range(5):
    EXPECTED[f"VID{n}"] = 1
for n in range(2):
    EXPECTED[f"PICD{n}"] = 1
for k in ("GND", "VCC_VTT", "VCC_CORE", "VCC_L2", "VCC5", "EMI",
          "Reserved"):
    EXPECTED[k] = {"GND": 30, "VCC_VTT": 4, "VCC_CORE": 19, "VCC_L2": 3,
                   "VCC5": 1, "EMI": 5, "Reserved": 9}[k]
got = collections.Counter(r[1] for r in rows)
diff = {k: (got[k], v) for k, v in EXPECTED.items() if got[k] != v}
extra = {k: got[k] for k in got if k not in EXPECTED}
check("signal multiset matches Table 35", not diff and not extra,
      f"diff={diff} extra={extra}")
# every typed row has dir/level/standard; power/nc rows have none
type_fail = [r[0] for r in rows
             if (r[5] not in ("power", "nc")
                 and (not r[2] or not r[4]))
             or (r[5] in ("power", "nc") and (r[2] or r[4]))]
check("typed rows complete", not type_fail, str(type_fail[:5]))
dirs = {r[2] for r in rows}
check("dir vocabulary", dirs <= {"I", "O", "IO", ""}, str(sorted(dirs)))
logic = sum(v for k, v in got.items()
            if k not in ("GND", "VCC_VTT", "VCC_CORE", "VCC_L2", "VCC5",
                         "EMI", "Reserved"))
print(f"logic pins (non power/nc/reserved): {logic} of 242")
if fails:
    sys.exit(1)
with OUT.open("w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["pin", "signal", "dir", "level", "standard", "class",
                "required", "source"])
    w.writerows(rows)
print(f"wrote {OUT} ({len(rows)} rows)")
