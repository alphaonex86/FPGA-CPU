#!/usr/bin/env python3
"""Quartus settings of the C2 cartridge (c2_cart_top.sv) from the PCB's ball
map: hw/slot1-cyclonev/pins.csv (CPU net -> ball) and the J5 link table of
hw/tools/gen_slot1_s6.py (J5 pin -> CPU net), joined with the J5 pin
functions of plan/slot1_c2.md "Cable link v0". Every pins.csv net is either
a port or listed unused here, so a PCB change cannot drop a pin silently.

Usage: gen_qsf.py <out.qsf>
"""
import csv
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "hw/tools"))
import gen_slot1_s6  # noqa: E402  (LINK, LINK_DCLK)

HERE = pathlib.Path(__file__).resolve().parent
SOURCES = ["rtl/c2/c2_cart.sv", "rtl/c2/c2_bus_sync.sv", "rtl/c2/c2_p6_agent.sv",
           "rtl/c2/cyclonev/c2_clk_fwd.sv", "rtl/c2/cyclonev/c2_bclk_pll.sv",
           "rtl/c2/cyclonev/c2_cart_top.sv"]

# nets the C2 cartridge leaves to the board's pull-ups / terminators
UNUSED = {"FLUSH#", "IGNNE#", "PWRGOOD", "SLP#", "THERMTRIP#", "BR1#", "DEFER#", "HIT#", "HITM#",
          "LOCK#", "RP#", "RSP#"}
NAMED = {"BCLK": "bclk", "LINT[0]/INTR": "intr", "LINT[1]/NMI": "nmi", "A20M#": "a20m_n",
         "INIT#": "init_n", "SMI#": "smi_n", "STPCLK#": "stpclk_n", "ADS#": "ads_n", "BNR#": "bnr_n",
         "BPRI#": "bpri_n", "BR0#": "br0_n", "TRDY#": "trdy_n", "DBSY#": "dbsy_n", "DRDY#": "drdy_n",
         "RESET#": "reset_n"}
# c2_p6_agent's registered inputs and its open-drain outputs (data = !*_drv)
REGISTERED_IN = {"d_n", "ads_n", "bnr_n", "bpri_n", "trdy_n", "dbsy_n", "drdy_n", "rs_n", "reset_n"}
OPEN_DRAIN = {"a_n", "d_n", "req_n", "ads_n", "br0_n", "drdy_n"}
# 3.3-V LVTTL: 16 mA is the strongest; SSTL-135: series OCT 34 ohm without
# calibration is its lowest impedance, and needs no RZQ pin [cv_5v2 vol1
# Table 5-25, "RS OCT without Calibration"]
OUT_LOW_Z = {"3.3-V LVTTL": "set_instance_assignment -name CURRENT_STRENGTH_NEW 16MA -to %s",
             "SSTL-135": 'set_instance_assignment -name OUTPUT_TERMINATION "SERIES 34 OHM WITHOUT CALIBRATION" -to %s'}
BUSES = {"A": ("a_n", 3, 31), "D": ("d_n", 0, 63), "REQ": ("req_n", 0, 4), "RS": ("rs_n", 0, 2)}


