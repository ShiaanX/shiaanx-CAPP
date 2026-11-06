"""
Job Manifest — Closed Loop Data Capture, Component 1

Persists a per-job status ledger (job.json) so job state survives a
capp_service restart and every closed-loop artifact for a job is
discoverable from one place, instead of being inferred from which
filename suffixes happen to exist on disk.

Usage (library):
    from job_manifest import create_job, update_status, register_artifact, load

Usage (CLI — backfill a manifest for an existing job folder):
    python job_manifest.py backfill "<job_dir>" --part-name "MOTOR MOUNT" --status ONGOING_PRODUCTION
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

MANIFEST_FILENAME = "job.json"

# Status values mirror the Milestones tab's job-status list.
STATUSES = [
    "QUOTED",
    "RM_TOOLS_PROCUREMENT",
    "QUEUED",
    "ONGOING_PRODUCTION",
    "QC",
    "PASS",
    "FAIL",
    "REWORK",
    "DISPATCH",
]

# Artifact keys this closed-loop build produces or expects, mapped to the
# filename suffix/pattern used to auto-discover them under a job dir.
ARTIFACT_PATTERNS = {
    "features": "*_features.json",
    "clustered": "*_clustered.json",
    "classified": "*_classified.json",
    "processes": "*_processes.json",
    "setups": "*_setups.json",
    "tools": "*_tools.json",
    "params": "*_params.json",
    "program_sheet": "*_program_sheet*.pdf",
    "datums": "*.datums.json",
    "features_datumed": "*_features_datumed.json",
    "tolerances": "*_tolerances.json",
    "inspection_template": "*_inspection_template.xlsx",
    "fixture_record": "*_fixture_record.xlsx",
    "actual_process": "actual_process.json",
    "baseline_accuracy_report": "baseline_accuracy_report.json",
    "override_log": "override_log.json",
    "machine_data": "machine_data.json",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _manifest_path(job_dir: Path) -> Path:
    return Path(job_dir) / MANIFEST_FILENAME


def discover_artifacts(job_dir: Path) -> dict:
    """Scan a job folder and return {artifact_key: relative_path} for whatever exists."""
    job_dir = Path(job_dir)
    found = {}
    for key, pattern in ARTIFACT_PATTERNS.items():
        matches = sorted(job_dir.glob(pattern))
        if matches:
            found[key] = matches[0].name
    return found


def create_job(job_dir: Path, job_id: str, part_name: str, material: str = "aluminium",
               status: str = "QUEUED") -> dict:
    job_dir = Path(job_dir)
    job_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "job_id": job_id,
        "part_name": part_name,
        "material": material,
        "status": status,
        "status_history": [{"status": status, "at": _now(), "note": "job created"}],
        "artifacts": discover_artifacts(job_dir),
        "created_at": _now(),
        "updated_at": _now(),
    }
    _write(job_dir, manifest)
    return manifest


def load(job_dir: Path) -> dict | None:
    path = _manifest_path(job_dir)
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write(job_dir: Path, manifest: dict) -> None:
    manifest["updated_at"] = _now()
    with open(_manifest_path(job_dir), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


def update_status(job_dir: Path, status: str, note: str = "") -> dict:
    if status not in STATUSES:
        raise ValueError(f"Unknown status {status!r}. Must be one of {STATUSES}")
    manifest = load(job_dir)
    if manifest is None:
        raise FileNotFoundError(f"No manifest at {job_dir} — call create_job() first")
    manifest["status"] = status
    manifest["status_history"].append({"status": status, "at": _now(), "note": note})
    _write(job_dir, manifest)
    return manifest


def update_fields(job_dir: Path, **fields) -> dict:
    """Merge arbitrary extra fields into the manifest (e.g. pipeline_status/stage,
    which are a separate concept from the shop-floor `status` enum above)."""
    manifest = load(job_dir)
    if manifest is None:
        raise FileNotFoundError(f"No manifest at {job_dir} — call create_job() first")
    manifest.update(fields)
    _write(job_dir, manifest)
    return manifest


def register_artifact(job_dir: Path, key: str, filename: str) -> dict:
    """Record that a specific artifact now exists for this job (called by producing scripts)."""
    manifest = load(job_dir)
    if manifest is None:
        raise FileNotFoundError(f"No manifest at {job_dir} — call create_job() first")
    manifest["artifacts"][key] = filename
    _write(job_dir, manifest)
    return manifest


def refresh_artifacts(job_dir: Path) -> dict:
    """Re-scan the job folder for known artifact patterns and merge into the manifest."""
    manifest = load(job_dir)
    if manifest is None:
        raise FileNotFoundError(f"No manifest at {job_dir} — call create_job() first")
    manifest["artifacts"].update(discover_artifacts(job_dir))
    _write(job_dir, manifest)
    return manifest


def _cli():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    backfill = sub.add_parser("backfill", help="Create/refresh a manifest for an existing job folder")
    backfill.add_argument("job_dir")
    backfill.add_argument("--job-id", default=None, help="Defaults to the job folder name")
    backfill.add_argument("--part-name", required=True)
    backfill.add_argument("--material", default="aluminium")
    backfill.add_argument("--status", default="QUEUED", choices=STATUSES)

    status_cmd = sub.add_parser("set-status", help="Update the status of an existing job manifest")
    status_cmd.add_argument("job_dir")
    status_cmd.add_argument("status", choices=STATUSES)
    status_cmd.add_argument("--note", default="")

    show = sub.add_parser("show", help="Print an existing job manifest")
    show.add_argument("job_dir")

    args = parser.parse_args()
    job_dir = Path(args.job_dir)

    if args.command == "backfill":
        job_id = args.job_id or job_dir.name
        existing = load(job_dir)
        if existing:
            manifest = refresh_artifacts(job_dir)
            print(f"Refreshed existing manifest at {job_dir / MANIFEST_FILENAME}")
        else:
            manifest = create_job(job_dir, job_id, args.part_name, args.material, args.status)
            print(f"Created manifest at {job_dir / MANIFEST_FILENAME}")
        print(json.dumps(manifest, indent=2))

    elif args.command == "set-status":
        manifest = update_status(job_dir, args.status, args.note)
        print(json.dumps(manifest, indent=2))

    elif args.command == "show":
        manifest = load(job_dir)
        if manifest is None:
            print(f"No manifest found at {job_dir}")
        else:
            print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    _cli()
