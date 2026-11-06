"""
cmm.py — generate a DMIS-like CMM inspection program for a job from its
tolerances + datums, using real face geometry from the job's STEP.

Tolerance sources (first non-empty wins):
  1. job tolerances.json   (Inspection tab; {cluster_id: {nominal_mm, upper_tol_mm, lower_tol_mm, ...}})
  2. part folder tolerances.json (same format)
  3. part folder Inspection Report/*.xlsx — the real drawing characteristics
     (description / TOL+ / TOL-) recorded by QC
Datum sources (first available wins):
  1. job datums.json (Datum Tagger tab)
  2. part folder *.datums.json, only if its step_file_hash matches the job's STEP
  3. auto 3-2-1 frame from geometry: A = largest plane, B = largest plane
     perpendicular to A, C = largest plane perpendicular to both (labelled as auto)

Each drawing characteristic is matched to geometry:
  diameter -> hole/boss cylinder whose CAD diameter is within tolerance of the
              drawing nominal (else nearest within CAD_MISMATCH_WINDOW_MM, flagged)
  linear   -> pair of opposed parallel planes whose separation matches
              (else overall bounding-box extent)
Unmatched characteristics are returned with matched:false and no points.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from . import part_data, step_geometry

CAD_MISMATCH_WINDOW_MM = 0.5   # widest CAD-vs-drawing gap we still call "same feature" (flagged)
PARALLEL_DOT = 0.9995          # |n1·n2| above this = parallel planes
PERP_DOT = 0.01                # |n1·n2| below this = perpendicular planes
CIRCLE_POINTS = 4              # touch points per circle (CMM fits LSQ circle)
PLANE_POINTS = 3               # touch points per plane (min to define a plane)
DATUM_PLANE_POINTS = 4


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _sub(a, b):
    return [x - y for x, y in zip(a, b)]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _pts(face, k):
    return [{'xyz': p['xyz'], 'ijk': p['ijk']} for p in step_geometry._spread(face['points'], k)]


# ── Datums ─────────────────────────────────────────────────────────────────

def _resolve_datums(job_dir: Path, part_dir: Path | None, step_path: Path, geo: dict):
    by_idx = {f['face_index']: f for f in geo['faces']}
    raw, source = None, None
    jd = job_dir / 'datums.json'
    if jd.exists():
        try:
            d = json.loads(jd.read_text(encoding='utf-8'))
            if d.get('datums'):
                raw, source = d['datums'], 'job datums.json (Datum Tagger)'
        except Exception:
            pass
    if raw is None:
        pd_ = part_data.load_part_datums(part_dir)
        if pd_ and pd_.get('datums'):
            if pd_.get('step_file_hash') and pd_['step_file_hash'] == _sha256(step_path):
                raw, source = pd_['datums'], 'part folder datums.json (hash-verified)'
    datums = []
    if raw:
        for d in raw:
            f = by_idx.get(d.get('face_index'))
            if f is None:
                continue
            datums.append({'label': d['label'], 'face_index': f['face_index'], 'type': f['type'],
                           'normal': f.get('normal') or f.get('axis_dir'), 'centroid': f['centroid'],
                           'area_mm2': f['area_mm2'], 'points': _pts(f, DATUM_PLANE_POINTS)})
    if not datums:
        planes = sorted((f for f in geo['faces'] if f['type'] == 'plane' and f['points']),
                        key=lambda f: -f['area_mm2'])
        chosen = []
        for f in planes:
            if all(abs(_dot(f['normal'], c['normal'])) < PERP_DOT for c in chosen):
                chosen.append(f)
            if len(chosen) == 3:
                break
        for label, f in zip('ABC', chosen):
            datums.append({'label': label, 'face_index': f['face_index'], 'type': 'plane',
                           'normal': f['normal'], 'centroid': f['centroid'], 'area_mm2': f['area_mm2'],
                           'points': _pts(f, DATUM_PLANE_POINTS)})
        source = 'auto 3-2-1 (no datums tagged: largest mutually-perpendicular planes)'
    return datums, source


# ── Geometry matching ──────────────────────────────────────────────────────

def _holes(geo):
    """Group cylinder faces into distinct cylinders (a full hole is often 2 half faces)."""
    groups = []
    for f in geo['faces']:
        if f['type'] != 'cylinder' or not f['points']:
            continue
        for g in groups:
            if (abs(g['radius_mm'] - f['radius_mm']) < 1e-3 and abs(abs(_dot(g['axis_dir'], f['axis_dir'])) - 1) < 1e-4):
                off = _sub(f['axis_loc'], g['axis_loc'])
                along = _dot(off, g['axis_dir'])
                perp = math.sqrt(max(_dot(off, off) - along * along, 0))
                if perp < 1e-3:
                    g['faces'].append(f)
                    break
        else:
            groups.append({'radius_mm': f['radius_mm'], 'axis_dir': f['axis_dir'],
                           'axis_loc': f['axis_loc'], 'inner': f['inner'], 'faces': [f]})
    return groups


def _arc_deg(h) -> float:
    """Angular coverage of a cylinder group (360 = full hole), from its surface points."""
    if 'arc_deg' in h:
        return h['arc_deg']
    a = h['axis_dir']
    # orthonormal basis perpendicular to the axis
    ref = [1, 0, 0] if abs(a[0]) < 0.9 else [0, 1, 0]
    u = _sub(ref, [a[k] * _dot(ref, a) for k in range(3)])
    nu = math.sqrt(_dot(u, u))
    u = [x / nu for x in u]
    v = [a[1] * u[2] - a[2] * u[1], a[2] * u[0] - a[0] * u[2], a[0] * u[1] - a[1] * u[0]]
    angs = sorted(math.degrees(math.atan2(_dot(_sub(p['xyz'], h['axis_loc']), v),
                                          _dot(_sub(p['xyz'], h['axis_loc']), u))) % 360
                  for f in h['faces'] for p in f['points'])
    if len(angs) < 2:
        h['arc_deg'] = 0.0
    else:
        gaps = [b - a_ for a_, b in zip(angs, angs[1:])] + [angs[0] + 360 - angs[-1]]
        h['arc_deg'] = round(360 - max(gaps), 1)
    return h['arc_deg']


def _match_diameter(ch, holes, used):
    nom, tol = ch['nominal_mm'], max(ch['upper_tol_mm'], ch['lower_tol_mm'])
    best = None
    for i, h in enumerate(holes):
        if i in used:
            continue
        delta = abs(2 * h['radius_mm'] - nom)
        area = sum(f['area_mm2'] for f in h['faces'])
        # drawing diameters are usually full bores; partial arcs (<180°) are fillets/corners
        key = (delta > tol, _arc_deg(h) < 180, not h['inner'], delta, -area)
        if delta <= CAD_MISMATCH_WINDOW_MM and (best is None or key < best[0]):
            best = (key, i, h, delta)
    if best is None:
        return None
    _, i, h, delta = best
    used.add(i)
    cad = round(2 * h['radius_mm'], 4)
    a = h['axis_dir']
    allp = [p for f in h['faces'] for p in f['points']]
    # probe one circle: keep candidates on the axial level nearest mid-depth
    ts = [_dot(_sub(p['xyz'], h['axis_loc']), a) for p in allp]
    mid = (min(ts) + max(ts)) / 2
    level = min(set(round(t, 3) for t in ts), key=lambda t: abs(t - mid))
    ring = [p for p, t in zip(allp, ts) if abs(t - level) < 1e-2]
    pts = step_geometry._spread(ring if len(ring) >= 3 else allp, CIRCLE_POINTS)
    # centre point on axis at the probed height
    t = sum(_dot(_sub(p['xyz'], h['axis_loc']), a) for p in pts) / len(pts)
    centre = [round(h['axis_loc'][k] + a[k] * t, 4) for k in range(3)]
    return {
        'type': 'circle_inner' if h['inner'] else 'circle_outer',
        'geometry': {'cad_value_mm': cad, 'centre': centre, 'axis': a,
                     'face_indices': [f['face_index'] for f in h['faces']]},
        'cad_nominal_mismatch': delta > max(ch['upper_tol_mm'], ch['lower_tol_mm']),
        'probe_strategy': f"{len(pts)}-pt {'bore' if h['inner'] else 'boss'} circle at mid-depth, LSQ fit, report DIAM",
        'points': [{'xyz': p['xyz'], 'ijk': p['ijk']} for p in pts],
    }


def _plane_pairs(geo):
    planes = [f for f in geo['faces'] if f['type'] == 'plane' and len(f['points']) >= PLANE_POINTS]
    pairs = []
    for i, a in enumerate(planes):
        for b in planes[i + 1:]:
            if _dot(a['normal'], b['normal']) > -PARALLEL_DOT:
                continue  # need opposed faces (material between them, e.g. thickness/width)
            sep = abs(_dot(_sub(b['centroid'], a['centroid']), a['normal']))
            pairs.append((sep, a, b))
    return pairs


def _match_linear(ch, pairs, used, geo):
    nom, tol = ch['nominal_mm'], max(ch['upper_tol_mm'], ch['lower_tol_mm'])
    best = None
    for sep, a, b in pairs:
        k = (a['face_index'], b['face_index'])
        if k in used:
            continue
        delta = abs(sep - nom)
        if delta > CAD_MISMATCH_WINDOW_MM:
            continue
        key = (delta > tol, -(min(a['area_mm2'], b['area_mm2'])) if delta <= tol else delta)
        if best is None or key < best[0]:
            best = (key, sep, a, b, delta)
    if best is not None:
        _, sep, a, b, delta = best
        used.add((a['face_index'], b['face_index']))
        pts = _pts(a, PLANE_POINTS) + _pts(b, PLANE_POINTS)
        return {
            'type': 'distance_plane_plane',
            'geometry': {'cad_value_mm': round(sep, 4), 'direction': a['normal'],
                         'face_indices': [a['face_index'], b['face_index']]},
            'cad_nominal_mismatch': delta > tol,
            'probe_strategy': f'{PLANE_POINTS} pts on each of 2 opposed planes, report DISTB along normal',
            'points': pts,
        }
    # overall extent fallback
    lo, hi = geo['bbox']['min'], geo['bbox']['max']
    for ax, name in enumerate('XYZ'):
        ext = hi[ax] - lo[ax]
        delta = abs(ext - nom)
        if delta <= CAD_MISMATCH_WINDOW_MM and ('bbox', ax) not in used:
            used.add(('bbox', ax))
            allp = [p for f in geo['faces'] for p in f['points']]
            pmin = min(allp, key=lambda p: p['xyz'][ax])
            pmax = max(allp, key=lambda p: p['xyz'][ax])
            return {
                'type': 'overall_extent',
                'geometry': {'cad_value_mm': round(ext, 4), 'axis': name},
                'cad_nominal_mismatch': delta > tol,
                'probe_strategy': f'extreme touch points along {name} (overall length), report DISTB',
                'points': [{'xyz': pmin['xyz'], 'ijk': pmin['ijk']}, {'xyz': pmax['xyz'], 'ijk': pmax['ijk']}],
            }
    return None


def _cluster_features(tols: dict, job_dir: Path, part_dir: Path | None, geo: dict):
    """Tolerances keyed by cluster_id (Inspection tab format) -> features via classified.json."""
    by_idx = {f['face_index']: f for f in geo['faces']}
    classified = None
    for d in (job_dir, part_dir):
        if d is None:
            continue
        m = sorted(d.glob('*_classified.json'))
        if m:
            classified = json.loads(m[0].read_text(encoding='utf-8'))
            break
    clusters = {str(c.get('cluster_id')): c for c in (classified or {}).get('clusters', [])}
    feats = []
    for fid, t in tols.items():
        c = clusters.get(str(fid))
        faces = [by_idx[i] for i in (c or {}).get('face_indices', []) if i in by_idx]
        cyl = [f for f in faces if f['type'] == 'cylinder']
        pts_src = cyl or faces
        pts = step_geometry._spread([p for f in pts_src for p in f['points']],
                                    CIRCLE_POINTS if cyl else PLANE_POINTS * 2)
        feats.append({
            'characteristic': f"{(c or {}).get('feature_type', 'feature')} {fid}",
            'kind': t.get('measurement_type', 'dimension'),
            'nominal': t.get('nominal_mm'),
            'tolerance': {'plus': t.get('upper_tol_mm'), 'minus': t.get('lower_tol_mm')},
            'matched': bool(pts),
            'type': ('circle_inner' if cyl and cyl[0]['inner'] else 'circle_outer') if cyl else 'surface',
            'geometry': {'face_indices': [f['face_index'] for f in faces],
                         'cad_value_mm': round(2 * cyl[0]['radius_mm'], 4) if cyl else None},
            'cad_nominal_mismatch': False,
            'probe_strategy': f"{len(pts)}-pt {'circle' if cyl else 'surface'} on cluster {fid}",
            'points': [{'xyz': p['xyz'], 'ijk': p['ijk']} for p in pts],
        })
    return feats


# ── Program text ───────────────────────────────────────────────────────────

def _fmt(v):
    return ','.join(f'{x:.4f}' for x in v)


def _program(part_name, datums, features):
    L = [f"DMISMN/'{part_name} - ShiaanX auto CMM program',05.2",
         'UNITS/MM,ANGDEG',
         "FILNAM/'" + part_name.replace(' ', '_') + "_CMM'",
         '$$ Generated from STEP geometry + drawing tolerances. Review before running on machine.',
         'D(MCS)=DATSET/MCS', 'MODE/MAN', '$$ --- Datum alignment ---']
    for d in datums:
        fn = f"DAT_{d['label']}"
        L.append(f"F({fn})=FEAT/PLANE,CART,{_fmt(d['centroid'])},{_fmt(d['normal'])}")
        L.append(f"MEAS/PLANE,F({fn}),{len(d['points'])}")
        for p in d['points']:
            L.append(f"  PTMEAS/CART,{_fmt(p['xyz'])},{_fmt(p['ijk'])}")
        L.append('ENDMES')
        L.append(f"DATDEF/FA({fn}),DAT({d['label']})")
    def _ax(n):
        k = max(range(3), key=lambda i: abs(n[i]))
        return ('' if n[k] > 0 else '-') + 'XYZ'[k]
    if len(datums) >= 3:
        a, b, c = datums[:3]
        L.append(f"D(DRF)=DATSET/DAT({a['label']}),{_ax(a['normal'])}DIR,DAT({b['label']}),"
                 f"{_ax(b['normal'])}DIR,DAT({c['label']}),{_ax(c['normal'])}ORIG")
    elif datums:
        L.append(f"D(DRF)=DATSET/DAT({datums[0]['label']}),{_ax(datums[0]['normal'])}DIR")
    L += ['MODE/AUTO,PROG,MAN', '$$ --- Characteristics ---']
    for f in features:
        if not f['matched']:
            L.append(f"$$ {f['id']}: '{f['characteristic']}' NOT MATCHED to geometry - measure manually")
            continue
        fid = f['id']
        t = f['tolerance']
        g = f['geometry']
        if f['type'].startswith('circle'):
            io = 'INNER' if f['type'] == 'circle_inner' else 'OUTER'
            L.append(f"F({fid})=FEAT/CIRCLE,{io},CART,{_fmt(g.get('centre') or f['points'][0]['xyz'])},"
                     f"{_fmt(g.get('axis') or [0, 0, 1])},{f['nominal']:.4f}")
            L.append(f"T({fid}_D)=TOL/DIAM,-{t['minus']:.4f},{t['plus']:.4f}")
            L.append(f"MEAS/CIRCLE,F({fid}),{len(f['points'])}")
        else:
            L.append(f"F({fid})=FEAT/PLANE,CART,{_fmt(f['points'][0]['xyz'])},{_fmt(f['points'][0]['ijk'])}")
            L.append(f"T({fid}_L)=TOL/DISTB,NOMINL,{f['nominal']:.4f},-{t['minus']:.4f},{t['plus']:.4f}")
            L.append(f"MEAS/PLANE,F({fid}),{len(f['points'])}")
        for p in f['points']:
            L.append(f"  PTMEAS/CART,{_fmt(p['xyz'])},{_fmt(p['ijk'])}")
        L.append('ENDMES')
        L.append(f"OUTPUT/FA({fid}),TA({fid}_{'D' if f['type'].startswith('circle') else 'L'})")
        if f.get('cad_nominal_mismatch'):
            L.append(f"$$ NOTE {fid}: CAD value {g.get('cad_value_mm')} differs from drawing {f['nominal']} beyond tolerance")
    L.append('ENDFIL')
    return '\n'.join(L)


# ── Entry point ────────────────────────────────────────────────────────────

def build(job_dir: Path, part_name: str) -> dict:
    steps = part_data.job_step_files(job_dir)
    if not steps:
        return {'status': 'error', 'error': 'STEP file not found in job'}
    step_path = steps[0]
    part_dir = part_data.find_part_dir(job_dir)

    tol_source, job_tols = None, {}
    jt = job_dir / 'tolerances.json'
    if jt.exists():
        try:
            job_tols = json.loads(jt.read_text(encoding='utf-8')) or {}
        except Exception:
            job_tols = {}
    if job_tols:
        tol_source = 'job tolerances.json (Inspection tab)'
    else:
        job_tols = part_data.load_part_tolerances_json(part_dir)
        if job_tols:
            tol_source = 'part folder tolerances.json'
    chars = [] if job_tols else part_data.load_inspection_characteristics(part_dir)
    dims = [c for c in chars if c['kind'] != 'visual']
    if not job_tols and not dims:
        return {
            'status': 'needs_tolerances',
            'part_folder': part_dir.name if part_dir else None,
            'missing': ['No tolerances saved for this job (Inspection tab -> POST /jobs/{id}/tolerances)',
                        'No tolerances.json with entries in the part folder',
                        'No Inspection Report/*.xlsx with drawing characteristics in the part folder'],
            'datums': None, 'features': [], 'program_format': 'DMIS-like', 'program_text': '', 'count': 0,
        }
    if not job_tols:
        tol_source = f"drawing characteristics from {part_dir.name}/Inspection Report"

    geo = step_geometry.load_or_extract(job_dir, step_path)
    datums, datum_source = _resolve_datums(job_dir, part_dir, step_path, geo)

    features = []
    if job_tols:
        features = _cluster_features(job_tols, job_dir, part_dir, geo)
    else:
        holes, pairs = _holes(geo), _plane_pairs(geo)
        used_h, used_p = set(), set()
        for c in dims:
            m = _match_diameter(c, holes, used_h) if c['kind'] == 'diameter' else _match_linear(c, pairs, used_p, geo)
            f = {
                'characteristic': ('DIA ' if c['kind'] == 'diameter' else '') + f"{c['nominal_mm']} (drawing item {c['sl_no']})",
                'kind': c['kind'],
                'nominal': c['nominal_mm'],
                'tolerance': {'plus': c['upper_tol_mm'], 'minus': c['lower_tol_mm']},
                'shop_instrument': c.get('instrument'),
                'matched': m is not None,
            }
            if m:
                f.update(m)
            else:
                f.update({'type': None, 'geometry': None, 'probe_strategy': 'manual — no matching CAD geometry found',
                          'points': [], 'cad_nominal_mismatch': None})
            features.append(f)
    for i, f in enumerate(features, 1):
        f['id'] = f'CH{i:02d}'
        # keep contract key order: id, type, nominal, tolerance, probe_strategy, points first
        features[i - 1] = {k: f.get(k) for k in ('id', 'type', 'nominal', 'tolerance', 'probe_strategy', 'points')} | \
                          {k: v for k, v in f.items() if k not in ('id', 'type', 'nominal', 'tolerance', 'probe_strategy', 'points')}

    visual = [{'description': c['description'], 'instrument': c.get('instrument')} for c in chars if c['kind'] == 'visual']
    matched = sum(1 for f in features if f['matched'])
    return {
        'status': 'ok',
        'part_folder': part_dir.name if part_dir else None,
        'tolerance_source': tol_source,
        'datum_source': datum_source,
        'datums': datums,
        'features': features,
        'visual_checks': visual,
        'program_format': 'DMIS-like',
        'program_text': _program(part_name, datums, features),
        'count': len(features),
        'matched_count': matched,
        'total_points': sum(len(f['points']) for f in features) + sum(len(d['points']) for d in datums),
    }
