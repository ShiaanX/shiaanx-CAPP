"""
v3_runs.py — planner console runs: list them, summarise any of them, publish one for an app.

A run made in the planner console (Rohit's console, spawning job.py) leaves a folder
    <V3_ROOT>/database_runtime/<PART>_<yyyymmdd_hhmmss>/
        run_manifest.json        status, argv, settings, setups_machined, stock/volume figures
        logs/journal.json        the event stream (same events as --emit-events: setup_summary,
                                 cutting_params, hold_plan, clamped_setup, checkpoint ...)
        checkpoints/after_<S>/   PowerMill project saved after each setup (cumulative toolpaths)
        pm_session/              the live PowerMill session project
Everything here is read-only: nothing is ever written under V3_ROOT and PowerMill is not run.

summarize_run(name) returns the same `live_program` dict shape program.py serves. When Rohit edits
toolpaths in PowerMill and saves, the newest saved project is the source of strategy, feeds and
PowerMill times; toolpaths added or deleted there show up (listed under edited_toolpaths).

Published runs (what the dev server shows): POST /jobs/{id}/program/publish stores one summary per
part under <published dir>/<part_key>.json; program.live_program prefers it over any snapshot.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import file_cache, part_data

RUN_NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.\-]{0,120}$')
RUN_TS_RE = re.compile(r'^(?P<part>.+)_(?P<ts>\d{8}_\d{6})$')
MAX_PUBLISH_BYTES = 2 * 1024 * 1024
MAX_TOOLPATHS = 3000

STAGE_ROLE = {
    'FACE': 'face', 'RESTROUGH': 'rough', 'ROUGH': 'rough', 'SEMI': 'semi-finish',
    'FINSTEEP': 'finish (steep walls)', 'FINFLAT': 'finish (flat floors)', 'FINSHALLOW': 'finish (shallow)',
    'FIN3D': 'finish (3D offset)', 'FINSS': 'finish (steep & shallow)',
    'SIZED': 'size feature', 'SIZEDFIN': 'size feature (finish)', 'CORNER': 'corner finish',
}
IMAGE_EXT = {'.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.bmp'}

UNAVAILABLE_MSG = ('Planner console runs are only on the planning laptop; this environment has no '
                   'planner installed. Open this page from the planning laptop to publish a run.')

_pml = None


# ── helpers shared with program.py ──────────────────────────────────────────

def _pml_project():
    global _pml
    if _pml is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location('_repo_pml_project', part_data.REPO_ROOT / 'pml_project.py')
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _pml = mod
    return _pml


def _r(v, n=2):
    return round(v, n) if isinstance(v, (int, float)) else v


def rel(p: Path) -> str:
    try:
        return p.relative_to(part_data.REPO_ROOT).as_posix()
    except ValueError:
        return p.as_posix()


def read_events(path: Path) -> list[dict]:
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


def _clk(e: dict | None) -> str | None:
    """Wall-clock 'HH:MM:SS' of an event: ndjson has `clock`, the run journal keeps it in `t`."""
    if not e:
        return None
    if isinstance(e.get('clock'), str):
        return e['clock']
    return e['t'] if isinstance(e.get('t'), str) else None


def _clock_s(c: str | None) -> int | None:
    m = re.match(r'(\d+):(\d+):(\d+)', c or '')
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) if m else None


def pm_times(project_dir: Path) -> dict:
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


def images_in(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob('*') if p.is_file() and p.suffix.lower() in IMAGE_EXT)


# ── the generic builder (events + a decoded PowerMill project -> live_program dict) ──

def build_live(ev: list[dict], *, man: dict, proj_read: Path | None, proj_path_label: str,
               proj_read_label: str, sources: list, images: list | None = None,
               reconcile: bool = False) -> tuple[dict | None, list[str]]:
    """Build the live_program dict. `images` None = this run kind has no image store (no note).
    `reconcile` True: the project is the source of truth for which toolpaths exist, so toolpaths
    added/deleted in PowerMill since the run log was written are applied."""
    notes: list[str] = []
    by_kind: dict[str, list] = {}
    for e in ev:
        by_kind.setdefault(e.get('kind'), []).append(e)

    params = {e['toolpath']: e for e in by_kind.get('cutting_params', [])}
    pm: dict = {}
    pm_t: dict = {}
    if proj_read is not None:
        try:
            prjs = sorted(proj_read.glob('*.pmlprj'))
            if prjs:
                pm = (_pml_project().load_project(prjs[0]) or {}).get('toolpaths', {})
                pm_t = pm_times(proj_read)
            else:
                notes.append(f'No .pmlprj in {proj_read}; PowerMill strategy/feeds not decoded')
        except Exception as e:
            notes.append(f'PowerMill project decode failed ({type(e).__name__}: {e}); event data only')

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
        t0, t1 = _clock_s(_clk(o)), _clock_s(_clk(ck))
        tps_here = []
        for op in s['operations']:
            name = op['toolpath']
            pmt = pm.get(name.lower()) or {}
            cp = (params.get(name) or {}).get('params') or {}
            pm_total = pm_t.get(name.lower())
            ev_total = op.get('time')
            if pm_total is not None and ev_total is not None and abs(pm_total - ev_total) > 0.05:
                notes.append(f'{name}: PowerMill TotalTime {pm_total:.2f} min vs event {ev_total:.2f} min')
            tps_here.append({
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
            })
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
            'wall_minutes': round((t1 - t0) / 60, 1) if t0 is not None and t1 is not None and t1 >= t0 else None,
            'started': _clk(o), 'finished': _clk(ck),
        })

    edited = _reconcile(toolpaths, setups, pm, pm_t, notes) if (reconcile and pm) else []
    if not toolpaths:
        return None, notes + ['This planner run has no finished setup yet (no toolpaths in its log).']

    start = (by_kind.get('process_start') or [{}])[0]
    end = (by_kind.get('run_end') or [{}])[0]
    run_min = None
    if isinstance(start.get('t'), (int, float)) and isinstance(end.get('t'), (int, float)):
        run_min = round((end['t'] - start['t']) / 60, 1)
    else:
        a = _clock_s(_clk((by_kind.get('run_start') or [None])[0]))
        b = _clock_s(_clk((by_kind.get('end') or [None])[0]))
        if a is not None and b is not None:
            run_min = round(((b - a) % 86400) / 60, 1)
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
    if images is not None and not images:
        notes.append('The live run saved no setup/toolpath images (no PNG/JPG/SVG anywhere in the run '
                     'backup); images[] is empty.')
    total_pm = round(sum(s['powermill_minutes'] or 0 for s in setups), 1)
    dropped = by_kind.get('toolpath_dropped', []) + by_kind.get('toolpath_discarded', [])
    above = man.get('above_target_mm3')
    if not above and fin.get('final_stock_mm3') is not None:
        above = fin.get('final_stock_mm3', 0) - geo.get('part_volume_mm3', 0)
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
        'final_stock_above_part_mm3': _r(above, 1),
        'run_minutes': run_min,
        'run_started': _clk((by_kind.get('run_start') or [None])[0]) or start.get('clock'),
        'run_finished': _clk((by_kind.get('end') or [None])[0]) or end.get('clock'),
        'step_import_seconds': imp.get('wall_s'),
        'v3_args': start.get('argv') or man.get('argv'),
        'project_path': proj_path_label,
        'project_decoded_from': proj_read_label,
        'edited_toolpaths': edited,
        'images': [{'name': p[0], 'url': p[1]} for p in (images or [])],
        'sources': sources,
    }, notes


def _reconcile(toolpaths: list, setups: list, pm: dict, pm_t: dict, notes: list) -> list[dict]:
    """Apply toolpaths added/deleted in PowerMill (project vs run log). Returns the edit list."""
    logged = {t['name'].lower() for t in toolpaths}
    edits = []
    for t in list(toolpaths):
        if t['name'].lower() not in pm:
            toolpaths.remove(t)
            edits.append({'toolpath': t['name'], 'change': 'deleted in PowerMill'})
    for key, pmt in pm.items():
        if key in logged:
            continue
        nm = pmt.get('name') or key
        si = next((s for s in setups if s['workplane'] and s['workplane'] == pmt.get('workplane')), None) or (setups[-1] if setups else None)
        if si is None:
            continue
        m = pm_t.get(key)
        toolpaths.append({
            'name': nm, 'setup': si['setup'], 'setup_name': si['name'], 'direction': si['direction'],
            'tool': None, 'stage': None, 'role': 'added in PowerMill', 'strategy': pmt.get('strategy'),
            'workplane': pmt.get('workplane'), 'rpm': None, 'feed_mm_min': pmt.get('feed_cut'),
            'plunge_mm_min': pmt.get('feed_plunge'), 'stepdown_mm': pmt.get('stepdown_mm'), 'stepover_mm': None,
            'vc_m_min': pmt.get('vc_m_min'), 'fz_mm': pmt.get('fz_mm'),
            'powermill_minutes': _r(m), 'cutting_minutes': None, 'link_minutes': None, 'removed_mm3': None,
        })
        edits.append({'toolpath': nm, 'change': 'added in PowerMill'})
    if edits:
        toolpaths.sort(key=lambda t: (t['setup'], 0))   # stable: keeps order inside a setup
        for s in setups:
            mine = [t for t in toolpaths if t['setup'] == s['setup']]
            s['toolpaths'] = len(mine)
            s['tools'] = sorted({t['tool'] for t in mine if t['tool']})
            s['powermill_minutes'] = _r(sum(t['powermill_minutes'] or 0 for t in mine), 1)
            s['powermill_cutting_minutes'] = _r(sum(t['cutting_minutes'] or 0 for t in mine), 1)
        notes.append('Toolpaths changed in PowerMill since the run log: '
                     + '; '.join(f"{e['toolpath']} {e['change']}" for e in edits[:12]))
    return edits


# ── run folders ─────────────────────────────────────────────────────────────

def runtime_root() -> Path:
    import v3_adapter
    return Path(v3_adapter._v3_root()) / 'database_runtime'


def disabled() -> bool:
    import v3_adapter
    return v3_adapter.v3_disabled()


def run_dir(name: str) -> Path | None:
    """The run folder for `name`, or None. `name` must be a bare folder name (no traversal)."""
    if not isinstance(name, str) or not RUN_NAME_RE.match(name) or '..' in name:
        return None
    root = runtime_root()
    p = root / name
    try:
        if not p.is_dir() or p.resolve().parent != root.resolve():
            return None
    except OSError:
        return None
    return p


def _read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return None


def _parse_ts(ts: str | None) -> str | None:
    try:
        return datetime.strptime(ts or '', '%Y%m%d_%H%M%S').isoformat(timespec='seconds')
    except ValueError:
        return None


def _run_info(p: Path) -> dict:
    man = _read_json(p / 'run_manifest.json') or {}
    m = RUN_TS_RE.match(p.name)
    part = m.group('part') if m else p.name
    argv = man.get('argv') or []
    planned = None
    if '--faces' in argv:
        try:
            planned = len([x for x in argv[argv.index('--faces') + 1].split(',') if x.strip()])
        except IndexError:
            pass
    journal = p / 'logs' / 'journal.json'
    return {
        'name': p.name, 'part': part, 'part_key': part_data.norm(part),
        'started': _parse_ts(man.get('started') or (m.group('ts') if m else None)),
        'updated': _parse_ts(man.get('updated')),
        'status': man.get('status') or 'unknown',
        'setups_done': len(man.get('setups_machined') or []),
        'setups_planned': planned,
        'has_log': journal.exists(),
        'usable': journal.exists() and (man.get('status') == 'finished' or bool(man.get('setups_machined'))),
    }


def list_runs(limit: int = 30) -> list[dict]:
    root = runtime_root()
    if not root.is_dir():
        return []
    runs = []
    for p in root.iterdir():
        if p.is_dir() and RUN_NAME_RE.match(p.name):
            try:
                runs.append(_run_info(p))
            except OSError:
                continue
    runs.sort(key=lambda r: (r['started'] or '', r['name']), reverse=True)
    return runs[:limit]


def _pick_project(d: Path) -> Path | None:
    """Newest saved PowerMill project of the run that holds toolpaths (checkpoints, then session)."""
    cands = list(d.glob('checkpoints/*/*.pmlprj')) + list(d.glob('pm_session/*.pmlprj'))
    cands.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    for f in cands:
        try:
            if (_pml_project().load_project(f) or {}).get('toolpaths'):
                return f.parent
        except Exception:
            continue
    return None


def _inputs(d: Path, proj: Path | None) -> list[Path]:
    files = [d / 'run_manifest.json', d / 'logs' / 'journal.json']
    if proj is not None:
        files += sorted(proj.glob('*.pmlprj')) + sorted(proj.glob('*.pmlent'))
    return files


def summarize_run(name: str) -> tuple[dict | None, list[str]]:
    """(live_program dict, notes) for any planner run folder; (None, [reason]) when not readable."""
    d = run_dir(name)
    if d is None:
        return None, [f'No planner run named {name!r}']
    journal = d / 'logs' / 'journal.json'
    if not journal.exists():
        return None, [f'Planner run {name} has no run log yet (it may still be starting).']
    proj = _pick_project(d)

    def compute():
        ev = _read_json(journal)
        if not isinstance(ev, list):
            return None, ['The run log could not be read.']
        man = _read_json(d / 'run_manifest.json') or {}
        live, notes = build_live(
            ev, man=man, proj_read=proj,
            proj_path_label=f'planner run {d.name} / {proj.parent.name}/{proj.name}' if proj else f'planner run {d.name}',
            proj_read_label=f'planner run {d.name}',
            sources=[f'planner run {d.name}: run_manifest.json, logs/journal.json',
                     (f'planner run {d.name}: {proj.parent.name}/{proj.name} (saved PowerMill project; '
                      f"strategy, feeds and 'TotalTime' per toolpath)") if proj else None],
            images=None, reconcile=True)
        if live is not None:
            info = _run_info(d)
            live['run_name'] = d.name
            live['run_started_at'] = info['started']
            live['run_updated_at'] = info['updated']
            live['project_saved_at'] = (datetime.fromtimestamp(max(f.stat().st_mtime for f in proj.glob('*.pmlprj')))
                                        .isoformat(timespec='seconds')) if proj else None
            live['status'] = live.get('status') or info['status']
        return live, notes

    return file_cache.memo(f'v3_run:{d}', _inputs(d, proj), compute)


def latest_finished_for(part_key: str | None) -> str | None:
    """Newest finished run for a part (laptop only)."""
    if not part_key or disabled():
        return None
    for r in list_runs(60):
        if r['part_key'] == part_key and r['status'] == 'finished' and r['has_log']:
            return r['name']
    return None


# ── published runs (one per part) ───────────────────────────────────────────

def published_dir() -> Path:
    env = os.environ.get('CAPP_PUBLISHED_DIR')
    if env:
        return Path(env)
    jobs = os.environ.get('CAPP_JOBS_DIR')
    if jobs:
        return Path(jobs).parent / 'published_runs'
    return part_data.DATA_DIR / 'published_runs'


def _key_ok(part_key) -> bool:
    return isinstance(part_key, str) and re.fullmatch(r'[a-z0-9]{1,80}', part_key) is not None


def validate_summary(live) -> str | None:
    """None when `live` has the live_program shape publish needs, else the reason."""
    if not isinstance(live, dict):
        return 'summary must be an object'
    tps, sus = live.get('toolpaths'), live.get('setups')
    if not isinstance(tps, list) or not tps:
        return 'summary.toolpaths must be a non-empty list'
    if len(tps) > MAX_TOOLPATHS:
        return f'too many toolpaths (max {MAX_TOOLPATHS})'
    if not isinstance(sus, list) or not sus:
        return 'summary.setups must be a non-empty list'
    if not all(isinstance(t, dict) and isinstance(t.get('name'), str) and t['name'] for t in tps):
        return 'every toolpath needs a name'
    if not all(isinstance(s, dict) and isinstance(s.get('setup'), int) for s in sus):
        return 'every setup needs a numeric setup index'
    if not isinstance(live.get('powermill_cutting_minutes_total'), (int, float)):
        return 'summary.powermill_cutting_minutes_total must be a number'
    return None


def publish(part_key: str, live: dict, run_name: str, published_by: str) -> dict:
    """Validate and atomically store the summary for a part; returns the stored record's header."""
    if not _key_ok(part_key):
        raise ValueError('this job has no recognised part to publish a run for')
    why = validate_summary(live)
    if why:
        raise ValueError(why)
    if not isinstance(run_name, str) or not RUN_NAME_RE.match(run_name or ''):
        raise ValueError('run_name is not a valid planner run name')
    by = (published_by or '').strip()
    if not by or len(by) > 120:
        raise ValueError('published_by is empty or too long')
    live = dict(live)
    live['images'] = []                       # image urls point at the laptop's run folder: not portable
    live['run_name'] = run_name
    rec = {'part_key': part_key, 'run_name': run_name, 'published_by': by,
           'published_at': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'live': live}
    data = json.dumps(rec, ensure_ascii=False).encode('utf-8')
    if len(data) > MAX_PUBLISH_BYTES:
        raise ValueError(f'summary too large ({len(data)} bytes; max {MAX_PUBLISH_BYTES})')
    d = published_dir()
    d.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=f'.{part_key}.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
        os.replace(tmp, d / f'{part_key}.json')
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return {k: rec[k] for k in ('part_key', 'run_name', 'published_by', 'published_at')}


def load_published(part_key: str | None) -> dict | None:
    if not _key_ok(part_key):
        return None
    f = published_dir() / f'{part_key}.json'
    if not f.exists():
        return None
    try:
        rec = file_cache.memo(f'published:{f}', [f], lambda: json.loads(f.read_text(encoding='utf-8')))
    except Exception:
        return None
    return rec if isinstance(rec, dict) and isinstance(rec.get('live'), dict) else None


def source_label(rec: dict) -> str:
    when = (rec.get('published_at') or '')[:10]
    return f"published from planner run {rec.get('run_name')} on {when} by {rec.get('published_by')}"
