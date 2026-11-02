#!/usr/bin/env python3
"""Dedicated C2 cartridge (plan/slot1_c2.md D33/D35/D37): label-wired
schematic + netlist, the S6 step of hw/slot1-cyclonev for this board.

Usage: python3 hw/tools/gen_c2cart_s6.py
Input: hw/slot1-c2cart/pins.csv (gen_c2cart_assign.py).
Output in hw/slot1-c2cart/: slot1-c2cart.kicad_sch, .net, .erc.json,
pdn.csv (every passive + regulator, for the placement step), project.

U1 5CEBA4/A9 F484 (A9 symbol; the A4's VCCIO2A/VCCPD1A2A balls, NC on
the A9, on VCCIO33), U2 the SC242 contacts, U3-U9 SN74GTL16612 (pins.csv
chip order), U10-U11 SN74CB3T3245, U12 CY2309 (BCLK -> each 16612's
CLKAB = CLKBA through 22 R; CLKOUT loaded like one chip), U13 EPCQ128A
(AS x1). Nets: bus A side = signal, B side = S_<signal> = contact; TX A
side = TX_<signal>; RX balls straight on S_<signal>; every AGTL+ contact
but RESET# 56 R to VTT15 (4-resistor packs).
Audit (exit 1): every pins.csv net reaches its ball, chip pins and
contact; chip clocks, AS flash, VREFs; Cyclone V supply bands; ERC 0.
"""
import csv
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import gen_t6_schematic as t6
import pdn
from pdn import C0402, C0603, C0805, C1210, CPAIR, R0402, Parts, buck54620, buck62130, farads, u1_pairs

ROOT = t6.ROOT
OUT = ROOT / "hw/slot1-c2cart"
NAME = "slot1-c2cart"
CPUSYM = ROOT / "sockets/kicad/CPU_SC242.kicad_sym"
FSYM = ROOT / "hw/lib/FPGA_CycloneV_5CEFA9_F484_FPGA.kicad_sym"
PARTS = ROOT / "hw/lib/Slot1_Parts.kicad_sym"
FPGACSV = ROOT / "FPGAlist/CycloneV_A9/pins/5cefa9_f484.csv"

VOLTS = {"VCC_1V1": 1.1, "VCC_AUX25": 2.5, "VCCA_FPLL25": 2.5, "VCCIO33": 3.3, "VCCIO18": 1.8}
A4_POWER = {"D4": "VCCIO33", "J1": "VCCIO33", "R1": "VCCIO33", "Y4": "VCCIO33",   # VCCIO2A
            "E1": "VCCIO33", "J2": "VCCIO33", "R2": "VCCIO33",                   # VCCPD1A2A
            "W1": "GND"}                                                          # VREFB2AN0
AS_PINS = {"DCLK": "16", "nCSO": "7", "AS_DATA0": "15", "AS_DATA1": "8"}         # FPGA -> EPCQ pin
MSEL = {"MSEL4": "VCCIO33", "MSEL3": "GND", "MSEL2": "GND", "MSEL1": "VCCIO33",
        "MSEL0": "VCCIO33"}             # 10011: AS x1/x4, 3.0/3.3 V, standard POR [cvhb Table 7-2]
GTL_REFS = {"ADDR0": "U3", "ADDR1": "U4", "DATA0": "U5", "DATA1": "U6", "DATA2": "U7",
            "DATA3": "U8", "TX": "U9"}
ZDB_OUT = dict(zip(GTL_REFS, ["CLKA1", "CLKA2", "CLKA3", "CLKA4", "CLKB1", "CLKB2", "CLKB3"]))
CB3T_REFS = {"CMOS0": "U10", "CMOS1": "U11"}
VID_GND = ["VID1", "VID2", "VID3", "VID4"]          # VID 00001 = 2.00 V, VID0 open
TIED_GND = ["100/66#", "SLOTOCC#"]                  # 66 MHz; cartridge present
FP = {"SN74GTL16612": "Package_SO:TSSOP-56_6.1x14mm_P0.5mm",
      "SN74CB3T3245": "Package_SO:TSSOP-20_4.4x6.5mm_P0.65mm",
      "CY2309": "Package_SO:SOIC-16_3.9x9.9mm_P1.27mm",
      "EPCQ128A": "Package_SO:SOIC-16W_7.5x10.3mm_P1.27mm"}
