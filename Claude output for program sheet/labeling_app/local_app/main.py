from __future__ import annotations

from collections import Counter
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
import threading
import traceback
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT
STATIC_ROOT = Path(__file__).resolve().parent / "static"
JOBS_ROOT = Path(__file__).resolve().parent / "jobs"
LABELING_JOBS_ROOT = Path(__file__).resolve().parent / "labeling_jobs"
CUSTOM_LABELS_PATH = Path(__file__).resolve().parent / "custom_labels.json"
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
SHARED_CODE_ROOT = PROJECT_ROOT.parent  # "Claude output for program sheet/" - the real CAPP pipeline, not a vendored copy
CHECKPOINT = PROJECT_ROOT / "model" / "hier_v1_model.pt"
DATASET_ROOT = PROJECT_ROOT / "resources" / "MFCAD++_labels"
VIEWER_HTML = PROJECT_ROOT / "viewer" / "step-viewer.html"
MAX_UPLOAD_BYTES = 500 * 1024 * 1024
ALLOWED_EXTENSIONS = {".step", ".stp"}

MFCADPP_LABELS = {
    0: "Chamfer",
    1: "Through hole",
    2: "Triangular passage",
    3: "Rectangular passage",
    4: "6-sided passage",
    5: "Triangular through slot",
    6: "Rectangular through slot",
    7: "Circular through slot",
    8: "Rectangular through step",
    9: "2-sided through step",
    10: "Slanted through step",
    11: "O-ring",
    12: "Blind hole",
    13: "Triangular pocket",
    14: "Rectangular pocket",
    15: "6-sided pocket",
    16: "Circular end pocket",
    17: "Rectangular blind slot",
    18: "Vertical circular end blind slot",
    19: "Horizontal circular end blind slot",
    20: "Triangular blind step",
    21: "Circular blind step",
    22: "Rectangular blind step",
    23: "Round",
    24: "Stock",
}
MFCADPP_LABEL_IDS = {label.casefold(): label_id for label_id, label in MFCADPP_LABELS.items()}

MODEL_BENCHMARK = {
    "dataset": "MFCAD++ validation split",
    "validation_accuracy": 0.9381594666461135,
    "validation_macro_f1": 0.9187464699204909,
    "validation_weighted_f1": 0.9379779974675794,
    "epoch": 12,
    "checkpoint": CHECKPOINT.name,
    "note": (
        "This is a held-out MFCAD++ validation benchmark, not the measured "
        "accuracy of an uploaded STEP file."
    ),
}

app = FastAPI(title="MFCAD++ STEP Feature Recognition", version="1.0.0")

# Cross-origin access for the admin app's inspection view, which creates the job for a part,
# sends its QC sheet and embeds /dimensions and /inspection.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def no_stale_pages(request, call_next):
    """HTML pages are revalidated on every load, so an edit to one shows up without a cache clear."""
    response = await call_next(request)
    if response.headers.get("content-type", "").startswith("text/html"):
        response.headers["Cache-Control"] = "no-cache"
    return response
jobs: dict[str, dict[str, Any]] = {}
labeling_jobs: dict[str, dict[str, Any]] = {}
jobs_lock = threading.Lock()
custom_labels_lock = threading.Lock()


def public_job(job: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in job.items() if key not in {"job_dir", "logs"}}


def persist_job(job: dict[str, Any]) -> None:
    job_dir = Path(job["job_dir"])
    job_dir.mkdir(parents=True, exist_ok=True)
    payload = {key: value for key, value in job.items() if key != "job_dir"}
    (job_dir / "job.json").write_text(json.dumps(payload, indent=2) + "\n")


def persist_labeling_job(job: dict[str, Any]) -> None:
    job_dir = Path(job["job_dir"])
    job_dir.mkdir(parents=True, exist_ok=True)
    payload = {key: value for key, value in job.items() if key != "job_dir"}
    (job_dir / "job.json").write_text(json.dumps(payload, indent=2) + "\n")


def update_job(job_id: str, **changes: Any) -> None:
    with jobs_lock:
        job = jobs[job_id]
        job.update(changes)
        persist_job(job)


def update_labeling_job(job_id: str, **changes: Any) -> None:
    with jobs_lock:
        job = labeling_jobs[job_id]
        job.update(changes)
        persist_labeling_job(job)


def append_log(job_id: str, phase: str, output: str) -> None:
    with jobs_lock:
        jobs[job_id].setdefault("logs", []).append({"phase": phase, "output": output[-12000:]})
        persist_job(jobs[job_id])


def append_labeling_log(job_id: str, phase: str, output: str) -> None:
    with jobs_lock:
        labeling_jobs[job_id].setdefault("logs", []).append({"phase": phase, "output": output[-12000:]})
        persist_labeling_job(labeling_jobs[job_id])


def run_command(job_id: str, phase: str, command: list[str], *, timeout: int = 1800) -> None:
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    output = "\n".join(part for part in (completed.stdout.strip(), completed.stderr.strip()) if part)
    append_log(job_id, phase, output)
    if completed.returncode:
        raise RuntimeError(f"{phase} failed: {output[-3000:]}")


def run_labeling_command(job_id: str, phase: str, command: list[str], *, timeout: int = 1800) -> None:
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    output = "\n".join(part for part in (completed.stdout.strip(), completed.stderr.strip()) if part)
    append_labeling_log(job_id, phase, output)
    if completed.returncode:
        raise RuntimeError(f"{phase} failed: {output[-3000:]}")


