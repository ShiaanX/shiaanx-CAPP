"""
v3_cache.py — run the v3 analysis engine once per job in a background thread
and cache the result as <job_dir>/v3_analysis.json.

The engine itself lives in capp_service/v3_adapter.py (owned separately) and is
imported lazily: until it exists, endpoints get status 'unavailable' (-> HTTP 503).

Server mode: V3_DISABLED=1 (v3 / PowerMill are not installed). Nothing is spawned; the saved
analysis for the uploaded STEP (matched by SHA-256, see v3_adapter) is used, otherwise the job
fails at once with v3_adapter.V3_UNAVAILABLE_MSG, reported like any other failed analysis
(state 'failed', payload {'error': <that message>}).

Local-testing escape hatch ONLY: if the env var SHIAANX_V3_SAMPLE=1 is set and
capp_service/demo_data/v3_motor_mount_sample.json exists, that sample is used
instead and every response is marked v3_origin='sample_fixture'. It is off by
default so the demo never silently shows sample numbers.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

from . import part_data

SERVICE_DIR = Path(__file__).resolve().parent.parent
SAMPLE_PATH = SERVICE_DIR / 'demo_data' / 'v3_motor_mount_sample.json'
CACHE_NAME = 'v3_analysis.json'
ERROR_NAME = 'v3_analysis.error.json'

_lock = threading.Lock()
_running: dict[str, float] = {}   # job_id -> start time


def _adapter():
    if str(SERVICE_DIR) not in sys.path:
        sys.path.insert(0, str(SERVICE_DIR))
    try:
        return importlib.import_module('v3_adapter')
    except ImportError as e:
        # ImportError from *inside* an existing adapter is a real error, not "missing"
        if (SERVICE_DIR / 'v3_adapter.py').exists():
            raise
        return None


def _disabled() -> bool:
    return os.environ.get('V3_DISABLED', '').strip().lower() in ('1', 'true', 'yes', 'on')


def _sample_enabled() -> bool:
    return os.environ.get('SHIAANX_V3_SAMPLE') == '1' and SAMPLE_PATH.exists()


def _material(job_dir: Path) -> str:
    try:
        m = json.loads((job_dir / 'job.json').read_text(encoding='utf-8')).get('material') or 'aluminium'
    except Exception:
        m = 'aluminium'
    return 'aluminium' if m.lower().startswith('al') else m


def _worker(job_id: str, job_dir: Path, step_path: Path):
    try:
        mod = _adapter()
        t0 = time.time()
        # cache_dir=None -> adapter's shared cache keyed by STEP sha256, so re-uploading
        # the same part (e.g. MOTOR MOUNT.step) reuses a finished v3 run instantly.
        faces = part_data.v3_faces_for_job(job_dir)
        result = mod.run_v3_analysis(str(step_path), material=_material(job_dir), cache_dir=None, faces=faces)
        if not isinstance(result, dict):
            raise TypeError(f'run_v3_analysis returned {type(result).__name__}, expected dict')
        result.setdefault('runtime_s', round(time.time() - t0, 1))
        result['requested_faces'] = faces
        (job_dir / CACHE_NAME).write_text(json.dumps(result, indent=2, default=str), encoding='utf-8')
        (job_dir / ERROR_NAME).unlink(missing_ok=True)
    except Exception as e:
        if type(e).__name__ == 'V3Unavailable':
            # expected in server mode: the message is meant for the user, no class prefix or trace
            payload = {'error': str(e), 'reason': 'v3_disabled'}
        else:
            payload = {'error': f'{type(e).__name__}: {e}', 'trace': traceback.format_exc()[-3000:]}
        (job_dir / ERROR_NAME).write_text(json.dumps(payload, indent=2), encoding='utf-8')
    finally:
        with _lock:
            _running.pop(job_id, None)


def start(job_id: str, job_dir: Path) -> None:
    """Kick off v3 analysis for a job if not cached / running. Safe to call repeatedly."""
    if (job_dir / CACHE_NAME).exists():
        return
    try:
        if _adapter() is None:
            return
    except Exception:
        pass  # surfaced by get()
    steps = part_data.job_step_files(job_dir)
    if not steps:
        return
    with _lock:
        if job_id in _running:
            return
        _running[job_id] = time.time()
    if _disabled():
        # saved-analysis lookup only (hash the STEP, read one JSON): run inline so a miss fails fast
        _worker(job_id, job_dir, steps[0])
        return
    threading.Thread(target=_worker, args=(job_id, job_dir, steps[0]), daemon=True).start()


def get(job_id: str, job_dir: Path) -> tuple[str, dict | None]:
    """Returns (state, payload).
    state: 'ready' (payload = v3 dict) | 'running' (payload = {started_s_ago}) |
           'failed' (payload = {error}) | 'unavailable' (payload = {reason})."""
    cache = job_dir / CACHE_NAME
    if cache.exists():
        data = json.loads(cache.read_text(encoding='utf-8'))
        if data.get('requested_faces') != part_data.v3_faces_for_job(job_dir):
            cache.unlink(missing_ok=True)   # planned with a different face order -> re-run (cache hit if known)
        else:
            data.setdefault('v3_origin', 'v3_adapter')
            return 'ready', data
    with _lock:
        t0 = _running.get(job_id)
    if t0 is not None:
        return 'running', {'started_s_ago': round(time.time() - t0, 1)}
    err = job_dir / ERROR_NAME
    try:
        mod = _adapter()
    except Exception as e:
        return 'failed', {'error': f'v3_adapter import failed: {type(e).__name__}: {e}'}
    if mod is None:
        if _sample_enabled():
            data = json.loads(SAMPLE_PATH.read_text(encoding='utf-8'))
            data['v3_origin'] = 'sample_fixture'
            return 'ready', data
        return 'unavailable', {'reason': 'capp_service/v3_adapter.py not present yet'}
    if err.exists():
        return 'failed', json.loads(err.read_text(encoding='utf-8'))
    start(job_id, job_dir)
    if _disabled() and ((job_dir / CACHE_NAME).exists() or err.exists()):
        return get(job_id, job_dir)   # start() finished inline: report ready / failed now
    return 'running', {'started_s_ago': 0.0}


def retry(job_id: str, job_dir: Path) -> None:
    (job_dir / ERROR_NAME).unlink(missing_ok=True)
    start(job_id, job_dir)
