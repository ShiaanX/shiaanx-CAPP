"""
dfm_geometry.py — face-level DFM facts straight from the job's STEP (PythonOCC).

Face index = 0-based TopExp_Explorer(shape, TopAbs_FACE) order over the whole
shape from STEPControl_Reader. This is the SAME order occt-import-js 0.0.23
reports in `meshes[*].brep_faces` (it walks TopExp_Explorer(solid, FACE) per
solid and emits every face, even untriangulated ones), so the browser can
colour faces by these indices. Parity was checked index-by-index on Motor
Mount (1096 faces) and RKSE-004-057 (71 faces): per-face area-weighted
triangle centroids match the B-rep centroids (worst 0.45 mm).

Two layers:
  extract(step)            -> heavy OCC pass, JSON-able "facts" (cached per job)
  categories(facts, ...)   -> DFM categories with face_indices (cheap, pure python)
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

CACHE_NAME = 'dfm_geometry.json'
CACHE_VERSION = 3

# ── Thresholds (aluminium 6061, 3-axis VMC) ─────────────────────────────────
ANG_TOL_DEG = 0.5            # normals/axes within this are "parallel"/"perpendicular"
SMOOTH_EDGE_DEG = 3.0        # dihedral below this = tangent (fillet blend), not a corner
# Concave wall/wall edges are flagged only when the corner's interior angle is <= 150°
# (dihedral >= 30°): shallower kinks leave < 0.05 mm per mm of cutter radius.
SHARP_EDGE_DEG = 30.0
# Internal corners: the cutter radius must be <= corner radius, and an end mill
# should not reach deeper than MAX_CUTTER_LD x its diameter in aluminium without
# chatter / deflection (standard-length 2-flute carbide). So for a corner of depth h
# the smallest sensible cutter is h / MAX_CUTTER_LD and the corner needs
# r >= h / (2 * MAX_CUTTER_LD). Never below the smallest stock end mill radius.
MAX_CUTTER_LD = 4.0
MIN_PRACTICAL_CUTTER_R_MM = 0.5     # Ø1 mm end mill = practical floor for a job shop
MICRO_CORNER_R_MM = 0.5             # below this a corner needs a micro tool / EDM -> block
# Standard end-mill corner / ball radii a shop carries (mm). Floor fillets that are
# not on this list need a custom bull-nose or slow 3D ball-nose surfacing.
STANDARD_RADII_MM = [0.2, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0]
RADIUS_MATCH_TOL_MM = 0.02
# Holes
HOLE_DDR_WARN = 5.0          # depth/dia > 5: peck drilling
HOLE_DDR_BLOCK = 10.0        # > 10: long-series / gun drill, high breakage risk
DRILL_MAX_DIA_MM = 20.0      # above this a hole is interpolated / bored, not drilled
FLAT_BOTTOM_MAX_DIA_MM = 20.0
DRILL_STEP_SMALL_MM = 0.1    # DIN 338 jobber drills: 0.1 mm steps up to 13 mm,
DRILL_STEP_LARGE_MM = 0.5    # 0.5 mm steps 13-20 mm
DRILL_MATCH_TOL_MM = 0.02
# ISO 68-1 coarse threads: nominal -> tap drill (mm)
TAP_DRILLS = {'M1.6': 1.25, 'M2': 1.6, 'M2.5': 2.05, 'M3': 2.5, 'M4': 3.3, 'M5': 4.2,
              'M6': 5.0, 'M8': 6.8, 'M10': 8.5, 'M12': 10.2}
TAP_MATCH_TOL_MM = 0.05
# Thin walls in aluminium: < 1.0 mm vibrates / deflects under the cutter (warn);
# < 0.5 mm usually tears or bends (block).
THIN_WALL_WARN_MM = 1.0
THIN_WALL_BLOCK_MM = 0.5
THIN_WALL_MIN_OVERLAP_MM2 = 0.5   # ignore slivers whose facing overlap is smaller than this
# Chamfers: narrow planar / conical bands between two convex edges
CHAMFER_MAX_WIDTH_MM = 3.0
# External fillets: convex rounds up to this radius are edge fillets (bigger = profile)
EXT_FILLET_MAX_R_MM = 6.0
# Concave arcs bigger than this are contour arcs any cutter can follow, not "corners"
CORNER_MAX_R_MM = 10.0
# Engraved text / logo: a connected patch of at least this many freeform faces
TEXT_MIN_FREEFORM_FACES = 20
TEXT_BOX_TOL_MM = 0.05
TEXT_MAX_FACE_FRAC = 0.25   # a face covering > 25% of the text footprint is the floor, not a letter

# Colour-blind-safe palette (Okabe-Ito + Paul Tol), fixed per category.
CATEGORY_META = {
    'small_internal_corner': ('Small radius internal corner(s)', '#D55E00',
        'A rotating cutter cannot make an internal corner sharper than its own radius, and a '
        'small cutter has to run slowly at short reach — so tight deep corners cost cycle time '
        'or need EDM.'),
    'non_standard_radius': ('Non-standard radius fillet(s)', '#E69F00',
        'Radii that do not match a stock end-mill corner or ball radius need a special tool or '
        'slow 3D surfacing passes instead of one standard cutter.'),
    'flat_bottom_hole': ('Flat bottom hole(s)', '#0072B2',
        'A drill leaves a 118-140° cone, so a flat-bottomed hole needs an extra end-mill or '
        'flat-bottom-drill operation.'),
    'deep_hole': ('Deep hole(s)', '#332288',
        'Holes deeper than 5x their diameter need peck cycles, and beyond 10x a long-series or '
        'gun drill — slower and with a higher breakage risk.'),
    'non_standard_hole': ('Non-standard hole size(s)', '#56B4E9',
        'A diameter that is not a stock drill size needs a special drill or a second '
        'interpolation / reaming operation.'),
    'non_perpendicular_face': ('Non-perpendicular milled face(s)', '#009E73',
        'Faces tilted to every machine axis cannot be cut with a flat end mill in a normal '
        'vise setup — they need a ball-nose 3D pass, an angled fixture or a 4th axis.'),
    'thin_wall': ('Thin wall(s)', '#F0E442',
        'Thin aluminium walls vibrate and deflect under the cutter, forcing light cuts and '
        'risking scrap.'),
    'external_edge_fillet': ('External edge fillet(s)', '#CC79A7',
        'Rounded outside edges need a corner-rounding cutter or a ball-nose pass; a chamfer or '
        'sharp edge is cheaper if the round is not functional.'),
    'chamfer': ('Chamfer(s)', '#882255',
        'Each chamfer is a separate chamfer-mill pass; consistent 45° chamfers let one tool do '
        'them all.'),
    'engraving': ('Engraved / embossed text or logo', '#44AA99',
        'Text and logos need a tiny engraving cutter and a long, slow toolpath; laser marking '
        'is usually cheaper if the marking is not structural.'),
    'small_tool_region': ('Regions forcing a small cutter', '#999999',
        'Areas only a small end mill can reach run at a fraction of the normal removal rate, '
        'driving cycle time.'),
    'unreachable_volume': ('Material not reachable on 3-axis', '#661100',
        'Material no 3-axis setup direction can reach needs a 4th/5th axis, special tooling or '
        'a design change.'),
}
CATEGORY_ORDER = list(CATEGORY_META)
SEV_RANK = {'block': 0, 'warn': 1, 'info': 2}


def thresholds() -> dict:
    return {'max_cutter_l_over_d': MAX_CUTTER_LD, 'min_practical_cutter_r_mm': MIN_PRACTICAL_CUTTER_R_MM,
            'micro_corner_r_mm': MICRO_CORNER_R_MM, 'sharp_edge_dihedral_deg': SHARP_EDGE_DEG,
            'standard_radii_mm': STANDARD_RADII_MM, 'radius_match_tol_mm': RADIUS_MATCH_TOL_MM,
            'hole_ddr_warn': HOLE_DDR_WARN, 'hole_ddr_block': HOLE_DDR_BLOCK,
            'drill_max_dia_mm': DRILL_MAX_DIA_MM, 'thin_wall_warn_mm': THIN_WALL_WARN_MM,
            'thin_wall_block_mm': THIN_WALL_BLOCK_MM, 'chamfer_max_width_mm': CHAMFER_MAX_WIDTH_MM,
            'ext_fillet_max_r_mm': EXT_FILLET_MAX_R_MM, 'angle_tol_deg': ANG_TOL_DEG}


# ═════════════════════════════ small vector helpers ═════════════════════════
def _dot(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def _sub(a, b): return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
def _add(a, b): return [a[0] + b[0], a[1] + b[1], a[2] + b[2]]
def _mul(a, s): return [a[0] * s, a[1] * s, a[2] * s]
def _cross(a, b): return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
def _norm(a): return math.sqrt(_dot(a, a))


def _unit(a):
    n = _norm(a)
    return [a[0] / n, a[1] / n, a[2] / n] if n > 1e-12 else [0.0, 0.0, 0.0]


def _r(v, n=3):
    return [round(x, n) for x in v] if isinstance(v, (list, tuple)) else round(v, n)


COS_PAR = math.cos(math.radians(ANG_TOL_DEG))
SIN_PERP = math.sin(math.radians(ANG_TOL_DEG))


def _parallel(a, b): return abs(_dot(a, b)) >= COS_PAR
def _perp(a, b): return abs(_dot(a, b)) <= SIN_PERP


# ═════════════════════════════════ extraction ═══════════════════════════════
def step_sha(step_path: Path) -> str:
    return hashlib.sha256(Path(step_path).read_bytes()).hexdigest()


def load_or_extract(job_dir: Path, step_path: Path) -> dict:
    cache = Path(job_dir) / CACHE_NAME
    sha = step_sha(step_path)
    if cache.exists():
        try:
            d = json.loads(cache.read_text(encoding='utf-8'))
            if d.get('version') == CACHE_VERSION and d.get('step_sha256') == sha:
                return d
        except Exception:
            pass
    facts = extract(step_path)
    facts['step_sha256'] = sha
    cache.write_text(json.dumps(facts), encoding='utf-8')
    return facts


def extract(step_path: Path) -> dict:
    from OCC.Core.STEPControl import STEPControl_Reader
    from OCC.Core.IFSelect import IFSelect_RetDone
    from OCC.Core.TopExp import TopExp_Explorer
    from OCC.Core.TopAbs import (TopAbs_FACE, TopAbs_EDGE, TopAbs_WIRE, TopAbs_REVERSED,
                                 TopAbs_IN)
    from OCC.Core.TopoDS import topods
    from OCC.Core.TopTools import TopTools_IndexedMapOfShape
    from OCC.Core.BRepAdaptor import BRepAdaptor_Surface, BRepAdaptor_Curve, BRepAdaptor_Curve2d
    from OCC.Core.BRep import BRep_Tool
    from OCC.Core.GeomAbs import (GeomAbs_Plane, GeomAbs_Cylinder, GeomAbs_Cone, GeomAbs_Sphere,
                                  GeomAbs_Torus, GeomAbs_Line, GeomAbs_Circle)
    from OCC.Core.GProp import GProp_GProps
    from OCC.Core.BRepGProp import brepgprop
    from OCC.Core.BRepTools import breptools
    from OCC.Core.BRepLProp import BRepLProp_SLProps
    from OCC.Core.Bnd import Bnd_Box
    from OCC.Core.BRepBndLib import brepbndlib
    from OCC.Core.gp import gp_Pnt, gp_Vec, gp_Dir

    reader = STEPControl_Reader()
    if reader.ReadFile(str(step_path)) != IFSelect_RetDone:
        raise RuntimeError(f'Could not read STEP: {step_path}')
    reader.TransferRoots()
    shape = reader.OneShape()

    occ_faces = []
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        occ_faces.append(topods.Face(exp.Current()))
        exp.Next()

    def p3(p): return [p.X(), p.Y(), p.Z()]

    def outward_normal(face, adaptor, u, v):
        pr = BRepLProp_SLProps(adaptor, u, v, 1, 1e-7)
        if not pr.IsNormalDefined():
            return None, None
        n = p3(pr.Normal())
        if face.Orientation() == TopAbs_REVERSED:
            n = _mul(n, -1)
        return p3(pr.Value()), n

    adaptors = [BRepAdaptor_Surface(f, True) for f in occ_faces]
    faces = []
    for i, face in enumerate(occ_faces):
        ad = adaptors[i]
        st = ad.GetType()
        gp_ = GProp_GProps()
        brepgprop.SurfaceProperties(face, gp_)
        bb = Bnd_Box()
        brepbndlib.Add(face, bb)
        nw = 0
        we = TopExp_Explorer(face, TopAbs_WIRE)
        while we.More():
            nw += 1
            we.Next()
        u0, u1, v0, v1 = breptools.UVBounds(face)
        um, vm = (u0 + u1) / 2, (v0 + v1) / 2
        P, n = outward_normal(face, ad, um, vm)
        rec = {'i': i, 'a': round(gp_.Mass(), 4), 'c': _r(p3(gp_.CentreOfMass()), 4),
               'bb': _r(list(bb.Get()), 4), 'nw': nw}
        if st == GeomAbs_Plane:
            rec['t'] = 'plane'
            rec['n'] = _r(n, 6) if n else None
        elif st in (GeomAbs_Cylinder, GeomAbs_Cone):
            g = ad.Cylinder() if st == GeomAbs_Cylinder else ad.Cone()
            ax = p3(g.Axis().Direction())
            loc = p3(g.Location())
            rec['t'] = 'cylinder' if st == GeomAbs_Cylinder else 'cone'
            rec['ax'] = _r(ax, 6)
            rec['loc'] = _r(loc, 5)
            if st == GeomAbs_Cylinder:
                rec['r'] = round(g.Radius(), 5)
                rec['span'] = round(math.degrees(u1 - u0), 3)
                lo = _dot(loc, ax)
                rec['ext'] = [round(lo + v0, 5), round(lo + v1, 5)]
            else:
                rec['half_angle'] = round(math.degrees(g.SemiAngle()), 3)
                rec['r'] = round(g.RefRadius(), 5)
            if P and n:
                d = _sub(P, loc)
                radial = _sub(d, _mul(ax, _dot(d, ax)))
                rec['cc'] = _dot(n, radial) < 0          # normal points at the axis -> concave
        elif st == GeomAbs_Torus:
            g = ad.Torus()
            ax, loc = p3(g.Axis().Direction()), p3(g.Location())
            rec.update(t='torus', ax=_r(ax, 6), loc=_r(loc, 5), R=round(g.MajorRadius(), 5),
                       r=round(g.MinorRadius(), 5))
            if P and n:
                d = _sub(P, loc)
                radial = _unit(_sub(d, _mul(ax, _dot(d, ax))))
                q = _add(loc, _mul(radial, g.MajorRadius()))
                rec['cc'] = _dot(n, _sub(P, q)) < 0
        elif st == GeomAbs_Sphere:
            g = ad.Sphere()
            loc = p3(g.Location())
            rec.update(t='sphere', loc=_r(loc, 5), r=round(g.Radius(), 5))
            if P and n:
                rec['cc'] = _dot(n, _sub(P, loc)) < 0
        else:
            rec['t'] = 'freeform'
            # sample principal curvatures on a 3x3 UV grid
            rs, ruled, conc, rulings = [], True, [], []
            for fu in (0.2, 0.5, 0.8):
                for fv in (0.2, 0.5, 0.8):
                    pr = BRepLProp_SLProps(ad, u0 + fu * (u1 - u0), v0 + fv * (v1 - v0), 2, 1e-7)
                    if not (pr.IsCurvatureDefined() and pr.IsNormalDefined()):
                        continue
                    k1, k2 = pr.MinCurvature(), pr.MaxCurvature()
                    kbig, ksmall = (k1, k2) if abs(k1) >= abs(k2) else (k2, k1)
                    if abs(ksmall) > 2e-3:
                        ruled = False
                    if abs(kbig) > 1e-6:
                        rs.append(1.0 / abs(kbig))
                        # OCC: centre of curvature = P + N/k (N = parametric normal)
                        fwd = face.Orientation() != TopAbs_REVERSED
                        conc.append((kbig > 0) == fwd)
                    try:
                        dmin_, dmax_ = gp_Dir(), gp_Dir()
                        pr.CurvatureDirections(dmax_, dmin_)     # (MaxD, MinD)
                        # ruling = direction of the near-zero curvature
                        rulings.append(p3(dmin_) if abs(k1) <= abs(k2) else p3(dmax_))
                    except Exception:
                        pass
            rec['ruled'] = ruled and bool(rs)
            if rs:
                rec['r_min'] = round(min(rs), 4)
                rec['r_max'] = round(max(rs), 4)
                rec['cc'] = sum(conc) > len(conc) / 2
                if rec['ruled'] and max(rs) - min(rs) <= max(0.02, 0.03 * min(rs)) and rulings:
                    # constant-radius ruled B-spline = a cylinder exported as a spline
                    ax = _unit(rulings[len(rulings) // 2])
                    rec['cyl_like'] = {'r': round(sum(rs) / len(rs), 4), 'ax': _r(ax, 5)}
            if n:
                rec['n'] = _r(n, 6)
        faces.append(rec)

    # ── edges: adjacency + convexity ────────────────────────────────────────
    emap = TopTools_IndexedMapOfShape()
    inst: dict[int, list] = {}
    for i, face in enumerate(occ_faces):
        ee = TopExp_Explorer(face, TopAbs_EDGE)
        while ee.More():
            e = topods.Edge(ee.Current())
            k = emap.Add(e)
            inst.setdefault(k, []).append((i, e))
            ee.Next()

    edges = []
    for k, lst in inst.items():
        fis = sorted({i for i, _ in lst})
        e0 = lst[0][1]
        if BRep_Tool.Degenerated(e0):
            continue
        ca = BRepAdaptor_Curve(e0)
        ctype = ca.GetType()
        kind = 'line' if ctype == GeomAbs_Line else 'circle' if ctype == GeomAbs_Circle else 'other'
        f_, l_ = ca.FirstParameter(), ca.LastParameter()
        m = (f_ + l_) / 2
        P = gp_Pnt()
        V = gp_Vec()
        ca.D1(m, P, V)
        t0 = _unit(p3(V))
        gp2 = GProp_GProps()
        from OCC.Core.BRepGProp import brepgprop as _bg
        _bg.LinearProperties(e0, gp2)
        rec = {'f': fis, 'kind': kind, 'len': round(gp2.Mass(), 4), 'mid': _r(p3(P), 4)}
        if kind == 'line':
            rec['dir'] = _r(t0, 6)
        elif kind == 'circle':
            circ = ca.Circle()
            rec['r'] = round(circ.Radius(), 5)
            rec['ax'] = _r(p3(circ.Axis().Direction()), 6)
            rec['ctr'] = _r(p3(circ.Location()), 5)
        if len(fis) == 2:
            # one oriented instance per face
            by_face = {}
            for i, e in lst:
                by_face.setdefault(i, e)
            (ia, ea), (ib, eb) = [(i, by_face[i]) for i in fis]
            try:
                normals, tans = [], []
                for i, e in ((ia, ea), (ib, eb)):
                    face = occ_faces[i]
                    c2 = BRepAdaptor_Curve2d(e, face)
                    uv = c2.Value(m)
                    _, nn = outward_normal(face, adaptors[i], uv.X(), uv.Y())
                    tt = t0 if e.Orientation() != TopAbs_REVERSED else _mul(t0, -1)
                    normals.append(nn)
                    tans.append(tt)
                n1, n2 = normals
                if n1 and n2:
                    ang = math.degrees(math.acos(max(-1.0, min(1.0, _dot(n1, n2)))))
                    into1 = _cross(n1, tans[0])           # direction into face A, along A
                    s = _dot(n2, into1)
                    if ang < SMOOTH_EDGE_DEG:
                        conv = 'smooth'
                    else:
                        conv = 'concave' if s > 0 else 'convex'
                    rec.update(conv=conv, ang=round(ang, 3), n=[_r(n1, 5), _r(n2, 5)])
            except Exception:
                pass
        edges.append(rec)

    # solid point-membership for thin-wall checks is done here (needs OCC)
    thin = _thin_wall_pairs(shape, occ_faces, faces, adaptors)

    return {'version': CACHE_VERSION, 'face_count': len(faces), 'faces': faces, 'edges': edges,
            'thin_wall_pairs': thin, 'step_file': Path(step_path).name}


def _thin_wall_pairs(shape, occ_faces, faces, adaptors) -> list:
    """Opposed parallel planar faces (outward normals anti-parallel, material between)
    closer than THIN_WALL_WARN_MM whose projections overlap."""
    from OCC.Core.BRepAdaptor import BRepAdaptor_Surface
    from OCC.Core.BRepClass import BRepClass_FaceClassifier
    from OCC.Core.BRepClass3d import BRepClass3d_SolidClassifier
    from OCC.Core.BRepTools import breptools
    from OCC.Core.ElSLib import elslib
    from OCC.Core.TopAbs import TopAbs_IN, TopAbs_ON
    from OCC.Core.gp import gp_Pnt, gp_Pnt2d

    planes = [f for f in faces if f['t'] == 'plane' and f.get('n') and f['a'] > 0.05]
    out = []
    solid_cls = BRepClass3d_SolidClassifier(shape)

    def samples(i, grid=9):
        face = occ_faces[i]
        ad = adaptors[i]
        u0, u1, v0, v1 = breptools.UVBounds(face)
        pts = []
        for a in range(grid):
            for b in range(grid):
                u = u0 + (a + 0.5) / grid * (u1 - u0)
                v = v0 + (b + 0.5) / grid * (v1 - v0)
                st = BRepClass_FaceClassifier(face, gp_Pnt2d(u, v), 1e-6).State()
                if st == TopAbs_IN:
                    p = ad.Value(u, v)
                    pts.append([p.X(), p.Y(), p.Z()])
        return pts

    cache = {}
    for ai in range(len(planes)):
        A = planes[ai]
        for bi in range(ai + 1, len(planes)):
            B = planes[bi]
            if _dot(A['n'], B['n']) > -COS_PAR:
                continue
            gap = -_dot(_sub(B['c'], A['c']), A['n'])   # B behind A along A's outward normal
            if not (1e-3 < gap < THIN_WALL_WARN_MM):
                continue
            # quick bbox overlap in the plane
            if any(A['bb'][k] > B['bb'][k + 3] + 1e-6 or B['bb'][k] > A['bb'][k + 3] + 1e-6
                   for k in range(3) if abs(A['n'][k]) < 0.5):
                continue
            small, big = (A, B) if A['a'] <= B['a'] else (B, A)
            if small['i'] not in cache:
                cache[small['i']] = samples(small['i'])
            pts = cache[small['i']]
            if not pts:
                continue
            bface = occ_faces[big['i']]
            bpl = adaptors[big['i']].Plane()
            hits = []
            for p in pts:
                q = _sub(p, _mul(small['n'], gap))        # step through the material
                u, v = elslib.Parameters(bpl, gp_Pnt(*q))
                st = BRepClass_FaceClassifier(bface, gp_Pnt2d(u, v), 1e-6).State()
                if st in (TopAbs_IN, TopAbs_ON):
                    hits.append(p)
            if len(hits) < max(2, int(0.25 * len(pts))):
                continue
            # material between the faces? (one solid classification at the overlap middle —
            # the solid classifier is ~60 ms/call on a 1000-face part)
            hc = [sum(p[k] for p in hits) / len(hits) for k in range(3)]
            p = min(hits, key=lambda h: _norm(_sub(h, hc)))
            solid_cls.Perform(gp_Pnt(*_sub(p, _mul(small['n'], gap / 2))), 1e-6)
            if solid_cls.State() == TopAbs_IN:
                out.append({'faces': [A['i'], B['i']], 'thickness': round(gap, 4),
                            'overlap_frac': round(len(hits) / len(pts), 3),
                            'overlap_area_mm2': round(small['a'] * len(hits) / len(pts), 3)})
    return out


# ══════════════════════════════ classification ══════════════════════════════
_AXES = {'+X': [1, 0, 0], '-X': [-1, 0, 0], '+Y': [0, 1, 0], '-Y': [0, -1, 0],
         '+Z': [0, 0, 1], '-Z': [0, 0, -1]}


def tool_dirs_from_v3(v3: dict | None) -> list[str]:
    """Setup approach directions ('+Z' = tool comes from +Z, cuts faces whose outward
    normal is +Z). From v3's setup plan; all six principal directions if unknown."""
    dirs: list[str] = []

    def push(d):
        d = str(d or '').strip().upper()
        if d in _AXES and d not in dirs:
            dirs.append(d)
    if v3:
        # 1) setups v3 actually planned and costed
        for s in (v3.get('plan') or {}).get('setups') or []:
            push(s.get('dir') if isinstance(s, dict) else s)
        # 2) v3's setup plan (greedy order)
        if not dirs:
            sp = v3.get('setup_plan')
            if isinstance(sp, str):
                for d in sp.split(','):
                    push(d)
            elif isinstance(sp, list):
                for d in sp:
                    push((d.get('direction') or d.get('dir')) if isinstance(d, dict) else d)
        if not dirs:
            for d in v3.get('directions') or []:
                if d.get('recommended'):
                    push(d.get('dir'))
        # 3) holes are drilled along their own axis -> that direction is a setup too
        if dirs:
            for h in v3.get('holes') or []:
                push(h.get('dir'))
    return dirs or list(_AXES)


