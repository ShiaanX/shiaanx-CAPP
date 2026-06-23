"""
evaluate_mfcad_accuracy.py
--------------------------
Re-evaluates classify_features.py accuracy on MFCAD++ test parts 21 & 25
after the clustering fix.

Runs stages 1-3 fresh, compares to ADVANCED_FACE GT labels embedded in the
STEP file, and reports per-class and overall accuracy for both rule-based
and ML modes.

Usage:
    cd "C:\\Users\\Siddhant Gupta\\Documents\\ShiaanX\\Claude output for program sheet"
    "C:\\Users\\Siddhant Gupta\\miniconda3\\envs\\occ\\python.exe" ..\\audit\\evaluate_mfcad_accuracy.py
"""

import json
import re
import subprocess
import sys
import shutil
from collections import Counter, defaultdict
from pathlib import Path

PYTHON = r"C:\Users\Siddhant Gupta\miniconda3\envs\occ\python.exe"
PIPELINE_DIR = Path(r"C:\Users\Siddhant Gupta\Documents\ShiaanX\Claude output for program sheet")
DATASET_DIR = Path(r"C:\Users\Siddhant Gupta\Documents\ShiaanX\Claude output for program sheet\Dataset\MFCAD_dataset\MFCAD++_dataset")
TAXONOMY_PATH = PIPELINE_DIR / "rule_sheets" / "07_label_taxonomy.json"
AUDIT_DIR = Path(__file__).parent

PARTS = {
    "21": DATASET_DIR / "step" / "test" / "21" / "21.step",
    "25": DATASET_DIR / "step" / "test" / "25" / "25.step",
}

PRE_FIX_BASELINE = {
    "21": {"clusters": 24, "correct": 3, "accuracy": 12.5},
    "25": {"clusters": 9,  "correct": 2, "accuracy": 22.2},
}


# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------

def load_taxonomy(path: Path) -> tuple[dict, dict]:
    """Returns (mfcad_id -> internal_feature_type, mfcad_id -> mfcad_name)."""
    with open(path) as f:
        data = json.load(f)
    id_to_type = {m["mfcad_id"]: m["internal_feature_type"] for m in data["mappings"]}
    id_to_name = {m["mfcad_id"]: m["mfcad_name"] for m in data["mappings"]}
    return id_to_type, id_to_name


# ---------------------------------------------------------------------------
# GT extraction
# ---------------------------------------------------------------------------

def extract_gt_labels(step_path: Path) -> list:
    """
    Returns list where index i = MFCAD++ class ID for the i-th ADVANCED_FACE
    (0-based, STEP file order). Name field 'N' in ADVANCED_FACE is the class ID.
    Non-numeric names default to 24 (Stock/background).
    """
    pattern = re.compile(r"ADVANCED_FACE\s*\(\s*'([^']*)'", re.IGNORECASE)
    labels = []
    with open(step_path, "r", errors="replace") as f:
        content = f.read()
    for m in pattern.finditer(content):
        try:
            labels.append(int(m.group(1).strip()))
        except ValueError:
            labels.append(24)
    return labels


# ---------------------------------------------------------------------------
# Pipeline stage runner
# ---------------------------------------------------------------------------

