#!/usr/bin/env python3
"""Task T4 (plan/interposers.md): generate hw/lib/ assets for both variants.

- hw/lib/<name>_FPGA.kicad_sym: generated FPGA symbol, one unit per I/O
  bank plus "PWR" (power/ground/rails) and "CFG" (configuration, clocks,
  reference and other dedicated balls); pin number = ball, pin name = ball.
- hw/lib/pretty/<name>_BGA.kicad_mod: generated BGA footprint with one
  round solder-mask pad per ball, rasterised in physical ball order
  (columns A..V then W,Y then AA,AB; rows 1..22).

Checks: symbol pin count equals CSV ball count; footprint pad count
equals ball count; the ball raster is rectangular with a physical column
order; exit 1 on failure.
"""
import csv
import pathlib
import re
import sys
import models3d

ROOT = pathlib.Path(__file__).resolve().parents[2]
LIB = ROOT / "hw/lib"
PRETTY = LIB / "Interposer.pretty"

VARIANTS = [
    ("FPGA_CycloneV_5CEFA9_F484", "FPGAlist/CycloneV_A9/pins/5ceba9_f484.csv",
     22, 1.0, 0.30),
    ("FPGA_CycloneV_5CGXFC5_F484", "FPGAlist/CycloneV_GX/pins/5cgxfc5_f484.csv",
     22, 1.0, 0.30),
    ("FPGA_Ti180_TI180G400", "FPGAlist/Ti180_G400/pins/ti180g400.csv",
     20, 0.8, 0.28),
]

CFG_NAME = re.compile(r"(NCONFIG|NSTATUS|CONF_DONE|CDONE|CRESET_N|DCLK|SPI"
                      r"|INIT|TEST|CSI|TCK|TMS|TDI|TDO|CRRAM|VREF|RREF"
                      r"|CLOCK|CCLK|CLK_)", re.I)


def balanced(text):
    depth, in_q = 0, False
    for ch in text:
        if ch == '"':
            in_q = not in_q
        elif not in_q:
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
                if depth < 0:
                    return -1
    return depth


def write_logic_symbols():
    """Interposer_Logic.kicad_sym: the 8-channel pass-gate level translator
    used between the socket pins and the FPGA I/O (per D1/D3, T5 translator
    column). One unit; A side = FPGA, B side = socket."""
    pins = []
    y0 = 20.32
    for i in range(8):                       # A1..A8 on the left edge
        y = y0 - i * 5.08
        pins.append((f"A{i + 1}", "passive", f"(at -12.7 {y:.2f} 0)"))
        pins.append((f"B{i + 1}", "passive", f"(at 12.7 {y:.2f} 180)"))
    pins.append(("VCCA", "power_in", "(at 0 27.94 270)"))
    pins.append(("VCCB", "power_in", "(at 0 -27.94 90)"))
    pins.append(("GND", "power_in", "(at 15.24 0 180)"))
    lines = []
    for n, t, at in pins:
        lines.append(f'\t\t\t(pin {t} line {at} (length 2.54) (name "{n}" '
                     '(effects (font (size 1.27 1.27)) (hide yes))) (number '
                     f'"{n}" (effects (font (size 1.27 1.27)))))')
    hexval = ("(rectangles (start -12.7 25.4) (end 12.7 -25.4) "
              "(stroke (width 0.254) (type default)) "
              "(fill (type background)))")
    body = "\n".join([
        '(kicad_symbol_lib (version 20241209) (generator "gen_lib.py")',
        '\t(symbol "Translator_8ch"',
        '\t\t(pin_numbers (hide yes))',
        '\t\t(pin_names (offset 0.254) (hide yes))',
        '\t\t(exclude_from_sim no) (in_bom yes) (on_board yes)',
        '\t\t(property "Reference" "TR" (at 0 30.48 0) '
        '(effects (font (size 2.54 2.54))))',
        '\t\t(property "Value" "Translator_8ch" (at 0 27.94 0) '
        '(effects (font (size 1.27 1.27))))',
        '\t\t(property "Footprint" "" (at 0 0 0) (hide yes) '
        '(effects (font (size 1.27 1.27))))',
        '\t\t(property "Datasheet" "8-channel pass-gate translator; '
        'part number decided at T9 BOM (NM)" (at 0 0 0) (hide yes) '
        '(effects (font (size 1.27 1.27))))',
        '\t(symbol "Translator_8ch_1_1" (unit_name "A=FPGA B=socket")',
        hexval.replace("rectangles", "rectangle"),
        "\n".join(lines),
        '\t\t)',
        '\t)',
        ')'])
    text = body
    d = balanced(text)
    if d != 0:
        raise AssertionError(f"unbalanced translator output (depth {d})")
    (LIB / "Interposer_Logic.kicad_sym").write_text(text)
    npins = text.count("(pin ")
    assert npins == len(pins), f"translator lost pins: {npins} != {len(pins)}"
    print(f"wrote hw/lib/Interposer_Logic.kicad_sym ({npins} pins)")


