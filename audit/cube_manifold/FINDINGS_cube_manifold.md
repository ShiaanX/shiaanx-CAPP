# Audit Findings — cube Manifold
**Date:** 2026-06-23  
**Branch:** audit/cube-manifold  
**STEP:** `G:\My Drive\Closed Loop\cube Manifold\Input\manifold.STEP`  
**Pipeline mode:** rule  
**Inspection date:** 2025-04-01

---

## 1. Part Geometry

| Property | Value |
|---|---|
| Bounding box | 28 × 28 × 28 mm (perfect cube) |
| CAD origin | Centre of XY, Z=0 at bottom face |
| Volume | 16,125 mm³ |
| Surface area | 7,019 mm² |
| Faces | 127 |
| Clusters (raw) | 39 |
| Material | Aluminium |

The part is a square manifold block. Multiple fluid/bolt passages run through all six faces, surrounded by pocket features and chamfered edges on the outlet faces.

---

## 2. Feature Detection Accuracy

### Pipeline classification (39 clusters)

| Feature type | Pipeline count | Notes |
|---|---|---|
| chamfer | 14 | All edge chamfers on outlet holes — **correct** |
| through_hole | 10 | Bolt/fluid passages — **correct** |
| planar_face | 9 | Mix of open faces and pocket floors — **partially wrong** (see §4) |
| slot | 4 | Side slots / cross-passages — **correct** |
| large_bore | 1 | ⌀20mm central bore — **correct** |
| background | 1 | 8-face raw stock envelope — **correct** |

**Overall detection: 5/6 feature types correctly identified. Classification accuracy estimated ~85%.**  
The misclassification is `planar_face` being over-counted — some of the 9 planar clusters are pocket *floors* that should be sub-classified as a pocket feature, not open planar faces.

### Inspection-confirmed features

| SL | Description | Nominal | Measured | Feature in pipeline |
|---|---|---|---|---|
| 1-3 | 28mm OD | 28 ±0.1 | 27.92–28.02 | background / cube outer |
| 4 | ⌀20mm bore | 20 ±0.1 | 19.95/19.96 | large_bore C00 ✓ |
| 5 | 2mm depth | 2 ±0.05 | 2.04/2.05 | pocket floor / planar_face |
| 6 | ⌀6×4 hole | 6 ±0.1 | 5.98/5.99 | through_hole ✓ |
| 7 | ⌀4×4 hole | 4 ±0.05 | 3.94/3.95 | through_hole ✓ (but **FAIL**) |
| 8 | 8mm width | 8 ±0.1 | 8.01/8.02 | slot width ✓ |
| 9 | 20mm length | 20 ±0.1 | 19.91/19.92 | slot / planar_face |
| 10 | 5mm depth | 5 ±0.1 | 5.03/5.04 | pocket depth |
| 11 | ⌀6×2 hole | 6 ±0.1 | 6.01/6.02 | through_hole ✓ |
| 12 | ⌀4×4 hole | 4 ±0.1 | 3.92/3.94 | through_hole ✓ |
| 13 | ⌀7×2 hole | 7 ±0.1 | 6.93/6.94 | through_hole ✓ |
| 14 | 8mm width | 8 ±0.1 | 8.01/8.02 | slot width ✓ |
| 15 | ⌀2.3mm hole | 2.3 ±0.05 | 2.28/2.29 | not detected (see §4) |
| 16 | ⌀15mm bore | 15 ±0.1 | 14.93/14.94 | not explicitly detected |

---

## 3. Inspection Pass Rate

| Metric | Value |
|---|---|
| Total measured features | 16 |
| **Pass** | **15 (93.75%)** |
| **Fail** | **1 (6.25%)** |

**Failed feature:** SL7 — ⌀4×4 blind hole, nominal 4.00mm, measured 3.94mm (lower reading).  
Lower bound = 4.00 − 0.05 = **3.95mm**. Reading 3.94 < 3.95 → out of tolerance.  
Root cause: machinist used a 4mm end mill for this blind hole via plunge interpolation. End mills leave nominal diameter; tool runout or deflection at 4mm produced 3.94mm. A 4mm drill would give a more consistent diameter.

---

## 4. Operation Gaps (Pipeline vs. Actual CAM)

### 4a. Setup count mismatch

| Source | Setups |
|---|---|
| Pipeline | 6 |
| Actual (TAP files) | 4 |

Pipeline generates: +X, −X, −Y, −Z, +Y, +Z approaches (one per face pair).  
Actual machinist combined multiple faces per setup using 5-axis-style re-clamping on 3-axis machine. Specifically: Setups 5 (+Y) and 6 (−Z front) in the pipeline correspond to features the machinist handled in Setup 2 and 3.

### 4b. Drill vs. circular interpolation — major gap

Pipeline generates **10× spot_drill + 10× twist_drill** for through holes.  
Actual CAM has **zero drill files** — all holes made by end mill circular/helical interpolation.

| Feature | Pipeline prescription | Actual machining |
|---|---|---|
| ⌀6 through hole | spot_drill → 6mm twist_drill | 6mm EM helical interpolation |
| ⌀4 through hole | spot_drill → 4mm twist_drill | 4mm EM plunge/interpolation |
| ⌀7 hole | spot_drill → 7mm twist_drill | 6mm EM interpolation (approx) |
| ⌀15 hole | spot_drill → pilot → circular_interp | 8mm or 6mm EM interpolation |
| ⌀20 bore | circular_interp ✓ | 8mm EM interpolation |

