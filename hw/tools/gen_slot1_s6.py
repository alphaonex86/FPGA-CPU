#!/usr/bin/env python3
"""Task S6 (plan/slot1.md): label-wired schematic + netlist for Slot 1.

hw/slot1-cyclonev/slot1-cyclonev.kicad_sch: one sheet; FPGA symbol (one
instance per bank unit), the SC242 CPU symbol (4 units), 20 8-channel
translator chips (A side = FPGA net, B side = S_<sig> contact net),
4 DDR3L x16 dies + the DDR_VTT tracker (cartridge RAM), headers (FPGA
JTAG, passive-serial config, 12 V barrel, board-rail feed), the D23 power
tree + decoupling from slot1_pdn.py (also written to pdn.csv for S7) and
one PWR_FLAG per net hosting a power-input pin.  No wires: every pin gets
a local label at its world position.  One net per physical rail:
VCCPD of the 3.3 V banks sits on VCCIO33, the 1.35 V banks' VCCIO on
VDDR3, the 2.5 V CMOS translator side on VCC_AUX25 (power.md topology).

hw/slot1-cyclonev/slot1-cyclonev.net: kicad-cli netlist export; audit:
- every S5-required signal's net holds the assigned FPGA ball and either
  (a) for the direct signal (BCLK) the contact too, or (b) a translator A
  pin; the S_<signal> net holds the contact and the paired translator B
  pin, and the chip/channel matches pins.csv translator T<dd>c<d>;
- every ddr3.csv ball's net also reaches the die pins of its rank/lane
  (die-pin mapping per D18-MN24: rank0 = die0/die1, rank1 = die2/die3);
- ERC --severity-error: 0 violations.
"""
import csv as csvmod
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import gen_t6_schematic as t6
import pdn
import slot1_pdn

ROOT = t6.ROOT
OUTDIR = ROOT / "hw/slot1-cyclonev"
CPUSYM = ROOT / "sockets/kicad/CPU_SC242.kicad_sym"
FSYM = ROOT / "hw/lib/FPGA_CycloneV_5CEFA9_F484_FPGA.kicad_sym"
LOGIC = ROOT / "hw/lib/Interposer_Logic.kicad_sym"
PARTS = ROOT / "hw/lib/Slot1_Parts.kicad_sym"
FPGACSV = ROOT / "FPGAlist/CycloneV_A9/pins/5cefa9_f484.csv"

BCLK = "BCLK"
VOLTS = {"VCC_1V1": 1.1, "VCC_AUX25": 2.5, "VCCA_FPLL25": 2.5,
         "VCCPGM18": 1.8, "VCCIO33": 3.3, "VDDR3": 1.35}
BRAIL = {"AGTL+ (OD, VTT 1.5 V, VREF 2/3 VTT)": "VTT15",
         "2.5 V CMOS": "VCC_AUX25"}


def slot1_fpga_net(ball, func, conf):
    """net for an FPGA ball not carrying an S5-assigned signal"""
    if func in ("TCK", "TMS", "TDI", "TDO"):
        return "F_" + func
    if conf:
        return "CFG_" + conf
    if func == "GND":
        return "GND"
    if func in ("NC", "DNU"):
        return "NC_" + ball
    if func == "VCC":
        return "VCC_1V1"
    if func == "VCCAUX":
        return "VCCAUX_1V8"
    if func == "VCC_AUX":
        return "VCC_AUX25"               # 2.375-2.625 V, abs max 3.25 V [cvds p.5, p.8]
    if func == "VCCA_FPLL":
        return "VCCA_FPLL25"
    if func == "VCCBAT":
        return "VCC_AUX25"
    if func == "VCCPGM":
        return "VCCPGM18"
    if func.startswith("VCCA_"):
        return "VCCA_0V95"
    if func.startswith("VCC"):
        if func.startswith("VCCPD"):
            # VCCPD follows its bank's VCCIO (cvds p.8 Table 4 note 4):
            # 2.5 V for the 1.35 V banks 7A/8A, 3.3 V for banks 3A..5B
            return "VCC_AUX25" if func.endswith("7A8A") else "VCCIO33"
        if func.endswith(("7A", "8A", "7A8A")):
            return "VDDR3"
        return "VCCIO33"
    if func.startswith("VREF"):
        return "VTTREF0675"              # C14 (7A), B8 (8A): NM23
    if func.startswith("RZQ"):
        return "DDR3_RZQ"
    return "NC_" + ball                  # spare CLK pairs, VQPS, ...


