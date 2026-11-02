#!/usr/bin/env python3
"""Dedicated C2 cartridge (plan/slot1_c2.md D33/D35): FPGA ball map.

Usage: python3 hw/tools/gen_c2cart_assign.py [c2cart|c2pcie]   (default: both)
Output: hw/slot1-<board>/pins.csv (signal, kind, ball, bank, chip, channel,
contact). c2cart: FPGA 5CEBA4F23C8 with A9 drop-in: only the F484 balls that
are IO on both (FPGAlist/CycloneV_A9/pins/5ceba4.txt, 5ceba9.txt); the J5
link. c2pcie (D34): the same on the Cyclone V GX F484 set (C4/C5/C7/C9, GT
D9: FPGAlist/CycloneV_GX/pins), no link; PCIe x4 on GXB Ch0-3 + REFCLK0L,
PERST# on nPERSTL1 (R17) [ug_c5_pcie_avst Figure 4-38, pin_perst]. Banks
3.3 V except 3A (RX, SSTL-18 with VREF).

The bus nets pass 7 SN74GTL16612 (18 channels): ADDR0-1, DATA0-3 (FPGA
direction pair per group, DATA B -> A clocked by BCLK through a CY2309
zero-delay buffer; A -> B clocked too), TX
(A -> B). Each group is cut into chips along the card edge (contact x),
and the bus nets take the edge-facing banks (7A 5B 5A 4A: high ball
numbers face the edge, as on the variant A board) in the same x order.
RX: every observed control line straight from its contact into bank 3A
(the transparent transceiver's 1.1-6.3 ns leaves no input window at
66 MHz, plan/slot1_c2.md D37); the TX nets are also RX nets.
CMOS nets pass 2 CB3T3245 pass-gates; BCLK and the J5 link are direct.
Checks (exit 1): every ball IO on both devices and used once, every chip
within 18 channels, BCLK / LINK_DCLK on their clock balls.
"""
import csv
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
A9PINS = ROOT / "FPGAlist/CycloneV_A9/pins"
GXPINS = ROOT / "FPGAlist/CycloneV_GX/pins"
BOARDS = {
    "c2cart": dict(tables=[A9PINS / "5ceba9.txt", A9PINS / "5ceba4.txt"], link=True, fixed={}),
    "c2pcie": dict(tables=[GXPINS / f"{d}.txt" for d in ("5cgxfc5", "5cgxfc4", "5cgxfc7", "5cgxfc9", "5cgtfd9")],
                   link=False, fixed={"PCIE_PERST#": "nPERSTL1"}),
}
PCIE = {**{f"PCIE_{d}{k}_{s.upper()}": f"GXB_{d}_L{k}{s}" for d in ("TX", "RX") for k in range(4) for s in "pn"},
        "PCIE_REFCLK_P": "REFCLK0Lp", "PCIE_REFCLK_N": "REFCLK0Ln"}
LETTERS = "A B C D E F G H J K L M N P R T U V W Y AA AB".split()

ADDR = ["A[%d]#" % i for i in range(3, 32)] + ["REQ[%d]#" % i for i in range(5)]
DATA = ["D[%d]#" % i for i in range(64)]
RX = ["ADS#", "BNR#", "BPRI#", "TRDY#", "DBSY#", "DRDY#", "RS[0]#", "RS[1]#", "RS[2]#", "RESET#",
      "DEFER#", "LOCK#", "HIT#", "HITM#", "BR0#"]
TX = ["ADS#", "DRDY#", "DBSY#", "BR0#", "BNR#", "HIT#", "HITM#"]
# AB_LE: every chip's LEAB (high: A -> B transparent, low: clocked)
CTRL = ["ADDR_OEAB#", "ADDR_OEBA#", "DATA_OEAB#", "DATA_OEBA#", "TX_OEAB#", "AB_LE"]
RX_BANK = "3A"
CMOS = ["A20M#", "FLUSH#", "IGNNE#", "INIT#", "LINT[0]/INTR", "LINT[1]/NMI", "PWRGOOD", "SLP#",
        "SMI#", "STPCLK#", "THERMTRIP#"]
LINK = ["LINK_DOWN%d" % i for i in range(8)] + ["LINK_UP%d" % i for i in range(8)] + ["LINK_UCLK"]
CLOCKS = {"BCLK": "M9", "LINK_DCLK": "M8"}       # CLK0p / CLK0n, bank 3B
EDGE_BANKS = ["7A", "5B", "5A", "4A"]       # RX_BANK too
CHIP_CH = 18
CB3T_CH = 8


def f484(path):
    """ball -> (bank, function, optional function) of the F484 block of an
    Altera pin table"""
    rows, col = {}, None
    for line in path.read_text(encoding="latin-1").splitlines():
        c = line.split("\t")
        if c[0] == "Bank Number":
            col = c.index("F484") if "F484" in c else None
        elif col is not None and len(c) > col and c[col].strip():
            rows[c[col].strip()] = (c[0], c[2].strip('"'), c[3].strip('"'), c[4].strip('"') if len(c) > 4 else "")
    return rows


def ball_xy(ball):
    """board position relative to the FPGA centre: letter -> x, number -> y
    (number 22 towards the card edge), the footprint's orientation"""
    m = re.fullmatch(r"([A-Z]+)(\d+)", ball)
    return LETTERS.index(m.group(1)) - 10.5, 10.5 - (int(m.group(2)) - 1)


def contacts():
    """signal -> SC242 contact; contact x = number - 1 (mm, both rows)"""
    out = {}
    for r in csv.DictReader(open(ROOT / "hw/common/slot1_signals.csv")):
        out.setdefault(r["signal"], r["pin"])
    return out


