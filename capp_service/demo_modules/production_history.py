"""
production_history.py — previous real production runs of a part, read from the shop's files.

Batch 1 (local, any part): the part folder's PowerMill NC programs ('<Nth> setting/*.tap') +
  its final-inspection report ('Inspection Report/*.xlsx'). Ops are parsed with tracking.py's
  _from_nc (repo closed_loop.parse_tap): programmed S, dominant cutting F, minutes = feed-move
  length / feed (rapids and tool changes excluded).
Batch 2 (external, registered per part in EXTERNAL_BATCHES): the TS machine's Sinumerik .MPF
  programs (one file per setup, one MSG("<op> = h:mm:ss") section per operation) + its inspection
  report. Op minutes = the programmer's MSG time; total = sum of the ';time =' header lines.
  If the external drive is unreachable, the last snapshot written by write_snapshots()
  (demo_data/production_history/<key>_<batch>.json) is served, marked snapshot=True.

QC grading matches the /proto "Defects & why" view (DefectsWhy.js): each reading vs nominal ± tol;
outside = out, using >=80% of its side's band = close, else in. A dimension takes its worst reading.
Rows without a numeric nominal/tolerance (visual checks, 'tapping') are 'checked', not counted.
"""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from . import file_cache, part_data

SNAPSHOT_DIR = Path(__file__).resolve().parent.parent / 'demo_data' / 'production_history'
NEAR_FRACTION = 0.8
EPS = 1e-6

# Batches that live outside the part folder, keyed by normalised part key.
EXTERNAL_BATCHES = {
    'motormount': [{
        'id': 'run2',
        'label': 'Batch 2: Sinumerik 828D program, TS machine',
        'machine': 'TS (Sinumerik 828D)',
        'program_type': 'Sinumerik 828D .MPF',
        'root': Path(r'G:\My Drive\Closed Loop\Clean Data\Motor Mount_TS'),
        'programs': 'CAM files_TS',
        'inspection': 'Inspection Report_TS',
    }],
}


def _rel(p: Path) -> str:
    try:
        return p.relative_to(part_data.REPO_ROOT).as_posix()
    except ValueError:
        return p.as_posix()


# ── part resolution ─────────────────────────────────────────────────────────

def find_part_dir_by_key(part_key: str) -> Path | None:
    k = part_data.norm(part_key)
    if not k:
        return None
    for d in part_data.part_dirs():
        if k in part_data._part_keys(d):
            return d
    return None


def part_key_of(part_dir: Path | None, fallback: str = '') -> str:
    if part_dir is None:
        return part_data.norm(fallback)
    keys = part_data._part_keys(part_dir)
    for k in sorted(keys):
        if k in EXTERNAL_BATCHES or k in part_data.V3_FACE_ORDER:
            return k
    return part_data.norm(part_dir.name)


# ── inspection report (same reading rules as scripts/build_motor_mount_data.py) ──

def _num_list(v):
    if v is None:
        return []
    if isinstance(v, (int, float)):
        return [float(v)]
    out = []
    for p in str(v).split('/'):
        try:
            out.append(float(p))
        except ValueError:
            pass
    return out


def read_report(path: Path) -> tuple[list[dict], list[str]]:
    """Cached by the workbook's mtime (see _read_report)."""
    dims, pieces = file_cache.memo(f'read_report:{path}', [path], lambda: _read_report(path))
    return dims, pieces


def _read_report(path: Path) -> tuple[list[dict], list[str]]:
    """-> (dims, pieces). Header row starts 'SL No.'; the row under it names the parts (P1..Pn)."""
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    dims: dict = {}
    for ws in wb.worksheets:
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        hi = next((i for i, r in enumerate(rows) if r and r[0] == 'SL No.'), None)
        if hi is None or hi + 1 >= len(rows):
            continue
        pieces_row = rows[hi + 1]
        remark_col = rows[hi].index('Remark') if 'Remark' in rows[hi] else len(rows[hi])
        pcols = [(i, pieces_row[i]) for i in range(5, min(remark_col, len(pieces_row))) if pieces_row[i]]
        for r in rows[hi + 2:]:
            if not r or not isinstance(r[0], int):
                continue
            desc = str(r[1]).replace('\ufffd', 'Ø').strip()
            try:
                nominal = float(desc.replace('Ø', '').strip())
            except ValueError:
                nominal = None
            d = dims.setdefault(r[0], {
                'sl': r[0], 'label': desc, 'nominal': nominal, 'is_diameter': 'Ø' in desc,
                'tol_plus': r[2] if isinstance(r[2], (int, float)) else None,
                'tol_minus': r[3] if isinstance(r[3], (int, float)) else None,
                'instrument': r[4],
                'remark': (str(r[remark_col]).strip() if remark_col < len(r) and r[remark_col] else None),
                'readings': {}, 'notes': {}})
            # the batch-1 sheet has a single 'P1' header but values in two columns (P1, P2: QTY 02)
            cols = pcols if len(pcols) > 1 else [(5, 'P1'), (6, 'P2')]
            for i, piece in cols:
                if i >= len(r):
                    continue
                if list(pieces_row).count(piece) > 1 and r[i] is None:
                    continue
                vals = _num_list(r[i])
                if vals:
                    d['readings'].setdefault(piece, []).extend(vals)
                elif r[i] is not None:
                    d['notes'][piece] = str(r[i]).strip()
    wb.close()
    out = [dims[k] for k in sorted(dims)]
    pieces = sorted({p for d in out for p in d['readings']} | {p for d in out for p in d['notes']},
                    key=lambda s: int(re.sub(r'\D', '', s) or 0))
    return out, pieces