def artifact_url(job_id: str, filename: str) -> str:
    return f"/api/jobs/{job_id}/files/{quote(filename)}"


def labeling_artifact_url(job_id: str, filename: str) -> str:
    return f"/api/labeling-jobs/{job_id}/files/{quote(filename)}"


def build_result(job_id: str, job_dir: Path) -> dict[str, Any]:
    prediction_path = job_dir / "model_predictions.json"
    viewer_path = job_dir / "model_viewer_faces.json"
    predictions = json.loads(prediction_path.read_text())
    viewer = json.loads(viewer_path.read_text())

    feature_counts = Counter(feature["raw_feature_type"] for feature in viewer.get("features", []))
    outputs = [
        ("Input STEP", "input.step"),
        ("OCP feature extraction", "features.json"),
        ("Geometric clusters", "clustered.json"),
        ("Model predictions", "model_predictions.json"),
        ("Model prediction summary", "model_prediction_summary.md"),
        ("Viewer face contract", "model_viewer_faces.json"),
        ("Reviewer CSV", "model_feature_review.csv"),
        ("Review summary", "model_review_summary.md"),
        ("Standalone review", "model_review.html"),
        ("Manual labels JSON", "manual_annotations.json"),
        ("Manual labels CSV", "manual_annotations.csv"),
    ]
    available_outputs = [
        {"label": label, "filename": filename, "url": artifact_url(job_id, filename)}
        for label, filename in outputs
        if (job_dir / filename).exists()
    ]

    return {
        "benchmark": MODEL_BENCHMARK,
        "face_count": predictions.get("face_count", 0),
        "feature_count": viewer.get("metadata", {}).get("feature_count", 0),
        "covered_face_count": viewer.get("metadata", {}).get("covered_face_count", 0),
        "missing_face_count": viewer.get("metadata", {}).get("missing_face_count", 0),
        "feature_distribution": [
            {"label": label.replace("_", " ").title(), "raw_label": label, "count": count}
            for label, count in feature_counts.most_common()
        ],
        "face_distribution": predictions.get("label_distribution", []),
        "viewer_url": (
            f"/viewer/step-viewer.html"
            f"?url={quote(artifact_url(job_id, 'input.step'), safe='/')}"
        ),
        "faces_url": f"/api/jobs/{job_id}/faces",
        "annotations_url": f"/api/jobs/{job_id}/annotations",
        "review_url": artifact_url(job_id, "model_review.html"),
        "outputs": available_outputs,
        "classification_source": CHECKPOINT.name,
        "label_taxonomy": "MFCAD++ 25 classes",
    }


def annotation_face_count(job: dict[str, Any]) -> int:
    viewer_path = Path(job["job_dir"]) / "model_viewer_faces.json"
    if not viewer_path.exists():
        raise HTTPException(status_code=409, detail="Recognition must finish before labeling.")
    viewer = json.loads(viewer_path.read_text())
    return int(viewer.get("metadata", {}).get("total_faces_in_step_extraction", 0))


def normalize_annotations(job: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    """Validate manual groups and create a deterministic per-face label table."""
    total_faces = annotation_face_count(job)
    raw_groups = raw.get("annotations", [])
    if not isinstance(raw_groups, list):
        raise HTTPException(status_code=400, detail="annotations must be a list.")

    seen_faces: dict[int, str] = {}
    groups: list[dict[str, Any]] = []
    for position, raw_group in enumerate(raw_groups, start=1):
        if not isinstance(raw_group, dict):
            raise HTTPException(status_code=400, detail=f"Annotation {position} must be an object.")
        try:
            label_id = int(raw_group.get("label_id"))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"Annotation {position} has an invalid label ID.") from None
        if label_id not in MFCADPP_LABELS:
            raise HTTPException(status_code=400, detail=f"Annotation {position} label must be between 0 and 24.")

        raw_faces = raw_group.get("face_indices", [])
        if not isinstance(raw_faces, list) or not raw_faces:
            raise HTTPException(status_code=400, detail=f"Annotation {position} must contain at least one face.")
        try:
            face_indices = sorted({int(value) for value in raw_faces})
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"Annotation {position} has an invalid face index.") from None

        annotation_id = str(
            raw_group.get("feature_instance_id")
            or raw_group.get("annotation_id")
            or f"feature_{position:03d}"
        )
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", annotation_id):
            raise HTTPException(status_code=400, detail=f"Annotation {position} has an invalid annotation ID.")
        for face_index in face_indices:
            if face_index < 0 or face_index >= total_faces:
                raise HTTPException(
                    status_code=400,
                    detail=f"Face {face_index} is outside the valid range 0-{max(total_faces - 1, 0)}.",
                )
            if face_index in seen_faces:
                raise HTTPException(
                    status_code=400,
                    detail=f"Face {face_index} appears in both {seen_faces[face_index]} and {annotation_id}.",
                )
            seen_faces[face_index] = annotation_id

        groups.append(
            {
                "annotation_id": annotation_id,
                "feature_instance_id": annotation_id,
                "label_id": label_id,
                "label": MFCADPP_LABELS[label_id],
                "face_indices": face_indices,
                "face_count": len(face_indices),
                "surface_indices": face_indices,
                "surface_count": len(face_indices),
                "notes": str(raw_group.get("notes", "")).strip()[:2000],
            }
        )

    face_labels = [
        {
            "face_index": face_index,
            "label_id": group["label_id"],
            "label": group["label"],
            "annotation_id": group["annotation_id"],
            "feature_instance_id": group["feature_instance_id"],
        }
        for group in groups
        for face_index in group["face_indices"]
    ]
    face_labels.sort(key=lambda row: row["face_index"])
    return {
        "schema_version": "1.1",
        "job_id": job["job_id"],
        "part_name": job["original_name"],
        "source_step": "input.step",
        "taxonomy": "MFCAD++ 25 classes",
        "annotation_unit": "feature_instance",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "total_faces": total_faces,
        "labeled_face_count": len(face_labels),
        "unlabeled_face_count": max(total_faces - len(face_labels), 0),
        "feature_instance_count": len(groups),
        "annotations": groups,
        "face_labels": face_labels,
    }