def j5_function(pin):
    """J5 pin -> c2_cart_top port (plan/slot1_c2.md, ax7a035b.xdc J11)."""
    if 3 <= pin <= 17 and pin % 2:
        return "link_down[%d]" % ((pin - 3) // 2)
    if pin == 19:
        return "link_uclk"
    if pin == 21:
        return "link_dclk"
    if 23 <= pin <= 35 and pin % 2:
        return "link_up[%d]" % ((pin - 23) // 2)
    if pin == 36:
        return "link_up[7]"
    raise SystemExit("gen_qsf: J5 pin %d has no link function" % pin)


def port_of(net, link_nets):
    if net in link_nets:
        return link_nets[net]
    if net in NAMED:
        return NAMED[net]
    m = re.fullmatch(r"([A-Z]+)\[(\d+)\]#", net)
    if m and m.group(1) in BUSES:
        name, lo, hi = BUSES[m.group(1)]
        if lo <= int(m.group(2)) <= hi:
            return "%s[%s]" % (name, m.group(2))
    return None


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    link_nets = {net: j5_function(pin) for pin, net in gen_slot1_s6.LINK.items()}
    ball_dclk, net_dclk = gen_slot1_s6.LINK_DCLK
    rows = list(csv.DictReader(open(ROOT / "hw/slot1-cyclonev/pins.csv")))
    lines = [
        'set_global_assignment -name FAMILY "Cyclone V"',
        "set_global_assignment -name DEVICE 5CEFA9F23C8",
        "set_global_assignment -name TOP_LEVEL_ENTITY c2_cart_top",
        "set_global_assignment -name SDC_FILE %s" % (HERE / "c2_cart_top.sdc"),
        'set_global_assignment -name RESERVE_ALL_UNUSED_PINS_WEAK_PULLUP "AS INPUT TRI-STATED"',
        # an I/O cell register has no synchronous clear + load: keep the
        # agent's pin flops plain so they pack (warning 176279)
        "set_instance_assignment -name ALLOW_SYNCH_CTRL_USAGE OFF -to agent",
    ] + ["set_global_assignment -name SYSTEMVERILOG_FILE %s" % (ROOT / s) for s in SOURCES]
    ports, unknown = {}, []
    for r in rows:
        port = port_of(r["signal"], link_nets)
        if port is None:
            if r["signal"] not in UNUSED:
                unknown.append(r["signal"])
            continue
        std = r["io_standard"].split(" (")[0]
        ports[port] = r["ball"]
        lines.append("set_location_assignment PIN_%s -to %s" % (r["ball"], port))
        lines.append('set_instance_assignment -name IO_STANDARD "%s" -to %s' % (std, port))
        if port.split("[")[0] in OPEN_DRAIN:
            # the lowest output impedance: the low level sinks the AGTL+
            # terminators through the pass-gate (plan/slot1.md NM45)
            lines.append(OUT_LOW_Z[std] % port)
            lines.append("set_instance_assignment -name SLEW_RATE 1 -to %s" % port)
        # the agent's input flops and open-drain output flops into the I/O cells
        base = port.split("[")[0]
        if base in REGISTERED_IN:
            lines.append("set_instance_assignment -name FAST_INPUT_REGISTER ON -to %s" % port)
        if base in OPEN_DRAIN:
            lines.append("set_instance_assignment -name FAST_OUTPUT_REGISTER ON -to %s" % port)
    ports["link_dclk"] = ball_dclk
    lines.append("set_location_assignment PIN_%s -to link_dclk" % ball_dclk)
    lines.append('set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to link_dclk')
    for p in [p for p in ports if p.startswith("link_") and p != "link_dclk"]:
        if p != "link_uclk":           # a DDIO output already (c2_clk_fwd)
            lines.append("set_instance_assignment -name FAST_%s_REGISTER ON -to %s"
                         % ("INPUT" if p.startswith("link_down") else "OUTPUT", p))
        if not p.startswith("link_down"):
            # 50 MHz over the cable: moderate drive, slow edges
            lines.append("set_instance_assignment -name CURRENT_STRENGTH_NEW 8MA -to %s" % p)
            lines.append("set_instance_assignment -name SLEW_RATE 0 -to %s" % p)
    if unknown:
        raise SystemExit("gen_qsf: pins.csv nets neither ported nor unused: %s" % " ".join(unknown))
    if net_dclk != "LINK_DCLK" or len(set(ports.values())) != len(ports):
        raise SystemExit("gen_qsf: a ball used twice, or LINK_DCLK renamed")
    expected = ["link_down[%d]" % i for i in range(8)] + ["link_up[%d]" % i for i in range(8)] + ["link_uclk"]
    missing = [p for p in expected if p not in ports]
    if missing:
        raise SystemExit("gen_qsf: link ports without a ball: %s" % " ".join(missing))
    pathlib.Path(sys.argv[1]).write_text("\n".join(lines) + "\n")
    print("gen_qsf: %d ports placed, %d nets unused" % (len(ports), len(UNUSED)))


if __name__ == "__main__":
    main()