U1_SMALL = {                            # slot1_pdn.py (devkit sheet 29) per rail
    "VCC_1V1": ["1uF", "470nF"] + ["220nF"] * 2 + ["100nF"] * 3 + ["47nF"] * 4
               + ["22nF"] * 12 + ["10nF"] * 17 + ["4.7nF"] * 13,
    "VCCIO33": ["1uF", "100nF", "47nF", "22nF"] + ["10nF"] * 2 + ["4.7nF"] * 2 + ["2.2nF"] * 2,
    "VCCIO18": ["1uF", "100nF", "10nF"],
    "VCC_AUX25": ["1uF", "100nF", "10nF"],
    "VCCA_FPLL25": ["100nF"],
}
U1_BULK = [("VCC_1V1", "100uF/6.3V", C1210)] * 3 + [
    ("VCC_1V1", "4.7uF", C0603), ("VCCIO33", "10uF", C0805), ("VCCIO18", "10uF", C0805)]


def fpga_net(ball, func):
    """net of an FPGA ball pins.csv does not assign"""
    if ball in A4_POWER:
        return A4_POWER[ball]
    if func in ("TCK", "TMS", "TDI", "TDO"):
        return "F_" + func
    if func in MSEL:
        return MSEL[func]
    if func == "nCE":
        return "GND"
    if func in ("nCONFIG", "nSTATUS", "CONF_DONE"):
        return "CFG_" + func
    if func.split(",")[0] in AS_PINS:
        return as_net(func.split(",")[0])
    if func == "RREF_TL":
        return "RREF_TL"                 # PLLs used: 2.0k 1 % to GND [pcg-01014]
    if func == "GND":
        return func
    if func == "VCC":
        return "VCC_1V1"
    if func in ("VCC_AUX", "VCCBAT"):
        return "VCC_AUX25"
    if func == "VCCA_FPLL":
        return "VCCA_FPLL25"
    if func == "VCCPGM":
        return "VCCIO33"                 # AS pins and the 3.3 V EPCQ on VCCPGM
    if func == "VCCIO3A":
        return "VCCIO18"
    if func == "VCCPD3A":
        return "VCC_AUX25"               # VCCIO 1.8 V -> VCCPD 2.5 V [cvds Table 4 note 4]
    if func.startswith(("VCCIO", "VCCPD")):
        return "VCCIO33"
    if func == "VREFB3AN0":
        return "VREF_3A"
    if func.startswith("VREFB"):
        return "GND"                     # unused VREF [pcg-01014]
    return "NC_" + ball                  # unused IO, NC, DNU


def as_net(func):
    return "AS_" + func.removeprefix("AS_").upper()


def sym_pins(d):
    return [p for ps in d[2].values() for p in ps]


def by_name(pins, names):
    """pin number -> net from {pin name: net}; every symbol pin named"""
    lab = {p["num"]: names[p["name"]] for p in pins if p["name"] in names}
    missing = [p["name"] for p in pins if p["num"] not in lab]
    assert not missing, missing
    return lab


def contact_net(row, used):
    """SC242 contact -> net"""
    sig, cls = row["signal"], row["class"]
    if sig == "GND" or sig in TIED_GND:
        return "GND"
    if sig == "VCC_VTT":
        return "VTT15"
    if sig == "BCLK":
        return "BCLK"
    if sig in used or sig in VID_GND or (row["standard"] == "AGTL+" and sig != "RESET#"):
        return "S_" + sig
    return "NC_U2_" + row["pin"]


