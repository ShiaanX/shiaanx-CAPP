"""
compare_motor_mount.py
Compare pipeline classified output against Motor Mount ground truth.
Produces accuracy_breakdown_motormount.txt
"""
import json
from pathlib import Path

AUDIT = Path(__file__).parent

GT_PATH          = AUDIT / "motor_mount_ground_truth.json"
CLASSIFIED_PATH  = AUDIT / "classified_motormount.json"
PROCESSES_PATH   = AUDIT / "processes_motormount.json"
OUT_PRE          = AUDIT / "accuracy_breakdown_motormount.txt"

# -------------------------------------------------------------------------
# Ground truth feature types implied by the setup sheets
# (manual extraction — see motor_mount_ground_truth.json feature_hints)
# -------------------------------------------------------------------------
GT_FEATURES = {
    # Feature type              : (expected count, notes)
    "face_milling":             (2,  "Top face (Setup 1 DYNAMIC) + Bottom face (Setup 2 DYNAMIC)"),
    "pocket":                   (5,  "Q11, SP, SMALL_POCKET, CAVITY (Setup 1) + STEP_POCKET (Setup 2)"),
    "step_feature":             (2,  "STEP-1 (Setup 1) + STEP-2 (Setup 2)"),
    "outer_profile":            (1,  "Outer contour milling (Setup 1 OUTER_PROFILE)"),
    "through_hole_2p5mm":       (4,  "2.5mm drilled holes, Setup 1 T03"),
    "through_hole_3p2mm":       (7,  "3.2mm drilled holes, Setup 1 T04"),
    "through_hole_3mm":         (1,  "3mm drilled hole, Setup 2 T11 (exact count unclear)"),
    "fillet_ballnose":          (4,  "Ballnose passes: step bottom R2.5 (setups 1/3), 3mm ballnose (setup 2)"),
    "fillet_bull_nose":         (2,  "8R1 endmill passes (setups 1, 2)"),
    "chamfer":                  (3,  "Chamfer ops: setup 1 x2, setup 4 x1"),
    "large_bore_16p1mm":        (1,  "16.1mm bore, circular interpolation, Setup 4 T13"),
    "deep_slot_41p5mm":         (1,  "41.5mm deep 3mm slot, Setup 4 T14"),
}
GT_TOTAL = sum(v[0] for v in GT_FEATURES.values())


def load_classified():
    with open(CLASSIFIED_PATH) as f:
        data = json.load(f)
    return data["clusters"]


def load_processes():
    with open(PROCESSES_PATH) as f:
        data = json.load(f)
    return data["clusters"]