def ball_key(ball):
    m = re.match(r"^([A-Za-z]+)([0-9]+)$", ball)
    if not m:
        sys.exit(f"ball name not in ball+row form: {ball}")
    return (len(m.group(1)), m.group(1), int(m.group(2)))


def collect_units(rows):
    power, cfg, banks = [], [], {}
    for r in rows:
        ball, bank, func = r[0], r[1], r[2]
        dedicated = bool(CFG_NAME.search(func))
        if not bank or bank in ("-",):
            (cfg if dedicated else power).append(ball)
        else:
            banks.setdefault(bank, []).append(ball)
    return power, cfg, banks


def write_symbol(name, rows):
    power, cfg, banks = collect_units(rows)
    units = [("PWR", power), ("CFG", cfg)] + sorted(banks.items())
    total = len(power) + len(cfg) + sum(len(v) for v in banks.values())
    assert total == len(rows), f"partition lost balls: {total} != {len(rows)}"

    s = [f'(kicad_symbol_lib (version 20241209) (generator "gen_lib.py")',
         f'\t(symbol "{name}"',
         '\t\t(pin_numbers (hide yes))',
         '\t\t(pin_names (offset 0.254) (hide yes))',
         '\t\t(exclude_from_sim no) (in_bom yes) (on_board yes)',
         '\t\t(property "Reference" "U" (at 0 0 0) (effects '
         '(font (size 2.54 2.54))))',
         f'\t\t(property "Value" "{name}" (at 0 0 0) (effects '
         '(font (size 1.27 1.27))))',
         f'\t\t(property "Footprint" "Interposer:{name}_BGA" (at 0 0 0) '
         '(hide yes) (effects (font (size 1.27 1.27))))',
         '\t\t(property "Datasheet" "generated from the variant FPGA pin '
         'CSV (hw/tools/gen_lib.py)" (at 0 0 0) (hide yes) '
         '(effects (font (size 1.27 1.27))))',
         '\t\t(embedded_fonts no)']

    unit_defs = []
    for uid, (uname, balls) in enumerate(units, start=1):
        n = len(balls)
        ncols = max(1, (n + 33) // 34)   # column layout: 34 pins per column
        x0 = -2.54 - (ncols - 1) * 7.62
        h = max(min(n, 34), 1) * 1.27 + 2.54
        lines = [f'\t\t(symbol "{name}_{uid}_1"',
                 f'\t\t\t(unit_name "{uname}")',
                 f'\t\t\t(rectangle (start {x0 - 2.54:.2f} {h / 2:.2f}) '
                 f'(end {x0 + 2.54:.2f} {-h / 2:.2f}) (stroke (width 0.254) '
                 '(type default)) (fill (type background)))']
        step = h / 35.0
        for i, ball in enumerate(sorted(balls, key=ball_key)):
            col, row = i // 34, i % 34
            y = h / 2 - (row + 1) * step
            x = x0 + col * 7.62
            lines.append(sym_pin(ball, x, y))
        lines.append('\t\t)')
        unit_defs.append((uid, uname, n, "\n".join(lines)))
    for uid, uname, n, txt in unit_defs:
        s.append(txt)
    s.append('\t)')
    s.append(')')
    text = "\n".join(s)
    d = balanced(text)
    if d != 0:
        raise AssertionError(f"unbalanced symbol output (depth {d})")
    return text, total, [(nm, n) for _uid, nm, n, _ in unit_defs]


def sym_pin(ball, x, y, angle=0, length=2.54):
    return (f'\t\t\t(pin passive line (at {x:.3f} {y:.3f} {angle}) '
            f'(length {length}) (name "{ball}" '
            f'(effects (font (size 1.27 1.27)) (hide yes))) (number '
            f'"{ball}" (effects (font (size 1.27 1.27)))))')


def write_fp(name, rows, size, pitch, pad):
    balls = [r[0] for r in rows]
    m = re.match(r"^([A-Za-z]+)([0-9]+)$", balls[0])
    letters = [re.match(r"^([A-Za-z]+)([0-9]+)$", b) for b in balls]
    assert all(letters), "bad ball names"
    pairs = [(l.group(1), int(l.group(2))) for l in letters]
    # physical order: single letters A..Z first, then doubles; rows asc
    cols = sorted({c for c, _ in pairs}, key=lambda c: (len(c), c))
    rws = sorted({r for _, r in pairs})
    assert len(cols) == size and len(rws) == size, (len(cols), len(rws))
    assert len(pairs) == size * size, (len(pairs), size * size)
    half = size * pitch / 2
    txt = [f'(footprint "{name}_BGA" (version 20241209) (generator "gen_lib.py")',
           '\t(descr "BGA generated from the variant FPGA pin CSV; '
           '(solder-mask-defined round pads, no paste; A1 corner at top-left")',
           '\t(attr smd)',
           '\t(layer "F.Cu")',
           '\t(property "Sheetfile" "")',
           f'\t(fp_text reference "REF**" (at 0 {-half - 1.6:.2f}) '
           '(layer "F.SilkS") (effects (font (size 1 1) '
           '(thickness 0.15))))',
           f'\t(fp_text value "{name}" (at 0 {half + 1.6:.2f}) '
           '(layer "F.Fab") (effects (font (size 1 1) '
           '(thickness 0.15))))']
    # A1 corner marker: circle at pad A1
    a1x = -half + pitch / 2
    a1y = half - pitch / 2
    txt.append(f'\t(fp_circle (center {a1x:.3f} {a1y:.3f}) (end '
               f'{a1x + 0.2:.3f} {a1y:.3f}) (stroke (width 0.15) (type '
               'solid)) (fill none) (layer "F.SilkS"))')
    for ball, (c, r) in zip(balls, pairs):
        x = (cols.index(c) - (size - 1) / 2) * pitch
        y = -((r - 1) - (size - 1) / 2) * pitch
        txt.append(f'\t(pad "{ball}" smd roundrect (at {x:.3f} {y:.3f}) '
                   f'(size {pad} {pad}) (layers "F.Cu" "F.Paste" '
                   '"F.Mask"))')
    txt.append(f'\t(fp_rect (start {-half - 0.3:.2f} {half + 0.3:.2f}) '
               f'(end {half + 0.3:.2f} {-half - 0.3:.2f}) (stroke (width '
               '0.05) (type default)) (fill none) (layer "F.CrtYd"))')
    txt.append(f'\t(fp_rect (start {-half:.2f} {half:.2f}) (end {half:.2f} '
               f'{-half:.2f}) (stroke (width 0.1) (type default)) '
               '(fill none) (layer "F.Fab"))')
    txt.append(')')
    fp = "\n".join(txt)
    d = balanced(fp)
    if d != 0:
        raise AssertionError(f"unbalanced footprint output (depth {d})")
    return fp, len(balls)


def main():
    LIB.mkdir(parents=True, exist_ok=True)
    PRETTY.mkdir(parents=True, exist_ok=True)
    fails = []
    for name, csvp, size, pitch, pad in VARIANTS:
        rows = list(csv.reader(open(ROOT / csvp)))[1:]
        balls = [r[0] for r in rows]
        sym_text, pin_count, unit_tally = write_symbol(name, rows)
        fp_text, pad_count = write_fp(name, rows, size, pitch, pad)
        (LIB / f"{name}_FPGA.kicad_sym").write_text(sym_text)
        (PRETTY / f"{name}_BGA.kicad_mod").write_text(models3d.with_models(fp_text, strict=False))
        ok = (pin_count == pad_count == len(balls) == size * size)
        # KiCad io check: both files must parse with the installed kicad-cli
        import subprocess
        out = "/tmp/opencode/gen_lib_check"
        r = subprocess.run(
            ["nice", "-n", "19", "kicad-cli", "sym", "export", "svg", "-o",
             out, str(LIB / f"{name}_FPGA.kicad_sym")],
            capture_output=True, text=True)
        if r.returncode != 0 or "Unable to load" in r.stderr:
            ok = False
            print(f"      sym kicad-cli check FAILED: "
                  f"{(r.stderr or r.stdout).strip()[-120:]}")
        r = subprocess.run(
            ["nice", "-n", "19", "kicad-cli", "fp", "export", "svg", "-o",
             out, "--footprint", f"{name}_BGA", str(PRETTY)],
            capture_output=True, text=True)
        if r.returncode != 0 or "Unable to load" in r.stderr:
            ok = False
            print(f"      fp kicad-cli check FAILED: "
                  f"{(r.stderr or r.stdout).strip()[-120:]}")
        print(f"{'PASS' if ok else 'FAIL'}  {name}: symbol pins {pin_count}, "
              f"footprint pads {pad_count}, csv balls {len(balls)}")
        for uname, n in unit_tally:
            print(f"      unit {uname}: {n} pins")
        if not ok:
            fails.append(name)
    write_logic_symbols()
    r = subprocess.run(
        ["nice", "-n", "19", "kicad-cli", "sym", "export", "svg", "-o",
         out, str(LIB / "Interposer_Logic.kicad_sym")],
        capture_output=True, text=True)
    if r.returncode != 0 or "Unable to load" in r.stderr:
        print("logic sym kicad-cli check FAILED: "
              f"{(r.stderr or r.stdout).strip()[-160:]}")
        sys.exit(1)
    print("PASS  Translator_8ch loads via kicad-cli")
    if fails:
        sys.exit(1)


main()
