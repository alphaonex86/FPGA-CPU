#!/usr/bin/env python3
"""socket3-cyclonev between the PCB and Quartus (s3_top.sv).
  board.py qsf <out.qsf>    the project settings: the board's own hw/socket3-cyclonev/assignment_quartus.qsf
                            (gen_socket3_assign.py: balls, I/O standards, configuration scheme) with
                            every signal as its s3_top port, I/O registers on the bus pins
The fitter's pin report is checked against the board by rtl/tools/fpga_pins.py.
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
BOARD = ROOT / "hw/socket3-cyclonev"
SOURCES = ["rtl/c2/cyclonev/c2_bclk_pll.sv", "rtl/s3/s3_bus.sv", "rtl/s3/s3_top.sv"]
REGISTERED_IN = ("a", "d", "dp")
REGISTERED_OUT = ("a", "d", "dp", "be_n", "ads_n", "m_io_n", "d_c_n", "w_r_n", "blast_n", "lock_n", "cache_n", "hlda",
                  "breq", "pchk_n")
OUTPUTS = REGISTERED_OUT + ("plock_n", "pcd", "pwt", "ferr_n", "hitm_n", "smiact_n", "tdo")


def port(signal):
    m = re.fullmatch(r"(A|D|DP)(\d+)", signal)
    if m:
        return f"{m.group(1).lower()}[{m.group(2)}]"
    m = re.fullmatch(r"BE(\d)#", signal)
    return f"be_n[{m.group(1)}]" if m else signal.lower().replace("/", "_").replace("#", "_n")


def qsf(out):
    lines = ["set_global_assignment -name DEVICE 5CEFA9F23C8", "set_global_assignment -name TOP_LEVEL_ENTITY s3_top",
             f"set_global_assignment -name SDC_FILE {ROOT / 'rtl/s3/s3_top.sdc'}",
             "set_global_assignment -name NUM_PARALLEL_PROCESSORS 4",
             'set_global_assignment -name RESERVE_ALL_UNUSED_PINS_WEAK_PULLUP "AS INPUT TRI-STATED"']
    core = re.search(r"X86_SRCS=\(([^)]*)\)", (ROOT / "rtl/tools/x86_files.sh").read_text()).group(1).split()
    lines += [f"set_global_assignment -name SYSTEMVERILOG_FILE {ROOT / 'rtl' / s}" for s in core]
    lines += [f"set_global_assignment -name SYSTEMVERILOG_FILE {ROOT / s}" for s in SOURCES]
    ports = set()
    for line in (BOARD / "assignment_quartus.qsf").read_text().splitlines():
        m = re.search(r'-to "([^"]+)"', line)
        if m:
            ports.add(port(m.group(1)))
            line = line.replace(m.group(0), f"-to {port(m.group(1))}")
        lines.append(line)
    for p in sorted(ports):
        base = p.split("[")[0]
        if base in REGISTERED_IN:
            lines.append(f"set_instance_assignment -name FAST_INPUT_REGISTER ON -to {p}")
        if base in REGISTERED_OUT:
            lines.append(f"set_instance_assignment -name FAST_OUTPUT_REGISTER ON -to {p}")
        if base in OUTPUTS:              # a bus of several loads behind the switch: 12 mA, fast edges
            lines.append(f"set_instance_assignment -name CURRENT_STRENGTH_NEW 12MA -to {p}")
            lines.append(f"set_instance_assignment -name SLEW_RATE 1 -to {p}")
    pathlib.Path(out).write_text("\n".join(lines) + "\n")
    print(f"board.py: {len(ports)} ports")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "qsf":
        sys.exit(__doc__)
    qsf(sys.argv[2])