def write_annotation_csv(path: Path, payload: dict[str, Any]) -> None:
    groups = {group["annotation_id"]: group for group in payload["annotations"]}
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "face_index",
                "label_id",
                "label",
                "annotation_id",
                "feature_instance_id",
                "surface_count",
                "notes",
            ],
        )
        writer.writeheader()
        for row in payload["face_labels"]:
            group = groups[row["annotation_id"]]
            writer.writerow({**row, "surface_count": group["surface_count"], "notes": group["notes"]})


def load_custom_labels() -> list[str]:
    if not CUSTOM_LABELS_PATH.exists():
        return []
    try:
        data = json.loads(CUSTOM_LABELS_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    labels = data.get("labels", []) if isinstance(data, dict) else []
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in labels:
        label = value.strip() if isinstance(value, str) else ""
        folded = label.casefold()
        if label and len(label) <= 120 and folded not in seen:
            cleaned.append(label)
            seen.add(folded)
    return cleaned


def remember_custom_labels(labels: list[str]) -> None:
    if not labels:
        return
    with custom_labels_lock:
        existing = load_custom_labels()
        known_lower = {label.casefold() for label in existing}
        changed = False
        for value in labels:
            label = value.strip()
            if label and len(label) <= 120 and label.casefold() not in known_lower:
                existing.append(label)
                known_lower.add(label.casefold())
                changed = True
        if changed:
            temporary_path = CUSTOM_LABELS_PATH.with_suffix(".tmp")
            temporary_path.write_text(json.dumps({"labels": existing}, indent=2) + "\n")
            temporary_path.replace(CUSTOM_LABELS_PATH)


def labeling_face_count(job: dict[str, Any]) -> int:
    features_path = Path(job["job_dir"]) / "features.json"
    if not features_path.exists():
        raise HTTPException(status_code=409, detail="STEP face extraction must finish before labeling.")
    features = json.loads(features_path.read_text())
    return int(features.get("faces", {}).get("total_faces", 0))


def normalize_open_annotations(job: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    """Validate open-vocabulary labels while keeping one manual label per face."""
    total_faces = labeling_face_count(job)
    raw_groups = raw.get("annotations", [])
    if not isinstance(raw_groups, list):
        raise HTTPException(status_code=400, detail="annotations must be a list.")

    seen_faces: dict[int, str] = {}
    groups: list[dict[str, Any]] = []
    for position, raw_group in enumerate(raw_groups, start=1):
        if not isinstance(raw_group, dict):
            raise HTTPException(status_code=400, detail=f"Annotation {position} must be an object.")
        label = str(raw_group.get("label", "")).strip()
        if not label or len(label) > 120:
            raise HTTPException(status_code=400, detail=f"Annotation {position} needs a label of 1-120 characters.")
        known_label_id = MFCADPP_LABEL_IDS.get(label.casefold())
        canonical_label = MFCADPP_LABELS[known_label_id] if known_label_id is not None else label

        raw_faces = raw_group.get("face_indices", [])
        if not isinstance(raw_faces, list) or not raw_faces:
            raise HTTPException(status_code=400, detail=f"Annotation {position} must contain at least one face.")
        try:
            face_indices = sorted({int(value) for value in raw_faces})
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"Annotation {position} has an invalid face index.") from None

        annotation_id = str(
            raw_group.get("feature_instance_id")
            or raw_group.get("annotation_id")
            or f"feature_{position:03d}"
        )
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", annotation_id):
            raise HTTPException(status_code=400, detail=f"Annotation {position} has an invalid annotation ID.")
        for face_index in face_indices:
            if face_index < 0 or face_index >= total_faces:
                raise HTTPException(
                    status_code=400,
                    detail=f"Face {face_index} is outside the valid range 0-{max(total_faces - 1, 0)}.",
                )
            if face_index in seen_faces:
                raise HTTPException(
                    status_code=400,
                    detail=f"Face {face_index} appears in both {seen_faces[face_index]} and {annotation_id}.",
                )
            seen_faces[face_index] = annotation_id

        groups.append(
            {
                "annotation_id": annotation_id,
                "feature_instance_id": annotation_id,
                "label": canonical_label,
                "label_id": known_label_id,
                "label_source": "MFCAD++" if known_label_id is not None else "custom",
                "face_indices": face_indices,
                "face_count": len(face_indices),
                "surface_indices": face_indices,
                "surface_count": len(face_indices),
                "notes": str(raw_group.get("notes", "")).strip()[:2000],
            }
        )

    face_labels = [
        {
            "face_index": face_index,
            "label": group["label"],
            "label_id": group["label_id"],
            "label_source": group["label_source"],
            "annotation_id": group["annotation_id"],
            "feature_instance_id": group["feature_instance_id"],
        }
        for group in groups
        for face_index in group["face_indices"]
    ]
    face_labels.sort(key=lambda row: row["face_index"])
    return {
        "schema_version": "1.1",
        "job_id": job["job_id"],
        "part_name": job["original_name"],
        "source_step": "input.step",
        "taxonomy": "Open vocabulary with MFCAD++ suggestions",
        "annotation_unit": "feature_instance",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "total_faces": total_faces,
        "labeled_face_count": len(face_labels),
        "unlabeled_face_count": max(total_faces - len(face_labels), 0),
        "feature_instance_count": len(groups),
        "annotations": groups,
        "face_labels": face_labels,
    }


def write_open_annotation_csv(path: Path, payload: dict[str, Any]) -> None:
    groups = {group["annotation_id"]: group for group in payload["annotations"]}
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "face_index",
                "label",
                "label_id",
                "label_source",
                "annotation_id",
                "feature_instance_id",
                "surface_count",
                "notes",
            ],
        )
        writer.writeheader()
        for row in payload["face_labels"]:
            group = groups[row["annotation_id"]]
            writer.writerow({**row, "surface_count": group["surface_count"], "notes": group["notes"]})


