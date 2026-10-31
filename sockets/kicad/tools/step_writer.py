#!/usr/bin/env python3
"""Minimal AP214 STEP writer for flat-faced solids.

WHY THIS EXISTS: this machine has no CAD toolkit - no cadquery, no build123d, no
FreeCAD, no OpenSCAD, no OCC python bindings.  The boards still need 3D models so
the operator can judge mechanical clearance in KiCad's 3D viewer and render in
Blender.  A polyhedron is enough for that, and a polyhedron is easy to write as
STEP by hand: every face is planar, every edge is a straight line.

STEP, not VRML, on purpose:
  - STEP carries an explicit unit (MILLI METRE here), so a model cannot come out
    at the wrong scale.  KiCad's legacy VRML models are authored in 0.1 inch
    units, which is exactly the kind of silent factor-of-25.4 mistake worth
    avoiding.
  - `kicad-cli pcb export step` and `... export glb` consume STEP models.  VRML
    models are ignored by those, so a VRML-only model would be invisible in the
    Blender path.
  - KiCad's 3D viewer tessellates STEP through OCC and honours the colours
    written here.

Geometry model: a solid is (vertices, faces).  `vertices` is a list of (x, y, z)
in millimetres.  `faces` is a list of vertex-index loops, each ordered
counter-clockwise as seen from OUTSIDE the solid, so the right-hand rule gives
the outward normal.  Faces must be planar; every edge must be shared by exactly
two faces.  Both are checked before anything is written.
"""
import datetime
import math
import os
import re


# ----------------------------------------------------------------------------
# primitives
# ----------------------------------------------------------------------------

def box(x0, x1, y0, y1, z0, z1):
    """Axis-aligned box.  Returns (vertices, faces)."""
    if not (x1 > x0 and y1 > y0 and z1 > z0):
        raise ValueError("box needs x1>x0, y1>y0, z1>z0, got "
                         "(%g,%g) (%g,%g) (%g,%g)" % (x0, x1, y0, y1, z0, z1))
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
         (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    f = [[0, 3, 2, 1],          # -Z
         [4, 5, 6, 7],          # +Z
         [0, 1, 5, 4],          # -Y
         [1, 2, 6, 5],          # +X
         [2, 3, 7, 6],          # +Y
         [3, 0, 4, 7]]          # -X
    return v, f


def prism(poly, z0, z1):
    """Extrude a counter-clockwise 2D polygon [(x,y), ...] from z0 to z1."""
    n = len(poly)
    if n < 3:
        raise ValueError("prism needs at least 3 points, got %d" % n)
    if z1 <= z0:
        raise ValueError("prism needs z1>z0, got %g..%g" % (z0, z1))
    if signed_area(poly) <= 0.0:
        raise ValueError("prism polygon must be counter-clockwise "
                         "(signed area %g)" % signed_area(poly))
    v = [(x, y, z0) for x, y in poly] + [(x, y, z1) for x, y in poly]
    f = [list(range(n - 1, -1, -1)), list(range(n, 2 * n))]
    for i in range(n):
        j = (i + 1) % n
        f.append([i, j, n + j, n + i])
    return v, f


def frustum(x0, x1, y0, y1, z0, z1, draft):
    """Box with `draft` mm of inward taper on all four sides at the TOP.

    A moulded plastic body is not a perfect brick; a small draft reads correctly
    in a render and, more usefully, keeps the widest section at the bottom where
    a neighbouring part would actually foul it.
    """
    if draft <= 0.0:
        return box(x0, x1, y0, y1, z0, z1)
    if 2 * draft >= min(x1 - x0, y1 - y0):
        raise ValueError("draft %g too large for %gx%g" % (draft, x1 - x0, y1 - y0))
    a, b = x0 + draft, x1 - draft
    c, d = y0 + draft, y1 - draft
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
         (a, c, z1), (b, c, z1), (b, d, z1), (a, d, z1)]
    f = [[0, 3, 2, 1], [4, 5, 6, 7],
         [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]
    return v, f


def signed_area(poly):
    s = 0.0
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        s += x0 * y1 - x1 * y0
    return s / 2.0


def translate(solid, dx, dy, dz):
    v, f = solid
    return [(x + dx, y + dy, z + dz) for x, y, z in v], f


def bbox(solids):
    """(xmin, xmax, ymin, ymax, zmin, zmax) over a list of solids."""
    xs = [p[0] for v, _f in solids for p in v]
    ys = [p[1] for v, _f in solids for p in v]
    zs = [p[2] for v, _f in solids for p in v]
    return min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)


