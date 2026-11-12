#!/usr/bin/env python3
"""Task T9 (plan/interposers.md) for socket3-cyclonev and socket7-cyclonev: JLCPCB fabrication +
assembly files (jlcfab.py).

Usage: python3 hw/tools/gen_socket_t9.py socket3|socket7 [boards]   (after gen_socket*_t8.py;
default 2 boards)
Output: hw/<socket>-cyclonev/fab/: <name>-gerbers.zip, <name>-bom.csv, <name>-cpl.csv.
U2 (the base footprint) is the Mill-Max PGA header, ordered from mill-max.com/pga with the base's
pin pattern and soldered after assembly, not a JLCPCB part.
Checks (exit 1): socket 3: the board against the vendor pin tables (check_board.py); kicad-cli DRC 0
errors and 0 unrouted; every part has an LCSC number and every
number is used; live JLCPCB stock >= quantity x boards, except CONSIGNED parts.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import check_board
import jlcfab

ROOT = pathlib.Path(__file__).resolve().parents[2]
NO_PART = {"U2"}
CONSIGNED = {"C1550735": "Digi-Key / Mouser (5CEBA9F23C8N or 5CEFA9F23C8N; JLCPCB stock 0 on 2026-11-05)",
             "C1550819": "broker (5CEFA9F23C7N: NTEMALL 159 at ~$274-310, Octopart ~$443; LCSC 0 on 2026-11-12)"}
STACK = {"socket3": "8 layers, stack JLC08161H-2116", "socket7": "8 layers, stack JLC08161H-2116"}
ORDER = ("JLCPCB order: {}, 1.6 mm, ENIG, via-in-pad (POFV: U1), PCBA both sides incl. BGA; U2: Mill-Max "
         "PGA header (551 socket 3 / 550 socket 7), soldered afterwards")
# (value, footprint) -> LCSC number, checked on JLCPCB 2026-11-05 (basic parts first): parts of both boards
COMMON = {
    ("100k", "R_0402_1005Metric"): "C25741",
    ("100nF", "C_0402_1005Metric"): "C1525",
    ("100nF", "C_0402_P1.00"): "C1525",
    ("10k", "R_0402_1005Metric"): "C25744",
    ("10nF", "C_0402_1005Metric"): "C15195",
    ("10nF", "C_0402_P1.00"): "C15195",
    ("10uF", "C_0805_2012Metric"): "C15850",
    ("1k", "R_0402_1005Metric"): "C11702",
    ("1uF", "C_0402_1005Metric"): "C52923",
    ("1uF", "C_0402_P1.00"): "C52923",
    ("2.2nF", "C_0402_P1.00"): "C1531",
    ("220nF", "C_0402_1005Metric"): "C16772",
    ("22nF", "C_0402_1005Metric"): "C1532",
    ("22nF", "C_0402_P1.00"): "C1532",
    ("22uF", "C_0805_2012Metric"): "C45783",
    ("22uF/6.3V", "C_0805_2012Metric"): "C45783",
    ("2k0 1%", "R_0402_1005Metric"): "C4109",
    ("4.7nF", "C_0402_P1.00"): "C1538",
    ("4.7uF", "C_0603_1608Metric"): "C19666",
    ("470nF", "C_0402_1005Metric"): "C47339",
    ("47nF", "C_0402_1005Metric"): "C307434",
    ("47nF", "C_0402_P1.00"): "C307434",
    ("4k7", "R_0402_1005Metric"): "C25900",
    ("BLM18AG601SN1D", "L_0603_1608Metric"): "C19330",
    ("Conn_02x03_Odd_Even", "PinHeader_2x03_P2.54mm_Vertical"): "C492420",
    ("MT25QL01GBBB8ESF-0SIT", "SOIC-16W_7.5x10.3mm_P1.27mm"): "C2061920",
}
EXTRA = {
    "socket3": {
        # C7 (operator 2026-11-12): the bus pin loop misses timing on C8
        ("FPGA_CycloneV_5CEFA9_F484", "FPGA_CycloneV_5CEFA9_F484_BGA"): "C1550819",
        ("1.33k", "R_0402_1005Metric"): "C2974006",
        ("100uF/6.3V", "C_1210_3225Metric"): "C49066",
        ("10k 1%", "R_0402_1005Metric"): "C25744",
        ("10uF/25V", "C_1210_3225Metric"): "C39232",
        ("2.2uH XFL4020-222", "L_Coilcraft_XxL4020"): "C122469",
        ("215k", "R_0402_1005Metric"): "C11489",
        ("22uF/10V", "C_1206_3216Metric"): "C5672",
        ("27nF", "C_0402_1005Metric"): "C880636",
        ("2A", "Fuse_1206_3216Metric"): "C3105",                  # 0466002.NRHF, 63 V fast
        ("3.3nF", "C_0402_1005Metric"): "C26404",
        ("316k", "R_0402_1005Metric"): "C2998151",
        ("37.4k", "R_0402_1005Metric"): "C25888",
        ("4.7uF/25V", "C_0805_2012Metric"): "C1779",
        ("52.3k", "R_0402_1005Metric"): "C2998086",
        ("6.8uH FXL1040-6R8", "L_Changjiang_FXL1040"): "C167231",
        ("68.1k 1%", "R_0402_1005Metric"): "C11537",
        ("Barrel_Jack", "BarrelJack_CUI_PJ-063AH_Horizontal"): "C22434582",
        ("SN74CB3T3245", "TSSOP-20_4.4x6.5mm_P0.65mm"): "C15298",
        ("TLV6700DDC", "SOT-23-6"): "C2868382",
        ("TPS54620RHL", "TI_RHL0014A"): "C263274",
        ("TPS62130RGT", "VQFN-16-1EP_3x3mm_P0.5mm_EP1.68x1.68mm"): "C43590",
    },
    "socket7": {
        ("FPGA_CycloneV_5CEFA9_F484", "FPGA_CycloneV_5CEFA9_F484_BGA"): "C1550735",
        ("10uF/10V", "C_0805_2012Metric"): "C15850",
        ("1nF", "C_0402_1005Metric"): "C1523",
        ("1uH XFL4020-102", "L_Coilcraft_XxL4020"): "C5355380",
        ("22uF/10V", "C_0805_2012Metric"): "C45783",
        ("82.5k", "R_0402_1005Metric"): "C11717",
        ("TLV62585PDRL", "SOT-563"): "C485118",
        ("TLV75725PDBVR", "SOT-23-5"): "C2872563",
        ("TPS22918DBVR", "SOT-23-6"): "C131941",
    },
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in EXTRA:
        sys.exit(f"usage: gen_socket_t9.py {'|'.join(EXTRA)} [boards]")
    socket = sys.argv[1]
    boards = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    name = f"{socket}-cyclonev"
    if socket in check_board.BOARDS:
        check_board.run(socket)
    jlcfab.fab(ROOT / "hw" / name / f"{name}.kicad_pcb", COMMON | EXTRA[socket], NO_PART, CONSIGNED, boards,
               ORDER.format(STACK[socket]))


if __name__ == "__main__":
    main()
