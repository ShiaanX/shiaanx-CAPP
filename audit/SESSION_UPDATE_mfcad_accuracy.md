# Session Update — MFCAD++ Accuracy Audit Post Clustering Fix
**Date:** 2026-06-23  
**Branch:** main  

## Summary

Re-evaluated pipeline classification accuracy on MFCAD++ test parts 21 and 25 after the clustering fix (connected-component plane seeding, chamfer exclusion fix, and chamfer classification improvements from commit dcc6cc822).

**Key result:** The clustering fix did not improve rule-based accuracy (still ~11%), but ML mode accuracy jumped to 55.7% overall — roughly 40 percentage points better than the pre-fix rule-based baseline.

## Accuracy Numbers

| | Part 21 | Part 25 | Overall |
|---|---------|---------|---------|
| Pre-fix rules (baseline) | 12.5% (3/24) | 22.2% (2/9) | 15.2% (5/33) |
| Post-fix rules | 12.8% (6/47) | 8.7% (2/23) | 11.4% (8/70) |
| Post-fix ML (v3) | **59.6% (28/47)** | **47.8% (11/23)** | **55.7% (39/70)** |

Note: cluster counts increased significantly (24→47 for part 21, 9→23 for part 25) because the clustering fix properly separates faces that were merged into the background megacluster.

## What the Numbers Mean

- Rule-based accuracy is flat because the test parts are dominated by passage types (triangular_passage, six_sided_passage) that the rule system has zero coverage of. These parts were never going to be easy for rule-based classification.
- ML accuracy of ~56% is a real improvement — the RF v3 model knows about passages and slots from training on 8790 MFCAD++ parts. Better clustering gave cleaner majority votes, so ML inference (unchanged) produces better cluster-level predictions.
- Rule-based is at its ceiling for these MFCAD++ part types. No further rule patching will help.

## Files Created / Modified

| File | Description |
|------|-------------|
| `audit/evaluate_mfcad_accuracy.py` | Evaluation script (runs stages 1-3, extracts GT, computes accuracy for rules + ML) |
| `audit/mfcad_accuracy_results.json` | Full results JSON with per-class breakdown for both parts and both modes |
| `audit/FINDINGS_mfcad_accuracy.md` | Detailed findings, root cause analysis, and ML retrain recommendation |
| `audit/SESSION_UPDATE_mfcad_accuracy.md` | This file |
| `Dataset/.../21_classified_rules.json` | Post-fix rule-based classified output for part 21 |
| `Dataset/.../21_classified_ml.json` | Post-fix ML classified output for part 21 |
| `Dataset/.../25_classified_rules.json` | Post-fix rule-based classified output for part 25 |
| `Dataset/.../25_classified_ml.json` | Post-fix ML classified output for part 25 |

## Next Steps

1. **GBM retrain** — Replace RF in `ml_train_classifier_v4.py` with XGBoost or LightGBM. Same 18 features, same 8790-part dataset. Expected gain: +5-10pp cluster-level accuracy.
2. **Expand test set** — Add more MFCAD++ test parts (not just 21 and 25) to get a statistically reliable accuracy number before committing to a retrain.
3. **Rule-based: stop patching** — Do not add passage/slot rules. The geometry overlap makes rule-based classification unreliable for these classes. ML is the correct path.