# ----------------------------------------------------------------------------
# validation - a malformed solid must fail here, not silently render wrong
# ----------------------------------------------------------------------------

def _normal(v, loop):
    """Newell's method: robust for any planar polygon, any winding."""
    nx = ny = nz = 0.0
    n = len(loop)
    for i in range(n):
        x0, y0, z0 = v[loop[i]]
        x1, y1, z1 = v[loop[(i + 1) % n]]
        nx += (y0 - y1) * (z0 + z1)
        ny += (z0 - z1) * (x0 + x1)
        nz += (x0 - x1) * (y0 + y1)
    m = math.sqrt(nx * nx + ny * ny + nz * nz)
    if m < 1e-12:
        raise ValueError("degenerate face %s" % (loop,))
    return nx / m, ny / m, nz / m


def check_solid(name, solid, tol=1e-6):
    v, faces = solid
    errors = []
    for k, loop in enumerate(faces):
        if len(loop) < 3:
            errors.append("face %d has %d vertices" % (k, len(loop)))
            continue
        if len(set(loop)) != len(loop):
            errors.append("face %d repeats a vertex: %s" % (k, loop))
        nx, ny, nz = _normal(v, loop)
        x0, y0, z0 = v[loop[0]]
        d = nx * x0 + ny * y0 + nz * z0
        for idx in loop[1:]:
            x, y, z = v[idx]
            off = abs(nx * x + ny * y + nz * z - d)
            if off > tol:
                errors.append("face %d is not planar (vertex %d off by %.6g mm)"
                              % (k, idx, off))
    # every undirected edge used exactly twice, and in opposite directions
    use = {}
    for k, loop in enumerate(faces):
        n = len(loop)
        for i in range(n):
            a, b = loop[i], loop[(i + 1) % n]
            use.setdefault((min(a, b), max(a, b)), []).append((a, b, k))
    for key, lst in sorted(use.items()):
        if len(lst) != 2:
            errors.append("edge %s used by %d faces, want 2" % (key, len(lst)))
        elif lst[0][0] == lst[1][0]:
            errors.append("edge %s traversed the same way by faces %d and %d "
                          "(inconsistent winding)" % (key, lst[0][2], lst[1][2]))
    if errors:
        raise ValueError("%s: malformed solid:\n  %s" % (name, "\n  ".join(errors)))


# ----------------------------------------------------------------------------
# STEP emission
# ----------------------------------------------------------------------------

class _Step:
    def __init__(self):
        self.lines = []
        self.n = 0

    def add(self, text):
        self.n += 1
        self.lines.append("#%d=%s;" % (self.n, text))
        return self.n


def _fmt(x):
    """STEP reals: always a decimal point, no exponent surprises."""
    if x == 0.0:
        return "0."
    s = "%.9g" % x
    if "e" in s or "E" in s:
        s = "%.9f" % x
    if "." not in s:
        s += "."
    return s


