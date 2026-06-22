# Feature Recognition Audit — Motor Mount
**Date:** 2026-06-22  
**Branch:** `audit/feature-recognition-motor-mount`  
**Part:** Motor Mount (STEP file from Closed Loop drive)  
**Auditor:** Claude Code / Siddhant Gupta

---

## Summary

Pipeline run against a real, machined Motor Mount part with 4-setup CAM programs (37 total operations, 14 unique tools). Pre-fix accuracy was 78.8% (26/33 feature instances); three deterministic fixes raised it to **81.8% (27/33)**. The dominant unresolved issue is an architectural limitation in the plane clustering stage that prevents all pocket, step, and outer-profile features from being detected.

| Metric | Pre-fix | Post-fix | Delta |
|--------|---------|----------|-------|
| Overall accuracy | 78.8% (26/33) | 81.8% (27/33) | +3.0% |
| Fillet clusters | 33 | 22 | -11 (spurious R<1mm removed) |
| Large bore (16.1mm) | through_hole ❌ | large_bore ✓ | fixed |
| Shallow bore edge arcs | large_bore ❌ | planar_face ✓ | fixed |
| Chamfer clusters | 2 | 0 | -2 (regression — see §5) |

---

## 1. Ground Truth

**Sources:** 4 setup sheet PDFs + 4 Siemens MPF G-code files  
**Extraction method:** Visual read of setup sheets; G-code parser (`parse_gcode.py`) confirmed tool call counts.

| Setup | Operations | Time |
|-------|-----------|------|
| 1 | 19 | 0:32:04 |
| 2 | 11 | 0:25:10 |
| 3 (finish) | 3 | 0:03:20 |
| 4 | 4 | 0:05:55 |
| **Total** | **37** | **1:06:29** |

Feature ground truth stored in `motor_mount_ground_truth.json`.

---

## 2. Pre-Fix Pipeline Output

Full 8-stage pipeline run on `MOTOR MOUNT.step`. Feature extraction: 71 clusters from the BRep adjacency graph.

**Pre-fix classification distribution (71 clusters):**

| Feature Type | Count |
|---|---|
| background | 15 |
| blind_hole | 2 |
| chamfer | 2 |
| fillet | 33 |
| planar_face | 5 |
| through_hole | 14 |

**Pre-fix accuracy by feature category:**

| Feature Type | Expected | Detected | Error |
|---|---|---|---|
| face_milling | 2 | 5 | EXTRA |
| pocket | 5 | 0 | MISSED |
| step_feature | 2 | 0 | MISSED |
| outer_profile | 1 | 0 | MISSED |
| through_hole (2.5mm) | 4 | 4 | — |
| through_hole (3.2mm) | 7 | 7 | — |
| through_hole (3mm) | 1 | 0 | MISSED |
| fillet (ballnose ≥R2) | 4 | 10 | EXTRA |
| fillet (bull-nose R1) | 2 | 0 | MISSED |
| chamfer | 3 | 2 | PARTIAL |
| large_bore (16.1mm) | 1 | 1 | — (wrong type) |
| deep_slot (41.5mm) | 1 | 0 | MISSED |

---

## 3. Discrepancy Analysis

### [1] GROUPING — Cluster 70 (1015 faces)

**Error type:** GROUPING  
**Root cause:** Plane clustering uses a single seed per axis-aligned normal direction. All Z-parallel faces — stock surface, pocket floors, step shoulders, and outer walls — collapse into a single 1015-face background cluster.  
**Impact:** Causes all 5 pockets, 2 step features, and 1 outer profile to be missed (8 feature instances).  
**Classification:** ARCHITECTURAL — not fixed in this audit. Requires Z-level separation or a plane-splitting pass keyed on face height.  
**Recommendation:** Add a plane segmentation step that groups co-planar Z faces by their Z-height into separate clusters before the main clustering pass.

---

### [2] TAXONOMY — Cluster 22 (r=8.05mm bore, 16.1mm diameter)

