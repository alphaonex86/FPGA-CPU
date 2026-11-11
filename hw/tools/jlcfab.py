#!/usr/bin/env python3
"""JLCPCB fabrication + assembly files of a routed board, common to gen_c2mu_s9.py and the socket
T9 scripts: kicad-cli DRC gate (0 errors, 0 unrouted), BOM (Comment, Designator, Footprint, LCSC
Part #), CPL (Designator, Mid X, Mid Y, Layer, Rotation), Gerbers + Excellon drill zip, live JLCPCB
stock and list price per BOM line. JLCPCB's placement preview still has to be checked by eye: its
library rotations differ from KiCad's for some packages."""
import collections
import csv
import json
import subprocess
import sys
import time
import urllib.request
import zipfile

import pcbnew

import close_route

JLC_SEARCH = "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList"


def drc_clean(pcb, fab_dir):
    out = fab_dir / "drc.json"
    r = subprocess.run(["nice", "-n", "19", "kicad-cli", "pcb", "drc", "--severity-error", "--format", "json",
                        "-o", str(out), str(pcb)], capture_output=True, text=True)
    if r.returncode != 0 or not out.exists():
        sys.exit(f"FAIL: kicad-cli drc: {r.stderr.strip()[:300]}")
    rep = json.load(open(out))
    out.unlink()
    viol, unrouted = rep.get("violations", []), rep.get("unconnected_items", [])
    print(f"DRC: {len(viol)} errors, {len(unrouted)} unrouted")
    return not viol and not unrouted


def bom_groups(board, no_part):
    groups = collections.defaultdict(list)
    for f in board.GetFootprints():
        ref = f.GetReference()
        if ref not in no_part:
            groups[(f.GetValue(), f.GetFPID().GetLibItemName().wx_str())].append(ref)
    return groups


