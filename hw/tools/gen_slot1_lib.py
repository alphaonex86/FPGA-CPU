#!/usr/bin/env python3
"""Task S4 (plan/slot1.md): Slot 1 part/footprint library for the
slot1-cyclonev cartridge.

Generates:
  hw/lib/Slot1.pretty/SC242_CardEdge_242.kicad_mod   card-edge plug footprint
  hw/lib/Slot1_Parts.kicad_sym                       DDR3L x16 die + power parts

Geometry sources (page numbers are printed pages):
  - 242 contacts, 1.0 mm pitch: SC242 Connector Design Guidelines
    (243397-02) section 1/2.2/2.3 [sc242 p7 sec 1, p10 sec 2.2-2.3];
    the Databook chapter 16 states it too [ch16 16.4.1 p 16-17].
  - Station positions: substrate edge drawing [sc242 Fig 1 p9]: A1 center
    0.157 in from card end X; A1..A73 group span 2.835 in (= 72 x 1 mm
    exactly), key datum W at 2.992 in = station 73 center, A74..A121 span
    1.850 in (= 47 x 1 mm), overall substrate 5.000 in. So the contact grid
    is one straight station line at 1.0 mm pitch, both faces carrying the
    same-numbered station (contact pairs; 73 + 48 pairs around the key,
    [ch16 Fig 16-18 p16-17]).
  - Substrate thickness 0.062 +0.007/-0.005 in [sc242 Fig 1 p9] -> the
    cartridge PCB must be 1.57 mm thick with +-0.18/-0.13 tolerance; the
    footprint assumes the pads are flush with the milled edge.
  - Key slot: the connector's polarization key extends 2.0 mm [sc242 p10
    sec 2.3]; the substrate key slot sits between stations 73/74 and does
    not shift the grid. The exact milled slot width/depth is an operator
    measurement (plan D16): the footprint marks the notch on the courtyard.
  - Pad shapes on the real substrate are stepped (head + neck, per Detail
    A [sc242 Fig 2 p10]); a rectangular finger is used here, sized to stay
    inside the 1.0 mm pitch (0.6 mm wide) with 3.5 mm length (covers the
    0.99 mm contact backout wipe per [sc242 sec 5.9.3 / rev notes p55]).
    Final engagement verification is D16/NM11 on a real cartridge.

Regenerate with this script. Checks pass or exit 1.
"""
import math
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
LIB = ROOT / "hw/lib"
PRETTY = LIB / "Slot1.pretty"
SYMFILE = LIB / "Slot1_Parts.kicad_sym"

DESC = ("SC242 card-edge plug (Slot 1, 2x121, 1.0 mm pitch). "
        "Origin: pad A1/B1 center (0.157 in from the card end per "
        "243397-02 Fig 1); stations 0..120 mm at 1.0 mm pitch along X along "
        "a 5.000 in (127.0 mm) substrate; contact pad rows on F.Cu (A) and "
        "B.Cu (B) both at local Y +1.75 mm with pad faces flush with the "
        "PCB edge (tips at Y 0), i.e. both faces' fingers run inboard from "
        "the insertion edge plane. PCB edge to be milled with the 2 mm key "
        "notch between "
        "stations 73/74 (courtyard/fab "
        "line). Substrate thickness 1.57 mm +0.18/-0.13 (243397-02 Fig 1). "
        "From the connector drawing; exact pad/key geometry pending plan "
        "slot1 D16 (operator measurement).")

KEY_NOTCH_MM = 2.0        # connector polarization key width (sc242 sec 2.3)
PAD_W = 0.6
PAD_L = 3.5
PITCH = 1.0
N = 121
ROW_OFFSET = PAD_L / 2    # pad center sits this far inboard of the edge

