#!/usr/bin/env python3
"""Task T6 (plan/interposers.md): label-wired schematic + netlist per variant.

hw/<v>/<v>.kicad_sch: one sheet; FPGA symbol (one instance per bank unit),
CPU PGA370 symbol, the 8-channel translator chips (A side = FPGA net,
B side = S_<sig> socket pad net), headers (CPU TAP, FPGA JTAG, passive-
serial config, 12 V barrel, board-rail feed) and one PWR_FLAG per net that
hosts a power input pin.  No wires: every pin gets a local label at its
world position (instanced pin world point = (X + px, Y - py)).

hw/<v>/<v>.net: kicad-cli netlist export; audit must pass:
- every T1 required signal's net holds the assigned FPGA ball and either
  (a) for direct signals (BCLK/PICCLK) the CPU socket pin too, or
  (b) a translator A pin, while the S_<signal> net holds the CPU socket
  pin and the paired translator B pin;
- ERC --severity-error: 0 violations.
"""
import collections
import csv as csvmod
import collections
import json
import pathlib
import re
import subprocess
import sys
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[2]
TAB = chr(9)
LP = TAB + "("
DIRECT = {"BCLK", "PICCLK"}

V = {"socket370-cyclonev": dict(
        fpgacsv="FPGAlist/CycloneV_A9/pins/5ceba9_f484.csv",
        fsym="hw/lib/FPGA_CycloneV_5CEFA9_F484_FPGA.kicad_sym",
     )}                                  # socket370-ti180 dropped (D10)
CPUSYM = ROOT / "sockets/kicad/CPU_Intel_PGA370.kicad_sym"
LOGIC = ROOT / "hw/lib/Interposer_Logic.kicad_sym"

# T1 level -> translator B-side (socket) supply rail (T3 power.md classes)
BRAIL = {"AGTL+ (OD, VTT-terminated)": "VTT15",
         "CMOS": "VCC3", "CMOS (OD)": "VCC3",
         "CMOS (rail unverified: NM8)": "VCC3",
         "2.5 V-tolerant CMOS": "VCC25",
         "2.5 V (0.5-2.0 V swing)": "VCC25",
         "single-driver active high": "VCC25",
         "active-low presence": "VCC25",
         "passive open/short": "VCC3", "strap": "VCC3"}

# kicad-cli checks
KL = "nice", "-n", "19", "kicad-cli"


def esc(net):
    return net.replace("/", "{slash}")


def block(t, start):
    depth, inq, esc = 0, False, False
    for k in range(start, len(t)):
        ch = t[k]
        if esc:
            esc = False
        elif ch == "\\" and inq:
            esc = True
        elif ch == '"':
            inq = not inq
        elif ch == "(" and not inq:
            depth += 1
        elif ch == ")" and not inq:
            depth -= 1
            if depth == 0:
                return k + 1
    raise ValueError(f"paren mismatch at {start}")


def parse_lib(path):
    """top-level symbols of a .kicad_sym: [(name, text, units{uid:[pin... ]})]"""
    t = path.read_text()
    raw = []
    i = 0
    while True:
        i = t.find(TAB + '(symbol "', i)
        if i < 0:
            break
        s = t.find('"', i) + 1
        e = t.find('"', s)
        name = t[s:e]
        bstart = t.rfind("(", 0, s)
        bend = block(t, bstart)
        # children carry a _N_1 suffix; keep only root symbols
        if not re.search(r"_\d+_[0-9]$", name):
            raw.append((name, t[bstart:bend]))
        i = bend
    out = []
    for name, text in raw:
        units = {}
        k = 0
        while True:
            j = text.find('(symbol "%s_' % name, k)
            if j < 0:
                break
            m = re.match(r'\(symbol "%s_([0-9]+)_[01]"' % re.escape(name),
                         text[j:])
            if not m:
                k = j + 8
                continue
            uid = m.group(1)
            ue = block(text, j)
            pins = []
            for pm in re.finditer(
                    r'\(pin (\w+) (\w+)\s*\(at (-?[\d.]+) (-?[\d.]+) '
                    r'(-?[\d.]+)\)\s*\(length (-?[\d.]+)\)\s*\(name\s*'
                    r'"((?:\\.|[^"])*)"\s*\(effects', text[j:ue]):
                pins.append(dict(el=pm.group(1), x=float(pm.group(3)),
                                 y=float(pm.group(4)), ang=float(pm.group(5)),
                                 lg=float(pm.group(6)), name=pm.group(7)))
            nums = [m.group(1) for m in
                    re.finditer(r'\(number "((?:\\.|[^"])*)"', text[j:ue])]
            for k2, p in enumerate(pins):
                p["num"] = nums[k2] if k2 < len(nums) else ""
            assert all(p["num"] for p in pins), f"{name} unit {uid}"
            units[uid] = pins
            k = ue
        out.append((name, text, units))
    return out


