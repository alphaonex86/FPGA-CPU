#!/usr/bin/env python3
"""Slot 1 C2 Mu cartridge: 3D clearance under the LattePanda Mu.

Usage: python3 -I hw/tools/check_mu_clearance.py [board.kicad_pcb]   (default hw/slot1-c2mu; gen_c2mu_s9.py runs it)
kicad-cli exports the board's 3D models to GLB; on a CELL grid the underside of the Mu model (module,
its bottom parts, socket) is compared with the top of every other part above the board.
Checks (exit 1): every part >= MIN_GAP below the Mu; each Mu standoff touches the module (|gap| <=
SEAT_TOL: the model pose of gen_mu_lib.py). The Mu top is printed only: the operator allows it above
Intel's 32.8 mm primary-side envelope (D16) on this cartridge (2026-11-06).
"""
import json
import pathlib
import re
import struct
import subprocess
import sys
import tempfile

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from gen_mu_lib import FP_NAME, STANDOFF

ROOT = pathlib.Path(__file__).resolve().parents[2]
PCB = ROOT / "hw/slot1-c2mu/slot1-c2mu.kicad_pcb"
CELL = 0.25                              # mm
DENSITY = 40                             # surface samples per mm^2 (~0.16 mm apart)
MIN_GAP = 0.3                            # mm: margin for the measured model pose (~0.2 mm)
SEAT_TOL = 0.1                           # mm
DTYPE = {5121: np.uint8, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}


def export_glb(pcb, out, *args):
    r = subprocess.run(["nice", "-n", "19", "kicad-cli", "pcb", "export", "glb", "-f", *args, "-o", str(out), str(pcb)],
                       capture_output=True, text=True)
    if r.returncode != 0 or not out.exists():
        sys.exit(f"FAIL: kicad-cli export glb: {r.stderr.strip()[:300]}")
    return out


