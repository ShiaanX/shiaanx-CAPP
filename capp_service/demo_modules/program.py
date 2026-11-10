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

import json
from datetime import datetime, timezone
from pathlib import Path

from . import file_cache, part_data, v3_runs

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
    # One time basis on screen: each setup's minutes = cutting + its tool changes on the shop's automatic changer,
    # so the setups add up to cycle_minutes_atc. v3's own figure (15 min per manual change) stays as v3_minutes.
    if cyc and p.get('tool_changes'):
        each = max(0.0, (cyc['total_minutes'] - (p.get('cutting_minutes') or 0)) / p['tool_changes'])
        for s in setups:
            s['v3_minutes'] = s['minutes']
            if s.get('cutting_minutes') is not None:
                s['minutes'] = round(s['cutting_minutes'] + (s.get('tool_changes') or 0) * each, 1)
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


def _latest_planner_run(key: str | None):
    """Planning laptop only: the newest finished planner console run for this part, read directly."""
    try:
        name = v3_runs.latest_finished_for(key)
        if not name:
            return None
        live, notes = v3_runs.summarize_run(name)
    except Exception:
        return None
    if not live:
        return None
    live['source_label'] = f"planner run {name} (newest finished run on this computer)"
    return live, notes


def live_program(key: str | None) -> tuple[dict | None, list[str]]:
    """Cached per run folder until the events file, manifest or decoded project changes."""
    pub = v3_runs.load_published(key)
    if pub is not None:
        live = dict(pub['live'])
        live['source_label'] = v3_runs.source_label(pub)
        live['published'] = {k: pub.get(k) for k in ('run_name', 'published_by', 'published_at')}
        return live, []
    latest = _latest_planner_run(key)
    if latest is not None:
        return latest
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
    run = LIVE_RUNS.get(key or '')
    if not run:
        return None, ['No live PowerMill run on record for this part: live_program is null. '
                      'The v3 plan above is the AI process plan; a CAM program is generated when the part '
                      'is run through v3 + PowerMill.']
    folder = run['folder']
    ev_path = folder / 'live_events.ndjson'
    if not ev_path.exists():
        return None, [f'Live run folder {folder} has no live_events.ndjson']
    proj_read = folder / run['read_project']
    manifest = folder / 'run_folder' / 'run_manifest.json'
    man = json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else {}
    imgs = _images(folder)
    return v3_runs.build_live(
        _events(ev_path), man=man, proj_read=proj_read,
        proj_path_label=_rel(folder / run['project']), proj_read_label=_rel(proj_read),
        sources=[_rel(ev_path), _rel(manifest) if manifest.exists() else None,
                 f"{_rel(proj_read)} (pml_project.py + toolpath 'TotalTime')"],
        images=[(p.relative_to(folder).as_posix(), f"image/{p.relative_to(folder).as_posix()}") for p in imgs])


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
        notes.append(f"Cycle time {plan['cycle_minutes_atc']} min per part, including tool changes on the shop's automatic changer.")
    return {
        'status': 'ok' if plan else v3_state,
        'part': pd.name if pd else None,
        'part_key': key,
        'source': {
            'plan': (f"v3 analysis cache {_rel(job_dir / 'v3_analysis.json')} "
                     f"(v3_origin={v3.get('v3_origin')}, faces={v3.get('requested_faces')})") if plan else None,
            'live_run': (live.get('source_label') or ', '.join(s for s in live['sources'] if s)) if live else None,
        },
        'approved': load_approval(job_dir),
        'published': (live or {}).get('published'),
        'plan': plan,
        'live_program': live,
        'notes': notes,
    }
