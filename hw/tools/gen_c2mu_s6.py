#!/usr/bin/env python3
"""Slot 1 C2 Mu cartridge (plan/slot1_c2.md D39/D40): label-wired schematic +
netlist, the S6 step of gen_c2cart_s6.py for this board.

Usage: python3 hw/tools/gen_c2mu_s6.py
Input: hw/slot1-c2mu/pins.csv (gen_c2mu_assign.py).
Output in hw/slot1-c2mu/: slot1-c2mu.kicad_sch, .net, .erc.json, pdn.csv
(every passive + regulator for the placement step), project.

Parts: U1 XC7A100T-2FGG484I; U2 the SC242 contacts; U3-U9 SN74GTL16612 and
U10 CY2309 as on the D33 board (gen_c2cart_s6); J4 the LattePanda Mu on a
LOTES ADDR0110 SO-DIMM 260 9.2H socket. Mu HSIO8-11 = PCIe lanes 0-3, 0.22 uF
in both directions (an on-board endpoint), REFCLK2 AC-coupled into
MGTREFCLK1 (the GTP input wants it); each capacitor joins the ball and the Mu
pin c2mu_pcie.LINKS pairs (its pair template: P / N swapped where the routing
needs it, polarity inversion [design_guide_pcie]), PLT_RST# -> PCIE_PERST#; PWRBTN# /
RSTBTN# pulled by NMOS from the FPGA (and SW1); PSON (S0) to the FPGA; CPU fan
J5 as on the Lite carrier; cabled CR2032 on J8, 1k into VBAT; USB2 ports 1 and 3 on
J6 (the 9-pin motherboard USB header: a bracket cable gives two USB-A),
port 2 to U16 FT232H (MPSSE JTAG: the Mu programs the FPGA and its flash
itself), UART0 on J7. U11 SPI x4 flash (master SPI, M[2:0] 001), U12 50 MHz
oscillator (link clock). Power: 12 V jack -> fuse -> Mu VIN and PS1 5 V
(16612 VCC5, fan, USB) -> PS2 1.0 V VCCINT/VCCBRAM -> PS3 1.8 V (VCCAUX,
VCCO 15, VCCADC; PG) -> PS4 3.3 V; TPS74801 LDOs from 1.8 V (bias 5 V; the
TLV757P class needs VIN >= 2.4 V at these outputs): U13 1.0 V MGTAVCC, U14
1.2 V MGTAVTT; order VCCINT -> VCCAUX -> VCCO [DS181], MGTAVTT may rise with
MGTAVCC (higher MGTAVTT current while ramping only [DS181]). Decoupling per
UG483 Table 2-2 (XC7A100T FGG484).
Audit (exit 1): every pins.csv net at its ball, chip pins and contact; PCIe
lane caps; supplies of every U1 power ball; ERC 0.
"""
import csv
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import c2mu_pcie
import gen_t6_schematic as t6
import pdn
from pdn import C0402, C0603, C0805, C1206, C1210, CPAIR, R0402, Parts, buck54620, buck62130, farads, u1_pairs
from gen_c2cart_s6 import CPUSYM, FP, GTL_REFS, PARTS, ZDB_OUT, by_name, contact_net, sym_pins

ROOT = t6.ROOT
NAME = "slot1-c2mu"
OUT = ROOT / "hw" / NAME
FSYM = ROOT / "hw/lib/FPGA_Artix7_XC7A100T_FGG484_FPGA.kicad_sym"
FCSV = ROOT / "FPGAlist/c2_cards/xilinx/xc7a100t_fgg484.csv"
MUSYM = ROOT / "hw/lib/LattePanda_Mu_SODIMM260.kicad_sym"     # gen_mu_lib.py
pdn.U1_FP = ROOT / "hw/lib/Interposer.pretty/FPGA_Artix7_XC7A100T_FGG484_BGA.kicad_mod"

