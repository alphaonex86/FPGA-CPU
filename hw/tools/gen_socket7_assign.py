#!/usr/bin/env python3
"""Task T5 (plan/interposers.md): assign socket 7 signals to Cyclone V
balls -> hw/socket7-cyclonev/pins.csv + assignment_quartus.qsf.

Socket 7 needs no translators (hw/common/socket7_notes.md R1: the 430TX
drives 3.3 V TTL and both FPGAs take 3.3 V on any bank), so every bank
runs VCCIO 3.3 V and all signals land directly (socket7-ti180 is
dropped: plan/interposers.md D9).

Bank plan: D bytes (8 D + their DP bit) never split across banks; the
address bus, then control, fill the remaining banks; TAP + sideband +
core local signals sit with the clock bank (3B, N9 = CLK1p, R5).

Checks and outputs: hw/tools/assign_common.py.
"""
import pathlib

from assign_common import assign

ROOT = pathlib.Path(__file__).resolve().parents[2]
T1 = ROOT / "hw/common/socket7_signals.csv"
OUT = ROOT / "hw/socket7-cyclonev"

CV_PLAN = [
    # 3B (28 user I/O + CLK1p ball N9): clock, interrupts, sideband, TAP
    ("CLK", "3B:N9"),
    ("FLUSH#", "3B"), ("SMI#", "3B"), ("SMIACT#", "3B"), ("STPCLK#", "3B"),
    ("INTR/LINT0", "3B"), ("NMI/LINT1", "3B"), ("FERR#", "3B"),
    ("IGNNE#", "3B"), ("PM0/BP0", "3B"), ("PM1/BP1", "3B"),
    ("BP2", "3B"), ("BP3", "3B"),
    ("TCK", "3B"), ("TMS", "3B"), ("TDI", "3B"), ("TDO", "3B"),
    ("TRST#", "3B"), ("PRDY", "3B"), ("VCC2DET#", "3B"),
    # 7A (60): lower 6 data bytes + parity + fastest bus control
    ("D[0-9]", "7A"), ("D1[0-9]", "7A"), ("D2[0-9]", "7A"),
    ("D3[0-9]", "7A"), ("D4[0-7]", "7A"), ("DP[0-5]", "7A"),
    ("ADS#", "7A"), ("ADSC#", "7A"), ("BRDY#", "7A"), ("BRDYC#", "7A"),
    ("NA#", "7A"), ("BOFF#", "7A"),
    # 4A (44): upper 2 data bytes + parity, low address, snoop/arbitration
    ("D4[89]", "4A"), ("D5[0-9]", "4A"), ("D6[0-3]", "4A"),
    ("DP[67]", "4A"),
    ("A[3-9]", "4A"), ("A1[0-4]", "4A"), ("AP", "4A"),
    ("BE[0-3]#", "4A"), ("BE6#", "4A"),
    ("AHOLD", "4A"), ("EADS#", "4A"), ("HIT#", "4A"), ("HITM#", "4A"),
    ("INV", "4A"), ("KEN#", "4A"), ("HOLD", "4A"), ("HLDA", "4A"),
    # 8A (28): high address, cycle definition, cache hints, reset-time straps
    ("A1[5-9]", "8A"), ("A2[0-9]", "8A"), ("A3[01]", "8A"),
    ("M/IO#", "8A"), ("D/C#", "8A"), ("W/R#", "8A"),
    ("PWT", "8A"), ("PCD", "8A"), ("WB/WT#", "8A"), ("EWBE#", "8A"),
    ("A20M#", "8A"), ("IERR#", "8A"),
    ("BF0", "8A"), ("BF1", "8A"),
    # 5B (14): board-absent sideband, machine-check parity, system control,
    # the bytes enables and SCYC that do not fit 7A/4A
    ("BE4#", "5B"), ("BE5#", "5B"), ("SCYC", "5B"), ("CACHE#", "5B"), ("LOCK#", "5B"),
    ("APCHK#", "5B"), ("PCHK#", "5B"), ("PEN#", "5B"), ("BUSCHK#", "5B"),
    ("BE7#", "5B"), ("RESET", "5B"), ("INIT", "5B"), ("CPUTYP", "5B"),
    ("BREQ", "5B"),
]
VCCIO = {"3A": "3.3 V", "3B": "3.3 V", "4A": "3.3 V", "5A": "3.3 V",
         "5B": "3.3 V", "7A": "3.3 V", "8A": "3.3 V"}


def main():
    assign(ROOT, T1, OUT, CV_PLAN, VCCIO, "CLK", translated=False)
    print("  translators: 0 (direct 3.3 V landing, notes R1)")
    print(f"  wrote {OUT.relative_to(ROOT)}/pins.csv + assignment_quartus.qsf")


if __name__ == "__main__":
    main()