# ---------------------------------------------------------------- footprint
def gen_footprint():
    pads = []
    for i in range(1, N + 1):                    # row A on F.Cu
        x = (i - 1) * PITCH                      # origin at pad A1/B1
        pads.append('\t\t(pad "%s" smd rect\n\t\t\t(at %.3f %.3f)\n'
                    '\t\t\t(size %.2f %.2f)\n\t\t\t(layers %s)\n'
                    '\t\t\t(remove_unused_layers no)\n\t\t)' % (
                        f"A{i}", x, ROW_OFFSET, PAD_W, PAD_L,
                        '"F.Cu" "F.Paste" "F.Mask"'))
    for i in range(1, N + 1):                    # row B on B.Cu, same face
        x = (i - 1) * PITCH
        pads.append('\t\t(pad "%s" smd rect\n\t\t\t(at %.3f %.3f)\n'
                    '\t\t\t(size %.2f %.2f)\n\t\t\t(layers %s)\n'
                    '\t\t\t(remove_unused_layers no)\n\t\t)' % (
                        f"B{i}", x, ROW_OFFSET, PAD_W, PAD_L,
                        '"B.Cu" "B.Paste" "B.Mask"'))
    # courtyard: edge line along the pads, with the key notch marked
    # between station 73 and 74 centers (x = -0.5 mm at the array center)
    lines = [
        (-2.0, ROW_OFFSET + 0.5, 123.0, ROW_OFFSET + 0.5),
        (-2.0, -(ROW_OFFSET + 0.5), 123.0, -(ROW_OFFSET + 0.5)),
    ]
    edges = [
        (-2.0, 0.0, 121.0 + 2.0, 0.0),
        # key notch marked between stations 73 and 74
        (72.5 - KEY_NOTCH_MM / 2.0, 0.0, 72.5 - KEY_NOTCH_MM / 2.0, 3.0),
        (72.5 + KEY_NOTCH_MM / 2.0, 0.0, 72.5 + KEY_NOTCH_MM / 2.0, 3.0),
        (72.5 - KEY_NOTCH_MM / 2.0, 3.0, 72.5 + KEY_NOTCH_MM / 2.0, 3.0),
    ]
    def line(x0, y0, x1, y1, layer):
        return ('%s(fp_line (start %.3f %.3f) (end %.3f %.3f) '
                '(stroke (width 0.1) (type solid)) %s)' % (
                    '\t\t', x0, y0, x1, y1, layer))
    text = [
        '\t\t(fp_text reference "REF**" (at 0 %f unlocked) '
        '(layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))'
        % (ROW_OFFSET + PAD_L + 1.5),
        '\t\t(fp_text value "SC242_CardEdge_242" (at 0 %f unlocked) '
        '(layer "F.Fab") (effects (font (size 1 1) (thickness 0.15))))'
        % -(ROW_OFFSET + PAD_L + 1.5),
        '\t\t(fp_text user "%s" (at 0 0 unlocked) (layer "F.Fab") '
        '(effects (font (size 1 1) (thickness 0.15))))' %
        DESC.replace('"', "'"),
    ]
    body = "\n".join(text + pads +
                     [line(*l, '(layer "F.CrtYd")') for l in lines] +
                     [line(*l, '(layer "F.Fab")') for l in edges])
    # strip the trailing period artifact if any
    out = ('(footprint "SC242_CardEdge_242" (layer "F.Cu")\n'
           '\t(descr "%s")\n'
           '\t(tags "slot1 SC242 card-edge 2x121 1mm")\n'
           '\t(attr exclude_from_pos_files exclude_from_bom)\n'
           '%s\n)\n' % (DESC, body))
    # remove trailing '.' from pad() artefact usage
    out = out.replace('\n.)', ')')
    return out

# ----------------------------------------------------------------- symbols
def pin(n, t, at, name):
    """Pin line exactly in the gen_lib.py emission form (names hidden)."""
    return ('\t\t\t(pin %s line %s (length 2.54) (name "%s" '
            '(effects (font (size 1.27 1.27)) (hide yes))) (number '
            '"%s" (effects (font (size 1.27 1.27)))))' % (t, at, name,
                                                          name))

def npin(num, t, at, name):
    """pin with a number distinct from its (visible) name"""
    return ('\t\t\t(pin %s line %s (length 2.54) (name "%s" '
            '(effects (font (size 1.27 1.27)))) (number "%s" '
            '(effects (font (size 1.27 1.27)))))' % (t, at, name, num))