def analyse(clusters, processes):
    """Build the comparison dict for each feature dimension."""

    # Count pipeline detections by feature_type
    from collections import Counter
    type_counts = Counter(c["feature_type"] for c in clusters)

    # Detailed analysis per cluster
    issues = []  # (error_type, cluster_id, description)

    # --- GROUPING: background cluster with 1015 faces ---
    for c in clusters:
        if c["feature_type"] == "background" and c["face_count"] > 100:
            issues.append((
                "GROUPING",
                c["cluster_id"],
                f"background cluster id={c['cluster_id']} contains {c['face_count']} faces — "
                "should be broken into pockets, steps, outer profile. "
                "Root cause: plane clustering uses single seed per normal direction, "
                "merging all Z-parallel faces into one cluster."
            ))

    # --- TAXONOMY: large bore classified as through_hole ---
    for c in clusters:
        if c["feature_type"] == "through_hole" and c.get("radii"):
            r = max(c["radii"])
            if r >= 8.0:
                issues.append((
                    "TAXONOMY",
                    c["cluster_id"],
                    f"r={r:.3f}mm (dia={2*r:.1f}mm) bore classified as through_hole — "
                    f"should be large_bore (requires circular interpolation, not drilling). "
                    f"LARGE_BORE_RADIUS_MM threshold is 10.0 but max drillable is ~8.0mm."
                ))

    # --- TAXONOMY: blind_hole that should be through_hole ---
    for c in clusters:
        if c["feature_type"] == "blind_hole" and c.get("radii"):
            r = c["radii"][0]
            # Same radius as confirmed through holes (1.2645mm)
            if abs(r - 1.2645) < 0.01:
                issues.append((
                    "TAXONOMY",
                    c["cluster_id"],
                    f"r={r:.4f}mm hole classified as blind_hole (face_count=1) "
                    f"but same radius as confirmed through_holes — "
                    f"clustering missed the second cylinder arc (exit face). "
                    f"Recommend: manual review or lower DDR threshold."
                ))

    # --- EXTRA: small-radius fillets generating profile_3d_contour ---
    small_fillet_count = sum(
        1 for c in clusters
        if c["feature_type"] == "fillet"
        and c.get("radii") and max(c["radii"]) < 1.0
    )
    if small_fillet_count:
        issues.append((
            "EXTRA",
            "multiple",
            f"{small_fillet_count} fillets with R<1.0mm classified as fillet → "
            f"profile_3d_contour operations generated. These are as-machined edge blends "
            f"(no tool in database with R<1.0mm). Should be background."
        ))

    # --- EXTRA: total fillet count far exceeds ground truth ---
    n_fillets = type_counts["fillet"]
    if n_fillets > 6:
        issues.append((
            "EXTRA",
            "fillet",
            f"{n_fillets} fillet clusters detected vs ~4 ballnose + 2 bull-nose passes "
            f"in ground truth. Pocket corner fillets (R=2.5, R=1.5) are separate "
            f"clusters but should be sub-features of their parent pocket."
        ))

    # --- MISSED: no pockets ---
    if type_counts.get("pocket", 0) == 0:
        issues.append((
            "MISSED",
            "—",
            "0 pocket clusters — Q11, SP, SMALL_POCKET, CAVITY (Setup 1) and "
            "STEP POCKET (Setup 2) all missed. Root cause: plane merging groups "
            "all pocket floors with stock face into one background cluster."
        ))

    # --- MISSED: no step features ---
    if type_counts.get("step", 0) == 0 and type_counts.get("step_feature", 0) == 0:
        issues.append((
            "MISSED",
            "—",
            "0 step features — STEP-1 and STEP-2 shoulders missed. "
            "Root cause: same plane merging issue as pockets."
        ))

    # --- MISSED: no outer profile / boss ---
    if type_counts.get("boss", 0) == 0:
        issues.append((
            "MISSED",
            "—",
            "0 boss/outer_profile clusters — outer contour milling operations "
            "(OUTER_PROFILE RF + FINISH + CORNER) have no corresponding feature. "
            "Root cause: plane merging captures outer wall faces into background."
        ))

    # --- MISSED: deep slot ---
    issues.append((
        "MISSED",
        "—",
        "Deep slot (41.5mm deep, 3mm endmill, Setup 4) not detected. "
        "Slot detection requires two matching semicircle arcs from detect_slots; "
        "this slot may lack the arc geometry or the arcs are too deep for detection."
    ))

    return type_counts, issues