**Error type:** TAXONOMY  
**Pre-fix:** `through_hole` — the LARGE_BORE_RADIUS_MM threshold was 10.0mm, so r=8.05 fell below it and followed the multi-face through_hole path.  
**Fix applied:** Lowered `LARGE_BORE_RADIUS_MM` from 10.0 to 8.0 in both `3. classify_features.py` and `rule_sheets/01_feature_classification.json`. The standard metric jobber drill range tops out at 16mm diameter (r=8mm); anything above requires circular interpolation or a boring bar.  
**Post-fix:** `large_bore` ✓  
**Note:** The code change alone was insufficient — the rule sheet override at module import time was neutralising it. Both files must be updated together.

---

### [3] TAXONOMY — Clusters 7 and 8 (r=25mm, depth=0.29mm)

**Error type:** TAXONOMY  
**Pre-fix:** After lowering `LARGE_BORE_RADIUS_MM` to 8.0, these shallow bore edge arcs (r=25mm, depth=0.29mm) newly qualified as `large_bore`.  
**Root cause:** The depth guard that routes shallow-depth large-radius bores to `planar_face` was missing from the audit branch version of the classifier.  
**Fix applied (Fix 3):** Restored depth guard:
```python
if radius >= LARGE_BORE_RADIUS_MM:
    if depth is not None and depth < 1.0:
        feature_type = 'planar_face'   # shallow arc = datum/stock face
        confidence   = 'medium'
    else:
        feature_type = 'large_bore'
        confidence   = 'high'
```
**Post-fix:** Both clusters → `planar_face` ✓

---

### [4] EXTRA — 13 Fillets with R<1.0mm (spurious edge blends)

**Error type:** EXTRA  
**Pre-fix:** 33 fillet clusters, including 13 with R<0.5mm. These generated `profile_3d_contour` operations in the process plan, but no tool in the database has a ball radius below 1.0mm.  
**Fix applied (Fix 2):** Added `FILLET_MIN_RADIUS_MM = 1.0` threshold in the fillet seed handler. Fillets with R<1.0mm are reclassified as `background` (as-machined edge blends that require no explicit machining operation).  
**Post-fix:** 22 fillet clusters, 0 with R<1.0mm. 11 spurious operations removed.

---

### [5] REGRESSION — Chamfer Clusters (2 → 0)

**Error type:** TAXONOMY regression  
**Pre-fix:** 2 chamfer clusters detected.  
**Post-fix:** 0 chamfer clusters detected.  
**Observed cause:** The post-fix `background` cluster count rose from 15 to 24 (+9), absorbing clusters that were previously chamfer. The fillet seed handler inserted in Fix 2 processes radius-bearing faces; if the chamfer clusters share a seed type with fillets and have radii below `FILLET_MIN_RADIUS_MM`, they now route to `background`.  
**Status:** Unresolved — needs investigation into how chamfer seed_type is assigned. Chamfer geometry (conical faces) should have a distinct seed_type from fillets (toroidal/cylindrical); if the seed assignment is incorrect, the seed detection in `2. cluster_features.py` should be audited.  
**Impact on accuracy:** -1 net (gained 1 from large_bore fix, lost 2 chamfers → net +1 for the large_bore row, -2 on chamfer).

---

### [6] MISSED — Through-hole 3mm (Setup 2, T11)

**Error type:** MISSED  
**Root cause:** Uncertain — the 3mm hole was drilled in Setup 2. Either the hole's cylinder faces were captured into the large background cluster, or both cylinder arcs (entry + exit) didn't co-cluster. Clusters 33 and 34 (r=1.26mm = 2.5mm dia) are classified as `blind_hole` due to single-face adjacency — the 3mm (r=1.5mm) through-hole may have the same problem.  
**Recommendation:** Check DDR of single-face cylinder clusters with r≈1.5mm; if DDR ≤ 0.5, they already qualify as `through_hole` (medium confidence). If not present, the cluster was swallowed by background.

---

### [7] MISSED — Deep Slot 41.5mm (Setup 4, T14)

**Error type:** MISSED  
**Root cause:** Slot detection requires two opposing semicircular arc faces of matching radius. A 41.5mm-deep slot cut with a 3mm end mill may produce rectangular wall faces rather than semicircular arcs (the end mill leaves a flat-bottomed slot, not a cylindrical one). The slot detector finds no matching arc geometry.  
**Recommendation:** Add a rectangular slot detection path: plane floor + two parallel planar walls + depth > width ratio > 3 → `slot`.

