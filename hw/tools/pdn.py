"""Shared power tree + decoupling builder (TPS54620 / TPS62130 stages,
Cyclone V F484 via-in-pad decoupling pairs) for the generated boards.

A board module (slot1_pdn.py, socket3_pdn.py) lists its stages and caps
with a Parts list; its schematic generator draws the rows with draw() and
writes them as pdn.csv for its placement step. Sources:
  tps54620  sockets/parts/ti_tps54620_6a_buck.pdf
  tps62130  sockets/parts/ti_tps62130_3a_buck.pdf
"""
import math
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
U1_FP = ROOT / "hw/lib/Interposer.pretty/FPGA_CycloneV_5CEFA9_F484_BGA.kicad_mod"
VREF = 0.8                              # tps54620 p.6, tps62130 p.14 Eq 6
E96 = [1.00, 1.02, 1.05, 1.07, 1.10, 1.13, 1.15, 1.18, 1.21, 1.24, 1.27, 1.30,
       1.33, 1.37, 1.40, 1.43, 1.47, 1.50, 1.54, 1.58, 1.62, 1.65, 1.69, 1.74,
       1.78, 1.82, 1.87, 1.91, 1.96, 2.00, 2.05, 2.10, 2.15, 2.21, 2.26, 2.32,
       2.37, 2.43, 2.49, 2.55, 2.61, 2.67, 2.74, 2.80, 2.87, 2.94, 3.01, 3.09,
       3.16, 3.24, 3.32, 3.40, 3.48, 3.57, 3.65, 3.74, 3.83, 3.92, 4.02, 4.12,
       4.22, 4.32, 4.42, 4.53, 4.64, 4.75, 4.87, 4.99, 5.11, 5.23, 5.36, 5.49,
       5.62, 5.76, 5.90, 6.04, 6.19, 6.34, 6.49, 6.65, 6.81, 6.98, 7.15, 7.32,
       7.50, 7.68, 7.87, 8.06, 8.25, 8.45, 8.66, 8.87, 9.09, 9.31, 9.53, 9.76]
E12 = [1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2]

C0402 = "Capacitor_SMD:C_0402_1005Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
C1206 = "Capacitor_SMD:C_1206_3216Metric"
C1210 = "Capacitor_SMD:C_1210_3225Metric"
R0402 = "Resistor_SMD:R_0402_1005Metric"
CPAIR = "Pwr:C_0402_P1.00"              # 0402 on two 1.0 mm via-in-pads (S7)
QFN14 = "Pwr:TI_RHL0014A"               # tps54620 p.45 land pattern (S7)
QFN16 = "Package_DFN_QFN:VQFN-16-1EP_3x3mm_P0.5mm_EP1.68x1.68mm"
L_BIG = {"MSS1048": "Inductor_SMD:L_Coilcraft_MSS1048-XXX",   # tps54620 p.25 example family
         "FXL1040": "Inductor_SMD:L_Changjiang_FXL1040"}      # LCSC-stocked 10 x 11.5 mm
L_SMALL = "Inductor_SMD:L_Coilcraft_XxL4020"     # tps62130 Table 9-1 p.13

FARAD = {"p": 1e-12, "n": 1e-9, "u": 1e-6}
# inductor (Isat at 20 % drop, Irms at 20 C rise) [Coilcraft Doc 462-1
# rev 10/15/08 MSS1048; Doc 745-1 rev 02/10/11 XFL4020; changjiang_fxl1040
# max columns]; XFL4020-102: LCSC C5355380 (lcsc_C5355380.html, drop not stated)
L_RATING = {"MSS1048-682": (5.00, 4.52), "MSS1048-152": (7.80, 7.41),
            "XFL4020-222": (3.5, 6.0), "FXL1040-6R8": (9.6, 7.0), "XFL4020-102": (5.4, 11.0)}


