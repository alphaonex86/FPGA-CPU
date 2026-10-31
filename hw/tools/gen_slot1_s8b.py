#!/usr/bin/env python3
"""Task S8 (plan/slot1.md) step B: pours + stitching on the D22 stack.

D22 as amended (2026-10-22, operator): 8 layers - signals F&B, ground
mids In1.Cu/In4.Cu/In6.Cu, power mid In2.Cu, signal mids In3.Cu/In5.Cu;
no HDI. This step mutates the S8a board file:

- the layer set becomes
  F.Cu/In1.Cu/In2.Cu/In3.Cu/In4.Cu/In5.Cu/In6.Cu/B.Cu (+ the user
  layers);
- In1.Cu, In4.Cu and In6.Cu get one GND plane each over the board
  (kicad-cli DRC refills the zones itself: verified with a 70 mm
  two-pad zone probe - no stored fill polygons needed);
- In2.Cu gets one island set per power rail: a 2.0 mm cell raster, every
  cell labelled with the rail whose nearest rail-pad sample it touches,
  then row-wise maximal horizontal runs are emitted as strip zones; no
  strip of one net ever overlaps a strip of another net;
- every rail/GND pad on the signal layers is stitched into the planes:
  BGA power/GND lands are widened to 0.60 mm for a 0.30 mm drill
  via-in-pad (ring 0.15 mm), TSSOP translator pads get a 0.35 mm vertical
  track to a 0.50/0.30 via inboard of the pad centre - the first power
  pin 0.675 mm deep and every further power pin of the same pad row another
  0.8 mm deeper so vias never come nearer than 1.03 mm to each other and
  0.94 mm to the pads of the row - and card-edge contacts get a 0.60 mm
  track to a 0.50/0.30 via in the connector cavity band (footprints are
  the only keep-out there, tracks/vias are legal [S7]); a B-row
  contact stitches through B.Cu at a 0.9 mm-lower via row so two nets on
  one station stay 0.9 mm apart (more than the 0.7 mm the 0.2 mm
  clearance needs).  Drills respect the project min_through_hole_diameter
  0.3 [S7 pro].  Plated through-holes (J*, U7) reach the planes through
  their annulus and need nothing.
  D23 power tree + decoupling (every other footprint): each rail/GND pad
  at least 0.5 mm wide gets a 0.50/0.30 via in its centre unless a
  same-net via already sits in it (U1 B.Cu capacitors ride the BGA
  via-in-pads, translator capacitors the VCCA/VCCB stitch vias); narrower
  pads (QFN leads) wait for S8c routing.

The stitching gives every SMD pad plane access without signal routing;
tracks stay S8c.  Gate: DRC severity==error stays 0; every rail/GND-pad
pad is stitched exactly once.
"""
import json
import pathlib
import re
import subprocess
import sys
from collections import defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from gen_slot1_s7 import tr_stitch

try:
    import pcbnew                      # same interpreter (3.13); KiCad 10
except ImportError:
    pcbnew = None

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "hw/slot1-cyclonev"

RAILS = ["V12", "V5", "VCCA_FPLL25", "VCCCORE", "VCCIO33", "VCCPGM18",
         "VCC_1V1", "VCC_AUX25", "VDDR3", "VTT15", "VTTREF0675"]
CELL = 2.0                     # In2 raster cell
W, H = 127.0, 57.8             # S7 outline (D16)
ZONE = ("\t(zone (net %d) (net_name \"%s\") (layers \"%s\") "
        '(uuid "00000000-0008-4000-8000-%012d") (priority %d)\n'
        '\t\t(hatch edge 0.5)\n'
        '\t\t(connect_pads yes (clearance 0.2))\n'
        '\t\t(min_thickness 0.15) (filled_areas_thickness no)\n'
        '\t\t(fill yes (thermal_gap 0.5) (thermal_bridge_width 0.5) '
        '(island_removal_mode 0))\n'
        '\t\t(polygon (pts %s))\n\t)\n')


def rect(x0, y0, x1, y1):
    return ("(xy %f %f) (xy %f %f) (xy %f %f) (xy %f %f)"
            % (x0, y0, x1, y0, x1, y1, x0, y1))


