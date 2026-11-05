#!/usr/bin/env python3
"""Slot 1 C2 Mu cartridge (plan/slot1_c2.md D39/D40): XC7A100T-2FGG484 ball map.

Usage: python3 hw/tools/gen_c2mu_assign.py
Output: hw/slot1-c2mu/pins.csv (signal, kind, ball, bank, chip, channel,
contact), the same columns as gen_c2cart_assign.py.

Banks (D39): 15 at 1.8 V takes the 15 observed control lines straight from
the contacts (SSTL18_I, internal VREF 0.90 V) and VTT_SENSE (slot VTT 1.5 V:
board powered); 14, 16, 13 at 3.3 V take the 111 transceiver A-side nets
(the 16612 groups of gen_c2cart_assign), the 11 CMOS pins (2.5 V signals, VIH 2.0 V: no
pass-gate), BCLK and the 50 MHz oscillator on MRCC balls, the SPI x4 flash
pins of bank 14, the Mu control lines and a LED; 34/35 at 3.3 V give spare
balls so the nets take the outer rings. Each net takes the ball of least
length to where its other end sits plus DEPTH_MM per ring from the BGA edge
(match(): no two ratsnest lines from the BGA cross, no ball deeper than the
3 signal layers escape). PCIe x4 to
the Mu (HSIO8-11): Mu lane k = GTP channel 3-k (pcie_7x x4 places lane k on
GTPE2_CHANNEL_X0Y(7-k), checked in Vivado), refclk MGTREFCLK1.
Checks (exit 1): every ball used once, user IO in its planned bank,
clocks on MRCC, every chip within 18 channels.
"""
import csv
import pathlib
import sys

import numpy as np
import pcbnew
from scipy.optimize import linear_sum_assignment

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import gen_t6_schematic as t6
from gen_c2cart_assign import ADDR, CHIP_CH, CMOS, CTRL, DATA, RX, TX, ball_xy, chips, contacts
from gen_c2cart_s6 import FP, GTL_REFS, PARTS, sym_pins
from gen_c2mu_s7 import MU_AT, U1_AT, band_centres
from gen_slot1_s7 import A1_X

ROOT = pathlib.Path(__file__).resolve().parents[2]
TABLE = ROOT / "FPGAlist/c2_cards/xilinx/xc7a100t_fgg484.csv"
OUT = ROOT / "hw/slot1-c2mu"
RX_BANK = "15"
IO_BANKS = ["16", "14", "13", "34", "35"]     # 3.3 V
DEPTH_MM = 6.0                          # a ring deeper costs as much as 6 mm of trace
CLOCKS = {"BCLK": "IO_L12P_T1_MRCC_14", "OSC50": "IO_L12P_T1_MRCC_13"}
SPI = {"SPI_CS#": "FCS_B", "SPI_D0": "D00_MOSI", "SPI_D1": "D01_DIN", "SPI_D2": "D02", "SPI_D3": "D03"}
# Mu lane k -> GTP channel 3 - k
PCIE = {}
for k in range(4):
    for s in "PN":
        PCIE[f"PCIE_TX{k}_{s}"] = f"MGTPTX{s}{3 - k}_216"     # FPGA TX -> Mu HSIO RX
        PCIE[f"PCIE_RX{k}_{s}"] = f"MGTPRX{s}{3 - k}_216"     # Mu HSIO TX -> FPGA RX
PCIE.update({"PCIE_REFCLK_P": "MGTREFCLK1P_216", "PCIE_REFCLK_N": "MGTREFCLK1N_216"})
# Mu: PLT_RST# in, power / reset buttons out (each through an NMOS), PSON in
MU = ["PCIE_PERST#", "MU_PWR_ON", "MU_RST", "MU_PSON", "LED"]


def gtl_pin_xy():
    """(chip ref, symbol pin name) -> board point: the s7 band layout + the stock TSSOP-56 pads"""
    lib, name = FP["SN74GTL16612"].split(":")
    fp = pcbnew.FootprintLoad(f"/usr/share/kicad/footprints/{lib}.pretty", name)
    if fp is None:
        sys.exit(f"FAIL: footprint {FP['SN74GTL16612']} missing")
    pad = {p.GetNumber(): (pcbnew.ToMM(p.GetPosition().x), pcbnew.ToMM(p.GetPosition().y)) for p in fp.Pads()}
    sym = next(d for d in t6.parse_lib(PARTS) if d[0] == "SN74GTL16612")
    num = {p["name"]: p["num"] for p in sym_pins(sym)}
    return {(ref, pin): (cx + pad[n][0], cy + pad[n][1])
            for ref, (cx, cy) in band_centres().items() if ref in GTL_REFS.values() for pin, n in num.items()}


def match(nets, balls):
    """net -> ball of least total length (target to ball) plus the ring depth: a least length matching
    has no crossing pair (the depth term is per ball, a swap keeps it), so the fanout stays planar"""
    def at(b):
        x, y = ball_xy(b)
        return U1_AT[0] + x, U1_AT[1] + y
    depth = lambda b: 10.5 - max(abs(v) for v in ball_xy(b))
    cost = np.array([[np.hypot(at(b)[0] - tx, at(b)[1] - ty) + DEPTH_MM * depth(b) for b in balls]
                     for _, (tx, ty) in nets])
    rows, cols = linear_sum_assignment(cost)
    return {nets[r][0]: balls[c] for r, c in zip(rows, cols)}


