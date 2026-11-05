#!/usr/bin/env python3
"""Task T6 (plan/interposers.md) for socket3-cyclonev: label-wired
schematic + netlist + audit + ERC, sharing the helpers of
gen_t6_schematic.py.

One sheet: FPGA symbol (one instance per bank unit), the PGA168 CPU symbol,
16 SN74CB3T3245 bus switches (A = FPGA net, B = S_<sig> socket net, single
3.3 V VCC, OE# = BUS_OE# from the VCORE-present detector of socket3_pdn.py:
open while the socket rail is down), pull resistors, the MT25QL01G AS x4
configuration flash (U4: bitstream + BIOS / UEFI / option ROM images,
plan/interposers.md Flash), the FPGA JTAG header, the 12 V barrel jack,
every instance with its footprint, and the power tree +
decoupling of socket3_pdn.py (power.md; also written to pdn.csv for
placement). S4 (VOLDET) is tied to VSS like on the Am5x86.

Every FPGA supply ball is checked against its Cyclone V band before the
sheet is written (gen_t6_schematic.cv_supply_errors).

Audit: every T5 signal's net holds its FPGA ball and its switch A pin; the
S_<signal> net holds the socket pin and the switch B pin of the channel
pins.csv names; each AS net joins its U1 ball and its U4 flash pin; every
resistor joins two nets that reach other pins; 23
socket VCC pins share S_VCC (board supply, only the detector divider: D1),
28 VSS + S4 on GND; every power-tree net reaches at least two pins.
"""
import csv
import pathlib
import re
import sys

import gen_t6_schematic as t6
import pdn
import socket3_pdn

ROOT = t6.ROOT
OUT = ROOT / "hw/socket3-cyclonev"
NAME = "socket3-cyclonev"
FCSV = ROOT / "FPGAlist/CycloneV_A9/pins/5ceba9_f484.csv"
FSYM = ROOT / "hw/lib/FPGA_CycloneV_5CEFA9_F484_FPGA.kicad_sym"
CPUSYM = ROOT / "sockets/kicad/CPU_Socket3_Am5x86.kicad_sym"
PARTS = ROOT / "hw/lib/Socket_Parts.kicad_sym"

VOLTS = {"VCC_1V1": 1.1, "VCC_AUX25": 2.5, "VCCA_FPLL25": 2.5, "V3V3": 3.3}

# AS x1/x4, standard POR: MSEL[4..0] = 10011, VCCPGM 3.0/3.3 V [cvhb p.7-3
# Table 7-2]; fast POR would need every supply ramp <= 4 ms [cvds p.9 Table 4]
MSEL = {"MSEL4": "V3V3", "MSEL3": "GND", "MSEL2": "GND", "MSEL1": "V3V3",
        "MSEL0": "V3V3"}
# dedicated AS balls (function column) -> flash nets
AS = {"nCSO": "AS_nCS", "DCLK": "AS_DCLK", "AS_DATA0,ASDO": "AS_DATA0",
      "AS_DATA1": "AS_DATA1", "AS_DATA2": "AS_DATA2", "AS_DATA3": "AS_DATA3"}
FLASH = {"S#": "AS_nCS", "C": "AS_DCLK", "DQ0": "AS_DATA0", "DQ1": "AS_DATA1",
         "DQ2": "AS_DATA2", "DQ3": "AS_DATA3", "RESET#": "V3V3", "VCC": "V3V3",
         "GND": "GND"}                     # RESET# unused: to VCC [cf52014 Table 8]
FP = {"U1": "Interposer:FPGA_CycloneV_5CEFA9_F484_BGA",
      "U2": "SocketBase:Socket3_Base_PGA168",          # sockets/kicad/Interposer.pretty
      "TR": "Package_SO:TSSOP-20_4.4x6.5mm_P0.65mm",
      "U4": "Package_SO:SOIC-16W_7.5x10.3mm_P1.27mm",
      "J1": "Connector_PinHeader_2.54mm:PinHeader_2x03_P2.54mm_Vertical",
      "J3": "Connector_BarrelJack:BarrelJack_CUI_PJ-063AH_Horizontal"}

