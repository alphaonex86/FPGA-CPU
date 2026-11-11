#!/usr/bin/env python3
"""socket3-cyclonev between the PCB and Quartus (s3_top.sv).
  board.py qsf <out.qsf> [bus]  the project settings: the board's own hw/socket3-cyclonev/assignment_quartus.qsf
                            (gen_socket3_assign.py: balls, I/O standards, configuration scheme) with
                            every signal as its s3_top port; bus: a traffic stub instead of the core
The fitter's pin report is checked against the board by rtl/tools/fpga_pins.py.
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
BOARD = ROOT / "hw/socket3-cyclonev"
BANKS = ("3A", "3B", "4A", "5A", "5B", "7A", "8A")
SOURCES = ["rtl/c2/cyclonev/c2_bclk_pll.sv", "rtl/s3/s3_bus.sv", "rtl/s3/s3_top.sv"]
# s3_bus.sv: I/O cell registers on the inputs and outputs that pass through a register of their own;
# the registers fed from RDY# / BRDY# / BOFF# / AHOLD (FAST_OUT, the output enables) stay in the
# fabric next to those pins
REGISTERED_IN = ("a", "d", "dp", "ken_n", "hold", "eads_n", "reset")
FAST_OUT = ("a[2]", "a[3]", "blast_n")
REGISTERED_OUT = ("a", "d", "dp", "be_n", "ads_n", "m_io_n", "d_c_n", "w_r_n", "lock_n", "cache_n", "hlda", "breq", "pchk_n")
OUTPUTS = REGISTERED_OUT + ("blast_n", "plock_n", "pcd", "pwt", "ferr_n", "hitm_n", "smiact_n", "tdo")


def port(signal):
    m = re.fullmatch(r"(A|D|DP)(\d+)", signal)
    if m:
        return f"{m.group(1).lower()}[{m.group(2)}]"
    m = re.fullmatch(r"BE(\d)#", signal)
    return f"be_n[{m.group(1)}]" if m else signal.lower().replace("/", "_").replace("#", "_n")


def qsf(out, bus_only=False):
    lines = ["set_global_assignment -name DEVICE 5CEFA9F23C8", "set_global_assignment -name TOP_LEVEL_ENTITY s3_top",
             f"set_global_assignment -name SDC_FILE {ROOT / 'rtl/s3/s3_top.sdc'}",
             "set_global_assignment -name NUM_PARALLEL_PROCESSORS 4",
             'set_global_assignment -name RESERVE_ALL_UNUSED_PINS_WEAK_PULLUP "AS INPUT TRI-STATED"']
    # the board feeds every bank 3.3 V, the unused ones too (Quartus assumes 2.5 V there)
    lines += [f"set_global_assignment -name IOBANK_VCCIO 3.3V -section_id {bank}" for bank in BANKS]
    core = re.search(r"X86_SRCS=\(([^)]*)\)", (ROOT / "rtl/tools/x86_files.sh").read_text()).group(1).split()
    if bus_only:                         # minutes instead of an hour: the pin timing of s3_bus alone
        core = ["tests/s3/x86_core_stub.sv"]
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
        if base in OUTPUTS:
            packed = base in REGISTERED_OUT and p not in FAST_OUT
            lines.append(f"set_instance_assignment -name FAST_OUTPUT_REGISTER {'ON' if packed else 'OFF'} -to {p}")
            lines.append(f"set_instance_assignment -name FAST_OUTPUT_ENABLE_REGISTER OFF -to {p}")
        if base in OUTPUTS:              # a bus of several loads behind the switch: 16 mA (3.3-V LVTTL: 4, 8 or 16), fast edges
            lines.append(f"set_instance_assignment -name CURRENT_STRENGTH_NEW 16MA -to {p}")
            lines.append(f"set_instance_assignment -name SLEW_RATE 1 -to {p}")
    pathlib.Path(out).write_text("\n".join(lines) + "\n")
    print(f"board.py: {len(ports)} ports")


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4) or sys.argv[1] != "qsf" or sys.argv[3:] not in ([], ["bus"]):
        sys.exit(__doc__)
    qsf(sys.argv[2], len(sys.argv) == 4)
