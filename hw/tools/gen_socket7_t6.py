#!/usr/bin/env python3
"""Task T6 (plan/interposers.md) for socket7-cyclonev: label-wired
schematic + netlist + audit + ERC, sharing the helpers of
gen_t6_schematic.py.

One sheet: FPGA symbol (one instance per bank unit), the Socket 7 CPU
symbol, pull resistors, the MT25QL01G AS x4 configuration flash (as
socket 3: gen_socket3_t6.py), the FPGA JTAG header, every instance with its
footprint. The bus is 3.3 V TTL [socket7_notes R1], so every signal is one
net from its FPGA ball to its socket pin (no translators, T5). Power comes
from the socket (D1): the power tree + decoupling of socket7_pdn.py (also
written to pdn.csv for placement): VCC2 feeds the core buck, VCC3 (3.4 V
on this board, power.md) reaches VCCIO/VCCPD/VCCPGM as VCCIO33 through a
load switch enabled by the core PGOOD (power.md Sequencing).

Every FPGA supply ball is checked against its Cyclone V band before the
sheet is written (gen_t6_schematic.cv_supply_errors).

Audit: every T5 signal's net holds its FPGA ball and its socket pin;
each AS net joins its U1 ball and its U4 flash pin; every resistor joins
two nets that reach other pins; 25 VCC2 pins on S_VCC2, 28 VCC3 pins on
S_VCC3, 53 VSS on GND; every power-tree net reaches at least two pins.
"""
import csv
import pathlib
import sys

import gen_t6_schematic as t6
import pdn
import socket7_pdn
from gen_socket3_t6 import AS, FLASH, PARTS

ROOT = t6.ROOT
OUT = ROOT / "hw/socket7-cyclonev"
NAME = "socket7-cyclonev"
FCSV = ROOT / "FPGAlist/CycloneV_A9/pins/5ceba9_f484.csv"
FSYM = ROOT / "hw/lib/FPGA_CycloneV_5CEFA9_F484_FPGA.kicad_sym"
CPUSYM = ROOT / "sockets/kicad/CPU_Intel_Socket7.kicad_sym"

# VCCIO33 = switched S_VCC3: the board's 3.4 V [spec p.5] is inside the
# 3.135-3.465 V VCCIO band [cvds p.8-9 Table 4]
VOLTS = {"VCC_1V1": 1.1, "VCC_AUX25": 2.5, "VCCA_FPLL25": 2.5, "VCCIO33": 3.3}

# AS x1/x4, standard POR: MSEL[4..0] = 10011 [cvhb p.7-3 Table 7-2]
MSEL = {"MSEL4": "VCCIO33", "MSEL3": "GND", "MSEL2": "GND", "MSEL1": "VCCIO33",
        "MSEL0": "VCCIO33"}
FLASH7 = {k: "VCCIO33" if v == "V3V3" else v for k, v in FLASH.items()}
FP = {"U1": "Interposer:FPGA_CycloneV_5CEFA9_F484_BGA",
      "U2": "SocketBase:Socket7_Base_PGA296",           # sockets/kicad/Interposer.pretty
      "U4": "Package_SO:SOIC-16W_7.5x10.3mm_P1.27mm",
      "J1": "Connector_PinHeader_2.54mm:PinHeader_2x03_P2.54mm_Vertical"}

# (value, net 1, net 2, source); socket nets = FPGA nets (direct bus)
PULLS = [
    *[("4k7", s, "GND", "socket7_notes R6 (active-high output)")
      for s in ("BREQ", "SCYC", "PM0/BP0", "PM1/BP1", "BP2", "BP3")],
    ("4k7", "A27", "GND", "socket7_notes R4/R6 (refresh strap at RESET)"),
    ("10k", "CFG_nSTATUS", "VCCIO33", "cvpcg p.5"),
    ("10k", "CFG_CONF_DONE", "VCCIO33", "cvpcg p.4"),
    ("10k", "CFG_nCONFIG", "VCCIO33", "cvpcg p.4"),
    ("10k", "AS_DCLK", "GND", "cvpcg p.7 (never floating)"),
    ("10k", "AS_DATA3", "VCCIO33", "micron_mt25ql01gbbb p.13"),
    ("1k", "F_TCK", "GND", "cvpcg p.6"),
    ("10k", "F_TMS", "VCCIO33", "cvpcg p.6"),
    ("10k", "F_TDI", "VCCIO33", "cvpcg p.7"),
    ("2k0 1%", "RREF_TL", "GND", "cvpcg p.16 (PLL used)"),
]
SOCKET_RAIL = {"VCC2": "S_VCC2", "VCC3": "S_VCC3", "VSS": "GND"}