def run_stage(script: str, input_path: Path, output_path: Path = None,
              extra_args: list = None) -> None:
    cmd = [PYTHON, str(PIPELINE_DIR / script), str(input_path)]
    if output_path:
        cmd.append(str(output_path))
    if extra_args:
        cmd.extend(extra_args)

    label = f"{script} ({extra_args[1] if extra_args else 'rules'})"
    print(f"  > {label} [{input_path.name}]")
    r = subprocess.run(cmd, cwd=str(PIPELINE_DIR), capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        print(f"    STDOUT: {r.stdout[-1000:]}")
        print(f"    STDERR: {r.stderr[-2000:]}")
        raise RuntimeError(f"{script} failed (exit {r.returncode})")


# ---------------------------------------------------------------------------
# Accuracy computation
# ---------------------------------------------------------------------------

def compute_accuracy(classified_path: Path, gt_labels: list, taxonomy: dict,
                     mode: str) -> dict:
    """
    For each cluster: majority-vote GT label over face_indices → expected class
    → translate via taxonomy → compare to predicted feature_type.
    _angled suffix is stripped before comparison (it's a setup hint, not a GT class).
    """
    with open(classified_path) as f:
        data = json.load(f)

    clusters = data.get("clusters", [])
    correct = 0
    per_class: dict = defaultdict(lambda: {"total": 0, "correct": 0,
                                            "predicted_as": Counter()})
    errors = []

    for cl in clusters:
        fi = cl.get("face_indices", [])
        predicted = cl.get("feature_type", "unknown")
        if not fi:
            continue

        face_labels = [gt_labels[i] for i in fi if i < len(gt_labels)]
        if not face_labels:
            continue

        maj_id = Counter(face_labels).most_common(1)[0][0]
        expected = taxonomy.get(maj_id, "mfcad_unmapped")

        pred_base = predicted.replace("_angled", "")
        exp_base = expected.replace("_angled", "")

        is_ok = (pred_base == exp_base)
        if is_ok:
            correct += 1

        per_class[exp_base]["total"] += 1
        if is_ok:
            per_class[exp_base]["correct"] += 1
        else:
            per_class[exp_base]["predicted_as"][pred_base] += 1
            errors.append({
                "cluster_id": cl.get("cluster_id"),
                "face_count": len(fi),
                "predicted": predicted,
                "expected": expected,
                "majority_mfcad_id": maj_id,
            })

    n = len(clusters)
    acc = round(100.0 * correct / n, 1) if n else 0.0
    return {
        "mode": mode,
        "total_clusters": n,
        "correct_clusters": correct,
        "accuracy_pct": acc,
        "per_class": {k: dict(v) for k, v in per_class.items()},
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    taxonomy, taxonomy_names = load_taxonomy(TAXONOMY_PATH)
    results = {}

    for part_id, step_path in PARTS.items():
        step_path = Path(step_path)
        parent = step_path.parent
        stem = step_path.stem  # "21" or "25"
        print(f"\n{'='*64}")
        print(f"  Part {part_id}  —  {step_path}")
        print(f"{'='*64}")

        # --- Extract GT ---
        gt_labels = extract_gt_labels(step_path)
        gt_counter = Counter(gt_labels)
        print(f"  GT: {len(gt_labels)} ADVANCED_FACE labels")
        for mid, cnt in sorted(gt_counter.items()):
            print(f"    [{mid:2d}] {taxonomy_names.get(mid, '?'):30s} {cnt:3d} faces")

        # --- Stage 1: extract_features ---
        features_path = parent / f"{stem}_features.json"
        run_stage("1. extract_features.py", step_path)
        assert features_path.exists(), f"Missing: {features_path}"

        # --- Stage 2: cluster_features ---
        clustered_path = parent / f"{stem}_features_clustered.json"
        run_stage("2. cluster_features.py", features_path)
        assert clustered_path.exists(), f"Missing: {clustered_path}"

        # --- Stage 3 rules: write to separate path so ML doesn't overwrite ---
        rules_out = parent / f"{stem}_classified_rules.json"
        run_stage("3. classify_features.py", clustered_path, rules_out)
        assert rules_out.exists(), f"Missing: {rules_out}"

        # --- Stage 3 ML ---
        ml_out = parent / f"{stem}_classified_ml.json"
        run_stage("3. classify_features.py", clustered_path, ml_out,
                  ["--mode", "ml", "--features", str(features_path)])
        assert ml_out.exists(), f"Missing: {ml_out}"

        # --- Evaluate ---
        rules_result = compute_accuracy(rules_out, gt_labels, taxonomy, "rules")
        ml_result = compute_accuracy(ml_out, gt_labels, taxonomy, "ml")

        print(f"\n  Rules: {rules_result['correct_clusters']}/{rules_result['total_clusters']}"
              f" = {rules_result['accuracy_pct']}%")
        print(f"  ML:    {ml_result['correct_clusters']}/{ml_result['total_clusters']}"
              f" = {ml_result['accuracy_pct']}%")

        # Per-class detail
        print("\n  Per-class (rules):")
        for cls, d in sorted(rules_result["per_class"].items()):
            acc = 100.0 * d["correct"] / d["total"] if d["total"] else 0
            wrong = dict(d.get("predicted_as", {}))
            print(f"    {cls:30s} {d['correct']:2d}/{d['total']:2d} = {acc:5.1f}%"
                  + (f"  predicted-as: {wrong}" if wrong else ""))

        results[part_id] = {
            "gt_label_counts": {str(k): {"name": taxonomy_names.get(k, "?"), "faces": v}
                                 for k, v in gt_counter.items()},
            "rules": rules_result,
            "ml": ml_result,
        }

    # --- Overall summary ---
    print(f"\n{'='*64}")
    print("  ACCURACY SUMMARY")
    print(f"{'='*64}")
    print(f"  {'Part':<8} {'Pre-fix':>10} {'Rules post':>12} {'ML post':>10}")
    print(f"  {'-'*44}")

    r_total_c = r_total_t = ml_total_c = ml_total_t = 0
    pre_c = pre_t = 0
    for pid in PARTS:
        pre = PRE_FIX_BASELINE[pid]
        r = results[pid]["rules"]
        m = results[pid]["ml"]
        print(f"  {pid:<8} {pre['accuracy']:>9.1f}% {r['accuracy_pct']:>11.1f}% {m['accuracy_pct']:>9.1f}%")
        r_total_c += r["correct_clusters"];  r_total_t += r["total_clusters"]
        ml_total_c += m["correct_clusters"]; ml_total_t += m["total_clusters"]
        pre_c += pre["correct"];             pre_t += pre["clusters"]

    pre_ov  = round(100.0 * pre_c / pre_t, 1)
    r_ov    = round(100.0 * r_total_c / r_total_t, 1)
    ml_ov   = round(100.0 * ml_total_c / ml_total_t, 1)
    print(f"  {'Overall':<8} {pre_ov:>9.1f}% {r_ov:>11.1f}% {ml_ov:>9.1f}%")

    # --- Persist ---
    out_path = AUDIT_DIR / "mfcad_accuracy_results.json"
    with open(out_path, "w") as f:
        json.dump({
            "pre_fix_baseline": PRE_FIX_BASELINE,
            "post_fix_results": {
                pid: {
                    "gt_label_counts": results[pid]["gt_label_counts"],
                    "rules": results[pid]["rules"],
                    "ml": results[pid]["ml"],
                } for pid in PARTS
            },
            "summary": {
                "pre_fix_overall_pct": pre_ov,
                "rules_overall_pct": r_ov,
                "ml_overall_pct": ml_ov,
            }
        }, f, indent=2, default=str)
    print(f"\n  Results JSON -> {out_path}")
    return results, pre_ov, r_ov, ml_ov


if __name__ == "__main__":
    main()
