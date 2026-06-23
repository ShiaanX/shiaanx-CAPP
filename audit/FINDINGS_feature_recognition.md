# Feature Recognition Audit — Motor Mount

**Date:** 2026-06-23  
**Branch:** audit/feature-recognition-motor-mount  
**Test part:** `G:\My Drive\Closed Loop\Motor Mount\input\MOTOR MOUNT.step`  
**Ground truth:** `audit/motor_mount_operations.json` (4 real setups from Sinumerik 828D MPF files)

---

## Summary

Three bugs in `cluster_features.py` and `classify_features.py` caused the pipeline to miss all pockets, steps, and chamfers. After fixes, recall improved from **62.5% → 100.0%** on the Motor Mount (8/8 feature types detected).

---

## Pre-Fix Results (baseline)

| Feature Type | Expected min | Detected | Met? |
|---|---|---|---|
| boss         | 2  | 24 | Yes |
| slot         | 0  | 12 | Yes |
| through_hole | 2  |  4 | Yes |
| large_bore   | 1  |  1 | Yes |
| counterbore  | 0  |  6 | Yes |
| pocket       | 6  |  0 | **No** |
| planar_face  | 3  |  0 | **No** |
| chamfer      | 2  |  0 | **No** |

**Pre-fix recall: 62.5% (5/8 types)**

Total clusters: 71 (one 1015-face background cluster containing all steps/pockets)

---

## Bugs Found and Fixed

### Bug 1 — P0: One seed per plane normal direction (cluster_features.py)

**Root cause:** `find_seeds()` Rule 3 planted exactly one BFS seed per unique plane normal direction. All Z-up plane faces (stock top at Z=13.5mm, pocket floors at Z=5mm, step shoulders at intermediate heights) shared the same normal and therefore got one combined seed. BFS from that single seed only reached the stock surface (face 19, 352 sub-faces) because pocket floors are NOT graph-adjacent to the stock face through the parallel-plane BFS rule — they're separated by pocket walls (perpendicular planes).

**Effect:** 426 plane faces collapsed into the 1015-face background cluster (id=70). Zero pockets, zero step features.

**Fix:** Connected-component seeding — instead of one seed per normal direction, do a BFS within each direction group to find disconnected components, and plant one seed per component. Each pocket floor, each step shoulder, and the stock face get their own independent seed.

**File:** `Claude output for program sheet/2. cluster_features.py`, `find_seeds()` Rule 3

---

### Bug 2 — Chamfer faces excluded from seeding (cluster_features.py)

**Root cause:** The cylinder-adjacency skip `if any(nb in cylinder_seed_indices for nb in G.neighbors(node))` excluded ALL plane faces adjacent to any cylinder seed. The 4 chamfer faces (45° normals, area=5.89mm²) are adjacent to bore cylinders at the bore entries, so they were excluded and fell into background.

**Effect:** Chamfer faces (face_indices 38, 42, 73, 77) always landed in background cluster. No chamfer seeds planted.

**Fix:** Only skip planes that are CAP faces (normal parallel to cylinder axis, dot product > 0.9). Chamfer planes at 45° have dot product ≈ 0 with the bore axis — they're NOT caps, so they now get their own seed.

**File:** `Claude output for program sheet/2. cluster_features.py`, `find_seeds()` cylinder-adjacency check

---

### Bug 3 — is_principal_axis not set for plane clusters (cluster_features.py)

**Root cause:** `get_feature_axis()` only extracts an axis from cylinder faces. For plane-seeded clusters (no cylinders), it returns `None`, so `is_principal_axis = None` for all plane clusters. The chamfer check `if is_principal is False` never fired (`None is False` → `False`).

**Effect:** Even after Bug 2 was fixed, chamfer faces got `is_principal_axis=None` and fell through to `planar_face`.

**Fix:** For plane-seeded clusters, derive `is_principal_axis` from the seed face's plane normal vector. If the normal is ±X, ±Y, or ±Z → True. Otherwise (45° normal) → False.

**File:** `Claude output for program sheet/2. cluster_features.py`, Phase 3 Grow Clusters loop

---

### Bug 4 — Chamfer detection missing from classify_features.py

**Root cause:** The chamfer classification path (`seed_type='plane'`, `is_principal is False`, `face_count==1`, `face_area < 100mm²`) was not present in the classify branch on the audit branch.

**Fix:** Added `CHAMFER_MAX_AREA_MM2 = 100.0` constant and chamfer detection before the pocket check in `classify_cluster()`.

**File:** `Claude output for program sheet/3. classify_features.py`

---

## Post-Fix Results

| Feature Type | Expected min | Detected | Met? |
|---|---|---|---|
| boss         | 2  | 24 | Yes |
| slot         | 0  | 12 | Yes |
| through_hole | 2  |  4 | Yes |
| large_bore   | 1  |  1 | Yes |
| counterbore  | 0  |  6 | Yes |
| pocket       | 6  | **21** | **Yes** |
| planar_face  | 3  | **21** | **Yes** |
| chamfer      | 2  |  **4** | **Yes** |

**Post-fix recall: 100.0% (8/8 types)**  
**Total clusters: 100** (was 71, background cluster: 945 faces, was 1015)

### Notable counts

- 21 pockets (up from 0) — Q11, small pocket, cavity, step recesses all now have independent clusters
- 21 planar faces — step shoulders, outer profile faces, datum faces
- 4 chamfers — the 4 × 45° angled faces at outer profile corners (2 per corner pair)
- 1 large_bore — the 25mm diameter bore
- 6 counterbores — correctly detected, consistent with pre-fix

---

## Remaining Gaps (not yet fixed)

1. **Background cluster still 945 faces** — BSpline fillets (547) and most torus faces (16) are outside current seeding logic. These represent complex freeform surfaces, not directly machinable features.

2. **D16.1mm bore classified as through_hole** — The actual machining uses circular interpolation (because at 16mm diameter, a drill is borderline). The `LARGE_BORE_RADIUS_MM` threshold is 10mm; D16.1 has radius 8.05mm < 10mm, so it's classified as `through_hole`. The process selection then generates `spot_drill → twist_drill` instead of `circular_interp`. This is a process selection accuracy gap, not a feature recognition gap.

3. **21 pockets vs ~6 expected** — Some overcounting: the motor mount has pocket-like features with shared floor areas that get split into multiple seeds by the connected-component fix. Further investigation needed to verify which are true pockets vs step recesses vs datum faces.

---

## Test Files Generated

- `audit/MOTOR MOUNT_features.json` — Stage 1 output (1096 faces)
- `audit/MOTOR MOUNT_clustered.json` — Stage 2 output (100 clusters)
- `audit/MOTOR MOUNT_classified.json` — Stage 3 output (100 classified)
- `audit/MOTOR MOUNT_processes.json` — Stage 4
- `audit/MOTOR MOUNT_params.json` — Stages 5-8
- `audit/MOTOR MOUNT_program_sheet.pdf` — Final output
- `audit/accuracy_breakdown_motormount_postfix.txt` — This report