# (value, net 1, net 2, source); pull-ups sit on the FPGA side so an open
# switch never feeds the socket rail (plan/interposers.md)
PULLS = [
    ("4k7", "S_HLDA", "GND", "socket3_notes R6"),
    ("4k7", "S_BREQ", "GND", "socket3_notes R6"),
    # FPGAmotherboard: RESET high-Z, held by 8.2k to VCORE during the ramp
    ("100k", "S_RESET", "GND", "socket3_notes R4 (C16, NM2)"),
    ("4k7", "HOLD", "GND", "socket3_notes R6 (FPGA side)"),
    ("10k", "UP#", "V3V3", "socket3_notes R4"),
    *[("10k", f"DP{k}", "V3V3", "socket3_notes R4, dx4 p.16")
      for k in range(4)],
    ("10k", "CFG_nSTATUS", "V3V3", "cvpcg p.5"),
    ("10k", "CFG_CONF_DONE", "V3V3", "cvpcg p.4"),
    ("10k", "CFG_nCONFIG", "V3V3", "cvpcg p.4"),
    ("10k", "AS_DCLK", "GND", "cvpcg p.7 (never floating)"),
    # DQ3 shares HOLD#: high in x1 / x2 commands [micron_mt25ql01gbbb Fig. 5 note 1]
    ("10k", "AS_DATA3", "V3V3", "micron_mt25ql01gbbb p.13"),
    ("1k", "F_TCK", "GND", "cvpcg p.6"),
    ("10k", "F_TMS", "V3V3", "cvpcg p.6"),
    ("10k", "F_TDI", "V3V3", "cvpcg p.7"),
    ("2k0 1%", "RREF_TL", "GND", "cvpcg p.16 (PLL used)"),
]


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
        return "V3V3"                        # every bank at 3.3 V (T5)
    return "NC_" + ball                      # NC, DNU, unused user I/O


