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

## Feature Recognition Audit — Motor Mount (2026-06-23, COMPLETE)

Branch: `audit/feature-recognition-motor-mount`

Full audit of the clustering + classification pipeline against a real machined Motor Mount part (4 setups, Sinumerik 828D, 14 tools). Ground truth from MPF G-code + setup sheet PDFs.

**Final results: Pre-fix 62.5% → Post-fix 100.0% (8/8 feature types detected)**

**Four bugs fixed (commit dcc6cc822):**
1. **P0 — Connected-component plane seeding** (`2. cluster_features.py`): `find_seeds()` Rule 3 planted one seed per normal direction → all Z-up planes (stock + pocket floors + steps) merged into 1015-face background. Fix: BFS within each normal-direction group to find disconnected components; one seed per component.
2. **Chamfer face exclusion** (`2. cluster_features.py`): cylinder-adjacency skip excluded chamfer planes (at 45° to bore axis). Fix: only skip planes where `dot(plane_normal, cyl_axis) > 0.9` (true cap planes).
3. **is_principal_axis for plane clusters** (`2. cluster_features.py`): `get_feature_axis()` returns None for plane clusters (no cylinders) → `is_principal_axis` was always None. Fix: derive from seed face plane normal.
4. **Chamfer classification** (`3. classify_features.py`): added `CHAMFER_MAX_AREA_MM2=100.0` and chamfer detection (`is_principal=False AND face_count==1 AND area<100mm²`).

**Cluster count:** 71 → 100 | **Background cluster:** 1015 → 945 faces
**Pockets:** 0 → 21 | **Planar_face:** 0 → 21 | **Chamfers:** 0 → 4