def _axis_name(v):
    k = max(range(3), key=lambda j: abs(v[j]))
    return 'XYZ'[k]


def _std_nearest(x, lst):
    return min(lst, key=lambda s: abs(s - x))


def _drill_nearest(d):
    step = DRILL_STEP_SMALL_MM if d <= 13.0 + 1e-9 else DRILL_STEP_LARGE_MM
    return round(round(d / step) * step, 2)


def _centroid(faces, idxs):
    tot = sum(faces[i]['a'] for i in idxs)
    if not idxs or tot <= 0:
        return None
    return [round(sum(faces[i]['c'][k] * faces[i]['a'] for i in idxs) / tot, 3) for k in range(3)]


def _coaxial_groups(faces, cands, adj):
    """Union adjacent cylinder faces that share axis line + radius."""
    parent = {i: i for i in cands}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    cset = set(cands)
    for i in cands:
        a = faces[i]
        for j in adj.get(i, ()):
            if j not in cset or j <= i:
                continue
            b = faces[j]
            if abs(a['r'] - b['r']) > 0.01 or not _parallel(a['ax'], b['ax']):
                continue
            d = _sub(b['loc'], a['loc'])
            off = _sub(d, _mul(a['ax'], _dot(d, a['ax'])))
            if _norm(off) > 0.01:
                continue
            parent[find(i)] = find(j)
    groups = {}
    for i in cands:
        groups.setdefault(find(i), []).append(i)
    return sorted(groups.values(), key=lambda g: min(g))


