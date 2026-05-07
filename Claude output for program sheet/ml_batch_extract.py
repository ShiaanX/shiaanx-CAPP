"""
ml_batch_extract.py - Generate *_features.json for all MFCAD++ test STEP files.

Runs extract_features.py on every STEP file in the test set that does not
already have a corresponding *_features.json.  Output files are placed next
to each STEP file (or in a stem/ subdirectory if the STEP is in one).

This only needs to run once.  Subsequent runs skip already-extracted parts.

Usage:
    conda run -n occ python "Claude output for program sheet/ml_batch_extract.py"
    conda run -n occ python "Claude output for program sheet/ml_batch_extract.py" --limit 500
    conda run -n occ python "Claude output for program sheet/ml_batch_extract.py" --workers 4
"""

import argparse
import multiprocessing
import os
import subprocess
import sys
import time
from pathlib import Path

BASE      = Path(__file__).parent
STEP_TEST = BASE / "Dataset/MFCAD_dataset/MFCAD++_dataset/step/test"


def features_path_for(step_path: Path) -> Path:
    """Always put *_features.json inside a stem/ subdirectory."""
    stem = step_path.stem
    return step_path.parent / stem / f"{stem}_features.json"


def _extract_worker(args):
    """Worker function for multiprocessing — extracts one STEP file."""
    python_exe, extract_script, step_path_str, out_path_str = args
    out_path = Path(out_path_str)
    if out_path.exists():
        return "skip"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            [python_exe, extract_script, step_path_str, out_path_str],
            capture_output=True, timeout=60,
        )
        if result.returncode == 0 and out_path.exists():
            return "ok"
        return f"fail:{result.stderr.decode()[:100]}"
    except subprocess.TimeoutExpired:
        return "timeout"
    except Exception as e:
        return f"error:{e}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                        help="Process at most N STEP files (for quick testing)")
    parser.add_argument("--workers", type=int,
                        default=max(1, os.cpu_count() - 1),
                        help="Parallel workers (default: CPU count - 1)")
    args = parser.parse_args()

    extract_script = str(BASE / "1. extract_features.py")
    python_exe = sys.executable

    all_steps = sorted(STEP_TEST.rglob("*.step"))
    if args.limit:
        all_steps = all_steps[: args.limit]

    todo = [p for p in all_steps if not features_path_for(p).exists()]
    already_done = len(all_steps) - len(todo)

    print(f"MFCAD++ test batch extractor")
    print(f"  Total STEP files : {len(all_steps)}")
    print(f"  Already extracted: {already_done}")
    print(f"  To process       : {len(todo)}")
    print(f"  Workers          : {args.workers}")

    if not todo:
        print("  Nothing to do.")
        return

    worker_args = [
        (python_exe, extract_script, str(p), str(features_path_for(p)))
        for p in todo
    ]

    t0 = time.time()
    ok = fail = 0

    with multiprocessing.Pool(processes=args.workers) as pool:
        for i, status in enumerate(pool.imap_unordered(_extract_worker, worker_args)):
            if status in ("ok", "skip"):
                ok += 1
            else:
                fail += 1
                if fail <= 5:
                    print(f"\n  [WARN] {status}")
            if (i + 1) % 10 == 0 or (i + 1) == len(todo):
                elapsed = time.time() - t0
                rate = (i + 1) / elapsed if elapsed > 0 else 0
                eta = (len(todo) - i - 1) / rate if rate > 0 else 0
                print(f"  {i+1}/{len(todo)} | {elapsed:.0f}s elapsed | "
                      f"ETA {eta:.0f}s | {rate:.1f} parts/s", end="\r")

    total = time.time() - t0
    print(f"\nDone: {ok} ok, {fail} failed, {total:.1f}s total "
          f"({total/max(ok,1):.2f}s/part, {args.workers} workers)")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
