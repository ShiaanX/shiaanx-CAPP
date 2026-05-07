"""
agent_retrain.py — Download a chosen dataset, check it contains usable STEP files
with MFCAD++ compatible labels, merge with existing training data, retrain RF.

Returns new accuracy and model path. Does NOT promote — that is agent_promote.py's job.
"""

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split

BASE          = Path(__file__).parent.parent
MODELS_DIR    = BASE / "models"
STEP_TEST     = BASE / "Dataset/MFCAD_dataset/MFCAD++_dataset/step/test"
TAXONOMY_PATH = BASE / "rule_sheets/07_label_taxonomy.json"
STAGING_DIR   = BASE / "Autonomous Agent/staging"

PYTHON = sys.executable

_ADVANCED_FACE_RE = re.compile(r"ADVANCED_FACE\s*\(\s*'(\d+)'", re.IGNORECASE)

# Use the canonical feature extractor from classify_features.py — same as v3 training
_clf_spec = importlib.util.spec_from_file_location(
    "classify_features", str(BASE / "3. classify_features.py"))
_clf_mod = importlib.util.module_from_spec(_clf_spec)
_clf_spec.loader.exec_module(_clf_mod)
_extract_ml_features = _clf_mod._extract_ml_features  # (features_data: dict) -> ndarray


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _load_feat_data(feat_path: Path) -> dict | None:
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


def _collect_existing_data(max_parts: int = 8000) -> tuple:
    """Load features + labels. STEP at test/<id>.step; features at test/<id>/<id>_features.json."""
    X_all, y_all = [], []
    step_files = sorted(
        list(STEP_TEST.glob("*.step")) + list(STEP_TEST.glob("*.STEP"))
    ) if STEP_TEST.exists() else []
    count = 0
    for sf in step_files:
        if count >= max_parts:
            break
        feat_path = STEP_TEST / sf.stem / f"{sf.stem}_features.json"
        if not feat_path.exists():
            continue
        feat_data = _load_feat_data(feat_path)
        if feat_data is None:
            continue
        gt = _get_gt_labels(sf)
        if not gt or _n_faces(feat_data) != len(gt):
            continue
        try:
            X = _extract_ml_features(feat_data)
        except Exception:
            continue
        if len(X) == 0:
            continue
        X_all.append(X)
        y_all.extend(gt)
        count += 1
    return np.vstack(X_all) if X_all else np.empty((0, 15)), np.array(y_all)


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def _get_kaggle_token() -> str | None:
    """Same token resolution as agent_search — KGAT_ bearer or classic kaggle.json."""
    import base64
    token = os.environ.get("KAGGLE_API_TOKEN", "")
    if token:
        return token
    token_file = Path.home() / ".kaggle" / "access_token"
    if token_file.exists():
        t = token_file.read_text().strip()
        if t:
            return t
    json_file = Path.home() / ".kaggle" / "kaggle.json"
    if json_file.exists():
        try:
            creds = json.loads(json_file.read_text())
            return "basic:" + base64.b64encode(f"{creds['username']}:{creds['key']}".encode()).decode()
        except Exception:
            pass
    return None


def download_kaggle_dataset(ref: str) -> Path:
    """Download a Kaggle dataset by ref (owner/dataset-name) into staging/."""
    dest = STAGING_DIR / ref.replace("/", "__")
    dest.mkdir(parents=True, exist_ok=True)
    print(f"[retrain] Downloading Kaggle dataset: {ref}")

    token = _get_kaggle_token()
    if not token:
        raise RuntimeError("No Kaggle credentials found. Place access_token at ~/.kaggle/access_token")

    auth_header = f"Basic {token[6:]}" if token.startswith("basic:") else f"Bearer {token}"

    # Get download URL from Kaggle API — path is /datasets/download/{owner}/{dataset}
    owner, dataset_slug = ref.split("/", 1)
    api_url = f"https://www.kaggle.com/api/v1/datasets/download/{owner}/{dataset_slug}"
    zip_path = dest / "dataset.zip"
    req = urllib.request.Request(api_url, headers={"Authorization": auth_header})
    with urllib.request.urlopen(req, timeout=600) as resp:
        with open(zip_path, "wb") as f:
            while chunk := resp.read(1024 * 1024):
                f.write(chunk)

    # Unzip
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(dest)
    zip_path.unlink()

    print(f"[retrain] Downloaded to {dest}")
    return dest


def count_step_files(folder: Path) -> int:
    return len(list(folder.rglob("*.step"))) + len(list(folder.rglob("*.STEP")))


# ---------------------------------------------------------------------------
# Main retrain
# ---------------------------------------------------------------------------

def retrain(new_data_dir: Path = None, version_tag: str = "candidate") -> dict:
    """
    Retrain RF on existing data + optional new_data_dir.
    Saves candidate model to models/rf_classifier_{version_tag}.pkl.
    Returns {accuracy, model_path, n_faces}.
    """
    print("[retrain] Collecting existing training data...")
    X, y = _collect_existing_data()
    print(f"[retrain] Existing data: {len(y):,} faces")

    if new_data_dir and new_data_dir.exists():
        step_files = list(new_data_dir.rglob("*.step")) + list(new_data_dir.rglob("*.STEP"))
        print(f"[retrain] New dataset has {len(step_files)} STEP files — checking for GT labels...")
        added = 0
        for sf in step_files[:2000]:
            gt = _get_gt_labels(sf)
            if not gt:
                continue  # no MFCAD++ labels in ADVANCED_FACE names
            feat_path = sf.with_suffix("").with_name(sf.stem + "_features.json")
            if feat_path.exists():
                fd = _load_feat_data(feat_path)
                if fd is None or _n_faces(fd) != len(gt):
                    continue
                try:
                    Xn = _extract_ml_features(fd)
                except Exception:
                    continue
                if len(Xn) == len(gt):
                    X = np.vstack([X, Xn])
                    y = np.concatenate([y, gt])
                    added += 1
        print(f"[retrain] Added {added} new parts from new dataset")

    if len(y) == 0:
        raise RuntimeError("No training data available.")

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    print(f"[retrain] Training RF on {len(y_train):,} faces, testing on {len(y_test):,}...")

    clf = RandomForestClassifier(n_estimators=200, n_jobs=-1, random_state=42)
    t0  = time.time()
    clf.fit(X_train, y_train)
    print(f"[retrain] Trained in {time.time()-t0:.1f}s")

    y_pred = clf.predict(X_test)
    acc    = accuracy_score(y_test, y_pred)
    print(f"[retrain] Candidate accuracy: {acc*100:.2f}%")

    model_path   = MODELS_DIR / f"rf_classifier_{version_tag}.pkl"
    encoder_path = MODELS_DIR / f"rf_label_encoder_{version_tag}.json"
    MODELS_DIR.mkdir(exist_ok=True)
    joblib.dump(clf, model_path)

    classes = sorted(set(y.tolist()))
    encoder = {str(c): i for i, c in enumerate(classes)}
    with open(encoder_path, "w") as f:
        json.dump(encoder, f)

    return {
        "accuracy":    round(acc, 4),
        "model_path":  str(model_path),
        "n_faces":     len(y),
        "version_tag": version_tag,
    }


if __name__ == "__main__":
    result = retrain()
    print(json.dumps(result, indent=2))