def main():
    rows = list(csv.DictReader(open(TABLE)))
    by_func = {r["function"]: r for r in rows}
    bank = {r["ball"]: r["bank"] for r in rows}
    fails = []

    def ball(func_part):
        hits = [r["ball"] for r in rows if func_part in r["function"].split("_")
                or r["function"] == func_part or r["function"].startswith(func_part)
                or f"_{func_part}_" in r["function"]]
        assert len(hits) == 1, (func_part, hits)
        return hits[0]

    contact = contacts()
    groups = chips(ADDR, "ADDR", contact) + chips(DATA, "DATA", contact) + \
        [("TX", sorted(TX, key=lambda n: int(contact[n][1:])))]
    bus = []                                    # signal, kind, chip, channel, contact
    for chip, nets in groups:
        if len(nets) > CHIP_CH:
            fails.append(f"{chip}: {len(nets)} channels")
        kind = chip.rstrip("0123456789").lower()
        bus += [(n, kind, chip, ch + 1, contact[n]) for ch, n in enumerate(nets)]

    fixed = {n: by_func[f]["ball"] for n, f in CLOCKS.items()}
    fixed |= {n: ball(f) for n, f in SPI.items()}
    fixed |= {n: by_func[f]["ball"] for n, f in PCIE.items()}
    # PUDC_B is tied high on the board (no pull-ups while configuring)
    free = [r["ball"] for r in rows if r["user_io"] == "1" and r["bank"] in IO_BANKS
            and r["ball"] not in fixed.values() and "PUDC_B" not in r["function"]]
    # every net matched to a ball by where its other end sits on the board: the transceiver's A pin,
    # the chips its control line drives, the slot contact, the Mu socket
    pin_xy = gtl_pin_xy()
    finger = lambda c: (A1_X + int(c[1:]) - 1, 0.0)
    ctrl_chips = {"ADDR": ["ADDR0", "ADDR1"], "DATA": ["DATA0", "DATA1", "DATA2", "DATA3"], "TX": ["TX"],
                  "AB": list(GTL_REFS)}
    rows_33 = [(n, kind, chip, ch, ct) for n, kind, chip, ch, ct in bus] + \
        [(n, "ctrl", "", "", "") for n in CTRL] + [(n, "cmos", "", "", contact[n]) for n in CMOS] + \
        [(n, "mu", "", "", "") for n in MU]

    def target(n, kind, chip, ch, ct):
        if kind in ("addr", "data", "tx"):
            return pin_xy[(GTL_REFS[chip], f"A{ch}")]
        if kind == "ctrl":
            cs = [band_centres()[GTL_REFS[c]] for c in ctrl_chips[n.split("_")[0]]]
            return sum(x for x, _ in cs) / len(cs), sum(y for _, y in cs) / len(cs)
        return finger(ct) if kind == "cmos" else MU_AT
    if len(free) < len(rows_33):
        fails.append(f"3.3 V banks: {len(free)} balls for {len(rows_33)} nets")
    got = match([(r, target(*r)) for r in rows_33], free)
    assigned = [r + (b,) for r, b in got.items()]
    rx_balls = [r["ball"] for r in rows if r["user_io"] == "1" and r["bank"] == RX_BANK]
    rx = [(n, contact[n]) for n in RX] + [("VTT_SENSE", "")]
    got = match([((n, ct), finger(ct) if ct else (A1_X, 0.0)) for n, ct in rx], rx_balls)
    assigned += [(n, "rx", "", "", ct, b) for (n, ct), b in got.items()]
    for n, b in fixed.items():
        kind = "clock" if n in CLOCKS else "spi" if n in SPI else "pcie"
        assigned.append((n, kind, "", "", contact.get(n, "") if n == "BCLK" else "", b))

    balls = [r[5] for r in assigned]
    if len(set(balls)) != len(balls):
        fails.append("a ball used twice")
    for n, kind, _, _, _, b in assigned:
        want = RX_BANK if kind == "rx" else "216" if kind == "pcie" else None
        if want and bank[b] != want or not want and bank[b] not in IO_BANKS:
            fails.append(f"{n} on {b} bank {bank[b]}")
    if fails:
        print("FAIL", *fails, sep="\n  ")
        sys.exit(1)
    OUT.mkdir(exist_ok=True)
    with open(OUT / "pins.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["signal", "kind", "ball", "bank", "chip", "channel", "contact"])
        for n, kind, chip, ch, ct, b in assigned:
            w.writerow([n, kind, b, bank[b], chip, ch, ct])
    used = {}
    for r in assigned:
        used[bank[r[5]]] = used.get(bank[r[5]], 0) + 1
    print(f"c2mu pins.csv: {len(assigned)} nets; per bank {sorted(used.items())}")


if __name__ == "__main__":
    main()