PWRF = ("""		(symbol "power:PWR_FLAG"
			(pin_numbers (hide yes))
			(pin_names (offset 0) (hide yes))
			(exclude_from_sim no)
			(in_bom yes)
			(on_board yes)
			(property "Reference" "#FLG" (at 0 1.905 0) (effects (font (size 1.27 1.27)) (hide yes)))
			(property "Value" "PWR_FLAG" (at 0 3.81 0) (effects (font (size 1.27 1.27))))
			(property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
			(property "Datasheet" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
			(property "Description" "Special symbol for telling ERC where power comes from" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
			(symbol "PWR_FLAG_0_1"
				(pin power_out line (at 0 0 90) (length 0) (name "" (effects (font (size 1.27 1.27)))) (number "1" (effects (font (size 1.27 1.27)))))
			)
			(embedded_fonts no)
		)""",)


STOCK = "/usr/share/kicad/symbols/"


def stock_defs(specs):
    """embedded defs for stock symbols, specs = [(library, [names])],
    plus PWR_FLAG"""
    out = []
    for lib, names in specs:
        t = pathlib.Path(STOCK + lib + ".kicad_sym").read_text()
        for n in names:
            i = t.find('(symbol "' + n + '"')
            if i < 0:
                raise SystemExit("stock symbol missing: " + n)
            text = t[i:block(t, i)]
            q1 = text.index('"', text.index('"') + 1)   # closing quote of name
            inner = text[q1 + 1:].rstrip()
            assert inner.endswith(")"), text[-30:]
            inner = inner[:inner.rfind(")")]           # drop the def close
            out.append((f"{lib}:{n}",
                        f'\t\t(symbol "{lib}:{n}"' + inner.rstrip()
                        + "\n\t\t\t(embedded_fonts no)\n\t\t)"))
    out.append(("power:PWR_FLAG", PWRF[0]))
    return out


def fpga_net(ball, func, conf):
    """net for an FPGA ball not carrying a T5-assigned signal"""
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
    if func == "VCC_AUX":
        return "VCC_AUX25"               # 2.375-2.625 V, abs max 3.25 V [cvds p.5, p.8]
    if func == "VCCA_FPLL":
        return "VCCA_FPLL25"
    if func == "VCCBAT":
        return "VCC_AUX25"
    if func == "VCCPGM":
        return "VCCPGM18"
    # banks per assign_pins.py: 5B at 2.5 V, its VCCPD5B at 2.5 V
    # (cvds p.8 Table 4 note 4)
    if func.startswith("VCCPD"):
        return "VCC_AUX25" if func.endswith("5B") else "VCCPD33"
    if func.startswith("VCCIO"):
        return "VCCIO25" if func.endswith("5B") else "VCCIO33"
    return "MF_" + ball


SUID = None


def label(net, x, y):
    # 6 decimals: KiCad's pin-label connection tolerance is tighter than the
    # 2-decimal rounding gen_lib's row pitch (h/35) produces (e.g. 13.446)
    return (f'{TAB}(label "{esc(net)}" (at {x:.6f} {y:.6f} 0) '
            "(effects (font (size 1.27 1.27)) (justify left bottom)) "
            f'(uuid "{uuid.uuid4()}"))')


NOCONNECT = object()      # labels value: no-connect flag instead of a label