def power(P, net_of_ball, gtl, cb3t, agtl):
    """power tree (variant A's minus DDR3, plus VCCIO18) + decoupling, terminations,
    dividers, pull-ups; every passive of the board as pdn.py rows"""
    print("power tree values:")
    P.add("F", "Device:Fuse", "2A", "Fuse:Fuse_1206_3216Metric", ["V12_IN", "V12"], "stage", "F1")
    # 5 V: 7 x 16612 ICC5 120 mA max [ti_sn74gtl16612 p.6] + the TPS62130 inputs
    buck54620(P, "PS1", ("V12", 12.0), "V5", 5.0, 3.0,
              (2, "22uF/10V", 22e-6), None, "PG_5V", 6.8e-6, "MSS1048-682", 0.25)
    buck54620(P, "PS2", ("V5", 5.0), "VCC_1V1", 1.1, 4.0,
              (4, "47uF/6.3V", 150e-6), "PG_5V", "PG_1V1", 1.5e-6, "MSS1048-152", 0.029)
    buck62130(P, "PS3", "VCC_AUX25", 2.5, (2.375, 2.625), "PG_1V1", None)
    P.add("FB", "Device:FerriteBead", "BLM18AG601SN1D", "Inductor_SMD:L_0603_1608Metric",
          ["VCC_AUX25", "VCCA_FPLL25"], "stage", "PS3")
    buck62130(P, "PS4", "VCCIO33", 3.3, (3.135, 3.465), "PG_1V1", None)
    buck62130(P, "PS5", "VCCIO18", 1.8, (1.71, 1.89), "PG_1V1", None)

    pairs = u1_pairs(net_of_ball, U1_SMALL)
    for rail, caps in U1_SMALL.items():
        mine = pairs.get(rail, [])
        for k, v in enumerate(sorted(caps, key=farads)):
            if k < len(mine):
                P.c(v, CPAIR, rail, "u1pair", *mine[k], side="B")
            else:
                P.c(v, C0402, rail, "u1bulk")
        print(f"  U1 {rail}: {min(len(mine), len(caps))}/{len(caps)} on B.Cu via pairs")
    for rail, v, f in U1_BULK:
        P.c(v, f, rail, "u1bulk")

    for ref in gtl:                     # 0.1 uF per supply / VREF pin
        for pin, net in (("7", "VCCIO33"), ("22", "VCCIO33"), ("50", "V5"), ("35", "VREF_GTL")):
            P.c("100nF", C0402, net, "pin", ref, pin)
    for ref in cb3t:
        P.c("100nF", C0402, "VCC_AUX25", "pin", ref, "20")
    for pin in ("4", "13"):
        P.c("100nF", C0402, "VCCIO33", "pin", "U12", pin)
    P.c("100nF", C0402, "VCCIO33", "pin", "U13", "1")

    # VREF 2/3 VTT for the 16612s; bank 3A 0.96 V (1.00k/1.78k) inside 0.833-0.969 V [cvds Table 16]
    P.r("1.00k", "VTT15", "VREF_GTL", "vref")
    P.r("2.00k", "VREF_GTL", "GND", "vref")
    P.r("1.00k", "VTT15", "VREF_3A", "vref", "U1")
    P.r("1.78k", "VREF_3A", "GND", "vref", "U1")
    P.c("100nF", C0402, "VREF_3A", "vref", "U1")
    # processor-end termination, 56 R +-5 % [p2 Table 8], packs in contact order
    for k in range(0, len(agtl), 4):
        sigs = [f"S_{s}" for s in agtl[k:k + 4]]
        sigs += [f"NC_RN{k // 4 + 1}_{n}" for n in range(len(sigs) + 1, 5)]
        P.add("RN", "Device:R_Pack04", "56R", "Resistor_SMD:R_Array_Convex_4x0402",
              sigs + ["VTT15"] * 4, "term")
    P.c("22uF", C0805, "VTT15", "term")
    P.c("22uF", C0805, "VTT15", "term")
    for _ in range(6):
        P.c("100nF", C0402, "VTT15", "term")

    for s in VID_GND:
        P.r("0R", f"S_{s}", "GND", "strap", "U2")
    for oe in ("ADDR_OEAB#", "ADDR_OEBA#", "DATA_OEAB#", "DATA_OEBA#", "TX_OEAB#"):
        P.r("10k", oe, "VCCIO33", "pullup")         # transceivers off while the FPGA configures
    for n in ("CFG_nCONFIG", "CFG_nSTATUS", "CFG_CONF_DONE"):
        P.r("10k", n, "VCCIO33", "pullup", "U1")    # to VCCPGM [pcg-01014]
    P.r("1k", "F_TCK", "GND", "pullup", "U1")
    P.r("10k", "F_TMS", "VCC_AUX25", "pullup", "U1")   # JTAG on VCCPD3A [pcg-01014]
    P.r("10k", "F_TDI", "VCC_AUX25", "pullup", "U1")
    P.add("R", "Device:R", "2.00k 1%", R0402, ["RREF_TL", "GND"], "pullup", "U1")
    for chip, out in ZDB_OUT.items():
        P.r("22R", f"ZCLK_{chip}", f"CLK_{chip}", "clk", "U12")
    P.r("22R", "ZCLK_FB", "CLK_FB", "clk", "U12")
    P.add("C", "Device:C", "10pF", C0402, ["CLK_FB", "GND"], "clk", "U12")   # ~ one chip's CLKAB + CLKBA
    return P.rows


