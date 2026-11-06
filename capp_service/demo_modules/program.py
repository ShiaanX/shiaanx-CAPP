"""
program.py — the AI-generated process plan and CAM program for a job's part (Rohit's v3 planner).

plan          = the cached v3 analysis for the job (v3_cache, same face order /quote uses via
                part_data.V3_FACE_ORDER): setups, tools per setup, v3 total, tool changes, and the
                quoted ATC cycle (quote.cycle_minutes: v3 cutting + tool changes x rates.tool_change_s).
live_program  = the real PowerMill program from a live v3 run, for parts that have one (LIVE_RUNS):
                - live_events.ndjson (v3 --emit-events, schema shiaanx.events/1): toolpaths, stages,
                  tools, cutting params, per-setup vise/grip and stock block, billet, run timings;
                - the saved PowerMill project (read-only, via repo pml_project.py + each toolpath
                  entity's "TotalTime"): strategy, workplane, feeds, PowerMill-computed time.
                The backup folder is never written to.
approval      = <job_dir>/program_approval.json ({by, at}), written by POST .../program/approve.
"""

from __future__ import annotations

import importlib.util
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from . import file_cache, part_data

BACKUP_ROOT = part_data.REPO_ROOT / 'demo_backup'
LIVE_RUNS = {
    'motormount': {
        'folder': BACKUP_ROOT / 'v3_motor_mount',
        'project': 'pm_project_final_all_3_setups',            # the project the run finished in
        'read_project': 'pm_project_final_PRISTINE_copy',       # identical read-only copy we decode
    },
}
APPROVAL_NAME = 'program_approval.json'
IMAGE_EXT = {'.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.bmp'}

STAGE_ROLE = {
    'FACE': 'face', 'RESTROUGH': 'rough', 'ROUGH': 'rough', 'SEMI': 'semi-finish',
    'FINSTEEP': 'finish (steep walls)', 'FINFLAT': 'finish (flat floors)', 'FINSHALLOW': 'finish (shallow)',
    'FIN3D': 'finish (3D offset)', 'FINSS': 'finish (steep & shallow)',
    'SIZED': 'size feature', 'SIZEDFIN': 'size feature (finish)', 'CORNER': 'corner finish',
}

_pml = None


def _pml_project():
    global _pml
    if _pml is None:
        spec = importlib.util.spec_from_file_location('_repo_pml_project', part_data.REPO_ROOT / 'pml_project.py')
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _pml = mod
    return _pml


def _rel(p: Path) -> str:
    try:
        return p.relative_to(part_data.REPO_ROOT).as_posix()
    except ValueError:
        return p.as_posix()


def _r(v, n=2):
    return round(v, n) if isinstance(v, (int, float)) else v


def part_key_for_job(job_dir: Path) -> str | None:
    pd = part_data.find_part_dir(job_dir)
    keys = set(part_data._part_keys(pd)) if pd else set()
    keys |= {part_data.norm(n) for n in part_data.job_name_candidates(job_dir)}
    for k in sorted(keys):
        if k in LIVE_RUNS:
            return k
    for k in sorted(keys):
        if k in part_data.V3_FACE_ORDER:
            return k
    return part_data.norm(pd.name) if pd else None


# ── plan (v3 cache) ─────────────────────────────────────────────────────────

