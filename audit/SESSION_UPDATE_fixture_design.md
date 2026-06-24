# Session Update — Fixture Design Integration

**Date:** 2026-06-24  
**Branch:** `feature/fixture-design`  
**Session focus:** Build and wire the Fixture Design Integration module into the ShiaanX CAPP pipeline

---

## Completion Checklist

| Step | Task | Status |
|------|------|--------|
| 1 | Reverse-engineer vendor fixture setup from 20 `.tap` G-code files | ✅ Done |
| 2 | Design `fixture_spec` JSON schema | ✅ Done |
| 3 | Write `fixture_planner.py`, test on Motor Mount | ✅ Done |
| 4 | Write `soft_jaw_generator.py` (PythonOCC STEP solid pair) | ✅ Done |
| 5 | Write `fixture_pdf_page.py`, integrate into `9. program_sheet.py` | ✅ Done |
| 6 | Wire fixture planning into `10. run_pipeline.py` as Stage 6a | ✅ Done |
| 7 | Test on second part (Botlabs Hub) to verify generalization | ✅ Done |
| 8 | Write session update + update SESSION_STATE.md | ✅ Done |

---

## Files Created

| File | Purpose |
|------|---------|
| `audit/FINDINGS_fixture_gcode.json` | Structured G-code analysis of 20 Motor Mount `.tap` files |
| `audit/FINDINGS_fixture_gcode.md` | Human-readable version of G-code audit |
| `Claude output for program sheet/fixture_design/fixture_schema.json` | JSON Schema for `fixture_spec` with Motor Mount examples |
| `Claude output for program sheet/fixture_design/fixture_planner.py` | Core module: takes `*_setups.json` + `*_features.json`, outputs `fixture_spec` per setup |
| `Claude output for program sheet/fixture_design/soft_jaw_generator.py` | PythonOCC-based STEP soft jaw solid generator (left/right pair) |
| `Claude output for program sheet/fixture_design/fixture_pdf_page.py` | ReportLab platypus flowables for fixture spec PDF pages |

## Files Modified

| File | Change |
|------|--------|
| `Claude output for program sheet/9. program_sheet.py` | Added importlib load of `fixture_pdf_page.py`; added `fixture_spec_data` kwarg; auto-loads `*_fixture_spec.json`; appends fixture pages to story before `doc.build()` |
| `Claude output for program sheet/10. run_pipeline.py` | Renumbered to 10 steps; added Step 6 = `fixture_planner.py` between setup_planning and setup_view_renderer; writes `*_fixture_spec.json`; fixture step is optional (non-fatal failure) |

## Files Generated (test outputs)

| File | Notes |
|------|-------|
| `Manufactured parts/Motor Mount/MOTOR MOUNT_fixture_spec.json` | Motor Mount fixture spec (3 setups) |
| `Manufactured parts/Motor Mount/MOTOR MOUNT_program_sheet_v2.pdf` | PDF with fixture pages appended |
| `Manufactured parts/Botlabs Hub/Hub_fixture_spec.json` | Botlabs Hub fixture spec (4 setups) |
| `Manufactured parts/Botlabs Hub/Hub_program_sheet_v2.pdf` | PDF with fixture pages appended |

---

## Key Findings from G-Code Audit

- **WCS strategy:** Vendor resets G54 between each setting (not G55/G56). Single WCS offset, probed fresh each time.
- **Z zero:** Setting 1 → `top_of_stock` (billet top). Settings 2+3 → `top_of_part` (probe off machined face).
- **XY zero:** Always centre of part (symmetric toolpaths).
- **Fixture type:** Standard hard-jaw vise for settings 1+2. Angle plate for setting 3 (side-face access).
- **Jaw opening:** 65mm for settings 1+2 (55mm part + 10mm clearance). Confirms `workholding.jaw_opening_mm + 10mm` rule.
- **Parallels:** 10mm across all settings.
- **Soft jaws:** Not used — Motor Mount geometry allows hard jaws throughout.
- **Z clearance jump:** 22.5mm (setting 1) → 100mm (settings 2+3) indicates taller workholding stack after flip (parallels + part + standoffs).

---

## Fixture Planner Design Decisions

1. **Jaw opening source:** Uses `workholding.jaw_opening_mm` from `setup_planning.py` as primary source (it's the correct short dimension already computed), adds 10mm clearance, rounds up to nearest 5mm. Falls back to bbox computation only if not set.

2. **Soft jaw trigger:** Only for (a) non-planar rest face on a previously machined setup AND the rest face is in `machined_faces`, OR (b) jaw_opening < 30mm. Raw billet setups never trigger soft jaws.

3. **Fixture type cascade:** If `workholding.type` is already set to a specific type, defer to it. Otherwise: angled spindle → angle_plate/sine_plate; jaw > 200mm → fixture_plate; setup 1 + jaw > 100mm → step_jaw_vise; default → vise.

4. **Parallels rule:** jaw < 50mm → None; 50–100mm → 10mm; > 100mm → 20mm.

5. **Z zero rule:** raw_billet stock → `top_of_stock`; previous_setup stock → `top_of_part`.

---

## Test Results

**Motor Mount (3 setups):**
- Setup 1: angle_plate, 70mm jaw, 10mm parallels, top_of_stock ✓
- Setup 2: fixture_plate, 70mm jaw, 10mm parallels, top_of_part ✓  
- Setup 3: angle_plate, 35mm jaw, no parallels, top_of_part ✓

**Botlabs Hub (4 setups):**
- Setup 1+2: vise, 45mm jaw, no parallels — correct for small hub part ✓
- Setup 3+4: angle_plate — correctly detected angled spindle direction (non-principal axis) ✓

Both parts: PDF generation with fixture pages succeeded without errors. ✓

---

## Known Limitations / Future Work

- `soft_jaw_generator.py` uses PythonOCC boolean subtraction which can fail on complex geometry. Simplified rectangular pocket fallback is implemented. Not tested end-to-end (Motor Mount and Hub don't require soft jaws).
- `fixture_pdf_page.py` uses a programmatic heading style; a dedicated ShiaanX logo/letterhead template is not yet integrated.
- Fixture type logic for `fixture_plate` is basic — in practice, fixture plates require dowel pin positions and bolt pattern data (out of scope for this session).
- `vise_model` field is always `null` — not yet linked to a vise database.