**All audit files:** `C:\Users\Siddhant Gupta\Documents\ShiaanX\audit\`
Key files: `FINDINGS_feature_recognition.md`, `accuracy_breakdown_motormount_postfix.txt`, `gen_postfix_report.py`, `MOTOR MOUNT_classified.json`

**Note on rule sheet + code changes:** The rule sheet override in `01_feature_classification.json` runs at module import time and overrides Python constants. Code-only changes to classify_features.py constants are silently neutralised. Always update BOTH.

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

**All seven sheets** (`01`–`07`) now have JSON files in this folder. **Loaders are wired into all relevant pipeline stages** (`3. classify_features.py`, `4. process_selection.py`, `5. setup_planning.py`, `7. tool_selection.py`, `8. parameter_calculation.py`) — rule sheets are active at runtime.

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

### Rule Sheets — Understanding Goals

Siddhant wants to understand each rule sheet in detail — what the rules mean, why each threshold/decision exists, and how they connect to real machining practice. This is a priority for future sessions alongside the ML improvement work.

### ML Model — MFCAD++ Feature Pipeline Improvement (in progress)

**Goal:** Use MFCAD++ ground truth to evaluate and improve `3. classify_features.py`, then train an ML classifier.

**Dataset notes:**
- Labels are **embedded in STEP files** as the name argument of `ADVANCED_FACE`: e.g. `ADVANCED_FACE('1', ...)` = Through hole (label 1). Face index i in the pipeline JSON = i-th `ADVANCED_FACE` in the STEP file (OCC iterates in STEP file order).
- Pre-processed hierarchical B-Rep graphs in `.h5` files (`hierarchical_graphs/`)
  - `V_1`: face-level features — [surface_area, centroid_x, centroid_y, centroid_z, surface_type]
  - `labels`: face-level class labels (0–24)
  - `CAD_model`: maps back to STEP filename
  - Each H5 group = one batch; `idx[i]` = [V1_global_start, V2_global_start] for model i; face range for model i = `idx[i][0] - idx[0][0]` to `idx[i+1][0] - idx[0][0]`
  - Adjacency matrices (B-Rep, mesh, convex/concave/smooth edges)
- **h5py installed** in `occ` env via pip (`pip install h5py` — conda solver conflicts with vtk-base HDF5 pin)

**Bridge:** each cluster in `_classified.json` has `face_indices` → look up GT label per face via STEP file → majority vote = expected class for cluster → translate via `07_label_taxonomy.json`.

**Plan:**

1. **Phase 1 — Evaluation Framework** ✅ DONE
   - Label encoding confirmed: `ADVANCED_FACE('N', ...)` name field = MFCAD++ class ID
   - `evaluate_classifier.py` written: loads `_classified.json` + STEP GT → per-class precision/recall/F1 + confusion matrix
   - Baseline established on parts 21 & 25

   **Baseline results (2026-04-15):**
   | Part | Clusters | Correct | Accuracy |
   |------|----------|---------|----------|
   | 25   | 9        | 2       | 22%      |
   | 21   | 24       | 3       | 12.5%    |

   **Root cause:** Pipeline implements rules for ~10 of 25 MFCAD++ classes. Unimplemented classes (`triangular_passage`, `six_sided_passage`, `circular_blind_step`, `slanted_through_step`, etc.) fall through to the nearest geometric match (`planar_face`, `pocket`). Confirmed by confusion matrix — errors are systematic gaps, not noise.

2. **Phase 2 — Improvement Loop** ✅ DONE (concluded)
   - `visualise_labels.py` written and working
   - Inspected cluster data for parts 21 & 25 — root cause confirmed
   - Added `pocket_max_perp_walls=8` threshold to fix Stock→pocket false positives
   - **Concluded:** rule-based fixes have hit a ceiling. Misclassifications for `circular_blind_step`, `triangular_passage`, `six_sided_passage` are caused by clustering splitting feature faces apart — not fixable at classification stage without fixing upstream clustering. Decision: skip further rule patching, go to ML.

3. **Phase 3 — ML Model** ← NEXT
   - **Strategy:** MFCAD++ baseline first, then real-part flywheel
   - **Model level:** face-level (not cluster-level) — survives poor clustering, generalises better
   - **Model type:** Random Forest first (fast, interpretable, small-data friendly) → GNN later (500+ real parts)
   - **Long-term vision:** feedback capture loop where machinist corrections on real jobs become training data — this is the moat
   - **MFCAD++ baseline plan:**
     - 3a: Extract face-level features from `.h5` files → `features.csv`
     - 3b: Train Random Forest / XGBoost on face features (surface_area, centroid, surface_type, adjacency stats)
     - 3c: Wire model into `classify_features.py` as `--mode ml` flag
     - 3d: Evaluate on held-out MFCAD++ parts, establish per-class F1 baseline
     - 3e: When real parts come in — corrections from program sheet review become new training rows

**Immediate next actions:**
- [x] Explore `.h5` file structure — confirmed V_1 (5 face features), labels, adjacency matrices A_1, train/val/test splits
- [x] Write `ml_train_classifier.py` — Random Forest on 10 features (5 face + 5 neighbourhood), ~1M training faces
- [x] scikit-learn + joblib installed in occ env
- [x] Run `ml_train_classifier.py` — **66.0% overall accuracy** (2026-04-18), model saved to `models/rf_classifier.pkl`
- [x] Per-class F1 breakdown — run `ml_perclass_f1.py` (2026-04-20), saved to `models/perclass_f1.json`
- [x] Per-part majority voting tested (2026-04-20) — **failed**: B-Rep adjacency connects feature faces to Stock faces making each part one large component; Stock dominates every vote (66% → 39.5%). Voting only viable at pipeline cluster level, not raw B-Rep level.
- [x] **Run `ml_train_classifier_v2.py`** — **69.2% overall accuracy** (2026-04-20), model saved to `models/rf_classifier_v2.pkl`; +3.2pp vs v1; top features: two_hop_degree, neigh_area_mean, area, comp_area_ratio
- [x] **Wire v2 model into `classify_features.py` with `--mode ml` flag** (2026-04-20) — DONE
  - Usage: `python "3. classify_features.py" <clustered.json> [output.json] --mode ml [--features <features.json>]`
  - Features inferred from input path if `--features` omitted
  - Uses B-Rep connected components to match training distribution
  - `_angled` suffix still applied from `is_principal_axis`
  - `ml_mfcad_id` and `ml_vote_counts` fields added to each cluster for debugging
  - **Known limitation:** Training used H5 pre-extracted features; inference uses our pipeline's feature extraction → distribution mismatch causes weaker predictions on real parts. Fix: retrain using our pipeline's `*_features.json` as feature source.
- [x] **Retrain RF using pipeline-native features (v3)** (2026-04-20) — DONE
  - Root cause confirmed: H5 has ~25 faces/part; our OCC pipeline extracts ~37 (full STEP ADVANCED_FACE). Not comparable.
  - Fix: train on `*_features.json` (our pipeline) + STEP ADVANCED_FACE GT labels. 0 mismatches.
  - **59.0% accuracy** on 356-part subset — lower than v2 (69.2%) because far fewer training faces, but gap is CLOSED.
  - Verified on part 53133: through_hole, pocket, passages correctly detected (vs v2 predicting all background).
  - `classify_features.py --mode ml` now auto-selects v3 over v2.
  - `ml_batch_extract.py` generates `*_features.json` for all 8949 MFCAD++ test parts (was 308 → 630+ and counting).
- [x] **Run ml_batch_extract.py to exhaustion** (2026-04-20) — 8790 parts extracted; parallelized to 15 workers (12-core machine), ~6 files/sec
- [x] **Retrain v3 on full 8790-part dataset** (2026-04-20) — **66.2% accuracy**, zero train/inference gap, model saved to `models/rf_classifier_v3.pkl`
  - Strong (F1 ≥ 0.80): Stock 0.990, Circular end pocket 0.882, Circular blind step 0.870, Through hole 0.854, O-ring 0.835
  - Weak: Rectangular blind slot 0.044, slots generally — face-level features insufficient; need cluster-level features (DDR, wall count)
  - `classify_features.py --mode ml` auto-selects v3
- [x] **Train v4 RF with 18 features (+ cluster-proxy features)** (2026-05-02) — **65.8% accuracy** on 52,776 test faces
  - Script: `ml_train_classifier_v4.py`; training set 7031/7032 parts (1 skipped), 211,387 faces, 25 classes
  - New features added: `comp_size`, `comp_area_ratio`, `comp_cyl_radius_mean`, `comp_plane_frac`, `comp_type_diversity`, `comp_bbox_ddr`, `comp_aspect_ratio`, `two_hop_degree`
  - Top features: `two_hop_degree` (0.095), `area` (0.088), `comp_area_ratio` (0.086), `neigh_area_mean` (0.085)
  - Strong (F1 ≥ 0.80): Stock 0.991, Circular end pocket 0.880, O-ring 0.843, Through hole 0.851, Circular blind step 0.871, Round 0.751
  - Still weak: Rectangular blind slot 0.040 (recall=0.021), Triangular through slot 0.158, Rectangular through slot 0.210
  - v4 marginally lower than v3 overall (65.8% vs 66.2%) — cluster-proxy features helped some classes but hurt others
  - Model saved: `models/rf_classifier_v4.pkl`, encoder: `models/rf_label_encoder_v4.json`

**Next improvement options:**
- Investigate why v4 cluster-proxy features didn't beat v3 — check feature distribution for slot/passage classes
- Try GBM (XGBoost/LightGBM) with same 18 features — often +3–5pp over RF on tabular data
- Wire `--mode ml` into `10. run_pipeline.py` as an option
- Start collecting real-part labeled data for the feedback flywheel
- **Integrate with Autodesk Fusion** — see "Fusion 360 CAM Integration" section below (in progress)

### Autonomous Agent (built 2026-05-04, not yet run)

A thin autonomous improvement loop that searches the internet for labeled CAD datasets, retrains the classifier, and auto-promotes if accuracy improves. Uses Gemini Flash (free) for two decision calls per cycle.

**Full state and setup instructions:** `Claude output for program sheet/Autonomous Agent/AGENT_STATE.md`

**Blockers before first run:**
1. Place Kaggle API token at `C:\Users\Siddhant Gupta\.kaggle\kaggle.json`
2. Get free Gemini API key at aistudio.google.com/apikey → set `$env:GEMINI_API_KEY`
3. Run: `conda run -n occ python "Claude output for program sheet/Autonomous Agent/agent_loop.py" --once`

**Per-class F1 results (2026-04-20) — baseline RF, 10 face-level features:**

Strong (F1 ≥ 0.80):
- Stock: 0.998 (57K faces — dominates dataset)
- Circular end pocket: 0.902
- Through hole: 0.881
- Circular blind step: 0.854
- Round: 0.810
- O-ring: 0.803

Weak (F1 < 0.40) — all slots and passages:
- Rectangular blind slot: 0.066 (recall=0.036 — nearly never predicted)
- Triangular through slot: 0.131
- Rectangular through slot: 0.143
- Triangular passage: 0.224
- Slanted through step: 0.307
- Rectangular through step: 0.397

**Root cause of weak classes:** Slots and passages are topologically similar to pockets/steps. Face-level features (area, centroid, surface_type, adjacency stats) can't distinguish them. Need richer cluster-level features: DDR, aspect ratio, face count, wall count.

**H5 file structure (confirmed 2026-04-17):**
- Each H5 file has numbered groups (0, 1, 2, ...) — each group = one batch of ~25 parts
- Per group:
  - `V_1`: (n_faces, 5) — [surface_area, cx, cy, cz, surface_type] normalised float32
  - `labels`: (n_faces,) — GT class 0–24 per face
  - `A_1_idx/shape/values`: sparse B-Rep adjacency matrix (face-face)
  - `idx`: (n_parts, 2) — maps each part within batch to its face range
  - `CAD_model`: STEP filenames in this batch
- Splits: training=1472 batches, val=312 batches, test=317 batches

**train_classifier.py (written 2026-04-17):**
- Location: `Claude output for program sheet/train_classifier.py`
- Features: 10-dim per face — [area, cx, cy, cz, surf_type, neigh_degree, neigh_type_mean, neigh_type_std, neigh_area_mean, neigh_area_std]
- Model: RandomForest, 200 trees, all CPU cores, random_state=42
- Outputs: `models/rf_classifier.pkl`, `models/rf_label_encoder.json`, appends to `metrics_log.csv`
- Run: `conda run -n occ python "Claude output for program sheet/train_classifier.py"`

---

### Fusion 360 CAM Integration (in progress)

**Goal:** Import ShiaanX process plans directly into Fusion 360 CAM as operations — user selects geometry, then simulates and posts G-code.

**Architecture:** Fusion 360 add-in (local, no backend required for v1).

**Add-in location:**
```
%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns\ShiaanX\
  ShiaanX.py          ← entry point, registers "Import ShiaanX Plan" in Manufacture workspace
  ShiaanX.manifest    ← add-in metadata
  cam_importer.py     ← core logic: params.json → Fusion CAM setups + operations