def generate_report(clusters, processes, out_path, suffix=""):
    type_counts, issues = analyse(clusters, processes)

    # Map pipeline types to ground truth categories
    PIPELINE_TO_GT = {
        "face_milling":     ("face_mill", type_counts.get("planar_face", 0)),
        "pocket":           ("pocket", type_counts.get("pocket", 0)),
        "step_feature":     ("step", 0),
        "outer_profile":    ("boss", type_counts.get("boss", 0)),
        "through_hole_2p5mm": ("through_hole r≈1.26mm", sum(
            1 for c in clusters
            if c["feature_type"] == "through_hole"
            and c.get("radii") and abs(c["radii"][0] - 1.2645) < 0.05
        )),
        "through_hole_3p2mm": ("through_hole r=1.6mm", sum(
            1 for c in clusters
            if c["feature_type"] == "through_hole"
            and c.get("radii") and abs(c["radii"][0] - 1.6) < 0.05
        )),
        "through_hole_3mm": ("through_hole r=1.5mm", sum(
            1 for c in clusters
            if c["feature_type"] == "through_hole"
            and c.get("radii") and abs(c["radii"][0] - 1.5) < 0.05
        )),
        "fillet_ballnose":  ("fillet R≥2.0mm", sum(
            1 for c in clusters
            if c["feature_type"] == "fillet"
            and c.get("radii") and max(c["radii"]) >= 2.0
        )),
        "fillet_bull_nose": ("fillet R=1.0mm", sum(
            1 for c in clusters
            if c["feature_type"] == "fillet"
            and c.get("radii") and abs(max(c["radii"]) - 1.0) < 0.05
        )),
        "chamfer":          ("chamfer", type_counts.get("chamfer", 0)),
        "large_bore_16p1mm":("large_bore r≈8mm", sum(
            1 for c in clusters
            if c["feature_type"] in ("large_bore", "through_hole")
            and c.get("radii") and max(c["radii"]) >= 8.0
        )),
        "deep_slot_41p5mm": ("slot", type_counts.get("slot", 0)),
    }

    lines = []
    lines.append(f"Motor Mount — Feature Recognition Accuracy Breakdown{suffix}")
    lines.append("=" * 78)
    lines.append("")
    lines.append(f"{'Feature Type':<28} | {'Expected':>8} | {'Detected':>8} | {'Error Type':<12} | Notes")
    lines.append("-" * 100)

    total_expected = 0
    total_correct  = 0
    grouping_n = taxonomy_n = missed_n = extra_n = 0

    for gt_key, (gt_count, gt_note) in GT_FEATURES.items():
        pipeline_key, detected = PIPELINE_TO_GT.get(gt_key, ("—", 0))
        total_expected += gt_count

        correct = min(gt_count, detected)
        total_correct += correct

        if detected == 0 and gt_count > 0:
            error = "MISSED"
            missed_n += gt_count
        elif detected > gt_count:
            error = "EXTRA"
            extra_n += (detected - gt_count)
            total_correct += min(gt_count, gt_count)
        elif detected == gt_count:
            error = "—"
        else:
            error = "PARTIAL"

        lines.append(
            f"{gt_key:<28} | {gt_count:>8} | {detected:>8} | {error:<12} | {gt_note[:45]}"
        )

    lines.append("-" * 100)
    lines.append(f"{'TOTALS':<28} | {total_expected:>8} | {'-':>8}")
    lines.append("")
    lines.append(f"Correctly detected:         {total_correct}/{total_expected}")
    lines.append(f"Overall accuracy:           {100*total_correct/max(1,total_expected):.1f}%")
    lines.append("")
    lines.append("Pipeline classification distribution (all 71 clusters):")
    for ft, n in sorted(type_counts.items()):
        lines.append(f"  {ft:<30}: {n}")
    lines.append("")
    lines.append(f"{'='*78}")
    lines.append("DISCREPANCY LOG")
    lines.append(f"{'='*78}")
    for i, (etype, cid, desc) in enumerate(issues, 1):
        lines.append(f"\n[{i}] {etype} | cluster={cid}")
        # word-wrap description
        words = desc.split()
        line = "     "
        for w in words:
            if len(line) + len(w) + 1 > 95:
                lines.append(line)
                line = "     " + w
            else:
                line += " " + w
        lines.append(line)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"Saved: {out_path}")
    print(f"Overall accuracy: {100*total_correct/max(1,total_expected):.1f}%")
    return total_correct, total_expected


if __name__ == "__main__":
    clusters  = load_classified()
    processes = load_processes()
    generate_report(clusters, processes, OUT_PRE)
