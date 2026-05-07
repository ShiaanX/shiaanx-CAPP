"""
agent_promote.py — Promote a candidate model to production if it beats the current best.

"Production" model = rf_classifier_v3.pkl (current best at 66.2%).
Keeps a backup of the replaced model. Updates metrics_log.csv.
"""

import json
import shutil
from datetime import date
from pathlib import Path

BASE        = Path(__file__).parent.parent
MODELS_DIR  = BASE / "models"
METRICS_LOG = BASE / "metrics_log.csv"
BACKUP_DIR  = MODELS_DIR / "backups"

PRODUCTION_MODEL   = MODELS_DIR / "rf_classifier_v3.pkl"
PRODUCTION_ENCODER = MODELS_DIR / "rf_label_encoder_v3.json"
CURRENT_BEST_ACC   = 0.6620  # v3 on 8789-part full dataset


def _read_current_best() -> float:
    """Read the highest accuracy from metrics_log.csv."""
    if not METRICS_LOG.exists():
        return CURRENT_BEST_ACC
    best = CURRENT_BEST_ACC
    with open(METRICS_LOG) as f:
        for line in f.readlines()[1:]:  # skip header
            parts = line.strip().split(",")
            if len(parts) >= 5:
                try:
                    acc = float(parts[4])
                    best = max(best, acc)
                except ValueError:
                    pass
    return best


def _append_metrics(model_name: str, acc: float, n_faces: int, notes: str):
    if not METRICS_LOG.exists():
        METRICS_LOG.write_text("date,model,n_train_faces,n_test_faces,overall_accuracy,notes\n")
    with open(METRICS_LOG, "a") as f:
        f.write(f"{date.today()},{model_name},{n_faces},,{acc:.4f},{notes}\n")


def promote(candidate_result: dict) -> dict:
    """
    candidate_result: output dict from agent_retrain.retrain()
    Returns {promoted: bool, reason: str, new_best: float}
    """
    candidate_acc  = candidate_result["accuracy"]
    candidate_path = Path(candidate_result["model_path"])
    version_tag    = candidate_result.get("version_tag", "candidate")
    n_faces        = candidate_result.get("n_faces", 0)

    current_best = _read_current_best()
    print(f"[promote] Candidate: {candidate_acc*100:.2f}%  |  Current best: {current_best*100:.2f}%")

    if candidate_acc <= current_best:
        reason = f"Candidate ({candidate_acc*100:.2f}%) did not beat current best ({current_best*100:.2f}%). Discarding."
        print(f"[promote] {reason}")
        candidate_path.unlink(missing_ok=True)
        enc = candidate_path.with_name(candidate_path.stem.replace("rf_classifier", "rf_label_encoder") + ".json")
        enc.unlink(missing_ok=True)
        return {"promoted": False, "reason": reason, "new_best": current_best}

    # Backup current production model
    BACKUP_DIR.mkdir(exist_ok=True)
    backup_suffix = f"_backup_{date.today().isoformat()}"
    if PRODUCTION_MODEL.exists():
        shutil.copy2(PRODUCTION_MODEL, BACKUP_DIR / (PRODUCTION_MODEL.stem + backup_suffix + ".pkl"))
    if PRODUCTION_ENCODER.exists():
        shutil.copy2(PRODUCTION_ENCODER, BACKUP_DIR / (PRODUCTION_ENCODER.stem + backup_suffix + ".json"))

    # Replace production model
    shutil.copy2(candidate_path, PRODUCTION_MODEL)
    candidate_enc = candidate_path.with_name(
        candidate_path.name.replace("rf_classifier", "rf_label_encoder").replace(".pkl", ".json")
    )
    if candidate_enc.exists():
        shutil.copy2(candidate_enc, PRODUCTION_ENCODER)

    _append_metrics(
        model_name=f"rf_mfcad_{version_tag}",
        acc=candidate_acc,
        n_faces=n_faces,
        notes=f"Auto-promoted by agent — beat {current_best*100:.2f}%",
    )

    reason = f"Promoted! {candidate_acc*100:.2f}% > {current_best*100:.2f}% (+{(candidate_acc-current_best)*100:.2f}pp)"
    print(f"[promote] {reason}")
    return {"promoted": True, "reason": reason, "new_best": candidate_acc}


if __name__ == "__main__":
    # Test: show current best
    print(f"Current best accuracy: {_read_current_best()*100:.2f}%")
