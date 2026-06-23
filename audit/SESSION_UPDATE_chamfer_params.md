# Session Update: Two-Pass Chamfer Parameter Differentiation

**Date:** 2026-06-23  
**Branch:** main  
**Commit:** 0b6543fc9

---

## What Was Changed

### Problem
The two-pass chamfer strategy (PS-AL6061-CHAMFER-002) was outputting **identical cutting parameters** for both TOUCH and FINISH passes. The `process_selection.py` code to generate TOUCH/FINISH steps existed, but:

1. The depth condition `if depth is not None and depth > 0.5:` blocked two-pass for Motor Mount chamfers (which have `depth=None`).
2. A stale merge commit had simplified `cluster_features.py` in a way that dropped chamfer plane seeds entirely, so chamfers weren't being detected at all.

### Root Causes Found & Fixed

**`cluster_features.py` — chamfer seeding regression**  
A previous merge commit replaced the cap-plane dot-product check with a simpler `any(nb in cylinder_seed_indices ...)` that skipped ALL planes adjacent to cylinder seeds — including chamfer planes. The correct logic only skips cap planes (normal ∥ cylinder axis, dot > 0.9). Also restored `is_principal_axis` derivation from plane normal for plane clusters (required for chamfer classification to fire `is_principal is False`).

**`process_selection.py` — depth condition**  
Changed `if depth is not None and depth > 0.5:` → `if depth is None or depth > 0.5:`. Two-pass is now the default when depth is unknown. Single-pass only when depth is confirmed ≤ 0.5mm.

**`parameter_calculation.py` — Vc/feed differentiation**  
Added constants and logic to apply validated Motor Mount parameters per pass:

| Pass | Vc (m/min) | RPM | Vf (mm/min) |
|------|-----------|-----|-------------|
| TOUCH (before) | 300 (tool DB) | 10000 (capped) | 1000 |
| **TOUCH (after)** | **28** | **1490** | **80 (capped from 149)** |
| FINISH (before) | 300 (tool DB) | 10000 (capped) | 1000 |
| **FINISH (after)** | **140** | **7430** | **743** |

**`rule_sheets/04_cutting_parameters.json`**  
Added `chamfer_two_pass` section documenting TOUCH (28 m/min, 80 mm/min cap) and FINISH (140 m/min) values with rationale.

---

## Files Modified

| File | Change |
|------|--------|
| `Claude output for program sheet/8. parameter_calculation.py` | Added CHAMFER_TOUCH_VC=28.0, CHAMFER_FINISH_VC=140.0, CHAMFER_TOUCH_FEED_MAX=80.0 constants; Vc override block; feed cap; chamfer_pass carry-through |
| `Claude output for program sheet/4. process_selection.py` | Depth condition fix for two-pass default |
| `Claude output for program sheet/2. cluster_features.py` | Restored cap-plane dot-product check and is_principal_axis plane-normal derivation |
| `Claude output for program sheet/rule_sheets/04_cutting_parameters.json` | Added chamfer_two_pass documentation section |

---

## Verification

Motor Mount pipeline run after all fixes:

```
C83 TOUCH    Vc=28.0   RPM=1490  Vf=80.0   (capped from 149)
C83 FINISH   Vc=140.0  RPM=7430  Vf=743
C84 TOUCH    Vc=28.0   RPM=1490  Vf=80.0
C84 FINISH   Vc=140.0  RPM=7430  Vf=743
C85 TOUCH    Vc=28.0   RPM=1490  Vf=80.0
C85 FINISH   Vc=140.0  RPM=7430  Vf=743
C86 TOUCH    Vc=28.0   RPM=1490  Vf=80.0
C86 FINISH   Vc=140.0  RPM=7430  Vf=743
Total chamfer steps: 8  (4 chamfers × 2 passes)
```

---

## Next Step

- Merge `feature/chamfer-params` → `main` (or confirm that the changes already landed on main; this session worked directly on main after branch confusion).
- Review whether the `feature/chamfer-params` branch should be deleted or rebased.