def write_step(path, parts, product_name, description):
    """Write `parts` = [(solid, (r,g,b), label), ...] to an AP214 STEP file.

    Colours are 0..1 floats.  Coordinates are millimetres.
    """
    for solid, _rgb, label in parts:
        check_solid("%s/%s" % (product_name, label), solid)

    s = _Step()
    # --- product / context boilerplate ------------------------------------
    app_ctx = s.add("APPLICATION_CONTEXT('automotive design')")
    s.add("APPLICATION_PROTOCOL_DEFINITION('international standard',"
          "'automotive_design',2000,#%d)" % app_ctx)
    pdc = s.add("PRODUCT_DEFINITION_CONTEXT('part definition',#%d,'design')" % app_ctx)
    pc = s.add("PRODUCT_CONTEXT('',#%d,'mechanical')" % app_ctx)
    prod = s.add("PRODUCT('%s','%s','%s',(#%d))"
                 % (product_name, product_name, description.replace("'", "''"), pc))
    pdf = s.add("PRODUCT_DEFINITION_FORMATION('','',#%d)" % prod)
    pd = s.add("PRODUCT_DEFINITION('design','',#%d,#%d)" % (pdf, pdc))
    pds = s.add("PRODUCT_DEFINITION_SHAPE('','',#%d)" % pd)

    # --- units -------------------------------------------------------------
    lu = s.add("(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT(.MILLI.,.METRE.))")
    au = s.add("(NAMED_UNIT(*)PLANE_ANGLE_UNIT()SI_UNIT($,.RADIAN.))")
    su = s.add("(NAMED_UNIT(*)SOLID_ANGLE_UNIT()SI_UNIT($,.STERADIAN.))")
    unc = s.add("UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-7),#%d,"
                "'distance_accuracy_value','confusion accuracy')" % lu)
    ctx = s.add("(GEOMETRIC_REPRESENTATION_CONTEXT(3)"
                "GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT((#%d))"
                "GLOBAL_UNIT_ASSIGNED_CONTEXT((#%d,#%d,#%d))"
                "REPRESENTATION_CONTEXT('Context','3D'))" % (unc, lu, au, su))

    origin = s.add("CARTESIAN_POINT('',(0.,0.,0.))")
    zdir = s.add("DIRECTION('',(0.,0.,1.))")
    xdir = s.add("DIRECTION('',(1.,0.,0.))")
    place = s.add("AXIS2_PLACEMENT_3D('',#%d,#%d,#%d)" % (origin, zdir, xdir))

    # --- one MANIFOLD_SOLID_BREP per part ---------------------------------
    breps = []
    for solid, _rgb, label in parts:
        breps.append(_emit_solid(s, solid, label))

    shape = s.add("ADVANCED_BREP_SHAPE_REPRESENTATION('%s',(#%d,%s),#%d)"
                  % (product_name, place,
                     ",".join("#%d" % b for b in breps), ctx))
    s.add("SHAPE_DEFINITION_REPRESENTATION(#%d,#%d)" % (pds, shape))

    # --- colours -----------------------------------------------------------
    styled = []
    for (solid, rgb, label), brep in zip(parts, breps):
        r, g, b = rgb
        col = s.add("COLOUR_RGB('',%s,%s,%s)" % (_fmt(r), _fmt(g), _fmt(b)))
        fasc = s.add("FILL_AREA_STYLE_COLOUR('',#%d)" % col)
        fas = s.add("FILL_AREA_STYLE('',(#%d))" % fasc)
        ssfa = s.add("SURFACE_STYLE_FILL_AREA(#%d)" % fas)
        sss = s.add("SURFACE_SIDE_STYLE('',(#%d))" % ssfa)
        ssu = s.add("SURFACE_STYLE_USAGE(.BOTH.,#%d)" % sss)
        psa = s.add("PRESENTATION_STYLE_ASSIGNMENT((#%d))" % ssu)
        styled.append(s.add("STYLED_ITEM('%s',(#%d),#%d)" % (label, psa, brep)))
    s.add("MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION('',(%s),#%d)"
          % (",".join("#%d" % i for i in styled), ctx))

    stamp = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    head = [
        "ISO-10303-21;",
        "HEADER;",
        "FILE_DESCRIPTION(('%s'),'2;1');" % description.replace("'", "''"),
        "FILE_NAME('%s','%s',(''),(''),"
        "'FPGAcommon/hw/step_writer.py','',''); " % (os.path.basename(path), stamp),
        "FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'));",
        "ENDSEC;",
        "DATA;",
    ]
    tail = ["ENDSEC;", "END-ISO-10303-21;", ""]
    text = "\n".join(head + s.lines + tail)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # The stamp above is the ONLY part of the file that is not a function of the
    # geometry, so a file that differs from what we just built in nothing but the
    # stamp is already correct.  Rewriting it would change its bytes and its
    # mtime for no reason, and every generator here is run often - the .step
    # files then show up in every diff and every review with nothing in them
    # changed.  Leave that file exactly as it is, and keep the stamp meaning
    # "when this geometry was last built" instead of "when this ran last".
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            if _destamp(fh.read()) == _destamp(text):
                return path
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        raise IOError("failed to write %s" % path)
    return path


