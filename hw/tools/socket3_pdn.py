"""socket3-cyclonev power tree + decoupling (plan/interposers.md T6).

gen_socket3_t6.py draws it and writes it to hw/socket3-cyclonev/pdn.csv
for the placement step. Rail plan: hw/socket3-cyclonev/power.md. Sources:
  cb3t      sockets/parts/ti_sn74cb3t3245.pdf
  tlv6700   sockets/parts/ti_tlv6700.pdf
  devkit    FPGAlist/CycloneV_A9/boards/cyclone_v_e_devkit_5cefa7f31_installer.zip
            (C5E_DEV_KIT_B.pdf sheet 29 FPGA decoupling)
"""
from pdn import (C0402, C0603, C0805, C1210, CPAIR, Parts, buck54620,
                 buck62130, farads, u1_pairs)

# devkit sheet 29 values per rail (<= 1 uF: small); every bank, VCCPD and
# VCCPGM sit on V3V3 here, so its list joins the devkit's I/O rails
U1_SMALL = {
    "VCC_1V1": ["1uF", "470nF"] + ["220nF"] * 2 + ["100nF"] * 3 + ["47nF"] * 4
               + ["22nF"] * 12 + ["10nF"] * 17 + ["4.7nF"] * 13,
    "V3V3": ["1uF"] * 2 + ["100nF"] * 3 + ["47nF"] * 2 + ["22nF"] * 2
            + ["10nF"] * 4 + ["4.7nF"] * 4 + ["2.2nF"] * 3,
    "VCC_AUX25": ["1uF", "100nF", "10nF"],
    "VCCA_FPLL25": ["100nF"],
}
U1_BULK = [("VCC_1V1", "100uF/6.3V", C1210)] * 3 + [
    ("VCC_1V1", "4.7uF", C0603), ("V3V3", "10uF", C0805),
    ("V3V3", "22uF", C0805)]


def build(net_of_ball, translators, taken):
    """net_of_ball: U1 ball -> net; translators: [SN74CB3T3245 refs];
    taken: references already on the sheet"""
    P = Parts("Socket3Parts", taken)
    print("power tree values:")
    P.add("F", "Device:Fuse", "2A", "Fuse:Fuse_1206_3216Metric",
          ["V12_IN", "V12"], "stage", "F1")
    # sequence [cvhb p.10-4 Fig 10-3]: 5 V -> PS2 core; its PG (92-98 %
    # Vout rising, tps62130 p.5) enables group 2 (PS3, PS4) together.
    # PS1 = the Slot 1 PS1 design (same rail, larger load there)
    buck54620(P, "PS1", ("V12", 12.0), "V5", 5.0, 3.0,
              (2, "22uF/10V", 22e-6), None, "PG_5V", 6.8e-6, "MSS1048-682", 0.25)
    buck62130(P, "PS2", "VCC_1V1", 1.1, (1.07, 1.13), "PG_5V", "PG_1V1")
    buck62130(P, "PS3", "VCC_AUX25", 2.5, (2.375, 2.625), "PG_1V1", None)
    # 600 R +-25 % @ 100 MHz, 500 mA, 0.38 R max [Murata BLM18AG601SN1]
    P.add("FB", "Device:FerriteBead", "BLM18AG601SN1D",
          "Inductor_SMD:L_0603_1608Metric", ["VCC_AUX25", "VCCA_FPLL25"],
          "stage", "PS3")
    buck62130(P, "PS4", "V3V3", 3.3, (3.135, 3.465), "PG_1V1", None)

    # VCORE-present interlock (plan/interposers.md FPGAmotherboard
    # compatibility): zero back-feed into a CPU rail at 0 V. INB- above
    # VIT+ pulls OUTB low = OE# (switches closed); INA+ above VIT+ releases
    # OUTA = VCORE_OK [tlv6700 p.3]. VIT+ 396-404 mV, VIT- >= 387 mV
    # [p.5]: S_VCC rising 3.04-3.21 V, falling >= 2.97 V (1 % resistors).
    # Below UVLO OUTB is high-Z = switches open [p.5 note 3]. VDD = V5:
    # valid 450 us after 1.8 V [p.5 note 2], V3V3 starts >= 2 ms later
    # (PS1 3.5 ms soft start)
    st = ("stage", "VDET")
    P.add("U", f"{P.lib}:TLV6700", "TLV6700DDC", "Package_TO_SOT_SMD:SOT-23-6",
          ["VCORE_OK", "GND", "VCORE_SENSE", "VCORE_SENSE", "V5", "BUS_OE#"],
          *st)
    P.r("68.1k 1%", "S_VCC", "VCORE_SENSE", *st)
    P.r("10k 1%", "VCORE_SENSE", "GND", *st)
    P.c("10nF", C0402, "VCORE_SENSE", *st)                # p.16 9.2.2.4
    P.c("100nF", C0402, "V5", *st)                        # p.17 9.3
    P.r("10k", "BUS_OE#", "V3V3", *st)                    # p.16 Eq 6
    P.r("10k", "VCORE_OK", "V3V3", *st)

    pairs = u1_pairs(net_of_ball, U1_SMALL)
    for rail, caps in U1_SMALL.items():
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
    for ref in translators:                               # cb3t p.11: 0.1 uF
        P.c("100nF", C0402, "V3V3", "trpin", ref, "VCC")
    P.c("100nF", C0402, "V3V3", "pin", "U4", "2")         # flash VCC
    return P.done()
