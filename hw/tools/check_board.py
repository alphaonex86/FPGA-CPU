#!/usr/bin/env python3
"""Independent check of a board as it will be fabricated: the pad nets of the .kicad_pcb against
1. the schematic netlist (.net): the same pins on the same nets;
2. the vendor documents, read again here and not through the generators' tables: every CPU contact
   of the datasheet's pin table -> its level translator channel (the translator datasheet's pin-out)
   -> the FPGA ball -> the pins.csv row the FPGA constraints are made from; supply, ground and
   no-connect contacts; the translators' own supply and enable pins;
   every regulator's output from its feedback divider, against the rail it feeds;
3. c2mu: the LattePanda Mu edge pin-out (supply, ground, PCIe lanes, reset);
4. the FPGA build: a complete one exists and its pin report agrees (rtl/tools/fpga_pins.py).

Usage: python3 hw/tools/check_board.py socket3|c2mu   (exit 1 on any difference)
"""
import collections
import csv
import pathlib
import re
import subprocess
import sys

import pcbnew

ROOT = pathlib.Path(__file__).resolve().parents[2]
# SN74CB3T3245 [sockets/parts/ti_sn74cb3t3245.pdf pin table]: 1 NC, 2-9 A1-A8, 10 GND, 11-18 B8-B1, 19 OE#, 20 VCC
CB3T_B_OF_A = {a: 20 - a for a in range(2, 10)}
# SN74GTL16612 [sockets/parts/ti_sn74gtl16612.pdf p.1]: channel -> (A pin, B pin)
GTL_A = [3, 5, 6, 8, 9, 10, 12, 13, 14, 15, 16, 17, 19, 20, 21, 23, 24, 26]
GTL_B = [54, 52, 51, 49, 48, 47, 45, 44, 43, 42, 41, 40, 38, 37, 36, 34, 33, 31]
GTL_FIXED = {"GND": (4, 11, 18, 25, 32, 39, 46, 53), "VCC_3V3": (7, 22), "V5": (50,), "VREF_GTL": (35,)}

# rail -> volts; every regulator here regulates its feedback pin to 0.8 V [ti_tps54620, ti_tps62130; TPS74801]
RAILS = {"V5": 5.0, "V3V3": 3.3, "VCC_3V3": 3.3, "VCC_AUX25": 2.5, "VCC_1V8": 1.8, "VCC_1V1": 1.1, "VCC_1V0": 1.0,
         "VCC_MGT10": 1.0, "VCC_MGT12": 1.2}
VFB = 0.8

fails = []


def fail(text):
    fails.append(text)


def pdf_text(path, first=None, last=None):
    pages = (["-f", str(first)] if first else []) + (["-l", str(last)] if last else [])
    r = subprocess.run(["pdftotext", "-layout", *pages, str(ROOT / path), "-"], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"FAIL: pdftotext {path}: {r.stderr.strip()}")
    return r.stdout


def name_of(net):
    return net.lstrip("/").replace("{slash}", "/")


