import threading
import subprocess
import sys
import os
import json
import time
from pathlib import Path

PIPELINE_DIR = Path(__file__).parent.parent / 'Claude output for program sheet'
PIPELINE_SCRIPT = PIPELINE_DIR / '10. run_pipeline.py'

# Output file suffixes produced by each stage, in order
STAGE_OUTPUTS = [
    (1, 'Extract Features',      '_features.json'),
    (2, 'Cluster Features',      '_clustered.json'),
    (3, 'Classify Features',     '_classified.json'),
    (4, 'Process Selection',     '_processes.json'),
    (5, 'Setup Planning',        '_setups.json'),
    # Step 6 (setup_view_renderer) produces a directory, not a JSON — tracked by pipeline completion
    (7, 'Tool Selection',        '_tools.json'),
    (8, 'Parameter Calculation', '_params.json'),
    (9, 'Program Sheet',         '_program_sheet.pdf'),
]


def _watch_progress(job_id: str, base: Path, jobs: dict, stop_event: threading.Event):
    """Poll for output files and update stage progress."""
    while not stop_event.is_set():
        for stage_num, stage_name, suffix in STAGE_OUTPUTS:
            out = Path(str(base) + suffix)
            if out.exists() and jobs[job_id]['stage'] < stage_num:
                jobs[job_id]['stage'] = stage_num
                jobs[job_id]['stage_name'] = stage_name
                # Load JSON outputs into memory for the API to serve
                if suffix.endswith('.json'):
                    try:
                        with open(out) as f:
                            key = suffix.lstrip('_').replace('.json', '')
                            jobs[job_id]['outputs'][key] = json.load(f)
                    except Exception:
                        pass
        time.sleep(1)


def run_pipeline(job_id: str, step_path: str, material: str, part_name: str, jobs: dict):
    base = Path(step_path).with_suffix('')
    stop_event = threading.Event()

    watcher = threading.Thread(
        target=_watch_progress,
        args=(job_id, base, jobs, stop_event),
        daemon=True
    )
    watcher.start()

    try:
        occ_python = sys.executable
        try:
            import OCC
        except ImportError:
            env_occ = os.environ.get('OCC_PYTHON')
            candidate_paths = [
                env_occ,
                '/opt/homebrew/Caskroom/miniconda/base/envs/occ/bin/python',
                os.path.expanduser('~/miniconda3/envs/occ/bin/python'),
                os.path.expanduser('~/anaconda3/envs/occ/bin/python'),
                r'C:\Users\Siddhant Gupta\miniconda3\envs\occ\python.exe'
            ]
            found = False
            for cand in candidate_paths:
                if cand and os.path.exists(cand):
                    occ_python = cand
                    found = True
                    break
            if not found:
                print("WARNING: OCC environment not found in current interpreter or candidate paths.")
        cmd = [
            occ_python,
            str(PIPELINE_SCRIPT),
            step_path,
            '--material', material,
            '--part-name', part_name,
            '--out-dir', str(Path(step_path).parent),
        ]
        result = subprocess.run(
            cmd,
            cwd=str(PIPELINE_DIR),
            capture_output=True,
            text=True,
        )
        stop_event.set()
        watcher.join(timeout=3)

        if result.returncode != 0:
            jobs[job_id]['status'] = 'FAILED'
            jobs[job_id]['error'] = result.stderr[-2000:] if result.stderr else 'Pipeline failed'
        else:
            # Final pass — load any outputs not yet picked up by watcher
            for stage_num, stage_name, suffix in STAGE_OUTPUTS:
                out = Path(str(base) + suffix)
                if out.exists() and suffix.endswith('.json'):
                    key = suffix.lstrip('_').replace('.json', '')
                    if key not in jobs[job_id]['outputs']:
                        with open(out) as f:
                            jobs[job_id]['outputs'][key] = json.load(f)

            pdf_path = Path(str(base) + '_program_sheet.pdf')
            if pdf_path.exists():
                jobs[job_id]['outputs']['pdf_path'] = str(pdf_path)

            jobs[job_id]['status'] = 'COMPLETE'
            jobs[job_id]['stage'] = 9
            jobs[job_id]['stage_name'] = 'complete'

    except Exception as e:
        stop_event.set()
        jobs[job_id]['status'] = 'FAILED'
        jobs[job_id]['error'] = str(e)


def start_pipeline(job_id: str, step_path: str, material: str, part_name: str, jobs: dict):
    t = threading.Thread(
        target=run_pipeline,
        args=(job_id, step_path, material, part_name, jobs),
        daemon=True
    )
    t.start()
