# Session Update — LIGHT-FCS Audit

**Date:** 2026-06-23  
**Branch:** audit/light-fcs  
**Pipeline run:** COMPLETE (8.9s, all 9 stages OK)

---

## Accuracy Summary

Pipeline produced a structurally valid plan but with several significant gaps vs actual machining practice.

**Setup count:** Pipeline = 3, Actual = 9. This is the most critical gap.  
**Feature detection:** 39 clusters detected — chamfer (12), pocket (10), counterbore (7), planar_face (4), pocket_angled (2), slot (2), through_hole (1).  
**Tool size gap:** Pipeline minimum tool = 4mm for pockets. Actual machining used 1.5mm and 2mm EM for narrow features. 1mm SL-11 dimension confirms 1.5mm EM was required.  
**Drilling vs interpolation:** Pipeline plans spot_drill + twist_drill for all holes. Actual CAM uses circular interpolation with end mills only — 0 drill files in the CAM set.

---

## New Feature Types / Operations Found

1. **Sub-2mm end mill operations** (1.5mm, 2mm EM) — for narrow slots / internal corner reliefs ≤ 1mm wide. SL-11 (1mm feature) confirms. Not in current pipeline rules or tool database.

2. **Circular interpolation for holes** — shop preference over drilling for holes with tight tolerance (Ø10 g8). Pipeline always drills; should offer interpolation path when tolerance ≤ IT7 or when hole Ø ≤ 15mm.

3. **Flat floor finish pass** — separate toolpath type (`3_4END_FLAT`, `6_4END_FLATE`). Pipeline includes this conceptually inside pocket_mill FINISH but doesn't distinguish it.

4. **9-setup workholding** — pipeline under-plans complex multi-face parts. Setup planning needs accessibility analysis or depth/reach constraints, not just axis grouping.

---

## Specific Pipeline Bugs Found

| Bug | Severity |
|---|---|
| pocket_mill tool_diameter_mm = 0mm on all 24 pocket ops | HIGH — tool selection broken for pockets |
| Setup count 3 vs actual 9 | HIGH — setup planning too coarse |
| Al 5083 not in material alias table | MEDIUM — runs as 6061 Vc/fz |
| Face mill (40mm) selected for 50×30mm part — overhangs vise | MEDIUM |
| Angled pocket (20°) only gets `fixture_rotation` stub, no angle value | LOW |

---

## Files Created

```
audit/light_fcs/
  drawing_summary.txt              — extracted dimensions, GD&T, material, finish
  tap_operations.json              — 16 CAM files parsed (setup, dia, op type, S, F)
  inspection_results.json          — 14 inspection dimensions, all OK except SL-8 (not measured)
  FINDINGS_light_fcs.md            — full audit findings
  LIGHT-FCS_A06.01.0001.A00_features.json
  LIGHT-FCS_A06.01.0001.A00_clustered.json
  LIGHT-FCS_A06.01.0001.A00_classified.json
  LIGHT-FCS_A06.01.0001.A00_processes.json
  LIGHT-FCS_A06.01.0001.A00_setups.json
  LIGHT-FCS_A06.01.0001.A00_tools.json
  LIGHT-FCS_A06.01.0001.A00_params.json
audit/SESSION_UPDATE_light_fcs.md  — this file
```

---

## Next Steps (priority order)

1. **Fix pocket_mill 0mm diameter bug** — `7. tool_selection.py` not receiving pocket width from classifier. Likely the `pocket` feature type is missing `width_mm` or `diameter_mm` in the classified JSON output.

2. **Add 1.5mm and 2mm EM to tool database** (`7a. tool_database.json`). Add rule to `4. process_selection.py`: if `slot.width < 2mm` or `pocket.min_corner_radius < 1mm` → route to 1.5mm EM.

3. **Add circular interpolation operation** — new operation type `circular_interp_mill`. Route to it when: hole tolerance IT7 or tighter, OR when hole diameter ≤ 15mm and shop preference = interpolation.

4. **Add Al 5083 to material alias table** — in `8. parameter_calculation.py` or the tool database material_params. Map 5083 → slightly lower Vc (~200 m/min rough vs 250 for 6061).

5. **Setup planning depth/reach analysis** — `5. setup_planning.py` needs to check that all features in a setup are accessible given tool reach and jaw position. Consider adding a `max_features_per_setup` limit as a stopgap.

6. **Face mill size sanity check** — reject face mill if diameter > part bounding box shorter dimension.