class Board:
    def __init__(self, name):
        self.dir = ROOT / "hw" / name
        board = pcbnew.LoadBoard(str(self.dir / f"{name}.kicad_pcb"))
        self.net, self.pads_on, self.value = {}, collections.defaultdict(set), {}
        for f in board.GetFootprints():
            self.value[f.GetReference()] = f.GetValue()
            for p in f.Pads():
                key, net = (f.GetReference(), p.GetNumber()), name_of(p.GetNetname())
                if self.net.setdefault(key, net) != net:
                    fail(f"{key}: pads of one pin on {self.net[key]} and {net}")
                if net:
                    self.pads_on[net].add(key)
        self.pins = list(csv.DictReader(open(self.dir / "pins.csv")))
        self.netlist = {}
        text = (self.dir / f"{name}.net").read_text()
        for m in re.finditer(r'\(net\s*\(code "[^"]+"\)\s*\(name "([^"]*)"\)', text):
            end = text.find("(net", m.end())
            for ref, pin in re.findall(r'\(ref "([^"]*)"\)\s*\(pin "([^"]*)"\)', text[m.end():end if end > 0 else None]):
                self.netlist[(ref, pin)] = name_of(m.group(1))

    def others(self, net, but):
        """the pads of a net except the footprint `but`"""
        return {k for k in self.pads_on.get(net, ()) if k[0] != but}

    def lone(self, key):
        """a pad without a net or alone on it"""
        return not self.net.get(key) or self.pads_on[self.net[key]] == {key}

    def check_regulators(self):
        """every *_FB net: one resistor to a rail, one to ground, the rail within 2 % of its voltage"""
        ohms = lambda v: float(re.match(r"[\d.]+", v).group()) * {"k": 1e3, "M": 1e6}.get(re.sub(r"[\d. ]|1%", "", v)[:1], 1)
        seen = []
        for net in sorted(n for n in self.pads_on if n.endswith("_FB") and n != "CLK_FB" and n != "ZCLK_FB"):
            legs = {}
            for ref, _ in self.pads_on[net]:
                if ref.startswith("R"):
                    legs[next(self.net[k] for k in self.net if k[0] == ref and self.net[k] != net)] = ohms(self.value[ref])
            rail = next((n for n in legs if n in RAILS), None)
            if rail is None or "GND" not in legs or len(legs) != 2:
                fail(f"{net}: divider {legs}")
                continue
            volts = VFB * (1 + legs[rail] / legs["GND"])
            seen.append(f"{rail} {volts:.3f} V")
            if abs(volts / RAILS[rail] - 1) > 0.02:
                fail(f"{net}: {rail} set to {volts:.3f} V")
        if set(RAILS) & set(self.pads_on) != {s.split()[0] for s in seen}:
            fail(f"rails without a feedback divider: {sorted(set(RAILS) & set(self.pads_on) - {s.split()[0] for s in seen})}")
        print("regulators: " + ", ".join(seen))

    def check_netlist(self):
        if not self.netlist:
            sys.exit("FAIL: no net parsed from the .net file: its format changed")
        for key, net in self.netlist.items():
            if self.net.get(key) != net:
                fail(f"{key}: schematic net {net}, board {self.net.get(key)}")
        for key, net in self.net.items():
            if net and key not in self.netlist:
                fail(f"{key}: on {net} on the board, not in the schematic")
        print(f"netlist: {len(self.netlist)} pins compared")

    def ball_row(self, net):
        """the pins.csv row of the one U1 ball on a net (None, with a failure, otherwise)"""
        balls = [k[1] for k in self.pads_on.get(net, ()) if k[0] == "U1"]
        rows = [r for r in self.pins if r["ball"] in balls]
        if len(balls) != 1 or len(rows) != 1:
            fail(f"net {net}: U1 balls {balls}, pins.csv rows {[r['signal'] for r in rows]}")
            return None
        return rows[0]