def reg_sym(name, left, right, bottom, datasheet, ref="PS"):
    """regulator (or any IC): inputs left, outputs right, supplies bottom;
    supply pins (VIN/PVIN/AVIN/VCC*/grounds) power_in, the rest passive"""
    def typ(nm):
        return "power_in" if nm in ("PVIN", "VIN", "AVIN", "GND", "AGND", "PGND", "PAD",
                                    "VDD") or nm.startswith("VCC") else "passive"
    w = 2.54 * (len(bottom) - 1)
    hw = max(10.16, 2.54 * math.ceil(w / 5.08 + 1))   # bottom pins inside the box
    # more than 8 bottom pins: rows for their vertical names under the side pins
    rows = math.ceil(max(len(nm) for _, nm in bottom) / 2 + 1) if len(bottom) > 8 else 0
    h = 2.54 * (max(len(left), len(right)) + 1 + rows)
    pins = [npin(n, typ(nm), "(at %g %.2f 0)" % (-hw - 2.54, h / 2 - 2.54 * (k + 1)), nm)
            for k, (n, nm) in enumerate(left)]
    pins += [npin(n, typ(nm), "(at %g %.2f 180)" % (hw + 2.54, h / 2 - 2.54 * (k + 1)), nm)
             for k, (n, nm) in enumerate(right)]
    pins += [npin(n, typ(nm), "(at %.2f %.2f 90)" % (-w / 2 + 2.54 * k,
                                                     -h / 2 - 2.54), nm)
             for k, (n, nm) in enumerate(bottom)]
    return rect_sym(name, ref, pins, (-hw, h / 2, hw, -h / 2),
                    datasheet=datasheet).replace('(pin_numbers (hide yes))\n', '')


def tps_syms():
    """the pdn.py regulators; pin numbers/names: tps54620 p.4, tps62130
    p.3 Table 6-1"""
    return [reg_sym("TPS54620", [
        ("4", "PVIN"), ("5", "PVIN"), ("6", "VIN"), ("10", "EN"),
        ("1", "RT/CLK"), ("9", "SS/TR")], [
        ("13", "BOOT"), ("11", "PH"), ("12", "PH"), ("7", "VSENSE"),
        ("8", "COMP"), ("14", "PWRGD")], [("2", "GND"), ("3", "GND"),
        ("15", "PAD")], "sockets/parts/ti_tps54620_6a_buck.pdf"),
        reg_sym("TPS62130", [
        ("11", "PVIN"), ("12", "PVIN"), ("10", "AVIN"), ("13", "EN"),
        ("9", "SS/TR"), ("7", "FSW"), ("8", "DEF")], [
        ("1", "SW"), ("2", "SW"), ("3", "SW"), ("14", "VOS"), ("5", "FB"),
        ("4", "PG")], [("6", "AGND"), ("15", "PGND"), ("16", "PGND"),
        ("17", "PAD")], "sockets/parts/ti_tps62130_3a_buck.pdf")]