def _grade_reading(v, nom, tp, tm):
    dev = round(v - nom, 3)
    tol = tp if dev >= 0 else tm
    if dev > tp + EPS or dev < -tm - EPS:
        return 'out'
    if tol > 0 and abs(dev) >= NEAR_FRACTION * tol - EPS:
        return 'close'
    return 'in'


def grade(dims: list[dict]) -> dict:
    rank = {'out': 3, 'close': 2, 'in': 1}
    per = []
    for d in dims:
        readings = [v for vals in d['readings'].values() for v in vals]
        gradable = (d['nominal'] is not None and d['tol_plus'] is not None
                    and d['tol_minus'] is not None and readings)
        if gradable:
            vs = [_grade_reading(v, d['nominal'], d['tol_plus'], d['tol_minus']) for v in readings]
            verdict = max(vs, key=rank.get)
        else:
            verdict = 'checked'
        tol = ([-d['tol_minus'], d['tol_plus']]
               if d['tol_plus'] is not None and d['tol_minus'] is not None else None)
        per.append({'dim': d['label'], 'sl': d['sl'], 'nominal': d['nominal'], 'tol': tol,
                    'readings': readings, 'readings_by_part': d['readings'], 'notes': d['notes'] or None,
                    'instrument': d['instrument'], 'remark': d['remark'], 'verdict': verdict})
    graded = [p for p in per if p['verdict'] != 'checked']
    return {'dimensions': len(graded),
            'in_tol': sum(p['verdict'] == 'in' for p in graded),
            'close': sum(p['verdict'] == 'close' for p in graded),
            'out': sum(p['verdict'] == 'out' for p in graded),
            'checked_only': len(per) - len(graded),
            'grading': 'each reading vs nominal ± tol: outside = out; >= 80% of the band = close; else in. '
                       'A dimension takes its worst reading. Visual / un-toleranced rows = checked (not counted).',
            'per_dimension': per}


# ── batch 1: part-folder PowerMill .tap ────────────────────────────────────

def _local_inputs(part_dir: Path) -> list[Path]:
    nc = part_data.find_ncprograms_dir(part_dir)
    idir = part_dir / 'Inspection Report'
    files = sorted(nc.rglob('*.tap')) if nc is not None else []
    files += sorted(idir.glob('*.xlsx')) if idir.exists() else []
    files += [part_dir / n for n in ('override_log.json', 'actual_process.json', 'job.json')]
    return files


def _batch_local(part_dir: Path) -> dict | None:
    """Cached until any .tap / inspection report / context file in the part folder changes."""
    return file_cache.memo(f'batch_local:{part_dir}', _local_inputs(part_dir),
                           lambda: _batch_local_uncached(part_dir))


def _batch_local_uncached(part_dir: Path) -> dict | None:
    from . import tracking
    nc = part_data.find_ncprograms_dir(part_dir)
    idir = part_dir / 'Inspection Report'
    reports = sorted(idir.glob('*.xlsx')) if idir.exists() else []
    if nc is None or not reports:
        return None
    ops_raw, _src = tracking._from_nc(nc, part_dir, part_dir)
    ops = [{'op': o['op'], 'setup': o['setup'], 'tool': o['tool'], 'rpm': o['planned'].get('rpm'),
            'feed_mm_min': o['planned'].get('feed_mm_min'), 'minutes': o['planned'].get('minutes'),
            'nc_file': o.get('nc_file')} for o in ops_raw]
    dims, pieces = read_report(reports[0])
    setups = len({o['setup'] for o in ops})
    srcs = [f'{_rel(nc)}/ ({len(ops)} .tap files)', _rel(reports[0])]
    for extra in ('override_log.json', 'actual_process.json', 'job.json'):
        if (part_dir / extra).exists():
            srcs.append(_rel(part_dir / extra) + ' (context only; parsed from the same NC, not machine actuals)')
    total = round(sum(o['minutes'] or 0 for o in ops), 1)
    return {
        'id': 'run1',
        'label': f'Batch 1: PowerMill program, {setups} settings',
        'machine': 'not recorded (local partner VMC; no machine record in the part folder)',
        'program_type': 'PowerMill NC (.tap)',
        'setups': setups,
        'parts_made': len(pieces),
        'parts': pieces,
        'program': {'ops': ops, 'total_minutes': total,
                    'minutes_basis': 'computed: feed-move path length / programmed feed per .tap '
                                     '(closed_loop.parse_tap via tracking.py); rapids, tool changes and '
                                     'load/unload excluded. The programmer stated no times for this batch.'},
        'qc': grade(dims),
        'defects_link': '/proto/closed-loop?view=defects&batch=run1',
        'sources': srcs,
        'snapshot': False,
    }