def jlc_part(code):
    req = urllib.request.Request(JLC_SEARCH, json.dumps({"keyword": code, "currentPage": 1, "pageSize": 5}).encode(),
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.load(r)
    hits = [p for p in (d.get("data") or {}).get("componentPageInfo", {}).get("list") or []
            if p["componentCode"] == code]
    return hits[0] if hits else None


def stock_check(groups, boards, lcsc, consigned):
    ok, cost = True, 0.0
    for (value, fp), refs in sorted(groups.items(), key=lambda g: lcsc[g[0]]):
        code, need = lcsc[(value, fp)], len(refs) * boards
        p = jlc_part(code)
        time.sleep(0.3)
        if p is None:
            print(f"FAIL  {code} {value}: not found at JLCPCB")
            ok = False
            continue
        price = next((q["productPrice"] for q in p["componentPrices"] if q["startNumber"] <= need <= q["endNumber"]),
                     p["componentPrices"][-1]["productPrice"])
        cost += price * need
        line = (f"{code:>10} {p['componentLibraryType'][:5]:5} stock {p['stockCount']:>8} need {need:>4} "
                f"{p['componentModelEn'][:24]:24} {p['componentSpecificationEn'][:16]:16} {value}")
        if code in consigned:
            print(f"CONS  {line}  <- {consigned[code]}")
        elif p["stockCount"] < need:
            print(f"FAIL  {line}  (short)")
            ok = False
        else:
            print(f"ok    {line}")
    print(f"parts at JLCPCB list prices: ~US$ {cost:.0f} for {boards} boards (consigned included at list price)")
    return ok


def write_bom(groups, lcsc, path):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
        for (value, fp), refs in sorted(groups.items(), key=lambda g: g[1][0]):
            w.writerow([value, ",".join(sorted(refs)), fp, lcsc[(value, fp)]])


def write_cpl(board, no_part, path):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        for fp in sorted(board.GetFootprints(), key=lambda fp: fp.GetReference()):
            if fp.GetReference() in no_part:
                continue
            pos = fp.GetPosition()
            w.writerow([fp.GetReference(), f"{pos.x / 1e6:.4f}mm", f"{-pos.y / 1e6:.4f}mm",
                        "Bottom" if fp.IsFlipped() else "Top", f"{fp.GetOrientationDegrees() % 360:.1f}"])


def write_gerbers(pcb, board, fab_dir):
    copper = [pcbnew.LayerName(L) for L in close_route.copper_layers(board)]
    tmp = fab_dir / "gerbers"
    tmp.mkdir(exist_ok=True)
    for cmd in (["gerbers", "--no-protel-ext", "--subtract-soldermask", "--layers",
                 ",".join(copper + ["F.Paste", "B.Paste", "F.SilkS", "B.SilkS", "F.Mask", "B.Mask", "Edge.Cuts"])],
                ["drill", "--format", "excellon", "--excellon-separate-th", "--generate-map", "--map-format", "gerberx2"]):
        r = subprocess.run(["nice", "-n", "19", "kicad-cli", "pcb", "export", *cmd, "-o", f"{tmp}/", str(pcb)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit(f"FAIL: kicad-cli export {cmd[0]}: {r.stderr.strip()[:300]}")
    files = sorted(p for p in tmp.iterdir() if p.is_file())
    check_package(board, pcb.stem, {p.name: p for p in files}, copper)
    with zipfile.ZipFile(fab_dir / f"{pcb.stem}-gerbers.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for p in files:
            z.write(p, p.name)
    for p in files:
        p.unlink()
    tmp.rmdir()
    print(f"gerbers: {len(files)} files")


def check_package(board, stem, files, copper):
    """the files as the fab reads them, not as the export was asked: a Gerber with artwork per copper
    layer, mask and the outline, 7 non-copper layers in all; the drill files hold one hit per via and
    plated pad hole (PTH) and per unplated hole (NPTH); exit 1 otherwise"""
    drawn = lambda name: name in files and any(c in files[name].read_text() for c in ("D01*", "D03*", "G36*"))
    bad = [name for name in (f"{stem}-{layer.replace('.', '_')}.gbr" for layer in copper + ["F.Mask", "B.Mask", "Edge.Cuts"])
           if not drawn(name)]
    gerbers = [n for n in files if n.endswith(".gbr") and not n.endswith("-drl_map.gbr")]
    if len(gerbers) != len(copper) + 7:
        bad.append(f"{len(gerbers)} Gerber layers, not {len(copper)} copper + 7")
    holes = {"PTH": sum(isinstance(t, pcbnew.PCB_VIA) for t in board.GetTracks()), "NPTH": 0}
    for f in board.GetFootprints():
        for p in f.Pads():
            if p.GetDrillSizeX():
                holes["NPTH" if p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH else "PTH"] += 1
    for kind, n in holes.items():
        name = f"{stem}-{kind}.drl"
        got = sum(line.startswith("X") for line in files[name].read_text().splitlines()) if name in files else -1
        if got != n:
            bad.append(f"{name}: {got} holes, the board has {n}")
    if bad:
        sys.exit(f"FAIL: fabrication package: {bad}")
    print(f"package: {len(gerbers)} Gerber layers ({len(copper)} copper), {holes['PTH']} plated and {holes['NPTH']} "
          "unplated holes, as on the board")


def fab(pcb, lcsc, no_part, consigned, boards, order):
    """pcb: the routed .kicad_pcb; lcsc {(value, footprint name): LCSC number}; no_part: references
    without a part (edge fingers, a header base); consigned {LCSC number: source}: not stocked by
    JLCPCB, bought elsewhere; exit 1 on a failed check"""
    fab_dir = pcb.parent / "fab"
    fab_dir.mkdir(exist_ok=True)
    if not drc_clean(pcb, fab_dir):
        sys.exit("FAIL: route the board first")
    board = pcbnew.LoadBoard(str(pcb))
    groups = bom_groups(board, no_part)
    missing = sorted(set(groups) - set(lcsc))
    unused = sorted(set(lcsc) - set(groups))
    if missing or unused:
        sys.exit(f"FAIL: parts without an LCSC number {missing}; LCSC entries no part uses {unused}")
    ok = stock_check(groups, boards, lcsc, consigned)
    write_bom(groups, lcsc, fab_dir / f"{pcb.stem}-bom.csv")
    write_cpl(board, no_part, fab_dir / f"{pcb.stem}-cpl.csv")
    write_gerbers(pcb, board, fab_dir)
    if not ok:
        sys.exit(1)
    print(f"PASS  {pcb.stem} fab: {sum(map(len, groups.values()))} parts in {len(groups)} BOM lines, files in {fab_dir}")
    print(order)
