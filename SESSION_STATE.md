# ShiaanX CAPP Pipeline — Session State

Paste this file into a new conversation to resume from where we left off.

---

## Project

ShiaanX is building an AI-driven CAD-to-process-plan pipeline for precision CNC manufacturing (aerospace/drone parts, aluminium 6061, 3-axis VMC). The pipeline lives in:

```
C:\Users\Siddhant Gupta\Documents\ShiaanX\Claude output for program sheet\
```

Git repo: https://github.com/siddhantg2311/shiaanx-CAPP (branch: main)

Python environment: `occ` conda env at `C:\Users\Siddhant Gupta\miniconda3\envs\occ\python.exe`

Note: scripts have numbered filenames (e.g. `1. extract_features.py`) — use `importlib.util.spec_from_file_location` to import them in Python, not normal imports.

---

## Pipeline Stages (in order)

| # | Script | Input | Output |
|---|--------|-------|--------|
| 1 | `1. extract_features.py` | `.step` file | `*_features.json` |
| 2 | `2. cluster_features.py` | `*_features.json` | `*_clustered.json` |
| 3 | `3. classify_features.py` | `*_clustered.json` | `*_classified.json` |
| 4 | `4. process_selection.py` | `*_classified.json` | `*_processes.json` |
| 5 | `5. setup_planning.py` | `*_processes.json` | `*_setups.json` |
| 6 | `7. tool_selection.py` | `*_setups.json` | `*_tools.json` |
| 7 | `8. parameter_calculation.py` | `*_tools.json` | `*_params.json` |
| 8 | `9. program_sheet.py` | `*_params.json` | `*_program_sheet.pdf` |

Helper modules (same folder): `coord_system.py`, `feature_graph.py`, `geometry_utils.py`
Tool database: `7a. tool_database.json` (version 2.0, 42 tools)

---

## Dataset

MFCAD++ dataset lives at:
```
Claude output for program sheet\Dataset\MFCAD_dataset\MFCAD++_dataset\
```

Test STEP files: `step\test\` (8,949 files)
Processed parts so far: `step\test\21\` and `step\test\25\` (each has their own subfolder with all intermediate JSONs)

feature_labels.txt: 25 feature classes (0=Chamfer, 1=Through hole ... 24=Stock)

---

## What Was Done This Session

### 1. Tool database upgraded to v2.0 (`7a. tool_database.json`)
- Added 4 new tool types: center drills (3), chamfer mills (3), slot mills (3), taps M2-M6 (5)
- Added `ramp_plunge` to all end mills and slot mills (ramp_angle_deg, vf_ramp_pct_of_feed, vf_plunge_pct_of_feed)
- Folded redundant top-level `Vc_rough`/`Vc_finish`/`fz_rough`/`fz_finish` into `material_params`
- Added `standard_tap_sizes` lookup table (M2–M12)
- Total: 28 → 42 tools

### 2. Setup planning improvements (`5. setup_planning.py`)
- Added `_build_workholding()` function — structured workholding dict per setup:
  - `type`: vise / step_jaw_vise / angle_plate / sine_plate / fixture_plate / custom_fixture
  - `clamp_faces`, `rest_face`, `clearance_faces`
  - `jaw_opening_mm` (from bbox)
  - `datum_from_setup` (cascades: setup 2 references setup 1, etc.)
  - `notes` (operator instruction)
- Added `_compute_wcs_origin()` function — actual 3D probe point in CAD space:
  - CORNER zero when part is placed at CAD origin (xmin≈0) — all G-code coords positive
  - CENTER zero when part is not aligned to CAD origin
  - Returns `{x_mm, y_mm, z_mm, origin_x, origin_y, origin_z, note}`
  - Handles all 6 principal directions correctly

### 3. Pipeline plumbing fix (`2. cluster_features.py`)
- `save_clusters()` now passes through `bounding_box`, `mass_properties`, `file`, `topology_counts` from features JSON
- Previously these were dropped, causing `jaw_opening_mm` and `wcs_origin_mm` to be null downstream

---

## What Is Still To Do (Priority Order)

### Medium priority
1. **Stock carryover across setups** (`5. setup_planning.py`)
   - Add `stock` dict to each setup: `{type, source_setup_id, remaining_faces}`
   - Setup 1 = raw billet, Setup 2+ = previous_setup stock

2. **Material awareness in naming** (`9. program_sheet.py`)
   - Currently material is implicit in tool selection
   - Add material prefix to strategy/preset names (like Toolpath's `Alu_` prefix)

### Low priority
3. **Wire new tool types into tool_selection.py**
   - `slot_mill` operation not yet handled in `_assign_tool_to_step()`
   - `chamfer_mill` operation not yet handled
   - `center_drill` not yet in `process_selection.py`
   - `tap_rh` not yet in process/tool selection

4. **Strategy key mapping layer**
   - `(material, feature_type, operation_type) → strategy_key` dict
   - Like Toolpath's `preset_naming_template.json`

5. **Request/response logging for debugging**

---

## Key Decisions Made

- Post-process fields (tool_number, length_offset) do NOT belong in tool_database.json — they are machine-specific, not tool properties
- Toolpath's inch-based tool library will NOT be imported — conversion unreliable for feeds/speeds
- `shiaanx-backend` (at github.com/siddhantg2311/shiaanx-backend) is a separate repo, independent of this one
- Dataset STEP files excluded from git via .gitignore (too large)

---

## How to Run a Part Through the Pipeline

```bash
PYTHON="C:/Users/Siddhant Gupta/miniconda3/envs/occ/python.exe"
DIR="C:/Users/Siddhant Gupta/Documents/ShiaanX/Claude output for program sheet"
STEP="Dataset/MFCAD_dataset/MFCAD++_dataset/step/test/25.step"

cd "$DIR"
"$PYTHON" "1. extract_features.py" "$STEP"
"$PYTHON" "2. cluster_features.py" "${STEP%.step}_features.json"
"$PYTHON" "3. classify_features.py" "${STEP%.step}_features_clustered.json"
# then process_selection, setup_planning, tool_selection, parameter_calculation, program_sheet
```

Move outputs into a numbered subfolder (e.g. `step/test/25/`) when done.

---

## Git Workflow

```bash
cd "C:/Users/Siddhant Gupta/Documents/ShiaanX"
git add "Claude output for program sheet/<changed file>"
git commit -m "description of change"
git push
```