```

**Flow:**
1. User runs pipeline → gets `*_params.json`
2. Opens Fusion, switches to Manufacture workspace
3. Loads add-in via Tools → Add-Ins (Shift+S) → Run ShiaanX
4. Clicks "Import ShiaanX Plan" → picks `*_params.json` via file dialog
5. Add-in creates one Fusion CAM setup per ShiaanX setup, one operation per process step (correct strategy, tool, feeds/speeds, depths pre-filled)
6. User selects geometry for each operation → Generate Toolpaths → Simulate → Post

**Operation → Fusion CAM strategy mapping:**
- face_mill → facing
- contour_mill → contour2d
- pocket_mill → pocket2d
- twist/spot/center/pilot/core drill / deep_peck → drilling
- circular_interp / boring_bar → bore
- chamfer_mill → chamfer2d
- tap_rh → tapping
- slot_mill → slot2d

**Status (2026-05-07):** ✅ WORKING. Demo part fully validated (6/6 ops, green toolpaths). Bottom Box pipeline run via frontend; outputs in capp_service/jobs/. Bottom Box imported with 71+36=107 ops after last fix.

**What works:**
- Add-in loads in Fusion Manufacture workspace — two buttons: "Import ShiaanX Plan" and "ShiaanX: Probe Geometry"
- Import flow: picks `*_params.json` then optionally `*_features.json` (Cancel skips geometry)
- Creates correct CAM setups (1 per ShiaanX setup) with spindle direction in name
- Creates all operations with correct Fusion strategy
- Feeds/speeds (RPM, Vf, ap, ae, peck depth) pre-filled from pipeline params — **unit conversion confirmed correct** (all lengths converted mm→cm before passing to Fusion API)
- **Geometry auto-assigned** from features.json — no manual face clicking needed:
  - `drill` → `holeFaces` (CadObjectParameterValue) ← [cylinder_face]
  - `bore` → `circularFaces` (CadObjectParameterValue) ← [cylinder_face]
  - `contour2d`, `chamfer2d`, `pocket2d`, `slot2d` → manual geometry pick required (CadContours2dParameterValue is not settable via API)
  - `facing` → no geometry param (machines full stock)
- Operation names set on `op.name` — shows cluster ID, op type, diameter, tool ID
- Spindle direction labels (+Z Top, -Z Bottom etc.) in setup names; WCS rotation hints in result dialog
- Duplicate setups auto-deleted on re-import
- 56-tool ShiaanX library (`shiaanx_tools.hsmlib`) imported into Fusion Local > Library
- `counterbore_mill` mapped to `pocket2d` (was missing — caused 30+ error popups on Bottom Box import)

**Known limitations:**
- Tool auto-assignment NOT possible — Fusion API blocks local library access. Must select manually.
- WCS orientation must be set manually (double-click setup → WCS tab → select face). Spindle direction shown in setup name as guide.
- `slot_mill` strategy: `slot2d` fails in Fusion API → falls back to `contour2d`
- `tap_rh` strategy: `tapping` fails → falls back to `drill`
- `face mill` type rejected from tool library ("Cutting Data not available") — workaround: use 20mm end mill for face_mill ops
- Contour/pocket geometry requires manual face selection in Geometry tab

**Critical: unit conversion**
Fusion CAM API uses cm internally for ALL length values. `cam_importer.py` converts with `_cm = lambda mm: mm * 0.1`.
- RPM: no conversion (stays as-is)
- Vf (feed rate mm/min): no conversion
- ap, ae, peck_depth, depth: multiply by 0.1 (mm → cm)

**Geometry param types (from probe):**
| Strategy | Param | Type | Scriptable? |
|---|---|---|---|
| drill | holeFaces | CadObjectParameterValue | ✅ Yes |
| bore | circularFaces | CadObjectParameterValue | ✅ Yes |
| contour2d, chamfer2d | contours | CadContours2dParameterValue | ❌ No |
| pocket2d | pockets | CadContours2dParameterValue | ❌ No |
| facing | — | no geometry needed | — |

**Frontend + backend stack:**
- `capp_service/` — FastAPI service (uvicorn on port 8001)
- `capp-frontend/` — React frontend (npm start, port 3000)
- Start backend: `& "C:\Users\Siddhant Gupta\miniconda3\envs\occ\python.exe" -m uvicorn main:app --reload --port 8001` (run from capp_service/)
- Bottom Box outputs: `capp_service/jobs/c31699c4-ef75-4f09-ad31-1cd02b396c05/`
  - `Bottom_Box_Mod_params.json`, `Bottom_Box_Mod_features.json`, `Bottom_Box_Mod_program_sheet.pdf`
  - 3 setups, 48 clusters, 107 total operations

**Exact workflow for next Bottom Box Fusion session:**
1. Reload add-in: Tools → Add-Ins (Shift+S) → ShiaanX → Stop → Run
2. Import: click "Import ShiaanX Plan" → pick `Bottom_Box_Mod_params.json` → pick `Bottom_Box_Mod_features.json`
3. Set WCS per setup (3 setups): double-click setup → WCS tab → select face matching spindle direction in setup name
4. Assign tools: double-click op → Tool tab → Select → Local > Library → pick by type + diameter from op name
5. Generate toolpaths: right-click setup → Generate All Toolpaths → Simulate → Post Process

**Files:**
```
%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns\ShiaanX\
  ShiaanX.py           ← entry point (2 buttons: Import + Probe)
  ShiaanX.manifest     ← add-in metadata
  cam_importer.py      ← core: params.json + features.json → CAM + auto-geometry
  geometry_probe.py    ← API discovery tool (keep for future probing)

