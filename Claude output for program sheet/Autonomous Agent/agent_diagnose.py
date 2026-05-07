"""
agent_diagnose.py — Load the current RF model, run it against the MFCAD++ test set,
and return the N weakest feature classes by F1 score.

Returns a dict ready to pass to the Gemini decision prompt.
"""

import importlib.util
import json
import re
import time
from pathlib import Path

import joblib
import numpy as np
from sklearn.metrics import classification_report, accuracy_score

BASE          = Path(__file__).parent.parent
MODELS_DIR    = BASE / "models"
STEP_TEST     = BASE / "Dataset/MFCAD_dataset/MFCAD++_dataset/step/test"
TAXONOMY_PATH = BASE / "rule_sheets/07_label_taxonomy.json"
OUTPUT_PATH   = MODELS_DIR / "perclass_f1_current.json"

_ADVANCED_FACE_RE = re.compile(r"ADVANCED_FACE\s*\(\s*'(\d+)'", re.IGNORECASE)

# Use the canonical feature extractor from classify_features.py — same as v3 training
_clf_spec = importlib.util.spec_from_file_location(
    "classify_features", str(BASE / "3. classify_features.py"))
_clf_mod = importlib.util.module_from_spec(_clf_spec)
_clf_spec.loader.exec_module(_clf_mod)
_extract_ml_features = _clf_mod._extract_ml_features  # signature: (features_data: dict) -> ndarray


def _load_taxonomy() -> dict:
    with open(TAXONOMY_PATH) as f:
        data = json.load(f)
    return {m["mfcad_id"]: m["mfcad_name"] for m in data["mappings"]}


def _get_gt_labels(step_path: Path) -> list:
    labels = []
    with open(step_path, "r", errors="replace") as f:
        for line in f:
            m = _ADVANCED_FACE_RE.search(line)
            if m:
                labels.append(int(m.group(1)))
    return labels


def _load_features_json(feat_path: Path) -> dict | None:
    """Return full JSON dict, or None on parse error."""
    try:
        with open(feat_path, encoding="utf-8", errors="replace") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _n_faces(feat_data: dict) -> int:
    face_block = feat_data.get("faces", {})
    if isinstance(face_block, dict):
        return len(face_block.get("faces", []))
    return len(feat_data.get("features", []))


def _find_best_model() -> tuple:
    for ver in ["v3", "v2", "v1", ""]:
        suffix = f"_{ver}" if ver else ""
        mp = MODELS_DIR / f"rf_classifier{suffix}.pkl"
        ep = MODELS_DIR / f"rf_label_encoder{suffix}.json"
        if mp.exists() and ep.exists():
            return mp, ep, ver or "baseline"
    raise FileNotFoundError("No RF model found in models/")


def run(top_n: int = 5, max_parts: int = 500) -> dict:
    """
    Evaluate current best model on up to max_parts STEP files.
    Returns dict with overall_accuracy and weakest N classes.
    """
    taxonomy = _load_taxonomy()
    model_path, encoder_path, version = _find_best_model()
    print(f"[diagnose] Using model: {model_path.name} (version={version})")

    clf = joblib.load(model_path)

    # STEP files: test/<id>.step  |  features: test/<id>/<id>_features.json
    step_files = sorted(
        list(STEP_TEST.glob("*.step")) + list(STEP_TEST.glob("*.STEP"))
    ) if STEP_TEST.exists() else []

    X_all, y_all = [], []
    parts_used = 0

    for sf in step_files:
        if parts_used >= max_parts:
            break
        feat_path = STEP_TEST / sf.stem / f"{sf.stem}_features.json"
        if not feat_path.exists():
            continue
        feat_data = _load_features_json(feat_path)
        if feat_data is None:
            continue
        gt = _get_gt_labels(sf)
        if not gt or _n_faces(feat_data) != len(gt):
            continue
        try:
            X = _extract_ml_features(feat_data)
        except Exception:
            continue
        X_all.append(X)
        y_all.extend(gt)
        parts_used += 1

    if not X_all:
        raise RuntimeError("No usable feature files found in test set.")

    X = np.vstack(X_all)
    y = np.array(y_all)

    print(f"[diagnose] Evaluating on {parts_used} parts, {len(y):,} faces...")
    t0 = time.time()
    y_pred = clf.predict(X)
    print(f"[diagnose] Inference in {time.time()-t0:.1f}s")

    acc = accuracy_score(y, y_pred)
    labels_present = sorted(np.unique(np.concatenate([y, y_pred])))
    target_names   = [taxonomy.get(int(l), f"class_{l}") for l in labels_present]

    report = classification_report(
        y, y_pred, labels=labels_present,
        target_names=target_names, output_dict=True, zero_division=0,
    )

    per_class = {
        name: {
            "f1":        report[name]["f1-score"],
            "precision": report[name]["precision"],
            "recall":    report[name]["recall"],
            "support":   int(report[name]["support"]),
        }
        for name in target_names
        if name in report
    }

    weakest = sorted(per_class.items(), key=lambda x: x[1]["f1"])[:top_n]

    result = {
        "model_version":    version,
        "overall_accuracy": round(acc, 4),
        "parts_evaluated":  parts_used,
        "faces_evaluated":  len(y),
        "weakest_classes":  [{"class": name, **metrics} for name, metrics in weakest],
        "per_class":        per_class,
    }

    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(result, f, indent=2)

    print(f"[diagnose] Overall accuracy: {acc*100:.1f}%")
    print(f"[diagnose] Weakest classes:")
    for item in result["weakest_classes"]:
        print(f"  {item['class']:<35} F1={item['f1']:.3f}  support={item['support']:,}")

    return result


if __name__ == "__main__":
    run()