def syminst(nick, ref, X, Y, unit, pins, labels, project="fpga-cpu",
            value=None, footprint=""):
    """instance + one label (or no-connect flag) per labelled pin at
    world (X+px, Y-py)"""
    r = [f"{TAB}(symbol",
         f'{TAB}{TAB}(lib_id "{nick}")',
         f"{TAB}{TAB}(at {X:.2f} {Y:.2f} 0)",
         f"{TAB}{TAB}(unit {unit})",
         f"{TAB}{TAB}(exclude_from_sim no)",
         f"{TAB}{TAB}(in_bom yes)",
         f"{TAB}{TAB}(on_board yes)",
         f"{TAB}{TAB}(dnp no)",
         f'{TAB}{TAB}(uuid "{uuid.uuid4()}")',
         f'{TAB}{TAB}(property "Reference" "{ref}" (at {X:.2f} {Y - 6:.2f} 0)'
         " (effects (font (size 1.27 1.27))))",
         f'{TAB}{TAB}(property "Value" "{value or nick.split(":")[1]}" '
         f"(at {X:.2f} {Y + 6:.2f} 0) "
         "(effects (font (size 1.27 1.27)) (hide yes)))",
         f'{TAB}{TAB}(property "Footprint" "{footprint}" (at {X:.2f} {Y:.2f} 0) '
         "(effects (font (size 1.27 1.27)) (hide yes)))",
         f'{TAB}{TAB}(property "Datasheet" "" (at {X:.2f} {Y:.2f} 0) '
         "(effects (font (size 1.27 1.27)) (hide yes)))",
         f'{TAB}{TAB}(property "Description" "" (at {X:.2f} {Y:.2f} 0) '
         "(effects (font (size 1.27 1.27)) (hide yes)))"]
    for p in pins:
        r.append(f'{TAB}{TAB}(pin "{p["num"]}" (uuid "{uuid.uuid4()}"))')
    r += [f"{TAB}{TAB}(instances (project \"{project}\" "
          f"(path \"/{SUID}\" (reference \"{ref}\") (unit {unit}))))",
          f"{TAB})"]
    out = "\n".join(r)
    for p in pins:
        net = labels.get(p["num"])
        if net is NOCONNECT:
            out += (f'\n{TAB}(no_connect (at {X + p["x"]:.6f} '
                    f'{Y - p["y"]:.6f}) (uuid "{uuid.uuid4()}"))')
        elif net:
            out += "\n" + label(net, X + p["x"], Y - p["y"])
    return out


def defs_into(defs):
    out = []
    for nick, text in defs:
        i = text.index('(symbol "')
        j = text.index('"', i + 9)          # closing quote of the name
        inner = text[j + 1:].rstrip()
        assert inner.endswith(")"), text[-30:]
        inner = inner[:inner.rfind(")")]    # drop the def close, re-add below
        inner = inner.replace("(embedded_fonts no)", "")   # dedupe (re-added)
        out.append(f'\t\t(symbol "{nick}"' + " ".join(inner.split())
                   + f" (embedded_fonts no))")
    return out


PWRPINS = [dict(num="1", x=0.0, y=0.0, el="power_out", name="")]


def sheet_head(generator, title, defs):
    """sets SUID; returns the sheet's opening lines with embedded defs"""
    global SUID
    SUID = str(uuid.uuid4())
    return (["(kicad_sch", "(version 20250114)", f'(generator "{generator}")',
             '(generator_version "9.0")', f'(uuid "{SUID}")', '(paper "A0")',
             f'\t(title_block (title "{title}"))', "\t(lib_symbols"]
            + defs_into(defs) + ["\t)"])


def power_nets(pins, labels):
    return {labels[p["num"]] for p in pins
            if p["el"] == "power_in" and labels.get(p["num"])}


def header(ref, nick, nets, X, Y, flagged, project="fpga-cpu", footprint=""):
    """stock connector instance, pin k (by number) -> nets[k]"""
    lib, name = nick.split(":")
    d = next(d for d in parse_lib(pathlib.Path(STOCK + lib + ".kicad_sym"))
             if d[0] == name)
    pins = sorted((p for ps in d[2].values() for p in ps),
                  key=lambda p: int(p["num"]))
    assert len(pins) == len(nets), (ref, len(pins), len(nets))
    lab = {p["num"]: n for p, n in zip(pins, nets)}
    flagged |= power_nets(pins, lab)
    return syminst(nick, ref, X, Y, 1, pins, lab, project=project, footprint=footprint)


