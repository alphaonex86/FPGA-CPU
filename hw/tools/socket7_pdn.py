"""socket7-cyclonev power tree + decoupling (plan/interposers.md T6).

gen_socket7_t6.py draws it and writes it to hw/socket7-cyclonev/pdn.csv
for the placement step. Rail plan and sequencing: hw/socket7-cyclonev/power.md.
Sources:
  tlv62585  sockets/parts/ti_tlv62585.pdf
  tps22918  sockets/parts/ti_tps22918.pdf
  tlv757p   sockets/parts/ti_tlv757p.pdf
"""
from pdn import (C0402, C0603, C0805, CPAIR, L_SMALL, Parts, farads, kohm,
                 l_check, tps62130_r1, u1_pairs)
from socket3_pdn import U1_SMALL

# the socket 3 network, its V3V3 here VCCIO33; VCC_1V1 bulk held to the
# TLV62585's 47 uF with 1 uH (with the buck's 22 uF and ~3 uF of small caps)
U1_SMALL7 = {("VCCIO33" if r == "V3V3" else r): v for r, v in U1_SMALL.items()}
U1_BULK = [("VCC_1V1", "22uF/6.3V", C0805), ("VCCIO33", "10uF", C0805),
           ("VCCIO33", "22uF", C0805), ("VCC_AUX25", "4.7uF", C0603)]


def buck62585(P, p, vin_net, vin_max, vout_net, vout, band, en, pg):
    """TLV62585PDRL [tlv62585 p.9-11]: R2 100 k (<= 100 k, Eq 2), 1 uH +
    22 uF (Table 4 typical), FB 594-606 mV at 0-85 C (p.6) inside the band"""
    r1, vset = tps62130_r1(vout, band, vref=0.6)
    lo, hi = 0.594 * (1 + r1 / 100e3), 0.606 * (1 + r1 / 100e3)
    print(f"  {p}: R1 {kohm(r1)} / R2 100k -> {vset:.4f} V ({lo:.3f}-{hi:.3f})")
    assert band[0] <= lo and hi <= band[1], p
    l_check(p, "XFL4020-102", 3.0,                 # 3 A [p.1], 1.5 MHz [p.6], Eq 3 p.11
            (vin_max - vout) / 1e-6 * vout / (vin_max * 1.5e6))
    P.cout_max[vout_net] = 47e-6                   # 1 uH: 10-47 uF [p.10 Table 4]
    st = ("stage", p)
    P.add("PS", f"{P.lib}:TLV62585", "TLV62585PDRL", "Package_TO_SOT_SMD:SOT-563",
          ["GND", f"{p}_SW", vin_net, en, f"{p}_FB", pg], *st)
    P.add("L", "Device:L", "1uH XFL4020-102", L_SMALL, [f"{p}_SW", vout_net], *st)
    P.c("22uF/10V", C0805, vin_net, *st)          # >= 10 uF [p.11]
    P.c("100nF", C0402, vin_net, *st)
    P.c("22uF/6.3V", C0805, vout_net, *st)
    P.r(kohm(r1), vout_net, f"{p}_FB", *st)
    P.r("100k", f"{p}_FB", "GND", *st)


def build(net_of_ball, taken):
    """net_of_ball: U1 ball -> net; taken: references already on the sheet"""
    P = Parts("SocketParts", taken)
    print("power tree values:")
    # S_VCC2 (2.7-2.9 V, power.md) -> core; always on: EN to VIN (VIH 1.2 V [p.6])
    buck62585(P, "PS1", "S_VCC2", 2.9, "VCC_1V1", 1.1, (1.07, 1.13), "S_VCC2", "PG_1V1")
    # PG pulled up to VCC_1V1, not S_VCC3: the board raises VCC3 first and PG
    # is undriven below 1.4 V VIN [tlv62585 p.8 Table 1]. It releases at 95 %
    # (1.045 V, p.6) above the ON / EN VIH of 1 V [tps22918 p.4, tlv757p p.6]
    P.r("100k", "PG_1V1", "VCC_1V1", "stage", "PS1")

    # group 2 together on PG_1V1 [cvhb p.10-4 Fig 10-3]: VCCIO33 through the
    # switch, CT 1 nF -> tR 1.68 ms at 3.3 V [tps22918 p.6], QOD to VOUT
    st = ("stage", "U3")
    P.add("U", f"{P.lib}:TPS22918", "TPS22918DBVR", "Package_TO_SOT_SMD:SOT-23-6",
          ["S_VCC3", "GND", "PG_1V1", "U3_CT", "VCCIO33", "VCCIO33"], *st)
    P.c("1nF", C0402, "U3_CT", *st)
    P.c("10uF/10V", C0805, "S_VCC3", *st)         # CIN >= 1 uF [p.4]
    # 2.5 V aux: 0.6 V dropout max at 1 A [tlv757p p.6] < 3.135 - 2.5 V
    st = ("stage", "PS2")
    P.add("PS", f"{P.lib}:TLV75725", "TLV75725PDBVR", "Package_TO_SOT_SMD:SOT-23-5",
          ["S_VCC3", "GND", "PG_1V1", "NC_PS2_4", "VCC_AUX25"], *st)
    P.c("1uF", C0402, "S_VCC3", *st)              # CIN >= 1 uF [p.4]
    P.cout_max["VCC_AUX25"] = 200e-6               # COUT 1-200 uF [p.4]
    # 600 R +-25 % @ 100 MHz, 500 mA, 0.38 R max [Murata BLM18AG601SN1]
    P.add("FB", "Device:FerriteBead", "BLM18AG601SN1D",
          "Inductor_SMD:L_0603_1608Metric", ["VCC_AUX25", "VCCA_FPLL25"],
          "stage", "PS2")

    pairs = u1_pairs(net_of_ball, U1_SMALL7)
    for rail, caps in U1_SMALL7.items():
        mine = pairs.get(rail, [])
        for k, v in enumerate(sorted(caps, key=farads)):
            if k < len(mine):
                P.c(v, CPAIR, rail, "u1pair", *mine[k], side="B")
            else:
                P.c(v, C0402, rail, "u1bulk")
        print(f"  U1 {rail}: {min(len(mine), len(caps))}/{len(caps)} "
              "on via pairs")
    for rail, v, f in U1_BULK:
        P.c(v, f, rail, "u1bulk")
    P.c("100nF", C0402, "VCCIO33", "pin", "U4", "2")    # flash VCC
    return P.done()