def l_check(name, part, iout, ripple):
    """peak = Iout + ripple/2 <= Isat(20 %), Iout <= Irms. TI's most
    conservative rule, Isat >= switch current limit [tps54620 p.25], is
    not met by these parts (8 A tps54620 p.6, 4.9 A tps62130 p.5)"""
    isat, irms = L_RATING[part]
    ipk = iout + ripple / 2
    print(f"  {name} {part}: Ipk {ipk:.2f} A <= Isat20% {isat} A, "
          f"Iout {iout} A <= Irms {irms} A")
    assert ipk <= isat and iout <= irms, (name, part)


def farads(v):
    m = re.match(r"([\d.]+)([pnu])F", v)
    return float(m.group(1)) * FARAD[m.group(2)]


def series(x, table):
    """nearest value of a decade table (E96 / E12)"""
    d = 10 ** math.floor(math.log10(x))
    return min((t * d for t in table + [table[0] * 10]),
               key=lambda v: abs(math.log(v / x)))


def kohm(r):
    return f"{r / 1e3:.3g}k"


def tps54620(name, vin, vout, iout, cout_n, cout_v, cout_eff, l_nom, dv,
             lpart):
    """design values per the tps54620 p.25-29 procedure; prints the check"""
    fsw = 480e3
    rrt = 48000 * (fsw / 1e3) ** -0.997 - 2               # Eq 13 p.19 (kOhm)
    lmin = (vin * 1.1 - vout) / (iout * 0.3) * vout / (vin * 1.1 * fsw)  # Eq 18
    kind = (vin * 1.1 - vout) / l_nom * vout / (vin * 1.1 * fsw) / iout
    r6 = 10e3
    r5 = series((vout - VREF) / VREF * r6, E96)           # Eq 29 p.28
    vset = VREF * (1 + r5 / r6)
    fpmod = iout / (2 * math.pi * vout * cout_eff)        # Eq 31 p.28
    fco = math.sqrt(fpmod * fsw / 2)                      # Eq 34 p.29
    r2 = series(2 * math.pi * fco * vout * cout_eff
                / (1300e-6 * VREF * 16), E96)             # Eq 35, gm p.6
    c3 = series(vout * cout_eff / (iout * r2), E12)       # Eq 36 p.29
    comin = 2 * 1.0 / (fsw * dv)                          # Eq 22 p.26, 1 A step
    print(f"  {name}: Rrt {rrt:.1f}k, L {l_nom * 1e6:.1f}uH (Eq18 {lmin * 1e6:.2f},"
          f" Kind {kind:.2f}), R5 {kohm(r5)} -> {vset:.4f} V, fco "
          f"{fco / 1e3:.1f} kHz, R2 {kohm(r2)}, C3 {c3 * 1e9:.1f} nF, Cout "
          f"{cout_n}x{cout_v} eff {cout_eff * 1e6:.0f}uF >= {comin * 1e6:.0f}uF")
    assert 0.1 <= kind <= 0.4 and cout_eff >= comin, name
    l_check(name, lpart, iout, kind * iout)
    return dict(rrt=series(rrt * 1e3, E96), r5=r5, r6=r6, r2=r2, c3=c3,
                vset=vset)


def tps62130_r1(vout, band, vref=VREF):
    """R2 = 100 k <= 400 k; R1 = R2 (Vout/0.8 - 1) [tps62130 Eq 6 p.14]:
    the E96 R1 nearest to vout whose output stays inside the rail band"""
    ideal = 100e3 * (vout / vref - 1)
    d = 10 ** math.floor(math.log10(ideal))
    cands = [t * d * s for t in E96 for s in (0.1, 1, 10)
             if band[0] <= vref * (1 + t * d * s / 100e3) <= band[1]]
    r1 = min(cands, key=lambda r: (round(abs(vref * (1 + r / 100e3) - vout), 4),
                                   -r))          # tie: the higher output
    return r1, vref * (1 + r1 / 100e3)


def nf(c):
    return f"{c * 1e9:.3g}nF"