# ── batch 2: external Sinumerik .MPF ───────────────────────────────────────

_TOK = re.compile(r'([A-Z])([-+]?\d*\.?\d*)')
_HDR_TIME = re.compile(r'^\s*;\s*time\s*=\s*(\d+):(\d\d):(\d\d)', re.I | re.M)
_TOOLS = re.compile(r'=>\s*(T\d+)\s*\|\s*([^|]*?)\s*\|\s*D([\d.]+)')
_MSG = re.compile(r'MSG\("(.*?)=\s*(\d+):(\d\d):(\d\d)\s*"\)')


def parse_mpf(path: Path) -> dict:
    """One Sinumerik program = one setup. Sections start at MSG("<op> = h:mm:ss")."""
    txt = path.read_text(encoding='utf-8', errors='ignore')
    tools = {t: {'type': typ.strip(), 'dia': float(d)} for t, typ, d in _TOOLS.findall(txt)}
    header_min = sum(int(h) * 60 + int(m) + int(s) / 60 for h, m, s in _HDR_TIME.findall(txt))
    secs, cur = [], None
    x = y = z = 0.0
    mode, tool, feed = 0, None, 0.0
    for raw in txt.splitlines():
        line = raw.strip()
        mt = re.match(r'(T\d+)\s*;', line)
        if mt:
            tool = mt.group(1)
        mm = _MSG.search(line)
        if mm:
            cur = {'op': mm.group(1).strip(), 'tool_id': tool,
                   'programmer_min': int(mm.group(2)) * 60 + int(mm.group(3)) + int(mm.group(4)) / 60,
                   'S': [], 'F': defaultdict(float)}
            secs.append(cur)
            continue
        if line.startswith(';') or cur is None:
            continue
        line = re.sub(r'CR=[-\d.]+', '', line.split(';')[0])
        if '(' in line:
            line = line[:line.index('(')]
        w, gs = {}, []
        for k, v in _TOK.findall(line):
            if v in ('', '+', '-', '.'):
                continue
            if k == 'G':
                gs.append(float(v))
            else:
                w[k] = float(v)
        for g in gs:
            if g in (0, 1, 2, 3):
                mode = int(g)
        if 'S' in w:
            cur['S'].append(w['S'])
        if 'F' in w:
            feed = w['F']
        if 28 in gs or not any(k in w for k in 'XYZ'):
            continue
        nx, ny, nz = w.get('X', x), w.get('Y', y), w.get('Z', z)
        if mode != 0:
            cur['F'][feed] += math.dist((x, y, z), (nx, ny, nz))
        x, y, z = nx, ny, nz
    ops = []
    for s in secs:
        t = tools.get(s['tool_id']) or {}
        rpm = max(set(s['S']), key=s['S'].count) if s['S'] else None
        f = max(s['F'].items(), key=lambda kv: kv[1])[0] if s['F'] else None
        ops.append({'op': s['op'],
                    'tool': f"{s['tool_id']} Ø{t['dia']:g} mm {t['type']}" if t else s['tool_id'],
                    'rpm': rpm, 'feed_mm_min': f or None, 'minutes': round(s['programmer_min'], 2)})
    return {'file': path.name, 'header_minutes': round(header_min, 2), 'ops': ops}


def _batch_external(spec: dict) -> dict | None:
    """Cached until any .MPF / inspection report in the external folder changes."""
    root = spec['root']
    inputs = sorted((root / spec['programs']).glob('*.MPF')) + sorted((root / spec['inspection']).glob('*.xlsx'))
    return file_cache.memo(f"batch_ext:{root}:{spec['id']}", inputs, lambda: _batch_external_uncached(spec))