**The pipeline correctly uses circular_interp only for the ⌀20 large bore.** For ⌀4–15 holes it prescribes drilling — but the machinist chose interpolation throughout. This may be because:
- The shop doesn't stock all drill sizes
- Manifold holes often need precise position which EM interpolation handles in one setup without a tool change
- For aluminium, end mill interpolation is viable and avoids drill breakage risk

### 4c. Face mill vs. end mill for planar faces — gap

Pipeline assigns **face_mill** (50/63/80mm indexable) to all 9 `planar_face` clusters.  
Actual CAM uses **6mm and 8mm end mills** for "flat" operations.

Reason: Most planar faces in this manifold are **pocket floors** or **slot floors** surrounded by walls, not open faces accessible with a face mill. The pipeline doesn't sub-classify planar faces into "open face" vs "pocket floor" — it defaults to face_mill for all.

Actual TAP flat operations: `2-6end_flat`, `3-4end_flat`, `3-8end_flat`, `3-8end_flat_1` → these are floor finishing passes inside pockets.

### 4d. 3mm end mill not in pipeline prescription

Actual Setup 3 uses **3mm end mill** for 2× finish passes (tight pocket features).  
Pipeline does not generate any 3mm end mill operations. The 3mm tool is available in `tool_database.json` but the slots/pockets are wide enough (8mm width) that the pipeline selects 6mm or 8mm end mills.

This suggests the actual pocket geometry has an **internal corner radius < 4mm** that forces the 3mm tool — but the pipeline's `internal_corner_radius` field is not populated (None) for these clusters, so it cannot make this decision.

### 4e. 2mm end mill in actual Setup 4

Actual Setup 4 includes a **2mm end mill finish** pass alongside the chamfer.  
Pipeline doesn't generate any 2mm operation. This 2mm operation likely clears a very small radius pocket or engraving feature that the pipeline doesn't detect as a separate cluster.

### 4f. Chamfer: 14 operations vs. 1 file

Pipeline generates **14 separate chamfer_mill operations** (one per chamfer cluster).  
Actual CAM has **1 chamfer file** (`4-8end_champhar.tap`) covering all perimeter chamfers in a single continuous toolpath.

The pipeline generates the right operation type (chamfer_mill) but doesn't consolidate them. This inflates the program sheet operation count and overstates setup time.

---

## 5. Spindle Speed Comparison

| Tool | Pipeline RPM | Actual RPM |
|---|---|---|
| 6mm EM | 10,000 (capped) | 3,500–4,000 |
| 8mm EM | 10,000 (capped) | 3,500 |
| 4mm EM | 10,000 (capped) | 3,500–4,500 |
| 2mm EM | 10,000 (capped) | 3,500 |

Pipeline Vc for aluminium finish = 300 m/min → calculated RPM far exceeds machine max of 10,000, so all are capped.  
Actual shop uses 3,500–4,500 RPM regardless of tool diameter — conservative by catalogue standards (implied Vc = 66–85 m/min for 6–8mm tools). Feed rates are 1,500–3,000 mm/min, consistent with low RPM + aggressive fz.

**Pipeline recommendation is correct in principle (higher Vc = better finish in Al) but in practice the shop machine is likely limited, or the programmer uses conservative speeds to reduce chatter on a manifold block with multiple thin walls.**

---

## 6. New Rules / Fields This Part Requires

| # | Gap | Required change |
|---|---|---|
| R1 | Pocket floor vs. open face | Add `face_context` field: `"open"` vs `"pocket_floor"`. Open → face_mill; pocket floor → end_mill |
| R2 | Circular interpolation for small holes | Add rule: if hole diameter ≤ 15mm AND available EM ≥ dia/2, prefer circular_interp over spot+drill |
| R3 | Internal corner radius propagation | Populate `internal_corner_radius` from geometry_utils adjacency data; use to select EM diameter |
| R4 | Chamfer consolidation | Group same-setup chamfers into a single chamfer_mill operation with one tool |
| R5 | Small-radius pocket (< 4mm radius) | If pocket has internal corner ≤ 2mm, add dedicated 3mm or 2mm EM finish step |
| R6 | Setup consolidation heuristic | If feature axis pairs are +X/−X, +Y/−Y, +Z/−Z, attempt to merge B-side features into same setup before splitting to new setup |
| R7 | Conservative RPM mode | Add `rpm_strategy: conservative` option that caps RPM at shop_max instead of Vc-derived |
| R8 | Manifold hole pattern detection | Detect co-axial through holes on multiple faces → flag as "fluid passage" for documentation |

---

## 7. Files Created

| File | Description |
|---|---|
| `audit/cube_manifold/manifold_classified.json` | Pipeline stage 3 output |
| `audit/cube_manifold/manifold_processes.json` | Pipeline stage 4 output |
| `audit/cube_manifold/manifold_setups.json` | Pipeline stage 5 output |
| `audit/cube_manifold/manifold_tools.json` | Pipeline stage 7 output |
| `audit/cube_manifold/manifold_params.json` | Pipeline stage 8 output |
| `audit/cube_manifold/tap_operations.json` | Parsed TAP file operations (19 files, 4 setups) |
| `audit/cube_manifold/inspection_results.json` | Inspection report parsed (16 measurements) |
| `audit/cube_manifold/FINDINGS_cube_manifold.md` | This document |
| `audit/SESSION_UPDATE_cube_manifold.md` | Session summary |