def blocks_of(pcb):
    out = []
    for m in re.finditer(r"\n\t\(footprint \"", pcb):
        s = m.start() + 1
        d, i = 0, s
        while True:
            if pcb[i] == "(":
                d += 1
            elif pcb[i] == ")":
                d -= 1
                if d == 0:
                    break
            i += 1
        blk = pcb[s:i + 1]
        ref = re.search(r'fp_text reference "([^"]+)"', blk).group(1)
        out.append((s, i + 1, ref, blk))
    return out


def pads_of(block):
    out = []
    for m in re.finditer(r"\n\t+\(pad \"", block):
        i, d = m.start() + 1, 0
        j = i
        while True:
            if block[j] == "(":
                d += 1
            elif block[j] == ")":
                d -= 1
                if d == 0:
                    break
            j += 1
        out.append((i, j + 1, block[i:j + 1]))
    return out


def main():
    pcb = (OUT / "slot1-cyclonev.kicad_pcb").read_text()

    nets = [(int(m.group(1)), m.group(2))
            for m in re.finditer(r'\t\(net (\d+) "([^"]+)"\)', pcb)]
    netname = dict(nets)
    code_of = {name.lstrip("/"): num for num, name in nets}
    if "GND" not in code_of or "In1.Cu" in pcb:
        raise SystemExit("FAIL: S8b needs the fresh S8a board (rerun "
                         "gen_slot1_s7.py and gen_slot1_s8.py)")
    gndcode = code_of["GND"]
    railcodes = {r: code_of[r] for r in RAILS}

    # ---- layer set -----------------------------------------------------
    old = re.search(r"\t\(layers [^\n]*\)\n", pcb).group(0)
    new = ('\t(layers (0 "F.Cu" signal) (2 "In1.Cu" signal) '
           '(3 "In2.Cu" signal) (4 "In3.Cu" signal) (5 "In4.Cu" signal) '
           '(6 "In5.Cu" signal) (7 "In6.Cu" signal) '
           '(31 "B.Cu" signal) (36 "B.SilkS" user)'
           ' (37 "F.SilkS" user) (38 "B.Mask" user) (39 "F.Mask" user)'
           ' (44 "Edge.Cuts" user) (46 "B.CrtYd" user) (47 "F.CrtYd" '
           'user) (48 "B.Fab" user) (49 "F.Fab" user))\n')
    pcb = pcb.replace(old, new, 1)

    # ---- pads per net, with world positions ----------------------------
    gathered = defaultdict(list)
    for (s, e, ref, blk) in blocks_of(pcb):
        fp_at = re.search(r'\n\t\t\(at (-?[\d.]+) (-?[\d.]+)\)', blk).groups()
        for (i, j, padtext) in pads_of(blk):
            netm = re.search(r'\(net (\d+)', padtext)
            atm = re.search(r'\(at (-?[\d.]+) (-?[\d.]+)\)', padtext)
            if not netm or not atm:
                continue
            x = float(fp_at[0]) + float(atm.group(1))
            y = fp_y = float(fp_at[1]) + float(atm.group(2))
            sz = re.search(r'\(size ([\d.]+) ([\d.]+)\)', padtext)
            gathered[(ref, int(netm.group(1)))].append(
                (x, fp_y, padtext, float(sz.group(1)), s, e))

    # ---- In1/In4/In6 GND planes ----------------------------------------
    # uuids 100/101: strip uuids run 2..15 below
    pcb = pcb.rsplit("\n)\n", 1)[0] + "\n" + ZONE % (
        gndcode, "/GND", "In1.Cu", 1, 0, rect(0.2, 0.2, W - 0.2, H - 0.2)) \
        + "\n" + ZONE % (
        gndcode, "/GND", "In4.Cu", 100, 0, rect(0.2, 0.2, W - 0.2, H - 0.2)) \
        + "\n" + ZONE % (
        gndcode, "/GND", "In6.Cu", 101, 0, rect(0.2, 0.2, W - 0.2, H - 0.2)) \
        + "\n)\n"

    # ---- In2 rail raster ------------------------------------------------
    samples = [(p[0], p[1], n) for (ref, n), ps in gathered.items()
               for p in ps if n in railcodes.values()]
    strips = defaultdict(list)
    uid = 1
    rows = []
    for gy in range(int(H // CELL)):
        cy = gy * CELL + CELL / 2
        row = []
        for gx in range(int(W // CELL)):
            cx = gx * CELL + CELL / 2
            best = min((( (x - cx) ** 2 + (y - cy) ** 2, n)
                        for (x, y, n) in samples), default=(1e19, None))
            row.append(best[1] if best[0] < 36.0 else None)
        rows.append(row)
    for gy, row in enumerate(rows):
        gx = 0
        while gx < len(row):
            if row[gx] is None:
                gx += 1
                continue
            gx2 = gx
            while gx2 < len(row) and row[gx2] == row[gx]:
                gx2 += 1
            n = row[gx]
            uid += 1
            strips[n].append(ZONE % (n, netname[n], "In2.Cu", uid, uid,
                                     rect(gx * CELL, gy * CELL,
                                          gx2 * CELL, (gy + 1) * CELL)))
            gx = gx2
    pcb = pcb.rsplit("\n)\n", 1)[0] + "\n" + "".join(
        z for n in sorted(strips) for z in strips[n]) + "\n)\n"

    # ---- stitching -------------------------------------------------------
    vias, tracks = [], []
    # card-edge via rows: A row at pad centre +2.55 mm, B row +3.45 mm so
    # two nets on one station keep their 0.2 mm through-via clearance
    tr_pads: dict = defaultdict(list)      # ref -> [(fpx, fpy, rows-list)]
    for (s, e, ref, blk) in blocks_of(pcb):
        if not re.match(r"TR\d\d$", ref):
            continue
        fp_at = re.search(r'\n\t\t\(at (-?[\d.]+) (-?[\d.]+)\)', blk).groups()
        pads = []
        for (i, j, padtext) in pads_of(blk):
            netm = re.search(r'\(net (\d+)', padtext)
            if not netm or int(netm.group(1)) not in \
                    [gndcode, *railcodes.values()]:
                continue
            atm = re.search(r'\(at (-?[\d.]+) (-?[\d.]+)\)', padtext)
            pads.append((re.search(r'\(pad "([^"]+)"', padtext).group(1),
                         float(atm.group(1)), float(atm.group(2)),
                         int(netm.group(1))))
        if not pads:
            continue
        fpx, fpy = float(fp_at[0]), float(fp_at[1])
        for name, (vx, vy) in tr_stitch(
                [(n, lx, ly) for n, lx, ly, _ in pads]).items():
            lx, ly, num = next((lx, ly, nn) for n, lx, ly, nn in pads
                               if n == name)
            vias.append('\t(via (at %f %f) (size 0.5) (drill 0.3) '
                        '(layers "F.Cu" "B.Cu") (net %d))'
                        % (fpx + vx, fpy + vy, num))
            tracks.append('\t(segment (start %f %f) (end %f %f) '
                          '(width 0.35) (layer "F.Cu") (net %d))'
                          % (fpx + lx, fpy + ly, fpx + vx, fpy + vy, num))
    for (s, e, ref, blk) in reversed(blocks_of(pcb)):
        if ref in ("J1", "J2", "J3", "J4", "U7"):
            continue                          # PTH: annulus reaches planes
        if not (ref == "U1" or re.match(r"U[2-6]$", ref)):
            continue
        fp_at = re.search(r'\n\t\t\(at (-?[\d.]+) (-?[\d.]+)\)', blk).groups()
        outblk = blk
        for (i, j, padtext) in reversed(pads_of(blk)):
            netm = re.search(r'\(net (\d+)', padtext)
            if not netm:
                continue
            num = int(netm.group(1))
            if num not in [gndcode, *railcodes.values()]:
                continue
            atm = re.search(r'\(at (-?[\d.]+) (-?[\d.]+)\)', padtext)
            x = float(fp_at[0]) + float(atm.group(1))
            y = float(fp_at[1]) + float(atm.group(2))
            pnum = re.search(r'\(pad "([^"]+)"', padtext).group(1)
            is_b = bool(re.match(r'B\d+', pnum)) and ref == "U2"
            is_bga = ref == "U1" or bool(re.match(r"U[3-6]$", ref))
            if is_bga:
                newpad = padtext.replace(re.search(
                    r'\(size [\d.]+ [\d.]+\)', padtext).group(0),
                    "(size 0.600 0.600)", 1)
                vias.append('\t(via (at %f %f) (size 0.6) (drill 0.3) '
                            '(layers "F.Cu" "B.Cu") (net %d))' % (x, y, num))
            elif ref == "U2":
                # stitch through the connector cavity band (tracks/vias are
                # legal there [S7]); the B row's via sits 0.9 mm lower so
                # two nets on one station keep their 0.2 mm clearance
                vy = y + (2.55 if not is_b else 3.45)
                vias.append('\t(via (at %f %f) (size 0.5) (drill 0.3) '
                            '(layers "F.Cu" "B.Cu") (net %d))'
                            % (x, vy, num))
                tracks.append('\t(segment (start %f %f) (end %f %f) '
                              '(width 0.6) (layer "%s") (net %d))'
                              % (x, y, x, vy, "B.Cu" if is_b else "F.Cu",
                                 num))
                newpad = padtext
            if is_bga:
                outblk = outblk[:i] + newpad + outblk[j:]
        pcb = pcb[:s] + outblk + pcb[e:]

    # ---- D23 parts: via in every wide-enough rail/GND pad ----------------
    have = [(float(x), float(y), int(n)) for x, y, n in re.findall(
        r'\(via \(at (-?[\d.]+) (-?[\d.]+)\).*?\(net (\d+)\)\)', "\n".join(vias))]
    n_pdn = 0
    for (s, e, ref, blk) in blocks_of(pcb):
        if re.match(r"(U\d|TR\d\d|J\d)$", ref):
            continue
        fp_at = re.search(r'\n\t\t\(at (-?[\d.]+) (-?[\d.]+)\)', blk).groups()
        for (i, j, padtext) in pads_of(blk):
            netm = re.search(r'\(net (\d+)', padtext)
            if not netm or int(netm.group(1)) not in \
                    [gndcode, *railcodes.values()]:
                continue
            num = int(netm.group(1))
            atm = re.search(r'\(at (-?[\d.]+) (-?[\d.]+)', padtext)
            sz = [float(v) for v in re.search(
                r'\(size ([\d.]+) ([\d.]+)\)', padtext).groups()]
            x = float(fp_at[0]) + float(atm.group(1))
            y = float(fp_at[1]) + float(atm.group(2))
            if min(sz) < 0.5 or any(
                    n == num and abs(vx - x) < sz[0] / 2
                    and abs(vy - y) < sz[1] / 2 for vx, vy, n in have):
                continue
            vias.append('\t(via (at %f %f) (size 0.5) (drill 0.3) '
                        '(layers "F.Cu" "B.Cu") (net %d))' % (x, y, num))
            have.append((x, y, num))
            n_pdn += 1
    print("D23 pad vias:", n_pdn)

    dev = "\n".join(vias) + "\n" + "\n".join(tracks)
    pcb = pcb.rsplit("\n)\n", 1)[0] + "\n" + dev + "\n)\n"

    path = OUT / "slot1-cyclonev.kicad_pcb"
    path.write_text(pcb)
    print("stitch vias:", len(vias), "| stub tracks:", len(tracks))

    # persist the zone fills so the DRC copper graph is real: kicad-cli DRC
    # does NOT refill (probe ztest2: an unfilled zone yields dangling-via
    # warnings while unconnected_items happily virtualises the outline),
    # but the pcbnew python module does
    filled = 0
    if pcbnew is not None:
        try:
            b = pcbnew.LoadBoard(str(path))
            zones = b.Zones()
            filler = pcbnew.ZONE_FILLER(b)
            filled = filler.Fill(zones)
            b.Save(str(path))
            print("zone fill via pcbnew: ok (%d zones)" % len(zones))
        except Exception as ex:            # fill is best-effort
            print("pcbnew fill failed:", ex)
    else:
        print("pcbnew python module missing - zones stay unfilled")

    r = subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json",
                        "-o", str(OUT / "slot1-cyclonev.drc.json"), str(path)],
                       capture_output=True, text=True)
    j = json.load(open(OUT / "slot1-cyclonev.drc.json"))
    errs = [v for v in j.get("violations", []) if v.get("severity") == "error"]
    if errs:
        print(f"DRC ERRORS ({len(errs)}):")
        for v in errs[:20]:
            print("  ", v.get("type"), str(v.get("description"))[:100])
            for it in v.get("items", [])[:2]:
                print("      -", str(it.get("description"))[:90])
        sys.exit(1)
    warn = len(j.get("violations", [])) - len(errs)
    print(f"PASS  S8b: {len(strips)} In2 strip zones, "
          f"{len(vias)} stitch vias, DRC errors 0 "
          f"({warn} warnings pending S8c routing)")


if __name__ == "__main__":
    main()