Claude output for program sheet\
  generate_tool_library.py   ← generates shiaanx_tools.hsmlib (56 tools)
  shiaanx_tools.hsmlib       ← tool library (delete all tools and re-import if duplicates appear)
```

**Next steps:**
- [ ] Re-import Bottom Box plan (add-in now has counterbore_mill fix) — should create 107 ops with no error popups
- [ ] Set WCS for all 3 Bottom Box setups, assign tools, generate toolpaths
- [ ] Fix `slot_mill` and `tap_rh` strategy IDs — probe correct Fusion strategy names
- [ ] Fix face mill tool library compatibility (`face mill` type rejected by Fusion)
- [ ] Phase 2: integrate with shiaanx-backend REST API (STEP upload → pipeline → results back to Fusion)

---

### Other pending items
- `slot_mill` / `pocket_mill`: **DONE** — `_process_slot()` and `_process_pocket()` added to `process_selection.py`; dispatch cases wired for `slot`, `slot_angled`, `pocket`, `pocket_angled`. `classify_features.py` was already emitting these types.
- `tap_rh`: **DONE** — `classify_features.py` now emits `tapped_hole` / `tapped_hole_angled` when `is_tapped=true` is set on a bore cluster. Full process chain (spot_drill → twist_drill → tap_rh) is active. Automatic STEP thread detection is future work.
- Post-process fields (tool_number, length_offset): decided these belong in a job setup sheet at runtime, NOT in tool_database.json (AD-001)
- Compare the rule sheet created for facing by our expert with the rule sheet getting created

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