_STAMP = re.compile(r"^FILE_NAME\('[^']*','[^']*'", re.M)


def _destamp(text):
    """The file with its FILE_NAME timestamp blanked, for comparing two builds."""
    return _STAMP.sub("FILE_NAME('',''", text, count=1)


def _emit_solid(s, solid, label):
    v, faces = solid
    pts = [s.add("CARTESIAN_POINT('',(%s,%s,%s))" % (_fmt(x), _fmt(y), _fmt(z)))
           for x, y, z in v]
    vps = [s.add("VERTEX_POINT('',#%d)" % p) for p in pts]

    edges = {}          # (a,b) sorted -> (entity id, a, b) with a->b as stored
    for loop in faces:
        n = len(loop)
        for i in range(n):
            a, b = loop[i], loop[(i + 1) % n]
            key = (min(a, b), max(a, b))
            if key in edges:
                continue
            ax, ay, az = v[key[0]]
            bx, by, bz = v[key[1]]
            dx, dy, dz = bx - ax, by - ay, bz - az
            ln = math.sqrt(dx * dx + dy * dy + dz * dz)
            d = s.add("DIRECTION('',(%s,%s,%s))"
                      % (_fmt(dx / ln), _fmt(dy / ln), _fmt(dz / ln)))
            vec = s.add("VECTOR('',#%d,%s)" % (d, _fmt(ln)))
            line = s.add("LINE('',#%d,#%d)" % (pts[key[0]], vec))
            ec = s.add("EDGE_CURVE('',#%d,#%d,#%d,.T.)"
                       % (vps[key[0]], vps[key[1]], line))
            edges[key] = ec

    face_ids = []
    for loop in faces:
        n = len(loop)
        oriented = []
        for i in range(n):
            a, b = loop[i], loop[(i + 1) % n]
            key = (min(a, b), max(a, b))
            same = ".T." if a == key[0] else ".F."
            oriented.append(s.add("ORIENTED_EDGE('',*,*,#%d,%s)" % (edges[key], same)))
        el = s.add("EDGE_LOOP('',(%s))" % ",".join("#%d" % o for o in oriented))
        fb = s.add("FACE_OUTER_BOUND('',#%d,.T.)" % el)
        nx, ny, nz = _normal(v, loop)
        # a reference direction in the plane: the first edge of the loop
        x0, y0, z0 = v[loop[0]]
        x1, y1, z1 = v[loop[1]]
        rx, ry, rz = x1 - x0, y1 - y0, z1 - z0
        rl = math.sqrt(rx * rx + ry * ry + rz * rz)
        p = s.add("CARTESIAN_POINT('',(%s,%s,%s))" % (_fmt(x0), _fmt(y0), _fmt(z0)))
        dn = s.add("DIRECTION('',(%s,%s,%s))" % (_fmt(nx), _fmt(ny), _fmt(nz)))
        dr = s.add("DIRECTION('',(%s,%s,%s))"
                   % (_fmt(rx / rl), _fmt(ry / rl), _fmt(rz / rl)))
        ax = s.add("AXIS2_PLACEMENT_3D('',#%d,#%d,#%d)" % (p, dn, dr))
        pl = s.add("PLANE('',#%d)" % ax)
        face_ids.append(s.add("ADVANCED_FACE('',(#%d),#%d,.T.)" % (fb, pl)))

    shell = s.add("CLOSED_SHELL('',(%s))" % ",".join("#%d" % f for f in face_ids))
    return s.add("MANIFOLD_SOLID_BREP('%s',#%d)" % (label, shell))