VOLTS = {"VCC_1V0": 1.0, "VCC_1V8": 1.8, "VCC_3V3": 3.3, "VCC_MGT10": 1.0, "VCC_MGT12": 1.2}
SUPPLY = {                              # U1 supply function -> (net, DS181 Table 2 recommended band)
    "VCCINT": ("VCC_1V0", (0.95, 1.05)), "VCCBRAM": ("VCC_1V0", (0.95, 1.05)),
    "VCCAUX": ("VCC_1V8", (1.71, 1.89)), "VCCADC_0": ("VCC_1V8", (1.71, 1.89)),
    "MGTAVCC": ("VCC_MGT10", (0.97, 1.03)), "MGTAVTT": ("VCC_MGT12", (1.17, 1.23)),
    "VCCO_15": ("VCC_1V8", (1.71, 1.89)),
    **{f"VCCO_{b}": ("VCC_3V3", (3.135, 3.465)) for b in ("0", "13", "14", "16", "34", "35")},
}
CONFIG = {"CFGBVS_0": "VCC_3V3", "M0_0": "VCC_3V3", "M1_0": "GND", "M2_0": "GND",   # master SPI [UG470 T2-2]
          "PROGRAM_B_0": "CFG_PROGRAM_B", "INIT_B_0": "CFG_INIT_B", "DONE_0": "CFG_DONE",
          "CCLK_0": "SPI_CLK", "TCK_0": "F_TCK", "TMS_0": "F_TMS", "TDI_0": "F_TDI", "TDO_0": "F_TDO",
          "VCCBATT_0": "GND", "GNDADC_0": "GND", "VREFP_0": "GND", "VREFN_0": "GND",   # XADC unused [UG480]
          "VP_0": "GND", "VN_0": "GND", "DXP_0": "GND", "DXN_0": "GND", "MGTRREF_216": "MGT_RREF"}
SMALL = {                               # UG483 Table 2-2, XC7A100T FGG484: 0.47 uF under U1
    "VCC_1V0": ["470nF"] * 10, "VCC_1V8": ["470nF"] * 9, "VCC_3V3": ["470nF"] * 12,
    "VCC_MGT10": ["100nF"] * 5, "VCC_MGT12": ["100nF"] * 6,
}
# the UG483 330 uF tantalum would take PS2 past its stable 400 uF [slva463a Table 1]: a second 100 uF
# ceramic instead, lower impedance from 100 kHz to 10 MHz (UG483 p.13 allows any network that low)
BULK = ([("VCC_1V0", "100uF/6.3V", C1210)] * 2 + [("VCC_1V0", "4.7uF", C0603)] * 6
        + [("VCC_1V8", "47uF/6.3V", C1210)] * 2 + [("VCC_1V8", "4.7uF", C0603)] * 5
        + [("VCC_3V3", "47uF/6.3V", C1210)] * 4 + [("VCC_3V3", "4.7uF", C0603)] * 8
        + [("VCC_MGT10", "4.7uF", C0603), ("VCC_MGT12", "4.7uF", C0603)])
MU_FP = "Slot1:LattePanda_Mu_LOTES_ADDR0110_9.2H"
MU_FPS = {"TPS74801": "Package_SON:VSON-10-1EP_3x3mm_P0.5mm_EP1.65x2.4mm"}
STOCK_SYMS = [("Connector_Generic", ["Conn_02x05_Odd_Even", "Conn_02x07_Odd_Even", "Conn_01x02", "Conn_01x03", "Conn_01x04"]),
              ("Connector", ["Barrel_Jack"]),
              ("Device", ["C", "R", "R_Pack04", "L", "Fuse", "FerriteBead", "Polyfuse", "LED", 
                          "Crystal_GND24", "D_Schottky", "C_Polarized"]),
              ("Transistor_FET", ["Q_NMOS_GSD"]), ("Mechanical", ["MountingHole_Pad"]), ("Switch", ["SW_Push"]),
              ("Memory_Flash", ["W25Q32JVSS"]), ("Oscillator", ["ASE-xxxMHz"]),
              ("Power_Protection", ["USBLC6-2P6"]),
              ("Interface_USB", ["FT232H"])]


def fpga_net(ball, func):
    """net of a U1 ball pins.csv does not assign"""
    if func == "GND" or func in CONFIG or func in SUPPLY:
        return {"GND": "GND", **CONFIG}.get(func) or SUPPLY[func][0]
    if "PUDC_B" in func:
        return "PUDC_B"                  # high: no pull-ups while configuring
    return "NC_" + ball                  # unused IO, MGTREFCLK0, NC


def mu_nets():
    """Mu edge signal (edge_pinout.csv) -> net; signals not listed: no connect"""
    nets = {"VIN": "V12", "GND": "GND", "REFCLK2_P": "MU_REFCLK_P", "REFCLK2_N": "MU_REFCLK_N",
            "PLT_RST#": "PCIE_PERST#", "PWR_SW#": "MU_PWRBTN#", "RST_SW#": "MU_RSTBTN#", "PSON": "MU_PSON",
            "FAN2_CTL": "MU_FAN_PWM", "FAN2_TAC": "MU_FAN_TAC", "VBAT": "MU_VBAT",
            "USB2_P1_N": "USB1_N", "USB2_P1_P": "USB1_P", "USB2_P2_N": "USB2_N", "USB2_P2_P": "USB2_P",
            "USB2_P3_N": "USB3_N", "USB2_P3_P": "USB3_P",
            "UART0_RXD": "MU_UART_RX", "UART0_TXD": "MU_UART_TX"}
    for k in range(4):                   # HSIO 8+k = lane k
        nets |= {f"HSIO{8 + k}_{d}_{s}": f"MU_{d}{k}_{s}" for d in ("TX", "RX") for s in "PN"}
    return nets


