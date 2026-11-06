"""
part_data.py — map a capp_service job to its real-world part folder and load
the shop records that live there (previous manual quote, drawing tolerances
from the inspection report, tagged datums, CAM NC programs, override log).

Part folders live under:
    Claude output for program sheet/Manufactured parts/<Part>/

A job is matched to a part folder by normalised name: the uploaded file's stem
(stored as `original_filename` in job.json), the job's part_name, or the STEP
filename in the job folder. Normalisation = lowercase, alphanumerics only, so
"MOTOR_MOUNT", "MOTOR MOUNT" and "motor mount" all match "MOTOR MOUNT.step";
"RKSE-004-057" matches "RKSE-004-057.stp".
"""

from __future__ import annotations

import gzip
import json
import os
import re
import shutil
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PARTS_ROOT = REPO_ROOT / 'Claude output for program sheet' / 'Manufactured parts'

# Data pack: the minimal real part files the demo endpoints read (NC programs, inspection report,
# quotation, tolerances, snapshots), shipped with the service so a server without this laptop's
# folders still serves Motor Mount / Rekise. Layout mirrors a Manufactured parts folder:
#     <pack>/<Part folder name>/{Quotation,Inspection Report,CAM Program/...}
# Override the location with SHIAANX_PART_DATA_DIR. When a part exists in both, the pack wins.
DATA_DIR = Path(__file__).resolve().parent.parent / 'demo_data'
PACK_ROOT = Path(os.environ.get('SHIAANX_PART_DATA_DIR') or (DATA_DIR / 'parts'))

_unpack_lock = threading.Lock()


def _unpack_taps(root: Path) -> None:
    """NC programs are stored gzipped in the pack (11 MB raw -> 2.5 MB); the readers glob '*.tap',
    so expand them next to the .gz once (idempotent; a read-only pack just keeps the .gz)."""
    with _unpack_lock:
        try:
            for gz in root.rglob('*.tap.gz'):
                tap = gz.with_suffix('')          # 'x.tap.gz' -> 'x.tap'
                if tap.exists() and tap.stat().st_mtime >= gz.stat().st_mtime:
                    continue
                with gzip.open(gz, 'rb') as src, open(tap, 'wb') as dst:
                    shutil.copyfileobj(src, dst)
        except OSError:
            pass


def parts_roots() -> list[Path]:
    """Existing part-folder roots, pack first."""
    roots = []
    if PACK_ROOT.is_dir():
        _unpack_taps(PACK_ROOT)
        roots.append(PACK_ROOT)
    if PARTS_ROOT.is_dir() and PARTS_ROOT != PACK_ROOT:
        roots.append(PARTS_ROOT)
    return roots


def part_dirs() -> list[Path]:
    """Every part folder, pack first; a folder name already seen in the pack is not repeated."""
    out, seen = [], set()
    for root in parts_roots():
        for d in sorted(root.iterdir()):
            if d.is_dir() and d.name not in seen:
                seen.add(d.name)
                out.append(d)
    return out


def rel_to_repo(p: Path) -> str:
    try:
        return Path(p).relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return Path(p).as_posix()


def norm(name: str) -> str:
    return re.sub(r'[^a-z0-9]', '', (name or '').lower())


def _part_keys(part_dir: Path) -> set[str]:
    keys = {norm(part_dir.name)}
    # The pack holds no STEP files, so the STEP-stem names a part answers to come from here.
    alias = part_dir / 'part_aliases.json'
    if alias.exists():
        try:
            keys |= {norm(k) for k in json.loads(alias.read_text(encoding='utf-8')).get('keys', [])}
        except Exception:
            pass
    for pat in ('*.step', '*.stp', '*.STEP', '*.STP'):
        for p in part_dir.glob(pat):
            keys.add(norm(p.stem))
    return {k for k in keys if k}


def job_name_candidates(job_dir: Path) -> list[str]:
    names = []
    manifest_path = job_dir / 'job.json'
    if manifest_path.exists():
        try:
            m = json.loads(manifest_path.read_text(encoding='utf-8'))
            if m.get('original_filename'):
                names.append(Path(m['original_filename']).stem)
            if m.get('part_name'):
                names.append(m['part_name'])
        except Exception:
            pass
    for p in job_step_files(job_dir):
        names.append(p.stem)
    return names


