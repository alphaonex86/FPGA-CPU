#!/usr/bin/env python3
"""Slot 1 C2 Mu cartridge (plan/slot1_c2.md D39/D40): XC7A100T-2FGG484 ball map.

Usage: python3 hw/tools/gen_c2mu_assign.py
Output: hw/slot1-c2mu/pins.csv (signal, kind, ball, bank, chip, channel,
contact), the same columns as gen_c2cart_assign.py.

Banks (D39): 15 at 1.8 V takes the 15 observed control lines straight from
the contacts (SSTL18_I, internal VREF 0.90 V) and VTT_SENSE (slot VTT 1.5 V:
board powered); 14, 16, 13 at 3.3 V take the 111 transceiver A-side nets
(the 16612 groups of gen_c2cart_assign, balls nearest the card edge, in
contact x order), the 11 CMOS pins (2.5 V signals, VIH 2.0 V: no
pass-gate), BCLK and the 50 MHz oscillator on MRCC balls, the SPI x4 flash
pins of bank 14, the Mu control lines and a LED. 34/35 unused. PCIe x4 to
the Mu (HSIO8-11): Mu lane k = GTP channel 3-k (pcie_7x x4 places lane k on
GTPE2_CHANNEL_X0Y(7-k), checked in Vivado), refclk MGTREFCLK1.
Checks (exit 1): every ball used once, user IO in its planned bank,
clocks on MRCC, every chip within 18 channels.
"""
import csv
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from gen_c2cart_assign import ADDR, CHIP_CH, CMOS, CTRL, DATA, RX, TX, ball_xy, chips, contacts

ROOT = pathlib.Path(__file__).resolve().parents[2]
TABLE = ROOT / "FPGAlist/c2_cards/xilinx/xc7a100t_fgg484.csv"
OUT = ROOT / "hw/slot1-c2mu"
RX_BANK = "15"
IO_BANKS = ["16", "14", "13"]           # 3.3 V
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
    # the bus takes the balls nearest the card edge, then left to right in
    # contact x; the direction pairs sit where ADDR and DATA meet
    edge = sorted(sorted(free, key=lambda b: -ball_xy(b)[1])[:len(bus) + len(CTRL)], key=ball_xy)

    chip_x = {c: sum(int(contact[n][1:]) for n in nets) / len(nets) for c, nets in groups}
    bus.sort(key=lambda r: (chip_x[r[2]], r[3]))
    split = next(i for i, r in enumerate(bus) if r[2].startswith("ADDR"))
    ordered = bus[:split] + [(n, "ctrl", "", "", "") for n in CTRL] + bus[split:]
    assigned = [r + (b,) for r, b in zip(ordered, edge)]
    rest = sorted((b for b in free if b not in edge), key=ball_xy)
    other = [(n, "cmos", "", "", contact[n]) for n in CMOS] + [(n, "mu", "", "", "") for n in MU]
    if len(rest) < len(other):
        fails.append(f"3.3 V banks: {len(rest)} balls left for {len(other)} nets")
    assigned += [r + (b,) for r, b in zip(other, rest)]
    rx_balls = sorted((r["ball"] for r in rows if r["user_io"] == "1" and r["bank"] == RX_BANK), key=ball_xy)
    rx = sorted(RX, key=lambda n: int(contact[n][1:])) + ["VTT_SENSE"]
    assigned += [(n, "rx", "", "", contact.get(n, "") if n != "VTT_SENSE" else "", b) for n, b in zip(rx, rx_balls)]
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