def chips(names, prefix, contact):
    """cut a net group into chips of consecutive contact x; channel order = x"""
    nets = sorted(names, key=lambda n: int(contact[n][1:]))
    k = -(-len(nets) // CHIP_CH)
    per = -(-len(nets) // k)
    return [(prefix + (str(i) if k > 1 else ""), nets[i * per:(i + 1) * per]) for i in range(k)]


def ball_of(table, func, col=1):
    """the one ball whose function (col 1) or configuration function (col 3) is func"""
    hits = [b for b, v in table.items() if v[col].split(",")[0] == func]
    assert len(hits) == 1, (func, hits)
    return hits[0]


def main(board):
    cfg = BOARDS[board]
    out = ROOT / f"hw/slot1-{board}"
    tables = [f484(p) for p in cfg["tables"]]
    a9 = tables[0]
    fixed = {s: ball_of(a9, f, 3) for s, f in cfg["fixed"].items()}
    common = {b for b in a9 if all(t.get(b, ("", ""))[1] == "IO" for t in tables)} - set(fixed.values())
    contact = contacts()
    fails = []

    groups = chips(ADDR, "ADDR", contact) + chips(DATA, "DATA", contact) + \
        [("TX", sorted(TX, key=lambda n: int(contact[n][1:])))]
    rows = []                                   # signal, kind, chip, channel, contact
    for chip, nets in groups:
        if len(nets) > CHIP_CH:
            fails.append("%s: %d channels" % (chip, len(nets)))
        kind = chip.rstrip("0123456789").lower()
        rows += [(n, kind, chip, ch + 1, contact[n]) for ch, n in enumerate(nets)]
    # the direction pairs sit with their groups' first chip
    rows += [(n, "ctrl", "", "", "") for n in CTRL]

    # bus nets -> edge banks in board-x order (mean x of the chip, channel)
    def net_x(r):
        same = [int(q[4][1:]) for q in rows if q[2] == r[2] and q[4]]
        return (sum(same) / len(same) if same else 0, r[3] or 0)
    edge = sorted((b for b in common if a9[b][0] in EDGE_BANKS), key=lambda b: ball_xy(b))
    if len(edge) < len(rows):
        fails.append("edge banks: %d balls for %d bus nets" % (len(edge), len(rows)))
    ctrl = [r for r in rows if r[1] == "ctrl"]
    bus = sorted((r for r in rows if r[1] != "ctrl"), key=net_x)
    # control nets between ADDR and DATA, where the two groups meet
    split = next(i for i, r in enumerate(bus) if r[2].startswith("ADDR")) if any(
        r[2].startswith("ADDR") for r in bus) else len(bus)
    ordered = bus[:split] + ctrl + bus[split:]
    assigned = [r + (b,) for r, b in zip(ordered, edge)]
    rx_balls = sorted((b for b in common if a9[b][0] == RX_BANK), key=lambda b: ball_xy(b))
    if len(rx_balls) < len(RX):
        fails.append("bank %s: %d balls for %d RX nets" % (RX_BANK, len(rx_balls), len(RX)))
    rx = sorted(RX, key=lambda n: int(contact[n][1:]))
    assigned += [(n, "rx", "", "", contact[n], b) for n, b in zip(rx, rx_balls)]

    # CMOS (2 pass-gates), link, clocks on the far banks
    far = sorted((b for b in common if a9[b][0] not in EDGE_BANKS + [RX_BANK] and b not in CLOCKS.values()),
                 key=lambda b: ball_xy(b))
    cmos = [(n, "cmos", "CMOS%d" % (i // CB3T_CH), i % CB3T_CH + 1, contact[n]) for i, n in enumerate(CMOS)]
    link = [(n, "link", "", "", "") for n in LINK] if cfg["link"] else []
    assigned += [r + (b,) for r, b in zip(cmos + link, far)]
    if len(far) < len(cmos) + len(link):
        fails.append("far banks: %d balls for %d nets" % (len(far), len(cmos) + len(link)))
    clocks = {n: b for n, b in CLOCKS.items() if cfg["link"] or n == "BCLK"}
    assigned += [(n, "clock", "", "", contact.get(n, ""), b) for n, b in clocks.items()]
    assigned += [(n, "pcie", "", "", "", b) for n, b in fixed.items()]
    if not cfg["link"]:
        pcie = {n: ball_of(a9, f) for n, f in PCIE.items()}
        if any(t[b][1] != a9[b][1] for t in tables for b in pcie.values()):
            fails.append("PCIe balls differ between the devices")
        assigned += [(n, "pcie", "", "", "", b) for n, b in pcie.items()]

    balls = [r[5] for r in assigned]
    if len(set(balls)) != len(balls):
        fails.append("a ball used twice")
    for n, b in clocks.items():
        if not all(t[b][2].startswith("CLK") and t[b][2] == a9[b][2] for t in tables):
            fails.append("%s ball %s is no clock input on every device" % (n, b))
    io = [r[5] for r in assigned if r[1] != "pcie"]
    if any(b not in common for b in io):
        fails.append("balls not IO on every device: %s" % [b for b in io if b not in common])
    if fails:
        print("FAIL", *fails, sep="\n  ")
        sys.exit(1)

    out.mkdir(exist_ok=True)
    with open(out / "pins.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["signal", "kind", "ball", "bank", "chip", "channel", "contact"])
        for n, kind, chip, ch, ct, b in assigned:
            w.writerow([n, kind, b, a9[b][0], chip, ch, ct])
    used = {}
    for r in assigned:
        used[a9[r[5]][0]] = used.get(a9[r[5]][0], 0) + 1
    print("%s pins.csv: %d nets, %d of %d common IO balls; per bank %s" % (
        board, len(assigned), len(io), len(common), sorted(used.items())))


if __name__ == "__main__":
    for b in sys.argv[1:] or BOARDS:
        main(b)