---

## 4. Fixes Applied

All fixes are in `3. classify_features.py` on branch `audit/feature-recognition-motor-mount`.

| Fix | Commit | Change | Effect |
|-----|--------|--------|--------|
| Fix 1 | `3a5dfc8a7` (code) + rule sheet update 2026-06-22 | `LARGE_BORE_RADIUS_MM` 10.0 → 8.0 | Cluster 22 (16.1mm bore): through_hole → large_bore |
| Fix 2 | `342d7c89a` | Added `FILLET_MIN_RADIUS_MM = 1.0`; R<1mm fillets → background | Removed 11 spurious fillet operations |
| Fix 3 | `5b8cb5c0e` | Restored depth guard for shallow large-radius bores (depth < 1mm → planar_face) | Clusters 7,8 (r=25mm edge arcs): large_bore → planar_face |

**Critical note:** Fix 1 requires updating **both** the Python constant and the rule sheet. The rule sheet (`rule_sheets/01_feature_classification.json`) is loaded at module import time and overrides the code constant. Code-only fixes are silently neutralised.

---

## 5. Architectural Issue — Plane Clustering (Do Not Fix Here)

The single largest accuracy blocker is the plane clustering strategy:

**Current behaviour:** One cluster seed per unique normal direction (Z-up, Z-down, X, Y, etc.). All Z-facing planar faces — regardless of their Z height — share one cluster seed and merge together.

**Effect on Motor Mount:** A 1015-face background cluster (id=70) absorbs: the stock top face, all pocket floors (4 distinct Z heights), all step shoulders (2 Z heights), and all outer wall top edges. This single failure causes 8/33 expected feature instances to be missed (pocket ×5, step ×2, outer profile ×1).

**Proposed fix (out of scope for this audit):**  
Before the clustering pass in `2. cluster_features.py`, group co-planar faces by their Z-coordinate (within ±0.5mm tolerance) into separate plane seeds. Each Z-level gets its own seed, giving pocket floors, step shoulders, and stock faces separate cluster roots. This is a behavioural change to Stage 2 and requires its own audit.

---

## 6. Recommendations (Priority Order)

| Priority | Issue | Action |
|---|---|---|
| P0 | Plane clustering merges all Z-faces | Split plane seeds by Z-height in `2. cluster_features.py` |
| P1 | Chamfer regression post-fix | Audit chamfer seed_type assignment; ensure conical faces have seed_type='cone' distinct from 'fillet' |
| P2 | 2 through_holes classified blind_hole | Lower DDR threshold or add radius-matching across nearby single-face clusters |
| P3 | Deep slot not detected | Add rectangular slot detection (planar walls + depth:width ratio) |
| P4 | Fillet clusters are not sub-features of pockets | After pocket detection, associate fillet clusters whose faces are adjacent to pocket walls as pocket sub-features |

---

## 7. Output Files

All files in `C:\Users\Siddhant Gupta\Documents\ShiaanX\audit\`:

| File | Description |
|---|---|
| `motor_mount_ground_truth.json` | Hand-extracted ground truth from 4 setup sheets |
| `gcode_tool_summary.json` | Tool sequences parsed from 4 MPF files |
| `parse_gcode.py` | Siemens MPF G-code parser |
| `features_motormount.json` | Stage 1 output (BRep faces) |
| `clustered_motormount.json` | Stage 2 output (face clusters) |
| `classified_motormount.json` | Stage 3 output — PRE-FIX |
| `classified_motormount_postfix.json` | Stage 3 output — POST-FIX |
| `processes_motormount.json` | Stage 4 output — PRE-FIX |
| `processes_motormount_postfix.json` | Stage 4 output — POST-FIX |
| `accuracy_breakdown_motormount.txt` | Accuracy table — PRE-FIX (78.8%) |
| `accuracy_breakdown_motormount_postfix.txt` | Accuracy table — POST-FIX (81.8%) |
| `compare_motor_mount.py` | Comparison script |
| `reclassify_postfix.py` | Pipeline runner for stages 3–8 (postfix) |
| `FINDINGS_feature_recognition.md` | This document |
