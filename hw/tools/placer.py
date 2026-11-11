"""Board placement helpers shared by the S7 / T7 generators: the netlist, footprints from hw/lib or the
stock library, stock 3D models copied to hw/lib/3dmodels, a courtyard occupancy grid per side with a
nearest-free-spot search, and the kicad-cli DRC gate."""
import json
import pathlib
import re
import shutil
import subprocess
import sys

import numpy as np
import pcbnew

import gen_t6_schematic as t6

ROOT = pathlib.Path(__file__).resolve().parents[2]
LIB = ROOT / "hw/lib"
STOCK_FP, STOCK_3D = pathlib.Path("/usr/share/kicad/footprints"), pathlib.Path("/usr/share/kicad/3dmodels")
RES = 0.1                                # occupancy grid (mm)


def mm(x, y):
    return pcbnew.VECTOR2I_MM(x, y)


def netlist(path, fixed_fp):
    """{ref: (value, footprint)}, {plain net name: [(ref, pin)]}, {plain name: netlist name};
    fixed_fp: the footprint of a ref the netlist leaves empty"""
    t = path.read_text()
    comps = {}
    for m in re.finditer(r'\(comp\s*\(ref "([^"]+)"\)\s*\(value "([^"]*)"\)(?:\s*\(footprint "([^"]*)"\))?', t):
        comps[m.group(1)] = (m.group(2), m.group(3) or fixed_fp.get(m.group(1), ""))
    nets, full = {}, {}
    for m in re.finditer(r'\(net\s*\(code "[^"]+"\)\s*\(name "([^"]*)"\)', t):
        plain = m.group(1).lstrip("/").replace("{slash}", "/")
        nets[plain] = re.findall(r'\(ref "([^"]*)"\)\s*\(pin "([^"]*)"\)', t[m.end():t6.block(t, m.start())])
        full[plain] = m.group(1)
    return comps, nets, full


def load(fpid, libs=None):
    """libs: {nickname: .pretty dir} before hw/lib/<nickname>.pretty and the stock library"""
    lib, name = fpid.split(":")
    own = (libs or {}).get(lib, LIB / f"{lib}.pretty")
    f = pcbnew.FootprintLoad(str(own if (own / f"{name}.kicad_mod").exists() else STOCK_FP / f"{lib}.pretty"), name)
    if f is None:
        sys.exit(f"FAIL: footprint {fpid} not found")
    return f


def localize_models(f, fails, out, no_model=()):
    """stock model -> hw/lib/3dmodels copy, path relative to the project in out"""
    import models3d
    ref = f.GetReference()
    models = f.Models()                  # set through the index: a loop variable is a copy
    if not len(models) and ref not in no_model:
        fails.append(f"{ref}: no 3D model")
    for k in range(len(models)):
        name = models[k].m_Filename
        if name.startswith("${KIPRJMOD}"):
            path = out / name.replace("${KIPRJMOD}/", "")
        else:
            src = STOCK_3D / re.sub(r"^\$\{KICAD\d*_3DMODEL_DIR\}/", "", name)
            if not src.exists() and f.GetFPID().GetLibItemName().wx_str() in models3d.MODELS:
                src = STOCK_3D / models3d.MODELS[f.GetFPID().GetLibItemName().wx_str()][0]
            path = LIB / "3dmodels" / src.name
            if src.exists() and not path.exists():
                shutil.copy(src, path)
            models[k].m_Filename = "${KIPRJMOD}/../lib/3dmodels/" + src.name
        if not path.resolve().exists():
            fails.append(f"{ref}: 3D model file missing {path}")


SCRATCH = pcbnew.BOARD()                 # a footprint flips only on a board