DIMENSION_TYPES = {"diameter", "radius", "linear", "center_distance", "depth", "thickness", "thread", "angle", "other"}
DIMENSION_TYPES_NEEDING_B = {"linear", "center_distance", "depth", "thickness", "angle"}


def _optional_number(value: Any, field: str, position: int, *, minimum: float | None = None) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"Dimension {position}: {field} must be a number.") from None
    if number != number or number in (float("inf"), float("-inf")):
        raise HTTPException(status_code=400, detail=f"Dimension {position}: {field} must be finite.")
    if minimum is not None and number < minimum:
        raise HTTPException(status_code=400, detail=f"Dimension {position}: {field} must be at least {minimum}.")
    return number


def _face_list(raw: Any, field: str, position: int, total_faces: int) -> list[int]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise HTTPException(status_code=400, detail=f"Dimension {position}: {field} must be a list.")
    try:
        faces = sorted({int(value) for value in raw})
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"Dimension {position}: {field} has an invalid face index.") from None
    for face_index in faces:
        if face_index < 0 or face_index >= total_faces:
            raise HTTPException(
                status_code=400,
                detail=f"Dimension {position}: face {face_index} is outside the valid range 0-{max(total_faces - 1, 0)}.",
            )
    return faces


def normalize_dimensions(job: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    """Validate balloon-keyed dimension tags. Unlike labels, one face may serve several dimensions."""
    total_faces = labeling_face_count(job)
    raw_items = raw.get("dimensions", [])
    if not isinstance(raw_items, list):
        raise HTTPException(status_code=400, detail="dimensions must be a list.")

    seen: set[int] = set()
    dimensions: list[dict[str, Any]] = []
    for position, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail=f"Dimension {position} must be an object.")
        try:
            balloon = int(item.get("balloon"))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"Dimension {position} needs an integer balloon number.") from None
        if balloon < 1:
            raise HTTPException(status_code=400, detail=f"Dimension {position}: balloon must be 1 or higher.")
        if balloon in seen:
            raise HTTPException(status_code=400, detail=f"Balloon {balloon} appears more than once.")
        seen.add(balloon)

        dim_type = str(item.get("dim_type", "other"))
        if dim_type not in DIMENSION_TYPES:
            raise HTTPException(status_code=400, detail=f"Balloon {balloon}: unknown dimension type '{dim_type}'.")
        faces_a = _face_list(item.get("faces_a"), "faces_a", position, total_faces)
        faces_b = _face_list(item.get("faces_b"), "faces_b", position, total_faces)
        if dim_type not in DIMENSION_TYPES_NEEDING_B:
            faces_b = []
        if set(faces_a) & set(faces_b):
            raise HTTPException(status_code=400, detail=f"Balloon {balloon}: faces A and B must not overlap.")

        needs_b = dim_type in DIMENSION_TYPES_NEEDING_B
        dimensions.append(
            {
                "balloon": balloon,
                "dim_type": dim_type,
                "description_raw": str(item.get("description_raw", ""))[:120],
                "nominal": _optional_number(item.get("nominal"), "nominal", position),
                "tol_plus": _optional_number(item.get("tol_plus"), "tol_plus", position, minimum=0),
                "tol_minus": _optional_number(item.get("tol_minus"), "tol_minus", position, minimum=0),
                "unit": "deg" if dim_type == "angle" else "mm",
                "faces_a": faces_a,
                "faces_b": faces_b,
                "notes": str(item.get("notes", "")).strip()[:2000],
                "tagged": bool(faces_a) and (bool(faces_b) or not needs_b),
            }
        )

    dimensions.sort(key=lambda entry: entry["balloon"])
    return {
        "schema_version": "1.0",
        "job_id": job["job_id"],
        "part_name": job["original_name"],
        "source_step": "input.step",
        "annotation_unit": "dimension",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "total_faces": total_faces,
        "dimension_count": len(dimensions),
        "tagged_count": sum(1 for entry in dimensions if entry["tagged"]),
        "dimensions": dimensions,
    }


def dimension_downloads(job_id: str) -> dict[str, str]:
    return {"json": f"/api/labeling-jobs/{job_id}/dimensions/download"}


