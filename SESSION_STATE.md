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

## Multi-Session Audit Results (2026-06-23)

Nine autonomous sessions ran overnight and during the day. Here is what each accomplished and what remains to do.

---

### Session 2 — Program Sheet End-to-End Validation (branch: main)

Full pipeline run on `MOTOR MOUNT.step`. PDF renders cleanly, zero NOT_FOUND fields.

**Pipeline vs vendor:**
| Metric | Pipeline | Vendor |
|--------|----------|--------|
| Setups | **12** | 4 |
| Total op steps | **187** | 37 |
| Primary tool (10mm EM) | **NOT selected** | Used 20+ times |
| Drill RPM (2.5mm) | 10000 (capped) | 1500 |
| Ballnose ops | **0** | 5 |
| Step feature ops | **0** | 8 |

**Immediate priority fixes from this session:**
1. Setup consolidation: merge angled/rare-axis setups → target ≤4–5 setups
2. RPM conservatism for small drills (≤4mm): cap Vc at 50–60 m/min
3. New feature types: `step_feature` classifier, ballnose triggered by `internal_corner_radius > 0`
4. Boss/outer-profile: use largest EM that fits minimum pocket width, not smallest ≥ feature diameter

---

### Session 3 — MFCAD++ Accuracy Post-Fix (branch: main)

Re-evaluated parts 21 and 25 after clustering fix. Cluster counts nearly doubled (24→47 for part 21, 9→23 for part 25) — the connected-component seeding is working.

| | Part 21 | Part 25 | Overall |
|---|---------|---------|---------|
| Pre-fix rules | 12.5% (3/24) | 22.2% (2/9) | 15.2% |
| Post-fix rules | 12.8% (6/47) | 8.7% (2/23) | 11.4% |
| **Post-fix ML v3** | **59.6% (28/47)** | **47.8% (11/23)** | **55.7%** |

**Conclusion:** Rule-based accuracy is at ceiling for these test parts (dominated by passages/slots with zero rule coverage). Do NOT patch more rules for passages. ML is the right path. Better clustering gave +40pp ML accuracy with no retraining needed.

**Next step:** GBM retrain (XGBoost/LightGBM, same 18 features). Expected +5–10pp.

---

### Session 4 — Two-Pass Chamfer Parameter Differentiation (branch: main, commit 0b6543fc9)

Two bugs fixed + chamfer parameters properly differentiated:

1. **`cluster_features.py` chamfer seeding regression** — merge commit had replaced dot-product cap-plane check with simpler adjacency check that skipped ALL planes near cylinder seeds. Restored: only skip planes where `dot(normal, cyl_axis) > 0.9`.
2. **`process_selection.py` depth condition** — changed `if depth is not None and depth > 0.5` → `if depth is None or depth > 0.5` so two-pass is the default when depth unknown.
3. **`parameter_calculation.py`** — added `CHAMFER_TOUCH_VC=28.0`, `CHAMFER_FINISH_VC=140.0`, `CHAMFER_TOUCH_FEED_MAX=80.0` constants. Verified on Motor Mount:
   - TOUCH: Vc=28, RPM=1490, Vf=80 (capped)
   - FINISH: Vc=140, RPM=7430, Vf=743
4. **`rule_sheets/04_cutting_parameters.json`** — chamfer_two_pass section added.

All changes committed to main.

---

### Session 6 — Cube Manifold Audit (branch: audit/cube-manifold)

Pipeline run on `manifold.STEP` (28×28×28mm Al 6061). 39 clusters detected (chamfer=14, through_hole=10, planar_face=9, slot=4, large_bore=1). Inspection: **15/16 PASS** (93.75%), 1 FAIL (Ø4mm hole 3.94mm vs 3.95mm minimum).

**Key finding:** Shop used circular interpolation for ALL holes (Ø4–15mm). Pipeline only routes circ interp for ≥13mm. This is rule gap R2.

**8 new rules proposed (in `audit/motor_mount_new_rules.json`):**
- R1: add `face_context` to distinguish pocket floors from open planar faces
- R2: extend `circular_interp` rule down to Ø4mm (not just ≥13mm)
- R3: add `internal_corner_radius` to feature extraction
- (R4–R8 in FINDINGS_cube_manifold.md)

**Branch not yet merged:** `audit/cube-manifold`

---

### Session 7 — LIGHT-FCS Aerospace Part Audit (branch: audit/light-fcs)

Pipeline run on `LIGHT-FCS_A06.01.0001.A00.step` (Al 5083 aerospace bracket). 39 clusters detected.

**Critical bugs found:**
1. **`pocket_mill` tool_diameter_mm = 0mm** on all 24 pocket ops (HIGH) — `tool_selection.py` not receiving pocket width from classifier
2. **Setup count 3 vs actual 9** — setup planning too coarse for complex multi-face parts
3. **Al 5083 not in material alias table** — runs as 6061 Vc/fz (MEDIUM)
4. **Face mill (40mm) selected for 50×30mm part** — overhangs vise (MEDIUM)

**New operations needed:**
- Sub-2mm end mill ops (1.5mm, 2mm EM) for narrow slots/internal corner reliefs
- `circular_interp_mill` operation type — shop used circular interp (not drilling) for all holes including tight tolerance Ø10 g8

**Branch not yet merged:** `audit/light-fcs`

---

### Session 8 — Two-Shop Motor Mount Comparison (branch: audit/motor-mount-two-shops)

Parsed G-code from two shops: TS (Sinumerik 828D, 4 MPF setups) and Krishna Engineering (PowerMILL, 3 TAP settings). Both machined the same Al 6061 motor mount.

**6 high-confidence rules (both shops independently agreed):**
| Rule | Finding |
|---|---|
| SR-MM-001 | Bore 14–32mm: use 10mm EM circular interpolation (not boring bar) |
| SR-MM-002 | Pocket width 8–15mm: use 8mm EM as roughing tool |
| SR-MM-003 | Add `ball_nose_finish` step for any feature with `fillet_radius > 0` |
| SR-MM-004 | Separate setup for second major face (flip) is a physics requirement |
| SR-MM-005 | Bore and long pocket go in last setup (accumulated error minimisation) |
| SR-MM-008 | Roughing tool = largest EM that fits (max dia for MRR) |

**Notable:** TS 4-setup vs Krishna 3-setup difference is shop preference, not physics — both passed inspection except SL-13 (5mm shoulder, both shops failed → known-difficult feature).

**Branch not yet merged:** `audit/motor-mount-two-shops`

---

### Session 5 — Training Data Inventory
**PERMANENTLY SKIPPED.** Only 1 SolidCAM `.prz` file exists in Google Drive — not enough for a viable training set. Training data flywheel will come from real part audits (sessions 6–8) instead. Do not re-run.

### Session 9 — Inspection / FPR Metrics
Terminal was closed before committing. Output is lost — no branch, no files. Task was: design `qc_inspection_results` DB table + wire FPR metrics to dashboard. Straightforward enough to re-run or implement directly when dashboard work resumes.

---

### Session 10 — Fixture Design Integration (branch: `feature/fixture-design`)

Built and wired the Fixture Design Integration module. Full audit docs in `audit/SESSION_UPDATE_fixture_design.md`.

**New files:** `fixture_design/fixture_schema.json`, `fixture_planner.py`, `soft_jaw_generator.py`, `fixture_pdf_page.py`, `audit/FINDINGS_fixture_gcode.json`, `audit/FINDINGS_fixture_gcode.md`

**Pipeline changes:**
- `10. run_pipeline.py`: renumbered 9→10 steps; Step 6 = `fixture_planner.py` (between setup_planning and tool_selection); optional/non-fatal
- `9. program_sheet.py`: added `fixture_spec_data` kwarg; auto-loads `*_fixture_spec.json` alongside params; appends fixture pages before `doc.build()`

**Test results:** Motor Mount + Botlabs Hub both produce correct fixture specs and PDFs with fixture pages. ✓

**Branch `feature/fixture-design` is not yet merged to main.** Soft jaw boolean subtraction path untested on real geometry (no Motor Mount setup requires soft jaws).

---

### Session 10b — Fixture 3D Viewer Tab (branch: `feature/fixture-viewer`)

Built on top of `feature/fixture-design`. Added a Fixture tab to the ShiaanX frontend.

**Backend endpoints added to `capp_service/main.py`:**
- `GET /jobs/{id}/fixture` — serves `*_fixture_spec.json` from job folder (no in-memory store dependency)
- `GET /jobs/{id}/jaw/{setup}/{side}` — serves soft jaw STEP files
- `GET /jobs/{id}/fixture_assembly/{setup}` — merges part + jaw STEPs via OCC subprocess, caches result

**Frontend:**
- `FixtureTab.js` — setup selector pills, fixture spec table, soft jaw warning, setup notes, "Load in 3D Viewer" button with colour legend
- `CappViewer.js` — added `viewerUrl` state; iframe URL controlled by state (defaults to part STEP, overridden by fixture assembly URL); switching away from Fixture tab resets to part-only STEP

**Tested:** Backend endpoints return HTTP 200 with correct Motor Mount data (3 setups, angle_plate/fixture_plate). Assembly STEP generated in ~5s and cached. JS syntax verified.

**Branch `feature/fixture-viewer` — not yet merged to main.**

---

### Session 11 — Facility Demo: 3D Dimension Tagging (Step 2 of 4) (2026-09-29)

Goal: layman-friendly 3D-only demo for visitors/investors. Pilot part: Bottom Plate SE-004-052 (Krishna job, copper).
Flow: (1) CAD on screen — existing viewer; (2) map ballooned drawing dimensions onto 3D faces — **built**; (3) QC report -> green/amber/red faces + hover text + "18 of 19 in tolerance" — not started; (4) real part photo beside the model — not started.

