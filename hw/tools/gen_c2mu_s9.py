#!/usr/bin/env python3
"""Slot 1 C2 Mu cartridge: JLCPCB fabrication + assembly files, the S9 step
for hw/slot1-c2mu.

Usage: python3 hw/tools/gen_c2mu_s9.py [boards]   (after gen_c2mu_s8.py; default 2 boards)
Output: hw/slot1-c2mu/fab/: slot1-c2mu-gerbers.zip (Gerbers + Excellon drill),
slot1-c2mu-bom.csv (Comment, Designator, Footprint, LCSC Part #) and
slot1-c2mu-cpl.csv (Designator, Mid X, Mid Y, Layer, Rotation).
Order options: ORDER (printed).
Checks (exit 1): the board against the vendor pin tables (check_board.py); the 3D clearance under
the Mu (check_mu_clearance.py);
kicad-cli DRC 0 errors and 0 unrouted; every board part
(U2 = the card edge itself, no part) has an LCSC number and every number is
used; live JLCPCB stock >= quantity x boards, except CONSIGNED parts (not
stocked by JLCPCB/LCSC: bought elsewhere and sent to JLCPCB, or JLCPCB Global
Sourcing), printed with their source. JLCPCB's placement preview still has to
be checked by eye: its library rotations differ from KiCad's for some
packages. The steps are jlcfab.py's.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import check_board
import check_mu_clearance
import jlcfab

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT, NAME = ROOT / "hw/slot1-c2mu", "slot1-c2mu"
NO_PART = {"U2"}                          # gold fingers of the PCB
ORDER = ("JLCPCB order: 8 layers, 1.6 mm, stack JLC08161H-2116, ENIG, gold fingers with 45 deg bevel "
         "(Slot 1 edge), via-in-pad (POFV: U1 and the plane vias), PCBA both sides incl. BGA")
CONSIGNED = {"C2876885": "ti.com (SN74GTL16612DGGR ACTIVE, in stock 2026-11-04)"}

# (value, footprint) -> LCSC number; chosen 2026-11-04 on JLCPCB stock (basic parts first)
LCSC = {
    ("100uF/25V", "CP_Elec_6.3x5.4"): "C46550402",
    ("10uF/25V", "C_1210_3225Metric"): "C39232",
    ("4.7uF/25V", "C_0805_2012Metric"): "C1779",
    ("22uF/10V", "C_1206_3216Metric"): "C5672",
    ("100nF", "C_0402_1005Metric"): "C1525",
    ("100nF", "C_0402_P1.00"): "C1525",
    ("10nF", "C_0402_1005Metric"): "C15195",
    ("27nF", "C_0402_1005Metric"): "C880636",
    ("22uF/6.3V", "C_0805_2012Metric"): "C45783",
    ("3.3nF", "C_0402_1005Metric"): "C26404",
    ("470nF", "C_0402_P1.00"): "C47339",
    ("470nF", "C_0402_1005Metric"): "C47339",
    ("100uF/6.3V", "C_1210_3225Metric"): "C49066",
    ("4.7uF", "C_0603_1608Metric"): "C19666",
    ("47uF/6.3V", "C_1210_3225Metric"): "C440151",
    ("1uF", "C_0402_1005Metric"): "C52923",
    ("2.2uF", "C_0402_1005Metric"): "C12530",
    ("1nF", "C_0402_1005Metric"): "C1523",
    ("22uF", "C_0805_2012Metric"): "C45783",
    ("10pF", "C_0402_1005Metric"): "C32949",
    ("220nF", "C_0402_1005Metric"): "C16772",
    ("10uF", "C_0805_2012Metric"): "C15850",
    ("27pF", "C_0402_1005Metric"): "C1557",
    ("green", "LED_0603_1608Metric"): "C12624",
    ("B5819WS", "D_SOD-323"): "C64886",
    ("5A", "Fuse_1812_4532Metric"): "C45935331",
    ("1.1A", "Fuse_1206_3216Metric"): "C269119",
    ("600R@100MHz", "L_0603_1608Metric"): "C1002",
    ("MountingHole_Pad", "Standoff_SMT_M2_D5.56_H6.6"): "C2916353",
    ("Conn_02x07_Odd_Even", "PinHeader_2x07_P2.00mm_Vertical"): "C32713238",
    ("Barrel_Jack", "BarrelJack_CUI_PJ-063AH_Horizontal"): "C22434582",
    ("LattePanda_Mu_SODIMM260", "LattePanda_Mu_LOTES_ADDR0110_9.2H"): "C962122",
    ("Conn_01x04", "JST_PH_B4B-PH-K_1x04_P2.00mm_Vertical"): "C131334",
    ("USB 2.0 x2 header", "PinHeader_2x05_P2.54mm_Vertical"): "C32713278",
    ("Conn_01x03", "PinHeader_1x03_P2.54mm_Vertical"): "C49257",
    ("CMOS cell", "Molex_PicoBlade_53261-0271_1x02-1MP_P1.25mm_Horizontal"): "C177225",
    ("6.8uH FXL1040-6R8", "L_Changjiang_FXL1040"): "C167231",
    ("2.2uH XFL4020-222", "L_Coilcraft_XxL4020"): "C122469",
    ("TPS54620RHL", "TI_RHL0014A"): "C263274",
    ("TPS62130RGT", "VQFN-16-1EP_3x3mm_P0.5mm_EP1.68x1.68mm"): "C43590",
    ("2N7002", "SOT-23"): "C8545",
    ("1.33k", "R_0402_1005Metric"): "C2974006",
    ("100k", "R_0402_1005Metric"): "C25741",
    ("52.3k", "R_0402_1005Metric"): "C2998086",
    ("10k", "R_0402_1005Metric"): "C25744",
    ("24.9k", "R_0402_1005Metric"): "C138027",
    ("124k", "R_0402_1005Metric"): "C2933070",
    ("316k", "R_0402_1005Metric"): "C2998151",
    ("1.13k 1%", "R_0402_1005Metric"): "C54102310",
    ("4.53k 1%", "R_0402_1005Metric"): "C3013171",
    ("2.49k 1%", "R_0402_1005Metric"): "C25884",
    ("4.99k 1%", "R_0402_1005Metric"): "C25903",
    ("1.00k", "R_0402_1005Metric"): "C11702",
    ("1k", "R_0402_1005Metric"): "C11702",
    ("2.00k", "R_0402_1005Metric"): "C4109",
    ("0R", "R_0402_1005Metric"): "C17168",
    ("22R", "R_0402_1005Metric"): "C25092",
    ("4.7k", "R_0402_1005Metric"): "C25900",
    ("330R", "R_0402_1005Metric"): "C25104",
    ("100R 1%", "R_0402_1005Metric"): "C25076",
    ("100R", "R_0402_1005Metric"): "C25076",
    ("21.5k", "R_0402_1005Metric"): "C25872",
    ("12k 1%", "R_0402_1005Metric"): "C25752",
    ("33R", "R_0402_1005Metric"): "C25105",
    ("56R", "R_Array_Convex_4x0402"): "C136842",
    ("PWR", "SW_Push_1P1T_XKB_TS-1187A"): "C318884",
    ("FPGA_Artix7_XC7A100T_FGG484", "FPGA_Artix7_XC7A100T_FGG484_BGA"): "C410276",
    ("SN74GTL16612", "TSSOP-56_6.1x14mm_P0.5mm"): "C2876885",
    ("CY2309", "SOIC-16_3.9x9.9mm_P1.27mm"): "C2840305",
    ("W25Q128JVSIQ", "SOIC-8_5.3x5.3mm_P1.27mm"): "C97521",
    ("50MHz", "Oscillator_SMD_SeikoEpson_SG210-4Pin_2.5x2.0mm"): "C2901606",
    ("TPS74801", "VSON-10-1EP_3x3mm_P0.5mm_EP1.65x2.4mm"): "C105263",
    ("USBLC6-2SC6", "SOT-23-6"): "C7519",
    ("FT232HL-REEL", "LQFP-48_7x7mm_P0.5mm"): "C51997",
    ("12MHz", "Crystal_SMD_3225-4Pin_3.2x2.5mm"): "C9002",
}


def main():
    boards = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    check_board.run("c2mu")
    check_mu_clearance.check(OUT / f"{NAME}.kicad_pcb")
    jlcfab.fab(OUT / f"{NAME}.kicad_pcb", LCSC, NO_PART, CONSIGNED, boards, ORDER)


if __name__ == "__main__":
    main()