def flags(nets, X, Y0, dy, project="fpga-cpu"):
    """one PWR_FLAG per net hosting a power-input pin"""
    print(f"flags: {len(nets)} nets: {sorted(nets)}")
    return [syminst("power:PWR_FLAG", f"#FLG{n}", X, Y0 + (n - 1) * dy, 1,
                    PWRPINS, {"1": net}, project=project)
            for n, net in enumerate(sorted(nets), 1)]


def write_sheet(path, parts):
    parts = parts + [f'{TAB}(sheet_instances (path "/" (page "1")))',
                     "\t(embedded_fonts no)", ")"]
    out = "\n".join(parts)
    depth, quoted = 0, False
    for ch in out:
        if ch == '"':
            quoted = not quoted
        elif ch in "()" and not quoted:
            depth += 1 if ch == "(" else -1
    assert depth == 0, f"unbalanced by {depth}"
    seen = collections.Counter(re.findall(
        r'\(reference "([^"]+)"\) \(unit (\d+)\)', out))
    dups = sorted(k for k, n in seen.items() if n > 1)
    if dups:
        sys.exit(f"duplicate (reference, unit): {dups[:10]}")
    path.write_text(out)
    print(f"wrote {path.relative_to(ROOT)} ({len(out) // 1000} kB)")