def node_matrix(node):
    if "matrix" in node:
        return np.array(node["matrix"], float).reshape(4, 4).T
    x, y, z, w = node.get("rotation", (0, 0, 0, 1))
    rot = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                    [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                    [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    m = np.eye(4)
    m[:3, :3] = rot * np.array(node.get("scale", (1, 1, 1)))
    m[:3, 3] = node.get("translation", (0, 0, 0))
    return m


def glb_triangles(path):
    """{name of each top-level node (the reference): (n, 3, 3) triangles in mm}; glTF axes: x, up, board y."""
    data = path.read_bytes()
    jlen = struct.unpack_from("<I", data, 12)[0]
    gltf = json.loads(data[20:20 + jlen])
    blob = data[28 + jlen:]

    def accessor(i):
        a = gltf["accessors"][i]
        view = gltf["bufferViews"][a["bufferView"]]
        dtype = np.dtype(DTYPE[a["componentType"]])
        width = {"SCALAR": 1, "VEC3": 3}[a["type"]]
        return np.ndarray((a["count"], width), dtype, blob, view.get("byteOffset", 0) + a.get("byteOffset", 0),
                          (view.get("byteStride") or width * dtype.itemsize, dtype.itemsize))

    out = {}

    def walk(i, parent, ref):
        node = gltf["nodes"][i]
        m = parent @ node_matrix(node)
        for prim in gltf["meshes"][node["mesh"]]["primitives"] if "mesh" in node else []:
            if prim.get("mode", 4) != 4:
                sys.exit(f"FAIL: {path.name}: primitive mode {prim['mode']}, only triangles handled")
            v = accessor(prim["attributes"]["POSITION"]).astype(float) @ m[:3, :3].T + m[:3, 3]
            idx = accessor(prim["indices"]).ravel() if "indices" in prim else np.arange(len(v))
            out.setdefault(ref, []).append(v[idx].reshape(-1, 3, 3) * 1000.0)
        for c in node.get("children", []):
            walk(c, m, ref)

    for r in gltf["scenes"][gltf.get("scene", 0)]["nodes"]:
        root = gltf["nodes"][r]
        for c in root.get("children", []):
            walk(c, node_matrix(root), gltf["nodes"][c].get("name", "?"))
    return {ref: np.concatenate(t) for ref, t in out.items()}


def surface_points(tri, rng):
    """Random points on the triangles, DENSITY per mm^2."""
    area = 0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
    pick = rng.choice(len(tri), int(area.sum() * DENSITY) + 1, p=area / area.sum())
    u, v = rng.random((2, len(pick), 1))
    flip = u + v > 1
    u, v = np.where(flip, 1 - u, u), np.where(flip, 1 - v, v)
    t = tri[pick]
    return t[:, 0] + u * (t[:, 1] - t[:, 0]) + v * (t[:, 2] - t[:, 0])


def height_map(p, reduce):
    """{(i, j) grid cell: reduced height}."""
    ij = np.floor(p[:, [0, 2]] / CELL).astype(np.int64)
    cells, inverse = np.unique(ij, axis=0, return_inverse=True)
    h = np.full(len(cells), np.inf if reduce is np.minimum else -np.inf)
    reduce.at(h, inverse.ravel(), p[:, 1])
    return dict(zip(map(tuple, cells.tolist()), h.tolist()))


def min_gap(mu_low, part_top):
    gaps = [(mu_low[c] - h, c) for c, h in part_top.items() if c in mu_low]
    return min(gaps) if gaps else None


def check(pcb=PCB):
    refs ={ref: fp for fp, ref in re.findall(r'\n\t\(footprint "(?:[^":]*:)?([^"]+)".*?\(property "Reference" "([^"]+)"',
                                              pcb.read_text(), re.S)}
    mu = [r for r, fp in refs.items() if fp == FP_NAME]
    standoffs = sorted(r for r, fp in refs.items() if fp == STANDOFF)
    if len(mu) != 1 or not standoffs:
        sys.exit(f"FAIL: {pcb.name}: expected one {FP_NAME} and its {STANDOFF}s, found {mu} {standoffs}")
    with tempfile.TemporaryDirectory() as tmp:
        board = glb_triangles(export_glb(pcb, pathlib.Path(tmp) / "board.glb", "--board-only"))
        parts = glb_triangles(export_glb(pcb, pathlib.Path(tmp) / "parts.glb", "--no-board-body"))
    board_top = max(t[..., 1].max() for t in board.values())
    rng = np.random.default_rng(1)
    mu_points = surface_points(parts.pop(mu[0]), rng)
    mu_low = height_map(mu_points, np.minimum)
    errors, worst, seats = [], (np.inf, "-"), {}
    for ref, tri in parts.items():
        p = surface_points(tri, rng)
        p = p[p[:, 1] > board_top]                           # B.Cu parts and solder tails stay below
        g = min_gap(mu_low, height_map(p, np.maximum)) if len(p) else None
        if ref in standoffs:
            seats[ref] = "none" if g is None else f"{g[0]:.2f}"
            if g is None or abs(g[0]) > SEAT_TOL:
                errors.append(f"standoff {ref} does not touch the Mu: gap {seats[ref]} mm")
        elif g is not None:
            worst = min(worst, (g[0], ref))
            if g[0] < MIN_GAP:
                errors.append(f"{ref} {refs.get(ref, '?')}: {g[0]:.2f} mm under the Mu at "
                              f"({(g[1][0] + 0.5) * CELL:.2f}, {(g[1][1] + 0.5) * CELL:.2f})")
    errors += [f"standoff {r} has no 3D model" for r in standoffs if r not in seats]
    top = mu_points[:, 1].max() - board_top
    print(f"{pcb.name}: Mu {mu[0]}: closest part {worst[1]} {worst[0]:.2f} mm, standoff gaps "
          f"{', '.join(f'{r} {seats.get(r, "none")}' for r in standoffs)} mm, top {top:.2f} mm above the board")
    if errors:
        sys.exit("FAIL: Mu clearance\n  " + "\n  ".join(errors))


if __name__ == "__main__":
    check(pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else PCB)