class Parts:
    def __init__(self, lib, taken=()):
        """lib: the board's symbol library nickname holding the TPS parts;
        taken: references the sheet already uses (skipped)"""
        self.rows, self.count, self.lib = [], {}, lib
        self.taken = set(taken)
        self.cout_max = {}                # converter output net -> proven nominal capacitance (F)

    def add(self, prefix, sym, value, fpn, nets, kind, a="", b="", side="F"):
        k = self.count.get(prefix, 0) + 1
        while f"{prefix}{k}" in self.taken:
            k += 1
        self.count[prefix] = k
        ref = f"{prefix}{k}"
        self.rows.append(dict(ref=ref, sym=sym, value=value, footprint=fpn,
                              nets="|".join(nets), side=side, kind=kind,
                              a=a, b=b))
        return ref

    def c(self, value, fpn, net, kind, a="", b="", side="F", gnd="GND"):
        return self.add("C", "Device:C", value, fpn, [net, gnd], kind, a, b,
                        side)

    def r(self, value, n1, n2, kind, a=""):
        return self.add("R", "Device:R", value, R0402, [n1, n2], kind, a)

    def done(self):
        """the rows; exit 1 when a converter output carries more nominal capacitance than proven stable"""
        for net, cmax in self.cout_max.items():
            total = sum(farads(r["value"]) for r in self.rows
                        if r["sym"] == "Device:C" and r["nets"].split("|")[0] == net)
            if total > cmax:
                sys.exit(f"FAIL: {net} carries {total * 1e6:.0f} uF, its converter is proven to {cmax * 1e6:.0f} uF")
        return self.rows


def buck54620(P, p, vin, vout_net, vout, iout, cout, en, pg, l_nom, lpart,
              dv):
    n, v, eff = cout
    d = tps54620(p, vin[1], vout, iout, n, v, eff, l_nom, dv, lpart)
    st = ("stage", p)
    nets = {"1": f"{p}_RT", "2": "GND", "3": "GND", "4": vin[0], "5": vin[0],
            "6": vin[0], "7": f"{p}_FB", "8": f"{p}_COMP", "9": f"{p}_SS",
            "10": en or f"NC_{p}_10", "11": f"{p}_SW", "12": f"{p}_SW",
            "13": f"{p}_BOOT", "14": pg, "15": "GND"}
    P.add("PS", f"{P.lib}:TPS54620", "TPS54620RHL", QFN14,
          [nets[str(k)] for k in range(1, 16)], *st)
    P.add("L", "Device:L", f"{l_nom * 1e6:.2g}uH {lpart}", L_BIG[lpart[:7]],
          [f"{p}_SW", vout_net], *st)
    P.c("10uF/25V", C1210, vin[0], *st)                   # PVIN, p.27
    P.c("4.7uF/25V", C0805, vin[0], *st)                  # VIN, p.27
    for _ in range(n):
        P.c(v, C1206, vout_net, *st)
    P.add("C", "Device:C", "100nF", C0402, [f"{p}_BOOT", f"{p}_SW"], *st)  # p.28
    P.c("10nF", C0402, f"{p}_SS", *st)                    # Eq 28: 3.5 ms
    P.c(nf(d["c3"]), C0402, f"{p}_CZ", *st)
    P.r(kohm(d["r2"]), f"{p}_COMP", f"{p}_CZ", *st)
    P.r(kohm(d["rrt"]), f"{p}_RT", "GND", *st)
    P.r(kohm(d["r5"]), vout_net, f"{p}_FB", *st)
    P.r(kohm(d["r6"]), f"{p}_FB", "GND", *st)
    P.r("100k", pg, "V5", *st)                            # PWRGD open drain


