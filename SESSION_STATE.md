# ShiaanX CAPP Pipeline — Session State

Paste this file into a new conversation to resume from where we left off.

---

## Project

ShiaanX is building an AI-driven CAD-to-process-plan pipeline for precision CNC manufacturing (aerospace/drone parts, aluminium 6061, 3-axis VMC). The pipeline lives in:

```
C:\Users\Siddhant Gupta\Documents\ShiaanX\Claude output for program sheet\
```

Git repo: https://github.com/siddhantg2311/shiaanx-CAPP (branch: main)

Python environment: conda env named `occ` (create from `environment.yml`)

Note: scripts have numbered filenames (e.g. `1. extract_features.py`) — use `importlib.util.spec_from_file_location` to import them in Python, not normal imports.

Full pipeline capabilities and module descriptions are in CLAUDE.md — read that first.

---

## How to Run a Part Through the Pipeline

```bash
DIR="C:/Users/Siddhant Gupta/Documents/ShiaanX/Claude output for program sheet"
STEP="Dataset/MFCAD_dataset/MFCAD++_dataset/step/test/25.step"

cd "$DIR"
conda run -n occ python "10. run_pipeline.py" "$STEP"
# Or stage by stage:
conda run -n occ python "1. extract_features.py" "$STEP"
conda run -n occ python "2. cluster_features.py" "${STEP%.step}_features.json"
conda run -n occ python "3. classify_features.py" "${STEP%.step}_features_clustered.json"
conda run -n occ python "4. process_selection.py" "${STEP%.step}_features_clustered_classified.json"
conda run -n occ python "5. setup_planning.py"    "..._processes.json"
conda run -n occ python "7. tool_selection.py"    "...and so on"
conda run -n occ python "8. parameter_calculation.py" "..."
conda run -n occ python "9. program_sheet.py"     "..."
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

### Rule sheets for ML improvement

The pipeline still has many rules hardcoded in Python. The next architectural step is to extract them into **versioned JSON rule sheets** that can be improved by ML or human feedback without touching code.

**Scope:** **7 sheets** — six that map to tunable pipeline stages, plus one **MFCAD++ bridge**.

#### Core 6 (map 1:1 to pipeline stages that need tunable rules)

| # | Sheet | Pipeline stage |
|---|--------|-----------------|
| 1 | Feature classification rules | `3. classify_features.py` — geometry thresholds, topology cues, priority order |
| 2 | Process selection rules | `4. process_selection.py` — feature + size + DDR → operation sequence, stock-to-leave |
| 3 | Tool matching policy | `7. tool_selection.py` — selection logic, substitution tolerances, fallbacks |
| 4 | Cutting parameter rules | `8. parameter_calculation.py` — material × operation × pass → Vc, fz, ap, ae defaults |
| 5 | Setup planning rules | `5. setup_planning.py` — axis clustering, setup ordering, datum stability constraints |
| 6 | Workholding / fixture rules | `5. setup_planning.py` — envelope → vise type, jaw heuristics, clamp/rest faces |

**Note:** Datum & WCS behaviour (see AD-006) is **not** a separate sheet — encode it as a **sub-section** of the setup planning rules (sheet 5).

#### +1 because MFCAD++ exists

| # | Sheet | Role |
|---|--------|------|
| 7 | Label / taxonomy map | Bridges MFCAD++ class IDs → internal `feature_type` enum — required before ML can train/evaluate on the dataset |

#### Deferred (explicitly not separate sheets for now)

| Idea | Why skip (for now) |
|------|---------------------|
| Confidence & escalation | Add a **warnings** (or similar) field per rule row where relevant — a standalone sheet has nothing to anchor to until the others exist |
| Validation / golden-test | Test harness, not a rule sheet — use MFCAD++ test parts and CI/regression scripts |
| Strategy / naming template | Toolpath naming is already defined in `9. program_sheet.py` — revisit when integrating with real CAM |

#### Practical order to build

1. **Label / taxonomy (7)** — unlocks MFCAD++ training data immediately  
2. **Feature classification (1)** — highest leverage for ML replacement  
3. **Process selection (2)** — most logic currently hardcoded  
4. **Tool matching policy (3)** — separates “what tools exist” (DB) from “how to pick” (policy)  
5. **Cutting parameters (4)** — consolidate what is split across tool DB and code  
6. **Setup planning (5) + Workholding (6)** — build together; they share the same part geometry inputs  

Each sheet should carry **`schema_version`** / **`ruleset_id`** (and optional **`updated_at`**) so runs and ML experiments stay reproducible.

#### Rule sheet files (on disk)

Rule sheets are **versioned JSON** (and a small manifest) kept next to the pipeline so they can be edited, diffed, and eventually loaded at runtime without changing Python for every tweak.

**All seven sheets** (`01`–`07`) now have JSON files in this folder. The Python stages still implement the same behaviour until you add a loader.

**Location (relative to repo / project root):**

```
Claude output for program sheet/rule_sheets/
```

**File naming:** `NN_<descriptive_name>.json` where `NN` is the sheet number (**01–07**) so folders sort in the same order as the “practical order to build” list above.

**What “good” looks like:** every JSON file starts with metadata (`schema_version`, `ruleset_id`, optional `updated_at`, short `description`) so experiment logs can say *which* rules produced an output. Optional fields like `warnings` or `process_selection_ready` document gaps (e.g. a label exists for ML but the milling sequence is not implemented yet).

---

##### `README.txt` (manifest)

Plain-text index of which sheets exist, which are planned, and what each filename is for. Use it as a quick orientation before opening JSON.

---

##### `07_label_taxonomy.json` — Sheet 7 (label / taxonomy map)

**Status:** done (first usable sheet — unlocks MFCAD++ supervision).

**What it is:** For each **MFCAD++ label id** (0–24 from `feature_labels.txt`), this file records the **ShiaanX `internal_feature_type`** you want models and metrics to use, plus flags for whether **`classify_features.py`** can emit that type today and whether **`process_selection.py`** already has a real rule (vs `manual_review`).

**Why it matters:** The dataset speaks in MFCAD ids; your pipeline speaks in `through_hole`, `pocket`, etc. Without this map, you cannot train or evaluate a classifier against MFCAD++ in a way that lines up with downstream stages.

**Example (one row — the file contains all 25 ids):**

```json
{
  "mfcad_id": 1,
  "mfcad_name": "Through hole",
  "internal_feature_type": "through_hole",
  "process_selection_ready": true,
  "classify_features_emits": true,
  "warnings": null
}
```

---

##### `01_feature_classification.json` — Sheet 1 (feature classification rules)

**Status:** started — **thresholds and decision order** are captured; the full if/else tree still lives in `3. classify_features.py` until a loader is wired.

**What it is:** Tunable **numbers** (mm, ratios, mm²) and a written **decision priority** that mirror `classify_cluster()`: large-bore cutoff, single-face through-hole DDR cutoff, pocket vs planar face area limit, multi-radius bore drillability cutoff, and how `_angled` suffixes attach.

**Why it matters:** This is the first place you’ll want to “turn the knobs” when moving from synthetic parts to production geometry, or when fitting thresholds from data — without a redeploy for every constant change.

**Example (one threshold block — the file groups all of them under `thresholds_mm`):**

```json
{
  "thresholds_mm": {
    "large_bore_radius_mm": {
      "value": 10.0,
      "unit": "mm",
      "role": "Radius above which a single-step bore is large_bore; also used in multi-radius bore max-radius check."
    }
  }
}
```

---

##### `02_process_selection.json` — Sheet 2 (process selection rules)

**Status:** done — mirrors constants and tables from `4. process_selection.py` (loader TBD).

**What it is:** Drill diameter bands (micro / twist / pilot+core / boring), **DDR → standard | peck | deep_peck**, **material stock-to-leave** for RF passes, **face mill max ap** per material, **RF split op set**, **tap drill ISO table**, and **corner-R feature types**.

**Why it matters:** This is the bulk of “what operations appear on the program sheet” logic — the first sheet you’ll tune for shop-specific drilling and roughing practice.

**Example (tap drill row inside `tap_drill_table_mm`):**

```json
"6.0": 5.0
```

---

##### `03_tool_matching_policy.json` — Sheet 3 (tool matching policy)

**Status:** done — policy only; catalogue data stays in `7a. tool_database.json`.

**What it is:** **Exact vs nearest** rules, **spot/center drill** coverage rule, **circular interp** and **contour** diameter fractions, **face mill** “smallest ≥ feature”, **chamfer** and **slot** selection, **`_query_tool`** drill-vs-mill behaviour, and **spot_drill ↔ center_drill** alias.

**Why it matters:** Separates *how you pick* from *what tools exist* — essential before ML or shop libraries change one without breaking the other.

**Example:**

```json
"circular_interp": {
  "target_fraction_of_bore_diameter": 0.45
}
```

---

##### `04_cutting_parameters.json` — Sheet 4 (cutting parameter rules)

**Status:** done — machine + formula policy; per-tool numbers remain in the DB.

**What it is:** **Max RPM**, **coolant modes**, **peck Q fractions**, **TSC Vc boost** for small drills, **RPM/Vf formulas**, **pass-type Vc/fz sourcing** (RF vs FINISH), **ap/ae** rules per operation (including contour/pocket **ae ratios**), **spot depth** heuristic, **tool-change time** for estimates. **Ramp/plunge** is referenced as DB-only (AD-004).

**Why it matters:** One place to align every part with a machine envelope and coolant mode before you learn feeds from real cuts.

**Example:**

```json
"through_spindle": { "peck": 0.8, "deep_peck": 0.5 }
```

---

##### `05_setup_planning.json` — Sheet 5 (setup planning rules)

**Status:** done — grouping and WCS policy; full coordinate math stays in code for now.

**What it is:** **VMC spindle convention**, **axis parallel tolerance**, **same-direction grouping**, **sort order** (principal before angled, then by feature count), **G54–G59** assignment, **corner-zero 2% heuristic** (AD-006), **stock face accumulation** from `clearance_faces`, **machinable filters**.

**Why it matters:** Controls how many setups and in what order — high impact on cycle time and datum error.

**Example:**

```json
"wcs": {
  "sequence": ["G54", "G55", "G56", "G57", "G58", "G59"]
}
```

---

##### `06_workholding.json` — Sheet 6 (workholding / fixture rules)

**Status:** done — structured templates from `_build_workholding()`; prose `fixture_note` strings still built in Python.

**What it is:** **Angled → sine_plate** template; **+Y / -Y / ±X / ±Z** principal spindle paths with **type** (vise, step_jaw_vise, angle_plate, fixture_plate), **clamp / rest / clearance** faces, **jaw_opening_mm** bbox mapping, **datum_from_setup** cascade, **custom_fixture** fallback.

**Why it matters:** Makes fixture choices explicit and editable before you learn from machinist feedback or ML.

**Example:**

```json
{
  "type": "vise",
  "clamp_faces": ["+X", "-X"],
  "clearance_faces": ["+Y"]
}
```

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