def process_job(job_id: str) -> None:
    job = jobs[job_id]
    job_dir = Path(job["job_dir"])
    step_path = job_dir / "input.step"
    features_path = job_dir / "features.json"
    clusters_path = job_dir / "clustered.json"
    predictions_path = job_dir / "model_predictions.json"
    model_summary_path = job_dir / "model_prediction_summary.md"

    try:
        update_job(job_id, status="processing", phase="Extracting B-Rep geometry", progress=10)
        run_command(
            job_id,
            "extract",
            [sys.executable, str(SCRIPTS_ROOT / "extract_features_ocp.py"), str(step_path), str(features_path)],
        )

        update_job(job_id, phase="Clustering connected faces", progress=42)
        run_command(
            job_id,
            "cluster",
            [sys.executable, str(SHARED_CODE_ROOT / "2. cluster_features.py"), str(features_path), str(clusters_path)],
        )

        update_job(job_id, phase="Running trained MFCAD++ model", progress=62)
        run_command(
            job_id,
            "classify",
            [
                sys.executable,
                str(SCRIPTS_ROOT / "predict_step_with_model.py"),
                str(features_path),
                str(CHECKPOINT),
                "--dataset",
                str(DATASET_ROOT),
                "--clusters-json",
                str(clusters_path),
                "--device",
                "cpu",
                "--out",
                str(predictions_path),
                "--summary-out",
                str(model_summary_path),
            ],
        )

        update_job(job_id, phase="Building report and viewer data", progress=86)
        run_command(
            job_id,
            "export",
            [
                sys.executable,
                str(SCRIPTS_ROOT / "export_viewer_faces.py"),
                str(clusters_path),
                "--features-json",
                str(features_path),
                "--model-predictions-json",
                str(predictions_path),
                "--step-file",
                str(step_path),
                "--viewer-html",
                str(VIEWER_HTML),
                "--part-name",
                job["original_name"],
                "--out-dir",
                str(job_dir),
                "--prefix",
                "model",
                "--label-source",
                "model",
                "--write-review-html",
            ],
        )

        result = build_result(job_id, job_dir)
        update_job(
            job_id,
            status="completed",
            phase="Complete",
            progress=100,
            result=result,
            error=None,
        )
    except Exception as exc:
        append_log(job_id, "exception", traceback.format_exc())
        update_job(
            job_id,
            status="failed",
            phase="Failed",
            error=str(exc),
        )


def build_labeling_result(job_id: str, job_dir: Path) -> dict[str, Any]:
    features = json.loads((job_dir / "features.json").read_text())
    face_count = int(features.get("faces", {}).get("total_faces", 0))
    outputs = [
        ("Input STEP", "input.step"),
        ("OCP face extraction", "features.json"),
        ("Manual labels JSON", "manual_labels.json"),
        ("Manual labels CSV", "manual_labels.csv"),
    ]
    return {
        "face_count": face_count,
        "viewer_url": (
            f"/viewer/step-viewer.html"
            f"?url={quote(labeling_artifact_url(job_id, 'input.step'), safe='/')}"
        ),
        "annotations_url": f"/api/labeling-jobs/{job_id}/annotations",
        "outputs": [
            {"label": label, "filename": filename, "url": labeling_artifact_url(job_id, filename)}
            for label, filename in outputs
            if (job_dir / filename).exists()
        ],
    }


def process_labeling_job(job_id: str) -> None:
    job = labeling_jobs[job_id]
    job_dir = Path(job["job_dir"])
    step_path = job_dir / "input.step"
    features_path = job_dir / "features.json"
    try:
        update_labeling_job(job_id, status="processing", phase="Extracting STEP faces", progress=20)
        run_labeling_command(
            job_id,
            "extract",
            [sys.executable, str(SCRIPTS_ROOT / "extract_features_ocp.py"), str(step_path), str(features_path)],
        )
        result = build_labeling_result(job_id, job_dir)
        update_labeling_job(
            job_id,
            status="completed",
            phase="Ready for labeling",
            progress=100,
            result=result,
            error=None,
        )
    except Exception as exc:
        append_labeling_log(job_id, "exception", traceback.format_exc())
        update_labeling_job(job_id, status="failed", phase="Failed", error=str(exc))


def load_existing_jobs() -> None:
    JOBS_ROOT.mkdir(parents=True, exist_ok=True)
    for state_path in JOBS_ROOT.glob("*/job.json"):
        try:
            data = json.loads(state_path.read_text())
            data["job_dir"] = str(state_path.parent)
            data.setdefault("logs", [])
            if data.get("status") == "processing":
                data.update(status="failed", phase="Interrupted", error="The local server stopped during processing.")
            jobs[data["job_id"]] = data
        except (OSError, ValueError, KeyError):
            continue


def load_existing_labeling_jobs() -> None:
    LABELING_JOBS_ROOT.mkdir(parents=True, exist_ok=True)
    for state_path in LABELING_JOBS_ROOT.glob("*/job.json"):
        try:
            data = json.loads(state_path.read_text())
            data["job_dir"] = str(state_path.parent)
            data.setdefault("logs", [])
            if data.get("status") == "processing":
                data.update(status="failed", phase="Interrupted", error="The local server stopped during extraction.")
            labeling_jobs[data["job_id"]] = data
        except (OSError, ValueError, KeyError):
            continue


load_existing_jobs()
load_existing_labeling_jobs()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_ROOT / "index.html")