DM_OF = {"T_DM_0": 0, "T_DM_1": 1, "T_DM_2": 2, "T_DM_4": 3}
LANE_OF = {"T_DQS_0": 0, "T_DQS#_0": 0, "T_DQS_1": 1, "T_DQS#_1": 1,
           "T_DQS_2": 2, "T_DQS#_2": 2, "T_DQS_4": 3, "T_DQS#_4": 3}
FIXED_OF = {"T_RAS#": "DDR3_RAS#", "T_CAS#": "DDR3_CAS#", "T_WE#": "DDR3_WE#",
            "T_CK": "DDR3_CK", "T_CK#": "DDR3_CK#",
            "T_CKE_0": "DDR3_CKE0", "T_CKE_1": "DDR3_CKE1",
            "T_ODT_0": "DDR3_ODT0", "T_ODT_1": "DDR3_ODT1",
            "T_CS#_0": "DDR3_CS#0", "T_CS#_1": "DDR3_CS#1",
            "T_RESET#": "DDR3_RESET#", "RZQ_2": "DDR3_RZQ"}


def ddr_net(desig):
    d = desig
    if d.startswith("T_DQ_"):
        n = int(d[5:])
        lane = 0 if n < 8 else 1 if n < 16 else 2 if n < 24 else 3
        idx = n if n < 16 else n - 16 if n < 24 else n - 32
        return "DDR3_DQ%02d" % (lane * 8 + idx)
    if d.startswith("T_DM_"):
        return "DDR3_DM%d" % DM_OF[d]
    if d.startswith("T_DQS"):
        return "DDR3_DQS%d%s" % (LANE_OF[d], "N" if "#" in d else "P")
    if d.startswith("T_A_"):
        return "DDR3_A%d" % int(d[4:])
    if d.startswith("T_BA_"):
        return "DDR3_BA%d" % int(d[5:])
    return FIXED_OF[d]


def die_labels(rank, lane0):
    """label map for one DDR3L_x16_die instance (pins by name)"""
    lab = {}
    for k in range(16):
        bit = 0 if k < 8 else 1
        lab["DQ%d" % k] = "DDR3_DQ%02d" % ((lane0 + bit) * 8 + k % 8)
    for b in (0, 1):
        lab["DQS%dp" % b] = ("DDR3_DQS%dP" % (lane0 + b))
        lab["DQS%dn" % b] = ("DDR3_DQS%dN" % (lane0 + b))
        lab["DM%d" % b] = "DDR3_DM%d" % (lane0 + b)
    for k in range(16):
        lab["A%d" % k] = "DDR3_A%d" % k
    for b in range(3):
        lab["BA%d" % b] = "DDR3_BA%d" % b
    for p in ("CKp", "CKn", "RAS#", "CAS#", "WE#", "RESET#"):
        lab[p] = {"CKp": "DDR3_CK", "CKn": "DDR3_CK#", "RAS#": "DDR3_RAS#",
                  "CAS#": "DDR3_CAS#", "WE#": "DDR3_WE#",
                  "RESET#": "DDR3_RESET#"}[p]
    lab["CS#"] = "DDR3_CS#%d" % rank
    lab["CKE"] = "DDR3_CKE%d" % rank
    lab["ODT"] = "DDR3_ODT%d" % rank
    lab["VREFDQ"] = lab["VREFCA"] = "VTTREF0675"
    for p in ("VDD", "VDDQ"):
        lab[p] = "VDDR3"
    for p in ("VSS", "VSSQ"):
        lab[p] = "GND"
    return lab                     # ZQ stays unsoldered-label (240 R at S9 BOM)


def chips_fill(pinsrows):
    """fill translator chips strictly in S5 pins.csv order (T<dd>c<d>)"""
    chips = []
    for row in pinsrows:
        sig = row["signal"]
        if sig == BCLK:
            continue
        m = re.match(r"T(\d+)c(\d+)$", row["translator"])
        cid, ch = int(m.group(1)), int(m.group(2))
        a = "VDDR3" if row["vccio"] == "1.35 V" else "VCCIO33"
        b = BRAIL[row["contact_level"]]
        if chips and chips[-1]["cid"] == cid:
            c = chips[-1]
            assert a == c["a"] and b == c["b"], (sig, "rail change mid-chip")
        else:
            assert cid == len(chips) + 1, (sig, "translator id gap")
            chips.append(dict(cid=cid, ref="TR%02d" % cid, a=a, b=b))
        assert ch == len(chips[-1]) - 3, (sig, "channel gap")
        chips[-1]["c%d" % ch] = sig
    assert all(len(c) - 4 <= 8 for c in chips), "chip overfilled"
    return chips


