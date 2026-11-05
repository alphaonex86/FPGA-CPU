"""Slot 1 cartridge power tree + decoupling (plan/slot1.md D23, D25).

One part list: gen_slot1_s6.py draws it and writes it to
hw/slot1-cyclonev/pdn.csv, gen_slot1_s7.py places it from that file.
Rail plan: hw/slot1-cyclonev/power.md. Sources:
  tps54620  sockets/parts/ti_tps54620_6a_buck.pdf
  tps62130  sockets/parts/ti_tps62130_3a_buck.pdf
  cb3t      sockets/parts/ti_sn74cb3t3245.pdf
  devkit    FPGAlist/CycloneV_A9/boards/cyclone_v_e_devkit_5cefa7f31_installer.zip
            (C5E_DEV_KIT_B.pdf sheet 29 FPGA decoupling, sheet 12 DDR3)
"""
from pdn import (C0402, C0603, C0805, C1210, CPAIR, Parts, buck54620,
                 buck62130, farads, u1_pairs)

# devkit sheet 29 values per rail (<= 1 uF: small; larger: bulk)
U1_SMALL = {
    "VCC_1V1": ["1uF", "470nF"] + ["220nF"] * 2 + ["100nF"] * 3 + ["47nF"] * 4
               + ["22nF"] * 12 + ["10nF"] * 17 + ["4.7nF"] * 13,
    "VCCIO33": ["1uF", "100nF", "47nF", "22nF"] + ["10nF"] * 2 + ["4.7nF"] * 2
               + ["2.2nF"] * 2,         # devkit 2.5V_VCCIO_VCCPD (main I/O rail)
    "VDDR3": ["1uF", "100nF", "47nF", "22nF"] + ["10nF"] * 2 + ["4.7nF"] * 2
             + ["2.2nF"],               # devkit 1.5V_VCCIO (DDR3 banks)
    "VCC_AUX25": ["1uF", "100nF", "10nF"],
    "VCCA_FPLL25": ["100nF"],
    "VCCPGM18": ["100nF"],
}
U1_BULK = [("VCC_1V1", "100uF/6.3V", C1210)] * 3 + [
    ("VCC_1V1", "4.7uF", C0603), ("VCCIO33", "10uF", C0805),
    ("VDDR3", "22uF", C0805)]
# devkit sheet 12, per DDR3 device: VDD/VDDQ set + 0.1 uF on VREF
DIE_CAPS = (["4.7nF", "3.3nF"] + ["2.2nF"] * 4 + ["470nF"] * 2
            + ["100nF"] * 3 + ["10nF"] * 3)


def build(net_of_ball, translators):
    """net_of_ball: U1 ball -> net; translators: [(ref, rail VCCA, rail VCCB)]"""
    P = Parts("Slot1Parts")
    print("power tree values:")
    P.add("F", "Device:Fuse", "2A", "Fuse:Fuse_1206_3216Metric",
          ["V12_IN", "V12"], "stage", "F1")
    # bands: cvds p.8-9 Table 4 (VCC_AUX, VCCIO 3.3 V, VCCPGM 1.8 V);
    # VDDR3 1.35 V -0/+5 % (plan/slot1.md D10)
    # sequence [cvhb p.10-4 Fig 10-3]: group 1 = VCC to >= 80 % before
    # group 2 (VCCPGM, VCCIO, VCCPD, VCCA_FPLL, VCC_AUX) starts, VCCIO
    # with VCCPD: 5 V -> PS2 core; its PWRGD (94 % Vref, tps54620 p.6)
    # enables PS3..PS6 together.
    # Cout effective = nominal derated for DC bias (assumption: 50 % for
    # 10 V parts at 5 V, 80 % for 6.3 V parts at 1.1 V); dv: 5 % on the
    # 5 V rail [p.26 example], the VCC band floor 1.07 V on the core
    # [cvds p.8 Table 4]
    buck54620(P, "PS1", ("V12", 12.0), "V5", 5.0, 3.0,
              (2, "22uF/10V", 22e-6), None, "PG_5V", 6.8e-6, "MSS1048-682", 0.25)
    buck54620(P, "PS2", ("V5", 5.0), "VCC_1V1", 1.1, 4.0,
              (4, "47uF/6.3V", 150e-6), "PG_5V", "PG_1V1", 1.5e-6, "MSS1048-152", 0.029)
    buck62130(P, "PS3", "VCC_AUX25", 2.5, (2.375, 2.625), "PG_1V1", None)
    # power.md topology; 600 R +-25 % @ 100 MHz, 500 mA, 0.38 R max
    # [Murata BLM18AG601SN1 catalog]: 38 mV at 100 mA, VCCA_FPLL current
    # waits for the power estimator (NM9)
    P.add("FB", "Device:FerriteBead", "BLM18AG601SN1D",
          "Inductor_SMD:L_0603_1608Metric", ["VCC_AUX25", "VCCA_FPLL25"],
          "stage", "PS3")
    buck62130(P, "PS4", "VCCIO33", 3.3, (3.135, 3.465), "PG_1V1", None)
    buck62130(P, "PS5", "VCCPGM18", 1.8, (1.71, 1.89), "PG_1V1", None)
    buck62130(P, "PS6", "VDDR3", 1.35, (1.35, 1.4175), "PG_1V1", None)

    pairs = u1_pairs(net_of_ball, U1_SMALL)
    for rail, caps in U1_SMALL.items():
        mine = pairs.get(rail, [])
        for k, v in enumerate(sorted(caps, key=farads)):
            if k < len(mine):
                P.c(v, CPAIR, rail, "u1pair", *mine[k], side="B")
            else:
                P.c(v, C0402, rail, "u1bulk")
        print(f"  U1 {rail}: {min(len(mine), len(caps))}/{len(caps)} "
              "on B.Cu via pairs")
    for rail, v, f in U1_BULK:
        P.c(v, f, rail, "u1bulk")
    for ref, va, vb in translators:                       # cb3t p.11: 0.1 uF
        P.c("100nF", CPAIR, va, "trpin", ref, "VCCA", side="B")
        P.c("100nF", CPAIR, vb, "trpin", ref, "VCCB", side="B")
    for die in ("U5", "U6", "U4", "U3"):
        for v in DIE_CAPS:
            P.c(v, C0402, "VDDR3", "die", die)
        P.c("100nF", C0402, "VTTREF0675", "die", die)
    return P.done()
