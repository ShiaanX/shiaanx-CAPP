"""
ml_train_classifier_v4.py - RF classifier with 18 features (v3 + 3 cluster-proxy features).

New features vs v3 (15 → 18):
  comp_cyl_radius_mean  mean cylinder radius in B-Rep connected component
  comp_plane_frac       fraction of faces in component that are planes (wall-count proxy)
  comp_bbox_ddr         component z-range / (2 * mean_cyl_radius), capped at 10
                        — high for deep slots/passages, low for shallow pockets/bores

These three features give the model access to shape-level geometry that pure face-level
features cannot distinguish: slots (high DDR, 2 curved ends) vs pockets (many walls,
lower DDR) vs passages (very high DDR, no cylinder caps).

Expected improvement: weak classes (rectangular_blind_slot F1=0.044, triangular_passage
F1=0.224) should improve significantly; strong classes (through_hole, stock) are unaffected.

Usage:
    conda run -n occ python "Claude output for program sheet/ml_train_classifier_v4.py"

Prerequisites:
    *_features.json must exist for MFCAD++ test parts.
    Run ml_batch_extract.py first if not already done.
"""

import importlib.util
import json
import re
import sys
import time
import warnings
from collections import Counter
from datetime import date
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")

BASE       = Path(__file__).parent
STEP_TEST  = BASE / "Dataset/MFCAD_dataset/MFCAD++_dataset/step/test"
MODELS_DIR = BASE / "models"
MODELS_DIR.mkdir(exist_ok=True)

MODEL_PATH   = MODELS_DIR / "rf_classifier_v4.pkl"
ENCODER_PATH = MODELS_DIR / "rf_label_encoder_v4.json"
METRICS_PATH = BASE / "metrics_log.csv"
TAXONOMY_PATH = BASE / "rule_sheets/07_label_taxonomy.json"

TRAIN_SPLIT = 0.8

FEAT_NAMES = [
    # v3 features
    "area", "cx", "cy", "cz", "surf_type",
    "neigh_degree", "neigh_type_mean", "neigh_type_std", "neigh_area_mean", "neigh_area_std",
    "comp_size", "comp_type_diversity", "comp_area_ratio", "two_hop_degree", "comp_aspect_ratio",
    # v4 additions
    "comp_cyl_radius_mean", "comp_plane_frac", "comp_bbox_ddr",
]


# ---------------------------------------------------------------------------
# GT label extraction from STEP file
# ---------------------------------------------------------------------------

_ADVANCED_FACE_RE = re.compile(r"ADVANCED_FACE\s*\(\s*'(\d+)'", re.IGNORECASE)


def get_gt_labels(step_path: Path) -> list:
    labels = []
    with open(step_path, "r", errors="replace") as f:
        for line in f:
            m = _ADVANCED_FACE_RE.search(line)
            if m:
                labels.append(int(m.group(1)))
    return labels


# ---------------------------------------------------------------------------
# Find STEP + features.json pairs
# ---------------------------------------------------------------------------

def find_pairs():
    pairs = []
    for step_path in sorted(STEP_TEST.rglob("*.step")):
        stem = step_path.stem
        candidates = [
            step_path.parent / f"{stem}_features.json",
            step_path.parent / stem / f"{stem}_features.json",
        ]
        for fp in candidates:
            if fp.exists():
                pairs.append((step_path, fp))
                break
    return pairs


# ---------------------------------------------------------------------------
# Dataset loader
# ---------------------------------------------------------------------------

def load_dataset(pairs: list, extractor_fn) -> tuple:
    X_parts, y_parts = [], []
    skipped = 0
    t0 = time.time()

    for i, (step_path, feat_path) in enumerate(pairs):
        if i % 50 == 0:
            elapsed = time.time() - t0
            print(f"  {i}/{len(pairs)} ({elapsed:.0f}s)  loaded={len(X_parts)}  "
                  f"skipped={skipped}", end="\r")

        gt_labels = get_gt_labels(step_path)
        if not gt_labels:
            skipped += 1
            continue

        try:
            with open(feat_path) as f:
                feat_data = json.load(f)
        except (json.JSONDecodeError, KeyError):
            skipped += 1
            continue

        n_pipeline = len(feat_data["faces"]["faces"])
        if n_pipeline != len(gt_labels):
            skipped += 1
            continue

        try:
            X = extractor_fn(feat_data)
        except Exception:
            skipped += 1
            continue

        X_parts.append(X)
        y_parts.append(np.array(gt_labels, dtype=np.int32))

    elapsed = time.time() - t0
    n_loaded = len(X_parts)
    print(f"  {len(pairs)}/{len(pairs)} done in {elapsed:.1f}s  "
          f"loaded={n_loaded}  skipped={skipped}          ")

    if not X_parts:
        raise RuntimeError(
            "No usable parts found.  Run ml_batch_extract.py first.")

    X = np.concatenate(X_parts, axis=0)
    y = np.concatenate(y_parts, axis=0)
    return X, y, n_loaded