def main():
    t1 = list(csvmod.DictReader(open(ROOT / "hw/common/slot1_signals.csv")))
    row_of_pin = {r["pin"]: r for r in t1}
    pinsrows = list(csvmod.DictReader(open(OUTDIR / "pins.csv")))
    sig_of_ball = {r["ball"]: r["signal"] for r in pinsrows}
    parked = {r["pin"] for r in csvmod.DictReader(open(OUTDIR / "parked.csv"))}
    ddr3rows = list(csvmod.DictReader(open(OUTDIR / "ddr3.csv")))

    frows = list(csvmod.DictReader(open(FPGACSV)))
    func_by = {r["ball"]: r["function"] for r in frows}
    conf_by = {r["ball"]: r["config"] for r in frows if r["config"]}

    fsym, csym, tsym, ddsym, tracksym = (
        t6.parse_lib(FSYM)[0], t6.parse_lib(CPUSYM)[0],
        t6.parse_lib(LOGIC)[0],
        next(d for d in t6.parse_lib(PARTS) if d[0] == "DDR3L_x16_die"),
        next(d for d in t6.parse_lib(PARTS) if d[0] == "DDR_VTT_tracker"))

    # net name of every assigned DDR3 ball (audit + FPGA labels)
    ball_ddr = {r["ball"]: ddr_net(r["designator"]) for r in ddr3rows}

    chips = chips_fill(pinsrows)

    fpganet_of = {b: ball_ddr.get(b) or sig_of_ball.get(b)
                  or slot1_fpga_net(b, f, conf_by.get(b, ""))
                  for b, f in func_by.items()}
    errs = t6.cv_supply_errors(func_by, fpganet_of, VOLTS)
    if errs:
        print(f"SUPPLY ERRORS ({len(errs)}):", *errs, sep="\n   ")
        sys.exit(1)

    parts = t6.sheet_head(
        "gen_slot1_s6", "Slot 1 cartridge: 5CEFA9 + 2x DDR3L x16 rank pair",
        [("hw_n:" + fsym[0], fsym[1]), ("cpu_n:" + csym[0], csym[1]),
         ("hw_n:" + tsym[0], tsym[1]), ("hw_n:" + ddsym[0], ddsym[1]),
         ("hw_n:" + tracksym[0], tracksym[1])] + t6.stock_defs(
            [("Connector_Generic", ["Conn_02x03_Odd_Even",
                                    "Conn_02x05_Odd_Even", "Conn_01x03"]),
             ("Connector", ["Barrel_Jack"]),
             ("Device", ["C", "R", "L", "Fuse", "FerriteBead"])])
        + [("hw_n:" + d[0], d[1]) for d in t6.parse_lib(PARTS)
           if d[0] in ("TPS54620", "TPS62130")])
    flagged = set()

    # ---- FPGA units ---------------------------------------------------
    fpnick = "hw_n:" + fsym[0]
    for i, uid in enumerate(sorted(fsym[2], key=int)):
        pins = fsym[2][uid]
        lab = {p["num"]: fpganet_of[p["num"]] for p in pins}
        X = 80.0 + (i % 3) * 95.0
        Y = 35.0 + (i // 3) * 62.0
        parts.append(t6.syminst(fpnick, "U1", X, Y, int(uid), pins, lab))
        flagged |= {lab[p["num"]] for p in pins
                    if not sig_of_ball.get(p["num"])
                    and not ball_ddr.get(p["num"])
                    and func_by.get(p["num"], "").startswith("VCC")}

    # ---- translator chips --------------------------------------------
    tpins = tsym[2]["1"]
    for i, chip in enumerate(chips, 1):
        ref = chip["ref"]
        lab = {}
        for p in tpins:
            num = p["num"]
            if num == "VCCA":
                lab[num] = chip["a"]
            elif num == "VCCB":
                lab[num] = chip["b"]
            elif num == "GND":
                lab[num] = "GND"
            else:
                side = num[0]
                s = chip.get("c" + num[1:])
                if s:
                    lab[num] = s if side == "A" else "S_" + s
                else:
                    lab[num] = "NC_%s_%s" % (ref, num)
        flagged |= t6.power_nets(tpins, lab)
        X = 25.0 + ((i - 1) % 6) * 55.0
        Y = 215.0 + ((i - 1) // 6) * 60.0
        parts.append(t6.syminst("hw_n:" + tsym[0], ref, X, Y, 1, tpins, lab))

    # ---- DDR3 dies + tracker -----------------------------------------
    dpins = ddsym[2]["1"]
    names_of = {p["num"]: p["name"] for p in dpins}
    dnicks = "hw_n:" + ddsym[0]
    for die in range(4):
        rank = 0 if die < 2 else 1
        lane0 = 0 if die in (0, 2) else 2
        d = {k: v for k, v in die_labels(rank, lane0).items()
             if k in set(names_of.values())}
        if "ZQ" in names_of.values():
            d["ZQ"] = "ZQ_RES%d" % die        # 240 Ohm resistor to GND at S9
        lab = {p["num"]: d[names_of[p["num"]]]
               for p in dpins if names_of[p["num"]] in d}
        X = 1030.0 + die * 40.0
        Y = 40.0 + die * 95.0
        parts.append(t6.syminst(dnicks, "U%d" % (3 + die), X, Y, 1, dpins,
                                lab))
    tkpins = tracksym[2]["1"]
    tklab = {}
    for p in tkpins:
        net = {"VIN": "VDDR3", "VTT": "VTTREF0675", "VTTSNS": "VTTREF0675",
               "VDDQ_REF": "VDDR3", "GND": "GND"}[p["name"]]
        tklab[p["num"]] = net
    flagged |= t6.power_nets(tkpins, tklab)
    parts.append(t6.syminst("hw_n:" + tracksym[0], "U7", 1150.0, 430.0, 1,
                            tkpins, tklab))

    # ---- CPU ----------------------------------------------------------
    cnick = "cpu_n:" + csym[0]
    ref_name = "U2"
    ycpu = 305.0
    col = 0
    xs = [430.0, 670.0, 910.0]
    for uid in sorted(csym[2], key=int):
        pins = csym[2][uid]
        lab = {}
        for p in pins:
            cpin = p["num"]
            row = row_of_pin.get(cpin)
            if row is None or row["class"] == "nc" or cpin in parked:
                lab[cpin] = "NC_U2_%s" % cpin     # cartridge tie / open
                continue
            sig, cls, req = row["signal"], row["class"], row["required"]
            if sig == "GND":
                net = "GND"
            elif sig == "VCC_VTT":
                net = "VTT15"
            elif sig == "VCC_CORE":
                net = "VCCCORE"
            elif cls == "power":
                net = "NC_%s_%s" % (ref_name, cpin)   # VCC_L2/VCC5/EMI: open
            elif req == "yes":
                net = sig if sig == BCLK else "S_" + sig
            else:
                net = "NC_%s_%s" % (ref_name, cpin)
            lab[cpin] = net
        flagged |= t6.power_nets(pins, lab)
        ys = [p["y"] for p in pins]
        slot = max(ys) + abs(min(ys)) + 14.0
        if ycpu + slot > 812.0:
            ycpu = 305.0
            col += 1
            assert col < len(xs), "CPU column overflow"
        parts.append(t6.syminst(cnick, "U2", xs[col], ycpu + max(ys) + 8.0,
                                int(uid), pins, lab))
        ycpu += slot

    # ---- headers ------------------------------------------------------
    HD = [("J1", "Connector_Generic:Conn_02x03_Odd_Even",
           ["F_TCK", "GND", "F_TMS", "GND", "F_TDI", "F_TDO"]),
          ("J2", "Connector_Generic:Conn_02x05_Odd_Even",
           ["CFG_nCONFIG", "GND", "CFG_nSTATUS", "GND", "CFG_CONF_DONE",
            "GND", "CFG_DCLK", "GND", "CFG_DATA0", "GND"]),
          ("J3", "Connector:Barrel_Jack", ["V12_IN", "GND"]),
          ("J4", "Connector_Generic:Conn_01x03",
           ["VCCCORE", "VTT15", "GND"])]
    for k, (ref, nick, nets) in enumerate(HD):
        parts.append(t6.header(ref, nick, nets, 700.0, 580.0 + k * 44.0,
                               flagged))

    # ---- power tree + decoupling (D23) ---------------------------------
    pdn_rows = slot1_pdn.build(fpganet_of, [(c["ref"], c["a"], c["b"])
                                            for c in chips])
    parts += pdn.draw(pdn_rows, PARTS, "Slot1Parts", 30.0, 455.0, flagged)
    with open(OUTDIR / "pdn.csv", "w", newline="") as f:
        w = csvmod.DictWriter(f, pdn.CSV_FIELDS)
        w.writeheader()
        w.writerows(pdn_rows)
    parts += t6.flags(flagged, 950.0, 678.0, -12.0)

    schpath = OUTDIR / "slot1-cyclonev.kicad_sch"
    t6.write_sheet(schpath, parts)
    print(f"chips: {len(chips)}")

    # ---- netlist export + audit --------------------------------------
    nets = t6.export_nets(schpath, OUTDIR / "slot1-cyclonev.net")

    def has(nname, ref, pin):
        return (ref, pin) in set(nets.get(nname, []))

    # slot1 signal nets
    fails = []
    for row in pinsrows:
        sig, ball, tr = row["signal"], row["ball"], row["translator"]
        cpin = row["contact"]
        if sig == BCLK:
            if not has(sig, "U1", ball) and not has(sig, "U1", "M9"):
                fails.append(f"{sig}: net missing FPGA ball {ball}")
                continue
            if not has(sig, "U2", cpin):
                fails.append(f"{sig}: BCLK net missing contact {cpin}")
            continue
        snds = set(nets.get(t6.esc("S_" + sig), []))
        if ("U2", cpin) not in snds:
            fails.append(f"{sig}: S_ net missing contact {cpin}: {snds}")
        m = re.match(r"T(\d+)c(\d+)$", tr)
        cid, ch = int(m.group(1)), int(m.group(2))
        ref = "TR%02d" % cid
        if (ref, "A%d" % ch) not in set(nets.get(t6.esc(sig), [])):
            fails.append(f"{sig}: net missing {ref} A{ch}")
        if (ref, "B%d" % ch) not in snds:
            fails.append(f"{sig}: S_ net missing {ref} B{ch}")
        if fpganet_of.get(ball) != sig or \
                not has(t6.esc(sig), "U1", ball):
            fails.append(f"{sig}: net missing FPGA ball {ball}")
    nfail0 = len(fails)

    # DDR3 nets: each ball's net must include U1's ball and the right dies
    die_expect = []          # (net_name, die_ref, die_pin) triples
    for die in range(4):
        rank = 0 if die < 2 else 1
        dref = "U%d" % (3 + die)
        lane0 = 0 if die in (0, 2) else 2
        d = die_labels(rank, lane0)
        for p in dpins:
            n = d.get(p["name"])
            if n:
                die_expect.append((n, dref, p["num"]))
    for nname, dref, dpin in die_expect:
        if not has(nname, dref, dpin):
            fails.append(f"{nname}: net missing die {dref} pin {dpin}")
    # 4 identical dies on the same labels: each shared net expect 4 dies
    for ball, dnet in ball_ddr.items():
        if not has(dnet, "U1", ball):
            fails.append(f"{dnet}: net missing FPGA ball {ball}")
    t6.audit_exit(fails)
    print(f"AUDIT OK: {len(pinsrows)} slot signals ({nfail0} issues would "
          f"have failed), {len(ddr3rows)} DDR3 balls into 4 die instances")

    t6.run_erc(schpath, OUTDIR / "slot1-cyclonev.erc.json")
    print("PASS  S6 checks (netlist audit + ERC)")
    t6.write_project(OUTDIR, "slot1-cyclonev", [
        ("Interposer", "../lib/Interposer_Logic.kicad_sym", "Translator"),
        ("Slot1Parts", "../lib/Slot1_Parts.kicad_sym", "DDR3 die + tracker"),
        ("SocketFPGA", f"../../hw/lib/{fsym[0]}.kicad_sym", "FPGA"),
        ("SocketCPU", f"../../sockets/kicad/{csym[0]}.kicad_sym", "CPU")])


if __name__ == "__main__":
    main()