def buck62130(P, p, vout_net, vout, band, en, pg):
    r1, vset = tps62130_r1(vout, band)
    print(f"  {p}: R1 {kohm(r1)} / R2 100k -> {vset:.4f} V")
    vin = 5.5                                   # 5 V rail + 10 %
    l_check(p, "XFL4020-222", 3.0,              # 3 A max [tps62130 p.1]
            (vin - vout) / 2.2e-6 * vout / (vin * 2.5e6))
    st = ("stage", p)
    # 2.2 uH: 400 uF nominal lab-stable, 800 uF unstable [slva463a p.1 Table 1]; Table 9-2 p.14 stops at 200 uF
    P.cout_max[vout_net] = 400e-6
    nets = {"1": f"{p}_SW", "2": f"{p}_SW", "3": f"{p}_SW",
            "4": pg or f"NC_{p}_4", "5": f"{p}_FB", "6": "GND", "7": "GND",
            "8": "GND", "9": f"{p}_SS", "10": "V5", "11": "V5", "12": "V5",
            "13": en, "14": vout_net, "15": "GND", "16": "GND", "17": "GND"}
    P.add("PS", f"{P.lib}:TPS62130", "TPS62130RGT", QFN16,
          [nets[str(k)] for k in range(1, 18)], *st)
    # Table 9-1 p.13: L1, C1, C3, C5, C7, R3
    P.add("L", "Device:L", "2.2uH XFL4020-222", L_SMALL, [f"{p}_SW", vout_net], *st)
    P.c("10uF/25V", C1210, "V5", *st)
    P.c("22uF/6.3V", C0805, vout_net, *st)
    P.c("100nF", C0402, "V5", *st)
    P.c("3.3nF", C0402, f"{p}_SS", *st)
    P.r(kohm(r1), vout_net, f"{p}_FB", *st)
    P.r("100k", f"{p}_FB", "GND", *st)
    if pg:
        P.r("100k", pg, "V5", *st)
    return vset


def u1_balls():
    t = U1_FP.read_text()
    return {m.group(1): (float(m.group(2)), float(m.group(3))) for m in
            re.finditer(r'\(pad "(\w+)" smd \w+ \(at (-?[\d.]+) (-?[\d.]+)\)', t)}


def u1_pairs(net_of_ball, small):
    """disjoint (supply ball, GND ball) neighbours at 1.0 mm, one per
    small cap (small: rail -> values), rails in the dict order; Kuhn augmenting paths keep every
    earlier match, so an earlier rail never loses a pair to a later one"""
    pos = u1_balls()
    at = {(round(x, 2), round(y, 2)): b for b, (x, y) in pos.items()}
    gnd_of = {}                          # GND ball -> supply ball
    pairs = {}

    def nbrs(b):
        x, y = pos[b]
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            g = at.get((round(x + dx, 2), round(y + dy, 2)))
            if g and net_of_ball.get(g) == "GND":
                yield g

    def augment(s, seen):
        for g in nbrs(s):
            if g in seen:
                continue
            seen.add(g)
            if g not in gnd_of or augment(gnd_of[g], seen):
                gnd_of[g] = s
                return True
        return False

    for rail, caps in small.items():
        got = 0
        for s in sorted(b for b, n in net_of_ball.items() if n == rail):
            if got < len(caps) and augment(s, set()):
                got += 1
    for g, s in gnd_of.items():
        pairs.setdefault(net_of_ball[s], []).append((s, g))
    return {r: sorted(v) for r, v in pairs.items()}


CSV_FIELDS = ["ref", "sym", "value", "footprint", "nets", "side", "kind", "a", "b"]


def draw(rows, libpath, lib, x0, y0, flagged):
    """sheet symbols + labels of every row on an 18-column grid from
    (x0, y0); lib parts (regulators) from libpath, the rest from the stock
    Device library; adds the rows' power nets to flagged"""
    import gen_t6_schematic as t6
    symdef = {d[0]: d for d in t6.parse_lib(libpath)}
    stock = {d[0]: d for d in t6.parse_lib(
        pathlib.Path(t6.STOCK + "Device.kicad_sym"))}
    out = []
    for k, row in enumerate(rows):
        rlib, name = row["sym"].split(":")
        big = rlib == lib
        d = symdef[name] if big else stock[name]
        pins = sorted((p for ps in d[2].values() for p in ps),
                      key=lambda p: int(p["num"]))
        nets = row["nets"].split("|")
        assert len(nets) == len(pins), row
        lab = {p["num"]: n for p, n in zip(pins, nets)}
        flagged |= t6.power_nets(pins, lab)
        out.append(t6.syminst(("hw_n:" if big else "Device:") + name,
                              row["ref"], x0 + (k % 18) * 20.0,
                              y0 + (k // 18) * 22.0 + (8.0 if big else 0.0),
                              1, pins, lab, value=row["value"],
                              footprint=row["footprint"]))
    return out