def plan_from_v3(v3: dict) -> dict:
    from . import quote
    p = v3.get('plan') or {}
    setups = [{'dir': s.get('dir'), 'workplane': s.get('workplane'), 'minutes': s.get('minutes'),
               'cutting_minutes': s.get('cutting_minutes'), 'tool_change_minutes': s.get('tool_change_minutes'),
               'tool_changes': s.get('tool_changes'), 'stock': s.get('stock'),
               'jaw_reach_mm': _r(s.get('jaw_reach_mm'), 1), 'left_mm3': s.get('left_mm3')}
              for s in p.get('setups') or []]
    try:
        cyc = quote.cycle_minutes(v3) if p.get('total_minutes') else None
    except Exception:
        cyc = None
    return {
        'setups': setups,
        'tools': p.get('tools') or [],
        'total_minutes': p.get('total_minutes'),
        'cutting_minutes': p.get('cutting_minutes'),
        'tool_change_minutes': p.get('tool_change_minutes'),
        'tool_change_min_each': p.get('tool_change_min_each'),
        'tool_changes': p.get('tool_changes'),
        'cycle_minutes_atc': cyc['total_minutes'] if cyc else None,
        'cycle_basis': ('v3 cutting minutes + tool_changes x rates.json tool_change_s (shop ATC), '
                        'quote.cycle_minutes(); total_minutes is v3\'s own figure at '
                        f"{p.get('tool_change_min_each')} min per manual tool change") if cyc else None,
        'billet_mm': v3.get('billet_mm'),
        'part_bbox_mm': v3.get('part_bbox_mm'),
        'requested_faces': v3.get('requested_faces'),
        'face_order_source': v3.get('face_order_source'),
        'warnings': v3.get('warnings') or [],
    }


# ── live PowerMill run ──────────────────────────────────────────────────────

def _events(path: Path) -> list[dict]:
    out = []
    with path.open(encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return out


def _clock_s(c: str | None) -> int | None:
    m = re.match(r'(\d+):(\d+):(\d+)', c or '')
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) if m else None


def _pm_times(project_dir: Path) -> dict:
    """toolpath name (lower) -> PowerMill 'TotalTime' (min) from each toolpath entity's JSON header."""
    out = {}
    for prj in project_dir.glob('*.pmlprj'):
        for line in prj.read_text(errors='ignore').splitlines():
            m = re.match(r"\s*(x[0-9a-f]+)\.pmlent\s+pmlEntToolpath\s+'([^']*)'", line)
            if not m:
                continue
            f = project_dir / f'{m.group(1)}.pmlent'
            if not f.exists():
                continue
            t = re.search(r'"TotalTime"\s*:\s*"([-\d.eE+]+)"', f.read_bytes().decode('latin1'))
            if t:
                out[m.group(2).lower()] = float(t.group(1))
    return out


def _images(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob('*') if p.is_file() and p.suffix.lower() in IMAGE_EXT)


def image_path(key: str | None, name: str) -> Path | None:
    """Resolve an image by its listed name, only from inside that part's live-run folder."""
    run = LIVE_RUNS.get(key or '')
    if not run or not name or '..' in name.replace('\\', '/').split('/'):
        return None
    root = run['folder'].resolve()
    for p in _images(run['folder']):
        rp = p.resolve()
        if p.relative_to(run['folder']).as_posix() == name and root in rp.parents:
            return rp
    return None


def _live_inputs(run: dict) -> list[Path]:
    """Files live_program reads: events, manifest, and the decoded project's .pmlprj/.pmlent."""
    folder = run['folder']
    proj = folder / run['read_project']
    files = [folder / 'live_events.ndjson', folder / 'run_folder' / 'run_manifest.json']
    if proj.exists():
        files += sorted(proj.glob('*.pmlprj')) + sorted(proj.glob('*.pmlent'))
    files += _images(folder)
    return files


LIVE_SNAPSHOT_NAME = 'live_program_snapshot.json'


def _load_snapshot(key: str | None):
    """(live, notes) from <part folder>/live_program_snapshot.json (the data pack), or None."""
    for d in part_data.part_dirs():
        f = d / LIVE_SNAPSHOT_NAME
        if not f.exists():
            continue
        try:
            data = file_cache.memo(f'live_snapshot:{f}', [f], lambda f=f: json.loads(f.read_text(encoding='utf-8')))
        except Exception:
            continue
        if data.get('part_key') == key and data.get('live'):
            return data['live'], list(data.get('notes') or [])
    return None