def stock_ic(lib, name, ref, X, Y, names, parts, flagged, footprint, value=None):
    d = next(d for d in t6.parse_lib(pathlib.Path(t6.STOCK + lib + ".kicad_sym")) if d[0] == name)
    pins = sym_pins(d)
    lab = by_name(pins, names) if not all(k.isdigit() for k in names) else {p["num"]: names[p["num"]] for p in pins}
    flagged.update(t6.power_nets(pins, lab))
    parts.append(t6.syminst(f"{lib}:{name}", ref, X, Y, 1, pins, lab, value=value, footprint=footprint))


def power(P, net_of_ball, agtl, mu_pin_net):
    """power tree, decoupling, terminations, PCIe caps, pull-ups: pdn.py rows"""
    P.add("F", "Device:Fuse", "5A", "Fuse:Fuse_1812_4532Metric", ["V12_IN", "V12"], "stage", "F1")
    # hot-plug damping on the jack (ceramics alone ring past the TPS54620 17 V max) + Mu VIN bulk
    P.add("C", "Device:C_Polarized", "100uF/25V", "Capacitor_SMD:CP_Elec_6.3x5.4", ["V12", "GND"], "stage", "J3")
    P.c("10uF/25V", C1210, "V12", "stage", "J4")
    # 5 V: 7 x 16612 ICC5 120 mA [ti_sn74gtl16612 p.6], fan 0.35 A, USB 0.5 A, the 1.0/1.8/3.3 V stages
    buck54620(P, "PS1", ("V12", 12.0), "V5", 5.0, 3.0,
              (2, "22uF/10V", 22e-6), None, "PG_5V", 6.8e-6, "FXL1040-6R8", 0.25)
    buck62130(P, "PS2", "VCC_1V0", 1.0, (0.97, 1.03), "PG_5V", "PG_1V0")    # VCCINT 0.15 A [Vivado power]
    buck62130(P, "PS3", "VCC_1V8", 1.8, (1.71, 1.89), "PG_1V0", "PG_1V8")
    buck62130(P, "PS4", "VCC_3V3", 3.3, (3.135, 3.465), "PG_1V8", None)
    pairs = u1_pairs(net_of_ball, SMALL)
    for rail, caps in SMALL.items():
        mine = pairs.get(rail, [])
        for k, v in enumerate(sorted(caps, key=farads)):
            if k < len(mine):
                P.c(v, CPAIR, rail, "u1pair", *mine[k], side="B")
            else:
                P.c(v, C0402, rail, "u1bulk")
        print(f"  U1 {rail}: {min(len(mine), len(caps))}/{len(caps)} on B.Cu via pairs")
    for rail, v, f in BULK:
        P.c(v, f, rail, "u1bulk")
    for ref in GTL_REFS.values():                 # 0.1 uF per supply / VREF pin
        for pin, net in (("7", "VCC_3V3"), ("22", "VCC_3V3"), ("50", "V5"), ("35", "VREF_GTL")):
            P.c("100nF", C0402, net, "pin", ref, pin)
    for pin in ("4", "13"):
        P.c("100nF", C0402, "VCC_3V3", "pin", "U10", pin)
    for ref, pin in (("U11", "8"), ("U12", "4")):
        P.c("100nF", C0402, "VCC_3V3", "pin", ref, pin)
    # TPS74801 [ti_tps74801 Table 7-1]: VOUT = 0.8 (1 + R1/R2), R2 <= 4.99k; CSS 1 nF ~ 1.8 ms
    for ref, out, r1, r2 in (("U13", "VCC_MGT10", "1.13k", "4.53k"), ("U14", "VCC_MGT12", "2.49k", "4.99k")):
        P.c("1uF", C0402, "VCC_1V8", "pin", ref, "1")
        P.c("1uF", C0402, "V5", "pin", ref, "4")
        P.c("2.2uF", C0402, out, "pin", ref, "9")
        P.add("R", "Device:R", r1 + " 1%", R0402, [out, f"{ref}_FB"], "pin", ref, "8")
        P.add("R", "Device:R", r2 + " 1%", R0402, [f"{ref}_FB", "GND"], "pin", ref, "8")
        P.add("C", "Device:C", "1nF", C0402, [f"{ref}_SS", "GND"], "pin", ref, "7")
    for pin in ("12", "24", "46", "39", "40"):     # FT232H 3.3 V pins
        P.c("100nF", C0402, "VCC_3V3", "pin", "U16", pin)
    # VPHY / VPLL through a ferrite (LC filter recommended [ftdi_ft232h Table 3.1])
    P.add("FB", "Device:FerriteBead", "600R@100MHz", "Inductor_SMD:L_0603_1608Metric",
          ["VCC_3V3", "FT_VPHY"], "pin", "U16", "3")
    for pin in ("3", "8"):
        P.c("100nF", C0402, "FT_VPHY", "pin", "U16", pin)
    P.c("4.7uF", C0603, "FT_VPHY", "pin", "U16", "3")
    P.c("100nF", C0402, "FT_VCORE", "pin", "U16", "38")
    P.c("100nF", C0402, "FT_VCCA", "pin", "U16", "37")
    P.c("4.7uF", C0603, "VCC_3V3", "pin", "U16", "40")

    # GTL+: VREF 2/3 VTT for the 16612s; 56 R processor-end terminations [p2 Table 8]
    P.r("1.00k", "VTT15", "VREF_GTL", "vref")
    P.r("2.00k", "VREF_GTL", "GND", "vref")
    for k in range(0, len(agtl), 4):
        sigs = [f"S_{s}" for s in agtl[k:k + 4]]
        sigs += [f"NC_RN{k // 4 + 1}_{n}" for n in range(len(sigs) + 1, 5)]
        P.add("RN", "Device:R_Pack04", "56R", "Resistor_SMD:R_Array_Convex_4x0402", sigs + ["VTT15"] * 4, "term")
    P.c("22uF", C0805, "VTT15", "term")
    P.c("22uF", C0805, "VTT15", "term")
    for _ in range(6):
        P.c("100nF", C0402, "VTT15", "term")
    P.r("1k", "VTT15", "VTT_SENSE", "vref", "U1")         # board powered -> bank 15 input
    for s in ("VID1", "VID2", "VID3", "VID4"):
        P.r("0R", f"S_{s}", "GND", "strap", "U2")
    for oe in ("ADDR_OEAB#", "ADDR_OEBA#", "DATA_OEAB#", "DATA_OEBA#", "TX_OEAB#"):
        P.r("10k", oe, "VCC_3V3", "pullup")             # transceivers off while the FPGA configures
    for chip in ZDB_OUT:
        P.r("22R", f"ZCLK_{chip}", f"CLK_{chip}", "clk", "U10")
    P.r("22R", "ZCLK_FB", "CLK_FB", "clk", "U10")
    P.add("C", "Device:C", "10pF", C0402, ["CLK_FB", "GND"], "clk", "U10")

    # configuration [UG470]: PROGRAM_B / INIT_B 4.7k, DONE 330 R, PUDC_B high, SPI CS pull-up
    P.r("4.7k", "CFG_PROGRAM_B", "VCC_3V3", "pullup", "U1")
    P.r("4.7k", "CFG_INIT_B", "VCC_3V3", "pullup", "U1")
    P.r("330R", "CFG_DONE", "VCC_3V3", "pullup", "U1")
    P.r("1k", "PUDC_B", "VCC_3V3", "pullup", "U1")
    P.r("4.7k", "SPI_CS#", "VCC_3V3", "pullup", "U11")
    P.add("R", "Device:R", "100R 1%", R0402, ["MGT_RREF", "VCC_MGT12"], "pullup", "U1")   # [UG482]
    P.r("10k", "F_TMS", "VCC_3V3", "pullup", "U1")
    P.r("10k", "F_TDI", "VCC_3V3", "pullup", "U1")
    P.r("4.7k", "F_TCK", "GND", "pullup", "U1")

    # PCIe: AC coupling on both directions (on-board endpoint) [design_guide_pcie]; REFCLK into the GTP;
    # pad 1 on the FPGA side, ball and pin as the pair template routes them
    for ball, pin in c2mu_pcie.LINKS:
        value = "100nF" if "REFCLK" in net_of_ball[ball] else "220nF"
        P.add("C", "Device:C", value, C0402, [net_of_ball[ball], mu_pin_net[pin]], "pcie", "U1", ball)
    P.r("10k", "PCIE_PERST#", "VCC_3V3", "pullup", "U1")

    # Mu power / reset buttons: NMOS gates from the FPGA, 100k down while it configures
    P.r("100k", "MU_PWR_ON", "GND", "mu", "Q1")
    P.r("100k", "MU_RST", "GND", "mu", "Q2")
    # CPU fan [Lite carrier fan_temp sheet]: PWM 100 R; TAC 21.5k, 4.7k to 5 V, Schottky clamp
    P.r("100R", "MU_FAN_PWM", "FAN_PWM", "mu", "J5")
    P.r("21.5k", "FAN_TAC", "MU_FAN_TAC", "mu", "J5")
    P.r("4.7k", "FAN_TAC", "V5", "mu", "J5")
    P.c("100nF", C0402, "V5", "mu", "J5")
    P.r("1k", "RTC_CELL", "MU_VBAT", "mu", "J8")         # cabled CR2032 [Lite carrier: BT1 -> R1 1k -> VBAT]
    P.r("330R", "LED_A", "LED", "mu", "D1")
    P.c("10uF", C0805, "USB_VBUS", "mu", "J6")
    # FT232H [ds_ft232h]: REF 12k 1 %, 12 MHz crystal 2 x 27 pF, RESET# up, EEPROM absent
    P.add("R", "Device:R", "12k 1%", R0402, ["FT_REF", "GND"], "mu", "U16")
    P.add("C", "Device:C", "27pF", C0402, ["FT_XI", "GND"], "mu", "Y1")
    P.add("C", "Device:C", "27pF", C0402, ["FT_XO", "GND"], "mu", "Y1")
    P.r("10k", "FT_RESET#", "VCC_3V3", "mu", "U16")
    P.r("10k", "FT_EEDATA", "VCC_3V3", "mu", "U16")
    for n, m in (("FT_TCK", "F_TCK"), ("FT_TDI", "F_TDI"), ("FT_TMS", "F_TMS"), ("F_TDO", "FT_TDO")):
        P.r("33R", n, m, "mu", "U16")
    return P.done()


