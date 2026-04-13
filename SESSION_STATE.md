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

Full pipeline capabilities and module descriptions are in CLAUDE.md — read that first.

---

## How to Run a Part Through the Pipeline

```bash
PYTHON="C:/Users/Siddhant Gupta/miniconda3/envs/occ/python.exe"
DIR="C:/Users/Siddhant Gupta/Documents/ShiaanX/Claude output for program sheet"
STEP="Dataset/MFCAD_dataset/MFCAD++_dataset/step/test/25.step"

cd "$DIR"
"$PYTHON" "10. run_pipeline.py" "$STEP"
# Or stage by stage:
"$PYTHON" "1. extract_features.py" "$STEP"
"$PYTHON" "2. cluster_features.py" "${STEP%.step}_features.json"
"$PYTHON" "3. classify_features.py" "${STEP%.step}_features_clustered.json"
"$PYTHON" "4. process_selection.py" "${STEP%.step}_features_clustered_classified.json"
"$PYTHON" "5. setup_planning.py"    "..._processes.json"
"$PYTHON" "7. tool_selection.py"    "...and so on"
"$PYTHON" "8. parameter_calculation.py" "..."
"$PYTHON" "9. program_sheet.py"     "..."
```

tool_selection and parameter_calculation default to `7a. tool_database.json` in the same directory — no `--db` flag needed unless overriding.

---

## What Was Completed (as of 2026-04-13)

### From Toolpath.ai competitive analysis:

**High priority — DONE**
- Tool database v2.0: added center drills, chamfer mills, slot mills, taps M2–M6, ramp/plunge data, restructured feeds/speeds into material_params (28 → 42 tools)
- Workholding config in setup_planning.py: structured dict per setup (type, clamp_faces, rest_face, clearance_faces, jaw_opening_mm, datum_from_setup)
- WCS origin (feature-driven): CORNER vs CENTER logic, all 6 spindle directions, actual CAD-space probe point

**Medium priority — DONE**
- Stock carryover across setups: raw_billet → previous_setup, remaining_faces tracking
- Material prefix in toolpath naming: `ALU 6 ENDMILL OUTER PROFILE RF` format
- WCS origin improvement: feature-driven, not always CENTER/TOP

**Low priority — DONE**
- Wire new tool types: chamfer_mill and slot_mill in tool_selection; tapped_hole process rule (spot→drill→tap_rh)
- Fix spot_drill → center_drill DB mismatch (tools were returning NOT_FOUND)
- Fix default DB path in tool_selection.py and parameter_calculation.py (`7a. tool_database.json`)
- Timestamped logging in run_pipeline.py (logs/ directory, per-stage timing)
- zlib STEP compression in geometry_utils.py (142 KB → 26 KB, round-trip verified)
- material_aliases in DB: aluminium_6061/6063/6082/7075/7050 all resolve correctly

**Decided NOT to implement (with reasons):**
- Import Toolpath's tool library — inch-based, unreliable feed/speed conversion (AD-002)
- Full strategy_key mapping layer — naming already shop-floor readable, material prefix covers it
- tap_rh in classify_features.py — no tapped-hole class in MFCAD++; process rule is ready and waiting

---

## What Is Still To Do

### Next: Rule sheets for ML improvement

The pipeline currently has all rules hardcoded in Python. The next architectural step is to extract them into JSON rule sheets that can be improved by ML or human feedback without touching code.

Priority order:

1. **Feature classification rule sheet** — geometry thresholds → feature type mapping
   - Most actionable: 8,949 labeled MFCAD++ examples available for training
   - Replace hardcoded if/else in `3. classify_features.py` with a loaded rule file
   - Longer term: train a classifier on the dataset

2. **Process selection rule sheet** — feature type + dimensions → operation sequence
   - Extract `TWIST_DRILL_MAX_DIA`, `DDR_PECK_MAX`, `TAP_DRILL_TABLE` etc. into JSON
   - Learned from: running pipeline on dataset and comparing to expert plans

3. **Feeds & speeds rule sheet** — material + operation → Vc/fz/ap/ae starting points
   - Currently in tool_database.json per tool; may want a separate material×operation matrix
   - Learned from: actual spindle load / surface finish data from machines

4. **Setup sequencing rule sheet** — feature distribution → setup ordering heuristics
   - Learned from: real setup sheets from shop floor

5. **Workholding rule sheet** — setup direction + part dimensions → fixture type
   - Learned from: machinist feedback on fixture choices

6. **Strategy naming rule sheet** — (material, feature_type, operation_type) → strategy key
   - Low priority; current naming already works

### Other pending items
- `slot_mill` and `pocket_mill` operations: process rules exist but `classify_features.py` doesn't yet emit `slot` or `pocket` feature types from MFCAD++ data (they show as `manual_review`)
- `tap_rh` is wired end-to-end but dormant until `classify_features.py` emits `tapped_hole` type
- Post-process fields (tool_number, length_offset): decided these belong in a job setup sheet at runtime, NOT in tool_database.json (AD-001)

---

## Key Decisions Made

See CLAUDE.md → Architectural Decisions (AD-001 through AD-008) for the full list.

---

## Git Workflow

```bash
cd "C:/Users/Siddhant Gupta/Documents/ShiaanX"
git add "Claude output for program sheet/<changed file>"
git commit -m "description of change"
git push
```
