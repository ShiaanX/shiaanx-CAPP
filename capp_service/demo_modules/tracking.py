"""
tracking.py — "the program sent to the machine" vs "what the machine actually did".

planned = the real NC program that ran, parsed with the repo's closed_loop.parse_tap:
          programmed spindle S, dominant cutting feed F, and cut time = feed-move path
          length / feed (+ canned-cycle depth / feed). Rapids/tool changes excluded.
actual  = real machine telemetry, when it can be linked to this part:
          1. the Krishna closed-loop records (closed-loop repo krishna_metrics.json,
             InfluxDB cnc-data-v2 pulled per NC program): rpm_median, feed_median and
             cutting_s from machine_state (NOT the broken `cutting_time` field);
          2. a machine_data.json in the job / part folder (influx_job_linkage.py output).
          If neither exists the op's actual is null and `source.actual` says why.
          override_log.json / actual_process.json are NOT used as "actual": both are
          parsed from the same NC programs (they record CAPP-vs-program deltas), so they
          carry no information about machine behaviour.
qc      = the part's real final-inspection report (measured values vs drawing tolerance),
          i.e. what actually came off the machine.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

from . import file_cache, part_data

RPM_FLAG_PCT = 15     # same threshold as closed_loop.py: |actual − planned| / planned
FEED_FLAG_PCT = 15
TIME_FLAG_PCT = 30    # cutting time vs NC path-length estimate

CLOSED_LOOP_METRICS = [
    Path(r'C:\Users\Siddhant Gupta\Documents\closed-loop') / 'krishna_metrics.json',
    part_data.REPO_ROOT / 'krishna_metrics.json',
]

_closed_loop = None


def _cl():
    global _closed_loop
    if _closed_loop is None:
        spec = importlib.util.spec_from_file_location('_repo_closed_loop', part_data.REPO_ROOT / 'closed_loop.py')
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        # parse_tap is pure-Python and ~0.25 s per .tap; cache each file's parse by mtime so
        # /tracking, /quote and /production-history don't re-parse the same NC programs.
        _parse = mod.parse_tap
        mod.parse_tap = lambda path: file_cache.memo(f'parse_tap:{Path(path)}', [Path(path)],
                                                    lambda: _parse(Path(path)))
        _closed_loop = mod
    return _closed_loop


def _setup_no(label: str) -> int:
    m = re.match(r'(\d+)', label.strip())
    return int(m.group(1)) if m else 999


def _minutes(pg: dict) -> float | None:
    s = (pg.get('est_cut_s') or 0) + (pg.get('est_drill_s') or 0)
    return round(s / 60, 2) if s else None


def _dev(field, p, a, thr):
    if p in (None, 0) or a is None:
        return None
    pct = round((a - p) / p * 100, 1)
    return {'field': field, 'planned': p, 'actual': a, 'pct': pct, 'flag': abs(pct) > thr}


def _op(name, tool, setup, planned, actual, extra_note=''):
    devs = []
    if actual:
        for d in (_dev('rpm', planned.get('rpm'), actual.get('rpm'), RPM_FLAG_PCT),
                  _dev('feed_mm_min', planned.get('feed_mm_min'), actual.get('feed_mm_min'), FEED_FLAG_PCT),
                  _dev('minutes', planned.get('minutes'), actual.get('minutes'), TIME_FLAG_PCT)):
            if d:
                devs.append(d)
        flagged = any(d['flag'] for d in devs)
        note = '; '.join(f"{d['field']} {d['pct']:+.0f}%" for d in devs if d['flag']) or 'ran as programmed'
    else:
        flagged, note = False, 'no machine record for this op'
    if extra_note:
        note = f'{note}; {extra_note}'
    return {'op': name, 'tool': tool, 'setup': setup, 'planned': planned, 'actual': actual,
            'deviations': devs, 'flagged': flagged, 'note': note}


# ── Source A: Krishna closed-loop telemetry records ────────────────────────

def _closed_loop_records(job_dir: Path):
    cands = {part_data.norm(n) for n in part_data.job_name_candidates(job_dir)}
    for path in CLOSED_LOOP_METRICS:
        if not path.exists():
            continue
        try:
            d = json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            continue
        for p in d.get('machined_parts', []):
            if part_data.norm(p.get('part_id')) in cands:
                return p, path
    return None, None


def _from_closed_loop(part, path):
    pl = part['payload']
    src = pl.get('source', {})
    ops = []
    for r in pl['closed_loop']['records']:
        pg, a, t = r.get('programmed') or {}, r.get('actual'), r.get('tool') or {}
        planned = {'rpm': pg.get('S'), 'feed_mm_min': pg.get('F_cut'), 'minutes': _minutes(pg)}
        actual = None
        if a:
            actual = {'rpm': a.get('rpm_median'), 'feed_mm_min': a.get('feed_median'),
                      'minutes': round(a['cutting_s'] / 60, 2) if a.get('cutting_s') is not None else None,
                      'cycles': a.get('cycles'), 'alarms': a.get('alarms'), 'feed_override': a.get('feed_override')}
        extra = ''
        if a and (a.get('cycles') or 1) > 1:
            extra = f"ran {a['cycles']}× (actual minutes cover all cycles)"
        dia = t.get('dia_mm')
        ops.append({**_op(r.get('cam_file') or r.get('operation'),
                          f"Ø{dia:g} mm {(t.get('type') or 'tool').upper()}" if dia else (t.get('type') or 'tool'),
                          (r.get('setup') or {}).get('id'), planned, actual, extra),
                    'nc_file': r.get('cam_file')})
    source = {
        'planned': 'NC programs sent to the machine (programmed S/F; minutes = toolpath length / feed)',
        'actual': (f"Machine telemetry, InfluxDB {src.get('bucket')} · factory {src.get('factory_id')} · machine "
                   f"{src.get('machine_id')} · {src.get('range_start')} → {src.get('range_stop')} "
                   '(rpm/feed medians per program; cutting minutes from machine_state, not cutting_time)'),
        'actual_record': str(path),
        'telemetry_linked': True,
    }
    return ops, source


# ── Source B: part-folder NC programs (+ machine_data.json if present) ─────

def _machine_data(job_dir: Path, part_dir: Path | None) -> dict:
    """influx_job_linkage.py output -> {program_name_lower: {rpm, feed_mm_min, minutes}}."""
    for d in (job_dir, part_dir):
        if d is None or not (d / 'machine_data.json').exists():
            continue
        try:
            md = json.loads((d / 'machine_data.json').read_text(encoding='utf-8'))
        except Exception:
            continue
        out = {}
        for prog in md.get('programs', []) if isinstance(md, dict) else []:
            name = str(prog.get('program_name') or '').lower()
            if name:
                out[name] = {'rpm': prog.get('rpm_median'), 'feed_mm_min': prog.get('feed_median'),
                             'minutes': round(prog['cutting_s'] / 60, 2) if prog.get('cutting_s') else None}
        if out:
            return out
    return {}


def _from_nc(nc_dir: Path, job_dir: Path, part_dir: Path):
    cl = _cl()
    md = _machine_data(job_dir, part_dir)
    ops = []
    for setting in sorted((d for d in nc_dir.iterdir() if d.is_dir()), key=lambda d: _setup_no(d.name)):
        taps = sorted(setting.glob('*.tap'), key=lambda p: (int(m.group(1)) if (m := re.match(r'(\d+)_', p.name)) else 0, p.name))
        for tap in taps:
            r = cl.parse_tap(tap)
            pg, t = r['programmed'], r['tool']
            planned = {'rpm': pg.get('S'), 'feed_mm_min': pg.get('F_cut'), 'minutes': _minutes(pg)}
            actual = md.get(tap.name.lower()) or md.get(r['toolpath'].lower())
            dia = t.get('dia_mm')
            ops.append({**_op(r['toolpath'], f"Ø{dia:g} mm {(t.get('type') or 'tool').upper()}" if dia else 'tool',
                              _setup_no(setting.name), planned, actual),
                        'nc_file': f'{setting.name}/{tap.name}'})
    linked = bool(md)
    source = {
        'planned': f"NC programs sent to the machine: {part_data.rel_to_repo(nc_dir)} "
                   '(programmed S/F; minutes = toolpath length / feed, rapids & tool changes excluded)',
        'actual': ('Machine telemetry from machine_data.json (influx_job_linkage.py)' if linked else
                   'No machine-run record linked to this part: it ran on a machine with no InfluxDB linkage, '
                   'so per-op actuals are not available. override_log.json / actual_process.json are parsed '
                   'from these same NC programs, so they are not used as "actual". The real outcome is the '
                   'QC result below.'),
        'telemetry_linked': linked,
    }
    return ops, source


# ── QC outcome (real inspection report) ────────────────────────────────────

_NUMS = re.compile(r'\d+(?:\.\d+)?')


def _qc(part_dir: Path | None) -> dict | None:
    chars = part_data.load_inspection_characteristics(part_dir)
    if not chars:
        return None
    items = []
    for c in chars:
        if c['kind'] == 'visual':
            items.append({'sl_no': c['sl_no'], 'description': c['description'], 'kind': 'visual',
                          'measured': c['observations'], 'in_tolerance': None, 'remark': c.get('remark')})
            continue
        vals = [float(v) for o in c['observations'] for v in _NUMS.findall(str(o))]
        lo, hi = c['nominal_mm'] - c['lower_tol_mm'], c['nominal_mm'] + c['upper_tol_mm']
        ok = all(lo - 1e-9 <= v <= hi + 1e-9 for v in vals) if vals else None
        worst = max((abs(v - c['nominal_mm']) for v in vals), default=None)
        items.append({'sl_no': c['sl_no'], 'description': c['description'].replace('\ufffd', 'Ø'),
                      'kind': c['kind'], 'nominal_mm': c['nominal_mm'],
                      'tol_mm': [-c['lower_tol_mm'], c['upper_tol_mm']], 'measured': vals,
                      'in_tolerance': ok, 'worst_dev_mm': round(worst, 3) if worst is not None else None,
                      'remark': c.get('remark')})
    dims = [i for i in items if i['kind'] != 'visual' and i['in_tolerance'] is not None]
    return {'source': f'{part_dir.name}/Inspection Report (shop final inspection, drawing tolerances)',
            'dimensions': len(dims), 'in_tolerance': sum(1 for i in dims if i['in_tolerance']),
            'items': items}


def build(job_dir: Path) -> dict:
    part_dir = part_data.find_part_dir(job_dir)
    rec, rec_path = _closed_loop_records(job_dir)
    if rec is not None:
        ops, source = _from_closed_loop(rec, rec_path)
    else:
        if part_dir is None:
            return {'status': 'ok', 'available': False,
                    'reason': 'No manufactured-part folder or telemetry record matches this job'}
        nc_dir = part_data.find_ncprograms_dir(part_dir)
        if nc_dir is None:
            return {'status': 'ok', 'available': False, 'part_folder': part_dir.name,
                    'reason': f"No NC programs ('<Nth> setting/*.tap') or machine telemetry recorded for {part_dir.name}"}
        ops, source = _from_nc(nc_dir, job_dir, part_dir)

    with_actual = [o for o in ops if o['actual']]

    def tot(rows, side):
        v = [(o[side] or {}).get('minutes') for o in rows]
        v = [x for x in v if x is not None]
        return round(sum(v), 2) if v else None

    qc = _qc(part_dir)
    return {
        'status': 'ok',
        'available': True,
        'actual_available': bool(with_actual),
        'part_folder': part_dir.name if part_dir else None,
        'source': source,
        'thresholds_pct': {'rpm': RPM_FLAG_PCT, 'feed_mm_min': FEED_FLAG_PCT, 'minutes': TIME_FLAG_PCT},
        'ops': ops,
        'summary': {
            'ops': len(ops),
            'ops_with_actual': len(with_actual),
            'flagged': sum(o['flagged'] for o in ops),
            'planned_minutes': tot(ops, 'planned'),
            'actual_minutes': tot(with_actual, 'actual'),
            'planned_minutes_same_ops': tot(with_actual, 'planned') if with_actual else None,
            'qc_in_tolerance': f"{qc['in_tolerance']}/{qc['dimensions']}" if qc else None,
        },
        'qc': qc,
    }