def export_nets(schpath, netf):
    """kicad-cli netlist export -> {net name: [(ref, pin)]}"""
    r = subprocess.run([*KL, "sch", "export", "netlist", "--format",
                        "kicadsexpr", "-o", str(netf), str(schpath)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr or r.stdout)
        sys.exit("netlist export failed")
    net = netf.read_text()
    nets = {}
    for m in re.finditer(r'\(net\s*\n\s*\(code "[^"]+"\)\s*\(name "([^"]*)"\)',
                         net):
        body = net[m.end():block(net, m.start())]
        nets[m.group(1).lstrip("/")] = re.findall(
            r'\(ref "([^"]*)"\)\s*\(pin "([^"]*)"\)', body)
    return nets


def audit_exit(fails):
    if fails:
        print(f"AUDIT FAILURES ({len(fails)}):")
        for f in fails[:25]:
            print("   ", f)
        sys.exit(1)


def run_erc(schpath, ercf):
    r = subprocess.run([*KL, "sch", "erc", "--severity-error",
                        "--exit-code-violations", "--format", "json",
                        "-o", str(ercf), str(schpath)],
                       capture_output=True, text=True)
    if r.returncode != 0 and not ercf.exists():
        print(r.stderr or r.stdout)
        sys.exit("erc crashed")
    if r.returncode != 0:
        j = json.load(open(ercf))
        viol = [v for sh in j.get("sheets", [])
                for v in sh.get("violations", [])]
        print(f"ERC ERRORS ({len(viol)}):")
        for v in viol[:15]:
            print("  ", v.get("severity"), v.get("type"),
                  str(v.get("description"))[:110])
            for it in v.get("items", [])[:3]:
                print("      -", str(it.get("description"))[:100])
        sys.exit(1)
    print("ERC: 0 errors")


def write_project(outdir, name, libs):
    """.kicad_pro + sym-lib-table; libs = [(name, uri, descr)]. An
    existing .kicad_pro keeps its other sections (the board settings and
    net classes a placement step wrote)"""
    path = outdir / f"{name}.kicad_pro"
    pro = json.loads(path.read_text()) if path.exists() else {}
    pro["meta"] = {"filename": f"{name}.kicad_pro", "version": 3}
    pro["sheets"] = [[SUID, "Root"]]
    path.write_text(json.dumps(pro, indent=2, sort_keys=True))
    (outdir / "sym-lib-table").write_text(
        "(sym_lib_table\n  (version 7)\n" + "".join(
            f'  (lib (name "{n}")(type "KiCad")(uri "${{KIPRJMOD}}/{u}")'
            f'(options "")(descr "{d}"))\n' for n, u, d in libs) + ")\n")
    print(f"wrote .kicad_pro + sym-lib-table in {outdir.relative_to(ROOT)}/")


# Cyclone V supply bands [cvds p.8-9 Table 4]
CV_BAND = {"VCC": (1.07, 1.13), "VCC_AUX": (2.375, 2.625),
           "VCCA_FPLL": (2.375, 2.625), "VCCBAT": (1.2, 3.0)}
CV_VCCIO = (3.3, 3.0, 2.5, 1.8, 1.5, 1.35, 1.25, 1.2)
CV_VCCPGM = (3.3, 3.0, 2.5, 1.8)


def cv_supply_errors(func_by, net_of, volts):
    """every Cyclone V supply ball on a net whose nominal voltage (volts)
    fits its Table 4 band; VCCPD = 2.5 V for VCCIO <= 2.5 V, else = VCCIO,
    for every bank sharing that VCCPD ball (note 4)"""
    errs, vccio = [], {}
    for b, f in func_by.items():
        if f.startswith("VCCIO"):
            vccio.setdefault(f[5:], set()).add(volts.get(net_of[b]))
    for bank, vs in vccio.items():
        if len(vs) != 1 or not vs <= set(CV_VCCIO):
            errs.append(f"VCCIO{bank}: nets at {vs}, allowed one of {CV_VCCIO}")
    for b, f in func_by.items():
        v = volts.get(net_of[b])
        if f in CV_BAND:
            lo, hi = CV_BAND[f]
            if v is None or not lo <= v <= hi:
                errs.append(f"{b} {f} on {net_of[b]} = {v} V, band {lo}-{hi}")
        elif f == "VCCPGM" and v not in CV_VCCPGM:
            errs.append(f"{b} VCCPGM on {net_of[b]} = {v} V")
        elif f.startswith("VCCPD"):
            for bank in re.findall(r"\d[A-Z]", f[5:]):
                io = next(iter(vccio.get(bank, {None})))
                need = None if io is None else 2.5 if io <= 2.5 else io
                if v != need:
                    errs.append(f"{b} {f} on {net_of[b]} = {v} V, bank {bank}"
                                f" VCCIO {io} V needs {need} V")
    return errs


VCCIO_NET = {"2.5 V": "VCCIO25", "3.3 V": "VCCIO33"}


def bank_of_supply(func):
    """bank a VCCIO ball powers: VCCIO3B -> 3B"""
    return func[5:] if re.fullmatch(r"VCCIO\d[A-Z]", func) else None


def bank_vccio_errors(pinsrows, func_by, net_of):
    """every bank pins.csv uses has all its VCCIO balls on that VCCIO rail"""
    errs = []
    for bank, vccio in {(r["bank"].removeprefix("BANK"), r["vccio"])
                        for r in pinsrows}:
        balls = [b for b, f in func_by.items() if bank_of_supply(f) == bank]
        nets = {net_of[b] for b in balls}
        if nets != {VCCIO_NET[vccio]}:
            errs.append(f"bank {bank} at {vccio}: VCCIO balls on {nets}")
    return errs


# nominal volts of the socket370-cyclonev rail nets (power.md)
S370_CV_VOLTS = {"VCC_1V1": 1.1, "VCC_AUX25": 2.5, "VCCA_FPLL25": 2.5,
                 "VCCPGM18": 1.8, "VCCIO25": 2.5, "VCCIO33": 3.3,
                 "VCCPD33": 3.3}


def main():
    variant = sys.argv[1] if len(sys.argv) > 1 else ""
    if variant not in V:
        sys.exit("usage: gen_t6_schematic.py socket370-cyclonev")
    cfg = V[variant]
    outdir = ROOT / "hw" / variant
    t1 = list(csvmod.DictReader(open(ROOT / "hw/common/socket370_signals.csv")))
    level_of = {r["signal"]: r["level"] for r in t1}
    pinsrows = list(csvmod.DictReader(open(outdir / "pins.csv")))
    ball_of = {r["signal"]: r["ball"] for r in pinsrows}
    sig_of_ball = {b: s for s, b in ball_of.items()}

    frows = list(csvmod.DictReader(open(ROOT / cfg["fpgacsv"])))
    func_by = {r["ball"]: r["function"] for r in frows}
    conf_by = {r["ball"]: r["config"] for r in frows if r["config"]}

    fsym, csym, tsym = (parse_lib(ROOT / cfg["fsym"])[0],
                        parse_lib(CPUSYM)[0], parse_lib(LOGIC)[0])

    fpganet_of = {b: sig_of_ball.get(b) or fpga_net(b, f,
                                                    conf_by.get(b, ""))
                  for b, f in func_by.items()}
    errs = bank_vccio_errors(pinsrows, func_by, fpganet_of)
    errs += cv_supply_errors(func_by, fpganet_of, S370_CV_VOLTS)
    if errs:
        print(f"SUPPLY ERRORS ({len(errs)}):", *errs, sep="\n   ")
        sys.exit(1)

    # ---- translator chip fill: group by (FPGA bank vccio, soc rail) ----
    groups = collections.defaultdict(list)
    for row in pinsrows:
        sig = row["signal"]
        if sig in DIRECT:
            continue
        a = VCCIO_NET[row["vccio"]]
        groups[(a, BRAIL[level_of[sig]])].append(sig)
    chips = []
    for key in sorted(groups):
        gs = groups[key]
        for i in range(0, len(gs), 8):
            sl = gs[i:i + 8]
            chips.append(dict(a=key[0], b=key[1],
                              **{f"A{n}": s for n, s in enumerate(sl, 1)}))
    # ---- sheet ----
    parts = sheet_head(
        "gen_t6", "Socket370 interposer: " + variant.replace("socket370-", ""),
        [(f"hw_n:{fsym[0]}", fsym[1]),
         (f"cpu_n:{csym[0]}", csym[1]),
         (f"hw_n:{tsym[0]}", tsym[1])] + stock_defs(
            [("Connector_Generic", ["Conn_02x03_Odd_Even", "Conn_02x05_Odd_Even",
                                    "Conn_02x06_Odd_Even", "Conn_01x05"]),
             ("Connector", ["Barrel_Jack"])]))
    flagged = set()

    # ---- FPGA units ----
    fpnick = "hw_n:" + fsym[0]
    uids = sorted(fsym[2], key=int)
    ncols = 2
    for i, uid in enumerate(uids):
        pins = fsym[2][uid]
        lab = {p["num"]: fpganet_of[p["num"]] for p in pins}
        X = 80.0 + (i % ncols) * 95.0
        Y = 35.0 + (i // ncols) * 62.0
        parts.append(syminst(fpnick, "U1", X, Y, int(uid), pins, lab))
        # FPGA rail nets (core, aux, PLL, per-bank VCCIO/VCCPD) get a
        # PWR_FLAG as their driver
        flagged |= {lab[p["num"]] for p in pins
                    if not sig_of_ball.get(p["num"])
                    and func_by.get(p["num"], "").startswith("VCC")}

    # ---- translator chips ----
    tpins = tsym[2]["1"]
    for i, chip in enumerate(chips, 1):
        ref = f"TR{i}"
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
                s = chip.get("A" + num[1:])
                lab[num] = (s if num[0] == "A" else "S_" + s) if s \
                    else f"NC_{ref}_{num}"
        flagged |= power_nets(tpins, lab)
        X = 25.0 + ((i - 1) % 6) * 55.0
        Y = 395.0 + ((i - 1) // 6) * 58.0
        parts.append(syminst("hw_n:" + tsym[0], ref, X, Y, 1, tpins, lab))
        chip["ref"] = ref

    # ---- CPU ----
    cnick = "cpu_n:" + csym[0]
    row_of_pin = {r["pin"]: r for r in t1}
    ycpu = 25.0
    col = 0
    xs = [480.0, 700.0]
    for uid in sorted(csym[2], key=int):
        pins = csym[2][uid]
        lab = {}
        for p in pins:
            row = row_of_pin.get(p["num"])
            # no row / Reserved (no_connect) pins stay bare: a label on
            # them dangles, ERC is clean with the pin left bare
            if row is None or row["class"] == "nc":
                continue
            sig = row["signal"]
            if row["required"] == "yes":
                lab[p["num"]] = sig if sig in DIRECT else "S_" + sig
            else:
                lab[p["num"]] = "GND" if sig == "GND" else "S_" + sig
        flagged |= power_nets(pins, lab)
        ys = [p["y"] for p in pins]
        slot = max(ys) + abs(min(ys)) + 14.0
        parts.append(syminst(cnick, "U2", xs[col], ycpu + max(ys) + 8.0,
                             int(uid), pins, lab, project=variant))
        ycpu += slot
        if ycpu > 780.0:
            ycpu = 25.0
            col += 1

    # ---- headers ----
    HD = [("J1", "Connector_Generic:Conn_02x06_Odd_Even",
           ["TCK", "GND", "TMS", "GND", "TDI", "GND", "TDO", "GND",
            "TRST#", "GND", "PRDY#", "PREQ#"]),
          ("J2", "Connector_Generic:Conn_02x03_Odd_Even",
           ["F_TCK", "GND", "F_TMS", "GND", "F_TDI", "F_TDO"]),
          ("J3", "Connector_Generic:Conn_02x05_Odd_Even",
           ["CFG_nCONFIG", "GND", "CFG_nSTATUS", "GND", "CFG_CONF_DONE",
            "GND", "CFG_DCLK", "GND", "CFG_DATA0", "GND"]),
          ("J4", "Connector:Barrel_Jack", ["V12", "GND"]),
          ("J5", "Connector_Generic:Conn_01x05",
           ["S_VCCCORE", "VTT15", "VCC3", "VCC25", "GND"])]
    for k, (ref, nick, nets) in enumerate(HD):
        parts.append(header(ref, nick, nets, 700.0, 690.0 + k * 34.0,
                            flagged, project=variant))
    parts += flags(flagged, 950.0, 690.0, 12.0, project=variant)

    schpath = outdir / f"{variant}.kicad_sch"
    write_sheet(schpath, parts)
    print(f"chips: {len(chips)}")

    # ---- netlist export + audit ----
    nets = export_nets(schpath, outdir / f"{variant}.net")
    fails = []
    for row in pinsrows:
        sig, ball = row["signal"], row["ball"]
        cpin = next(r["pin"] for r in t1
                    if r["signal"] == sig and r["required"] == "yes")
        if sig in DIRECT:
            have = set(nets.get(sig, []))
            if not {("U1", ball), ("U2", cpin)} <= have:
                fails.append(f"{sig}: direct net has {sorted(have)}")
            continue
        snds = nets.get("S_" + sig, [])
        if ("U2", cpin) not in snds:
            fails.append(f"{sig}: S_ net missing CPU {cpin}: {snds}")
        chip = next(c for c in chips
                    if any(c.get(f"A{n}") == sig for n in range(1, 9)))
        an = next(n for n in range(1, 9) if chip.get(f"A{n}") == sig)
        if (chip["ref"], f"A{an}") not in nets.get(sig, []):
            fails.append(f"{sig}: net missing TR A{an}")
        if (chip["ref"], f"B{an}") not in snds:
            fails.append(f"{sig}: S_ net missing TR B{an}")
        if fpganet_of.get(ball) != sig or ("U1", ball) not in nets.get(sig, []):
            fails.append(f"{sig}: net missing FPGA ball {ball}")
    audit_exit(fails)
    print(f"AUDIT OK: {len(pinsrows)} required signals connected"
          f" ({len(DIRECT)} direct, {len(pinsrows) - len(DIRECT)} via"
          f" {len(chips)} chips)")

    run_erc(schpath, outdir / f"{variant}.erc.json")
    print("PASS  T6 checks (netlist audit + ERC)")
    write_project(outdir, variant, [
        ("Interposer", "../lib/Interposer_Logic.kicad_sym", "Translator"),
        ("SocketFPGA", f"../lib/{fsym[0]}.kicad_sym", "FPGA"),
        ("Socket370CPU", f"../../sockets/kicad/{csym[0]}.kicad_sym", "CPU")])


if __name__ == "__main__":
    main()