@app.get("/label")
def label_workspace() -> FileResponse:
    return FileResponse(STATIC_ROOT / "label.html")


@app.get("/dimensions")
def dimension_workspace() -> FileResponse:
    return FileResponse(STATIC_ROOT / "dimensions.html")


@app.get("/viewer/step-viewer.html")
def viewer() -> FileResponse:
    return FileResponse(VIEWER_HTML)


@app.get("/api/health")
def health() -> dict[str, Any]:
    missing = [
        str(path)
        for path in (CHECKPOINT, DATASET_ROOT, VIEWER_HTML, SHARED_CODE_ROOT)
        if not path.exists()
    ]
    return {
        "ok": not missing,
        "missing": missing,
        "model": MODEL_BENCHMARK,
        "job_count": len(jobs),
    }


@app.get("/api/jobs")
def list_jobs() -> dict[str, Any]:
    ordered = sorted(jobs.values(), key=lambda row: row.get("created_order", ""), reverse=True)
    return {"jobs": [public_job(job) for job in ordered[:20]]}


@app.post("/api/jobs", status_code=202)
async def create_job(file: UploadFile, background_tasks: BackgroundTasks) -> dict[str, Any]:
    original_name = Path(file.filename or "upload.step").name
    extension = Path(original_name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Upload a .step or .stp file.")

    job_id = uuid4().hex[:12]
    job_dir = JOBS_ROOT / job_id
    job_dir.mkdir(parents=True, exist_ok=False)
    step_path = job_dir / "input.step"
    total = 0
    try:
        with step_path.open("wb") as handle:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="STEP file exceeds the 500 MB limit.")
                handle.write(chunk)
    except Exception:
        if step_path.exists():
            step_path.unlink()
        raise
    finally:
        await file.close()

    job = {
        "job_id": job_id,
        "job_dir": str(job_dir),
        "original_name": original_name,
        "stored_filename": "input.step",
        "size_bytes": total,
        "status": "queued",
        "phase": "Queued",
        "progress": 0,
        "created_order": job_id,
        "benchmark": MODEL_BENCHMARK,
        "result": None,
        "error": None,
        "logs": [],
    }
    with jobs_lock:
        jobs[job_id] = job
        persist_job(job)
    background_tasks.add_task(process_job, job_id)
    return public_job(job)


@app.post("/api/labeling-jobs", status_code=202)
async def create_labeling_job(file: UploadFile, background_tasks: BackgroundTasks) -> dict[str, Any]:
    original_name = Path(file.filename or "upload.step").name
    extension = Path(original_name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Upload a .step or .stp file.")

    job_id = uuid4().hex[:12]
    job_dir = LABELING_JOBS_ROOT / job_id
    job_dir.mkdir(parents=True, exist_ok=False)
    step_path = job_dir / "input.step"
    total = 0
    try:
        with step_path.open("wb") as handle:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="STEP file exceeds the 500 MB limit.")
                handle.write(chunk)
    except Exception:
        if step_path.exists():
            step_path.unlink()
        raise
    finally:
        await file.close()

    job = {
        "job_id": job_id,
        "job_dir": str(job_dir),
        "original_name": original_name,
        "stored_filename": "input.step",
        "size_bytes": total,
        "status": "queued",
        "phase": "Queued",
        "progress": 0,
        "created_order": job_id,
        "result": None,
        "error": None,
        "logs": [],
    }
    with jobs_lock:
        labeling_jobs[job_id] = job
        persist_labeling_job(job)
    background_tasks.add_task(process_labeling_job, job_id)
    return public_job(job)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.get("status") == "completed":
        viewer_faces = Path(job["job_dir"]) / "model_viewer_faces.json"
        if viewer_faces.exists():
            job["result"] = build_result(job_id, Path(job["job_dir"]))
    return public_job(job)


@app.get("/api/labeling-jobs/{job_id}")
def get_labeling_job(job_id: str) -> dict[str, Any]:
    job = labeling_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Labeling job not found.")
    if job.get("status") == "completed" and (Path(job["job_dir"]) / "features.json").exists():
        job["result"] = build_labeling_result(job_id, Path(job["job_dir"]))
    return public_job(job)


@app.get("/api/jobs/{job_id}/faces")
def get_faces(job_id: str) -> FileResponse:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    path = Path(job["job_dir"]) / "model_viewer_faces.json"
    if not path.exists():
        raise HTTPException(status_code=409, detail="Viewer data is not ready.")
    return FileResponse(path, media_type="application/json")


@app.get("/api/jobs/{job_id}/annotations")
def get_annotations(job_id: str) -> dict[str, Any]:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    path = Path(job["job_dir"]) / "manual_annotations.json"
    if path.exists():
        payload = json.loads(path.read_text())
        payload["saved"] = True
        payload["downloads"] = {
            "json": artifact_url(job_id, "manual_annotations.json"),
            "csv": artifact_url(job_id, "manual_annotations.csv"),
        }
        return payload
    payload = normalize_annotations(job, {"annotations": []})
    payload["saved"] = False
    return payload