def fpga_net(ball, func, conf):
    """net for an FPGA ball not carrying a T5 signal"""
    if func in ("TCK", "TMS", "TDI", "TDO"):
        return "F_" + func
    if func in MSEL:
        return MSEL[func]
    if func in AS:
        return AS[func]
    if func == "nCE":
        return "GND"                         # single device [cvpcg p.4]
    if conf:
        return "CFG_" + conf
    if func == "RREF_TL":
        return "RREF_TL"
    if func.startswith("VREFB"):
        return "GND"                         # unused VREF [cvpcg p.19]
    if func == "GND":
        return "GND"
    if func == "VCC":
        return "VCC_1V1"
    if func in ("VCC_AUX", "VCCBAT"):
        return "VCC_AUX25"
    if func == "VCCA_FPLL":
        return "VCCA_FPLL25"
    if func.startswith(("VCCIO", "VCCPD", "VCCPGM")):
        return "VCCIO33"                     # every bank at 3.3 V (T5)
    return "NC_" + ball                      # NC, DNU, unused user I/O


def main():
    t1 = list(csv.DictReader(open(ROOT / "hw/common/socket7_signals.csv")))
    pinsrows = list(csv.DictReader(open(OUT / "pins.csv")))
    bad = [r["signal"] for r in pinsrows if r["translator"]]
    if bad:
        sys.exit(f"translator on a direct 3.3 V bus: {bad}")
    sig_of_ball = {r["ball"]: r["signal"] for r in pinsrows}
    frows = list(csv.DictReader(open(FCSV)))
    func_by = {r["ball"]: r["function"] for r in frows}
    net_of = {r["ball"]: sig_of_ball.get(r["ball"])
              or fpga_net(r["ball"], r["function"], r["config"])
              for r in frows}
    errs = t6.cv_supply_errors(func_by, net_of, VOLTS)
    if errs:
        print(f"SUPPLY ERRORS ({len(errs)}):", *errs, sep="\n   ")
        sys.exit(1)

    fsym = t6.parse_lib(FSYM)[0]
    csym = t6.parse_lib(CPUSYM)[0]
    psyms = t6.parse_lib(PARTS)
    parts = t6.sheet_head(
        "gen_socket7_t6", "Socket 7 interposer: 5CEBA9, direct 3.3 V bus",
        [("hw_n:" + fsym[0], fsym[1]), ("cpu_n:" + csym[0], csym[1])]
        + [("hw_n:" + d[0], d[1]) for d in psyms] + t6.stock_defs(
            [("Connector_Generic", ["Conn_02x03_Odd_Even"]),
             ("Device", ["C", "R", "L", "FerriteBead"])]))
    flagged = {"S_VCC2", "S_VCC3", "GND"}    # the board VRM feeds the socket

    # ---- FPGA units ----
    for i, uid in enumerate(sorted(fsym[2], key=int)):
        pins = fsym[2][uid]
        lab = {p["num"]: net_of[p["num"]] for p in pins}
        parts.append(t6.syminst("hw_n:" + fsym[0], "U1", 80.0 + i % 3 * 95.0,
                                35.0 + i // 3 * 62.0, int(uid), pins, lab, footprint=FP["U1"]))
        flagged |= {n for n in lab.values() if n in VOLTS}

    # ---- CPU socket ----
    row_of = {r["pin"]: r for r in t1}
    sig_of_pin = {r["socket_pin"]: r["signal"] for r in pinsrows}
    y, col = 25.0, 0
    for uid in sorted(csym[2], key=int):
        pins = csym[2][uid]
        lab = {}
        for p in pins:
            net = (sig_of_pin.get(p["num"])
                   or SOCKET_RAIL.get(row_of[p["num"]]["signal"]))
            # pins the interposer leaves open (UP: NC, socket7_notes R4)
            lab[p["num"]] = net or t6.NOCONNECT
        ys = [p["y"] for p in pins]
        if y + max(ys) - min(ys) > 800.0:
            y, col = 25.0, col + 1
        parts.append(t6.syminst("cpu_n:" + csym[0], "U2", 480.0 + col * 120.0,
                                y + max(ys) + 8.0, int(uid), pins, lab, footprint=FP["U2"]))
        y += max(ys) - min(ys) + 22.0

    # ---- pull resistors ----
    rpins = next(d for d in t6.parse_lib(pathlib.Path(
        t6.STOCK + "Device.kicad_sym")) if d[0] == "R")[2]["1"]
    for k, (val, a, b, _src) in enumerate(PULLS, 1):
        parts.append(t6.syminst("Device:R", f"R{k}", 760.0 + (k - 1) % 10 * 20.0,
                                40.0 + (k - 1) // 10 * 25.0, 1, rpins,
                                {"1": a, "2": b}, value=val,
                                footprint="Resistor_SMD:R_0402_1005Metric"))

    # ---- configuration flash ----
    msym = next(d for d in psyms if d[0] == "MT25QL01G")
    mpins = msym[2]["1"]
    lab = {p["num"]: FLASH7.get(p["name"], f"NC_U4_{p['num']}") for p in mpins}
    flagged |= t6.power_nets(mpins, lab)
    parts.append(t6.syminst("hw_n:MT25QL01G", "U4", 780.0, 110.0, 1, mpins, lab,
                            value="MT25QL01GBBB8ESF-0SIT", footprint=FP["U4"]))

    # ---- JTAG header ----
    parts.append(t6.header("J1", "Connector_Generic:Conn_02x03_Odd_Even",
                           ["F_TCK", "GND", "F_TMS", "GND", "F_TDI", "F_TDO"],
                           780.0, 150.0, flagged, footprint=FP["J1"]))

    # ---- power tree + decoupling ----
    pdn_rows = socket7_pdn.build(net_of, {f"R{k}" for k in range(1, len(PULLS) + 1)}
                                 | {"U1", "U2", "U4"})
    parts += pdn.draw(pdn_rows, PARTS, "SocketParts", 30.0, 440.0, flagged)
    with open(OUT / "pdn.csv", "w", newline="") as f:
        w = csv.DictWriter(f, pdn.CSV_FIELDS)
        w.writeheader()
        w.writerows(pdn_rows)
    parts += t6.flags(flagged, 980.0, 150.0, 12.0)

    schpath = OUT / f"{NAME}.kicad_sch"
    t6.write_sheet(schpath, parts)

    # ---- netlist audit ----
    exported = t6.export_nets(schpath, OUT / f"{NAME}.net")

    def on(net):
        return set(exported.get(t6.esc(net), ()))
    fails = []
    for r in pinsrows:
        if not {("U1", r["ball"]), ("U2", r["socket_pin"])} <= on(r["signal"]):
            fails.append(f"{r['signal']}: net lacks U1 {r['ball']} or "
                         f"U2 {r['socket_pin']}")
    as_ball = {AS[f]: b for b, f in func_by.items() if f in AS}
    flash_pin = {p["name"]: p["num"] for p in mpins}
    if len(as_ball) != len(AS):
        fails.append(f"AS balls found: {sorted(as_ball)}")
    for name, net in FLASH7.items():
        if ("U4", flash_pin[name]) not in on(net) or \
                (net in as_ball and ("U1", as_ball[net]) not in on(net)):
            fails.append(f"{net}: lacks U4 {name} or its U1 AS ball")
    for k, (val, a, b, _src) in enumerate(PULLS, 1):
        for net, pin in ((a, "1"), (b, "2")):
            if (f"R{k}", pin) not in on(net) or len(on(net)) < 2:
                fails.append(f"R{k} {val}: pin {pin} net {net} reaches nothing")
    for sig, count in (("VCC2", 25), ("VCC3", 28), ("VSS", 53)):
        got = {p for ref, p in on(SOCKET_RAIL[sig]) if ref == "U2"}
        want = {r["pin"] for r in t1 if r["signal"] == sig}
        if got != want or len(want) != count:
            fails.append(f"{sig}: {len(want)} pins, {SOCKET_RAIL[sig]} "
                         f"has {len(got)}")
    for row in pdn_rows:
        for net in row["nets"].split("|"):
            if not net.startswith("NC_") and len(on(net)) < 2:
                fails.append(f"{row['ref']}: net {net} reaches one pin")
    t6.audit_exit(fails)
    print(f"AUDIT OK: {len(pinsrows)} signals direct, {len(PULLS)} resistors,"
          f" VCC2/VCC3/VSS, AS flash, {len(pdn_rows)} power parts")

    t6.run_erc(schpath, OUT / f"{NAME}.erc.json")
    print("PASS  T6 checks (supply bands + netlist audit + ERC)")
    t6.write_project(OUT, NAME, [
        ("SocketParts", "../lib/Socket_Parts.kicad_sym", "Bus switch, power"),
        ("SocketFPGA", f"../lib/{fsym[0]}.kicad_sym", "FPGA"),
        ("SocketCPU", f"../../sockets/kicad/{csym[0]}.kicad_sym", "CPU")])


if __name__ == "__main__":
    main()