def c2cart_syms():
    """dedicated C2 cartridge (plan/slot1_c2.md D33/D35/D37); pin numbers:
    ti_sn74gtl16612 p.1 (DGG), ti_sn74cb3t3245 p.3 (PW), infineon_cy2305
    Table 2 (CY2309, SOIC-16), cf52014 (EPCQ128A, SOIC-16), snia_sff9402 (OCuLink)"""
    a = [("3", "A1"), ("5", "A2"), ("6", "A3"), ("8", "A4"), ("9", "A5"), ("10", "A6"),
         ("12", "A7"), ("13", "A8"), ("14", "A9"), ("15", "A10"), ("16", "A11"), ("17", "A12"),
         ("19", "A13"), ("20", "A14"), ("21", "A15"), ("23", "A16"), ("24", "A17"), ("26", "A18")]
    b = [("54", "B1"), ("52", "B2"), ("51", "B3"), ("49", "B4"), ("48", "B5"), ("47", "B6"),
         ("45", "B7"), ("44", "B8"), ("43", "B9"), ("42", "B10"), ("41", "B11"), ("40", "B12"),
         ("38", "B13"), ("37", "B14"), ("36", "B15"), ("34", "B16"), ("33", "B17"), ("31", "B18")]
    ctl = [("1", "OEAB#"), ("2", "LEAB"), ("56", "CEAB#"), ("55", "CLKAB"),
           ("27", "OEBA#"), ("28", "LEBA"), ("29", "CEBA#"), ("30", "CLKBA")]
    sup = [("7", "VCC33"), ("22", "VCC33"), ("50", "VCC5"), ("35", "VREF")] + \
        [(n, "GND") for n in ("4", "11", "18", "25", "32", "39", "46", "53")]
    gtl = reg_sym("SN74GTL16612", a + ctl, b, sup, "sockets/parts/ti_sn74gtl16612.pdf", ref="U")
    cb3t = reg_sym("SN74CB3T3245", [("%d" % (k + 2), "A%d" % (k + 1)) for k in range(8)] + [("19", "OE#")],
                   [("%d" % (18 - k), "B%d" % (k + 1)) for k in range(8)],
                   [("20", "VCC"), ("10", "GND"), ("1", "NC")], "sockets/parts/ti_sn74cb3t3245.pdf", ref="U")
    zdb = reg_sym("CY2309", [("1", "REF"), ("9", "S1"), ("8", "S2")],
                  [("2", "CLKA1"), ("3", "CLKA2"), ("14", "CLKA3"), ("15", "CLKA4"), ("6", "CLKB1"),
                   ("7", "CLKB2"), ("10", "CLKB3"), ("11", "CLKB4"), ("16", "CLKOUT")],
                  [("4", "VDD"), ("13", "VDD"), ("5", "GND"), ("12", "GND")],
                  "sockets/parts/infineon_cy2305.pdf", ref="U")
    # AS x1 pin-out (cf52014_epcq-a_datasheet Figure 3, Table 8)
    epcq = reg_sym("EPCQ128A", [("7", "nCS"), ("16", "DCLK"), ("15", "DATA0"), ("3", "nRESET")],
                   [("8", "DATA1")] + [(n, "NC") for n in ("4", "5", "6", "11", "12", "13", "14")],
                   [("1", "VCC"), ("2", "VCC"), ("9", "VCC"), ("10", "GND")],
                   "FPGAlist/CycloneV_A9/docs/cf52014_epcq-a_datasheet.pdf", ref="U")
    # OCuLink 4i receptacle, endpoint side (snia_sff9402 Table 6-1, SFF-8621 column); SH = shell pads
    ocu_a = ["P3V3_RX", "GND", "PERp0", "PERn0", "GND", "PERp1", "PERn1", "GND", "2W_CLK", "2W_DATA", "GND",
             "PERST#", "CPRSNT#", "GND", "PERp2", "PERn2", "GND", "PERp3", "PERn3", "GND", "P5V_2"]
    ocu_b = ["P5V_1", "GND", "PETp0", "PETn0", "GND", "PETp1", "PETn1", "GND", "BP_TYPE", "CWAKE#", "GND",
             "REFCLK+", "REFCLK-", "GND", "PETp2", "PETn2", "GND", "PETp3", "PETn3", "GND", "P3V3_TX"]
    ocu = reg_sym("OCuLink_4i_EP", [("A%d" % (k + 1), n) for k, n in enumerate(ocu_a)],
                  [("B%d" % (k + 1), n) for k, n in enumerate(ocu_b)], [("SH", "SHIELD")],
                  "sockets/parts/snia_sff9402_rev1.1.pdf", ref="J")
    return [gtl, cb3t, zdb, epcq, ocu]


def rect_sym(name, ref, pins, box, unit_name="",
             datasheet="hw/tools/gen_slot1_lib.py"):
    x0, y0, x1, y1 = box
    unit_line = ('\t\t\t(unit_name "%s")' % unit_name) if unit_name else None
    body = [
        '\t(symbol "%s"' % name,
        '\t\t(pin_numbers (hide yes))',
        '\t\t(pin_names (offset 0.254))',
        '\t\t(exclude_from_sim no) (in_bom yes) (on_board yes)',
        '\t\t(property "Reference" "%s" (at 0 %.2f 0) (effects '
        '(font (size 1.27 1.27))))' % (ref, y0 - 1.27),
        '\t\t(property "Value" "%s" (at 0 %.2f 0) (effects '
        '(font (size 1.27 1.27))))' % (name, y1 + 1.27),
        '\t\t(property "Footprint" "" (at 0 0 0) (hide yes) (effects '
        '(font (size 1.27 1.27))))',
        '\t\t(property "Datasheet" "%s" (at 0 0 0) '
        '(hide yes) (effects (font (size 1.27 1.27))))' % datasheet,
        '\t\t(embedded_fonts no)',
        '\t\t(symbol "%s_1_1"' % name,
        unit_line,
        '\t\t\t(rectangle (start %.2f %.2f) (end %.2f %.2f) '
        '(stroke (width 0.254) (type default)) (fill (type background)))'
        % (x0, y0, x1, y1),
    ] + list(pins) + ['\t\t)', '\t)']
    return "\n".join(b for b in body if b is not None)