def socket3():
    b = Board("socket3-cyclonev")
    b.check_netlist()
    b.check_regulators()
    text = pdf_text("sockets/socket3/intel_dx4_write_back_enhanced.pdf")
    first = text.index("Table 6. Pin Assignment for 168-Pin PGA Package (Sheet 1")
    table = dict(re.findall(r"\b([A-S]\d{1,2})\s+([A-Z][A-Z0-9/#]*)(?=\s|$)", text[first:text.index("Table 7.", first)]))
    if len(table) != 168:
        sys.exit(f"FAIL: DX4 Table 6: {len(table)} pins read, not 168")
    # Am5x86 names of DX4 pins [amd_am5x86_19751C]; S4 VOLDET is tied to VSS (plan/interposers.md)
    alias = {"RESERVED#": "UP#"}
    fixed = {"VCC": "S_VCC", "VSS": "GND", "VOLDET": "GND"}
    open_pins = {"INC", "NC", "VCC5"}          # J1 VCC5: +5 V on a DX4 board, never onto the interposer
    switches = {ref for ref, v in b.value.items() if v == "SN74CB3T3245"}
    seen = set()
    for pin, name in sorted(table.items()):
        name, key = alias.get(name, name), ("U2", pin)
        if name in fixed:
            if b.net.get(key) != fixed[name]:
                fail(f"U2 {pin} {name}: on {b.net.get(key)}, not {fixed[name]}")
        elif name in open_pins:
            if not b.lone(key):
                fail(f"U2 {pin} {name}: connected to {b.net[key]}")
        else:
            legs = [k for k in b.others(b.net.get(key, ""), "U2") if k[0] in switches]
            if len(legs) != 1 or int(legs[0][1]) not in CB3T_B_OF_A.values():
                fail(f"U2 {pin} {name}: switch pads on its net {legs}, not one B pin")
                continue
            ref, bpin = legs[0]
            row = b.ball_row(b.net[(ref, str(20 - int(bpin)))])
            if row and (row["signal"], row["socket_pin"]) != (name, pin):
                fail(f"U2 {pin} {name}: reaches ball {row['ball']} = pins.csv {row['signal']} / {row['socket_pin']}")
            seen.add(name)
    for r in b.pins:
        if r["source"] != "board-local" and r["signal"] not in seen:
            fail(f"pins.csv {r['signal']}: no socket contact of the datasheet reaches it")
        if r["ball"] not in {k[1] for k in b.pads_on.get(r["signal"], ()) if k[0] == "U1"}:
            fail(f"pins.csv {r['signal']}: ball {r['ball']} is not on the net of that name")
    for ref in sorted(switches):
        for pin, net in (("20", "V3V3"), ("10", "GND"), ("19", "BUS_OE#")):
            if b.net.get((ref, pin)) != net:
                fail(f"{ref} pin {pin}: on {b.net.get((ref, pin))}, not {net}")
    qsf = dict(re.findall(r'set_location_assignment PIN_(\w+) -to "([^"]+)"', (b.dir / "assignment_quartus.qsf").read_text()))
    if qsf != {r["ball"]: r["signal"] for r in b.pins}:
        fail("assignment_quartus.qsf: not the balls of pins.csv")
    print(f"socket 3: {len(seen)} signal contacts of DX4 Table 6 through {len(switches)} switches to their balls, "
          f"{sum(n in fixed for n in table.values())} supply / ground and {sum(n in open_pins for n in table.values())} "
          "open contacts")


