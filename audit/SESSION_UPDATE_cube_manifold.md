# Session Update — cube Manifold Audit
**Date:** 2026-06-23  
**Branch:** audit/cube-manifold

---

## Accuracy Summary

| Metric | Result |
|---|---|
| Feature detection (cluster-level) | ~85% — 5/6 types correct; planar_face over-counted |
| Setup count | Pipeline 6 vs Actual 4 — over-estimated by 2 |
| Operation type match | Chamfer ✓, Slots ✓, Large bore ✓; Holes wrong (drill vs. interp); Faces wrong (face mill vs. end mill) |
| Inspection pass rate | 15/16 (93.75%) — 1 fail on ⌀4mm hole (3.94 vs 3.95mm min) |

---

## Key Gaps Found

1. **Drill vs. circular interpolation**: Pipeline prescribes spot+drill for all ⌀4–15mm holes. Actual machining uses end mill interpolation throughout. Need rule R2.

2. **Face mill vs. end mill for pocket floors**: Pipeline can't distinguish open planar faces from pocket floors. All 9 planar clusters get face_mill; actual uses 6–8mm EM. Need `face_context` field (R1).

3. **Internal corner radius not populated**: `internal_corner_radius` is None for all clusters. This prevents the pipeline from selecting 3mm/2mm EM for tight features. Need geometry computation (R3).

4. **Chamfer over-counting**: 14 separate chamfer operations generated; actual = 1 continuous toolpath. Need consolidation logic (R4).

5. **Setup count over-estimation**: Pipeline creates 6 setups (one per face); machinist used 4. Principal axis merging heuristic needed (R6).

6. **Missing 3mm and 2mm EM operations**: These tool sizes are in the DB but never selected because cluster geometry doesn't drive them. Blocked by gap in #3.

7. **RPM strategy**: Pipeline Vc-derived RPM (capped at 10,000) vs actual shop RPM of 3,500–4,500. Shop operates at ~65–85 m/min vs. catalogue 300 m/min for aluminium. Conservative RPM mode needed (R7).

8. **⌀2.3mm hole not detected**: SL15 in inspection shows a 2.3mm hole. No pipeline cluster corresponds to it — either not in the STEP geometry or merged into a larger cluster.

---

## Files Created

```
audit/cube_manifold/
  manifold_classified.json      (21 KB)
  manifold_clustered.json       (19 KB)
  manifold_features.json        (311 KB)
  manifold_params.json          (112 KB)
  manifold_processes.json       (48 KB)
  manifold_setups.json          (67 KB)
  manifold_tools.json           (92 KB)
  tap_operations.json           (parsed from 19 TAP files)
  inspection_results.json       (16 measurements, 1 fail)
  FINDINGS_cube_manifold.md     (full audit findings)

audit/
  SESSION_UPDATE_cube_manifold.md  (this file)
```

---

## Next Steps

1. **Implement R1** (`face_context` open vs. pocket_floor): Inspect adjacency — if planar face is enclosed on 3+ sides by perpendicular walls, classify as pocket floor → use end_mill not face_mill
2. **Implement R3** (populate `internal_corner_radius`): Already stored in cluster struct; ensure geometry_utils computes it from the edge radii of adjacent cylinder faces
3. **Implement R2** (circular interp preference for ⌀≤15mm): Add logic in process_selection.py to offer helical_interp as alternative to spot+drill for aluminium manifold parts
4. **Implement R4** (chamfer consolidation): Group chamfer clusters by setup and tool diameter; emit one operation entry per group
5. **Track ⌀2.3mm feature origin**: Open the STEP in a viewer to identify if it's a separate solid face or part of a larger bore
6. **Compare against motor mount findings**: Check if R1–R4 also resolve gaps found in the previous motor mount audit