def gen_symbols():
    syms = []

    # ---- DDR3L x16 die (96-ball FBGA 8 Gb class = MT41K512M16 per NM24) ---
    dd = []
    groups_left = [
        ["DQ%d" % i for i in range(16)],
        ["DQS0p", "DQS0n", "DQS1p", "DQS1n"],
        ["DM0", "DM1"],
    ]                                                  # 22 left pins
    groups_right = [
        ["A%d" % i for i in range(16)],
        ["BA0", "BA1", "BA2"],
        ["CKp", "CKn", "CKE", "CS#", "RAS#", "CAS#", "WE#", "ODT",
         "RESET#"],
        ["VREFCA", "VREFDQ", "ZQ"],
    ]                                                  # 32 right pins
    power = ["VDD", "VSS", "VDDQ", "VSSQ"]
    pins = []
    y0, step = 26.16, 1.27
    for k, nm in enumerate([n for g in groups_left for n in g]):
        pins.append(pin(nm, "passive", "(at -17.78 %.2f 0)"
                        % (y0 - k * step), nm))
    for k, nm in enumerate([n for g in groups_right for n in g]):
        pins.append(pin(nm, "passive", "(at 17.78 %.2f 180)"
                        % (y0 - k * step), nm))
    for k, nm in enumerate(power):
        pins.append(pin(nm, "passive", "(at %.2f -30.48 90)"
                        % (-5.08 + k * 2.54), nm))
    syms.append(rect_sym("DDR3L_x16_die", "U", pins,
                         (-15.24, 32.46, 15.24, -27.94),
                         'DDR3L x16 8 Gb (96-ball, MT41K512M16 class): row '
                         'A[15:0], VREFCA/VREFDQ 0.675 V [alliance/micron '
                         '8Gb x16 datasheet]'))

    # ---- power tree regulators (plan D23; pdn.py) ------------------------
    syms += tps_syms()

    syms += c2cart_syms()

    # ---- DDR VTT source/sink tracker -------------------------------------
    vt = [
        pin("1", "power_in", "(at -12.7 5.08 0)", "VIN"),
        pin("2", "output", "(at 12.7 5.08 180)", "VTT"),
        pin("3", "passive", "(at 12.7 -5.08 180)", "VTTSNS"),
        pin("4", "input", "(at -12.7 -5.08 0)", "VDDQ_REF"),
        pin("5", "power_in", "(at 0 -12.7 270)", "GND"),
    ]
    syms.append(rect_sym("DDR_VTT_tracker", "U", vt,
                         (-10.16, 7.62, 10.16, -7.62),
                         '0.675 V VTTDDR source/sink per '
                         'hw/slot1-cyclonev/power.md'))
    return ("(kicad_symbol_lib (version 20241209) "
            '(generator "gen_slot1_lib.py")\n%s\n)\n'
            % "\n".join(syms))

def parse_sexp(text):
    """Validate s-expression structure, ignoring parens inside quotes.
    Returns depth or raises ValueError."""
    depth = 0
    in_str = False
    for i, ch in enumerate(text):
        if in_str:
            if ch == '"':
                if text[i - 1] != "\\":
                    in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                raise ValueError("unbalanced ) at char %d" % i)
    if depth:
        raise ValueError("unclosed ( : depth %d" % depth)
    if in_str:
        raise ValueError("unterminated string")
    return depth