def main():
    sig_rows = list(csv.DictReader(open(ROOT / "hw/common/slot1_signals.csv")))
    contact_row = {r["pin"]: r for r in sig_rows}
    pinsrows = list(csv.DictReader(open(OUT / "pins.csv")))
    func_by = {r["ball"]: r["function"] for r in csv.DictReader(open(FPGACSV))}
    ball_net = {}
    for r in pinsrows:
        ball_net[r["ball"]] = {"tx": "TX_", "rx": "S_"}.get(r["kind"], "") + r["signal"]
    net_of = {b: ball_net.get(b) or fpga_net(b, f) for b, f in func_by.items()}
    errs = t6.cv_supply_errors(func_by, net_of, VOLTS)
    if errs:
        print(f"SUPPLY ERRORS ({len(errs)}):", *errs, sep="\n   ")
        sys.exit(1)
    used = {r["signal"] for r in pinsrows if r["contact"]}
    agtl = sorted({r["signal"] for r in sig_rows if r["standard"] == "AGTL+" and r["signal"] != "RESET#"},
                  key=lambda s: int(next(r["pin"][1:] for r in sig_rows if r["signal"] == s)))

    lib = {d[0]: d for d in t6.parse_lib(PARTS)}
    fsym, csym = t6.parse_lib(FSYM)[0], t6.parse_lib(CPUSYM)[0]
    big = ["SN74GTL16612", "SN74CB3T3245", "CY2309", "EPCQ128A", "TPS54620", "TPS62130"]
    parts = t6.sheet_head(
        "gen_c2cart_s6", "Slot 1 C2 cartridge: 5CEBA4 + GTL+ transceivers",
        [("hw_n:" + fsym[0], fsym[1]), ("cpu_n:" + csym[0], csym[1])]
        + t6.stock_defs([("Connector_Generic", ["Conn_02x05_Odd_Even", "Conn_02x20_Odd_Even"]),
                         ("Connector", ["Barrel_Jack"]),
                         ("Device", ["C", "R", "R_Pack04", "L", "Fuse", "FerriteBead"])])
        + [("hw_n:" + n, lib[n][1]) for n in big])
    flagged = set()

    for i, uid in enumerate(sorted(fsym[2], key=int)):
        pins = fsym[2][uid]
        parts.append(t6.syminst("hw_n:" + fsym[0], "U1", 80.0 + (i % 3) * 95.0, 35.0 + (i // 3) * 62.0,
                                int(uid), pins, {p["num"]: net_of[p["num"]] for p in pins}))

    # SC242 contacts, 4 units in columns
    y, col = 305.0, 0
    for uid in sorted(csym[2], key=int):
        pins = csym[2][uid]
        lab = {p["num"]: contact_net(contact_row[p["num"]], used) if p["num"] in contact_row
               else "NC_U2_" + p["num"] for p in pins}
        flagged |= t6.power_nets(pins, lab)
        ys = [p["y"] for p in pins]
        slot = max(ys) - min(ys) + 14.0
        if y + slot > 812.0:
            y, col = 305.0, col + 1
        parts.append(t6.syminst("cpu_n:" + csym[0], "U2", 430.0 + col * 240.0, y + max(ys) + 8.0,
                                int(uid), pins, lab))
        y += slot

    def ic(name, ref, X, Y, names):
        pins = sym_pins(lib[name])
        lab = by_name(pins, names)
        flagged.update(t6.power_nets(pins, lab))
        parts.append(t6.syminst("hw_n:" + name, ref, X, Y, 1, pins, lab, footprint=FP[name]))

    chan = {}
    for r in pinsrows:
        if r["chip"]:
            chan.setdefault(r["chip"], {})[int(r["channel"])] = r
    for k, (chip, ref) in enumerate(GTL_REFS.items()):
        grp = re.sub(r"\d", "", chip)
        names = {"OEAB#": f"{grp}_OEAB#", "OEBA#": "VCCIO33" if grp == "TX" else f"{grp}_OEBA#",
                 "LEAB": "AB_LE", "LEBA": "VCCIO33" if grp == "ADDR" else "GND",
                 "CEAB#": "GND", "CEBA#": "GND", "CLKAB": f"CLK_{chip}", "CLKBA": f"CLK_{chip}",
                 "VCC33": "VCCIO33", "VCC5": "V5", "VREF": "VREF_GTL", "GND": "GND"}
        for ch in range(1, 19):
            r = chan[chip].get(ch)
            names[f"A{ch}"] = (("TX_" if grp == "TX" else "") + r["signal"]) if r else t6.NOCONNECT
            names[f"B{ch}"] = "S_" + r["signal"] if r else t6.NOCONNECT
        ic("SN74GTL16612", ref, 30.0 + k * 60.0, 230.0, names)
    for k, (chip, ref) in enumerate(CB3T_REFS.items()):
        names = {"OE#": "GND", "VCC": "VCC_AUX25", "GND": "GND", "NC": t6.NOCONNECT}
        for ch in range(1, 9):
            r = chan[chip].get(ch)
            names[f"A{ch}"] = r["signal"] if r else t6.NOCONNECT
            names[f"B{ch}"] = "S_" + r["signal"] if r else t6.NOCONNECT
        ic("SN74CB3T3245", ref, 30.0 + k * 50.0, 290.0, names)
    zdb = {"REF": "BCLK", "S1": "VCCIO33", "S2": "VCCIO33", "VDD": "VCCIO33", "GND": "GND",
           "CLKOUT": "ZCLK_FB", "CLKB4": t6.NOCONNECT}
    zdb.update({out: f"ZCLK_{chip}" for chip, out in ZDB_OUT.items()})
    ic("CY2309", "U12", 150.0, 290.0, zdb)
    epcq = {"nCS": "AS_NCSO", "DCLK": "AS_DCLK", "DATA0": "AS_DATA0", "DATA1": "AS_DATA1",
            "nRESET": "VCCIO33", "VCC": "VCCIO33", "GND": "GND", "NC": t6.NOCONNECT}
    ic("EPCQ128A", "U13", 200.0, 290.0, epcq)

    # USB-Blaster 10-pin: 1 TCK, 3 TDO, 4 VCC(TRGT) = VCCPD3A, 5 TMS, 9 TDI, 2/10 GND
    nc = t6.NOCONNECT
    jtag = ["F_TCK", "GND", "F_TDO", "VCC_AUX25", "F_TMS", nc, nc, nc, "F_TDI", "GND"]
    parts.append(t6.header("J1", "Connector_Generic:Conn_02x05_Odd_Even", jtag, 700.0, 580.0, flagged))
    parts.append(t6.header("J3", "Connector:Barrel_Jack", ["V12_IN", "GND"], 700.0, 624.0, flagged))
    # D32 link (gen_qsf.py j5_function): 1/37/38 and even 4-34 GND, 2/39/40 open
    link = {**{3 + 2 * k: f"LINK_DOWN{k}" for k in range(8)}, 19: "LINK_UCLK", 21: "LINK_DCLK",
            **{23 + 2 * k: f"LINK_UP{k}" for k in range(7)}, 36: "LINK_UP7"}
    j5 = ["GND" if n in (1, 37, 38) or (n % 2 == 0 and 4 <= n <= 34) else link.get(n, nc)
          for n in range(1, 41)]
    parts.append(t6.header("J5", "Connector_Generic:Conn_02x20_Odd_Even", j5, 760.0, 600.0, flagged))

    rows = power(Parts("Slot1Parts"), net_of, list(GTL_REFS.values()), list(CB3T_REFS.values()), agtl)
    parts += pdn.draw(rows, PARTS, "Slot1Parts", 30.0, 455.0, flagged)
    with open(OUT / "pdn.csv", "w", newline="") as f:
        w = csv.DictWriter(f, pdn.CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)
    parts += t6.flags(flagged, 950.0, 678.0, -12.0)
    sch = OUT / f"{NAME}.kicad_sch"
    t6.write_sheet(sch, parts)

    pin_num = {n: {p["name"]: p["num"] for p in sym_pins(lib[n])} for n in big}
    nets = {k: set(v) for k, v in t6.export_nets(sch, OUT / f"{NAME}.net").items()}
    fails = []

    def need(net, *pins):
        got = nets.get(t6.esc(net), set())
        for p in pins:
            if p not in got:
                fails.append(f"{net}: missing {p[0]} {p[1]}")

    for r in pinsrows:
        sig, kind, ball, ct = r["signal"], r["kind"], r["ball"], r["contact"]
        if kind in ("addr", "data", "tx", "cmos"):
            ref = (GTL_REFS | CB3T_REFS)[r["chip"]]
            num = pin_num["SN74CB3T3245" if kind == "cmos" else "SN74GTL16612"]
            need(("TX_" if kind == "tx" else "") + sig, ("U1", ball), (ref, num["A" + r["channel"]]))
            need("S_" + sig, ("U2", ct), (ref, num["B" + r["channel"]]))
        elif kind == "rx":
            need("S_" + sig, ("U1", ball), ("U2", ct))
        elif kind == "link":
            need(sig, ("U1", ball), ("J5", str(next(n for n, s in link.items() if s == sig))))
        else:
            need(sig, ("U1", ball))
    need("BCLK", ("U1", "M9"), ("U2", next(p for p, r in contact_row.items() if r["signal"] == "BCLK")),
         ("U12", "1"))
    need("LINK_DCLK", ("U1", "M8"), ("J5", "21"))
    for chip, ref in GTL_REFS.items():
        need(f"CLK_{chip}", (ref, "55"), (ref, "30"))
        need("VREF_GTL", (ref, "35"))
    for func, pin in AS_PINS.items():
        ball = next(b for b, f in func_by.items() if f.split(",")[0] == func)
        need(as_net(func), ("U1", ball), ("U13", pin))
    need("VREF_3A", ("U1", "Y7"))
    for s in agtl:
        if not any(ref.startswith("RN") for ref, _ in nets.get(t6.esc("S_" + s), ())):
            fails.append(f"S_{s}: no 56 R termination")
    t6.audit_exit(fails)
    print(f"AUDIT OK: {len(pinsrows)} pins.csv nets, {len(agtl)} terminated contacts")
    t6.run_erc(sch, OUT / f"{NAME}.erc.json")
    t6.write_project(OUT, NAME, [
        ("Slot1Parts", "../lib/Slot1_Parts.kicad_sym", "C2 cartridge parts"),
        ("SocketFPGA", f"../../hw/lib/{fsym[0]}.kicad_sym", "FPGA"),
        ("SocketCPU", f"../../sockets/kicad/{csym[0]}.kicad_sym", "CPU")])
    print("PASS  C2 cartridge S6 (netlist audit + ERC)")


if __name__ == "__main__":
    main()