def job_step_files(job_dir: Path) -> list[Path]:
    """Part STEP(s) in a job folder — excludes generated jaw / assembly STEPs."""
    files = list(job_dir.glob('*.step')) + list(job_dir.glob('*.stp'))
    return [p for p in files if 'soft_jaw' not in p.name and 'fixture_assembly' not in p.name]


def find_part_dir(job_dir: Path) -> Path | None:
    cands = [norm(n) for n in job_name_candidates(job_dir) if norm(n)]
    for part_dir in part_dirs():
        keys = _part_keys(part_dir)
        if any(c in keys for c in cands):
            return part_dir
    return None


# ── Previous manual quote (Quotation/*.xlsx) ────────────────────────────────

def _load_previous_quote(part_dir: Path | None) -> dict | None:
    """Parse the real ShiaanX quotation workbook for this part, if one exists.
    Reads the line-item table (header row containing 'Unit Price') and the
    'Dispatch' term. Customer name/contact are deliberately not returned."""
    if part_dir is None:
        return None
    qdir = part_dir / 'Quotation'
    files = sorted(qdir.glob('*.xlsx')) if qdir.exists() else []
    if not files:
        return None
    try:
        import openpyxl
    except ImportError:
        return None
    path = files[0]
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = wb.worksheets[0]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    out = {'source_file': rel_to_repo(path)}
    header_idx, cols = None, {}
    for i, r in enumerate(rows):
        cells = [str(c).strip().lower() if c is not None else '' for c in r]
        if 'quote id' in cells:
            j = cells.index('quote id')
            out['quote_id'] = r[j + 1] if j + 1 < len(r) else None
        if 'date' in cells and 'quote_date' not in out:
            j = cells.index('date')
            v = r[j + 1] if j + 1 < len(r) else None
            out['quote_date'] = v.date().isoformat() if hasattr(v, 'date') else (str(v) if v else None)
        if 'unit price' in cells and header_idx is None:
            header_idx = i
            cols = {name: cells.index(name) for name in cells if name}
        if cells and cells[1:2] == ['dispatch'] or (len(cells) > 1 and cells[1].startswith('dispatch')):
            out['dispatch_terms'] = r[2] if len(r) > 2 else None
    if header_idx is not None:
        for r in rows[header_idx + 1:]:
            pn = r[cols.get('part name', 1)]
            proc = str(r[cols.get('process', 3)] or '').lower()
            if pn and 'machining' in proc:
                out.update({
                    'part_name': str(pn).strip(),
                    'material': r[cols.get('material', 2)],
                    'qty': r[cols.get('qty', 4)],
                    'unit_price_inr': r[cols.get('unit price', 5)],
                    'line_total_inr': r[cols.get('total price', 6)],
                })
                break
    wb.close()
    return out if 'unit_price_inr' in out else None


# ── Drawing tolerances (Inspection Report/*.xlsx or tolerances.json) ────────

_NUM_RE = re.compile(r'(\d+(?:\.\d+)?)')