# ---------------------------------------------------------------------------
# Train / evaluate
# ---------------------------------------------------------------------------

def train(X_train, y_train):
    from sklearn.ensemble import RandomForestClassifier
    print(f"\nTraining Random Forest v4 ({X_train.shape[1]} features)...")
    t0 = time.time()
    clf = RandomForestClassifier(
        n_estimators=200, min_samples_leaf=2, n_jobs=-1, random_state=42)
    clf.fit(X_train, y_train)
    print(f"  Done in {time.time()-t0:.1f}s")
    return clf


def evaluate(clf, X_test, y_test, taxonomy: dict) -> dict:
    from sklearn.metrics import classification_report, accuracy_score
    print("\nEvaluating...")
    t0 = time.time()
    y_pred = clf.predict(X_test)
    acc = accuracy_score(y_test, y_pred)
    print(f"  Done in {time.time()-t0:.1f}s")
    print(f"\n  Overall accuracy: {acc*100:.1f}%  ({int(acc*len(y_test)):,}/{len(y_test):,} faces)\n")

    labels_present = sorted(np.unique(np.concatenate([y_test, y_pred])))
    target_names   = [taxonomy.get(int(l), f"class_{l}") for l in labels_present]
    report = classification_report(
        y_test, y_pred, labels=labels_present,
        target_names=target_names, digits=3, zero_division=0)
    print(report)

    print("  Feature importances:")
    for name, imp in sorted(zip(FEAT_NAMES, clf.feature_importances_), key=lambda x: -x[1]):
        bar = "|" * int(imp * 50)
        print(f"    {name:30s} {imp:.4f}  {bar}")

    return {"accuracy": acc, "report": report}


def save_model(clf, taxonomy: dict):
    import joblib
    joblib.dump(clf, MODEL_PATH)
    with open(ENCODER_PATH, "w") as f:
        json.dump({str(k): v for k, v in taxonomy.items()}, f, indent=2)
    print(f"\n  Model saved:   {MODEL_PATH}")
    print(f"  Encoder saved: {ENCODER_PATH}")


def log_metrics(accuracy: float, n_train: int, n_test: int, n_parts: int):
    today = date.today().isoformat()
    header = not METRICS_PATH.exists()
    with open(METRICS_PATH, "a") as f:
        if header:
            f.write("date,model,n_train_faces,n_test_faces,overall_accuracy,notes\n")
        f.write(f"{today},rf_mfcad_v4,{n_train},{n_test},{accuracy:.4f},"
                f"RandomForest 18-feat cluster-proxy {n_parts}-parts\n")
    print(f"  Metrics logged: {METRICS_PATH}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("ShiaanX — MFCAD++ Random Forest v4 (18 features + cluster-proxy)")
    print("=" * 60)

    # Import v4 extractor from classify_features
    spec = importlib.util.spec_from_file_location(
        "classify_features", str(BASE / "3. classify_features.py"))
    clf_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(clf_mod)
    extractor = clf_mod._extract_ml_features_v4

    with open(TAXONOMY_PATH) as f:
        taxonomy_data = json.load(f)
    taxonomy = {m["mfcad_id"]: m["mfcad_name"] for m in taxonomy_data["mappings"]}

    print("\nScanning for STEP + features.json pairs...")
    pairs = find_pairs()
    print(f"  Found {len(pairs)} parts with features.json")

    if len(pairs) < 10:
        print("\nToo few parts.  Run ml_batch_extract.py first:")
        print("  conda run -n occ python \"Claude output for program sheet/ml_batch_extract.py\"")
        sys.exit(1)

    rng = np.random.default_rng(42)
    idx = rng.permutation(len(pairs))
    n_train_parts = int(len(pairs) * TRAIN_SPLIT)
    train_pairs = [pairs[i] for i in idx[:n_train_parts]]
    test_pairs  = [pairs[i] for i in idx[n_train_parts:]]

    print(f"\nLoading training data ({len(train_pairs)} parts)...")
    X_train, y_train, n_tr = load_dataset(train_pairs, extractor)
    print(f"  {X_train.shape[0]:,} faces, {X_train.shape[1]} features, "
          f"{len(np.unique(y_train))} classes")
    print(f"  Label distribution (top 5): "
          f"{Counter(y_train.tolist()).most_common(5)}")

    print(f"\nLoading test data ({len(test_pairs)} parts)...")
    X_test, y_test, n_te = load_dataset(test_pairs, extractor)
    print(f"  {X_test.shape[0]:,} faces")

    clf = train(X_train, y_train)
    results = evaluate(clf, X_test, y_test, taxonomy)
    save_model(clf, taxonomy)
    log_metrics(results["accuracy"], len(X_train), len(X_test), n_tr + n_te)

    print("\nDone.")


if __name__ == "__main__":
    main()
