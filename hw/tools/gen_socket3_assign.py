#!/usr/bin/env python3
"""Task T5 (plan/interposers.md): assign socket 3 signals to Cyclone V
balls -> hw/socket3-cyclonev/pins.csv + assignment_quartus.qsf.

Every CPU net crosses an 8-channel translator (D2: the UMC chipset drives
5 V TTL, hw/common/socket3_notes.md R1), so all banks run VCCIO 3.3 V.
(socket3-ti180 is dropped: plan/interposers.md D9.)

Bank plan: data + parity in 7A with the cycle-control inputs; address
and cycle definition in 4A; clock (N9 = CLK1p, notes R5), reset,
interrupts, straps and TAP in 3B. Translator chips never straddle a bank.
VCORE_OK (3B) is the VCORE-present detector output, straight from the
board (plan/interposers.md FPGAmotherboard compatibility); CLKMUL has
only the FPGA weak pull-up (the FPGAmotherboard ties R17 to GND).

Checks and outputs: hw/tools/assign_common.py.
"""
import pathlib

from assign_common import assign

ROOT = pathlib.Path(__file__).resolve().parents[2]
T1 = ROOT / "hw/common/socket3_signals.csv"
OUT = ROOT / "hw/socket3-cyclonev"

CV_PLAN = [
    ("CLK", "3B:N9"),
    ("RESET", "3B"), ("SRESET", "3B"), ("INTR", "3B"), ("NMI", "3B"),
    ("SMI#", "3B"), ("SMIACT#", "3B"), ("STPCLK#", "3B"), ("FLUSH#", "3B"),
    ("A20M#", "3B"), ("FERR#", "3B"), ("IGNNE#", "3B"),
    ("TCK", "3B"), ("TMS", "3B"), ("TDI", "3B"), ("TDO", "3B"),
    ("WB/WT#", "3B"), ("CLKMUL", "3B"), ("UP#", "3B"),
    ("D[0-9]", "7A"), ("D[12][0-9]", "7A"), ("D3[01]", "7A"), ("DP[0-3]", "7A"),
    ("ADS#", "7A"), ("RDY#", "7A"), ("BRDY#", "7A"), ("BLAST#", "7A"),
    ("BOFF#", "7A"), ("KEN#", "7A"), ("EADS#", "7A"), ("AHOLD", "7A"),
    ("HOLD", "7A"), ("HLDA", "7A"), ("BREQ", "7A"), ("BE[0-3]#", "7A"),
    ("A[2-9]", "4A"), ("A[12][0-9]", "4A"), ("A3[01]", "4A"),
    ("M/IO#", "4A"), ("D/C#", "4A"), ("W/R#", "4A"), ("LOCK#", "4A"),
    ("PLOCK#", "4A"), ("PWT", "4A"), ("PCD", "4A"), ("CACHE#", "4A"),
    ("HITM#", "4A"), ("INV", "4A"), ("PCHK#", "4A"),
    ("BS16#", "4A"), ("BS8#", "4A"),
]
VCCIO = {"3B": "3.3 V", "7A": "3.3 V", "4A": "3.3 V"}
# AS x4 from U4 (MSEL 10011, gen_socket3_t6.py); Quartus checks the device name only at assembly
CONFIG = ['set_global_assignment -name STRATIXV_CONFIGURATION_SCHEME "ACTIVE SERIAL X4"',
          "set_global_assignment -name USE_CONFIGURATION_DEVICE ON",
          "set_global_assignment -name STRATIXII_CONFIGURATION_DEVICE MT25QL01G"]


def main():
    rows, chips = assign(ROOT, T1, OUT, CV_PLAN, VCCIO, "CLK", translated=True,
                         local=[("VCORE_OK", "3B")], pullup=["CLKMUL"], qsf=CONFIG)
    if any(not r[5] for r in rows if r[0] != "VCORE_OK"):
        raise SystemExit("signal without a translator channel")
    print(f"  translators: {chips} x 8 channels for "
          f"{sum(1 for r in rows if r[5])} nets (D2)")
    print(f"  wrote {OUT.relative_to(ROOT)}/pins.csv + assignment_quartus.qsf")


if __name__ == "__main__":
    main()
