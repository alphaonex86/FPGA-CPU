#!/usr/bin/env python3
"""3D models of the hw/lib footprints (KiCad stock models, copied into
hw/lib/3dmodels so the tree works offline).

Usage: models3d.py <board.kicad_pcb>...   (also used by gen_slot1_s7.py, gen_lib.py)
Adds or replaces the (model ...) of every mapped footprint in hw/lib/*.pretty
and in the given boards; fails on a board footprint without an entry.
"""
import pathlib
import re
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
LIB = ROOT / "hw/lib"
STOCK = pathlib.Path("/usr/share/kicad/3dmodels")
DIR = "${KIPRJMOD}/../lib/3dmodels"

# footprint -> (stock model, z rotation in degrees (KiCad: positive turns
# clockwise seen from the top), xy offset in mm (y up)); our footprints are
# centred, some turned 90 degrees from the stock ones (checked with
# kicad-cli pcb render). Placeholder land patterns get the nearest real
# body: Translator_TSSOP20 is no real TSSOP (rows offset, pin order of
# neither face), FBGA96_x16 a generic grid (plan/slot1.md S7).
MODELS = {
    "C_0402_1005Metric": ("Capacitor_SMD.3dshapes/C_0402_1005Metric.step", 0, (0, 0)),
    "C_0402_P1.00": ("Capacitor_SMD.3dshapes/C_0402_1005Metric.step", 0, (0, 0)),
    "C_0603_1608Metric": ("Capacitor_SMD.3dshapes/C_0603_1608Metric.step", 0, (0, 0)),
    "C_0805_2012Metric": ("Capacitor_SMD.3dshapes/C_0805_2012Metric.step", 0, (0, 0)),
    "C_1206_3216Metric": ("Capacitor_SMD.3dshapes/C_1206_3216Metric.step", 0, (0, 0)),
    "C_1210_3225Metric": ("Capacitor_SMD.3dshapes/C_1210_3225Metric.step", 0, (0, 0)),
    "R_0402_1005Metric": ("Resistor_SMD.3dshapes/R_0402_1005Metric.step", 0, (0, 0)),
    "L_0805_2012Metric": ("Inductor_SMD.3dshapes/L_0805_2012Metric.step", 0, (0, 0)),
    "L_0603_1608Metric": ("Inductor_SMD.3dshapes/L_0603_1608Metric.step", 0, (0, 0)),
    "Fuse_1206_3216Metric": ("Fuse.3dshapes/Fuse_1206_3216Metric.step", 0, (0, 0)),
    # no stock 1812 fuse body: the 1812 chip of the same size
    "Fuse_1812_4532Metric": ("Capacitor_SMD.3dshapes/C_1812_4532Metric.step", 0, (0, 0)),
    "SW_Push_1P1T_XKB_TS-1187A": ("Button_Switch_SMD.3dshapes/SW_SPST_TL3342.step", 0, (0, 0)),   # no stock model; same 5 mm tact body
    "L_Coilcraft_MSS1048-XXX": ("Inductor_SMD.3dshapes/L_Coilcraft_MSS1048-XXX.step", 0, (0, 0)),
    # XxL4020 = XAL/XEL4020, one body
    "L_Coilcraft_XxL4020": ("Inductor_SMD.3dshapes/L_Coilcraft_XAL4020-XXX.step", 0, (0, 0)),
    # the EP 1.68 body is not in the stock set: same 3 x 3 x 0.9 mm QFN
    "VQFN-16-1EP_3x3mm_P0.5mm_EP1.68x1.68mm": ("Package_DFN_QFN.3dshapes/QFN-16-1EP_3x3mm_P0.5mm_EP1.7x1.7mm.step", 0, (0, 0)),
    "TSSOP-56_6.1x14mm_P0.5mm": ("Package_SO.3dshapes/TSSOP-56_6.1x14mm_P0.5mm.step", 0, (0, 0)),
    "TSSOP-20_4.4x6.5mm_P0.65mm": ("Package_SO.3dshapes/TSSOP-20_4.4x6.5mm_P0.65mm.step", 0, (0, 0)),
    "SOIC-16_3.9x9.9mm_P1.27mm": ("Package_SO.3dshapes/SOIC-16_3.9x9.9mm_P1.27mm.step", 0, (0, 0)),
    "SOIC-16W_7.5x10.3mm_P1.27mm": ("Package_SO.3dshapes/SOIC-16W_7.5x10.3mm_P1.27mm.step", 0, (0, 0)),
    "R_Array_Convex_4x0402": ("Resistor_SMD.3dshapes/R_Array_Convex_4x0402.step", 0, (0, 0)),
    "TI_RHL0014A": ("Package_DFN_QFN.3dshapes/Texas_S-PVQFN-N14.step", 0, (0, 0)),
    "FPGA_CycloneV_5CEFA9_F484_BGA": ("Package_BGA.3dshapes/BGA-484_23.0x23.0mm_Layout22x22_P1.0mm.step", -90, (0, 0)),
    "FPGA_CycloneV_5CGXFC5_F484_BGA": ("Package_BGA.3dshapes/BGA-484_23.0x23.0mm_Layout22x22_P1.0mm.step", -90, (0, 0)),
    "FPGA_Artix7_XC7A100T_FGG484_BGA": ("Package_BGA.3dshapes/BGA-484_23.0x23.0mm_Layout22x22_P1.0mm.step", -90, (0, 0)),
    "FBGA96_x16": ("Package_BGA.3dshapes/BGA-96_9.0x13.0mm_Layout2x3x16_P0.8mm.step", 0, (0, 0)),
    "Translator_TSSOP20": ("Package_SO.3dshapes/TSSOP-20_4.4x6.5mm_P0.65mm.step", -90, (0, 0)),
    "PinHeader_2x20_P1.27mm_Vertical_SMD": ("Connector_PinHeader_1.27mm.3dshapes/PinHeader_2x20_P1.27mm_Vertical_SMD.step", -90, (0, 0)),
    "Header_2x05": ("Connector_PinHeader_2.54mm.3dshapes/PinHeader_2x05_P2.54mm_Vertical.step", -90, (-5.08, -1.27)),
    "Header_2x03": ("Connector_PinHeader_2.54mm.3dshapes/PinHeader_2x03_P2.54mm_Vertical.step", -90, (-2.54, -1.27)),
    "Header_1x03": ("Connector_PinHeader_2.54mm.3dshapes/PinHeader_1x03_P2.54mm_Vertical.step", -90, (-2.54, 0)),
    # no stock SFF-8612 body: the nearest shielded right-angle receptacle
    # (16.5 x 11 x 6.2 mm vs 17.3 x 10.4), front moved onto the shell front
    "OCuLink_4i_SFF-8612_RA": ("Connector_Video.3dshapes/HDMI_A_Amphenol_10029449-x01xLF_Horizontal.step", 0, (0, -3.28)),
    "BarrelJack_CUI_PJ-063AH_Horizontal": ("Connector_BarrelJack.3dshapes/BarrelJack_CUI_PJ-063AH_Horizontal.step", 0, (0, 0)),
}
# no body: the card-edge fingers are the PCB itself; U7 is a 5-pad
# placeholder until the TPS51200 land pattern replaces it (plan/slot1.md)
NO_MODEL = {"SC242_CardEdge_242", "VTT_tracker", "FPGA_Ti180_TI180G400_BGA", "Barrel2"}