def write_live_snapshot(key: str, out_dir: Path) -> Path:
    """Freeze the live-run decode (events + decoded PowerMill project) into the data pack.
    Run on the machine that has the run folder; the server then needs neither it nor PowerMill."""
    live, notes = _live_program(key)
    if not live:
        raise RuntimeError('; '.join(notes) or f'no live run for {key}')
    out = Path(out_dir) / LIVE_SNAPSHOT_NAME
    out.write_text(json.dumps({'part_key': key, 'written_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                               'live': live, 'notes': notes}, indent=1, ensure_ascii=False), encoding='utf-8')
    return out


def live_program(key: str | None) -> tuple[dict | None, list[str]]:
    """Cached per run folder until the events file, manifest or decoded project changes."""
    run = LIVE_RUNS.get(key or '')
    if not run:
        return _live_program(key)
    snap = _load_snapshot(key)
    if snap is not None:
        live, notes = snap
        if not run['folder'].exists():
            notes = notes + [f"Live PowerMill run details are served from the saved snapshot "
                             f"({LIVE_SNAPSHOT_NAME}); the original run folder is not on this machine."]
        return live, notes
    live, notes = file_cache.memo(f"live_program:{run['folder']}", _live_inputs(run), lambda: _live_program(key))
    return live, notes


def _live_program(key: str | None) -> tuple[dict | None, list[str]]:
    notes = []
    run = LIVE_RUNS.get(key or '')
    if not run:
        return None, ['No live PowerMill run on record for this part: live_program is null. '
                      'The v3 plan above is the AI process plan; a CAM program is generated when the part '
                      'is run through v3 + PowerMill.']
    folder = run['folder']
    ev_path = folder / 'live_events.ndjson'
    if not ev_path.exists():
        return None, [f'Live run folder {folder} has no live_events.ndjson']
    ev = _events(ev_path)
    by_kind: dict[str, list] = {}
    for e in ev:
        by_kind.setdefault(e.get('kind'), []).append(e)

    params = {e['toolpath']: e for e in by_kind.get('cutting_params', [])}
    proj_read = folder / run['read_project']
    proj_path = folder / run['project']
    pm = {}
    pm_times = {}
    try:
        prjs = sorted(proj_read.glob('*.pmlprj'))
        if prjs:
            pm = (_pml_project().load_project(prjs[0]) or {}).get('toolpaths', {})
            pm_times = _pm_times(proj_read)
        else:
            notes.append(f'No .pmlprj in {proj_read}; PowerMill strategy/feeds not decoded')
    except Exception as e:
        notes.append(f'PowerMill project decode failed ({type(e).__name__}: {e}); event data only')

    # setup context
    hold = {e['direction']: e for e in by_kind.get('hold_plan', [])}
    opened = {e['setup']: e for e in by_kind.get('setup_open', [])}
    clamped = {e['setup']: e for e in by_kind.get('clamped_setup', [])}
    face_time = {e['direction']: e for e in by_kind.get('face_time', [])}
    checkpoints = {e.get('setup'): e for e in by_kind.get('checkpoint', []) if e.get('tag')}
    plans = {}
    for e in by_kind.get('plan', []):
        plans.setdefault(e['direction'], e)      # first plan per direction = the plan the setup opened with

    toolpaths, setups = [], []
    for n, s in enumerate(by_kind.get('setup_summary', []), start=1):
        d = s['direction']
        h = hold.get(d) or {}
        c = clamped.get(s['setup']) or {}
        o = opened.get(s['setup']) or {}
        ck = checkpoints.get(s['setup']) or {}
        ft = face_time.get(d) or {}
        t0, t1 = _clock_s(o.get('clock')), _clock_s(ck.get('clock'))
        tps_here = []
        for op in s['operations']:
            name = op['toolpath']
            pmt = pm.get(name.lower()) or {}
            cp = (params.get(name) or {}).get('params') or {}
            pm_total = pm_times.get(name.lower())
            ev_total = op.get('time')
            if pm_total is not None and ev_total is not None and abs(pm_total - ev_total) > 0.05:
                notes.append(f'{name}: PowerMill TotalTime {pm_total:.2f} min vs event {ev_total:.2f} min')
            rec = {
                'name': name, 'setup': n, 'setup_name': s['setup'], 'direction': d,
                'tool': op.get('tool'), 'stage': op.get('stage'),
                'role': STAGE_ROLE.get(op.get('stage'), (op.get('stage') or '').lower()),
                'strategy': pmt.get('strategy'), 'workplane': pmt.get('workplane') or o.get('workplane'),
                'rpm': cp.get('rpm'), 'feed_mm_min': cp.get('feed') or pmt.get('feed_cut'),
                'plunge_mm_min': cp.get('plunge') or pmt.get('feed_plunge'),
                'stepdown_mm': cp.get('stepdown'), 'stepover_mm': _r(cp.get('stepover')),
                'vc_m_min': cp.get('vc'), 'fz_mm': cp.get('fz'),
                'powermill_minutes': _r(pm_total if pm_total is not None else ev_total),
                'cutting_minutes': _r(op.get('cutting_time')), 'link_minutes': _r(op.get('link_time')),
                'removed_mm3': _r(op.get('removed'), 1),
            }
            tps_here.append(rec)
        toolpaths += tps_here
        grip = c.get('grip') or h
        blk = c.get('block') or {}
        setups.append({
            'setup': n, 'name': s['setup'], 'direction': d, 'workplane': o.get('workplane') or h.get('workplane'),
            'toolpaths': len(tps_here),
            'tools': sorted({t['tool'] for t in tps_here if t['tool']}),
            'powermill_minutes': _r(s.get('total_minutes'), 1),
            'powermill_cutting_minutes': _r(sum(t['cutting_minutes'] or 0 for t in tps_here), 1),
            'v3_planned_minutes': ft.get('planned_cut'),
            'tool_changes': ft.get('changes'), 'v3_planned_tool_changes': ft.get('planned_changes'),
            'removed_mm3': _r(s.get('total_removed_mm3'), 1),
            'vise': {
                'level': c.get('level'), 'grip_axis': grip.get('grip_axis'), 'grip_axis_why': grip.get('grip_axis_why'),
                'grip_depth_mm': grip.get('grip_depth_mm'), 'jaw_gap_mm': _r(grip.get('jaw_gap_mm')),
                'jaw_reach_mm': _r(grip.get('jaw_reach_mm')), 'clamp_clearance_mm': h.get('clamp_clearance_mm'),
                'max_tool_dia_mm': h.get('max_tool_dia_mm'), 'held_on': grip.get('source'),
            },
            'stock_block_mm': {k: _r(v) for k, v in blk.items() if k in ('XMin', 'XMax', 'YMin', 'YMax', 'ZMin', 'ZMax')} or None,
            'first_planned_tools': (plans.get(d) or {}).get('tools'),
            'wall_minutes': round((t1 - t0) / 60, 1) if t0 is not None and t1 is not None else None,
            'started': o.get('clock'), 'finished': ck.get('clock'),
        })

    start = (by_kind.get('process_start') or [{}])[0]
    end = (by_kind.get('run_end') or [{}])[0]
    run_min = None
    if isinstance(start.get('t'), (int, float)) and isinstance(end.get('t'), (int, float)):
        run_min = round((end['t'] - start['t']) / 60, 1)
    geo = (by_kind.get('geometry') or [{}])[0]
    allow = (by_kind.get('allowance') or [{}])[0]
    fin = (by_kind.get('end') or [{}])[0]
    imp = (by_kind.get('import') or [{}])[0]
    bbox = geo.get('bbox') or {}
    per_face = allow.get('per_face') or {}
    billet = None
    if bbox:
        billet = {
            'size_mm': [_r(bbox['size_x'] + per_face.get('+X', 0) + per_face.get('-X', 0)),
                        _r(bbox['size_y'] + per_face.get('+Y', 0) + per_face.get('-Y', 0)),
                        _r(bbox['size_z'] + per_face.get('+Z', 0) + per_face.get('-Z', 0))],
            'allowance_mm_per_face': per_face, 'volume_mm3': allow.get('billet_mm3'),
            'part_bbox_mm': [bbox.get('size_x'), bbox.get('size_y'), bbox.get('size_z')],
            'part_volume_mm3': geo.get('part_volume_mm3'),
        }
    manifest = folder / 'run_folder' / 'run_manifest.json'
    man = json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else {}
    imgs = _images(folder)
    if not imgs:
        notes.append('The live run saved no setup/toolpath images (no PNG/JPG/SVG anywhere in the run '
                     'backup); images[] is empty.')
    total_pm = round(sum(s['powermill_minutes'] or 0 for s in setups), 1)
    dropped = by_kind.get('toolpath_dropped', []) + by_kind.get('toolpath_discarded', [])
    return {
        'available': True,
        'run': man.get('run') or (by_kind.get('run_start') or [{}])[0].get('run'),
        'status': man.get('status') or end.get('why'),
        'toolpaths': toolpaths,
        'setups': setups,
        'powermill_cutting_minutes_total': total_pm,
        'powermill_minutes_basis': "PowerMill-computed toolpath time ('TotalTime': cutting + links/leads at "
                                   'programmed feeds, rapids at the run\'s 3500 mm/min) summed per setup; '
                                   'tool changes and load/unload excluded. Pure cutting-move time is '
                                   'setups[].powermill_cutting_minutes.',
        'powermill_pure_cutting_minutes_total': round(sum(s['powermill_cutting_minutes'] or 0 for s in setups), 1),
        'toolpaths_tried': len(by_kind.get('cutting_params', [])),
        'toolpaths_dropped_or_empty': len({e.get('toolpath') for e in dropped}),
        'billet': billet,
        'final_stock_above_part_mm3': _r(man.get('above_target_mm3') or (fin.get('final_stock_mm3', 0) - geo.get('part_volume_mm3', 0)), 1),
        'run_minutes': run_min,
        'run_started': start.get('clock'), 'run_finished': end.get('clock'),
        'step_import_seconds': imp.get('wall_s'),
        'v3_args': start.get('argv'),
        'project_path': _rel(proj_path),
        'project_decoded_from': _rel(proj_read),
        'images': [{'name': p.relative_to(folder).as_posix(),
                    'url': f"image/{p.relative_to(folder).as_posix()}"} for p in imgs],
        'sources': [_rel(ev_path), _rel(manifest) if manifest.exists() else None,
                    f"{_rel(proj_read)} (pml_project.py + toolpath 'TotalTime')"],
    }, notes


# ── approval ───────────────────────────────────────────────────────────────

def load_approval(job_dir: Path) -> dict | None:
    p = job_dir / APPROVAL_NAME
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding='utf-8'))
        return {'by': d.get('by'), 'at': d.get('at')}
    except Exception:
        return None


def approve(job_dir: Path, by: str) -> dict:
    rec = {'by': by.strip(), 'at': datetime.now(timezone.utc).isoformat(timespec='seconds')}
    (job_dir / APPROVAL_NAME).write_text(json.dumps(rec, indent=2), encoding='utf-8')
    return rec


# ── response ───────────────────────────────────────────────────────────────

def build(job_dir: Path, v3_state: str, v3: dict | None) -> dict:
    key = part_key_for_job(job_dir)
    pd = part_data.find_part_dir(job_dir)
    notes = []
    plan = None
    if v3_state == 'ready' and v3:
        plan = plan_from_v3(v3)
    else:
        notes.append(f'v3 plan not ready (state: {v3_state}); plan is null. '
                     + (f"Detail: {v3.get('error') or v3.get('reason')}" if v3 and (v3.get('error') or v3.get('reason')) else ''))
    live, live_notes = live_program(key)
    notes += live_notes
    if plan and live:
        notes.append(f"v3 plan (before PowerMill): {plan['total_minutes']} min with 15-min manual tool changes, "
                     f"{plan['cycle_minutes_atc']} min quoted with ATC. PowerMill's computed time for the real "
                     f"program: {live['powermill_cutting_minutes_total']} min (incl. link moves, excl. tool changes).")
    return {
        'status': 'ok' if plan else v3_state,
        'part': pd.name if pd else None,
        'part_key': key,
        'source': {
            'plan': (f"v3 analysis cache {_rel(job_dir / 'v3_analysis.json')} "
                     f"(v3_origin={v3.get('v3_origin')}, faces={v3.get('requested_faces')})") if plan else None,
            'live_run': (', '.join(s for s in live['sources'] if s)) if live else None,
        },
        'approved': load_approval(job_dir),
        'plan': plan,
        'live_program': live,
        'notes': notes,
    }
