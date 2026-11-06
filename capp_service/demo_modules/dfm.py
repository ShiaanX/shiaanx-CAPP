"""
dfm.py — Design-for-Manufacturability findings derived from the v3 analysis
(3-axis VMC, vise workholding). Every finding cites the v3 numbers it came from.
"""

from __future__ import annotations

from . import dfm_geometry

# ── Thresholds (3-axis VMC, aluminium) ──────────────────────────────────────
# Unreachable volume below this is voxel/tessellation noise from the reachability
# sim, not a real undercut.
UNREACHABLE_NOISE_MM3 = 1.0
# Unreachable volume above this AND above this fraction of removal volume cannot be
# fixed with a re-clamp: needs a 4th/5th axis, special tooling or a design change.
# (Both, because v3 residuals of a few hundred mm3 on fillets/corners are normal —
# Motor Mount shows 852 mm3 = 0.6% and was machined on 3-axis in 3 settings.)
UNREACHABLE_BLOCK_MM3 = 100.0
UNREACHABLE_BLOCK_FRAC = 0.01
# Each extra setup on a vise = re-fixturing + re-zeroing time and a datum stack-up
# risk; >3 setups on a 3-axis part is a cost driver worth raising with the client.
SETUPS_WARN = 3
SETUPS_BLOCK = 6
# Small end mills: <3 mm is fragile/slow in Al; <1 mm is a micro tool (special order,
# very low feed) — flag as a blocker for cost/lead time unless the feature can open up.
SMALL_TOOL_WARN_MM = 3.0
SMALL_TOOL_BLOCK_MM = 1.0
# Holes: depth/dia > 5 needs peck drilling; > 10 needs a long-series / gun drill.
HOLE_DDR_WARN = 5.0
HOLE_DDR_BLOCK = 10.0
MICRO_HOLE_MM = 1.0
# Removal > 85% of billet = mostly chips: consider near-net stock / extrusion.
REMOVAL_FRAC_WARN = 0.85


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _vol(dims):
    if not dims or len(dims) != 3 or any(_f(d) is None for d in dims):
        return None
    return _f(dims[0]) * _f(dims[1]) * _f(dims[2])


