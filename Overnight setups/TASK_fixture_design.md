# Overnight Task — Fixture Design Integration for Motor Mount

## Context (read this first)

Read `CLAUDE.md` and `SESSION_STATE.md` in the repo root before doing anything else. They contain full project context, file paths, pipeline architecture, and architectural decisions.

**Summary of what ShiaanX is:** An AI-driven CAD-to-process-plan pipeline for precision CNC parts. This task extends the pipeline to also output fixture specifications and soft jaw geometry, starting with the real Motor Mount part that has been machined by a vendor.

**Python environment:** conda env `occ`
**OCC Python executable:** `C:\Users\Siddhant Gupta\miniconda3\envs\occ\python.exe`
**Pipeline lives in:** `C:\Users\Siddhant Gupta\Documents\ShiaanX\Claude output for program sheet\`
**Motor Mount assets:**
- STEP file: `Claude output for program sheet\Manufactured parts\Motor Mount\MOTOR MOUNT.step`
- G-code (Fanuc format .tap): `Claude output for program sheet\Manufactured parts\Motor Mount\CAM Program\ncprograms\ncprograms\`
  - `1st setting\` — 10 programs (12mm EM, 4mm EM, 2mm EM, 4mm ball nose)
  - `2nd setting\` — 8 programs (8mm EM, 4mm EM, 2mm EM, 3mm ball nose, 12mm face mill)
  - `3rd setting\` — 2 programs (10mm EM, 4mm EM)
- Pipeline outputs already exist:
  - `MOTOR MOUNT_features.json` — face geometry, bounding box, mass properties
  - `MOTOR MOUNT_setups.json` — setup plan with workholding blocks
  - `MOTOR MOUNT_params.json` — full operation parameters

**Git branch to work on:** Create and work on `feature/fixture-design`. Commit frequently. Do not touch the main pipeline scripts unless instructed.

---

## Goal

Build a fixture design module for ShiaanX that:
1. **Reverse-engineers the real fixture** from vendor G-code (what WCS origin, what clamping envelope, what Z reference)
2. **Produces a structured fixture specification** per setup (machine-readable JSON)
3. **Generates soft jaw profiles** for vise setups as DXF files (machinable geometry)
4. **Adds a fixture page to the program sheet PDF** summarising clamping setup per setup
5. **Generalises** so it works on any part, not just Motor Mount

Work through the steps below in order. Each step has a clear deliverable. If a step takes too long or hits a blocker, document it and move to the next one.

---

## Step 1 — Reverse-engineer the vendor fixture from G-code

**Goal:** Understand exactly how the vendor held the motor mount in each setting.

Read all 20 `.tap` files across the 3 settings. For each setting, extract:

1. **WCS origin position** — the G54 zero point. Infer from:
   - The first G00 X Y move after G54 activation
   - The Z clearance height (G43 Z... H01) — this is Z0 = top of part or top of stock
   - The XY extents of all toolpaths — the bounding box tells you part size relative to zero

2. **Clamping envelope** — what X/Y/Z region the tool never enters (implying a clamp or jaw is there). Look for:
   - Large rapid moves that skip over a region
   - Z floor that the tool never goes below (= bottom of machined area = top of jaw or parallels)
   - Whether WCS zero is centred (XY symmetric) or corner-based

3. **Jaw opening** — from the Y extent of the part in the WCS frame. If Y goes ±34mm, jaw opening = ~68mm + clearance.

4. **Setup-to-setup relationship** — how the part is repositioned between settings. Compare WCS origins and Z0 levels across settings to infer which face was down in each setting.

Write your findings as structured JSON to:
```
audit\FINDINGS_fixture_gcode.json
```

Schema:
```json
{
  "settings": [
    {
      "setting": "1st",
      "wcs": "G54",
      "z_zero_interpretation": "top of stock / top of part / bottom of part",
      "z_zero_mm": <float>,
      "xy_zero_interpretation": "center / corner / other",
      "part_x_range_mm": [min, max],
      "part_y_range_mm": [min, max],
      "part_z_depth_mm": <float>,
      "inferred_clamped_face": "+Z / -Z / +Y / -Y / +X / -X",
      "inferred_jaw_opening_mm": <float>,
      "inferred_fixture_type": "vise / step_jaw_vise / fixture_plate / angle_plate",
      "notes": "..."
    }
  ]
}
```

Also write a human-readable markdown summary to `audit\FINDINGS_fixture_gcode.md`.

---

## Step 2 — Design the fixture specification schema

**Goal:** Define the structured data format that the pipeline will output for each setup.

The existing `setup_planning.py` already outputs a `workholding` block per setup. It looks like:
```json
{
  "type": "vise",
  "clamp_faces": ["+X", "-X"],
  "rest_face": "-Z",
  "clearance_faces": ["+Y", "+Z"],
  "jaw_opening_mm": 68.5,
  "datum_from_setup": "previous_top_face"
}
```

Extend this to a richer `fixture_spec` block. Design the full schema based on what you learned in Step 1, covering:

- `fixture_type`: vise / step_jaw_vise / angle_plate / sine_plate / custom_soft_jaw / fixture_plate
- `vise_model`: string — e.g. "Kurt D688" or null if unknown
- `jaw_type`: "standard_hard" / "soft_aluminum" / "step_jaw" / "custom_profile"
- `jaw_opening_mm`: float
- `jaw_height_mm`: float — standard 38mm for most Kurt vises; affects what Z clearance you have
- `parallels_mm`: float or null — height of parallels under part (raises part above jaw top)
- `clamped_faces`: list of face directions e.g. ["+X", "-X"]
- `rest_face`: which face sits on the jaw/parallels e.g. "-Z"
- `datum_face`: which face the WCS Z0 is probed off
- `z_zero_face`: "top_of_stock" / "top_of_part" / "bottom_of_part"
- `wcs_xy_zero`: "center_of_part" / "corner_of_part"
- `clamp_clearance_mm`: minimum clearance between jaw top and lowest tool path Z
- `soft_jaw_required`: bool — true if part geometry won't sit flat in standard hard jaws
- `soft_jaw_profile_file`: filename of generated DXF, or null
- `setup_notes`: list of strings — machinist-readable notes

Write the schema definition to `fixture_design\fixture_schema.json` with a `$schema` key, field descriptions, and one complete Motor Mount example per setting.

---

## Step 3 — Write `fixture_design\fixture_planner.py`

**Goal:** A module that takes `*_setups.json` (pipeline output) and the part bounding box from `*_features.json`, and outputs a `fixture_spec` per setup.

**File:** `Claude output for program sheet\fixture_design\fixture_planner.py`

**Rules for fixture type selection** (implement these in order, first match wins):

1. If setup `spindle_direction` is not a principal axis (i.e. angled) → `angle_plate` or `sine_plate`
2. If `jaw_opening_mm` > 200mm → `fixture_plate`
3. If setup is not the first setup (part has been partially machined) AND the rest face is curved or irregular → `soft_jaw_required = True`, `jaw_type = "custom_profile"`
4. If `jaw_opening_mm` > 100mm → `step_jaw_vise`
5. Otherwise → standard `vise`

**Rules for Z reference:**
- Setup 1 (raw billet): `z_zero_face = "top_of_stock"`, add `stock_above_part_mm` (from stock-to-leave in process plan)
- Setup 2+ (previously machined): `z_zero_face = "top_of_part"` (probe off finished face)

**Rules for jaw opening:**
- Use the bounding box dimension perpendicular to the clamped axis
- Add 5mm clearance each side
- Round up to nearest 5mm

**Rules for parallels:**
- If `jaw_opening_mm` < 50mm: no parallels needed (part sits directly on jaw serrations)
- If `jaw_opening_mm` 50–100mm: recommend 10mm parallels
- If `jaw_opening_mm` > 100mm: recommend 20mm parallels or step jaws

**Soft jaw flag:**
- Set `soft_jaw_required = True` if:
  - Any finished face used as `rest_face` has a non-planar geometry (cylinder, fillet) — check features JSON
  - OR `jaw_opening_mm` < 30mm (part too narrow for standard hard jaws to grip reliably)

**Input:** path to `*_setups.json` and `*_features.json`
**Output:** dict — same structure as `*_setups.json` but with `fixture_spec` added to each setup

Test by running against Motor Mount:
```powershell
& "C:\Users\Siddhant Gupta\miniconda3\envs\occ\python.exe" "Claude output for program sheet\fixture_design\fixture_planner.py" "Claude output for program sheet\Manufactured parts\Motor Mount\MOTOR MOUNT_setups.json" "Claude output for program sheet\Manufactured parts\Motor Mount\MOTOR MOUNT_features.json"
```

Write output to `MOTOR MOUNT_fixture_spec.json` in the Motor Mount folder. Print a human-readable summary to stdout showing each setup's fixture type, jaw opening, and whether soft jaws are needed.

---

## Step 4 — Write `fixture_design\soft_jaw_generator.py`

**Goal:** For any setup where `soft_jaw_required = True` or `jaw_type = "custom_profile"`, generate a **STEP file** of the soft jaw — a real 3D solid that can be opened in Fusion 360, verified visually, and sent directly to CAM to machine the jaw itself.

**File:** `Claude output for program sheet\fixture_design\soft_jaw_generator.py`

**What a soft jaw is:** A piece of aluminium held in the vise that has been machined to match the part's profile. The part sits in the pocket, gripped by matching geometry. For Motor Mount Setup 2 (flip setup), the previously machined outer profile from Setup 1 becomes the grip surface for Setup 2.

**Library:** PythonOCC — already installed in the `occ` env. No new installs needed. Key modules:
- `BRepPrimAPI_MakeBox` — jaw blank solid
- `BRepPrimAPI_MakeCylinder` — M8 screw holes
- `BRepAlgoAPI_Cut` — boolean subtraction (jaw blank minus part shape, minus screw holes)
- `BRepBuilderAPI_MakeEdge`, `BRepBuilderAPI_MakeFace` — chamfer construction if needed
- `BRepFilletAPI_MakeChamfer` — 1mm entry chamfer on pocket edges
- `STEPControl_Writer` — STEP export
- `STEPControl_StepModelType` — use `STEPControl_AsIs`
- Load the part STEP with `STEPControl_Reader` (already done in `1. extract_features.py` — reuse that pattern)

**How to build the jaw solid:**

1. **Load the part solid** from `MOTOR MOUNT.step` using `STEPControl_Reader`. Get the compound shape with `reader.OneShape()`.

2. **Compute jaw blank dimensions** from `fixture_spec`:
   - `jaw_width = jaw_opening_mm + 40mm` (20mm grip material each side)
   - `jaw_depth = 60mm` (standard soft jaw body depth front-to-back)
   - `jaw_height = parallels_mm + part_grip_height + 5mm clearance`
   - `part_grip_height` = the dimension of the part along the clamping axis (from bounding box in features JSON)

3. **Position the jaw blank** so it is centred on the part's clamped faces:
   - Use `gp_Trsf` and `BRepBuilderAPI_Transform` to translate the jaw blank into position relative to WCS origin
   - The jaw pocket opening faces the part's clamped face direction

4. **Boolean subtract the part** from the jaw blank:
   ```python
   from OCC.Core.BRepAlgoAPI import BRepAlgoAPI_Cut
   jaw_with_pocket = BRepAlgoAPI_Cut(jaw_blank, part_solid).Shape()
   ```
   This creates the exact negative of the part profile as the jaw pocket — handles all curves, fillets, bosses automatically without any manual profile extraction.

5. **Add M8 screw holes** (for mounting jaw to vise body):
   - Two holes: 30mm from each end of jaw, centred at mid-height
   - Diameter 8.5mm (clearance for M8), depth = full jaw depth
   - Boolean subtract two cylinders from the jaw solid

6. **Add 1mm chamfer** on the top edges of the jaw pocket (entry chamfer so part loads easily):
   ```python
   from OCC.Core.BRepFilletAPI import BRepFilletAPI_MakeChamfer
   ```
   Select the top pocket edges and apply 1mm chamfer.

7. **Apply 0.1mm offset** to the pocket (interference fit):
   - Use `BRepOffsetAPI_MakeOffsetShape` with offset = +0.1mm on the part solid before subtracting, so the jaw pocket is 0.1mm smaller than the part → light press fit
   - If offset fails (complex geometry), skip and add a note to the STEP file name: `_CLEARANCE_FIT`

8. **Export as STEP:**
   ```python
   from OCC.Core.STEPControl import STEPControl_Writer, STEPControl_AsIs
   from OCC.Core.IFSelect import IFSelect_RetDone
   writer = STEPControl_Writer()
   writer.Transfer(jaw_solid, STEPControl_AsIs)
   status = writer.Write(output_path)
   ```

9. **Also export a pair** — generate both the left jaw and right jaw (mirror of left across the part centre plane) as separate STEP files. In a standard vise both jaws are identical for symmetric parts, but generate both for clarity.

**Output files** (for Motor Mount Setup 2):
```
Claude output for program sheet\Manufactured parts\Motor Mount\MOTOR MOUNT_setup2_soft_jaw_LEFT.step
Claude output for program sheet\Manufactured parts\Motor Mount\MOTOR MOUNT_setup2_soft_jaw_RIGHT.step
```

**Fallback:** If the boolean subtraction fails (degenerate geometry, OCC topology error), catch the exception and fall back to a simplified rectangular pocket at bounding box dimensions. Write the fallback STEP with `_SIMPLIFIED` suffix and print a warning: `WARNING: Soft jaw profile simplified — verify pocket dimensions against part drawing before machining`.

**Test:** Run against Motor Mount. Open the output STEP in any CAD viewer to verify the jaw pocket matches the part outer profile.

---

## Step 5 — Add a fixture page to the program sheet PDF

**Goal:** Extend `9. program_sheet.py` to include a fixture summary page per setup.

Do NOT modify `9. program_sheet.py` directly. Instead:

1. Create `fixture_design\fixture_pdf_page.py` — a helper that takes a `fixture_spec` dict and a `reportlab` canvas and draws one fixture summary page.

2. Call it from `9. program_sheet.py` by adding an import at the top (via `importlib.util` per AD-009 convention) and inserting the fixture page after each setup's tool list page.

**Fixture page layout (one page per setup):**

```
┌─────────────────────────────────────────────────────┐
│  SETUP 1 — FIXTURE SPECIFICATION                    │
├─────────────────────┬───────────────────────────────┤
│  Fixture Type       │  Vise (Standard Hard Jaws)    │
│  Jaw Opening        │  75 mm                        │
│  Jaw Height         │  38 mm                        │
│  Parallels          │  10 mm                        │
│  Clamped Faces      │  +X, -X                       │
│  Rest Face          │  -Z                           │
│  Datum Face         │  +Z (top of stock)            │
│  WCS XY Zero        │  Centre of part               │
│  Soft Jaws Required │  No                           │
├─────────────────────┴───────────────────────────────┤
│  SETUP NOTES                                        │
│  • Zero off top face of raw billet                  │
│  • Ensure parallels are seated before torquing vise │
│  • Minimum 25mm jaw engagement each side            │
└─────────────────────────────────────────────────────┘
```

If `soft_jaw_required = True`, add a highlighted box:
```
⚠ SOFT JAWS REQUIRED — See: MOTOR MOUNT_setup2_soft_jaw_LEFT.step / _RIGHT.step
```

Use `reportlab` (already used by `9. program_sheet.py`). Match the existing PDF visual style (same font, same table borders, same header colour).

**Test:** Re-run `9. program_sheet.py` on Motor Mount params and verify fixture pages appear after each setup's tool list.

---

## Step 6 — Wire into `10. run_pipeline.py`

Add fixture planning as Stage 6a in the pipeline runner, between setup planning (Stage 5) and tool selection (Stage 6). It should:

- Call `fixture_planner.py` automatically
- Write `*_fixture_spec.json` alongside the other outputs
- If any setup has `soft_jaw_required = True`, call `soft_jaw_generator.py` and write the DXF
- Log fixture stage timing to the pipeline log like all other stages

No new CLI flags needed — fixture planning always runs.

---

## Step 7 — Generalise and test on a second part

Run the full updated pipeline (with fixture planning) on one of the MFCAD++ test parts to confirm it generalises beyond Motor Mount:

```powershell
conda run -n occ python "Claude output for program sheet\10. run_pipeline.py" "Claude output for program sheet\Dataset\MFCAD_dataset\MFCAD++_dataset\step\test\25.step"
```

Check:
- `fixture_spec` is generated for each setup
- Fixture types are sensible given the part geometry
- No crashes or KeyErrors
- If soft jaws triggered, DXF is written and valid

---

## Step 8 — Write session update and update SESSION_STATE.md

When all steps are done (or as many as possible), do two things:

### 8a — Write `audit\SESSION_UPDATE_fixture_design.md` with:

```markdown
# Session Update — Fixture Design Integration