def _tol(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _load_inspection_characteristics(part_dir: Path | None) -> list[dict]:
    """Read the real final-inspection report: one row per drawing characteristic
    (SL No | Description | TOL+ | TOL- | Instrument | Observation ...). Rows whose
    tolerance is '-' are visual checks."""
    if part_dir is None:
        return []
    idir = part_dir / 'Inspection Report'
    files = sorted(idir.glob('*.xlsx')) if idir.exists() else []
    if not files:
        return []
    import openpyxl
    wb = openpyxl.load_workbook(files[0], data_only=True, read_only=True)
    ws = wb.worksheets[0]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    wb.close()
    hdr = None
    for i, r in enumerate(rows):
        cells = [str(c).strip().lower() if c is not None else '' for c in r]
        if 'description' in cells and 'tol+' in cells:
            hdr = i
            ci = {k: cells.index(k) for k in ('description', 'tol+', 'tol-')}
            ci['instrument'] = next((j for j, c in enumerate(cells) if 'instrument' in c), None)
            ci['observation'] = next((j for j, c in enumerate(cells) if 'observation' in c), None)
            ci['remark'] = next((j for j, c in enumerate(cells) if 'remark' in c), None)
            break
    if hdr is None:
        return []
    out = []
    for r in rows[hdr + 1:]:
        sl = r[0]
        if not isinstance(sl, (int, float)):
            continue
        desc_raw = r[ci['description']]
        desc = str(desc_raw).strip() if desc_raw is not None else ''
        tp, tm = _tol(r[ci['tol+']]), _tol(r[ci['tol-']])
        obs = []
        if ci['observation'] is not None:
            for c in r[ci['observation']:ci['remark'] or len(r)]:
                if c is not None:
                    obs.append(str(c))
        entry = {
            'sl_no': int(sl),
            'description': desc,
            'instrument': r[ci['instrument']] if ci['instrument'] is not None else None,
            'observations': obs,
            'remark': r[ci['remark']] if ci['remark'] is not None else None,
        }
        m = _NUM_RE.search(desc)
        if tp is None or tm is None or not m:
            entry['kind'] = 'visual'
        else:
            # The xlsx renders the diameter symbol as a non-ASCII glyph (often
            # mojibake) before the number — any non-digit prefix means diameter.
            prefix = desc[:m.start()].strip()
            entry.update({
                'kind': 'diameter' if prefix else 'linear',
                'nominal_mm': float(m.group(1)),
                'upper_tol_mm': tp,
                'lower_tol_mm': tm,
            })
        out.append(entry)
    return out


def load_part_tolerances_json(part_dir: Path | None) -> dict:
    if part_dir is None:
        return {}
    p = part_dir / 'tolerances.json'
    if p.exists():
        try:
            return json.loads(p.read_text(encoding='utf-8')) or {}
        except Exception:
            return {}
    return {}


def load_part_datums(part_dir: Path | None) -> dict | None:
    if part_dir is None:
        return None
    files = sorted(part_dir.glob('*.datums.json'))
    if not files:
        return None
    return json.loads(files[0].read_text(encoding='utf-8'))


def load_json(part_dir: Path | None, name: str):
    if part_dir is None:
        return None
    p = part_dir / name
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding='utf-8'))


def find_ncprograms_dir(part_dir: Path | None) -> Path | None:
    """The folder holding '<Nth> setting/*.tap' directories."""
    if part_dir is None:
        return None
    for d in part_dir.rglob('*'):
        if d.is_dir() and re.match(r'^\d+(st|nd|rd|th)\s+setting$', d.name, re.I):
            return d.parent
    return None


def find_capp_params(job_dir: Path, part_dir: Path | None) -> Path | None:
    for d in (job_dir, part_dir):
        if d is None:
            continue
        m = sorted(d.glob('*_params.json'))
        if m:
            return m[0]
    return None


# ── v3 face order per part ──────────────────────────────────────────────────
# v3's default greedy face order can pick unrealistic setups (Motor Mount: +Y,-Y,+Z,
# i.e. the plate stood on edge). For parts we have real programs for, pass the
# programmer's real setting order. These strings must match what the v3 cache was
# built with (the adapter's cache key includes `faces`). Unknown parts -> None (greedy).
V3_FACE_ORDER = {
    'motormount': '+Z,-Z,-Y',     # real programmer's 3 settings (batch 1 PowerMill NC)
    # Rekise: v3's greedy order already gives -Y,+Y (the cached sample). Left as None:
    # an explicit '-Y,+Y' is (a) a different cache key and (b) currently mis-parsed by
    # v3_runner's argparse (`--faces -Y,+Y` reads as a flag) -> runner exits rc=1.
    'rkse004057': None,
}


def v3_faces_for_job(job_dir: Path) -> str | None:
    for n in job_name_candidates(job_dir):
        f = V3_FACE_ORDER.get(norm(n))
        if f:
            return f
    return None


# ── Real shop cycle-time references ─────────────────────────────────────────
# Other shop programs for the same part that live outside the part folder.
EXTERNAL_PROGRAM_DIRS = {
    'motormount': [Path(r'G:\My Drive\Closed Loop\Clean Data\Motor Mount_TS\CAM files_TS')],
}
EXTERNAL_REFS_SNAPSHOT = 'external_cycle_refs.json'
_MPF_TIME = re.compile(r'^\s*;\s*time\s*=\s*(\d+):(\d+):(\d+)', re.I | re.M)
_ref_cache: dict = {}