def build(v3: dict, geometry: dict | None = None) -> dict:
    """geometry = dfm_geometry facts for the job's STEP (None -> no face-level categories)."""
    findings = []

    def add(sev, title, detail, evidence):
        findings.append({'severity': sev, 'title': title, 'detail': detail, 'evidence': evidence})

    # 1. Reachability
    unreach = _f(v3.get('unreachable_mm3'))
    removal = _f(v3.get('removal_volume_mm3'))
    if unreach is not None:
        frac = (unreach / removal) if removal else None
        ev = {'unreachable_mm3': unreach, 'removal_volume_mm3': removal,
              'unreachable_pct_of_removal': round(frac * 100, 3) if frac is not None else None}
        if unreach <= UNREACHABLE_NOISE_MM3:
            add('ok', 'All material reachable on 3-axis',
                'Every region to be removed is reachable from at least one vise setup direction.', ev)
        elif unreach > UNREACHABLE_BLOCK_MM3 and (frac is None or frac > UNREACHABLE_BLOCK_FRAC):
            add('block', f'{unreach:.0f} mm³ not reachable on 3-axis',
                'Material remains that no 3-axis setup direction can reach (undercut / blind side). '
                'Needs 4th-axis, special tooling, or a design change.', ev)
        else:
            add('warn', f'{unreach:.0f} mm³ hard to reach' if unreach >= 10 else f'{unreach:.1f} mm³ hard to reach',
                'A small volume is unreachable from the analysed directions — likely corner/undercut '
                'regions; confirm with the drawing whether it is functional.', ev)

    # 2. Setups
    setups = v3.get('setups_needed')
    if setups is not None:
        recs = [d.get('dir') for d in (v3.get('directions') or []) if d.get('recommended')]
        ev = {'setups_needed': setups, 'recommended_directions': recs}
        if setups > SETUPS_BLOCK:
            add('block', f'{setups} setups needed',
                'Too many re-clamps for a 3-axis vise job — tolerance stack-up and cost risk. '
                'Consider a fixture plate or 4th-axis.', ev)
        elif setups > SETUPS_WARN:
            add('warn', f'{setups} setups needed',
                f'More than {SETUPS_WARN} setups adds re-fixturing time and datum stack-up risk.', ev)
        else:
            add('ok', f'{setups} setup{"s" if setups != 1 else ""} on a 3-axis vise',
                'Setup count is within normal range for a 3-axis VMC.', ev)

    # 3. Forced small tools
    plan_tools = {t.get('tool'): t for t in ((v3.get('plan') or {}).get('tools') or [])}
    small = v3.get('forced_small_tools') or []
    for st in small:
        t = plan_tools.get(st.get('tool'), {})
        dia = _f(t.get('dia_mm')) or _f(st.get('dia_mm'))
        ev = {'tool': st.get('tool'), 'dia_mm': dia, 'minutes': t.get('minutes'), 'reason': st.get('reason')}
        sev = 'block' if (dia is not None and dia < SMALL_TOOL_BLOCK_MM) else 'warn'
        add(sev, f"Small tool forced: {st.get('tool')}" + (f' (Ø{dia:g} mm)' if dia else ''),
            (st.get('reason') or 'Geometry forces a small cutter.') +
            ' Small cutters run slow and break easily — opening up the internal radius / slot width '
            'would cut cycle time.', ev)
    if not small and plan_tools:
        add('ok', 'No forced small tools', 'No feature forces a cutter below the standard range.',
            {'tools_in_plan': len(plan_tools)})

    # 4. Holes
    holes = v3.get('holes') or []
    deep, micro, nodrill = [], [], []
    for h in holes:
        d, depth = _f(h.get('dia_mm')), _f(h.get('depth_mm'))
        if d and depth:
            ddr = depth / d
            if ddr > HOLE_DDR_WARN:
                deep.append({**h, 'depth_to_dia': round(ddr, 1)})
        if d is not None and d < MICRO_HOLE_MM:
            micro.append(h)
        if not h.get('drill'):
            nodrill.append(h)
    for h in deep:
        sev = 'block' if h['depth_to_dia'] > HOLE_DDR_BLOCK else 'warn'
        add(sev, f"Deep hole Ø{_f(h['dia_mm']):g} × {_f(h['depth_mm']):g} mm (L/D {h['depth_to_dia']})",
            'Needs peck drilling' + (' and a long-series / gun drill' if sev == 'block' else '') + '.', h)
    for h in micro:
        add('warn', f"Micro hole Ø{_f(h['dia_mm']):g} mm", 'Micro drill — slow, fragile, special tool.', h)
    for h in nodrill:
        add('warn', f"No standard drill for Ø{h.get('dia_mm')} mm",
            'No stock drill matches this diameter — needs a special drill or interpolation.', h)
    if holes and not (deep or micro or nodrill or any(h.get('notes') for h in holes)):
        add('ok', f'{len(holes)} hole{"s" if len(holes) != 1 else ""} drillable with standard drills',
            f'All holes have L/D ≤ {HOLE_DDR_WARN:g} and a standard drill size.', {'holes': len(holes)})

    # 5. Stock utilisation
    bv = _vol(v3.get('billet_mm'))
    if bv and removal:
        frac = removal / bv
        ev = {'billet_mm': v3.get('billet_mm'), 'billet_volume_mm3': round(bv),
              'removal_volume_mm3': removal, 'removal_pct': round(frac * 100, 1),
              'part_volume_mm3': v3.get('part_volume_mm3')}
        if frac > REMOVAL_FRAC_WARN:
            add('warn', f'{frac * 100:.0f}% of the billet becomes chips',
                'High material removal — consider near-net stock (extrusion / thinner plate) to cut '
                'material cost and cycle time.', ev)
        else:
            add('ok', f'{frac * 100:.0f}% material removal', 'Stock utilisation is reasonable.', ev)

    # 6. Engine warnings: kept verbatim in engine_notes (mostly model caveats); only
    # the ones that mean a check could not run are promoted to findings.
    notes = [str(w) for w in (v3.get('warnings') or [])]
    hole_fail = [w for w in notes if 'hole extraction failed' in w.lower()]
    if hole_fail and not holes:
        add('warn', 'Hole check not run', 'v3 could not extract holes from the CAD, so hole depth / '
            'drill-size checks were skipped — review holes manually against the drawing.',
            {'source': 'v3', 'warning': hole_fail[0]})
    drill_unpriced = [w for w in notes if 'drilling is not priced' in w.lower()]
    if drill_unpriced:
        add('warn', 'Drilling not priced in the plan',
            'The offline v3 run does not price drilling; holes are left to end mills or unreached, so '
            'hole time is not in the cycle time.', {'source': 'v3', 'warning': drill_unpriced[0]})
    predicted = [w for w in notes if 'predicted stock' in w.lower()]
    if predicted:
        add('warn', 'Later setups planned on predicted stock',
            'Setups after the first are costed against v3\'s predicted remaining stock, not measured '
            'stock — times for those setups are less certain.', {'source': 'v3', 'warning': predicted[0]})
    # per-hole notes from v3 (e.g. undersize drill that leaves stock to open out)
    noted = [h for h in holes if h.get('notes')]
    if noted:
        uniq = sorted({n for h in noted for n in h['notes']})
        add('warn', f'{len(noted)} hole{"s" if len(noted) != 1 else ""} need a second operation',
            '; '.join(uniq[:3]) + (f' (+{len(uniq) - 3} more)' if len(uniq) > 3 else ''),
            {'holes': len(noted), 'notes': uniq})

    counts = {s: sum(1 for f in findings if f['severity'] == s) for s in ('block', 'warn', 'ok')}

    # Face-level categories (geometry from the STEP + v3 part-level regions)
    categories, face_count, geom_error = [], None, None
    if geometry is not None:
        try:
            categories = dfm_geometry.categories(geometry, v3)
            face_count = geometry.get('face_count')
        except Exception as e:                       # never break /dfm on a geometry bug
            geom_error = f'{type(e).__name__}: {e}'
    elif v3:
        categories = dfm_geometry.categories({'faces': [], 'edges': []}, v3)
    face_counts = {s: sum(1 for c in categories for it in c['items'] if it['severity'] == s)
                   for s in ('block', 'warn', 'info')}

    if counts['block']:
        verdict = 'Not manufacturable as-is on 3-axis'
    elif face_counts['block']:
        verdict = 'Manufacturable on 3-axis after design changes'
    elif counts['warn'] or face_counts['warn']:
        verdict = 'Manufacturable with notes'
    else:
        verdict = 'Manufacturable on 3-axis VMC'
    order = {'block': 0, 'warn': 1, 'ok': 2}
    findings.sort(key=lambda f: order[f['severity']])
    return {
        'source': 'v3',
        'setups_needed': setups,
        'unreachable_mm3': unreach,
        'directions': v3.get('directions') or [],
        'findings': findings,
        'forced_small_tools': small,
        'holes': holes,
        'engine_notes': notes,
        'face_count': face_count,
        'categories': categories,
        'geometry_error': geom_error,
        'summary': {'verdict': verdict, 'counts': counts, 'face_level_counts': face_counts,
                    'billet_mm': v3.get('billet_mm'), 'part_bbox_mm': v3.get('part_bbox_mm'),
                    'text': f"{verdict}: {counts['block']} blocker(s), {counts['warn']} warning(s), "
                            f"{counts['ok']} check(s) passed; face-level: {face_counts['block']} "
                            f"blocker(s), {face_counts['warn']} warning(s), {face_counts['info']} note(s) "
                            f"in {len(categories)} categor{'y' if len(categories) == 1 else 'ies'}."},
        'thresholds': {
            'unreachable_noise_mm3': UNREACHABLE_NOISE_MM3, 'unreachable_block_mm3': UNREACHABLE_BLOCK_MM3,
            'unreachable_block_frac': UNREACHABLE_BLOCK_FRAC, 'setups_warn': SETUPS_WARN,
            'setups_block': SETUPS_BLOCK, 'small_tool_warn_mm': SMALL_TOOL_WARN_MM,
            'small_tool_block_mm': SMALL_TOOL_BLOCK_MM, 'hole_ddr_warn': HOLE_DDR_WARN,
            'hole_ddr_block': HOLE_DDR_BLOCK, 'removal_frac_warn': REMOVAL_FRAC_WARN,
            'face_level': dfm_geometry.thresholds(),
        },
    }