@app.put("/api/jobs/{job_id}/annotations")
def save_annotations(job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    normalized = normalize_annotations(job, payload)
    job_dir = Path(job["job_dir"])
    json_path = job_dir / "manual_annotations.json"
    csv_path = job_dir / "manual_annotations.csv"
    json_path.write_text(json.dumps(normalized, indent=2) + "\n")
    write_annotation_csv(csv_path, normalized)
    normalized["downloads"] = {
        "json": artifact_url(job_id, json_path.name),
        "csv": artifact_url(job_id, csv_path.name),
    }
    normalized["saved"] = True
    return normalized


@app.get("/api/labeling-jobs/{job_id}/annotations")
def get_open_annotations(job_id: str) -> dict[str, Any]:
    job = labeling_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Labeling job not found.")
    path = Path(job["job_dir"]) / "manual_labels.json"
    if path.exists():
        payload = json.loads(path.read_text())
        payload["saved"] = True
        payload["downloads"] = {
            "json": labeling_artifact_url(job_id, "manual_labels.json"),
            "csv": labeling_artifact_url(job_id, "manual_labels.csv"),
        }
        return payload
    payload = normalize_open_annotations(job, {"annotations": []})
    payload["saved"] = False
    return payload


@app.put("/api/labeling-jobs/{job_id}/annotations")
def save_open_annotations(job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    job = labeling_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Labeling job not found.")
    normalized = normalize_open_annotations(job, payload)
    job_dir = Path(job["job_dir"])
    json_path = job_dir / "manual_labels.json"
    csv_path = job_dir / "manual_labels.csv"
    json_path.write_text(json.dumps(normalized, indent=2) + "\n")
    write_open_annotation_csv(csv_path, normalized)
    remember_custom_labels([
        group["label"] for group in normalized["annotations"] if group["label_source"] == "custom"
    ])
    normalized["downloads"] = {
        "json": labeling_artifact_url(job_id, json_path.name),
        "csv": labeling_artifact_url(job_id, csv_path.name),
    }
    normalized["saved"] = True
    return normalized


@app.get("/api/custom-labels")
def get_custom_labels() -> dict[str, Any]:
    return {"labels": load_custom_labels()}


@app.get("/api/labeling-jobs/{job_id}/dimensions")
def get_dimensions(job_id: str) -> dict[str, Any]:
    job = labeling_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Labeling job not found.")
    path = Path(job["job_dir"]) / "dimension_tags.json"
    if path.exists():
        payload = json.loads(path.read_text())
        payload["saved"] = True
        payload["downloads"] = dimension_downloads(job_id)
        return payload
    payload = normalize_dimensions(job, {"dimensions": []})
    payload["saved"] = False
    return payload


@app.put("/api/labeling-jobs/{job_id}/dimensions")
def save_dimensions(job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    job = labeling_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Labeling job not found.")
    normalized = normalize_dimensions(job, payload)
    (Path(job["job_dir"]) / "dimension_tags.json").write_text(json.dumps(normalized, indent=2) + "\n")
    normalized["downloads"] = dimension_downloads(job_id)
    normalized["saved"] = True
    return normalized


@app.post("/api/labeling-jobs/{job_id}/dimensions/seed")
async def seed_dimensions(job_id: str, file: UploadFile) -> dict[str, Any]:
    """Read balloon numbers, nominals and tolerances from a QC inspection .xlsx (nothing is saved)."""
    if job_id not in labeling_jobs:
        raise HTTPException(status_code=404, detail="Labeling job not found.")
    if Path(file.filename or "").suffix.lower() != ".xlsx":
        raise HTTPException(status_code=400, detail="Upload the QC inspection report as an .xlsx file.")
    data = await file.read(20 * 1024 * 1024 + 1)
    await file.close()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="QC sheet exceeds the 20 MB limit.")
    from .qc_sheet import apply_face_links, parse_face_links, parse_qc_sheet

    try:
        rows = parse_qc_sheet(data)
    except RuntimeError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from None
    except Exception:
        raise HTTPException(status_code=400, detail="Could not read that file as an Excel workbook.") from None
    if not rows:
        raise HTTPException(status_code=422, detail="No numbered rows found under an 'SL No.' header.")
    response: dict[str, Any] = {"dimensions": rows}
    # Optional 'Face links' sheet: pre-made balloon -> CAD face links (additive; plain sheets are unaffected).
    try:
        links = parse_face_links(data)
    except Exception:
        links = {"links": {}}
    if links["links"]:
        import hashlib

        step = Path(labeling_jobs[job_id]["job_dir"]) / "input.step"
        job_sha = hashlib.sha256(step.read_bytes()).hexdigest() if step.is_file() else None
        try:
            job_faces = labeling_face_count(labeling_jobs[job_id])
        except HTTPException:
            job_faces = None
        response["face_links"] = apply_face_links(rows, links, job_sha256=job_sha, job_faces=job_faces)
    return response


@app.get("/api/labeling-jobs/{job_id}/dimensions/download")
def download_dimensions(job_id: str) -> FileResponse:
    job = labeling_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Labeling job not found.")
    path = Path(job["job_dir"]) / "dimension_tags.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Save the dimension tags first.")
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(job["original_name"]).stem) or "part"
    return FileResponse(path, filename=f"{stem}_dimension_tags.json", media_type="application/json")