def _part_key(part_dir: Path | None) -> str | None:
    if part_dir is None:
        return None
    for k in _part_keys(part_dir):
        if k in EXTERNAL_PROGRAM_DIRS or k in V3_FACE_ORDER:
            return k
    return norm(part_dir.name)


def shop_cycle_references(part_dir: Path | None, closed_loop_module=None) -> list[dict]:
    """Every real shop program we have for this part, with its machining minutes, read
    from the files themselves:
      - PowerMill .tap (part folder): feed-move path length / programmed F (closed_loop.parse_tap)
      - Sinumerik .MPF (external): sum of the programmer's ';time = h:mm:ss' header lines
    """
    if part_dir is None:
        return []
    key = str(part_dir)
    if key in _ref_cache:
        return _ref_cache[key]
    refs = []
    nc = find_ncprograms_dir(part_dir)
    if nc is not None and closed_loop_module is not None:
        setups, files = [], 0
        for setting in sorted(d for d in nc.iterdir() if d.is_dir()):
            secs = 0.0
            for tap in setting.glob('*.tap'):
                pg = closed_loop_module.parse_tap(tap)['programmed']
                secs += (pg.get('est_cut_s') or 0) + (pg.get('est_drill_s') or 0)
                files += 1
            setups.append({'setup': setting.name, 'minutes': round(secs / 60, 1)})
        refs.append({
            'label': 'Shop program A: PowerMill NC (part folder)',
            'source': rel_to_repo(nc),
            'setups': len(setups), 'files': files, 'by_setup': setups,
            'minutes_per_part': round(sum(s['minutes'] for s in setups), 1),
            'basis': 'feed-move toolpath length / programmed feed, summed over all .tap files '
                     '(rapids, tool changes, load/unload excluded)',
        })
    snap = part_dir / EXTERNAL_REFS_SNAPSHOT
    for d in EXTERNAL_PROGRAM_DIRS.get(_part_key(part_dir), []):
        if not d.exists():
            # Drive not reachable (server): serve the references saved while it was mounted.
            if snap.exists():
                try:
                    refs += [{**r, 'snapshot': True} for r in json.loads(snap.read_text(encoding='utf-8'))]
                except Exception:
                    pass
            continue
        setups = []
        for mpf in sorted(d.glob('*.MPF')):
            txt = mpf.read_text(encoding='utf-8', errors='ignore')
            secs = sum(int(h) * 3600 + int(m) * 60 + int(s) for h, m, s in _MPF_TIME.findall(txt))
            setups.append({'setup': mpf.name, 'minutes': round(secs / 60, 2)})
        if setups:
            refs.append({
                'label': 'Shop program B: Sinumerik MPF (TS machine)',
                'source': d.as_posix(),
                'setups': len(setups), 'files': len(setups), 'by_setup': setups,
                'minutes_per_part': round(sum(s['minutes'] for s in setups), 1),
                'basis': "sum of the programmer's ';time =' header lines (CAM-estimated machining time; "
                         'load/unload and changeovers excluded)',
            })
    _ref_cache[key] = refs
    return refs


# ── mtime-cached wrappers (openpyxl load is ~0.3-3 s; the workbooks rarely change) ──

def _xlsx_in(part_dir: Path | None, sub: str) -> list[Path]:
    d = part_dir / sub if part_dir is not None else None
    return sorted(d.glob('*.xlsx')) if d is not None and d.exists() else []


def load_previous_quote(part_dir: Path | None) -> dict | None:
    from . import file_cache
    if part_dir is None:
        return None
    return file_cache.memo(f'prev_quote:{part_dir}', _xlsx_in(part_dir, 'Quotation'),
                           lambda: _load_previous_quote(part_dir))


def load_inspection_characteristics(part_dir: Path | None) -> list[dict]:
    from . import file_cache
    if part_dir is None:
        return []
    return file_cache.memo(f'insp_chars:{part_dir}', _xlsx_in(part_dir, 'Inspection Report'),
                           lambda: _load_inspection_characteristics(part_dir))
