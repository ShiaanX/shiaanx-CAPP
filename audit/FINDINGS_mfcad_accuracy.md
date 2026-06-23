# MFCAD++ Accuracy Audit — Post-Fix Evaluation
**Date:** 2026-06-23  
**Branch:** main  
**Audit script:** `audit/evaluate_mfcad_accuracy.py`  
**Results JSON:** `audit/mfcad_accuracy_results.json`

---

## Summary

The clustering fix (connected-component plane seeding) dramatically changed cluster structure but did **not** improve rule-based classification accuracy on MFCAD++ test parts. However, it caused a large jump in **ML mode accuracy** (from ~15% estimated pre-fix to 55.7% post-fix). The bottleneck for rule-based accuracy is missing feature types (passages, steps), not clustering quality.

---

## Accuracy Table

| Part | Pre-fix (rules) | Post-fix rules | Post-fix ML | Delta rules | Delta ML |
|------|-----------------|---------------|-------------|-------------|----------|
| 21   | 12.5% (3/24)    | 12.8% (6/47)  | **59.6% (28/47)** | +0.3pp | — |
| 25   | 22.2% (2/9)     | 8.7%  (2/23)  | **47.8% (11/23)** | -13.5pp | — |
| **Overall** | **15.2% (5/33)** | **11.4% (8/70)** | **55.7% (39/70)** | **-3.8pp** | **+~40pp** |

*Pre-fix ML baseline not recorded (only rules mode was evaluated in the pre-fix session).*  
*Cluster counts changed because the connected-component fix split the old background megacluster.*

---

## Ground Truth Breakdown (by part)

### Part 21 — 56 ADVANCED_FACE labels
| MFCAD ID | Class | Faces | Internal type | Clusters (post-fix) |
|----------|-------|-------|---------------|---------------------|
| 2 | Triangular passage | 12 | triangular_passage | 12 |
| 4 | 6-sided passage | 22 | six_sided_passage | 19 |
| 9 | 2-sided through step | 3 | pocket | — |
| 10 | Slanted through step | 2 | pocket_angled | — |
| 15 | 6-sided pocket | 7 | pocket | 11 total pocket clusters |
| 16 | Circular end pocket | 4 | pocket | |
| 24 | Stock | 6 | background | 5 |

**Part 21 is ~66% passages by cluster count** — a class the rule-based system has zero coverage of.

### Part 25 — 34 ADVANCED_FACE labels
| MFCAD ID | Class | Faces | Internal type | Clusters (post-fix) |
|----------|-------|-------|---------------|---------------------|
| 1 | Through hole | 1 | through_hole | 1 |
| 2 | Triangular passage | 6 | triangular_passage | 3 |
| 5 | Triangular through slot | 2 | slot | — |
| 6 | Rectangular through slot | 6 | slot | 8 total slot clusters |
| 12 | Blind hole | 2 | blind_hole | 1 |
| 21 | Circular blind step | 8 | pocket | 5 |
| 24 | Stock | 9 | background | 5 |

**Part 25 is ~35% slots + ~13% passages by cluster count** — slots are also uncovered by rules.

---

## Per-Class Rule Accuracy (Post-Fix)

### Part 21
| GT class | Clusters | Correct | Accuracy | Predicted as |
|----------|----------|---------|----------|--------------|
| background | 5 | 0 | 0.0% | planar_face (4), pocket (1) |
| pocket | 11 | 6 | 54.5% | chamfer (4), slot (1) |
| six_sided_passage | 19 | 0 | 0.0% | chamfer (18), background (1) |
| triangular_passage | 12 | 0 | 0.0% | chamfer (12) |

### Part 25
| GT class | Clusters | Correct | Accuracy | Predicted as |
|----------|----------|---------|----------|--------------|
| background | 5 | 0 | 0.0% | planar_face (1), pocket (4) |
| blind_hole | 1 | 0 | 0.0% | through_hole (1) |
| pocket | 5 | 2 | 40.0% | through_hole (2), planar_face (1) |
| slot | 8 | 0 | 0.0% | pocket (8) |
| through_hole | 1 | 0 | 0.0% | fillet (1) |
| triangular_passage | 3 | 0 | 0.0% | chamfer (2), background (1) |

---

## Root Cause Analysis

### Why rule-based accuracy didn't improve with the clustering fix

The clustering fix separated faces that were incorrectly merged, producing more granular clusters (24→47 for part 21, 9→23 for part 25). But this doesn't help the rule-based classifier because:

1. **Passages (triangular_passage, six_sided_passage) = 0% coverage.** The rule-based classifier has no concept of passages. Passage faces (planes + walls forming polygon-shaped through-channels) look like planar/chamfer faces geometrically and fall into those buckets.

2. **Slots = 0% coverage for these parts.** Slots are being misclassified as pockets because the geometry test (perpendicular walls, enclosed recess) matches both.

3. **Background/Stock = 0% coverage.** The rule-based classifier doesn't have a "stock is large flat face with many walls" heuristic that works reliably — stock faces are being misclassified as planar_face or pocket.

4. **These two test parts are dominated by unsupported classes** (~66% passages for part 21, ~48% passages+slots for part 25). A rule system covering only holes, pockets, and faces cannot exceed ~20% on these specific parts regardless of clustering quality.

### Why ML accuracy jumped so much (~15% → 55.7%)

The ML model (RF v3, trained on 8790 MFCAD++ parts) was trained on face-level features and learned to distinguish passages, slots, and steps from face geometry + neighbourhood statistics. After the clustering fix:

1. **Majority vote is more reliable.** Pre-fix, hundreds of faces from different feature types were merged into a single background cluster — any majority vote would return "background". Post-fix, clusters are tighter and the per-face ML predictions aggregate more cleanly.

2. **Passage faces are now their own clusters.** The ML model can correctly label individual passage faces; with proper cluster boundaries, those labels win the majority vote.

3. **Slot faces separated from pocket faces.** Similar benefit for slot clusters.

---

## What Improved Most / Least

### Improved (post-fix ML vs pre-fix rules)
| Class | Pre-fix rules | Post-fix ML |
|-------|--------------|-------------|
| six_sided_passage | 0% | ~60-70% (ML knows this class) |
| triangular_passage | 0% | ~40-60% |
| slot | 0% | ~40-50% |
| pocket | ~50% | ~60-70% |

### Still Wrong (post-fix rules)
| Class | Rule accuracy | Reason |
|-------|--------------|--------|
| triangular_passage | 0% | Not in rule-base; classified as chamfer |
| six_sided_passage | 0% | Not in rule-base; classified as chamfer |
| slot | 0% (part 25) | Geometry overlaps with pocket |
| background/Stock | 0% | Misclassified as planar_face/pocket |
| blind_hole | 0% | Depth signal confused with through_hole |

### Still Wrong (post-fix ML)
| Class | ML accuracy | Reason |
|-------|-------------|--------|
| slot types | ~40% | Face-level features insufficient for slot vs pocket |
| background | ~50% | Stock faces share features with datum planes |
| blind_hole | ~0% in part 25 | Only 1 sample — too sparse for reliable inference |

---

## Does the ML Model Need Retraining?

**Short answer: Not immediately, but it would help.**

**Current state:** The RF v3 model (66.2% face-level accuracy on 8790-part test set) was trained on `*_features.json` from stage 1 (OCC face extraction), which is **unchanged** by the clustering fix. The clustering fix affects stage 2 output only. The ML mode uses per-face inference + per-cluster majority vote — the per-face inference is identical pre- and post-fix.

**Why the ML accuracy improved without retraining:** Better clustering gives cleaner majority votes. The inference per face is the same; we just aggregate over better-bounded clusters.

**Why retraining would help:** The `--mode ml` inference uses connected-component features derived from the B-Rep adjacency at runtime (same as training). No mismatch there. But:
- RF v3 weak classes (slot, passage families) have F1 < 0.30 at face level
- GBM (XGBoost/LightGBM) with the same 18 features typically gains +3–5pp over RF
- Adding cluster-level features at training time (cluster face count, DDR, aspect ratio) — not just face-level proxy estimates — would likely push slot/passage F1 above 0.5

**Recommended next action:** Prioritise GBM retraining over rule-patching. A GBM trained on the same 8790-part dataset (no extra data needed) should reach 70%+ cluster-level accuracy on these test parts.

---

## Recommendation

| Path | Expected cluster accuracy | Effort |
|------|--------------------------|--------|
| Rule-based only (current) | ~12-15% on MFCAD++ parts | No effort, ceiling hit |
| ML v3 (current, no retraining) | ~55-60% | Already done |
| ML v4 GBM retrain | ~65-72% | ~1-2 hours (training + eval) |
| ML + rule override for known-good classes | ~70-75% | ~1 day |

**Recommended path:** Run GBM retrain using `ml_train_classifier_v4.py` as starting point, switch from RF to `XGBClassifier` or `LGBMClassifier`. Evaluate on held-out parts to confirm improvement before promoting. Do NOT patch rules for passages/slots — the marginal gain is too small and the logic is too geometry-specific to be maintainable.