def main():
    t1 = list(csv.DictReader(open(ROOT / "hw/common/socket3_signals.csv")))
    pinsrows = list(csv.DictReader(open(OUT / "pins.csv")))
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
    ssym = next(d for d in psyms if d[0] == "SN74CB3T3245")
    parts = t6.sheet_head(
        "gen_socket3_t6", "Socket 3 interposer: 5CEBA9 + 16x SN74CB3T3245",
        [("hw_n:" + fsym[0], fsym[1]), ("cpu_n:" + csym[0], csym[1]),
        ] + [("hw_n:" + d[0], d[1]) for d in psyms] + t6.stock_defs(
            [("Connector_Generic", ["Conn_02x03_Odd_Even"]),
             ("Connector", ["Barrel_Jack"]),
             ("Device", ["C", "R", "L", "Fuse", "FerriteBead"])]))
    flagged = set()

    # ---- FPGA units ----
    for i, uid in enumerate(sorted(fsym[2], key=int)):
        pins = fsym[2][uid]
        lab = {p["num"]: net_of[p["num"]] for p in pins}
        parts.append(t6.syminst("hw_n:" + fsym[0], "U1", 80.0 + i % 3 * 95.0,
                                35.0 + i // 3 * 62.0, int(uid), pins, lab, footprint=FP["U1"]))
        flagged |= {n for n in lab.values() if n in VOLTS}

    # ---- bus switches: chip/channel from pins.csv T<dd>c<n> ----
    chips = {}
    for r in pinsrows:
        if r["source"] == "board-local":
            continue
        m = re.fullmatch(r"T(\d+)c([1-8])", r["translator"])
        if not m:
            sys.exit(f"{r['signal']}: bad translator {r['translator']!r}")
        ch = chips.setdefault(int(m.group(1)), {})
        if m.group(2) in ch:
            sys.exit(f"{r['signal']}: channel {r['translator']} used twice")
        ch[m.group(2)] = r["signal"]
    if sorted(chips) != list(range(1, len(chips) + 1)):
        sys.exit(f"translator ids not contiguous: {sorted(chips)}")
    spins = ssym[2]["1"]
    pinnum = {p["name"]: p["num"] for p in spins}
    for cid, ch in sorted(chips.items()):
        ref = "TR%02d" % cid
        byname = {"VCC": "V3V3", "GND": "GND", "OE#": "BUS_OE#"}
        for n in range(1, 9):
            s = ch.get(str(n))
            byname[f"A{n}"] = s or f"NC_{ref}_A{n}"
            byname[f"B{n}"] = "S_" + s if s else f"NC_{ref}_B{n}"
        lab = {pinnum[k]: v for k, v in byname.items()}
        flagged |= t6.power_nets(spins, lab)
        parts.append(t6.syminst("hw_n:" + ssym[0], ref,
                                25.0 + (cid - 1) % 8 * 45.0,
                                260.0 + (cid - 1) // 8 * 75.0, 1, spins, lab, footprint=FP["TR"]))

    # ---- CPU socket ----
    row_of = {r["pin"]: r for r in t1}
    y, col = 25.0, 0
    for uid in sorted(csym[2], key=int):
        pins = csym[2][uid]
        lab = {}
        for p in pins:
            r = row_of[p["num"]]
            lab[p["num"]] = ("GND" if r["signal"] in ("VSS", "VOLDET") else
                             "S_VCC" if r["signal"] == "VCC" else
                             "NC_U2_" + p["num"] if r["class"] == "nc" else
                             "S_" + r["signal"])
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
    lab = {p["num"]: FLASH.get(p["name"], f"NC_U4_{p['num']}") for p in mpins}
    flagged |= t6.power_nets(mpins, lab)
    parts.append(t6.syminst("hw_n:MT25QL01G", "U4", 780.0, 110.0, 1, mpins, lab,
                            value="MT25QL01GBBB8ESF-0SIT", footprint=FP["U4"]))

    # ---- headers ----
    HD = [("J1", "Connector_Generic:Conn_02x03_Odd_Even",
           ["F_TCK", "GND", "F_TMS", "GND", "F_TDI", "F_TDO"]),
          ("J3", "Connector:Barrel_Jack", ["V12_IN", "GND"])]
    for k, (ref, nick, nets) in enumerate(HD):
        parts.append(t6.header(ref, nick, nets, 780.0, 150.0 + k * 40.0,
                               flagged, footprint=FP[ref]))

    # ---- power tree + decoupling ----
    pdn_rows = socket3_pdn.build(net_of, ["TR%02d" % c for c in sorted(chips)],
                                 {f"R{k}" for k in range(1, len(PULLS) + 1)}
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
        sig, ball, cpin = r["signal"], r["ball"], r["socket_pin"]
        if r["source"] == "board-local":
            if ("U1", ball) not in on(sig) or len(on(sig)) < 2:
                fails.append(f"{sig}: net lacks U1 {ball} or a driver")
            continue
        cid, n = re.fullmatch(r"T(\d+)c(\d)", r["translator"]).groups()
        ref = "TR%02d" % int(cid)
        if not {("U1", ball), (ref, pinnum["A" + n])} <= on(sig):
            fails.append(f"{sig}: net lacks U1 {ball} or {ref} A{n}")
        if not {("U2", cpin), (ref, pinnum["B" + n])} <= on("S_" + sig):
            fails.append(f"S_{sig}: net lacks U2 {cpin} or {ref} B{n}")
    if len({ref for ref, _ in on("BUS_OE#")} & {f"TR{c:02d}" for c in chips}) \
            != len(chips):
        fails.append("BUS_OE# does not reach every bus switch")
    as_ball = {AS[f]: b for b, f in func_by.items() if f in AS}
    flash_pin = {p["name"]: p["num"] for p in mpins}
    if len(as_ball) != len(AS):
        fails.append(f"AS balls found: {sorted(as_ball)}")
    for name, net in FLASH.items():
        if ("U4", flash_pin[name]) not in on(net) or \
                (net in as_ball and ("U1", as_ball[net]) not in on(net)):
            fails.append(f"{net}: lacks U4 {name} or its U1 AS ball")
    for k, (val, a, b, _src) in enumerate(PULLS, 1):
        for net, pin in ((a, "1"), (b, "2")):
            if (f"R{k}", pin) not in on(net) or len(on(net)) < 2:
                fails.append(f"R{k} {val}: pin {pin} net {net} reaches nothing")
    for sigs, net, count in ((("VCC",), "S_VCC", 23),
                             (("VSS", "VOLDET"), "GND", 29)):
        got = {p for ref, p in on(net) if ref == "U2"}
        want = {r["pin"] for r in t1 if r["signal"] in sigs}
        if got != want or len(want) != count:
            fails.append(f"{sigs}: {len(want)} pins, {net} has {len(got)}")
    for row in pdn_rows:
        for net in row["nets"].split("|"):
            if not net.startswith("NC_") and len(on(net)) < 2:
                fails.append(f"{row['ref']}: net {net} reaches one pin")
    t6.audit_exit(fails)
    print(f"AUDIT OK: {len(pinsrows)} signals via {len(chips)} SN74CB3T3245,"
          f" {len(PULLS)} resistors, VCC/VSS, {len(pdn_rows)} power parts")

    t6.run_erc(schpath, OUT / f"{NAME}.erc.json")
    print("PASS  T6 checks (supply bands + netlist audit + ERC)")
    t6.write_project(OUT, NAME, [
        ("SocketParts", "../lib/Socket_Parts.kicad_sym", "Bus switch, power"),
        ("SocketFPGA", f"../lib/{fsym[0]}.kicad_sym", "FPGA"),
        ("SocketCPU", f"../../sockets/kicad/{csym[0]}.kicad_sym", "CPU")])


if __name__ == "__main__":
    main()