**Date:** 2026-06-24
**Branch:** feature/fixture-design

## What was completed
- [ ] Step 1: G-code reverse engineering
- [ ] Step 2: Fixture spec schema
- [ ] Step 3: fixture_planner.py
- [ ] Step 4: soft_jaw_generator.py
- [ ] Step 5: PDF fixture page
- [ ] Step 6: run_pipeline.py wiring
- [ ] Step 7: Generalisation test

## Key findings from G-code analysis
[fill in — WCS origins, clamping envelope, fixture type inferred per setting]

## Motor Mount fixture specs (one line per setup)
[fill in — e.g. "Setup 1: Vise, 75mm jaw opening, 10mm parallels, no soft jaws"]

## What the soft jaw DXF looks like
[describe — dimensions, profile shape, layers]

## Blockers / deferred items
[anything that didn't complete and why]

## Files created
[list all new files with one-line description each]
```

---

### 8b — Update `SESSION_STATE.md` in the repo root

Add a new section after the "Closed-Loop Inspection System" section. The section should be titled `## Fixture Design Module` and include:

- What was built (fixture_planner.py, soft_jaw_generator.py, fixture_pdf_page.py)
- Key findings from the G-code analysis (what fixture the vendor actually used per setting)
- Motor Mount fixture specs per setup (fixture type, jaw opening, parallels, soft jaw Y/N)
- Location of generated files (`fixture_design/` folder, `MOTOR MOUNT_fixture_spec.json`, soft jaw STEP files)
- Branch: `feature/fixture-design`
- Any known limitations or next steps

Also update the **Pipeline Fixes Priority Queue** table to add a new row:

```
| ✅ DONE | — | Fixture design module: fixture_planner.py + soft_jaw_generator.py + PDF page | This session | fixture_design/ |
```

---

## Commit instructions

Use the `shiaanx-CAPP` git repo (not shiaanx-backend). Commit after each step with descriptive messages:

```bash
cd "C:\Users\Siddhant Gupta\Documents\ShiaanX"
git checkout -b feature/fixture-design
git add "Claude output for program sheet/fixture_design/" audit/
git commit -m "feat(fixture): <description>"
git push origin feature/fixture-design
```

Do NOT push to main — leave as a feature branch for review.

---

## What NOT to do

- Do not modify `1. extract_features.py` through `8. parameter_calculation.py` (existing pipeline stages)
- Do not add FEA, clamping force calculations, or collision detection — that is explicitly out of scope
- Do not redesign the workholding block that already exists in `setup_planning.py` — extend it by adding `fixture_spec` alongside it, do not replace it
- Do not install packages other than `ezdxf` without checking that `occ` env doesn't already have them first