def placed(fpid, x, y, rot, side, libs=None):
    """a footprint at a spot, off the real board (pad positions for planning)"""
    f = load(fpid, libs)
    SCRATCH.Add(f)
    if side == "B":
        f.Flip(f.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
    f.SetPosition(mm(x, y))
    f.SetOrientationDegrees(rot)
    return f


def pads(f):
    return {p.GetNumber(): (p.GetPosition().x / 1e6, p.GetPosition().y / 1e6) for p in f.Pads()}


def ring_depth(ball_xy, centre):
    """rings in from the edge of a 22 x 22, 1.0 mm pitch BGA"""
    return 10.5 - max(abs(ball_xy[0] - centre[0]), abs(ball_xy[1] - centre[1]))


class Placer:
    """footprints on the board, courtyard occupancy per side. size: the grid (mm, from 0, 0);
    region: near()'s default search box; shaped: refs marked by their courtyard polygon, not its
    bounding box; forbid(ref, box): True where a part may not go (on top of the courtyards); libs: load()"""
    def __init__(self, board, comps, nets, full, size, region, shaped=(), forbid=lambda ref, b: False, libs=None):
        self.board, self.comps, self.libs = board, comps, libs
        self.region, self.shaped, self.forbid = region, shaped, forbid
        self.grid = {s: np.zeros((int(size[0] / RES) + 1, int(size[1] / RES) + 1), bool) for s in "FB"}
        self.netinfo, self.pin_net = {}, {}
        for n, nodes in nets.items():
            ni = pcbnew.NETINFO_ITEM(board, full[n])
            board.Add(ni)
            self.netinfo[n] = ni
            for ref, pin in nodes:
                self.pin_net[(ref, pin)] = n
        self.fp, self.where = {}, {}

    def make(self, ref):
        value, fpid = self.comps[ref]
        f = load(fpid, self.libs)
        f.SetReference(ref)
        f.SetValue(value)
        self.board.Add(f)
        for p in f.Pads():
            n = self.pin_net.get((ref, p.GetNumber()))
            if n:
                p.SetNet(self.netinfo[n])
        self.fp[ref] = f
        return f

    def box(self, f, side):
        f.BuildCourtyardCaches()
        poly = f.GetCourtyard(pcbnew.F_CrtYd if side == "F" else pcbnew.B_CrtYd)
        b = poly.BBox() if poly.OutlineCount() else f.GetBoundingBox(False)
        return b.GetX() / 1e6, b.GetY() / 1e6, b.GetRight() / 1e6, b.GetBottom() / 1e6

    def shape(self, f, side, b):
        """courtyard polygon rasterised over its bbox cells"""
        poly = f.GetCourtyard(pcbnew.F_CrtYd if side == "F" else pcbnew.B_CrtYd)
        xs, ys = self.cells(b)
        return np.array([[poly.Contains(mm(i * RES, j * RES), -1, pcbnew.FromMM(RES))
                          for j in range(ys.start, ys.stop)] for i in range(xs.start, xs.stop)])

    def sides(self, f, side):
        return "FB" if f.GetAttributes() & pcbnew.FP_THROUGH_HOLE else side

    def cells(self, b):
        return (slice(max(0, int(b[0] / RES)), int(np.ceil(b[2] / RES)) + 1),
                slice(max(0, int(b[1] / RES)), int(np.ceil(b[3] / RES)) + 1))

    def put(self, ref, x, y, rot=0.0, side="F", mark=True):
        f = self.fp.get(ref) or self.make(ref)
        if side == "B" and not f.IsFlipped():
            f.Flip(f.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
        f.SetPosition(mm(x, y))
        f.SetOrientationDegrees(rot)
        if mark:
            f.BuildCourtyardCaches()
            for s in self.sides(f, side):
                own = f.GetCourtyard(pcbnew.F_CrtYd if s == "F" else pcbnew.B_CrtYd).OutlineCount()
                b = self.box(f, s if own else side)
                self.grid[s][self.cells(b)] |= self.shape(f, s if own else side, b) if ref in self.shaped else True
        self.where[ref] = (x, y, side)
        return f

    def ok(self, ref, b, f, side, region):
        if b[0] < region[0] or b[1] < region[1] or b[2] > region[2] or b[3] > region[3]:
            return False
        if self.forbid(ref, b):
            return False
        return not any(self.grid[s][self.cells(b)].any() for s in self.sides(f, side))

    def near(self, ref, tx, ty, side="F", region=None, rots=(0.0, 90.0), reach=40.0, top=0.0):
        """nearest free spot to (tx, ty), square spiral in 0.25 mm steps; top: a strip that deep above
        the part kept free too (its fanout vias; the region may exclude it, vias may go there)"""
        f = self.fp.get(ref) or self.make(ref)
        region = region or self.region
        local = {}
        for rot in rots:
            self.put(ref, 0.0, 0.0, rot, side, mark=False)
            local[rot] = self.box(f, side)
        step, k = 0.25, 0
        while k * step <= reach:
            d = k * step
            ring = [(0.0, 0.0)] if k == 0 else \
                [(-d + i * step, -d) for i in range(2 * k)] + [(d, -d + i * step) for i in range(2 * k)] + \
                [(d - i * step, d) for i in range(2 * k)] + [(-d, d - i * step) for i in range(2 * k)]
            for dx, dy in sorted(ring, key=lambda p: p[0] ** 2 + p[1] ** 2):
                for rot, lb in local.items():
                    x, y = tx + dx, ty + dy
                    b = (lb[0] + x, lb[1] + y, lb[2] + x, lb[3] + y)
                    strip = self.cells((b[0], b[1] - top, b[2], b[1]))
                    if self.ok(ref, b, f, side, region) and not (top and self.grid[side][strip].any()):
                        if top:
                            self.grid[side][strip] = True
                        return self.put(ref, x, y, rot, side)
            k += 1
        around = sorted(r for r, (x, y, sd) in self.where.items() if abs(x - tx) < reach and abs(y - ty) < reach)
        sys.exit(f"FAIL: no room for {ref} within {reach} mm of ({tx:.1f}, {ty:.1f}) on {side}.Cu; placed there: "
                 + " ".join(f"{r}@({self.where[r][0]:.1f},{self.where[r][1]:.1f})" for r in around))

    def unmatched(self, nets):
        """netlist nodes without a pad of that number on the placed footprint (their net would be lost)"""
        numbers = {ref: {p.GetNumber() for p in f.Pads()} for ref, f in self.fp.items()}
        return [f"{ref}.{pin}" for nodes in nets.values() for ref, pin in nodes
                if ref in numbers and pin not in numbers[ref]]

    def pad_xy(self, ref, num):
        p = next(p for p in self.fp[ref].Pads() if p.GetNumber() == num)
        return p.GetPosition().x / 1e6, p.GetPosition().y / 1e6


EDGE = 0.3                               # copper to the routed outline
PTH = 0.3                                # copper to a plated component hole


def write_rules(pro_path, classes, patterns, edge_parts=()):
    """the board rules into the .kicad_pro: 0.1 mm track / space, vias 0.45 / 0.25, copper 0.2 mm from a
    hole; classes [(name, clearance, track width)] beside Default (0.1 / 0.1); patterns {class: [net
    glob]}. The fab rules KiCad's board setup cannot tell apart go in the .kicad_dru next to it
    [sockets/parts/jlcpcb_pcb_capabilities.html]: copper EDGE from the outline (JLCPCB: >= 0.2 mm
    from a routed edge, the edge itself +-0.2 mm), except the pads of edge_parts (card-edge fingers);
    copper PTH from a plated component hole (JLCPCB: PTH to track 0.28 mm min, 0.35 recommended; via
    hole to track 0.2 mm)"""
    rules = [f'(rule "copper to the routed outline"\n  (constraint edge_clearance (min {EDGE}mm)))',
             f'(rule "copper to a plated component hole"\n  (condition "A.Pad_Type == \'Through-hole\'")\n'
             f'  (constraint hole_clearance (min {PTH}mm)))']
    rules += [f'(rule "{ref}: pads up to the outline"\n  (condition "A.memberOfFootprint(\'{ref}\')")\n'
              '  (constraint edge_clearance (min 0mm)))' for ref in edge_parts]
    pro_path.with_suffix(".kicad_dru").write_text("(version 1)\n" + "\n".join(rules) + "\n")
    pro = json.loads(pro_path.read_text())
    tmpl = json.loads(pathlib.Path("/usr/share/kicad/template/Edgeberry_Cartridge/"
                                   "Edgeberry_cartridge_template.kicad_pro").read_text())
    pro["board"] = {"design_settings": tmpl["board"]["design_settings"]}
    rules = pro["board"]["design_settings"]["rules"]
    rules.update(min_copper_edge_clearance=0.001, min_clearance=0.1, min_track_width=0.1, min_via_diameter=0.45,
                 min_through_hole_diameter=0.25, min_via_annular_width=0.1, min_hole_clearance=0.2)
    default = next(c for c in tmpl["net_settings"]["classes"] if c["name"] == "Default")
    via = dict(via_diameter=0.45, via_drill=0.25)
    pro["net_settings"] = {"meta": tmpl["net_settings"]["meta"], "classes": [
        dict(default, clearance=0.1, track_width=0.1, **via)] + [
        dict(default, name=n, clearance=c, track_width=w, **via) for n, c, w in classes],
        "netclass_patterns": [{"netclass": c, "pattern": "/" + p} for c, ps in patterns.items() for p in ps]}
    pro_path.write_text(json.dumps(pro, indent=2))


def drc(path, report):
    """kicad-cli DRC, errors only, into report (json); exit 1 on a violation"""
    r = subprocess.run(["nice", "-n", "19", "kicad-cli", "pcb", "drc", "--severity-error", "--format", "json",
                        "-o", str(report), str(path)], capture_output=True, text=True)
    if not report.exists():
        sys.exit(f"FAIL: kicad-cli drc: {r.stderr[-400:]}")
    rep = json.load(open(report))
    viol = rep.get("violations", [])
    print(f"DRC: {len(viol)} errors, {len(rep.get('unconnected_items', []))} unrouted connections")
    if viol:
        for v in viol[:25]:
            print("  ", v.get("type"), str(v.get("description"))[:80],
                  [str(i.get("description"))[:50] for i in v.get("items", [])[:2]])
        sys.exit(1)