# ------------------------------------------------------------------- main
def write_footprint():
    PRETTY.mkdir(parents=True, exist_ok=True)
    out = PRETTY / "SC242_CardEdge_242.kicad_mod"
    out.write_text(gen_footprint())
    return out

def main():
    fails = []

    def check(name, ok, detail=""):
        print(("PASS" if ok else "FAIL"), name, detail)
        if not ok:
            fails.append(name)

    # --- sources on disk --------------------------------------------------
    for name, rel in (("sc242", "sockets/slot1/"
                       "sc242_connector_designguidelines_243397-02.pdf"),
                      ("ch16", "sockets/slot1/"
                       "sec_cartridge_packaging_databook_ch16.pdf"),
                      ("signals", "hw/common/slot1_signals.csv")):
        check(f"source {name} exists", (ROOT / rel).is_file(), rel)

    fp = gen_footprint()
    # structural checks
    pads_a = re.findall(r'\(pad "A(\d+)"', fp)
    pads_b = re.findall(r'\(pad "B(\d+)"', fp)
    check("pads A = 121", len(pads_a) == 121, len(pads_a))
    check("pads B = 121", len(pads_b) == 121, len(pads_b))
    check("pad A numbers 1..121",
          [int(p) for p in pads_a] == list(range(1, 122)))
    check("pad B numbers 1..121",
          [int(p) for p in pads_b] == list(range(1, 122)))
    # station pitch: extract all A pad x and confirm 1.0 mm spacing
    xs = [float(m) for m in re.findall(
        r'\(pad "A\d+" smd rect\s+\(at (-?[\d.]+)', fp)]
    diffs = [round(b - a, 3) for a, b in zip(xs, xs[1:])]
    check("A pad pitch 1.0 mm", all(abs(d - 1.0) < 1e-6 for d in diffs))
    check("first A at origin (pad A1 center)", xs[0] == 0.0)
    check("last A at 120 mm", abs(xs[-1] - 120.0) < 1e-6)
    check("A73 station at 72 mm = 2.992 in minus the 0.157 in A1 offset",
          abs(xs[72] - 72.0) < 1e-6, xs[72])
    # card ends at -3.99 mm / +124.0 mm relative to the A1 origin
    # (127.0 mm substrate, 0.157 in left margin, 4.724 in span to A121)
    check("text refs card length", "127" in DESC and "5.000" in fp)
    # direct regex check: both faces' fingers run inboard from Y +1.75
    # with pad faces flush with the PCB edge (tips at Y 0)
    a_y = len(re.findall(r'\(pad "A\d+" smd rect\s+\(at -?[\d.]+ 1\.750\)',
                         fp))
    b_y = len(re.findall(r'\(pad "B\d+" smd rect\s+\(at -?[\d.]+ 1\.750\)',
                         fp))
    check("A pads at +1.75", a_y == 121, a_y)
    check("B pads at +1.75 (inboard, B.Cu)", b_y == 121, b_y)
    check("cites doc numbers",
          "243397-02" in fp and "D16" in fp)
    balanced = fp.count("(") == fp.count(")")
    check("footprint parens balanced", balanced,
          f"{fp.count('(')}/{fp.count(')')}")
    try:
        parse_sexp(fp)
        check("footprint parses as s-expr (quote-aware)", True)
    except ValueError as e:
        check("footprint parses as s-expr (quote-aware)", False, str(e))

    syms = gen_symbols()
    check("symbol parens balanced", syms.count("(") == syms.count(")"),
          f"{syms.count('(')}/{syms.count(')')}")
    try:
        parse_sexp(syms)
        check("symbol lib parses as s-expr (quote-aware)", True)
    except ValueError as e:
        check("symbol lib parses as s-expr (quote-aware)", False, str(e))
    for name in ("DDR3L_x16_die", "TPS54620", "TPS62130", "DDR_VTT_tracker"):
        check(f"symbol {name}", f'(symbol "{name}"' in syms)
    dq = len(re.findall(r'\(at -17\.78 ', syms))
    check("DDR3L left pins", dq == 22, dq)

    if fails:
        sys.exit(1)
    fpath = write_footprint()
    spath = SYMFILE
    spath.write_text(syms)
    print(f"wrote {fpath}")
    print(f"wrote {spath}")

if __name__ == "__main__":
    main()