def categories(facts: dict, v3: dict | None = None) -> list[dict]:
    faces = facts['faces']
    edges = facts['edges']
    tool_dirs = tool_dirs_from_v3(v3)
    tool_vecs = {d: _AXES[d] for d in tool_dirs}
    tool_axes = []
    for d, v in tool_vecs.items():
        if not any(_parallel(v, a) for a in tool_axes):
            tool_axes.append([abs(x) for x in v])

    adj: dict[int, set] = {}
    edge_by_pair: dict[tuple, list] = {}
    for e in edges:
        if len(e['f']) == 2:
            a, b = e['f']
            adj.setdefault(a, set()).add(b)
            adj.setdefault(b, set()).add(a)
            edge_by_pair.setdefault((a, b), []).append(e)

    def pair_edges(a, b):
        return edge_by_pair.get((min(a, b), max(a, b)), [])

    def conv_between(a, b):
        cs = {e.get('conv') for e in pair_edges(a, b)}
        cs.discard(None)
        return cs

    items: dict[str, list] = {k: [] for k in CATEGORY_ORDER}

    def add(cat, sev, label, detail, measured, expected, idxs):
        idxs = sorted(set(idxs))
        items[cat].append({'id': f'{cat}-{len(items[cat]) + 1}', 'severity': sev, 'label': label,
                           'detail': detail, 'measured': measured, 'expected': expected,
                           'face_indices': idxs, 'centroid_mm': _centroid(faces, idxs)})

    # ── engraved text / logo: connected patches of freeform faces ───────────
    freeform = {f['i'] for f in faces if f['t'] == 'freeform' and not f.get('cyl_like')}
    seen, text_faces = set(), set()
    for s in sorted(freeform):
        if s in seen:
            continue
        comp, stack = set(), [s]
        while stack:
            x = stack.pop()
            if x in comp:
                continue
            comp.add(x)
            for y in adj.get(x, ()):
                if y in freeform and y not in comp:
                    stack.append(y)
                elif y not in comp and faces[y]['t'] == 'plane':
                    # small planar bits between letter strokes belong to the text
                    nb = adj.get(y, set())
                    if nb and sum(1 for z in nb if z in freeform) * 2 >= len(nb):
                        stack.append(y)
        nff = sum(1 for x in comp if x in freeform)
        if nff < TEXT_MIN_FREEFORM_FACES:
            continue
        # depth axis = normal of the largest flat face in the patch
        flats = [faces[x] for x in comp if faces[x]['t'] == 'plane' and faces[x].get('n')]
        ax = _unit(max(flats, key=lambda f: f['a'])['n']) if flats else [0, 0, 1]
        k = max(range(3), key=lambda j: abs(ax[j]))
        box = [min(faces[x]['bb'][j] for x in comp) for j in range(3)] +               [max(faces[x]['bb'][j + 3] for x in comp) for j in range(3)]
        plan_area = 1.0
        for j in range(3):
            if j != k:
                plan_area *= box[j + 3] - box[j]
        # every other face lying wholly inside the lettering's box (straight letter walls,
        # letter tops) is part of the text too — except the big floor it sits on
        tol = TEXT_BOX_TOL_MM
        for f in faces:
            if f['i'] in comp or f['i'] in seen:
                continue
            if all(f['bb'][j] >= box[j] - tol and f['bb'][j + 3] <= box[j + 3] + tol for j in range(3))                     and f['a'] < TEXT_MAX_FACE_FRAC * plan_area:
                comp.add(f['i'])
        seen |= comp
        text_faces |= comp
        depth = box[k + 3] - box[k]
        rmins = [faces[x]['r_min'] for x in comp if faces[x].get('cc') and faces[x].get('r_min')]
        rmin = min(rmins) if rmins else None
        add('engraving', 'warn', f'Text / logo ({len(comp)} faces)',
            f'{len(comp)} faces of engraved/embossed lettering, {depth:.2f} mm deep'
            + (f'; tightest inside curve R{rmin:.2f} mm' if rmin else '')
            + ' — needs an engraving cutter or laser marking.',
            {'faces': len(comp), 'depth_mm': round(depth, 3),
             'min_internal_radius_mm': round(rmin, 3) if rmin else None,
             'extent_mm': _r([box[j + 3] - box[j] for j in range(3)], 2)},
            {'tool': 'engraving cutter / V-bit, or laser mark'}, comp)

    skip = set(text_faces)

    # ── cylinder-like faces (true cylinders + constant-radius ruled splines) ──
    def cyl(i):
        f = faces[i]
        if f['t'] == 'cylinder':
            return f
        cl = f.get('cyl_like')
        if cl and f.get('cc') is not None:
            # synthesise axis location & extent from the bbox
            ax = cl['ax']
            lo = min(_dot([f['bb'][a], f['bb'][b], f['bb'][c]], ax)
                     for a in (0, 3) for b in (1, 4) for c in (2, 5))
            hi = max(_dot([f['bb'][a], f['bb'][b], f['bb'][c]], ax)
                     for a in (0, 3) for b in (1, 4) for c in (2, 5))
            return {**f, 'r': cl['r'], 'ax': ax, 'loc': f['c'], 'span': 90.0, 'ext': [lo, hi],
                    'approx': True}
        return None

    concave_cyl = [i for i in range(len(faces)) if i not in skip and (c := cyl(i)) and c.get('cc')]
    cyl_cache = {i: cyl(i) for i in concave_cyl}
    true_cyl = [i for i in concave_cyl if not cyl_cache[i].get('approx')]
    groups = _coaxial_groups({i: cyl_cache[i] for i in true_cyl} | {}, true_cyl, adj) if true_cyl else []
    groups += [[i] for i in concave_cyl if cyl_cache[i].get('approx')]

    holes, partials = [], []
    for g in groups:
        span = sum(cyl_cache[i]['span'] for i in g)
        (holes if span >= 359.0 else partials).append(g)

    # ── holes ───────────────────────────────────────────────────────────────
    v3_holes = list((v3 or {}).get('holes') or [])
    used_v3 = set()
    hole_records = []
    for g in holes:
        c0 = cyl_cache[g[0]]
        ax, r = c0['ax'], c0['r']
        dia = 2 * r
        lo = min(cyl_cache[i]['ext'][0] for i in g)
        hi = max(cyl_cache[i]['ext'][1] for i in g)
        depth = hi - lo
        gs = set(g)
        bottom, bottom_faces = None, []
        ends_open = 0
        for i in g:
            for j in adj.get(i, ()):
                if j in gs:
                    continue
                fj = faces[j]
                conv = conv_between(i, j)
                circ = [e for e in pair_edges(i, j) if e['kind'] == 'circle']
                if not circ:
                    continue
                if fj['t'] == 'plane' and fj.get('n') and _parallel(fj['n'], ax):
                    if 'concave' in conv:
                        if fj['nw'] == 1:
                            bottom, bottom_faces = 'flat', [j]
                        else:
                            bottom = bottom or 'shoulder'
                    elif 'convex' in conv:
                        ends_open += 1
                elif fj['t'] == 'cone' and 'concave' in conv and fj.get('cc'):
                    bottom = bottom or 'drill_point'
                    bottom_faces = bottom_faces or [j]
                elif 'convex' in conv:
                    ends_open += 1
        through = bottom is None
        axis = _axis_name(ax)
        # match to v3's hole list (same axis, dia within 0.05, nearest depth)
        match = None
        for k, h in enumerate(v3_holes):
            if k in used_v3:
                continue
            try:
                hd, hz = float(h.get('dia_mm')), float(h.get('depth_mm') or 0)
            except (TypeError, ValueError):
                continue
            if abs(hd - dia) <= 0.05 and str(h.get('dir', '')).upper().endswith(axis):
                if match is None or abs(hz - depth) < abs(float(v3_holes[match].get('depth_mm') or 0) - depth):
                    match = k
        vh = v3_holes[match] if match is not None else None
        if match is not None:
            used_v3.add(match)
        hole_records.append({'faces': sorted(g), 'bottom_faces': bottom_faces, 'dia': dia, 'depth': depth,
                             'axis': axis, 'bottom': bottom or 'through', 'v3': vh})

    for h in hole_records:
        dia, depth = h['dia'], h['depth']
        fidx = h['faces'] + h['bottom_faces']
        lab = f'Ø{dia:.2f} × {depth:.2f} mm ({h["axis"]})'
        v3d = (h['v3'] or {}).get('drill')
        if h['bottom'] == 'flat' and dia <= FLAT_BOTTOM_MAX_DIA_MM:
            add('flat_bottom_hole', 'warn', f'Flat bottom hole {lab}',
                f'Blind hole Ø{dia:.2f} mm with a flat floor {depth:.2f} mm deep — drill point '
                f'must be milled flat (end mill or flat-bottom drill), or allow a 118° drill point.',
                {'dia_mm': round(dia, 3), 'depth_mm': round(depth, 3), 'bottom': 'flat'},
                {'bottom': 'drill point (118°) or through'}, fidx)
        if dia <= DRILL_MAX_DIA_MM and depth / dia > HOLE_DDR_WARN:
            ddr = depth / dia
            sev = 'block' if ddr > HOLE_DDR_BLOCK else 'warn'
            add('deep_hole', sev, f'Deep hole {lab} (L/D {ddr:.1f})',
                f'Depth {depth:.2f} mm is {ddr:.1f}× the diameter — '
                + ('needs a long-series / gun drill and peck cycle.' if sev == 'block' else 'needs a peck-drilling cycle.'),
                {'dia_mm': round(dia, 3), 'depth_mm': round(depth, 3), 'depth_to_dia': round(ddr, 2)},
                {'max_depth_to_dia': HOLE_DDR_WARN}, fidx)
        if dia <= DRILL_MAX_DIA_MM and h['bottom'] != 'shoulder':
            near = _drill_nearest(dia)
            if abs(near - dia) > DRILL_MATCH_TOL_MM:
                tap = next((m for m, td in TAP_DRILLS.items() if abs(td - dia) <= TAP_MATCH_TOL_MM), None)
                det = f'Ø{dia:.3f} mm is not a stock drill size (nearest Ø{near:g} mm)'
                if v3d:
                    det += f'; v3 plans {v3d}'
                    if (h['v3'] or {}).get('notes'):
                        det += ' and opens it out after'
                if tap:
                    det += f'. Close to the {tap} tap drill (Ø{TAP_DRILLS[tap]:g}) — if this is a {tap} thread, model it at the tap-drill size'
                second_op = bool((h['v3'] or {}).get('notes'))
                add('non_standard_hole', 'warn' if (second_op or not tap) else 'info',
                    f'Hole Ø{dia:.3f} mm (nearest Ø{near:g})', det + '.',
                    {'dia_mm': round(dia, 4), 'v3_drill': v3d, 'possible_thread': tap},
                    {'nearest_standard_dia_mm': near}, fidx)

    # ── internal corners (concave partial cylinders) ────────────────────────
    ns_groups: dict[tuple, list] = {}     # (kind, radius) -> faces, for non-standard radii
    for g in partials:
        c0 = cyl_cache[g[0]]
        ax, r = c0['ax'], c0['r']
        lo = min(cyl_cache[i]['ext'][0] for i in g)
        hi = max(cyl_cache[i]['ext'][1] for i in g)
        depth = hi - lo
        # floor fillet: tangent to a floor whose outward normal is a setup direction, axis
        # lying in that floor -> made by the corner radius of a bull-nose / ball from that setup
        floor = any(faces[j]['t'] == 'plane' and faces[j].get('n') and 'smooth' in conv_between(i, j)
                    and any(_dot(faces[j]['n'], v) >= COS_PAR and _perp(ax, v) for v in tool_vecs.values())
                    for i in g for j in adj.get(i, ()))
        vertical = (not floor) and any(_parallel(ax, ta) for ta in tool_axes)
        near = _std_nearest(r, STANDARD_RADII_MM)
        if floor:
            if abs(near - r) > RADIUS_MATCH_TOL_MM:
                ns_groups.setdefault(('floor_fillet', round(r, 3)), []).extend(g)
        elif vertical:
            exp_r = max(MIN_PRACTICAL_CUTTER_R_MM, depth / (2 * MAX_CUTTER_LD))
            if r + 1e-6 < exp_r:
                sev = 'block' if r < MICRO_CORNER_R_MM else 'warn'
                add('small_internal_corner', sev, f'Internal corner ({exp_r:.2f}, {r:.2f})',
                    f'Expected minimum radius {exp_r:.2f} mm, actual {r:.2f} mm '
                    f'({depth:.2f} mm deep along {_axis_name(ax)}).',
                    {'radius_mm': round(r, 3), 'depth_mm': round(depth, 3)},
                    {'min_radius_mm': round(exp_r, 3), 'max_cutter_l_over_d': MAX_CUTTER_LD}, g)
            if r <= CORNER_MAX_R_MM and abs(near - r) > RADIUS_MATCH_TOL_MM:
                ns_groups.setdefault(('internal_corner', round(r, 3)), []).extend(g)
    # concave tori = fillet blends where a floor fillet turns a corner
    for f in faces:
        if f['i'] in skip or f['t'] != 'torus' or not f.get('cc'):
            continue
        r = f['r']
        near = _std_nearest(r, STANDARD_RADII_MM)
        if abs(near - r) > RADIUS_MATCH_TOL_MM:
            ns_groups.setdefault(('floor_fillet', round(r, 3)), []).append(f['i'])
    for (kind, r), idxs in sorted(ns_groups.items()):
        near = _std_nearest(r, STANDARD_RADII_MM)
        n = len(set(idxs))
        if kind == 'floor_fillet':
            add('non_standard_radius', 'warn', f'Floor fillet R{r:g} (nearest R{near:g})',
                f'Floor fillet radius {r:.3f} mm ({n} face{"s" if n != 1 else ""}) does not match a '
                f'standard bull-nose / ball radius; nearest standard R{near:g} mm — otherwise a '
                f'ball-nose 3D pass.', {'radius_mm': r, 'kind': kind, 'faces': n},
                {'nearest_standard_radius_mm': near}, idxs)
        else:
            add('non_standard_radius', 'info', f'Internal corner R{r:g} (nearest R{near:g})',
                f'Vertical corner radius {r:.3f} mm ({n} face{"s" if n != 1 else ""}) is not a '
                f'standard cutter radius; nearest standard R{near:g} mm. Cut by interpolating a '
                f'smaller cutter.', {'radius_mm': r, 'kind': kind, 'faces': n},
                {'nearest_standard_radius_mm': near}, idxs)

    # ── sharp concave vertical corners (radius 0) ───────────────────────────
    for e in edges:
        if e.get('conv') != 'concave' or e.get('ang', 0) < SHARP_EDGE_DEG or e['kind'] != 'line':
            continue
        a, b = e['f']
        if a in skip or b in skip:
            continue
        n1, n2 = e['n']
        for ta in tool_axes:
            if not (_parallel(e['dir'], ta) and _perp(n1, ta) and _perp(n2, ta)):
                continue
            # producible sharp as a floor/wall step from another setup?
            ok = any((_dot(n1, v) >= COS_PAR and _perp(n2, v)) or (_dot(n2, v) >= COS_PAR and _perp(n1, v))
                     for v in tool_vecs.values())
            if ok:
                continue
            depth = e['len']
            exp_r = max(MIN_PRACTICAL_CUTTER_R_MM, depth / (2 * MAX_CUTTER_LD))
            add('small_internal_corner', 'block', f'Internal corner ({exp_r:.2f}, 0.00)',
                f'Expected minimum radius {exp_r:.2f} mm, actual 0.00 mm (sharp {e["ang"]:.0f}° '
                f'corner, {depth:.2f} mm deep along {_axis_name(ta)}) — needs EDM or a corner radius.',
                {'radius_mm': 0.0, 'depth_mm': round(depth, 3), 'corner_angle_deg': round(180 - e['ang'], 1)},
                {'min_radius_mm': round(exp_r, 3)}, [a, b])
            break

    # ── chamfers + non-perpendicular planes ─────────────────────────────────
    def max_edge_len(i):
        return max((e['len'] for j in adj.get(i, ()) for e in pair_edges(i, j)), default=0.0)

    def all_convex(i):
        cs = set()
        for j in adj.get(i, ()):
            cs |= conv_between(i, j)
        cs.discard('smooth')
        return bool(cs) and cs == {'convex'}

    chamfer_faces = set()
    ch_groups: dict[tuple, list] = {}
    for f in faces:
        i = f['i']
        if i in skip:
            continue
        if f['t'] == 'plane' and f.get('n'):
            if any(_parallel(f['n'], ta) or _perp(f['n'], ta) for ta in tool_axes):
                continue
            L = max_edge_len(i)
            width = f['a'] / L if L else 0.0
            tilt = min(math.degrees(math.acos(min(1.0, abs(_dot(f['n'], ta))))) for ta in tool_axes)
            ref = min(tool_axes, key=lambda ta: math.acos(min(1.0, abs(_dot(f['n'], ta)))))
            if width <= CHAMFER_MAX_WIDTH_MM and all_convex(i):
                chamfer_faces.add(i)
                ch_groups.setdefault(('plane', round(width, 2), round(tilt, 1), _axis_name(ref)), []).append(i)
            else:
                add('non_perpendicular_face', 'warn', f'Tilted face ({tilt:.1f}°)',
                    f'Planar face tilted {tilt:.1f}° from {_axis_name(ref)} and not parallel to any '
                    f'setup axis ({", ".join(tool_dirs)}) — needs a ball-nose 3D pass, an angled '
                    f'fixture or a 4th axis.',
                    {'angle_from_axis_deg': round(tilt, 2), 'normal': f['n'], 'area_mm2': round(f['a'], 2)},
                    {'angle_from_axis_deg': [0, 90]}, [i])
        elif f['t'] == 'cone' and all_convex(i):
            # countersink / hole-edge chamfer
            ch_groups.setdefault(('cone', round(2 * f['r'], 2), round(f['half_angle'], 1), ''), []).append(i)
    for (kind, size, ang, axn), idxs in sorted(ch_groups.items()):
        n = len(idxs)
        nf = f' ({n} faces)' if n > 1 else ''
        if kind == 'plane':
            add('chamfer', 'info', f'Chamfer {size:.2f} mm × {ang:g}°{nf}',
                f'Planar chamfer ~{size:.2f} mm wide, {ang:g}° from {axn}{" on " + str(n) + " edges" if n > 1 else ""} '
                f'— chamfer-mill pass.', {'width_mm': size, 'angle_deg': ang, 'faces': n},
                {'tool': 'chamfer mill'}, idxs)
        else:
            add('chamfer', 'info', f'Hole-edge chamfer Ø{size:g} × {ang:g}°{nf}',
                f'Conical edge break (half-angle {ang:g}°) at a Ø{size:g} mm edge'
                f'{" on " + str(n) + " holes" if n > 1 else ""} — chamfer / countersink tool.',
                {'half_angle_deg': ang, 'ref_dia_mm': size, 'faces': n}, {'tool': 'chamfer mill / countersink'}, idxs)

    # ── external edge fillets (convex rounds not made by side milling) ──────
    ext = []
    for f in faces:
        i = f['i']
        if i in skip:
            continue
        c = cyl(i) if f['t'] == 'cylinder' or f.get('cyl_like') else None
        r = None
        if c and c.get('cc') is False and c.get('span', 0) < 359:
            if any(_parallel(c['ax'], ta) for ta in tool_axes):
                continue                      # vertical outside corner: profile-milled
            r = c['r']
        elif f['t'] == 'torus' and f.get('cc') is False:
            r = f['r']
        if r is None or r > EXT_FILLET_MAX_R_MM:
            continue
        smooth = sum(1 for j in adj.get(i, ()) if 'smooth' in conv_between(i, j))
        if smooth < 1:
            continue
        ext.append((round(r, 3), i))
    by_r = {}
    for r, i in ext:
        by_r.setdefault(r, []).append(i)
    for r, idxs in sorted(by_r.items()):
        add('external_edge_fillet', 'info', f'External fillet R{r:g} ({len(idxs)} face{"s" if len(idxs) != 1 else ""})',
            f'Convex edge round R{r:g} mm — corner-rounding cutter R{_std_nearest(r, STANDARD_RADII_MM):g} '
            f'or ball-nose pass.', {'radius_mm': r, 'faces': len(idxs)},
            {'tool': f'corner-rounding R{_std_nearest(r, STANDARD_RADII_MM):g}'}, idxs)

    # ── thin walls ──────────────────────────────────────────────────────────
    for p in facts.get('thin_wall_pairs') or []:
        if any(i in skip for i in p['faces']) or p.get('overlap_area_mm2', 1e9) < THIN_WALL_MIN_OVERLAP_MM2:
            continue
        t = p['thickness']
        sev = 'block' if t < THIN_WALL_BLOCK_MM else 'warn'
        add('thin_wall', sev, f'Thin wall ({THIN_WALL_WARN_MM:.2f}, {t:.2f})',
            f'Expected minimum wall {THIN_WALL_WARN_MM:.2f} mm, actual {t:.2f} mm.',
            {'thickness_mm': t}, {'min_thickness_mm': THIN_WALL_WARN_MM}, p['faces'])

    # ── v3 part-level regions (no face mapping from v3) ─────────────────────
    if v3:
        plan_tools = {t.get('tool'): t for t in ((v3.get('plan') or {}).get('tools') or [])}
        for st in v3.get('forced_small_tools') or []:
            t = plan_tools.get(st.get('tool'), {})
            dia = t.get('dia_mm') or st.get('dia_mm')
            add('small_tool_region', 'warn', f'{st.get("tool")}' + (f' (Ø{dia:g} mm)' if dia else ''),
                st.get('reason') or 'Geometry forces a small cutter.',
                {'tool': st.get('tool'), 'dia_mm': dia, 'minutes': t.get('minutes')},
                {'source': 'v3 planner'}, [])
        try:
            un = float(v3.get('unreachable_mm3'))
        except (TypeError, ValueError):
            un = None
        if un is not None and un > 1.0:
            rem = v3.get('removal_volume_mm3')
            frac = un / rem if rem else None
            sev = 'block' if un > 100.0 and (frac is None or frac > 0.01) else 'warn'
            add('unreachable_volume', sev, f'{un:.0f} mm³ unreachable',
                f'{un:.0f} mm³' + (f' ({frac * 100:.2f}% of removal)' if frac is not None else '')
                + ' cannot be reached from the analysed 3-axis setup directions.',
                {'unreachable_mm3': un, 'removal_volume_mm3': rem}, {'unreachable_mm3': 0}, [])

    out = []
    for cid in CATEGORY_ORDER:
        its = items[cid]
        if not its:
            continue
        label, color, why = CATEGORY_META[cid]
        sev = min((it['severity'] for it in its), key=lambda s: SEV_RANK[s])
        its.sort(key=lambda it: SEV_RANK[it['severity']])
        out.append({'id': cid, 'label': label, 'severity': sev, 'color': color, 'count': len(its),
                    'items': its, 'why': why})
    return out