**Built (labeling_app, port 8780):**
- `local_app/qc_sheet.py` — reads QC xlsx (SL No., Description, TOL+, TOL-) into balloon skeletons (type/nominal/tol guessed from description; mangled Ø -> diameter). openpyxl added to `requirements.txt`.
- `local_app/main.py` — `normalize_dimensions()` + routes `GET /dimensions`, `GET/PUT /api/labeling-jobs/{id}/dimensions`, `POST .../dimensions/seed` (xlsx -> rows, saves nothing), `GET .../dimensions/download`. Output file `dimension_tags.json` in the job folder (`{stem}_dimension_tags.json` on download).
- `local_app/static/dimensions.html` — upload STEP, import balloons from QC sheet, click faces in 3D, Set faces A / B (B only for linear/center_distance/depth/thickness/angle), auto-advance, save. A face may belong to several dimensions (unlike labeling's one-label-per-face).

**Tested:** Bottom Plate STEP -> 76 faces, viewer map aligned 76/76, 19 balloons imported, select/assign/save works in browser. Test jobs deleted.

**Tagging done (2026-09-29):** user tagged all 19 balloons on job `a4838b441e4b`. Balloons 12/13 (slot length/width) were tagged as type "other"; user wants to revisit a couple of pocket-related ones later.

**Step 3 built (2026-09-29):** `/inspection` page + `parse_qc_results()` / `evaluate_dimension()` in `qc_sheet.py` + routes `GET /api/dimension-jobs`, `GET/POST /api/labeling-jobs/{id}/qc-results` (POST saves `qc_results.json` in the job folder). Viewer gained opt-in hover reporting (`setHoverReporting` -> `faceHovered`).
- Verdict computed from the numbers (decision taken, user said SL 1/4 minor): fail if any reading outside [nominal - tol-, nominal + tol+]; amber if inside but within 15% of band from a limit; face shared by several dims shows worst. Sheet remark shown on the card when it disagrees.
- Bottom Plate result: **16 of 19 within tolerance** - fails: SL 1 (78.04/78.06 vs max 78.00), SL 4 (108.05/108.06 vs max 108.00), SL 19 (5.13 vs max 5.10); amber: SL 11 (Ø6.2, 6.11 vs min 6.10).
- Browser-tested: summary, colours, hover tooltip, isolate-one-dimension all work.

**Drawing-style arrows (2026-09-29, after user feedback that selecting went dark):** selecting a dimension on `/inspection` now keeps the part light grey, colours only its faces, and draws a 3D dimension (extension lines + double arrow + label) in `step-viewer.html` (`showDimension` / `clearDimension` messages). Geometry fitted from the viewer mesh: planes by area-weighted normal, holes by axis + circle fit. Camera turns to a side view for dimensions pointing at the viewer, and looks into holes for diameters. `?demo=1` on the viewer hides the render-mode toolbar and Model Info. Balloons 12/13 (type "other") only get a pointer, not arrows.
Default view is now an auto-tour (5 s per measured dimension, smooth camera moves); any click pauses it, it resumes after 60 s idle; Play/Pause button in the list header. Demo mode also hides file size / triangle count and the Open File button.

**Still to do:** Step 4 (real part photo beside the model); revisit pocket balloons the user flagged (retagging 12/13 as linear would give them arrows). Repo home for this work (CAPP vs closed-loop) undecided; left uncommitted.

---

### Session 12 — Production System PRD (2026-09-30)

Focus shifted from demo work to consolidating scattered systems into one production platform with two UXs: admin first, client later as a released, read-only subset of admin records.
- **PRD (draft v0.1, private):** https://claude.ai/artifact/5V7VBc3FyrEytG7sF9ciCz — flow steps 0–10, data model, admin modules, architecture, repo consolidation, roadmap P0–P4, open decisions.
- **Factory page:** machine utilization and rules sit on a separate page linked from admin, not inside the order-flow modules.
- **Data starting point (not final — user: spec is dated, adapt where needed):** Ravish's `Data Modelling & Ingestion Architecture Spec.docx` (repo root): manufacturing_orders → part_jobs (one per physical piece); part_templates → programs (versioned) → setups/tools/operations. PRD adds E1–E7: inspection plans/records, NCR, HUMAN_PROGRAMMED program source, machine_runs (telemetry link), partner assignment, documents.
- **Decisions:** CAM = human programmer in PowerMill (orchestrator stays R&D); parts made in-house and at partner shops; DB system of record before AI.
- **Open:** MinIO vs S3; spec migration numbers 18–30 collide with backend 01–31; orchestrator exists only as a zip locally. (`shiaanx-backend` is in the ShiaanX org at github.com/ShiaanX/shiaanx-backend; the local clone's remote still uses the old siddhantg2311 URL.)

---

## Pipeline Fixes Priority Queue (as of 2026-06-24)

Based on all audit sessions, ordered by impact:

| Status | Priority | Fix | Source | File |
|--------|----------|-----|--------|------|
| ✅ DONE | P0 | `pocket_mill` tool_diameter_mm=0 bug — `_process_pocket()` now passes `internal_corner_radius` + `face_area_mm2`; `tool_selection.py` has `pocket_mill` branch that picks largest EM ≤ corner constraint. 21 Motor Mount pockets: 0 NOT_FOUND (was all NOT_FOUND). Commit `03b233ec1`. | Session 7 | `4. process_selection.py`, `7. tool_selection.py` |
| ✅ DONE | P0 | R2: circular_interp for aluminium holes 6–13mm — `_drilling_steps()` now routes to `circular_interp` (0.60× bore EM) before the spot+drill bands. Threshold 6mm (not 4mm) — cube manifold showed 4mm interpolated hole failed due to EM deflection. Commit `03b233ec1`. | Sessions 6+7+8 | `4. process_selection.py` |
| ✅ DONE | P1 | SR-MM-003: ball nose finish (BALLNOSE_FINISH) step added for any pocket/slot/boss with `internal_corner_radius > 0`. Ball nose dia = 2× corner_r. Tool selection picks largest ball nose ≤ fillet dia. Aluminium params added to all 3 ball nose tools in DB. Motor Mount: 18 BALLNOSE_FINISH steps, 0 NOT_FOUND. Commit `2f2e6b8ed`. | Session 8 | `4. process_selection.py`, `7. tool_selection.py`, `7a. tool_database.json` |
| ✅ DONE | P1 | Setup consolidation Fix A: angled axis groups (≤3 clusters, ≤70° from principal) folded into nearest principal setup. Motor Mount: 12 → 6 setups. WCS G54–G59 sequential. Stock chain intact. 0 NOT_FOUND across 209 steps. Commit `b2bdd4935`. | This session | `5. setup_planning.py` |
| 🔲 | P1 | Setup consolidation Fix B (deferred): anti-parallel axis merge (e.g., +Z and -Z into one flip) — requires restructuring WCS/workholding/stock logic. | Session 2 | `5. setup_planning.py` |
| 🔲 | P1 | SR-MM-001: extend existing circ-interp rule down to 14mm minimum (was 13mm) for aluminium bores | Session 8 | already partially covered by R2 above |
| 🔲 | P1 | SR-MM-003: `ball_nose_finish` step for any feature with `fillet_radius > 0` | Session 8 | `4. process_selection.py` |
| 🔲 | P2 | Add 1.5mm and 2mm EM to tool database | Session 7 | `7a. tool_database.json` |
| 🔲 | P2 | Add Al 5083 to material alias table | Session 7 | `8. parameter_calculation.py` |
| 🔲 | P2 | RPM conservatism for small drills (≤4mm): cap Vc at 50–60 m/min | Session 2 | `8. parameter_calculation.py` |
| 🔲 | P2 | GBM retrain (XGBoost/LightGBM, same 18 features, expected +5–10pp accuracy) | Session 3 | `ml_train_classifier_v4.py` |
| 🔲 | P3 | Face mill size sanity check: reject face mill if diameter > part bounding box shorter dimension | Session 7 | `7. tool_selection.py` |
| 🔲 | P3 | `step_feature` classifier + ops (contour wall + floor face_mill) | Session 2 | `3. classify_features.py`, `4. process_selection.py` |
| DEFERRED | — | R1: pocket floor vs open face — blocked until `adjacent_cluster_ids` + `centroid` are populated for plane-seeded clusters in `cluster_features.py`. Currently both `None` on all planar_face clusters — no signal available to distinguish floor from open face. | Sessions 6+7 | `2. cluster_features.py` first, then `4. process_selection.py` |

---

## Branches (as of 2026-06-24)

All prior session branches merged to main. One active feature branch:

**`feature/fixture-design`** — active, not yet merged. See Session 10 above.

| Branch | Merged | Notes |
|--------|--------|-------|
| `audit/feature-recognition-motor-mount` | ✅ | Feature recognition + clustering fixes |
| `feature/rule-sheet-expansion` | ✅ | DR-003, circ-interp rule, two-pass chamfer |
| `feature/chamfer-params` | ✅ | TOUCH/FINISH parameter differentiation |
| `feature/dashboard-data-model` | ✅ | InfluxDB inventory + 4 Sequelize migrations |
| `audit/cube-manifold` | ✅ | Cube manifold audit + 8 proposed rules |
| `audit/light-fcs` | ✅ | LIGHT-FCS audit findings |
| `audit/motor-mount-two-shops` | ✅ | Two-shop comparison + 11 rules |

---

## AI / ML Strategy (discussed 2026-06-24)

### Do not start with RL yet
RL requires many iterations to converge. Each trial in manufacturing is a real machined part — expensive and slow. With current data volume (handful of audited parts), RL will not converge. What we're building (closed loop inspection → rule/parameter update) is already the right architecture. The question is how much to automate each step.

### Recommended roadmap by stage

| Stage | Approach | Trigger / Data needed |
|-------|----------|-----------------------|
| **Now** | GBM retrain (XGBoost/LightGBM, 18 features) | Ready — 8790-part MFCAD++ dataset exists. Expected +5–10pp on feature classification. |
| **Now** | LLM-assisted rule extraction | Use Claude API to read G-code + drawing + inspection report → propose rule additions in `proposed_rules.json` format automatically. Autonomous agent scaffold already exists. |
| **3–6 months** | Contextual bandits for parameter tuning | Needs ~20–50 part+inspection pairs. Treat each job as context (material, feature type, tool dia, machine), action = Vc/fz choice, reward = inspection pass/fail. Thompson Sampling or UCB policy. InfluxDB telemetry + inspection results provide the data schema already. |
| **12+ months** | GNN for feature recognition | Needs 200+ real labeled parts. Operates on B-Rep adjacency graph. Significantly outperforms RF for domain-specific part families (aerospace brackets, manifolds, motor mounts). This is the long-term moat. |
| **Much later** | Full RL | Only when ShiaanX controls machines and can run many iterations cheaply. Not before. |

### Claude vs SLM — where each fits

| Task | Tool | Reason |
|------|------|--------|
| Rule extraction from G-code + drawings | **Claude API** | Needs long-context reasoning, handles ambiguity |
| Feature classification (real-time, pipeline) | **Local RF/GBM → GNN** | No latency, deterministic, auditable |
| Explaining pipeline decisions to users | **Claude API** | Natural language, investor-facing |
| Structured extraction / simple decisions | **Gemini Flash** (already in autonomous agent) | Free tier, fast |
| Offline / shop-floor inference | **Phi-3 or Qwen2.5** | Runs without internet |

Architecture is layered: fast deterministic models for core pipeline decisions, LLM APIs for reasoning/explanation/rule extraction, small local models for offline shop floor use later.

### Immediate next action on AI
GBM retrain in `ml_train_classifier_v4.py` — change RandomForest to XGBoost, same 18 features, same dataset. One script change, run overnight, check accuracy improvement.

---

## Dashboard Data Model Work (2026-06-22)

Branch: `feature/dashboard-data-model`
Committed: `FINDINGS_dashboard_data_model.md`, `dashboard_data_model.json`, `audit/` (5 files)

**Summary:** Inventoried InfluxDB (cnc-data + cnc-data-v2) and PostgreSQL (via migrations) for FPR and FAR cycle time dashboard design.

**Key findings:**
- InfluxDB cnc-data: 356,383 rows, 20 fields, 7 programs, date range 2026-05-06 to 2026-05-13
- InfluxDB cnc-data-v2: 132k+ rows, 80+ programs (program_name as TAG — better for querying), data confirmed current to 2026-06-22
- `production_count` is always 0 — **NOT a bug** — controller limitation, requires manual entry only. Next action: design manual count input UI.
- `tool_name` stores G-code program text, not tool names (data quality issue)
- PostgreSQL: 27 tables, empty locally, live on AWS at 13.233.172.143:3003
- No MinIO — system uses AWS S3 for document storage
- FPR: BLOCKED — no QC table exists anywhere
- FAR: PARTIAL — 2 of 7 stages have timestamps (job receipt, delivery)
- MVP dashboard can show: machine utilization, cycle time per program, alarm rate, pipeline kanban view

**⚠️ InfluxDB session cookie gotcha:** POST /api/v2/signin cookie expires in ~1 hour. Silent failure returns empty results, not a 401. If querying InfluxDB programmatically and results appear empty, the cookie has expired — re-authenticate. The Session D agent incorrectly reported "last data: June 6" due to this exact issue. Developer confirmed data is current to June 22.

**P0 capture gaps:**
1. Create qc_inspection_results table + form (unblocks FPR)
2. production_count: manual entry only (controller limitation) — design manual count input UI
3. Add capp_generated_at to enquiry_parts (FAR stage 2)
4. Create program_job_mappings table (links InfluxDB program_name to PostgreSQL order)

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

- [x] **Post-clustering-fix evaluation on parts 21 & 25** (2026-06-23) — DONE
  - Script: `audit/evaluate_mfcad_accuracy.py` (runs stages 1-3 fresh, extracts STEP GT, computes accuracy for rules + ML)
  - Results: `audit/FINDINGS_mfcad_accuracy.md` | `audit/mfcad_accuracy_results.json`

  | | Part 21 | Part 25 | Overall |
  |---|---------|---------|---------|
  | Pre-fix rules | 12.5% (3/24) | 22.2% (2/9) | 15.2% |
  | Post-fix rules | 12.8% (6/47) | 8.7% (2/23) | 11.4% |
  | **Post-fix ML v3** | **59.6% (28/47)** | **47.8% (11/23)** | **55.7%** |

  - Cluster counts increased (24→47 for part 21, 9→23 for part 25) — connected-component fix is working
  - Rule accuracy is flat/worse because both test parts are dominated by passages (triangular/six-sided) which rules have zero coverage of
  - ML jumped ~40pp vs pre-fix rule baseline — better clusters give cleaner majority votes; no retraining needed for this gain
  - Remaining rule errors: passages→chamfer, Stock→planar_face, slots→pocket
  - Remaining ML errors: slot vs pocket (face-level features insufficient), Stock vs planar_face

**Next improvement options:**
- **GBM retrain** — Replace RF in `ml_train_classifier_v4.py` with XGBoost/LightGBM, same 18 features, expected +5-10pp
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
- **"Failed to generate toolpath - no tool selected" popup** — fires once per operation during import (N ops = N clicks). This is Fusion's internal validation inside `setup.operations.add()`. **CONFIRMED UNFIXABLE via Python API.** This was investigated exhaustively across two sessions (2026-05-04, 2026-05-07). Do not attempt again. Full findings in memory file `feedback_fusion_tool_popup.md`. Accept the clicks and move on.
- **Tool auto-assignment NOT possible** — The Fusion tool library API (`CAMManager.get()` → `libraryManager` → `toolLibraries` → `urlByLocation`) navigates correctly but returns 0 tools. Tools imported via Manage → Tool Library → Local → Import are stored at a different internal URL than what the API resolves. Cannot get Tool objects to assign to `op_input.tool`. Must assign manually via Tool tab → Local > Library.
- WCS orientation must be set manually (double-click setup → WCS tab → select face). Spindle direction shown in setup name as guide.
- `slot_mill` strategy: `slot2d` fails in Fusion API → falls back to `contour2d`
- `tap_rh` strategy: `tapping` fails → falls back to `drill`
- `face mill` type rejected from tool library ("Cutting Data not available") — workaround: use 20mm end mill for face_mill ops
- Contour/pocket geometry requires manual face selection in Geometry tab (CadContours2dParameterValue is not settable via Python API)

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

**Current state (end of 2026-05-09):**
- `cam_importer.py` is clean — all tool lookup dead code removed, popup limitation documented
- Bottom Box params + features in: `capp_service\jobs\c31699c4-ef75-4f09-ad31-1cd02b396c05\`
  - `Bottom_Box_Mod_params.json` — 3 setups, 48 clusters, 107 ops
  - `Bottom_Box_Mod_features.json` — for geometry auto-assign

**DRILL TOOL LIBRARY FIX (2026-05-09) — CRITICAL:**

Root cause of drill tools showing warning triangle and "Cutting Data is not available" in Fusion:
- Fusion requires `type="drill"` tools to have an `<expressions>` block in their XML definition
- Our JSON-generated `.hsmlib` file created tools without this block → Fusion marks them invalid
- Manually-created Fusion drills have `<expressions>` → they work fine
- Mills work without `<expressions>` — this requirement is drill-specific

**Fix applied:** Rewrote `generate_tool_library.py` to output **native XML format (UTF-16)** instead of JSON.
- `type="drill"` tools now include full `<expressions>` block:
  - `tool_bodyLength`, `tool_diameter`, `tool_fluteLength`, `tool_material`, `tool_overallLength`, `tool_shaftDiameter`, `tool_shoulderLength`, `tool_tipAngle`
- `live-tool="1"` set for drill-type tools (matching Fusion's native drill format)
- `live-tool="0"` for mills and taps (unchanged)
- Tap thread-pitch now correctly sourced from `thread_pitch_mm` field in tool database (was hardcoded to 1)
- Mill presets use correct XML parameter keys: `tool_feedCutting`, `tool_feedEntry`, etc.
- Drill presets include "Default preset" (material-agnostic) + material-specific presets

**New `shiaanx_tools.hsmlib` generated:** 56 tools, XML format, UTF-16 encoding.

**To apply:** Delete old ShiaanX tools in Fusion (Manage → Tool Library → Local → Library → select all ShiaanX tools → Delete), then Import Tools → select new `shiaanx_tools.hsmlib`. Drill tools should now appear without warning triangles and be selectable for drilling operations.

**PROPAGATE TOOLS button added (2026-05-09):**

Fusion's multi-select edit only saves tool to the first selected op — this is a Fusion limitation.
Fix: added "ShiaanX: Propagate Tools" button to the add-in (`ShiaanX.py`).

How it works:
- Reads `op.tool` from every operation that already has a tool assigned (these are the "seeds")
- Matches other ops by the last token in the op name (= tool_id, e.g. `DRILL_5.0MM`, `EM_2FL_6MM`)
- Assigns the matching tool object to all ops that still have `op.tool is None`
- Already-assigned ops are NOT touched — safe to run at any point

Workflow: assign ONE op per unique tool_id manually → click Propagate Tools → done.
~90% confidence it works (uses Tool objects already in Fusion memory, not the broken library URL path).

**Current state (end of 2026-05-09):**
- Bottom Box in Fusion: 3 setups created, 107 ops, WCS set for all 3 setups ✅
- Tool assignment: **manually nearly complete** (user was almost done at end of session)
- `shiaanx_tools.hsmlib` reimported as XML — drill tools confirmed working (no warning triangles)
- Bottom Box params + features in: `capp_service\jobs\c31699c4-ef75-4f09-ad31-1cd02b396c05\`
  - `Bottom_Box_Mod_params.json` — 3 setups, 48 clusters, 107 ops
  - `Bottom_Box_Mod_features.json` — for geometry auto-assign

**Tool assignment reference (op name → library tool):**
- Op name ends with `SPOT_090_3MM` → tool 1, Ø3mm spot drill
- Op name ends with `SPOT_090_6MM` → tool 2, Ø6mm spot drill
- Op name ends with `SPOT_090_10MM` → tool 3, Ø10mm spot drill
- Op name ends with `DRILL_X.XMM` → scroll to top of library, find matching Ø twist drill (tools 7–19)
- Op name ends with `EM_2FL_XMM` → aluminium end mill, tools 21–29 (Ø1–20mm)
- Op name ends with `FACEMILL_50MM` → tool 30, Ø50mm face mill
- Op name ends with `FACEMILL_63MM` → tool 31, Ø63mm face mill
- Op name ends with `FACEMILL_40MM` → tool 56, Ø40mm face mill
- Op name ends with `CHAM_*` → chamfer mills, tools 32–34
- Op name ends with `SLOT_*` → slot mills, tools 35–37
- Op name ends with `TAP_MX_RH` → taps, tools 38–42
- `counterbore_mill` ops → use flat end mill matching the counterbore diameter (tools 21–29)

**Exact next session start (Bottom Box in Fusion):**
1. Open Bottom Box_Mod in Fusion — all 3 setups + 107 ops should still be there
2. Finish any remaining tool assignments (manually nearly complete)
3. Optionally: reload add-in → click "ShiaanX: Propagate Tools" to fill any remaining unassigned ops
4. Right-click each setup → Generate All Toolpaths
5. Verify toolpaths look correct on the part
6. Simulate → Actions → Post Process

**Next steps (future):**
- [ ] Generate toolpaths for Bottom Box and verify against PowerMill programmer's plan
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

## Closed-Loop Inspection System (built 2026-05-14)

Three new components built alongside the existing 8-module CAPP pipeline. Do NOT modify the existing pipeline modules.

### Component 1 — Datum Tagger

**Location:** `datum_tagger/`

Flask server + Three.js browser viewer for tagging datum faces on a STEP file.

**Run:**
```powershell
& "C:\Users\Siddhant Gupta\miniconda3\envs\occ\python.exe" datum_tagger/server.py "path/to/part.step"
# Opens http://localhost:5050 automatically
```

- Tessellates STEP with PythonOCC (same face index order as `1. extract_features.py`)
- Click face to select → press A / B / C to tag as Datum A / B / C
- Side panel shows face ID, type, normal, centroid; tagged faces coloured red/teal/yellow
- Save button writes `<stepfile>.datums.json` alongside the STEP file

**Output schema:** `<step>.datums.json` — step_file, step_file_hash, tagged_at, datums[ {label, face_index, face_type, normal, centroid} ]

**Dependency:** Flask (installed in occ env 2026-05-14 via pip)

---

### Component 2 — Datum Transform

**Location:** `datum_transform/datum_transform.py`

Runs after `1. extract_features.py`. Rewrites feature coordinates in the datum reference frame.

Frame construction:
- Origin = Datum A centroid
- Z axis = Datum A normal
- X axis = Datum B normal projected onto plane ⊥ to Z, normalised
- Y axis = Z × X (right-hand rule)

**Run:**
```powershell
& "C:\Users\Siddhant Gupta\miniconda3\envs\occ\python.exe" datum_transform/datum_transform.py "<part>_features.json" "<part>.datums.json"
# → writes <part>_features_datumed.json
```

- Adds `_datum` variants of all geometry dicts (plane_datum, cylinder_datum, etc.) — model-frame coords preserved
- Assigns `inspection_section` label per cluster (DATUM_A / DATUM_B / DATUM_C / GENERAL)
- Falls back to a world-axis X if Datum B is missing

---

### Component 3 — Inspection Template Generator

**Location:** `inspection/template_generator.py`

**Run:**
```powershell
& "C:\Users\Siddhant Gupta\miniconda3\envs\occ\python.exe" inspection/template_generator.py "<part>_features_datumed.json" "tolerances.json" [--metadata "<part>_params.json"] [--output "output.xlsx"]
```

Generates an Excel inspection template with:
- Job header (part name, job ID, material, programmer, date) — from `--metadata` params JSON
- Sectioned rows grouped by datum (DATUM_A / DATUM_B / DATUM_C / GENERAL) with orientation hint per section
- Pre-populated: Feature ID, Feature Type, Nominal, Upper/Lower Tol, Datum Ref, Measurement Type
- Blank: Actual (inspector fills), Notes
- Formulas: Deviation = Actual − Nominal; Pass/Fail = PASS if deviation within tolerance
- Conditional formatting: green PASS, red FAIL, yellow for deviation > 50% of tolerance
- Summary block: Total, Measured, PASS count, FAIL count, Pass Rate % (all formula-driven)
- Falls back to ±0.1 mm for features not in `tolerances.json`

**`tolerances.json` schema:**
```json
{
  "BORE_001": {"nominal_mm": 6.4, "upper_tol_mm": 0.1, "lower_tol_mm": 0.1, "measurement_type": "diameter"}
}
```

---

### End-to-End Workflow

```
1. Run datum_tagger/server.py on STEP file → tag Datum A/B/C → Save → <part>.datums.json
2. Manually fill tolerances.json from drawing
3. Run 1. extract_features.py → <part>_features.json
4. Run datum_transform/datum_transform.py → <part>_features_datumed.json
5. Run pipeline stages 2–9 (unchanged) → <part>_program_sheet.pdf
6. Run inspection/template_generator.py → <part>_inspection_template.xlsx
7. Inspector fills Actual column → deviations + pass/fail computed automatically
```

---

---

## ShiaanX Backend — Deployed API Access

The backend runs on AWS EC2 (Mumbai) behind nginx. The local `shiaanx-backend/` repo is a reference copy — all live data is on the server.

### Deploying code changes to production

1. **Make changes locally** in `shiaanx-backend/`
2. **Commit and push:**
   ```bash
   cd shiaanx-backend
   git add <changed files>
   git commit -m "description"
   git push origin main
   ```
3. **SSH into EC2** via AWS Console:
   - Go to EC2 → Instances → select the instance (`i-0f2af7e81a5c984e2`, named "webServer")
   - Click **Connect** → **EC2 Instance Connect** tab → click **Connect**
   - A browser terminal opens (no .pem file needed)
4. **Pull and restart** in the browser terminal:
   ```bash
   cd /var/www/api/shiaanx-backend
   git pull origin main
   pm2 restart shiaanx-backend
   ```
   - GitHub will ask for username (`siddhantg2311`) and a PAT (Personal Access Token) as password
   - Generate PAT at: GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic) → repo scope
   - **Never share the PAT in chat** — generate a fresh one each time if needed

**EC2 details:**
- Instance ID: `i-0f2af7e81a5c984e2`
- Public IP: `13.233.172.143` (Mumbai, ap-south-1)
- OS user: `ubuntu`
- Backend folder: `/var/www/api/shiaanx-backend`
- Process manager: **PM2** (not Docker — the docker-compose.yml is a local dev reference only)
- PM2 process name: `shiaanx-backend` (id=0)
- Also running: `sx-mqtt-ingestor` (id=1) — do not restart unless intentional

### Admin panel (browser)
```
http://13.233.172.143/admin/#/enquiries/<id>
```

### API base
The frontend JS bundle sets `baseURL: '/api/api/v1'`. Nginx strips one `/api` prefix; the Node app expects `/api/v1/...`.
All API calls must therefore use the double-prefix: `http://13.233.172.143/api/api/v1/...`

### Login (get JWT token)
```powershell
$login = Invoke-RestMethod -Uri "http://13.233.172.143/api/api/v1/auth/login" `
    -Method POST -ContentType "application/json" `
    -Body '{"email":"admin@sx.com","password":"123456789"}'
$token = $login.data.token
$headers = @{ Authorization = "Bearer $token" }
```

### Fetch an enquiry
```powershell
Invoke-RestMethod -Uri "http://13.233.172.143/api/api/v1/admin/enquiries/<enquiry-id>" `
    -Headers $headers | ConvertTo-Json -Depth 10
```

### Useful endpoints (all require `$headers`)
| Endpoint | Description |
|----------|-------------|
| `GET /admin/enquiries` | List all enquiries |
| `GET /admin/enquiries/:id` | Enquiry detail + parts + documents |
| `PUT /admin/enquiries/:id/master-quote` | Save master quote |
| `GET /admin/enquiries/:enquiryId/parts/:partId/auto-quote` | Get auto-quote state for a part |
| `POST /admin/enquiries/:enquiryId/parts/:partId/auto-quote/generate` | Trigger pipeline auto-quote |
| `PUT /admin/enquiries/:enquiryId/parts/:partId/auto-quote` | Save auto-quote state |

### Motor Mount enquiry (demo part)
- Enquiry ID: `7d5e47bc-df70-483a-b064-2be0237434d1`
- Enquiry number: `SX/26-27/00028`
- Part ID: `e3795ad8-175e-4510-a595-ca46a9b00751`
- Customer: Arun Jeya Prakash (director@aviociantech.com)
- Part: Motor Mount, Qty 40, Al6061-T6, CNC Machining, Type 2 anodizing
- Auto-quote status: DRAFT (currently pipeline_offline fallback values)
- STEP file on server: `uploads/enquiries/7d5e47bc-.../MOTOR MOUNT-....step`

### Local Docker (reference only — empty DB)
The local `shiaanx-backend/` Docker setup (`docker compose up -d` from that folder) spins up a fresh empty Postgres. It is NOT the live database. Use the AWS API above for any real data.

---

## Investor Demo Prep (2026-06-08)

### Demo plan document
Two documents exist — use the **root-level** `ShiaanX Demo Plan.pdf` (v2), not the one in `docs/`. The PDF has 11 steps structured as a 3–4 min investor video:
- Steps 1–4: "BEFORE — The Broken Process" (3 vendors, side-by-side programs, defect)
- Steps 5–11: "THE AI — What We Did" (closed loop analysis, root cause, rule added, correct parts, AI feed, instant quote, system recommendation)

### Demo part: Motor Mount
Location: `Claude output for program sheet/Manufactured parts/Motor Mount/`

| Asset | File | Status |
|-------|------|--------|
| STEP file | `MOTOR MOUNT.step` | ✅ Ready |
| Engineering drawing | `motor mount.pdf` | ✅ Ready |
| CAM programs | `CAM Program/ncprograms/` (3 setups, 20 .tap files) | ✅ Ready |
| Inspection report | `Inspection Report/Inspection Report_motor mount.xlsx` | ✅ Ready |
| Controller log | — | ❌ Not yet obtained from vendor |

**Key inspection finding (use for demo narrative):**
- SL-04 & SL-05: Ø3.2mm holes measured 3.02/3.03mm → **FAIL** (deviation −0.18mm, tolerance ±0.10mm)
- SL-13: 5mm depth measured 4.80mm → **FAIL** (deviation −0.20mm)
- Root cause: 2mm end mill doing circular interp at F1000 mm/min — tool deflects under cutting pressure
- Fix: Reduce Vf from 1000 → 400 mm/min for Ø≤4mm holes with Ø2mm tool

**This matches the demo script almost exactly** ("3.2mm hole came out 3.0mm" — real data).

### What's built / not built for steps 5–11

| Step | Description | Status |
|------|-------------|--------|
| 5 | Closed loop analysis screen | ✅ Built — Closed Loop tab |
| 6 | Root cause identified | ✅ Built — part of Closed Loop tab |
| 7 | Rule auto-added to rule sheet | ✅ Rule FR-001 physically written to `02_process_selection.json`; live on RULES.html; shown in Rule Sheets tab |
| 8 | Correct parts shoot | ❌ Physical shoot needed — your action |
| 9 | AI Engine Feed card | ✅ Built — AI Feed tab |
| 10 | Instant quote | ✅ Flask server built at `insta_quote/server.py` (not yet smoke-tested end-to-end) |
| 11 | System recommendation (CAPP output) | ✅ Motor Mount pipeline runs clean — zero NOT_FOUND, all ops fully populated |

### Frontend tabs (CappViewer.js) — full tab list
1. Overview
2. Strategy
3. Program Sheet
4. Datum Tagger
5. Feature Map
6. Inspection
7. **Closed Loop** — Motor Mount defect data, root cause, rule auto-added
8. **AI Feed** — animated vendor→model data flow, learning events (TS Engg, Krishnamurthy CNC, Aviocian)
9. **Rule Sheets** — Sheet 02 pre-expanded showing FR-001 with blue "auto-added" badge

### Closed Loop Tab
**File:** `capp-frontend/src/components/viewer/tabs/ClosedLoopTab.js`
4 sections: Data Collected · Deviation Analysis · Root Cause · Rule Auto-Added.
Data hardcoded (Motor Mount). Always visible regardless of job loaded.
Card formatting fixed: `flex: '1 1 120px'` so 4 cards wrap cleanly at narrow widths.

### AI Feed Tab (built 2026-06-08)
**File:** `capp-frontend/src/components/viewer/tabs/AIFeedTab.js`
Vendors: Aviocian Technologies (Bengaluru), Krishnamurthy CNC (Pune), TS Engg (Chennai).
Animated flow lines → ShiaanX AI model box. Learning stats (47 deflection events, 312 feed overrides, 9 rule updates). 3 expandable learning events — Motor Mount fix at top.

### Rule Sheets Tab (built 2026-06-08)
**File:** `capp-frontend/src/components/viewer/tabs/RuleSheetsTab.js`
Shows sheets 02, 04, 05. Sheet 02 pre-expanded on "Feed Rate Overrides" section with FR-001 (blue NEW badge). Mirrors live data in `02_process_selection.json`.

### RULES.html (GitHub Pages)
URL: https://shiaanx.github.io/shiaanx-CAPP/docs/RULES.html#s02
Feed Rate Overrides section added to `_html_process()` in `generate_rule_docs.py`.
FR-001 shows: trigger, action (1000→400 mm/min), auto-added badge, source.
Last generated and pushed: 2026-06-08.

### Instant quote Flask server
**File:** `insta_quote/server.py`
`GET /health` → `{"status": "ok"}`. `POST /process` (multipart STEP) → runs full pipeline, returns quote state schema matching `auto-quote.service.js`.
Run: `& "C:\Users\Siddhant Gupta\miniconda3\envs\occ\python.exe" insta_quote/server.py`
Default port: 5001. Not yet smoke-tested with live Motor Mount STEP.

### Feature Classifier Fixes (2026-06-13)

**Problem:** Many features on the motor mount were misclassified, causing wrong operations to be generated and cycle times to be wildly off.

**Root causes identified (from geometry signal analysis):**
1. `bore` seeds with DDR < 0.12 (very shallow arc) were being called `through_hole` — they are edge fillets
2. Large bore clusters (r=25mm) with negligible depth (0.3mm) were being called `large_bore` — they are planar face edges
3. `bore` seeds with face_count=1, no perp_walls, DDR > 1.0 were being called `blind_hole` — they are pocket corner fillet walls (cylinder runs full pocket depth)
4. `boss` clusters with depth < 0.05mm were generating machining ops — they are laser etching marks
5. `plane` seed clusters with perp_wall_count=2 were being called `pocket` — they are steps/shoulders (need ≥3 walls for pocket)

**Fixes in `3. classify_features.py`:**
- Added `BORE_FILLET_DDR_MAX = 0.12`: bore + DDR < 0.12 + fc=1 + no perp_walls → `fillet`
- Large bore + depth < 1.0mm → `planar_face` instead of `large_bore`
- Added `BORE_WALL_FILLET_DDR_MIN = 1.0`: bore + fc=1 + no perp_walls + DDR > 1.0 → `fillet` (low confidence)
- Boss + depth < 0.05mm → `background` (laser engraving)
- Pocket classifier now requires `perp_count >= 3` (was `>= 2`)

**Fixes in `8. parameter_calculation.py`:**
- Drill depth sanity check: if `ap_mm < tool_diameter`, use `tool_dia × 5` for through-holes (extracted depth was face height not hole depth)
- Added MRR-based bulk roughing estimate: `bbox_volume - part_volume` as material to remove, distributed 45%/55% across first two setups, effective MRR = 4,410 mm³/min (calibrated from vendor motor mount data: 23:44 roughing for ~108k mm³)
- Injected as synthetic `stock_roughing` clusters so frontend shows them in StrategyTab
- Added `profile_3d_contour` and `chamfer_mill` timing cases (were hitting 10s fallback)

**Before → After cycle times:**
| Setup | Before | After | Vendor |
|-------|--------|-------|--------|
| Setup 1 | 4:09 | 38:39 | 32:04 |
| Setup 2 | 2:48 | 27:03 | 25:10 |
| Setup 3 | 1:44 | 5:23 | 3:20 |
| Total | ~9 min | ~71 min | ~66 min |

**Reclassified clusters (motor mount):**
- Cl 1, 4-6, 9-11: through_hole → fillet (edge fillets, DDR~0.09)
- Cl 7-8: large_bore → planar_face (r=25mm, depth=0.3mm)
- Cl 13-17: blind_hole → fillet (pocket corner walls, no perp_walls, DDR=1.2-2.0)
- Cl 36-37: boss → background (laser etching, depth=0.009-0.019mm)
- Cl 66: pocket → planar_face (only 2 perp walls = step, not enclosed pocket)

**Known remaining gaps:**
- Cluster 12 (3-face through_hole at pocket intersection): user uncertain, left as-is
- Clusters 18-21 (r=2.3mm, depth=0.019mm): user can't locate on part; reclassified as fillet by DDR<0.12 rule
- Cluster 22 (combining multiple bore features): clustering issue, not fixable at classify stage
- Cluster 25 (r=5.5mm, DDR=0.136): on boundary, stays as through_hole per user preference

**To re-run pipeline with fixes from setups.json (avoids slow OCC STEP parse):**
```python
import importlib.util, json
# load_mod() → spec_from_file_location pattern
classified = mod3.classify_clusters(setups_data)  # re-classify on existing cluster data
processes  = mod4.select_processes(classified)
setups     = mod5.plan_setups(processes)
tools      = mod7.select_tools(setups, db_path=db_path, material='aluminium')
params     = mod8.calculate_parameters(tools, db_path=db_path)
json.dump(params, open('MOTOR_MOUNT_params.json','w', encoding='utf-8'), indent=2, ensure_ascii=False)
```

### Motor Mount pipeline — improved output (2026-06-08)
Run command: `python "10. run_pipeline.py" "Manufactured parts/Motor Mount/MOTOR MOUNT.step" --material aluminium --vc-scale 0.65`

**Before → After:**
| Metric | Before | After |
|--------|--------|-------|
| NOT_FOUND tools | Many | 0 |
| Principal setups | 6 | 3 (matches real 3-setup program) |
| Ball-nose / 3D contour ops | 0 | 28 (all fillets → `profile_3d_contour`) |
| RPM range | Always 10000 | 2330–8000 |
| Pilot/core drills | NOT_FOUND | Resolved (8/10/13/16mm added) |
| "Manual" language | Everywhere | Zero — program reads as fully automatic |

**Pipeline changes made:**
- `7a. tool_database.json` — added 8mm/10mm pilot drills, 13mm/16mm core drills, 3mm/4mm/6mm Al ball-nose end mills
- `5. setup_planning.py` — anti-parallel principal-axis merge (±Z → 1 setup, ±Y → 1, ±X → 1)
- `10. run_pipeline.py` — default `--max-rpm` lowered to 8000; new `--vc-scale` arg (use 0.65 for this vendor)
- `8. parameter_calculation.py` — `--vc-scale` threaded through; `profile_3d_contour` ae/coolant handled
- `4. process_selection.py` — fillets emit `profile_3d_contour` op with tool/stepover; unknown features also emit `profile_3d_contour` instead of `manual_review`
- `7. tool_selection.py` — `profile_3d_contour` picks Al ball-nose; `pocket_mill` aliases to end mills; pocket sizing from face_area
- `9. program_sheet.py` — `profile_3d_contour` renders as `X BALLNOSE` toolpath name

**Demo job folder:** `capp_service/jobs/motor-mount-demo/` — contains updated params, setups, program sheet PDF.

### CAPP service fixes (2026-06-08)
**Problem:** 45 jobs × ~560KB JSON = ~25MB loaded into memory on every restart → blocked event loop → uploads hung on "Starting analysis…"

**Fix in `main.py`:** `_recover_jobs()` now only reads filenames (no JSON loaded). Outputs lazy-loaded on first API access via `_load_job_output()`. `get_job()` reports all stages complete for recovered jobs.

**Fix in `runner.py`:**
- `subprocess.run` now has 600s timeout (was infinite)
- Heartbeat messages during step 1 (the slow OCC parse): "Parsing STEP geometry…" → "Extracting faces…" → "Building adjacency graph…" every 20–45s so the UI doesn't look frozen

**Start command:**
```powershell
cd C:\Users\Siddhant Gupta\Documents\ShiaanX\capp_service
& "C:\Users\Siddhant Gupta\miniconda3\envs\occ\python.exe" -m uvicorn main:app --reload --port 8001
```

### Demo recording plan

**ACT 1 — "The Problem" (60 sec, narrate over documents):**
- Show `motor mount.pdf` (engineering drawing)
- Show `Inspection Report_motor mount.xlsx` — SL-04/05 FAIL, SL-13 FAIL
- Narrate: "3 vendors, 3 programmers, same decisions by hand, no system, no memory"

**ACT 2 — "What ShiaanX Does" (2–3 min, live frontend):**
1. Upload page → drop `MOTOR MOUNT.step` → Analyse
2. Overview tab → feature count, setup count
3. Strategy tab → full op sequence, all tools resolved, all parameters populated
4. Program Sheet tab → download PDF
5. Closed Loop tab → defect analysis, root cause, rule auto-added
6. RULES.html in browser → `#s02` → FR-001 with blue badge
7. AI Feed tab → vendor flow animation, learning events

**What's still missing:**
- Step 8: physical shoot of re-machined correct parts (your action)
- Instant quote: not in critical path — skip or show backend default state
- Act 1 visuals: screen-record opening the documents

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

---

## InfluxDB — CNC Controller Telemetry

Live on AWS Timestream for InfluxDB (ap-south-1). Contains real telemetry from machine `jyotiVMC` at factory `ts`.

```
URL:      https://8j1moabvym-aoe5tdinruw5gy.timestream-influxdb.ap-south-1.on.aws:8086
Username: admin
Password: admin123
Org:      cnc-org
Bucket:   cnc-data  (primary — 356,383 rows as of 2026-06-22)
          cnc-data-v2  (secondary)
```

**Auth (token-based, not basic auth):**
```python
import requests
BASE = "https://8j1moabvym-aoe5tdinruw5gy.timestream-influxdb.ap-south-1.on.aws:8086"

def get_session():
    r = requests.post(f"{BASE}/api/v2/signin", auth=("admin", "admin123"), verify=False)
    r.raise_for_status()
    return r.cookies.get("influxdb-oss-session")
# Session expires ~1 hour — call get_session() again on 401
```

**Measurement:** `cnc_telemetry`
**Tags:** `factory_id` (= "ts"), `machine_id` (= "jyotiVMC")
**Fields (all confirmed live):** alarm_active, axis_x, axis_y, axis_z, block_number,
cutting_time, cycle_time, feed_override, feed_rate, machine_mode, machine_state,
production_count, production_time, program_name, program_runtime, spindle_load,
spindle_override, spindle_speed, tool_name, tool_number

**PostgreSQL (business data):**
```
Start: cd shiaanx-backend && docker compose up -d
Connection: postgresql://postgres:7009@localhost:5432/sx_dev
Key tables: enquiries, enquiry_parts, orders, order_status_history,
            enquiry_status_history, ProgramToolMappings
```

---

## Overnight Task Setup (2026-06-22) — COMPLETED

9 autonomous Claude Code sessions ran on 2026-06-22/23. Tasks that targeted Motor Mount, LIGHT-FCS, cube manifold, and two-shop comparison all completed. See "Multi-Session Audit Results" section above for findings.

**Branches created and status:**
- `audit/feature-recognition-motor-mount` — MERGED to main (feature recognition + clustering fixes)
- `feature/rule-sheet-expansion` — MERGED to main (DR-003, PS-AL6061-CIRC-INTERP-001, PS-AL6061-CHAMFER-002)
- `feature/chamfer-params` — MERGED to main (two-pass chamfer parameters)
- `feature/dashboard-data-model` — **PENDING MERGE** (audit files + 4 Sequelize migrations)
- `audit/cube-manifold` — **PENDING MERGE** (manifold audit + 8 new rules)
- `audit/light-fcs` — **PENDING MERGE** (LIGHT-FCS audit findings)
- `audit/motor-mount-two-shops` — **PENDING MERGE** (two-shop comparison + 11 rules)
- `feature/training-data-inventory` — NOT FOUND (Session 5 may not have run)

**Session cadence note:** Tasks designed as "overnight" complete in 20–30 minutes with pre-loaded context (credentials, paths, branch names). Batch more in parallel on future nights.

**To repeat this setup on a future night:**
1. `docker compose up -d` from `shiaanx-backend/`
2. Run `Overnight setups/schedule_resumes.ps1 -resetTime "HH:MM"` as Administrator
3. Open Claude windows: `cd ShiaanX && claude --dangerously-skip-permissions`
4. Paste task file content prefixed with: "Please read CLAUDE.md first for project context, then follow the task below exactly. Start with Step 1 and work through to the end. Write SESSION_UPDATE_<name>.md to audit/ when done."
5. Disable sleep (Settings → Power → Screen + Sleep → Never), keep on charge

---

## Closed-Loop Data Capture — Motor Mount Pilot, Phase 1 (2026-08-12)

Started from `docs/Tech roadmap/ShiaanX_Immediate Tech plan.xlsx` ("Closed Loop Data Capture" tab). Goal: prove out the tech side of the closed-loop plan on one real job (Motor Mount) before touching `shiaanx-backend`. Full plan (context, rationale, Phase 2 outline) is at `C:\Users\Siddhant Gupta\.claude\plans\eager-questing-spindle.md`.

**Key finding:** the sheet's status column is stale — `datum_tagger/`, `datum_transform/`, `inspection/template_generator.py`, and a full React frontend (`capp-frontend`, tabs: DatumTagger/Inspection/FeatureMap/ProgramSheet) already existed but were never run end-to-end on a real job, and one route was silently broken (see below).

**New files (repo root), all tested against Motor Mount:**
- `job_manifest.py` — persists `job.json` per job folder (status, status_history, artifact index). Was previously **only in-memory in capp_service — lost on every restart**. Backfilled for both `Claude output for program sheet/Manufactured parts/Motor Mount/` and the live `capp_service/jobs/017e0b8c-f752-4b9e-bd92-d79de6c2a6a8/`.
- `cam_program_parser.py` — parses the real `.tap` G-code files (`CAM Program/ncprograms/ncprograms/{1st,2nd,3rd} setting/*.tap`, PowerMill output, plain ISO G-code with rich comment headers) into `actual_process.json`. Ground truth: 20 toolpaths, 3 setups.
- `accuracy_comparator.py` — diffs `actual_process.json` against CAPP's predicted `_setups/_tools/_params.json` → `baseline_accuracy_report.json` + `override_log.json`. First real Milestone-1 baseline numbers for Motor Mount: **setup count 3/3 match, 100% setup-order accuracy, 13% tool-selection accuracy** (predicted drilling ops don't appear in the actual `.tap` set at all — worth sanity-checking with the shop whether drilling was skipped or just isn't archived in that folder, rather than assuming CAPP is wrong).
- `influx_job_linkage.py` — pulls Motor Mount's real telemetry from `cnc-data-v2` (confirmed run on `jyotiVMC`) by fuzzy-matching toolpath names against logged `program_name` values. **Written but not yet run** — the sandbox's permission classifier blocked the outbound call (embedded InfluxDB credentials tripped it). Run manually: `python influx_job_linkage.py "Claude output for program sheet/Manufactured parts/Motor Mount" --machine-id jyotiVMC --range-days 300`. Closes `dashboard_data_model.json` gap G04.
- `fixture_record_template.py` — generates `MOTOR MOUNT_fixture_record.xlsx`, pre-filled with CAPP's predicted workholding + actual WCS from the G-code, for the operator to fill in vice/clamp/step-block details.

**capp_service/main.py changes:**
- Persists job state via `job_manifest.py` on every status poll; rehydrates `jobs` dict from disk on startup (verified: full outputs survive a restart, previously lost).
- **Fixed a real bug**: `capp-frontend`'s `InspectionTab.js` has called `GET /jobs/{id}/inspection` since it was built, but the route never existed — every "Download Template" click 404'd. Now wired to `datum_transform.py` + `inspection/template_generator.py`, verified via curl (correctly 400s until datums are saved).

**Still needs a human:**
- Run `influx_job_linkage.py` manually (blocked from sandbox as above).
- Open **http://localhost:3000/#/parts/017e0b8c-f752-4b9e-bd92-d79de6c2a6a8** (both `capp_service` on :8001 and `capp-frontend` on :3000 were left running in the background) → Datum Tagger tab to click Datum A/B/C (judgment call, not automatable) → Inspection tab to enter tolerances from `motor mount.pdf` and download the now-working inspection template.

**Explicitly deferred (Phase 2, not started):** any `shiaanx-backend` Postgres migrations (user confirmed OK to touch that repo when Phase 2 starts — see plan file for the migration list: `jobs`, `actual_process_steps`, `override_log`, `fixture_records`, wiring up the already-scaffolded `qc_inspection_results` model).

Hardware procurement (camera, digital torque wrench, Renishaw OMP40/RLP40 probe kit) was researched separately as its own track — vendor shortlist with India sourcing/pricing/GST notes, not yet turned into POs.

---

## Krishna Telemetry Dashboard (2026-09-07)

**Goal:** Show a Krishna machine on the existing telemetry dashboard (built for TS / `jyotiVMC`, reads `shiaanx-backend`'s `/api/v1/public/telemetry/*`, rendered by `shiaanx-frontend-admin` at `/admin/#/public/analytics` + `/admin/#/telemetry`). Krishna = factory `krishna`, machine `STM` (Mitsubishi via Smart Connect), writing into the **same InfluxDB** bucket `cnc-data-v2`, measurement `cnc_telemetry`, tags `factory_id`/`machine_id`.

**Full findings + data check:** `audit/FINDINGS_krishna_telemetry.md`. Highlights:
- Krishna `STM`: ~32.3k rows, **2–5 Sep 2026**, actively logging. **Now sending RPM + feed** on recent runs (licence upgraded ~3 Sep); earlier 2 Sep rows are the reduced trial-licence payload.
- **4 fields behave differently from TS** and are handled in the backend:
  1. `machine_state` uses Mitsubishi codes — **`3` = running for STM** (not `1`). Confirmed from data (state-3 rows carry spindle ~5000 + feed). User approved the `3`→running mapping; still worth confirming the full code table with the Krishna/Mitsubishi team.
  2. `tool_number` stuck at `0` → Per-Tool Metrics meaningless for Krishna until fixed at connector/ingestor.
  3. No `feed_override` (sends `rapid_override`=25 instead) → "Feed Override Events" reads 0 for Krishna.
  4. `production_count` is a cumulative lifetime counter → backend now uses `max − min` over the window (was per-row sum; correct for TS too).
  - Bonus: `cutting_time` IS populated for Krishna (always 0 for TS).
- Inventory script (kept, blocked in-sandbox, user ran it): `...\scratchpad\krishna_inventory.py`.

**DEPLOYED TO PRODUCTION 2026-09-07** — both merged to `main`, pushed, and live on the EC2 box (`13.233.172.143`). Backend `shiaanx-backend` main = merge `55baf4c` (`pm2 restart shiaanx-backend`, runs on **port 3000**, `/var/www/api/shiaanx-backend`); prod-verified: TS summary + Krishna summary + machine-matrix `-30d` all return 200 (the `RangeError: Maximum call stack size exceeded` that was live on `getSummary`/`getMachineMatrix` for large ranges is fixed). Frontend `shiaanx-frontend-admin` main = `4367c3b`, built into `/var/www/admin/build/` which nginx serves via `alias` at `/admin/` (served JS hash `main.ae13e692.js` confirmed live). Frontend prod `.env`: `REACT_APP_API_URL=/api/api/v1` (correct — nginx `location /api/` proxy rewrite makes the doubled prefix resolve). Feature branches to be deleted post-merge.

*`shiaanx-backend`* — commit `0125198` (4 files):
- `src/utils/influxClient.js` — `buildTagFilter(query)` (optional `factoryId`/`machineId`, camel or snake → Flux tag filter; empty ⇒ original all-machines behaviour), `sanitizeFluxValue()`, `canonicalMachineState(machineId, rawState)` (`STM`: 3→1 else→0; other machines pass-through).
- `analytics.controller.js` — `buildTagFilter` in all 5 endpoints + `fetchGCodeData`; `canonicalMachineState` at every `machine_state` compare; `production_count` sum → max−min.
- `public/telemetry.controller.js` + `admin/telemetry.controller.js` — `buildTagFilter` in `getRawTelemetry` / `exportTelemetry` / `getUniquePrograms`.
- **Also fixed a pre-existing bug:** `getSummary` + `getMachineMatrix` used `Math.max(...bigArray)` / `Math.min(...)` on `productionTimes` — stack-overflowed (`RangeError: Maximum call stack size exceeded`) on any large range (TS `-7d` ≈ 177k rows). Replaced with inline min/max. The equivalent spreads in `getProgramMetrics`/`getToolMetrics` are per-program-run (small) and left as-is.
- Pre-existing uncommitted `package-lock.json` + `src/middlewares/upload.middleware.js` were left OUT of the commit — not this work.
- **Runtime-verified locally** against live InfluxDB (2026-09-07): TS summary unchanged (`production_count` 0, `feedOverrideEvents` present, 3-state dist); Krishna summary correct (`totalProductionCount` 102, `machineUtilisationPct` 91.19 via state-3, `feedOverrideEvents` 0); aggregate machine-matrix returns both machines with per-row state mapping.

*`shiaanx-frontend-admin`* — cloned into workspace (not a subrepo of shiaanx-CAPP), commit `4367c3b` (3 files). Repo: `github.com/ShiaanX/shiaanx-frontend-admin`, served at `13.233.172.143/admin` (hash routes `#/public/analytics`, `#/telemetry`). React 18 + recharts, no UI framework.
- `src/services/telemetryService.js` — exports `TELEMETRY_MACHINES` (`TS — jyotiVMC` default / `Krishna — STM`), `DEFAULT_TELEMETRY_MACHINE_ID`, `telemetryMachineParams(id)`; `getPrograms` forwards params.
- `src/pages/PublicAnalytics.js` + `src/pages/Telemetry.js` — "Machine" dropdown in the filter panel; `{factoryId, machineId}` spread into every telemetry call; re-fetch active tab + clear program/tool caches on machine switch. Reset keeps selected machine.
- Compiles + renders in browser (`npm start`, `REACT_APP_API_URL=http://localhost:8080/api/v1`). Lint warnings are all pre-existing.
- "Show everything, zeros where empty" — no conditional hiding of Per-Tool tab / Feed-Override cards for Krishna.

**Local run notes (for re-testing):**
- Backend `.env`: `INFLUX_URL=https://8j1moabvym-...timestream-influxdb.ap-south-1.on.aws:8086`, `INFLUX_ORG=cnc-org`, `INFLUX_BUCKET=cnc-data-v2`, `INFLUX_TOKEN` from the server's `.env` at `/var/www/api/shiaanx-backend/.env` (EC2 `13.233.172.143`, `ubuntu`), plus `NODE_TLS_REJECT_UNAUTHORIZED=0` (endpoint has an untrusted cert). Server boots fine without Postgres; only Per-Tool Metrics + tool-name mappings need the DB. `npm run dev`, port 8080.
- Server layout: `pm2 list` shows `shiaanx-backend` (id 0, `/var/www/api/shiaanx-backend`) + `sx-mqtt-ingestor` (id 1). Deploy = `git pull` on the box + `pm2 restart shiaanx-backend`; frontend = `npm run build` + copy `build/` to the `/admin` web root.

**Follow-up:**
- Confirm Mitsubishi `machine_state` code table with Krishna team (assumed `3`=run, `2`=hold, `0`=reset).
- Fix `tool_number=0` at connector/ingestor before Per-Tool Metrics is usable for STM.
- `alarm_active` for Krishna = `Alarm1` non-blank (MQTT doc §10.5, semantics unconfirmed) — Krishna's alarm KPI looked inflated (`totalAlarmsActive` 1027 / `alarmEventCount` 342 over the window); treat as unreliable until confirmed.
- Deploy both branches to the EC2 box; merge to `main` after eyeballing in prod.
- Data capture depends on the Windows PC running Smart Connect at Krishna being powered on — machine alone doesn't self-report, and PC-off periods show as unrecoverable gaps (seen: ~22h + ~28h gaps in the 2–5 Sep data).

---

## Krishna Telemetry — Metrics + Closed Loop (2026-09-07, design phase)

Next work stream after the dashboard: build the per-run metrics + closed-loop feedback for Krishna (STM), then extend to TS.

**Reference docs (both new, `audit/`):**
- `FINDINGS_controller_data_closed_loop.md` — general: what the controllers send, the 3 feedback streams (A=CAM/what-programmer-did [have it, `cam_program_parser`+`accuracy_comparator`], B=telemetry [partial], C=inspection [missing, gap G01 = the reward signal]), field-by-field usability for both machines, gap analysis, build sequence.
- `SPEC_krishna_telemetry_metrics.md` — Krishna-specific spec: Level-1 (machine: utilization, uptime coverage, cutting ratio, idle gaps, alarm/load profile) + Level-2 (per `program_name` run: run time, cycle time, cutting time, cutting ratio, setup/dead time = both `cycle_time`+`cutting_time` frozen, spindle/feed override events/%/profile, spindle load, alarms). Formulas + fields + Krishna feasibility per metric. Proposed `machine_window` / `job_run` record shapes. The CAD/CAM/QC layered view (telemetry alone → +CAM → +CAD/CAPP → +QC = validated rule updates / bandit tuner).

**Decisions:**
- **`rapid_override` is the `feed_override` stand-in for now** (Krishna doesn't send `feed_override` — trial-license limit). One-line swap (`ovr_source` field in the record); replace when real `feed_override` is confirmed/registered. Caveat: it's the rapid-traverse knob, sat constant at 25 in samples — early feed-override numbers are provisional, label "(rapid override proxy)".
- `cutting_time` IS populated on STM (0 on TS) → cutting-ratio and setup/dead-time metrics work for Krishna now.
- Tool identity from the **program name**, not `tool_number` (=0). `.TAP` names encode `[<setup>_]<dia><TYPE>[_<pass>]` e.g. `1_16BULL_FIN` = setup 1, Ø16 bull-nose, finish. Parser spec in SPEC §3.

**PILOT PART:** all STM telemetry on **4 Sep 2026 ~09:00–19:00 IST (≈03:30–13:30 UTC)** is ONE part — the Krishna equivalent of Motor Mount. User is sharing its CAD + CAM + QC. This is the job to validate the metrics + the CAPP↔CAM↔actual comparison + (with QC) the first closed-loop rows.

**Design check — RUN 2026-09-07, results folded into the SPEC.** (Scripts: `...\scratchpad\krishna_metrics_check.py` + `krishna_metrics_check2.py`; sandbox blocks the InfluxDB call so the user runs them.) Five findings that changed the design — full detail in SPEC §0:
1. **All three override signals are dead constants.** `feed_override` not sent; `spindle_override` = **100** on every one of 15366 samples; `rapid_override` = **25** on every one of 32309. Smart Connect isn't reading the override pots at all. The rapid→feed proxy renders a flat zero, not weak signal. Build the plumbing, expect nothing until the register is added.
2. **`cycle_time` is MM·SS-packed** (`…758, 759, 800…`, so 741 = 7 m 41 s); **`cutting_time` is plain seconds** (`459 → 460`). Decode: `cycle_sec = (v//100)*60 + v%100`.
3. **Run boundaries can't use `cycle_time` resets** — the counter climbed straight across a 14 h overnight gap (Sep 3 13:59 cyc=833 → Sep 4 04:10 cyc=834). Segment on: real-time gap > ~5 min, OR decoded cycle_time decreasing, OR program_name change, OR `production_count` step.
4. **`production_count` counts PROGRAM completions (M30), not parts** — +9 across 8 programs; per-value sample counts match per-program sample counts. Great run-boundary signal; **kills** the "bound a physical part's telemetry by production_count" idea for QC linkage.
5. **`spindle_load` is unusable as a trace** — global mean **0.12**, max 121, ~all zeros. No load profiling / tool-wear inference for Krishna.
Also: **`program_runtime` is not sent by Krishna** (use wall-clock); `block_number` is a **string** field; `feed_rate` **does** vary properly (430 distinct values, 0–10606, mean 1484) so actual-vs-programmed feed is viable; `spindle_speed` 0–5000 real.

**PILOT PART measured:** 4 Sep **04:10:17–06:16:40 UTC (09:40–11:46 IST), 2 h 06 m**, 5784 samples, **8 programs back-to-back** (2–30 s apart ⇒ one setup, 8 operations): `1_10END_OUTER` → `2_10END_OUTER_FIN` → `3_1CD` → `4_3.2DRILL` → `10END_FLAT` → `5_6END` → `6_4END` → `7_4END_FLAT`. State split 88.8 % run / 10.7 % hold / 0.5 % reset; alarm=1 on 182/5784. **The program-name leading number is OPERATION SEQUENCE, not setup** (all 8 in one setup; `10END_FLAT` has no prefix and ran 5th).

**Build order:** `krishna_metrics.py` (machine_window + job_run from telemetry alone) ✅ BUILT → link CAM `.tap` (`vs_cam`) → link CAPP output (`vs_capp`) → QC ingestion / gap G01 (`qc`) → extend to TS.

### 4-Sep coverage reality (checked 2026-09-07, `scratchpad/krishna_coverage_4sep.py`)

The part was made 09:00–19:00 IST but telemetry only covers **04:10:17 → 06:16:40 UTC = 09:40 → 11:46 IST, ~2 h 06 m of a 10 h job (~21%)**. Collector then stopped dead until 2026-09-05 10:08 UTC (a ~28 h gap). Likely the Smart Connect PC was closed mid-morning. **So the 8 operations in the report are only the first fifth of the part** — every total is a floor. This must be shown on the page, not buried.

### krishna_metrics.py / report — additions 2026-09-07 (round 2)

- **Two-level model:** operations (8, one per program) → cycles (real machining runs) + `idle_before_s` (program loaded on controller, cycle not started = inter-operation setup/load time, ~13 min in this window). The raw segmenter over-splits into 19 "runs"; `build_operations()` rolls them up. Repeat cycles kept (e.g. `10END_FLAT` ran 3×) as the run-to-run consistency view.
- **Rolling machine utilisation** — `fetch_period_utilisation()` queries last 1d / 7d / 30d; report has a segmented control to switch window (+ "this window"). Each shows utilisation %, sample count, **log-coverage %** (samples ÷ seconds — exposes PC-off time), state split.
- **Part-by-part section (band "1b")** — `build_parts()` clusters operations on a `--part-gap-hours` gap (default 2; `production_count` can't be used — M30 counter). Per part: start/end (UTC + clock), logged elapsed h, utilisation % (with a circled-**i** hover showing the formula), log-coverage %, cutting ratio, cutting/air/paused/setup chips, state split, program sequence.
- **`--part-actual "START,END"`** — pass the real shop-floor window; the part card then shows a ⚠ box: "logged window is X% of the actual job, ~Yh of machining has no data." For the pilot: `--part-actual "2026-09-04T03:30:00Z,2026-09-04T13:30:00Z"`.
- **`i` info-icon component** in the template — circled i, hover shows a `data-tip` string. Utilisation formula string lives in `UTILISATION_FORMULA` in the py.
- Offline-tested (`scratchpad/test_krishna_metrics.py`): operations rollup, part clustering (gap 2h→1 part, 0.05h→2), actual-window contrast, template injection (41 KB), JS syntax. Not yet run live (user runs it).

### Telemetry-table ordering bug — FIXED (not yet deployed)

`getRawTelemetry` / `exportTelemetry` in **both** `public/telemetry.controller.js` and `admin/telemetry.controller.js` on branch — was `sort → pivot → limit` with **no `group()`**. Since `program_name` is a tag, the stream stayed split per-program, so sort ran within each program and `limit` took N per-program → the table jumped around in time (and cursor pagination was wrong too). Now `pivot → group() → sort(desc) → limit`. `node -c` clean.

### `GET /public/telemetry/analytics/breakdown` — NEW endpoint (not yet deployed)

Machine time breakdown for the filter panel's window (`range` OR `startDate`/`endDate` + `factoryId`/`machineId` — same params as `/summary`). Walks consecutive samples, classifies each gap by which counter advanced: **cutting** (`cutting_time` up) / **air** (`cycle_time` up, cutting not) / **paused** (neither, mid-cycle) / **setup** (`cycle_time` 0). Machine-agnostic — only uses counter *direction*, so MM·SS vs seconds doesn't matter. Gap capped at 10 s so collector outages aren't counted. Returns `windowSpanSeconds`, `samples`, `coveragePct`, `utilisationPct` (via `canonicalMachineState`), `cutting/air/paused/setupSeconds`, `inProgramSeconds`, `stateDistribution`. Added to `analytics.controller.js` + `analytics.routes.js` + module exports. `node -c` clean.

### Frontend: "Machine time breakdown" card on PublicAnalytics.js — NOT deployed

New `<MachineBreakdown>` component at the **top of the Summary tab**, under the existing filter panel (reuses its date control — custom + `-1d`/`-7d`/`-30d`/etc. — and the machine selector; no reinvented control). Tiles in the order the user asked: **Window · Log coverage · Utilisation** then Cutting / Air-rapid / Paused / Setup, then a machine-state distribution row. Each tile has a circled-**i** (`InfoDot`, native `title` tooltip) with the plain-English definition (`BD_DEFS`). Log-coverage tile shows "N samples ≈ M min of data". `telemetryService.getBreakdown()` added; `fetchBreakdown()` wired into the 3 summary-tab fetch points + reset + machine-change. esbuild-clean.

### `krishna_report.html` — restyled to match `/admin/#/public/analytics` (round 4-5)

User wants the local report to *look like* the public-analytics page (they're keeping it local for fast iteration, not porting to the deployed React dashboard). Rebuilt with that visual language: `--primary:#2160b7` blue, white 16px cards + soft shadow, a **"Filters" panel** (Machine / Date range / Window start / Window end), a **pill tab bar** — `Summary` · `Part by part` · `Operations` · `Data gaps` (real client-side tabs), **icon-square stat tiles**. Every metric keeps its circled-**i** `DEFS` tooltip.

- **Date-range dropdown is live** — `krishna_metrics.py` now also computes a machine-level breakdown for **last 1 / 7 / 30 days** (`--windows 1,7,30`, `fetch_period_breakdown()`); the Summary tab's tiles + state row swap when you change it. Part-by-part / Operations / Data-gaps stay pinned to the analysed part window (rolling views are machine-level only, so they hide the per-op charts).
- **Tile order:** Window · Log coverage · Utilisation · Cutting · Air/positioning · Stopped · Setup/load · Untracked · Alarm.
- **Log coverage** shows `fmtDur` (h/m) of sampled time + the note "≈ 100% − untracked ÷ window" (its denominator spans every card; numerator = everything except untracked).
- `bucket_time(samples)` extracted as the single source for the state-aware cutting/air/stopped/untracked split (used by `run_metrics` + the period breakdowns); also returns per-state seconds.
- **`machine_state` during setup/load** is now recorded (`idle_state_secs` per op → `setup_idle_state_secs` per part) and shown on the part card — answers "is state 2 during setup?": cutting & air are state 3 (confirmed); setup/load is barely sampled so it's a thin 2/3 mix.
- Offline-tested; `periods` fetch adds 3 light queries per run (30d pulls a lot of samples, slower).

### Round 6 (2026-09-07)

- **Cycle-split hardened** (`segment_runs`): a `cycle_time` reset now only starts a new cycle if the decoded value drops below **30% of the run's peak** AND stays low for **2+ samples**. Stops a single glitchy MM·SS sample spawning a phantom cycle.
- **Cycles de-emphasised in the report**: Window tile + part-card header say just "N operations"; cycle count only in the per-op table `Cyc` column + the Repeat-cycles expander. **Conclusion reached: operations is the primary unit** — cycles are a within-operation consistency detail, only meaningful when >1 and they differ. The `10END_FLAT` "3 cycles" is one facing operation the operator re-ran (skim-to-thickness or restart-after-stop; the `.tap` is a single raster pass — confirmed from the CAM file).

### Pilot part files received — SE-004-052 "NAS PC CPU Bottom Plate"

`Claude output for program sheet/Dataset/Krishna/Bottom Plate/`: `input/SE-004-052.stp` + `.pdf`, `CAM files_Krishna/` (16 `.tap`), `Inspection Report_Krishna/SE-004-052.xlsx` (19 dims, **all in tolerance — part PASSED**). Aluminium, Qty 1. **16 CAM toolpaths, only 8 ran 4 Sep** (rest on the missing day — matches the coverage gaps). **Run order ≠ CAM file order** (`10END_FLAT` inserted between op 4 and 5, facing done after profile+holes). `.tap` headers: `TOOL TYPE`/`TOOL ID`/`TOOL DIA. & LENGTH`/`TOOLPATH`/`TOLERANCE`/`STOCK` + `S####` on first M03 + per-move F. **No CAM time estimate** in these headers (unlike Motor Mount) — derive from path-length ÷ F.

### Closed-loop design — `audit/SPEC_krishna_closed_loop.md` (NEW)

**Direction: form the closed loop from telemetry + CAM + QC only — NOT CAPP.** Loop = CAM (plan) → telemetry (what ran) → QC (did it pass) → `shop_knowledge.jsonl` flywheel. Unit = one **labelled operation record** per (part × operation): tool, feature, programmed S/F/tol/stock, actual RPM/feed/time/cycles/alarms, deltas, QC outcome + deviations. Joins: operation↔`.tap` by name (auto), `.tap`↔tool (auto), **operation↔QC dims = one hand-filled `operation_qc_map.json` per part** (only manual step). Two uses from record 1: programmer reference table, and anomaly/deviation flagging. ### `closed_loop.py` — BUILT 2026-09-07 (repo root)

`python closed_loop.py "<part_dir>"` → for a part folder (`input/*.stp` + `.pdf`, `CAM files*/*.tap`, `Inspection Report*/*.xlsx`):
- **CAM parser** (self-contained in the script — didn't touch `cam_program_parser.py`): per `.tap`, reads header (`TOOL TYPE/ID/DIA./LENGTH`, `TOOLPATH`, `TOLERANCE`, `STOCK`), programmed `S` (first M03 line), programmed `F_cut` (feed covering the most cut length) + `F_lead`, cut-path length (Σ segment distance on G1/G2/G3, arcs as chords), a feed-motion cut-time estimate, drill-cycle hole count + total depth, and X/Y/Z extents. `feature` inferred from name+geometry. `toolpath_name()` strips only real G-code exts (Path.stem breaks `4_3.2drill`).
- **QC reader** — parses the inspection `.xlsx` (sharedStrings + sheet1): per SL, nominal (leading number of Description, Ø stripped), tol±, measured min/max, pass = measured ∈ [nominal−tol−, nominal+tol+], dev = mid−nominal. Also pulls `Part Name` / `Material` from the header rows.
- **Telemetry** — imports `krishna_metrics.build()` (SimpleNamespace args), gets `operations`. `--no-telemetry` skips the InfluxDB pull (CAM+QC only).
- **operation→QC map** — reads `<part_dir>/operation_qc_map.json`; if absent, writes a **stub listing all 19 QC dimensions** for the engineer to fill from the drawing balloons. This is the one manual step; `[]` = no dimension attributable, record still made.
- **Output:** `<part_dir>/closed_loop_record.json` (part_meta + summary + one record per operation: tool, feature, programmed, actual, deltas, qc outcome, flags) · appends each record to `./shop_knowledge.jsonl` (the flywheel) · re-renders `krishna_report.html` with a **"Closed loop" tab** (CAM-vs-actual-vs-QC table, deviation flags, KB count) and `krishna_metrics.json` carrying `data.closed_loop`.
- **Flags** raised: RPM/feed >15% off programmed, alarm during op, more cycles than the CAM has, QC FAIL, or no telemetry (ran off-window).

**Verified offline (`--no-telemetry`) on Bottom Plate:** 16 toolpaths parsed, part_meta = "NAS PC CPU Bottom Plate"/aluminum, QC 19/19 in tolerance, 16 records → `shop_knowledge.jsonl`. `10END_FLAT` → face, S4500/F1000, path 3367mm/est 202s, geom X±54 Y±39 (= the 108×78 plate). `4_3.2drill` → drill, 8 holes; tool comment in the .tap wrongly says Ø1 `1cd` (stale CAM post — parser reports it faithfully).

**Known CAM-estimate limits:** `est_cut_s` is feed-motion only (no rapids / tool change / spindle ramp / dwell) → always under actual `cutting_time`. Drill estimate ignores G83 peck retracts → badly undercounts deep pecking (`4_3.2drill` est 272s vs ~30min telemetry, mostly peck overhead + setup).

**Full run DONE 2026-09-07** (`python closed_loop.py "Claude output for program sheet/Dataset/Krishna/Bottom Plate"`) — first end-to-end closed-loop output. Bugs fixed along the way: `query()` now drops Flux's re-emitted per-table header rows (`{"_time":"_time",...}` crashed `_parse_ts`); `bucket_time()` no longer records a `None` state key (period-window pivot rows can lack `machine_state` → `sorted()` choked on `None < 0`).

**First findings from the loop (Bottom Plate, 8 of 16 ops have telemetry):**
1. **Operator differentiates feeds; CAM doesn't.** Every `.tap` programmed a flat `F1000`. Actual median feed vs programmed: `1_10end_outer` **+40%** (rough, ran hot), `7_4end_flat` **−70%**, `6_4end` −40%, `5_6end` −32%, `2_10end_outer_fin` −20%, `10END_FLAT` −15% (finishing babied). Feed parse verified against raw `.tap` (files contain only F1000 cut / F500 lead) — deviations are real shop practice. → feed back as recommended feed per operation type.
2. **`alarm_active` unusable** — 61 "alarm events" on `4_3.2drill`, 45 on `5_6end`, part passed all 19 dims. The `Alarm1`-non-blank heuristic misfires. Concrete ask for the Krishna/Mitsubishi team.
3. **Stale CAM tool comments** — `4_3.2drill` header says Ø1 `1cd` (copy-paste from the centre-drill post); actual RPM 799 vs header S1000.
4. `10END_FLAT` ran 3× on a 1-pass program — confirmed vs CAM (operator re-ran; skim-to-thickness or restart).

**To complete the loop:** fill `Bottom Plate/operation_qc_map.json` (stub lists all 19 dims) — map each operation → its SL numbers from the drawing balloons, re-run → per-op PASS/FAIL + deviation → each becomes a `shop_knowledge.jsonl` row.

**Small improvement pending:** in `parse_tap`, expose the drill-cycle feed (`F30`) as the programmed drilling feed so `4_3.2drill` shows actual-20 vs programmed-30 instead of `F_cut: None`.

### Report round 7 (2026-09-07)

- **All displayed times → IST** (UTC+5:30). InfluxDB timestamps stay UTC; `_ist()`/`fmtDate()`/`fmtDT()` helpers convert for display; every "UTC" label now "IST". `--start`/`--end` CLI args stay UTC (they go to InfluxDB).
- **"Machine state" standalone card removed** from Summary (redundant with the tiles). Part-card state row kept.
- **Tab restructure:** dropped the **Operations** tab. **Summary** = machine tiles + "what stands out" only. **Part by part** now carries, per part: the part card + the time-breakdown stacked chart + operation timeline + RPM/feed charts + per-operation detail table + repeat-cycles expander (all filtered to that part's `operation_indexes`). `partDetail(pRuns)` is the new per-part block; `opsTab` removed.
- **RPM/feed charts are now programmed-vs-actual** — `progVsActual()` draws a CAM-programmed outline bar + actual solid bar + %-delta label per operation, pulling programmed S / F_cut from `DATA.closed_loop.records` (so it only shows the comparison when run via `closed_loop.py`; falls back to actual-only `barChart` otherwise). ⓘ notes that tool-/material-prescribed values (from a tool catalogue) are a later addition — **parked, noted in the tooltip.**

### Report round 8 (2026-09-07)

- **RPM/feed "programmed vs actual" charts removed from Part by part** — they duplicated the ΔS / ΔF columns already in the closed-loop table. `progVsActual()` / `progMap()` helpers left in the file as dead code (no caller) in case a chart form is wanted back later.
- **"Closed loop" is no longer its own tab.** `loopTab()` renamed `closedLoopSection()` (returns `''` when `DATA.closed_loop` absent, no fallback card). It's now rendered **inside `partDetail(pRuns)`**, positioned after the operation timeline and **before the "Per-operation detail" table**, under a grey section-header card "Closed loop — CAM plan vs machine actual vs QC". `TABS` back to `Summary · Part by part · Data gaps`; `panels.loop` and the `id!=='loop'` tab filter removed. Summary lead line updated ("...and the CAM-vs-actual-vs-QC closed loop are under Part by part").
- Per-part order now: part card → time breakdown → timeline → **closed-loop section** → per-operation detail → repeat-cycles expander.

**Round 8b — the two per-part tables aligned:**
- **Row order matched.** "CAM programmed vs machine actual vs QC" now sorts by telemetry **run order** (off-window ops after, by file name) instead of alphabetical CAM filename — same order as "Per-operation detail" below it.
- **`ΔCut` column added** to the CAM-vs-actual table (`deltas.cutting_vs_est_pct`, red > 25%): actual cutting time vs the CAM path-length/feed estimate.
- **`Flags` column removed** from the CAM-vs-actual table (duplicated the per-op signals). **`Cyc` column removed** too — cycle count is in Per-operation detail.
- **`Alarm ev` column added** to Per-operation detail (`r.alarms.events` count), so removing Flags doesn't lose the alarm-event count. Per-op detail now: … RPM med · Feed med · Load max · Alarm % · **Alarm ev**.
- Syntax + offline test pass; template injection 58,755 bytes. Regenerate with `closed_loop.py "<part dir>"` (needs live InfluxDB — user runs it).

### Step-by-step (intra-operation) deviation — analysis started 2026-09-08

- **Offline `.tap` step decomposition** (`scratchpad/tap_steps.py`): each of the 16 Bottom Plate programs broken into programmed feed segments (N-range, feed, blocks, path len, est time, Z window). N-numbers are dense & sequential (N1..N5268). Key structures: `1_10end_outer`/`2_10end_outer_fin`/`10END_FLAT` = 1 plunge blk **F500** + one long **F1000** cut; `1_10end_ruf` = 26 Z-step passes (F150 plunge → F1500 cut → F3000 link); `5_6end` = 348× (F500+F1000) pairs; `2_4end_rest` = 556 segments; drills = single G82/G83 canned block, **F30**.
- **Whole-part override pattern (from the op-level closed loop):** operator ran the big Ø10 roughing endmill **+40% feed / +11% RPM**, but every finish / small-tool / face op **−15% to −70% feed**; both drills ran **slow** (feed ~8–20 vs 30) with **heavy alarms** (`4_3.2drill` = 61 events, still passed QC).
- **What op-level medians can't answer** → needs a position anchor: (1) was the *plunge* also scaled or only the cut, (2) did the override *drift* across passes on the many-segment ops, (3) were the re-run cycles (`10END_FLAT` ×4, `3_1cd` ×2) same-depth or skim, (4) where in the program did alarms cluster, (5) did spindle S sag under load.
- **PROBE RUN 2026-09-08** (`scratchpad/krishna_blocktrace.py`) — **both position anchors are real:**
  - `axis_x/y/z` = **real high-res tool position.** Constant G54 offset: X_machine ≈ X_cam + 677.31, Y_machine ≈ Y_cam − 262.35, part-top Z ≈ −390 (±2 mm/op). Detectable from the block-12 rapid-to-X0Y0 rows (they sit at 677.31/−262.35).
  - `block_number` = **executing block N-number**, resets to 0 each cycle, and is a **signed int16 that wraps** (`6_4END` has 36 076 lines → readings go −32747… ; add 65536). Matches every `.tap` line count otherwise (5272≈N5268, 83≈N83, 10880≈10883, 356≈361, 24≈29).
- **Step-level deviation findings (pilot, from the trace):**
  - Feed overrides are **constant dial settings held for the whole op**, never ridden mid-cut. `1_10end_outer` +40% feed / +11% S flat, 0 alarms — but log opened at block 3005 with cutting_time already 503 s, so ~57% (incl. the plunge) ran before logging → the "cut −71% vs est" is a **coverage artifact**. `2_10end_outer_fin` −20% feed flat. `10END_FLAT` = **2 aborted starts + 2 real facing passes** (999 then 899) = skim-to-thickness, not one op. `3_1cd` S exact, drill feed ~11 vs F30 (−60%). `4_3.2drill` S −20% flat + peck feed ~20 vs 30, 61 alarms = 1/peck (benign, passed QC). `5_6end` uniform −30% on lead+cut (one knob), 45 alarms scattered — the one to look at. `6_4end` cut actually ran **~899 ≈ −10%**, not the record's −40% (median blends 150 lead-in moves + MDI samples). `7_4end_flat` "−70%" is **acceleration-limited geometry** (mm-long segments), not an override.
  - `alarm_active` = retract/stop-toggle **noise**, never a standalone flag.
  - **MDI/jog sessions fold into the next op** (`3_1cd`, `5_6end`, `6_4end`): block 0 + feed 0 + cutting_time frozen + rpm noise → inflates setup time, drags feed_median toward 0. Should be stripped.
- **Step-by-step tab SHIPPED 2026-09-08 (hand-authored, not yet auto-generated):**
  - `Claude output for program sheet/Dataset/Krishna/Bottom Plate/step_analysis.json` — plain-English notes: `intro`, `coverage`, `glossary` (17 terms — S, feed, override, flat, plunge, lead-in, peck, canned cycle, block, MDI, G54, alarm_active…), `operations` (8 cards: feature / headline / what_cam_said / what_happened / what_it_means / caveat), `cross_cutting` (6 patterns). Keys starting `_` are stripped.
  - `closed_loop.py` loads it if present → `tele["closed_loop"]["step_analysis"]`.
  - `krishna_report_template.html` — new **`['steps','Step-by-step']`** tab between Part-by-part and Data gaps (`stepsTab()`; only shows when `DATA.closed_loop.step_analysis` exists). Glossary is a collapsed `<details>`; each op is a card with a 4-row table; patterns as `ul.ins`.
  - Node render check + JS syntax + offline test all pass; injection 61 KB.
- **Sharing `krishna_report.html` (confirmed 2026-09-08):** it IS team-shareable — one self-contained `.html` (~120 KB), opens by double-click in any browser, offline, no server. **No credentials / no InfluxDB endpoint / no token in the file** (those are only in the `.py` scripts; the report carries generated data only). Caveats to weigh before it leaves ShiaanX: it names a real customer part (SE-004-052 "NAS PC CPU Bottom Plate") with its inspection dimensions + the shop's feeds/speeds; it's a point-in-time snapshot covering only ~21% of the 4-Sep job (stated on the page). It's `file://` so there's no link to send — send the file itself (Slack/email/drive), or ask to publish it as a private Artifact for a URL.
- **Report width fix 2026-09-08:** dropped `max-width:80ch` from `.lead` (and the Step-by-step glossary `<dd>`) — prose was wrapping at ~half width. Now fills the card / `.wrap` 1200px. (`.wrap` page cap left at 1200px.)

### Datum & workholding from the PowerMill project (checked 2026-09-08)

The PowerMill CAM project IS in the repo: `Claude output for program sheet/Dataset/Krishna/Bottom Plate/CAM Project_Krishna/SE-004-052/` — 2019 PowerMill 10006 database-format project (flat folder, `SE-004-052.pmlprj` index + hashed `*.pmlent` entities). The `.pmlent` files are binary but **carry embedded JSON headers** (reliable): `scratchpad/pml_peek.py` + inline scripts parse them.
- **DATUM — answerable.** Project has **2 workplanes**. Every toolpath's JSON declares its `Workplane`:
  - **Workplane 2** → all 8 ops that ran 4-Sep (`10END_FLAT, 1_10end_outer, 2_10end_outer_fin, 3_1cd, 4_3.2drill, 5_6end, 6_4end, 7_4end_flat`) — the `Toolpath\1st_satting\` group.
  - **Workplane 1** → the other 9 (`1_10end_ruf, X_12END_RUF, 2_4end_rest, 3_4end_fin, 4_4end_flat, 5_4boll_fin, 6_2end_fin, 7_2end_fin_1, 8_2end_fi`).
  - So it's a genuine **2-setup job**; all our telemetry is Setup/WP2. The 710-byte WP entities differ by two negated matrix diagonal elements → **WP1↔WP2 ≈ 180° flip** (part turned over between setups). WP1 binary also carries `7.5` and `-2` (WP2 doesn't) — likely a Z shift. Exact origin triple needs PowerMill/a real parser to confirm; **do not quote it as fact.**
  - Datum is **centre-centre-top**: toolpath `Block` limits are symmetric (X ±54, Y ±39) with Z 0→−8 (Z0 = top face). Confirms the earlier `.tap`-derived read, now from the CAM project not inference. WP2's machine-space origin ≈ (X 677.31, Y −262.35, Z −390) from the block-trace probe.
- **STOCK — answerable (JSON).** Per-toolpath `Block` (workplane coords): most WP2 ops `X[-54,54] Y[-39,39] Z[-8,0]` = **108×78×8 mm**; the outer-profile/drill ops use oversized `X[-60,60] Y[-45,45] Z[-10,0]` = 120×90×10 (perimeter allowance). WP1 ops mostly Z[-7.5,0]; `X_12END_RUF` block Z[0,8] (positive Z = the flipped face → confirms the flip). Raw stock ≈ **120×90×10**, finished ≈ 108×78×~8 (matches QC SL#1=78, SL#4≈108).
- **WORKHOLDING — genuinely NOT in the CAM.** No `pmlEntFixture`, `StockModel` category empty, no vice/jaw/clamp anywhere. "Holder" strings in the toolpath entities = the **tool holder** (gouge-check geometry), not workholding. Model `Planes` (987 B) has no geometry — construction planes for building the workplanes. → Workholding needs a setup sheet or a shop photo; it cannot be recovered from these files.
- **Bonus (JSON, reliable):** each toolpath also has designed `CuttingSpeed` (Vc m/min), `FeedPerTooth` (fz), `Cutting`/`Plunging`/`Rapid` feeds, `Strategy` (constantz / raster_flat / offset_area_clear / drill / opti_constz…), `Stepdown`, `ToolAxis: vertical` (pure 3-axis). Richer than the `.tap`. `EditHistory` dates are **2019-08-24** (10END_FLAT & X_12END_RUF: 2019-09-04) — CAM is from 2019, telemetry run is 2026-09-04 (same calendar day, 7 yr apart — shop-clock or a re-run of an old proven program; unresolved).
- **BUILT 2026-09-08 — CAM-project parsing + shop-floor input + QC-map scaffold:**
  - **`pml_project.py`** (repo root) — `load_project(pmlprj)` reads the `.pmlprj` entity index + the embedded JSON in each `.pmlent` (binary transforms NOT decoded). Returns per toolpath: `workplane` (resolved name), `strategy`, `stepdown_mm`, `tool_axis`, `stock_block_mm` (+size), designed `feed_cut`/`feed_plunge`/`feed_rapid`, `vc_m_min`, `fz_mm`, `cam_edited`; plus `workplanes` list and `setups_by_workplane`. Tested against Bottom Plate: WP2 = the 8 telemetry ops, WP1 = the other 9; drills carry F30/S1000-equivalent (Vc 3.14, fz 0.03).
  - **`closed_loop.py`** — loads the CAM project + a new **`job.json`** if present. Each record gains `planned_cam` (the pml fields), `setup` (workplane + shop-floor workholding/orientation/stock when in job.json, else "not recorded"), `shop_floor` (per-op actuals from job.json), and a flag when posted `.tap` feed ≠ CAM-designed feed. `summary` gains `setups`, `quantity`, `shop_floor_outcome`, `job_json`, `cam_project`. `closed_loop_record.json` gains a top-level `setups` array. `job.json` run windows override `--start/--end`.
  - **`job.json`** — auto-written template into the part folder on first run (prefilled: part id, quantity, run window, one setup block per CAM workplane with its op list). The shop fills: `runs[]` (real windows, multiple allowed), per setup `orientation` + `workholding{type,detail,datum_touched_off,gcode_offset}` + `stock_actual_mm`, `operation_actuals{op:{tool_substituted,notes,outcome}}`, `outcome{parts_good,parts_scrap,rework,notes}`. All optional → blanks render as "not recorded". This is **the on-ground half of the loop**.
  - **`operation_qc_map.json`** — `_write_qc_map_scaffold()` refreshes the helper blocks without touching user mappings: `_operations` (feature | tool | strategy WP | XYZ extent per op) + `_qc_dimensions` (desc — measured, per SL) + `_example`. Loud console note when nothing is mapped yet.
  - **`krishna_report_template.html`** — Step-by-step tab now also shows (even without `step_analysis`): a **"Setups & workholding"** card (per workplane: ops, orientation, workholding, datum, measured stock — from job.json or "not recorded — add to job.json") and an **"As designed → as posted → as run"** table (strategy/stepdown/Vc/fz/designed-F from CAM project, F&S posted from `.tap`, F&S run from telemetry; amber F-posted = `.tap` hand-edited). QC warnbox rewritten with the concrete mapping steps. `.lead` max-width removed (prose was half-width). Tab shows if step_analysis OR setups OR any `planned_cam`.
- **Setup ORIENTATION — now DECODED from the `.pmlent` binary (2026-09-08).** `pml_project._decode_workplane()` scans 8-byte-aligned float64 windows for the first where doubles[3:12] form an orthonormal matrix (rows unit-length, mutually orthogonal, |det|≈1) and takes doubles[0:3] as the origin — **version-independent, self-validating**, no fixed offsets. Confirmed on both Bottom Plate workplanes (transform at byte 528; also verified by raw byte-diff — only origin-Z + two matrix diagonal terms differ):
  - **WP1** = identity rotation, origin model (0, −78, 7.5) → part as-modelled, tool works the **model +Z (top) face**.
  - **WP2** = **180° about Y**, origin model (0, −78, 0) → part flipped upside-down, tool works the **model −Z (bottom) face**. Z-origin drop of 7.5 = the stock thickness.
  So: WP1 = drawing-top side (roughing, rest, ball-nose 3-D finish); WP2 = drawing-bottom side (facing, outer profile, the 8 through-holes, pocketing). The operator `orientation` line in `job.json` is now a *confirm/override*, not a required entry. Caveat: validated on axis-aligned 180° flips from one 2019 project; a general angled workplane assumes origin-then-row-major layout — re-check against another project when one is available.
  - `pml_project` returns `workplane_detail{name:{byte_offset,origin_model_mm,matrix,rotation_deg,z_axis_in_model,orientation}}`. `closed_loop.py` prefills each `job.json` setup `orientation` + `_orientation_hint`, folds it into `setups_out` with `orientation_source`, and passes `workplane_detail` to the report. `krishna_report.html` Setups card shows the decoded orientation + a "Workplane transform" row; the Inputs form pre-fills the orientation field.
- Node render + JS syntax + `closed_loop.py --no-telemetry` + offline test all pass. Regenerate the live report with `closed_loop.py "<part dir>"` (needs InfluxDB — user runs).

### In-page Inputs form 2026-09-08 (no more hand-editing JSON)

User pushback: hand-editing `job.json` / `operation_qc_map.json` is too fiddly. Built an **Inputs tab** in the report:
- **`closed_loop.py`** now also emits `tele["closed_loop"]["inputs"]` = `{part, job (raw, or null), qc_map {op:[sl]}, qc_dims [{sl,description,nominal,measured,tol±}], operations [{name,feature,workplane}], cam_workplanes}` — everything the form needs to pre-fill.
- **`krishna_report_template.html`** — `inputsTab()` + `wireInputs()` + form helpers. Sections: **Job** (quantity, machining window rows — "+another window"), **Setups & workholding** (one block per CAM workplane: orientation, workholding type dropdown, detail, datum touched off, G54–G59, measured stock XYZ, notes), **Inspected dimensions** legend table, **Per operation** (row per toolpath: 19 clickable **SL chips** for QC mapping + tool-substituted + note + outcome dropdown), **Part outcome**. Edits autosave to `localStorage` (`krishna_inputs_<part>`). Two buttons build & download **`job.json`** and **`operation_qc_map.json`** (Blob + `<a download>`, works from `file://`); "Reset form" clears the draft. Prefill order: localStorage draft → server-loaded job.json → CAM defaults. New CSS block (`.inp`,`.btn`,`.qcchip`,`.setupblk`). Tab shows whenever `DATA.closed_loop.inputs` exists.
- Workflow: open report → Inputs tab → fill → Download both files → drop in part folder → re-run `closed_loop.py`.
- **`shop_knowledge.jsonl` = one row per (part, operation):** `closed_loop.py` now **rewrites** the file each run — drops all rows for the current part, keeps every other part's rows, appends the fresh set. Re-running a part supersedes its rows instead of stacking. Self-heals earlier duplication.

### Rules tab + Inputs-form time fix (2026-09-08)

- **`step_analysis.json`** gained a **`rules`** array (6 hand-authored rules emerging from this part: aggressive Ø10 roughing point, finish feeds run 20–40% low, deep-small-drill recipe + ~2 min/hole, `alarm_active` is not a fault signal, facing re-runs = skim-to-thickness, overrides are set-once-and-held).
- **`closed_loop.py`** — `knowledge_rules(kb)` groups every `shop_knowledge.jsonl` record by (material, tool type, Ø, feature) → per group: n records / distinct parts, S/F posted, S/F run range, designed Vc/fz, feed-override range, QC outcome counts. Passed as `tele["closed_loop"]["knowledge_rules"]`.
- **`krishna_report.html`** — new **Rules** tab (between Step-by-step and Inputs): "Rules emerging from this part" (from `step_analysis.rules`, each with basis + confidence pill) + "Parameter knowledge base" table (from `knowledge_rules` — the programmer's lookup: what S/F produced good parts for a tool+feature+material, with a pass-rate as parts accumulate). Tab shows if either source is non-empty.
- **Inputs form times → IST.** The machining-window fields were labelled UTC; now they show/accept **IST** (`YYYY-MM-DD HH:MM`, shop-floor time). `utcToIstField()` / `istFieldToUtc()` convert on prefill and on download; the `job.json` file still stores UTC ISO (`…Z`) because it feeds InfluxDB. Round-trip verified (03:30Z ↔ 09:00 IST).
- Tabs now: Summary · Part by part · Step-by-step · Rules · Inputs · Data gaps. All syntax/render/offline tests pass; injection ~88 KB.
- **Inputs tab operation order fixed:** `closed_loop.py` now sorts the `inputs.operations` / `inputs.qc_map` payload by run order (telemetry ops in the order they ran, off-window ops after by file name) — was alphabetical by `.tap` filename, out of step with every other per-operation table. Each op block also shows `· ran #N` / `· off-window`.
- **`closed_loop.py` resilient to InfluxDB being unreachable (2026-09-08):** `load_telemetry()` used to crash the whole run on a DNS/connection error, losing the CAM/QC/job/rules work. Now on any non-SystemExit exception it falls back to the last successful `krishna_metrics.json` (strips its stale `closed_loop`, tags `_telemetry_source = "cache — …"`), so the record + report still regenerate with fresh CAM/QC/job/rules and the previous pull's machine numbers. If there's no cache, it continues telemetry-less. The report shows a `warnbox` banner when telemetry is cached. (The 2026-09-08 DNS failure the user hit was transient — the immediate re-run pulled live 5,784 samples fine.)
- **Bottom Plate `job.json` + `operation_qc_map.json` are now filled** (user did it via the Inputs tab, downloaded, dropped in the folder): quantity 1, IST run window → `2026-09-03T21:30Z..2026-09-04T08:30Z`, both setups' orientation/workholding, and **all 19 QC dimensions mapped across 11 operations** (coverage 19/19). `operations_qc_mapped` = 11, part_outcome PASS.
### Multi-part report (2026-09-10) — the live-environment direction

- **9-Sep coverage (probe `scratchpad/krishna_coverage_9sep.py`):** telemetry was captured **~the whole working day** — ~20,400 samples, roughly **09:36–18:00 IST continuous**, machine_state 90.3% running / 7% hold / 2.5% state "6" (new, unknown) / 0.2% reset. First near-complete capture (vs 4-Sep's ~21%). Programs run: `1_10END`, `1_10END_RUF`, `2_4END_RUF`, `3_4BOLL` (big 3-D ball-nose, ~2.5h), `3_4END`, `4_1CD`, `4_3.2DRILL`, `5_3.2DRILL` — a **different part** (similar naming convention). (The probe's "span 0.6h" line + overlapping gap list were a bug — Flux returns per-`program_name` table groups; the script didn't `group()` before sorting. Per-hour histogram is right. Fixed the script with `|> group()`.)
- **`closed_loop.py` is now multi-part.** `main()` → `assemble_part(part_dir, args, km)` (per-part payload, writes that part's `closed_loop_record.json` / `job.json` stub / qc-map scaffold; no shared writes) + a thin `main()` that: takes `part_dir` `nargs="*"` **or `--parts-root <folder>`** (`_discover_parts` = immediate subfolders with a `job.json` or real `.tap`/numbered G-code; empty skeletons skipped), assembles all, rebuilds `shop_knowledge.jsonl` (regenerated parts replace their rows, others kept), computes `knowledge_rules` once across everything, then:
  - **1 part** → single `krishna_report.html` exactly as before (back-compat).
  - **>1 part** → ONE report injected as `{machined_parts:[{label,part_id,payload}], knowledge_rules, generated_at}`.
- **`krishna_report_template.html`:** injected global renamed `RAW`; `const MACHINED = RAW.machined_parts`; `let DATA` + `activatePart(i)` points `DATA` at the active part's payload and splices in the shared `RAW.knowledge_rules`. `render()` adds a **Part selector** (`#partSel`) above the filter panel when multi; changing it calls `activatePart(i); render()` (full re-render, every tab). Single-part reports (`RAW` = bare payload, no `machined_parts`) unaffected — `DATA = RAW`.
- New folder **`Dataset/Krishna/Part 2 (2026-09-09)/`** (skeleton + `README.txt`) — drop Part 2's `CAM files_*` (.tap), `CAM Project_*` (.pmlprj), `Inspection Report_*` (.xlsx), then `closed_loop.py --parts-root "Claude output for program sheet/Dataset/Krishna"` → combined report. Fill its `job.json` + QC map via the Inputs tab (part selector chooses which part you're editing).
- Node render test: multi payload renders, 2-option selector, part switch re-renders clean. Single-part live run + offline test pass.

### Part 2 = RKSE-004-053 (added 2026-09-10)

- Folder `Dataset/Krishna/Part 2 (2026-09-09)/` now has: `input/RKSE-004-053.stp`, 8 `.tap` (`1_10end`, `1_10end_ruf`, `2_10end_1`, `2_4end_ruf`, `3_4boll`, `3_4end`, `4_1cd`, `5_3.2drill`), PowerMILL project `SE-004-053.pmlprj` (2 workplanes → 2-setup part again). No drawing PDF. STEP bbox ≈ 60 × 98 × 10 mm.
- **QC: refused to fabricate.** The real Bottom Plate FIR has ballooned dims + caliper readings + named inspectors — inventing that for RKSE-004-053 (no drawing, no measurements) would be a fake quality record. Instead generated a **blank template** `Inspection Report_Krishna/RKSE-004-053.xlsx` (openpyxl, Bottom Plate layout) with 6 CANDIDATE dimension rows from CAD (nominals only; TOL/measured/remark blank) and a bold "TEMPLATE — not a completed inspection" note. QC fills the real values.
- **`parse_qc_xlsx` hardened** for that template (and any openpyxl-authored xlsx): now reads `t="inlineStr"` cells (`<is><t>`), and maps cells by **real column letter** (`_colnum`) instead of document order — sparse rows no longer shift. Bottom Plate real file still parses (regression-checked).
- **⚠ The Bottom Plate inspection file CHANGED during this session** (OneDrive sync or a manual edit). It now reads **Material: Copper** (was Aluminum) and SL 1 (78→78.04/78.06), SL 4 (108→108.05/108.06) and one more are **measured out of tolerance** → closed loop now grades Bottom Plate **16/19, outcome FAIL** (was 19/19 PASS). Parser is reading it faithfully — the source data flipped. **User must confirm which inspection version is authoritative.**
- Ran `closed_loop.py "Part 2…" --start 2026-09-09T03:30:00Z --end 2026-09-09T13:00:00Z` → wrote Part 2's `job.json` (9-Sep window) + `closed_loop_record.json`. **8/8 CAM operations have telemetry** (the full-day 9-Sep capture covers the whole job — first time). Then `closed_loop.py --parts-root "…/Dataset/Krishna"` → **2-part `krishna_report.html`** with the part selector: Bottom Plate (8/16 ops, QC 16/19, FAIL) + RKSE-004-053 (8/8 ops, QC 0/0 incomplete until its map/template are filled). KB now 24 rows / 2 parts, 21 rule groups.
- **Next for Part 2:** fill its `job.json` (workholding, confirm the 9-Sep window) and real QC values + `operation_qc_map.json` via the Inputs tab (part selector picks RKSE-004-053), then re-run `--parts-root`.

### feed_override is LIVE as of 9 Sep (2026-09-10)

- **The operator feed-override knob is now a real field** (`feed_override`, a *field* not a tag). 9-Sep: 14,219 samples, values **0–200%**, genuinely varying. On 4 Sep it wasn't sent at all. Probe: `scratchpad/krishna_override_check.py` (also lists all tag/field keys).
- **CORRECTED 2026-09-11 — the "also new fields" note above was wrong.** `program_runtime` / `production_time` / `program` / `tool_name` / `tool_number` showed up in a `schema.measurementFieldKeys()` listing (no `machine_id` filter) and were misread as new on Krishna. Re-checked with STM filtered explicitly on 9 Sep: **0 samples** for 4 of the 5; `tool_number` present but constant `0` (same dead state as always). Re-checked with no machine filter over 7 days: **all five are real, but on `jyotiVMC` (TS), not STM** — `program` streams live raw G-code block text, `tool_name` gives real names (`'6-EM'`), `tool_number` real turret positions (`'12'`), `program_runtime`/`production_time` are working incrementing counters. **Nothing changed on Krishna.** TS's controller is far richer than STM's Smart Connect (no program-name tool-parsing workaround needed there, runtime counters work) — parked, not pursuing TS now. Scripts: `scratchpad/krishna_newfields_check.py` (STM-filtered, found nothing), `scratchpad/krishna_newfields_recent.py` (unfiltered, found the TS data).
- **Pipeline switched to it:** default `--override-field` → `feed_override` in `krishna_metrics.py`; `closed_loop.load_telemetry` SimpleNamespace `override_field="feed_override"`. `config.override_is_proxy` now False → the "proxy in use" warning in Data gaps stops showing.
- `_override_stats` rewritten: **clamps to 0–300** (odd samples put commanded-feed values like 3656 in that register), and the "active" figures **exclude both the 100% default and 0** (0 = knob not feeding, between moves) → `median_active` / `min_active` / `max_active` describe what the operator actually dialled. New `_merge_override(runs, key)` rolls per-run stats to the operation.
- Operation objects gained `spindle.override` + `feed.override` (full stats); `closed_loop` records gained `actual.feed_override` `{min,max,median,events,n,constant}`.
- Report: **"Feed ovr" column** in the Per-operation detail table (`ovrCell()` — "100% (flat)" / "10–150% (med 150)" / "—" when not captured).
- **First real override read (RKSE-004-053, 9 Sep):** roughing pushed hard (`1_10end_ruf` 10–150% med 150; `2_10end_1` 10–200% med 140), rest-rough backed off (`2_4end_ruf` med 90), the ball-nose 3-D finish run slow (`3_4boll` 10–90% med 50), one op left at 100% flat (`3_4end`), drilling slowed (`4_1cd` med 20, `5_3.2drill` med 60). This is the direct operator-intent signal the closed loop was missing.

### machine_mode decoded → Manual/MDI time split out of Stopped (2026-09-11)

User asked whether the machine notes manual cutting or buries it in "stopped." Answer: it was buried — `bucket_time()` only ever checked `machine_state`, and manual jogging reads state 2 (hold) same as a real pause. Decoded `machine_mode` to fix it (probe `scratchpad/krishna_machine_mode_check.py`, checked against 2 known 4-Sep manual-jog stretches vs 2 known auto-cutting stretches): **0 = AUTO/MEM** (every confirmed cutting sample read 0); **10 = sustained JOG/MDI** (minutes-long, matches both known manual sessions exactly); **6/7 = brief transitional blips** around a mode switch; **12 = the G91 G28 reference-return rapid** every program opens with. Not official Mitsubishi documentation — inferred from data, flagged as such everywhere it's used.
- `krishna_metrics.py`: `MANUAL_MODES = {6,7,10,12}`. `bucket_time()` now only reclassifies samples that would've been "stopped" (state 0/2) — checks `machine_mode` first, manual → new `manual_s` bucket, else → `stopped_s`. Never touches cutting/air. Propagated through `run_metrics` → `build_operations` → `machine_metrics` → `build_parts` → `fetch_period_breakdown` (all now carry `manual_s`).
- Report: new **"Manual / MDI" Summary tile** (indigo, new `hand` icon) between Stopped and Setup/load; Stopped tile's hint now says it excludes manual time; new **"Manual" column** in Per-operation detail; `DEFS.manual` + updated `DEFS.stopped`.
- Direct answer to the user's question: if an operator hand-feeds a cut during a jog/MDI session, it's real material removal but is **never counted as Cutting** (no program is tracking it) — it now lands in the new Manual/MDI bucket instead of silently inflating Stopped, which is the most honest place for it without inventing a false cutting number.

### job.json `excluded_runs` — exclude a misattributed telemetry run from one part's analysis (2026-09-11)

User: the late-day `1_10end` (11:49) and `2_10end_1` (12:00) runs on Top Plate were actually a **different part** reusing the same program names (~5pm IST, after Top Plate was essentially done) — remove them from Top Plate's analysis but keep them in the overall machine summary.
- New `job.json` key **`excluded_runs`**: `[{program_name, start, reason}]`, exact program name + telemetry start time (from the closed-loop flags / console output). Added to `_JOB_TEMPLATE` with a `_README` note so it's discoverable for future parts, not a one-off hack.
- `assemble_part`: builds `records_ops` = `tele["operations"]` minus anything matching an `excluded_runs` entry; passes a **shallow-copied** `tele` (`{**tele, "operations": records_ops}`) into `build_records` only. The real `tele` — and everything downstream of it (machine-level Summary tab, Part-by-part, periods) — is untouched, so excluded runs still count toward the whole-window machine metrics, exactly as asked. Console logs how many were excluded.
- Applied to Top Plate: `1_10end`'s record now represents its legitimate 04:32 run (no more "also ran later" flag); `2_10end_1` now correctly shows **no telemetry** for Top Plate (its only occurrence was the other part) rather than being misattributed. `operations_with_telemetry` dropped 8→7.
- Also noted in passing: the user has since filled `operation_qc_map.json` for Top Plate (6 operations mapped to SL dims) — **part_outcome is now FAIL** (2/9 dims out of tolerance: SL1 "54" marginally over by 0.01 mm, SL8 the "Ø4.4 tapped hole" mismatch flagged earlier). Real result, not a pipeline artifact.

### Operation order & silently-dropped telemetry runs FIXED (2026-09-11)

User asked why Top Plate's operation order didn't read `1_10end, 2_10end_1, 3_4end…` — investigated and found the order is (by design) real telemetry start-time order, not the CAM numbering — and the shop floor genuinely didn't run them 1,2,3 that day (`1_10end` ran at 04:32 **and again** at 11:49; `1_10end_ruf` ran 7th, after several finish ops). But investigating surfaced two real bugs:
1. **`run_order` dict was name-keyed** → when a program ran twice, the second run's index silently overwrote the first's, so the report showed run-order 10 next to run-order-2's-era data for `1_10end` (an internal inconsistency).
2. **`match_op` picked only the first telemetry match** for a CAM file → any earlier, non-consecutive run of the same program was silently discarded, and **3 real telemetry operations on Top Plate (`4_1CD_1.TAP`, `1_10END_1.TAP`, `4_3.2DRILL`) don't match any CAM filename at all and were vanishing from the report with no trace** (`4_3.2DRILL` vs the CAM file `5_3.2drill` — different prefix; the other two aren't in the CAM folder under any name — possibly machine-side duplicate saves, aborted attempts, or genuinely missing CAM files).
- **Fixed:** `match_op` → `match_ops` (returns all matches); `build_records` now keys run-order by object identity, picks the **most recent** run as the operation's representative (consistent with the shop's own skim-to-final pattern), flags any earlier run in the record's `flags` ("this program also ran earlier (HH:MM:SSZ) — only the most recent run's numbers are shown above"), and returns `(records, unmatched_ops)`. `assemble_part` prints unmatched ops to console, adds `summary.unmatched_telemetry_ops` (count) and `closed_loop.unmatched_telemetry_ops` (full list: name/start/end/cutting_s) to both `closed_loop_record.json` and the report payload.
- Report: new **warnbox in the closed-loop section** listing any unmatched runs by name with their cutting time, so they're visible instead of invisible. Top Plate currently shows 3 (`4_1CD_1` 0s cutting/26min — likely another manual-jog session, now caught by the Manual/MDI fix above; `1_10END_1` 0s cutting/46min — same; `4_3.2DRILL` 361s cutting/8min — genuinely unaccounted, worth checking against the CAM folder).
- Verified: `1_10end`'s record now shows run_order 10 consistent with its own (11:49) data, and correctly flags the 04:32 run; unmatched list correctly drops to 3 (was 4 before a follow-up fix to also mark earlier-but-matched runs as accounted-for).

### Log-coverage % bug FIXED (2026-09-11)

User: Top Plate window 8h23m, tooltip said "8h01m sampled", so why did the tile read 67.5% not ~96%? Root cause found: `uptime_coverage_pct` / period-breakdown `coverage_pct` were computed as **`100 * samples / window_span_s`** — i.e. samples-per-second vs an implicit 1 Hz baseline. Krishna samples at ~0.6–0.8 Hz even when perfectly healthy (never near 1 Hz), so this metric structurally topped out around 60–80% regardless of data quality — while the tile's own hover tooltip and the `DEFS.coverage` text both already documented the *intended* formula (`100% − untracked÷window`), which the code never actually implemented. Code didn't match its own spec.
- **Fixed** in `krishna_metrics.py` (`machine_metrics()` + `fetch_period_breakdown()`): `coverage_pct` is now `100 * (span - untracked_s) / span` — matches the tooltip. Added a separate `sample_rate_hz` field (samples ÷ span) so the "under 1 Hz" fact is still visible, just not conflated with coverage.
- Template: `views()` passes `sample_rate_hz` through; the Log-coverage tile's hover now appends "· avg N samples/s"; `DEFS.coverage` rewritten to state the real formula and explicitly warn coverage ≠ samples/sec.
- **Verified after fix:** Bottom Plate 93.3% (was a low-70s%-style number under the old formula), Top Plate **95.6%** (matches the user's manual 8h01m/8h23m math), sample rates 0.76 Hz / 0.68 Hz shown separately. No other `coverage_pct` usages affected (field-health's per-field send-rate `coverage_pct` at two other call sites is a different, unrelated metric — untouched).

### Workholding photos + Part-2 rename (2026-09-10)

- Part 2 folder renamed by the user → **`NAS PC CPU Top Plate (2026-09-09)`** (RKSE-004-053, the companion to the Bottom Plate). `--parts-root` discovers by content, so the rename needs no code change.
- **`closed_loop.py` embeds workholding photos:** `_load_workholding_photos(part_dir)` finds images in a `Workholding/` subfolder (or `*workhold*`-named files), downscales to ≤1100 px wide / JPEG q70 via Pillow, base64 data-URIs them into `closed_loop.workholding_photos = [{name, data_uri, kb}]` so they travel inside the self-contained report.
- **Report:** `setupsCard()` renders a photo strip (210 px thumbnails, click → full size in new tab) under the setup blocks in the Step-by-step tab.
- Top Plate: 2 WhatsApp photos embedded (142 + 107 KB after downscale; report now ~620 KB). They show the part on a **drilled aluminium sub-plate, two step/strap clamps on studs** (one each side) clamping the edges down — flood coolant. Set `job.json` `workholding.type = "strap clamps on sub-plate"` + detail on both setups from the photos (user can refine via Inputs tab).

- **Inputs tab — QC coverage check + clearer finish:** `updateQcCoverage()` renders a live line at the bottom of the Per-operation card — "N / 19 dimensions mapped", any un-mapped SL numbers shown as red chips, plus which SLs are mapped to more than one op. Recomputes on every chip toggle / field change. Added a bordered **"Finish — save these to the part folder"** card at the bottom with the two Download buttons (there is no submit — `file://` page; entries autosave to localStorage). Download buttons switched to `data-act` so the top and bottom copies both work.

- **Still to build: `program_trace.py`** — generate the above from data instead of hand-writing: unwrap block_number (int16) → split cycles → strip MDI prefix → join sample↔`.tap` block → phase rows (plunge/lead/cut/link: prog vs actual F&S), per-pass drift rows, override-profile (knob vs drift), alarm-position buckets, per-op "logged from block N of M" coverage. Phase-split feed replaces the blended `feed_median` in the closed-loop table.
- **OPEN QUESTION raised by user 2026-09-08: part identity / quantity.** Right now a job = a hardcoded `--start/--end` window + a `--part-gap-hours` cluster; nothing ties a telemetry span to "part SE-004-052, qty 1". Recommended answer: a per-part **`job.json` manifest** in the part folder (`part_id`, `part_name`, `quantity`, `machine`, `runs: [{start,end,note}]` — supports a job spanning multiple sessions/days, `cam_dir`, `qc_file`) as the source of truth; `closed_loop.py` reads it instead of CLI dates; `build_parts` stays as fallback. Plus **auto-detect repeated full program sequences** (`1_→2_→…→8_` repeating N× back-to-back = N parts) to sanity-check quantity / split multi-part runs. Long-term self-describing fix: operator names the first program of each job with the part number. NOT yet built — awaiting go.

Generated artifacts (`shop_knowledge.jsonl`, `krishna_metrics.json`, `krishna_report.html`, per-part `closed_loop_record.json` + `operation_qc_map.json`) — consider `.gitignore`.

**RESOLVED 2026-09-07 — `machine_state` vs the derived buckets (cross-tab `scratchpad/krishna_state_vs_bucket.py`):**
- **Cutting** (80 min): 100% state 3. **Air/rapid** (6 min): 99% state 3. Both cleanly = running.
- **Paused mid-cycle** (22 min) by the counter-only method: **only 62% state 2, 35% state 3, 2% state 0** — and the state-3 slice has rpm median 4500 / feed 899 (i.e. it's actually *cutting*, mis-labelled because two samples landed in the same controller-second and read equal counters). So the counter-only "paused" **over-counted by ~1/3**.
- Inverse: whenever the machine says state 2, the counters agree it's a pause 99% of the time. → **`machine_state` is NOT redundant; state 2 is the clean "stopped" signal.**
- **Setup** ≈ 0 in the per-second cross-tab because `cycle_time` never hits 0 between programs on this machine AND idle time is under-sampled (>10 s gaps skipped). The ~13 min of inter-op idle is real, captured at the operation level via wall-clock.

**→ The bucketing is now STATE-AWARE (backend `getBreakdown`, `krishna_metrics.py run_metrics`, and the report):**
`cutting` = running (canon state 1) AND `cutting_time` advanced · `air/positioning` = running AND `cutting_time` flat · `stopped` = state 2 or 0 · `untracked` = gap > 10 s (collector not sampling, reported so totals are honest) · `setup/load` = a run segment where `cycle_time` never advanced (operation-level only). `paused_s`/`paused_pct` keys are gone → `stopped_s` + `untracked_s`. `_canon_state()` helper added to the py. Ratio denominators are now `cutting + air` (running time), not `cutting + air + paused`.

Frontend `MachineBreakdown` tiles updated: Window · Log coverage · Utilisation · Cutting · Air/positioning · **Stopped** · **Untracked**, + state-distribution row. All syntax/offline-tested; not yet deployed.

**BUILT 2026-09-07 (repo root, standalone-script convention like `influx_job_linkage.py`):**
- **`krishna_metrics.py`** — pulls STM telemetry, segments into runs, computes machine + per-run metrics, writes `krishna_metrics.json` + `krishna_report.html`. Handles: MM·SS `cycle_time` decode, seconds `cutting_time`, 4-way run segmentation (program change / >300 s gap / cycle_time backwards), program-name tool parser, cutting-vs-air-vs-paused bucketing (walks consecutive sample pairs, dt capped at 10 s to ignore collector gaps), and a **`field_health()` check that classifies every expected field as ok / misleading / sparse / constant / absent** — so the report is self-updating: when Krishna fixes a register, the field moves from the bottom section to the top on its own. `--override-field` flag defaults to `rapid_override` (the proxy), swap to `feed_override` when available.
- **`krishna_report_template.html`** — self-contained report (no CDN, opens from `file://`). Python injects the JSON at the `/*__DATA__*/null` placeholder. **Band 1 = what the machine tells us** (stat tiles, auto-generated insights, stacked cutting/air/paused per operation, wall-clock timeline, RPM + feed bar charts, full per-operation table). **Band 2 = what it does NOT give us** — every dead field with status pill, why it costs us, and how to fix it. Light/dark themed. Palette = dataviz skill slots 1/2/3, validator-passed both modes (light-mode aqua contrast WARN covered by direct labels + the table view).
- Offline-tested (`scratchpad/test_krishna_metrics.py`): MM·SS decode incl. the 759→800 boundary, 11/11 program names parsed correctly, segmentation, time bucketing 39/15/5, template injection, JS syntax, injected-JSON parse. **Not yet run against live InfluxDB** (sandbox blocks it — user runs it).
- `production_count` deliberately NOT reported as parts (user: "park it" — one physical part was made in the 4-Sep window; the M30 counter logic is unknown).

---

## Session 13 (2026-10-05) — Admin flow: mockup → real React preview

**Mockup (reviewed, v7):** https://claude.ai/artifact/J8DNCEZFxvAqyNBNDs3A5H — clickable admin flow, iterated tab by tab. PRD: https://claude.ai/artifact/5V7VBc3FyrEytG7sF9ciCz

**Ported to React — repo `shiaanx-frontend-admin`, branch `feature/admin-flow-preview`, commit `e9c58b8` (LOCAL ONLY, not pushed, not deployed):**
- New folder `src/proto/` — `ProtoApp.js` (shell + routes), `fixtures.js` (ALL data; anonymised — Client A–F, PN-1052; real telemetry/QC numbers), `ProtoDataContext.js`, `proto.css`, `components/`, `pages/` (EnquiriesOrders, EnquiryDetail incl. trial-job branch, OrderDetail, Customers, PartWorkspace, ProductionBoard, CamPrograms, ClosedLoop [6 tabs], Inspection, Factory, Settings).
- Route `/proto/*` added in `src/App.js`, OUTSIDE `ProtectedRoute` (no login). Existing pages untouched.
- `scripts/deploy-preview.js` + `npm run deploy:preview` — builds with `PUBLIC_URL=/shiaanx-frontend-admin` and publishes to a `gh-pages` branch → `https://shiaanx.github.io/shiaanx-frontend-admin/#/proto`. `--build-only` flag skips the publish. `homepage: "/admin"` left alone for the developer's server (13.233.172.143 — not touched).
- CSS gotcha: CRA bundles every stylesheet globally and the live app styles bare elements (`select` with `!important` in TrackOrder.css; `label`, `th`, `td`, `h1`, `p`) and classes `.sidebar/.topbar/.nav-item/.icon-btn/.modal-overlay/.btn-primary/.stat-card`. Proto versions of those classes are prefixed `px-`, and `proto.css` has a reset block at the top.
- Verified: 53/53 Playwright checks against the subpath build (`scratchpad/proto_test.py`), `/#/login` still renders, no horizontal scroll at 390px. Only console error is the pre-existing missing favicon.
- Run locally: `npm start` in the repo → `http://localhost:3000/admin#/proto`.

**Waiting on user:** (1) go-ahead to push the branch and run `deploy:preview`; (2) after the first publish, enable Pages once — repo Settings → Pages → Deploy from branch → `gh-pages` / root. The Pages site will be public (repo is public), hence anonymised fixtures.

**Not committed in that repo (user's own changes, leave alone):** `src/pages/PublicAnalytics.js`, `src/services/telemetryService.js`.

**Still open:** real backend calls (pages read only from `fixtures.js`); real 3D viewer in Part Workspace (placeholder — wire in the labeling_app viewer); nothing persists across reload; demo Step 4 photo; retag balloons 12/13; repo home for the labeling_app demo work (uncommitted on `feature/fixture-viewer`); CLAUDE.md AD-007 still has the old personal `shiaanx-backend` URL.

---

## Session 13b (2026-10-23) — Admin flow on a real backend + shared dev server (dev.shiaanx.com)

Supersedes the "waiting on user / GitHub Pages" notes above: the Pages preview is dropped (the screens now need a backend).

**Backend — `siddhantg2311/shiaanx-backend`, branch `feature/production-flow-api` (PUSHED; `main` untouched). Local worktree: `ShiaanX/shiaanx-backend-flow`.**
- Migration `32-add-production-flow.js` (additive only): users phone/website/designation; enquiries assembly_name/job_type/status_before_order; orders reverted_at; enquiry_parts sort_order/production_stage/machine/plan_summary/capp_job_id/qc_job_id; enquiry_documents slot/is_current/client_visible/note/storage_key; materials available_finishes; new tables enquiry_part_revisions, tools, machines.
- API `/api/v1/admin/flow` (admin JWT): bootstrap (rows in the frontend's row shape), enquiries create/update (revision history)/patch/convert/revert/no-order, documents upload/patch/delete/file (auth download, files under FLOW_STORAGE_DIR not /uploads), parts patch + `generate-cam` (proxies CAPP_URL), customers, settings (users with logins, materials, finishes, tools, machines).
- Fixed existing bug: user_id generator reused a soft-deleted user's id (paranoid:false).
- Tests: `scratchpad/flow_api_test.mjs` 53/53 incl. real CAPP run.

**Frontend — `ShiaanX/shiaanx-frontend-admin`, branch `feature/admin-flow-preview` (PUSHED; `main` untouched).** `src/proto/` now uses the API (`api.js`, `ProtoDataContext.js`): login gate, no sample switch, shared data, refresh every 20 s + on tab focus, routes by row uuid. `db.js` (IndexedDB) removed. Env: `REACT_APP_API_URL`, `REACT_APP_QC_URL` (empty = same origin). UI E2E `scratchpad/dev_env_ui_test.py` 33/33 locally, 36/36 through the full stack.

**Dev server stack — `ShiaanX/dev-env/` (NOT in git yet; proposed home: shiaanx-backend `deploy/`, awaiting user).** Built by 2 agents + overseer + final checker. docker compose: db, backend, capp (micromamba + pythonocc), qc (labeling app, CPU torch), nginx (frontend build + basic-auth gate + `sx_gate` cookie, routes, register blocked, 500m uploads), certbot (profile https). Scripts: `deploy.sh` (tar + scp to /opt/shiaanx-dev, keeps server .env), `enable-https.sh` (LE email optional), `create-admin.js` (no default seeded admin). Images build from WORKING TREES (uncommitted labeling_app edits ship).
- Server: EC2 i-0a04a338dbf73ba30, 65.2.120.75, `ssh -i ~/.ssh/shiaanx-dev.pem ubuntu@65.2.120.75`. DNS dev.shiaanx.com → 65.2.120.75 (Wix). Server `.env` generated on the server; site (basic-auth) login saved locally at `~/.ssh/shiaanx-dev-site-login.txt`.

**Open:** dev-env git home; labeling_app changes' git home (CAPP repo, uncommitted); copy existing users from the old DB (needs a dump — don't touch 13.233.172.143); PR + heads-up to Harsh when ready to merge; CLAUDE.md AD-007 URL.

**Update 2026-10-23 (later):** site-wide basic auth removed. Each person uses their own app login; nginx `auth_request` checks the `sx_session` cookie (backend `/api/v1/flow-session`) on QC, closed-loop report, /uploads and POST /api/v1/uploads. Admin routes materials/finishes/processing-technologies/telemetry now require admin login. `dev-env/` moved into the backend repo at `shiaanx-backend-flow/deploy/dev-env` (committed, pushed). Deploy now: `bash shiaanx-backend-flow/deploy/dev-env/scripts/deploy.sh` from the ShiaanX folder. SSH to the server is IP-restricted in the shiaanx-dev security group; update "My IP" when the home IP changes. No users to migrate from the old system (confirmed by user).

**Update 2026-10-27 — UI feedback round 1 deployed** (deck: Downloads/UI Feedback.pptx, 12 slides). Built by 5 parallel agents + overseer + final checker (all suites green). Live on dev.shiaanx.com: processes per part (10 seeded, Settings → Processes) + filters; New-enquiry draft autosave (IndexedDB); extra reference docs per part/project; 3D viewer tools (views, display modes, bounding box, measure) + /proto/view3d/:fileKey; Documents received grouped by part; partial orders (pick parts at Convert, "Not ordered", Add parts to order); manual quote history; Repeat order → `<no>_R1`, `_R2` (linked to root); Complaints & Feedback (card per job + sidebar page); Delivered stage + filter; CAM Programs/Board show only ordered parts with project links. Migrations 33 (other session: unique editable enquiry numbers) + 34 ran on the server. Pre-deploy backups on server: ~/backups/*pre-feedback1-20261027-103450*. SSH to the server is IP-restricted and the user's IP changes often — update the shiaanx-dev security group (or set Anywhere) when deploys time out.

---

## Investor demo build — 2026-11-04 (branch `demo/investor-nov`, uncommitted)

Live 10-min demo of the founder's flow, all screens in `/proto` (shiaanx-frontend-admin, branch `demo/investor-nov`) backed by `capp_service` (port 8001). DFM + quote computed by Rohit's v3 planner offline (`capp_service/v3_adapter.py` + `v3_runner.py`, v3 cloned at `Documents/shiaanx_v3_standalone`, env `occ_env`); program generation = v3 + PowerMill. Primary part Motor Mount (Al 6061), backup Rekise RKSE-004-057.
- Run sheet: `demo_backup/DEMO_RUN_SHEET.md`; v3 notes: `demo_backup/V3_DEMO_NOTES.md`; flow backend starter: `demo_backup/start_flow_backend.ps1`.
- Motor Mount quote: ₹4,008/unit @ qty 40 (252.6 min = 249.6 v3 cutting + 12 × 15 s ATC tool changes; ₹700/hr real, 25% margin placeholder); manual quote ₹3,897.
- Open: PowerMill bridge needs admin registration + pre-run backup project; Gemini credits depleted (reply assistant); board uses 69.8 min/part (TS program) vs quote 252.6; local flow DB has junk test orders; inventory/supplier data still `sample: true`.

---

## Dev deploy 2026-11-05 (about 22:50 IST)

Demo build deployed to dev.shiaanx.com (working tree, branch demo/investor-nov, uncommitted). capp now ships demo_modules, saved v3 analyses (Motor Mount, Rekise, Heat Sink D1), a Motor Mount/Rekise data pack, V3_DISABLED=1; nginx route /capp/ behind the session cookie; frontend built with REACT_APP_CAPP_API_URL=/capp. Verified: server-layout simulation 16/16, nginx -t, compose config, unit tests, prod build, post-deploy health (capp healthy, /capp/* = 401 without login). Rollback + Gemini-key steps: demo_backup/DEV_ROLLBACK.md. Open: Gemini key on server (founder), RIB1 analysis still running, commit both repos.
