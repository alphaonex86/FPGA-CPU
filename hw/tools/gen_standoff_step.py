#!/usr/bin/env python3
"""3D model of the Mu's M2 standoff, Sinhoo SMTSO2066CTJ (LCSC C2916353), from its drawing
sockets/parts/xhyj_smtso2066ctj.pdf. LCSC's own model (SMD_BD5.6-D3.6) is the family's 2.5 mm body.

Usage: python3 -I hw/tools/gen_standoff_step.py   (one-off, the STEP is in the tree; needs OCP:
pip install cadquery-ocp)
Output: hw/lib/3dmodels/Standoff_Sinhoo_SMTSO2066CTJ.step, origin on the PCB top at the hole centre:
body 5.56 x 6.60 above, spigot 3.60 x 1.53 in the hole, M2 bore through (minor diameter 1.6, no
thread), chamfers 0.20 at the top and 0.15 at the spigot end (not dimensioned: read off the drawing).
Checks (exit 1): STEP written, bounding box = drawing.
"""
import math
import pathlib
import sys

from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon
from OCP.BRepPrimAPI import BRepPrimAPI_MakeRevol
from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "hw/lib/3dmodels/Standoff_Sinhoo_SMTSO2066CTJ.step"
BODY_R, BODY_H = 5.56 / 2, 6.60
SPIGOT_R, SPIGOT_H = 3.60 / 2, 1.53
BORE_R = 1.6 / 2
TOP_C, END_C = 0.20, 0.15
# (radius, z) half section, revolved about Z
PROFILE = [(BORE_R + END_C, -SPIGOT_H), (SPIGOT_R - END_C, -SPIGOT_H), (SPIGOT_R, -SPIGOT_H + END_C),
           (SPIGOT_R, 0), (BODY_R, 0), (BODY_R, BODY_H - TOP_C), (BODY_R - TOP_C, BODY_H),
           (BORE_R + TOP_C, BODY_H), (BORE_R, BODY_H - TOP_C), (BORE_R, -SPIGOT_H + END_C)]


def main():
    poly = BRepBuilderAPI_MakePolygon()
    for r, z in PROFILE:
        poly.Add(gp_Pnt(r, 0, z))
    poly.Close()
    face = BRepBuilderAPI_MakeFace(poly.Wire()).Face()
    solid = BRepPrimAPI_MakeRevol(face, gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), 2 * math.pi).Shape()
    box = Bnd_Box()
    BRepBndLib.Add_s(solid, box)
    lo, hi = box.CornerMin(), box.CornerMax()
    got = [round(v, 2) for v in (lo.X(), lo.Y(), lo.Z(), hi.X(), hi.Y(), hi.Z())]
    want = [-BODY_R, -BODY_R, -SPIGOT_H, BODY_R, BODY_R, BODY_H]
    if any(abs(g - w) > 0.01 for g, w in zip(got, want)):
        sys.exit(f"FAIL: bounding box {got}, drawing {want}")
    writer = STEPControl_Writer()
    writer.Transfer(solid, STEPControl_AsIs)
    if writer.Write(str(OUT)) != IFSelect_RetDone:
        sys.exit(f"FAIL: STEP write {OUT}")
    print(f"wrote {OUT.relative_to(ROOT)}: bbox {got}")


if __name__ == "__main__":
    main()