def c2mu():
    b = Board("slot1-c2mu")
    b.check_netlist()
    b.check_regulators()
    text = pdf_text("sockets/slot1/pentium2_350-450_sc242_24365703.pdf", 58, 61)
    table = {pin: re.sub(r"#\[(\d+)\]", r"[\1]#", name)             # the datasheet writes A#[4]
             for pin, name in re.findall(r"\b([AB]\d{1,3}) {2,}(\S+)",
                                         text[text.index("Table 35. Signal Listing in Order by Pin Number"):])}
    if len(table) != 242:
        sys.exit(f"FAIL: Pentium II Table 35: {len(table)} contacts read, not 242")
    chips = {ref for ref, v in b.value.items() if v == "SN74GTL16612"}
    by_contact = collections.defaultdict(list)
    for r in b.pins:
        if r["contact"]:
            by_contact[r["contact"]].append(r)
    supplies, unused, seen = collections.defaultdict(set), collections.defaultdict(list), 0
    for pin, name in sorted(table.items()):
        key, rows = ("U2", pin), by_contact.get(pin, [])
        net = b.net.get(key, "")
        if not rows:                      # a contact the FPGA does not use: supply, ground, terminated or open
            state = "open" if b.lone(key) else "terminated" if net.startswith("S_") else net
            if name.startswith(("VCC", "GND", "Reserved")):
                supplies[name].add(state)
            else:
                unused[state].append(name)
            if any(k[0] in chips | {"U1"} for k in b.others(net, "U2")) and net not in ("GND", "VTT15"):
                fail(f"U2 {pin} {name}: not in pins.csv but wired to {sorted(b.others(net, 'U2'))[:3]}")
            continue
        for r in rows:
            if r["signal"] not in (name, name.split("/")[-1]):          # LINT[0]/INTR
                fail(f"U2 {pin}: datasheet {name}, pins.csv {r['signal']}")
            if r["kind"] in ("addr", "data", "tx"):
                legs = [k for k in b.others(net, "U2") if k[0] in chips]
                if len(legs) != 1 or int(legs[0][1]) not in GTL_B:
                    fail(f"U2 {pin} {name}: transceiver pads on its net {legs}, not one B pin")
                    continue
                channel = GTL_B.index(int(legs[0][1]))
                if str(channel + 1) != r["channel"]:
                    fail(f"U2 {pin} {name}: on channel {channel + 1}, pins.csv says {r['channel']}")
                row = b.ball_row(b.net[(legs[0][0], str(GTL_A[channel]))])
                if row and row is not r:
                    fail(f"U2 {pin} {name}: channel A side reaches ball {row['ball']} = {row['signal']} ({row['kind']})")
            elif ("U1", r["ball"]) not in b.pads_on.get(net, ()):
                fail(f"U2 {pin} {name}: ball {r['ball']} ({r['kind']}) is not on its net {net}")
            seen += 1
    if seen != sum(bool(r["contact"]) for r in b.pins):
        fail(f"{seen} pins.csv rows reached from Table 35, pins.csv has {sum(bool(r['contact']) for r in b.pins)}")
    for want, got in (("GND", {"GND"}), ("VCC_VTT", {"VTT15"})):
        if supplies[want] != got:
            fail(f"slot {want} contacts on {supplies[want]}")
    for ref in sorted(chips):
        for net, pins in GTL_FIXED.items():
            for pin in pins:
                if b.net.get((ref, str(pin))) != net:
                    fail(f"{ref} pin {pin}: on {b.net.get((ref, str(pin)))}, not {net}")
    # LattePanda Mu edge [sockets/slot1/lattepanda_mu/edge_pinout.csv, from the vendor xlsx]
    mu = {r["pin"]: r["signal"] for r in csv.DictReader(open(ROOT / "sockets/slot1/lattepanda_mu/edge_pinout.csv"))}
    want = {"GND": "GND", "VIN": "V12", "PLT_RST#": "PCIE_PERST#", "REFCLK2_P": "MU_REFCLK_P", "REFCLK2_N": "MU_REFCLK_N"}
    for k in range(4):                    # HSIO8-11 = PCIe x4 lanes 0-3 [bios_dflt_README.md]
        for d in ("TX", "RX"):
            for pn in "PN":
                want[f"HSIO{8 + k}_{d}_{pn}"] = f"MU_{d}{k}_{pn}"
    for pin, sig in mu.items():
        net = b.net.get(("J4", pin), "")
        if sig in want and net != want[sig]:
            fail(f"J4 {pin} {sig}: on {net}, not {want[sig]}")
        if sig not in want and net in want.values():
            fail(f"J4 {pin} {sig}: on {net}")
    if set(want) - set(mu.values()):
        fail(f"Mu pin-out lacks {sorted(set(want) - set(mu.values()))}")
    print(f"c2mu: {seen} pins.csv rows reached from the {len(table)} contacts of Pentium II Table 35 through "
          f"{len(chips)} transceivers; supply contacts: " + "; ".join(f"{k}: {sorted(v)}" for k, v in sorted(supplies.items())))
    for state, names in sorted(unused.items()):      # listed every run: each is a decision, not a silence
        print(f"  signal contacts the FPGA does not use, {state}: {' '.join(sorted(names))}")
    print(f"Mu edge: {sum(s in want for s in mu.values())} supply, ground, PCIe and reset pins on their nets")


BOARDS = {"socket3": socket3, "c2mu": c2mu}
# the FPGA build of each board: (what a complete build leaves, its pin report)
FPGA = {"socket3": ("rtl/build/s3/s3.ok", "rtl/build/s3/s3.pin", "rtl/s3/build.sh rtl/build/s3"),
        "c2mu": ("rtl/build/c2mu/c2mu.bit", "rtl/build/c2mu/io.rpt",
                 "rtl/tools/vivado.sh rtl/c2/xilinx/build_c2mu.tcl rtl/build/c2mu")}


def run(name):
    """the fab steps (gen_socket_t9.py, gen_c2mu_s9.py) call it first: the board against the vendor
    tables, then against the FPGA build (rtl/tools/fpga_pins.py)"""
    BOARDS[name]()
    done, report, how = FPGA[name]
    if not (ROOT / done).exists():
        fail(f"no complete FPGA build ({done}): run {how}")
    elif subprocess.run([sys.executable, str(ROOT / "rtl/tools/fpga_pins.py"), name, str(ROOT / report)]).returncode:
        fail("the FPGA build's pins are not the board's (above)")
    if fails:
        print(f"FAIL: {len(fails)} differences")
        for f in fails[:40]:
            print("  ", f)
        sys.exit(1)
    print(f"PASS  check_board {name}")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in BOARDS:
        sys.exit(__doc__)
    run(sys.argv[1])
