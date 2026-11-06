"""
step_geometry.py — real face geometry from a job's STEP file (PythonOCC), used
by the CMM program generator.

Face index = 0-based TopExp_Explorer(TopAbs_FACE) order — the same convention
as datum_tagger/server.py and 1. extract_features.py, so datum face indices
saved by the Datum Tagger refer to the same faces.

For every Plane / Cylinder face we record type, area, centroid, the outward
normal (planes) or axis/radius (cylinders), and a small set of on-surface probe
candidate points (UV grid, trimmed by BRepClass_FaceClassifier so every point
lies on the real bounded face). Result is cached to <job_dir>/cmm_geometry.json.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

GRID_N = 7            # UV grid resolution per face for probe-point candidates
UV_MARGIN = 0.12      # stay this fraction away from face UV bounds (edge-break / chamfer)
MAX_CANDIDATES = 12   # spread-out candidates kept per plane face
CACHE_VERSION = 2


def _spread(points: list[dict], k: int) -> list[dict]:
    """Farthest-point selection: k points that cover the face well."""
    if len(points) <= k:
        return points
    # start from the point closest to the mean
    cx = sum(p['xyz'][0] for p in points) / len(points)
    cy = sum(p['xyz'][1] for p in points) / len(points)
    cz = sum(p['xyz'][2] for p in points) / len(points)
    chosen = [min(points, key=lambda p: math.dist(p['xyz'], (cx, cy, cz)))]
    while len(chosen) < k:
        nxt = max(points, key=lambda p: min(math.dist(p['xyz'], c['xyz']) for c in chosen))
        chosen.append(nxt)
    return chosen


def extract(step_path: Path) -> dict:
    from OCC.Core.STEPControl import STEPControl_Reader
    from OCC.Core.IFSelect import IFSelect_RetDone
    from OCC.Core.TopExp import TopExp_Explorer
    from OCC.Core.TopAbs import TopAbs_FACE, TopAbs_REVERSED, TopAbs_IN, TopAbs_ON
    from OCC.Core.TopoDS import topods
    from OCC.Core.BRepAdaptor import BRepAdaptor_Surface
    from OCC.Core.GeomAbs import GeomAbs_Plane, GeomAbs_Cylinder
    from OCC.Core.GProp import GProp_GProps
    from OCC.Core.BRepGProp import brepgprop
    from OCC.Core.BRepTools import breptools
    from OCC.Core.BRepClass import BRepClass_FaceClassifier
    from OCC.Core.BRepLProp import BRepLProp_SLProps
    from OCC.Core.gp import gp_Pnt2d
    from OCC.Core.Bnd import Bnd_Box
    from OCC.Core.BRepBndLib import brepbndlib

    reader = STEPControl_Reader()
    if reader.ReadFile(str(step_path)) != IFSelect_RetDone:
        raise RuntimeError(f'Could not read STEP: {step_path}')
    reader.TransferRoots()
    shape = reader.OneShape()

    bb = Bnd_Box()
    brepbndlib.Add(shape, bb)
    xmin, ymin, zmin, xmax, ymax, zmax = bb.Get()

    faces = []
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    idx = 0
    while exp.More():
        face = topods.Face(exp.Current())
        surf = BRepAdaptor_Surface(face, True)
        st = surf.GetType()
        reversed_ = face.Orientation() == TopAbs_REVERSED
        rec = {'face_index': idx}
        props = GProp_GProps()
        brepgprop.SurfaceProperties(face, props)
        c = props.CentreOfMass()
        rec['area_mm2'] = round(props.Mass(), 4)
        rec['centroid'] = [round(c.X(), 4), round(c.Y(), 4), round(c.Z(), 4)]
        if st == GeomAbs_Plane:
            pln = surf.Plane()
            d = pln.Axis().Direction()
            n = [d.X(), d.Y(), d.Z()]
            if reversed_:
                n = [-v for v in n]
            rec.update({'type': 'plane', 'normal': [round(v, 6) for v in n]})
        elif st == GeomAbs_Cylinder:
            cyl = surf.Cylinder()
            ax = cyl.Axis()
            d, loc = ax.Direction(), ax.Location()
            rec.update({
                'type': 'cylinder',
                'radius_mm': round(cyl.Radius(), 5),
                'axis_dir': [round(d.X(), 6), round(d.Y(), 6), round(d.Z(), 6)],
                'axis_loc': [round(loc.X(), 4), round(loc.Y(), 4), round(loc.Z(), 4)],
                # Reversed cylinder = material outside the surface = a hole/bore.
                'inner': bool(reversed_),
            })
        else:
            idx += 1
            exp.Next()
            continue

        umin, umax, vmin, vmax = breptools.UVBounds(face)
        du, dv = umax - umin, vmax - vmin
        clf = BRepClass_FaceClassifier()
        cands = []
        for i in range(GRID_N):
            for j in range(GRID_N):
                u = umin + du * (UV_MARGIN + (1 - 2 * UV_MARGIN) * i / (GRID_N - 1))
                v = vmin + dv * (UV_MARGIN + (1 - 2 * UV_MARGIN) * j / (GRID_N - 1))
                clf.Perform(face, gp_Pnt2d(u, v), 1e-6)
                if clf.State() not in (TopAbs_IN,):
                    continue
                sl = BRepLProp_SLProps(surf, u, v, 1, 1e-6)
                if not sl.IsNormalDefined():
                    continue
                p = sl.Value()
                nn = sl.Normal()
                nv = [nn.X(), nn.Y(), nn.Z()]
                if reversed_:
                    nv = [-x for x in nv]
                cands.append({'xyz': [round(p.X(), 4), round(p.Y(), 4), round(p.Z(), 4)],
                              'ijk': [round(x, 5) for x in nv]})
        # cylinders keep the full grid so a single-height probe ring can be picked later
        rec['points'] = cands if rec['type'] == 'cylinder' else _spread(cands, MAX_CANDIDATES)
        if rec['type'] == 'cylinder' and cands:
            # axial extent of the trimmed face (for hole depth / mid-height probing)
            a = rec['axis_dir']
            ts = [sum((q['xyz'][k] - rec['axis_loc'][k]) * a[k] for k in range(3)) for q in cands]
            rec['axial_range'] = [round(min(ts), 4), round(max(ts), 4)]
        faces.append(rec)
        idx += 1
        exp.Next()

    return {
        'version': CACHE_VERSION,
        'step_file': Path(step_path).name,
        'face_count': idx,
        'bbox': {'min': [round(xmin, 4), round(ymin, 4), round(zmin, 4)],
                 'max': [round(xmax, 4), round(ymax, 4), round(zmax, 4)]},
        'faces': faces,
    }


def load_or_extract(job_dir: Path, step_path: Path) -> dict:
    cache = job_dir / 'cmm_geometry.json'
    if cache.exists() and cache.stat().st_mtime >= step_path.stat().st_mtime:
        geo = json.loads(cache.read_text(encoding='utf-8'))
        if geo.get('version') == CACHE_VERSION:
            return geo
    geo = extract(step_path)
    cache.write_text(json.dumps(geo), encoding='utf-8')
    return geo