def _batch_external_uncached(spec: dict) -> dict | None:
    root = spec['root']
    mpfs = sorted((root / spec['programs']).glob('*.MPF'))
    reports = sorted((root / spec['inspection']).glob('*.xlsx'))
    if not mpfs or not reports:
        return None
    ops, by_setup = [], []
    for n, f in enumerate(mpfs, start=1):
        p = parse_mpf(f)
        for o in p['ops']:
            ops.append({**o, 'setup': n, 'nc_file': f.name})
        by_setup.append({'setup': n, 'file': f.name, 'minutes': p['header_minutes']})
    dims, pieces = read_report(reports[0])
    return {
        'id': spec['id'],
        'label': f"{spec['label']}, {len(mpfs)} setups",
        'machine': spec['machine'],
        'program_type': spec['program_type'],
        'setups': len(mpfs),
        'parts_made': len(pieces),
        'parts': pieces,
        'program': {'ops': ops, 'by_setup': by_setup,
                    'total_minutes': round(sum(s['minutes'] for s in by_setup), 1),
                    'ops_minutes_sum': round(sum(o['minutes'] for o in ops), 1),
                    'minutes_basis': "programmer's CAM-estimated times: total = sum of the ';time =' tool-list "
                                     'header lines across the setup programs; op minutes = each '
                                     'MSG("<op> = h:mm:ss"). Load/unload and setup changeovers excluded.'},
        'qc': grade(dims),
        'defects_link': f"/proto/closed-loop?view=defects&batch={spec['id']}",
        'sources': [f"{(root / spec['programs']).as_posix()}/ ({', '.join(m.name for m in mpfs)})",
                    reports[0].as_posix()],
        'snapshot': False,
    }


def _snapshot_path(key: str, batch_id: str) -> Path:
    return SNAPSHOT_DIR / f'{key}_{batch_id}.json'


def write_snapshots(part_key: str) -> list[Path]:
    """Refresh the JSON fallbacks for external batches from the real files (run while G: is mounted)."""
    out = []
    for spec in EXTERNAL_BATCHES.get(part_data.norm(part_key), []):
        b = _batch_external(spec)
        if b is None:
            continue
        b = {**b, 'snapshot_written_at': datetime.now(timezone.utc).isoformat(timespec='seconds')}
        p = _snapshot_path(part_data.norm(part_key), spec['id'])
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(b, indent=1, ensure_ascii=False), encoding='utf-8')
        out.append(p)
    return out


def _external(key: str, notes: list) -> list[dict]:
    out = []
    for spec in EXTERNAL_BATCHES.get(key, []):
        b = None
        if spec['root'].exists():
            try:
                b = _batch_external(spec)
            except Exception as e:
                notes.append(f"{spec['id']}: reading {spec['root']} failed ({type(e).__name__}: {e})")
        if b is None:
            snap = _snapshot_path(key, spec['id'])
            if snap.exists():
                b = json.loads(snap.read_text(encoding='utf-8'))
                b['snapshot'] = True
                b['sources'] = [f"{_rel(snap)} (snapshot of the files below, written "
                                f"{b.get('snapshot_written_at')}; {spec['root']} not reachable now)"] + b['sources']
                notes.append(f"{spec['id']}: served from snapshot; {spec['root']} not reachable")
            else:
                notes.append(f"{spec['id']}: {spec['root']} not reachable and no snapshot")
        if b is not None:
            md = _machine_data(key, spec['id'], notes)
            if md is not None:
                b = {**b, 'machine_data': md}
            out.append(b)
    return out


def _machine_data(key: str, batch_id: str, notes: list) -> dict | None:
    """Controller-log facts for the batch, served ONLY from the telemetry snapshot (never InfluxDB)."""
    try:
        from . import telemetry_batch
        return telemetry_batch.machine_data_for(key, batch_id)
    except Exception as e:
        notes.append(f'{batch_id}: machine data unavailable ({type(e).__name__}: {e})')
        return None


def build(part_dir: Path | None, part_key: str = '') -> dict:
    key = part_key_of(part_dir, part_key)
    notes: list[str] = []
    batches = []
    if part_dir is not None:
        try:
            b1 = _batch_local(part_dir)
            if b1:
                batches.append(b1)
        except Exception as e:
            notes.append(f'run1: reading {part_dir.name} failed ({type(e).__name__}: {e})')
    batches += _external(key, notes)
    if not batches:
        notes.append('No previous production run on record for this part (no NC programs + inspection '
                     'report in its part folder, no registered external batch).')
    return {'status': 'ok', 'part_key': key, 'part': part_dir.name if part_dir else None,
            'batches': batches, 'notes': notes}


def build_for_key(part_key: str) -> dict:
    return build(find_part_dir_by_key(part_key), part_key)


if __name__ == '__main__':
    import sys
    for k in sys.argv[1:] or ['motormount']:
        print([str(p) for p in write_snapshots(k)])