MODEL_RE = re.compile(r'\n\s*\(model "[^"]*"(?:[^()]|\((?:[^()]|\([^()]*\))*\))*\)')


def model_sexpr(name, indent):
    step, rot, (dx, dy) = MODELS[name]
    return ('%s(model "%s/%s"\n%s\t(offset (xyz %g %g 0))\n%s\t(scale (xyz 1 1 1))\n'
            '%s\t(rotate (xyz 0 0 %g))\n%s)' % (indent, DIR, pathlib.Path(step).name, indent, dx, dy,
                                                indent, indent, rot, indent))


def footprint_blocks(text):
    """(start, end, name) of every top-level (footprint ...) block"""
    for m in re.finditer(r'\(footprint "(?:[^":]*:)?([^"]*)"', text):
        depth, i, quoted = 0, m.start(), False
        while True:
            if i == len(text):
                raise SystemExit("models3d: unbalanced footprint %s" % m.group(1))
            c = text[i]
            if c == '"' and text[i - 1] != "\\":
                quoted = not quoted
            elif not quoted:
                depth += c == "("
                depth -= c == ")"
            i += 1
            if depth == 0:
                break
        yield m.start(), i, m.group(1)


def with_models(text, strict):
    out, last, missing = [], 0, set()
    for start, end, name in footprint_blocks(text):
        if name in NO_MODEL:
            continue
        if name not in MODELS:
            missing.add(name)
            continue
        block = MODEL_RE.sub("", text[start:end])
        close = re.search(r"\n([ \t]*)\)$", block)
        close = close.group(1) if close else ""
        out += [text[last:start], block[:-1].rstrip() + "\n" + model_sexpr(name, close + "\t") + "\n" +
                close + ")"]
        last = end
    if strict and missing:
        raise SystemExit("models3d: footprints without a model entry: %s" % " ".join(sorted(missing)))
    return "".join(out) + text[last:]


def copy_models():
    dest = LIB / "3dmodels"
    dest.mkdir(exist_ok=True)
    for step, _, _ in MODELS.values():
        src = STOCK / step
        if not (dest / src.name).exists():
            if not src.exists():
                raise SystemExit("models3d: %s missing (KiCad 3D library)" % src)
            shutil.copyfile(src, dest / src.name)


def apply(boards):
    copy_models()
    for mod in LIB.glob("*.pretty/*.kicad_mod"):
        mod.write_text(with_models(mod.read_text(), strict=False))
    for b in boards:
        b = pathlib.Path(b)
        b.write_text(with_models(b.read_text(), strict=True))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    apply(sys.argv[1:])
