#!/usr/bin/env python3
"""The FPGA build's pin report against the board (the last link PCB -> FPGA code): every ball the
tool placed a port on is that signal's ball in the board's pins.csv (itself checked against the PCB
and the vendor pin tables by hw/tools/check_board.py), every pins.csv signal is a port or listed
UNUSED here, and every supply / ground ball sits on a board net of the voltage the tool asks for.

Usage: fpga_pins.py socket3 <quartus .pin>   (rtl/s3/build.sh runs it)
       fpga_pins.py c2mu <vivado io.rpt>      (rtl/c2/xilinx/build_c2mu.tcl's report_io)
The fab steps (hw/tools/gen_socket_t9.py, gen_c2mu_s9.py) run it on rtl/build/<s3|c2mu>.
"""
import csv
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "rtl/s3"))
import board as s3_board  # noqa: E402  (port names of s3_top)

# pins.csv signals no port uses: wired on the board, left to its pull-ups / terminators by this RTL
UNUSED = {"socket3": set(),
          "c2mu": {("cmos", "FLUSH#"), ("cmos", "IGNNE#"), ("cmos", "PWRGOOD"), ("cmos", "SLP#"), ("cmos", "THERMTRIP#"),
                   ("rx", "DEFER#"), ("rx", "LOCK#"), ("rx", "HIT#"), ("rx", "HITM#"), ("rx", "BR0#")}}
# board net of each supply voltage [hw/socket3-cyclonev/power.md, plan/slot1_c2.md Artix cartridge]
RAILS = {"socket3": {"1.1V": {"VCC_1V1"}, "2.5V": {"VCC_AUX25", "VCCA_FPLL25"}, "3.3V": {"V3V3"},
                     "3.0V/3.3V": {"V3V3"},               # VCCPGM, VCCPD at a 3.3 V bank
                     "VCCBAT": {"VCC_AUX25"}},            # 1.2-3.0 V [cv_51002 Table 4]
         "c2mu": {"VCCINT": {"VCC_1V0"}, "VCCBRAM": {"VCC_1V0"}, "VCCAUX": {"VCC_1V8"}, "VCCADC": {"VCC_1V8"},
                  "MGTAVCC": {"VCC_MGT10"}, "MGTAVTT": {"VCC_MGT12"}, "3.30": {"VCC_3V3"}, "any**": {"VCC_1V8"}}}
BOARD = {"socket3": "socket3-cyclonev", "c2mu": "slot1-c2mu"}


def c2mu_port(r):
    """c2mu_top's port of a pins.csv row (build_c2mu.tcl port_of); None: no port (configuration pins)"""
    sig, kind = r["signal"], r["kind"]
    fixed = {"LINT[0]/INTR": "intr", "LINT[1]/NMI": "nmi", "PCIE_REFCLK_P": "pcie_clk_p", "PCIE_REFCLK_N": "pcie_clk_n"}
    tx = {"ADS#": "ads_tx_n", "DRDY#": "drdy_tx_n", "BR0#": "br0_tx_n", "DBSY#": "tx_spare_n[0]",
          "BNR#": "tx_spare_n[1]", "HIT#": "tx_spare_n[2]", "HITM#": "tx_spare_n[3]"}
    if kind == "spi":
        return None
    if sig in fixed:
        return fixed[sig]
    if kind == "tx":
        return tx[sig]
    m = re.fullmatch(r"PCIE_(TX|RX)(\d)_(P|N)", sig)
    if m:
        return f"pcie_{m.group(1)}_{m.group(3)}[{m.group(2)}]".lower()
    m = re.fullmatch(r"(\w+)\[(\d+)\]#", sig)
    if m:
        return f"{m.group(1).lower()}_n[{m.group(2)}]"
    return sig[:-1].lower() + "_n" if sig.endswith("#") else sig.lower()


def quartus(report):
    """[(ball, port or None, supply key or None, is ground)]"""
    out = []
    for line in pathlib.Path(report).read_text().splitlines():
        if re.match(r"^\S.* : [A-Z]+\d+ +:", line):
            use, ball, _dir, _std, volt, _bank, assigned = [c.strip() for c in line.split(":")][:7]
            supply = "VCCBAT" if use == "VCCBAT" else volt if use.startswith("VCC") else None
            out.append((ball, use if assigned == "Y" else None, supply, use == "GND"))
    return out


def vivado(report):
    out = []
    for line in pathlib.Path(report).read_text().splitlines():
        if re.match(r"\| [A-Z]{1,2}\d{1,2} ", line):
            c = [x.strip() for x in line.split("|")[1:]]
            ball, sig, pin, use, volt = c[0], c[1], c[3], c[4], c[11]
            supply = volt if use == "VCCO" else re.sub(r"_.*", "", pin) if re.match(r"VCC|MGTAV", pin) and use != "Config" else None
            out.append((ball, sig or None, supply, use == "GND"))
    return out


def main(name, report):
    import pcbnew
    path = ROOT / "hw" / BOARD[name]
    u1 = pcbnew.LoadBoard(str(path / f"{BOARD[name]}.kicad_pcb")).FindFootprintByReference("U1")
    net = {p.GetNumber(): p.GetNetname().lstrip("/") for p in u1.Pads()}
    rows = list(csv.DictReader(open(path / "pins.csv")))
    port_of = (lambda r: s3_board.port(r["signal"])) if name == "socket3" else c2mu_port
    want = {r["ball"]: port_of(r) for r in rows if (r.get("kind"), r["signal"]) not in UNUSED[name]}
    balls = (quartus if name == "socket3" else vivado)(report)
    if len(balls) != 484:
        sys.exit(f"FAIL: {len(balls)} balls read from {report}, not 484")
    fails, ports, supplies, grounds = [], 0, 0, 0
    for ball, port, supply, ground in balls:
        if port != want.get(ball):
            fails.append(f"{ball}: the build has {port}, pins.csv {want.get(ball)}")
        ports += port is not None
        if ground and net.get(ball) != "GND":
            fails.append(f"{ball}: ground ball on the board's {net.get(ball)}")
        grounds += ground
        if supply is not None:
            supplies += 1
            if net.get(ball) not in RAILS[name].get(supply, ()):
                fails.append(f"{ball}: supply {supply}, board net {net.get(ball)}")
    print(f"fpga_pins {name}: {ports} ports on their pins.csv balls, {supplies} supply and {grounds} ground balls on "
          f"their nets; pins.csv signals without a port: {' '.join(sorted(s for _, s in UNUSED[name])) or 'none'}")
    if fails:
        print(f"FAIL: {len(fails)} balls", *fails[:30], sep="\n  ")
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in BOARD:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