def build_inspection_view(job: dict[str, Any]) -> dict[str, Any]:
    """Join a job's dimension tags with its saved QC readings and compute a verdict per balloon."""
    from .qc_sheet import evaluate_dimension

    job_dir = Path(job["job_dir"])
    tags_path = job_dir / "dimension_tags.json"
    tags = json.loads(tags_path.read_text()) if tags_path.exists() else {"dimensions": []}
    qc_path = job_dir / "qc_results.json"
    qc = json.loads(qc_path.read_text()) if qc_path.exists() else {"rows": []}
    qc_by_balloon = {row["balloon"]: row for row in qc["rows"]}

    results = []
    for dim in tags["dimensions"]:
        if not dim.get("tagged"):
            continue
        row = qc_by_balloon.get(dim["balloon"], {})
        nominal = dim.get("nominal") if dim.get("nominal") is not None else row.get("nominal")
        tol_plus = dim.get("tol_plus") if dim.get("tol_plus") is not None else row.get("tol_plus")
        tol_minus = dim.get("tol_minus") if dim.get("tol_minus") is not None else row.get("tol_minus")
        readings = row.get("readings", [])
        verdict = evaluate_dimension(nominal, tol_plus, tol_minus, readings)
        remark = row.get("sheet_remark", "")
        disagrees = (
            (verdict["verdict"] == "fail" and remark.strip().lower() in {"ok", "pass", "accepted"})
            or (verdict["verdict"] in {"pass", "near_limit"} and remark.strip().lower() in {"nok", "not ok", "fail", "rejected"})
        )
        results.append({
            "balloon": dim["balloon"],
            "dim_type": dim["dim_type"],
            "description_raw": dim.get("description_raw", ""),
            "notes": dim.get("notes", ""),
            "nominal": nominal,
            "tol_plus": tol_plus,
            "tol_minus": tol_minus,
            "unit": dim.get("unit", "mm"),
            "faces_a": dim["faces_a"],
            "faces_b": dim.get("faces_b", []),
            "readings": readings,
            "instrument": row.get("instrument", ""),
            "sheet_remark": remark,
            "remark_disagrees": disagrees,
            **verdict,
        })

    counts = {name: sum(1 for r in results if r["verdict"] == name) for name in ("pass", "near_limit", "fail", "pending", "unknown")}
    measured = counts["pass"] + counts["near_limit"] + counts["fail"]
    return {
        "job_id": job["job_id"],
        "part_name": tags.get("part_name") or job.get("original_name"),
        "has_qc": bool(qc["rows"]),
        "qc_source": qc.get("source_name"),
        "summary": {
            "total": len(results),
            "measured": measured,
            "within_tolerance": counts["pass"] + counts["near_limit"],
            "near_limit": counts["near_limit"],
            "out_of_tolerance": counts["fail"],
            "not_measured": counts["pending"] + counts["unknown"],
            "remark_disagreements": sum(1 for r in results if r["remark_disagrees"]),
        },
        "results": results,
    }


@app.get("/inspection")
def inspection_page() -> FileResponse:
    return FileResponse(STATIC_ROOT / "inspection.html")


@app.get("/api/dimension-jobs")
def list_dimension_jobs() -> dict[str, Any]:
    """Jobs that already have saved dimension tags, newest first."""
    found = []
    for job in labeling_jobs.values():
        path = Path(job["job_dir"]) / "dimension_tags.json"
        if not path.is_file():
            continue
        payload = json.loads(path.read_text())
        if not payload.get("tagged_count"):
            continue
        found.append({
            "job_id": job["job_id"],
            "original_name": job.get("original_name"),
            "tagged_count": payload["tagged_count"],
            "dimension_count": payload["dimension_count"],
            "updated_at": payload.get("updated_at", ""),
        })
    found.sort(key=lambda item: item["updated_at"], reverse=True)
    return {"jobs": found}


@app.get("/api/labeling-jobs/{job_id}/qc-results")
def get_qc_results(job_id: str) -> dict[str, Any]:
    job = labeling_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Labeling job not found.")
    return build_inspection_view(job)


@app.post("/api/labeling-jobs/{job_id}/qc-results")
async def upload_qc_results(job_id: str, file: UploadFile) -> dict[str, Any]:
    """Read measured values from a QC inspection .xlsx, save them with the job, return the verdicts."""
    job = labeling_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Labeling job not found.")
    if Path(file.filename or "").suffix.lower() != ".xlsx":
        raise HTTPException(status_code=400, detail="Upload the QC inspection report as an .xlsx file.")
    data = await file.read(20 * 1024 * 1024 + 1)
    await file.close()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="QC sheet exceeds the 20 MB limit.")
    from .qc_sheet import parse_qc_results

    try:
        rows = parse_qc_results(data)
    except RuntimeError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from None
    except Exception:
        raise HTTPException(status_code=400, detail="Could not read that file as an Excel workbook.") from None
    if not rows:
        raise HTTPException(status_code=422, detail="No numbered rows found under an 'SL No.' header.")
    payload = {"source_name": file.filename, "uploaded_at": datetime.now(timezone.utc).isoformat(), "rows": rows}
    (Path(job["job_dir"]) / "qc_results.json").write_text(json.dumps(payload, indent=2) + "\n")
    return build_inspection_view(job)


@app.get("/api/jobs/{job_id}/files/{filename:path}")
def get_artifact(job_id: str, filename: str) -> FileResponse:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", filename):
        raise HTTPException(status_code=400, detail="Invalid filename.")
    path = Path(job["job_dir"]) / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found.")
    return FileResponse(path, filename=None if filename.endswith(".html") else filename)


@app.get("/api/labeling-jobs/{job_id}/files/{filename:path}")
def get_labeling_artifact(job_id: str, filename: str) -> FileResponse:
    job = labeling_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Labeling job not found.")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", filename):
        raise HTTPException(status_code=400, detail="Invalid filename.")
    path = Path(job["job_dir"]) / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found.")
    return FileResponse(path)