def main():
    sig_rows = list(csv.DictReader(open(ROOT / "hw/common/slot1_signals.csv")))
    contact_row = {r["pin"]: r for r in sig_rows}
    pinsrows = list(csv.DictReader(open(OUT / "pins.csv")))
    func_by = {r["ball"]: r["function"] for r in csv.DictReader(open(FCSV))}
    ball_net = {r["ball"]: {"tx": "TX_", "rx": "S_", "cmos": "S_"}.get(r["kind"], "") + r["signal"]
                for r in pinsrows}
    ball_net = {b: ("BCLK" if n == "BCLK" else "S_VTT_SENSE" if n == "S_VTT_SENSE" else n)
                for b, n in ball_net.items()}
    ball_net = {b: ("VTT_SENSE" if n == "S_VTT_SENSE" else n) for b, n in ball_net.items()}
    net_of = {b: ball_net.get(b) or fpga_net(b, f) for b, f in func_by.items()}
    errs = []
    for b, f in func_by.items():
        if f in SUPPLY:
            lo, hi = SUPPLY[f][1]
            if not lo <= VOLTS.get(net_of[b], 0) <= hi:
                errs.append(f"{b} {f} on {net_of[b]}")
        elif re.match(r"(VCC|MGTAV)", f) and f not in CONFIG:
            errs.append(f"{b} {f}: no supply rule")
    if errs:
        print(f"SUPPLY ERRORS ({len(errs)}):", *errs, sep="\n   ")
        sys.exit(1)
    used = {r["signal"] for r in pinsrows if r["contact"]}
    pin_of = {}
    for r in sig_rows:
        pin_of.setdefault(r["signal"], r["pin"])
    agtl = sorted({r["signal"] for r in sig_rows if r["standard"] == "AGTL+" and r["signal"] != "RESET#"},
                  key=lambda s: (int(pin_of[s][1:]), pin_of[s][0]))

    lib = {d[0]: d for d in t6.parse_lib(PARTS)}
    fsym, csym = t6.parse_lib(FSYM)[0], t6.parse_lib(CPUSYM)[0]
    musym = t6.parse_lib(MUSYM)[0]
    big = ["SN74GTL16612", "CY2309", "TPS54620", "TPS62130", "TPS74801"]
    parts = t6.sheet_head(
        "gen_c2mu_s6", "Slot 1 C2 Mu cartridge: XC7A100T + LattePanda Mu + GTL+ transceivers",
        [("hw_n:" + fsym[0], fsym[1]), ("cpu_n:" + csym[0], csym[1]), ("mu_n:" + musym[0], musym[1])]
        + t6.stock_defs(STOCK_SYMS) + [("hw_n:" + n, lib[n][1]) for n in big])
    flagged = set()

    for i, uid in enumerate(sorted(fsym[2], key=int)):
        pins = fsym[2][uid]
        parts.append(t6.syminst("hw_n:" + fsym[0], "U1", 80.0 + (i % 3) * 95.0, 35.0 + (i // 3) * 62.0,
                                int(uid), pins, {p["num"]: net_of[p["num"]] for p in pins}))
    y, col = 305.0, 0
    for uid in sorted(csym[2], key=int):
        pins = csym[2][uid]
        lab = {p["num"]: contact_net(contact_row[p["num"]], used) if p["num"] in contact_row
               else "NC_U2_" + p["num"] for p in pins}
        lab = {k: ("VCC_3V3" if False else v) for k, v in lab.items()}
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
        parts.append(t6.syminst("hw_n:" + name, ref, X, Y, 1, pins, lab, footprint=FP.get(name) or MU_FPS[name]))

    chan = {}
    for r in pinsrows:
        if r["chip"]:
            chan.setdefault(r["chip"], {})[int(r["channel"])] = r
    for k, (chip, ref) in enumerate(GTL_REFS.items()):
        grp = re.sub(r"\d", "", chip)
        names = {"OEAB#": f"{grp}_OEAB#", "OEBA#": "VCC_3V3" if grp == "TX" else f"{grp}_OEBA#",
                 "LEAB": "AB_LE", "LEBA": "VCC_3V3" if grp == "ADDR" else "GND",
                 "CEAB#": "GND", "CEBA#": "GND", "CLKAB": f"CLK_{chip}", "CLKBA": f"CLK_{chip}",
                 "VCC33": "VCC_3V3", "VCC5": "V5", "VREF": "VREF_GTL", "GND": "GND"}
        for ch in range(1, 19):
            r = chan[chip].get(ch)
            names[f"A{ch}"] = (("TX_" if grp == "TX" else "") + r["signal"]) if r else t6.NOCONNECT
            names[f"B{ch}"] = "S_" + r["signal"] if r else t6.NOCONNECT
        ic("SN74GTL16612", ref, 30.0 + k * 60.0, 230.0, names)
    zdb = {"REF": "BCLK", "S1": "VCC_3V3", "S2": "VCC_3V3", "VDD": "VCC_3V3", "GND": "GND",
           "CLKOUT": "ZCLK_FB", "CLKB4": t6.NOCONNECT}
    zdb.update({out: f"ZCLK_{chip}" for chip, out in ZDB_OUT.items()})
    ic("CY2309", "U10", 150.0, 290.0, zdb)

    nc = t6.NOCONNECT
    X0, Y0 = 950.0, 60.0
    stock_ic("Memory_Flash", "W25Q32JVSS", "U11", X0, Y0, {
        "~{CS}": "SPI_CS#", "DO/IO_{1}": "SPI_D1", "~{WP}/IO_{2}": "SPI_D2", "GND": "GND",
        "DI/IO_{0}": "SPI_D0", "CLK": "SPI_CLK", "~{HOLD}/~{RESET}/IO_{3}": "SPI_D3", "VCC": "VCC_3V3"},
        parts, flagged, "Package_SO:SOIC-8_5.3x5.3mm_P1.27mm", "W25Q128JVSIQ")
    stock_ic("Oscillator", "ASE-xxxMHz", "U12", X0 + 40, Y0, {"EN": "VCC_3V3", "GND": "GND", "OUT": "OSC50",
             "Vdd": "VCC_3V3"}, parts, flagged, "Oscillator:Oscillator_SMD_SeikoEpson_SG210-4Pin_2.5x2.0mm", "50MHz")
    for ref, out in (("U13", "VCC_MGT10"), ("U14", "VCC_MGT12")):
        ic("TPS74801", ref, X0 + (80 if ref == "U13" else 120), Y0, {
            "IN": "VCC_1V8", "BIAS": "V5", "EN": "VCC_1V8", "SS": f"{ref}_SS", "OUT": out, "FB": f"{ref}_FB",
            "PG": nc, "GND": "GND", "PAD": "GND"})
    for ref, port in (("U15", 1), ("U17", 3)):
        stock_ic("Power_Protection", "USBLC6-2P6", ref, X0 + 160, Y0 + (port - 1) * 10, {
            "1": f"USB{port}_P", "6": f"USB{port}_P", "2": "GND", "3": f"USB{port}_N", "4": f"USB{port}_N",
            "5": "USB_VBUS"}, parts, flagged, "Package_TO_SOT_SMD:SOT-23-6", "USBLC6-2SC6")
    ft = {"XCSI": "FT_XI", "XCSO": "FT_XO", "VPHY": "FT_VPHY", "AGND": "GND", "REF": "FT_REF", "DM": "USB2_N",
          "DP": "USB2_P", "VPLL": "FT_VPHY", "GND": "GND", "VCCIO": "VCC_3V3", "ADBUS0": "FT_TCK",
          "ADBUS1": "FT_TDI", "ADBUS2": "FT_TDO", "ADBUS3": "FT_TMS", "~{RESET}": "FT_RESET#",
          "VCCA": "FT_VCCA", "VCCCORE": "FT_VCORE", "VCCD": "VCC_3V3", "VREGIN": "VCC_3V3", "TEST": "GND",
          "EEDATA": "FT_EEDATA", "EECLK": nc, "EECS": nc}
    ft.update({f"ADBUS{k}": nc for k in range(4, 8)} | {f"ACBUS{k}": nc for k in range(10)})
    stock_ic("Interface_USB", "FT232H", "U16", X0 + 200, Y0, ft, parts, flagged,
             "Package_QFP:LQFP-48_7x7mm_P0.5mm", "FT232HL-REEL")
    stock_ic("Device", "Crystal_GND24", "Y1", X0 + 240, Y0, {"1": "FT_XI", "2": "GND", "3": "FT_XO", "4": "GND"},
             parts, flagged, "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm", "12MHz")
    for ref, gate, drain in (("Q1", "MU_PWR_ON", "MU_PWRBTN#"), ("Q2", "MU_RST", "MU_RSTBTN#")):
        stock_ic("Transistor_FET", "Q_NMOS_GSD", ref, X0 + (260 if ref == "Q1" else 280), Y0,
                 {"G": gate, "S": "GND", "D": drain}, parts, flagged, "Package_TO_SOT_SMD:SOT-23", "2N7002")
    stock_ic("Switch", "SW_Push", "SW1", X0, Y0 + 40, {"1": "MU_PWRBTN#", "2": "GND"}, parts, flagged,
             "Button_Switch_SMD:SW_Push_1P1T_XKB_TS-1187A", "PWR")
    stock_ic("Device", "LED", "D1", X0 + 20, Y0 + 40, {"K": "GND", "A": "LED_A"}, parts, flagged,
             "LED_SMD:LED_0603_1608Metric", "green")
    stock_ic("Device", "D_Schottky", "D2", X0 + 40, Y0 + 40, {"K": "V5", "A": "FAN_TAC"}, parts, flagged,
             "Diode_SMD:D_SOD-323", "B5819WS")
    stock_ic("Connector_Generic", "Conn_01x02", "J8", X0 + 60, Y0 + 40, {"1": "RTC_CELL", "2": "GND"}, parts,
             flagged, "Connector_Molex:Molex_PicoBlade_53261-0271_1x02-1MP_P1.25mm_Horizontal", "CMOS cell")
    stock_ic("Device", "Polyfuse", "F2", X0 + 80, Y0 + 40, {"1": "V5", "2": "USB_VBUS"}, parts, flagged,
             "Fuse:Fuse_1206_3216Metric", "1.1A")
    jtag = ["GND", "VCC_3V3", "GND", "F_TMS", "GND", "F_TCK", "GND", "F_TDO", "GND", "F_TDI", "GND", nc, "GND", nc]
    for ref, slib, name, X, nets, fp in (     # Xilinx 2 mm 14-pin; 4-pin fan GND, +5 V, tach, PWM [Lite carrier]
            ("J1", "Connector_Generic", "Conn_02x07_Odd_Even", X0, jtag,
             "Connector_PinHeader_2.00mm:PinHeader_2x07_P2.00mm_Vertical"),
            ("J3", "Connector", "Barrel_Jack", X0 + 40, ["V12_IN", "GND"], "Connector_BarrelJack:BarrelJack_CUI_PJ-063AH_Horizontal"),
            ("J5", "Connector_Generic", "Conn_01x04", X0 + 80, ["GND", "V5", "FAN_TAC", "FAN_PWM"],
             "Connector_JST:JST_PH_B4B-PH-K_1x04_P2.00mm_Vertical"),
            ("J7", "Connector_Generic", "Conn_01x03", X0 + 160, ["GND", "MU_UART_TX", "MU_UART_RX"],
             "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical")):
        stock_ic(slib, name, ref, X, Y0 + 80, {str(k + 1): n for k, n in enumerate(nets)}, parts, flagged, fp)
    usb = ["USB_VBUS", "USB_VBUS", "USB1_N", "USB3_N", "USB1_P", "USB3_P", "GND", "GND", nc, nc]   # Intel 9-pin
    stock_ic("Connector_Generic", "Conn_02x05_Odd_Even", "J6", X0 + 120, Y0 + 80,
             {str(k + 1): n for k, n in enumerate(usb)}, parts, flagged,
             "Connector_PinHeader_2.54mm:PinHeader_2x05_P2.54mm_Vertical", "USB 2.0 x2 header")
    for k, ref in enumerate(("H1", "H2")):     # the Mu's M2 holes: 6.6 mm standoffs [design_guide_edge_connector]
        stock_ic("Mechanical", "MountingHole_Pad", ref, X0 + 200 + 20 * k, Y0 + 80, {"1": "GND"}, parts, flagged,
                 "Slot1:Standoff_SMT_M2_D5.56_H6.6")
    mnets = mu_nets()
    for uid, mpins in sorted(musym[2].items()):
        mlab = {p["num"]: mnets.get(p["name"], nc) for p in mpins}
        parts.append(t6.syminst("mu_n:" + musym[0], "J4", X0 + 60 + int(uid) * 60, Y0 + 130, int(uid), mpins, mlab,
                                footprint=MU_FP))

    mu_pin_net = {p["num"]: mnets[p["name"]] for mpins in musym[2].values() for p in mpins if p["name"] in mnets}
    rows = power(Parts("Slot1Parts", taken={"F2"}), net_of, agtl, mu_pin_net)
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

    def series(a, b):
        """a two-pin part between nets a and b"""
        ra = {r for r, _ in nets.get(t6.esc(a), ())}
        return any(r[0] in "CR" and r in ra for r, _ in nets.get(t6.esc(b), ()))

    for r in pinsrows:
        sig, kind, ball, ct = r["signal"], r["kind"], r["ball"], r["contact"]
        if kind in ("addr", "data", "tx"):
            ref, num = GTL_REFS[r["chip"]], pin_num["SN74GTL16612"]
            need(("TX_" if kind == "tx" else "") + sig, ("U1", ball), (ref, num["A" + r["channel"]]))
            need("S_" + sig, ("U2", ct), (ref, num["B" + r["channel"]]))
        elif kind in ("rx", "cmos") and ct:
            need("S_" + sig, ("U1", ball), ("U2", ct))
        elif sig == "BCLK":
            need("BCLK", ("U1", ball), ("U2", ct), ("U10", "1"))
        else:
            need(sig, ("U1", ball))
    for ball, pin in c2mu_pcie.LINKS:    # Mu TX -> cap -> GTP RX, GTP TX -> cap -> Mu RX, REFCLK2 -> MGTREFCLK1
        fpga, mu = net_of[ball], mu_pin_net[pin]
        if not (fpga.startswith("PCIE_") and mu.startswith("MU_")) or not series(fpga, mu):
            fails.append(f"U1 {ball} {fpga} -> J4 {pin} {mu}: no series capacitor")
        need(mu, ("J4", pin))
    need("PCIE_PERST#", ("J4", "105"))
    need("V12", ("J4", "250"), ("J4", "260"))
    for chip, ref in GTL_REFS.items():
        need(f"CLK_{chip}", (ref, "55"), (ref, "30"))
        need("VREF_GTL", (ref, "35"))
    for n, pin in (("SPI_CS#", "1"), ("SPI_D0", "5"), ("SPI_D1", "2"), ("SPI_D2", "3"), ("SPI_D3", "7"),
                   ("SPI_CLK", "6")):
        need(n, ("U11", pin))
    need("SPI_CLK", ("U1", next(b for b, f in func_by.items() if f == "CCLK_0")))
    for s in agtl:
        if not any(ref.startswith("RN") for ref, _ in nets.get(t6.esc("S_" + s), ())):
            fails.append(f"S_{s}: no 56 R termination")
    t6.audit_exit(fails)
    print(f"AUDIT OK: {len(pinsrows)} pins.csv nets, {len(agtl)} terminated contacts, 4 PCIe lanes")
    t6.run_erc(sch, OUT / f"{NAME}.erc.json")
    t6.write_project(OUT, NAME, [
        ("Slot1Parts", "../lib/Slot1_Parts.kicad_sym", "C2 cartridge parts"),
        ("SocketFPGA", f"../../hw/lib/{fsym[0]}.kicad_sym", "FPGA"),
        ("SocketCPU", f"../../sockets/kicad/{csym[0]}.kicad_sym", "CPU"),
        ("LattePanda", "../lib/LattePanda_Mu_SODIMM260.kicad_sym", "LattePanda Mu edge (gen_mu_lib.py)")])
    print("PASS  c2mu S6 (netlist audit + ERC)")


if __name__ == "__main__":
    main()
