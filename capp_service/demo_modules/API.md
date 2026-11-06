# capp_service demo endpoints: API contract

Five endpoints on the FastAPI app in `capp_service/main.py` (port 8001). The logic lives in
`capp_service/demo_modules/`. Every number comes from one of these:

- real part data: STEP geometry, v3 analysis, shop NC programs, the QC inspection report, or the real quotation xlsx
- a labelled data file in `capp_service/demo_data/`:
  - `rates.json`: machine rate ₹700/hr and tool change 15 s (shop ATC) are real. Margin 25% is a placeholder.
  - `inventory.json` and `suppliers.json`: every entry is `"sample": true` until the team replaces them.

CORS is `allow_origins=['*']`, which covers `http://localhost:*` and `https://dev.shiaanx.com`. No credentials are needed.

## Job creation (existing endpoint, extended)

`POST /jobs` takes multipart `step_file` (required), `part_name` (optional) and `material` (optional).
It returns right away with `{job_id, part_name, original_filename}`. The CAPP pipeline, the v3 analysis
and the CMM geometry extraction then run in background threads.

- If `part_name` is omitted, it defaults to the uploaded file's stem. `job.json` stores `original_filename`.
- `part_data.find_part_dir` maps a job to `Claude output for program sheet/Manufactured parts/<Part>/`
  by normalised name. Normalising lowercases the name and keeps only alphanumerics:
  - `MOTOR MOUNT.step` maps to the `Motor Mount` folder
  - `RKSE-004-057.stp` maps to the `Al extrusion mount (Rekise)` folder

## How v3 runs (applies to `/dfm` and `/quote`)

- The first request, or job creation, starts `v3_adapter.run_v3_analysis()` in a background thread.
  The adapter keeps a cache keyed by STEP sha256 + v3 commit, so re-uploading the same STEP is instant.
  A fresh part takes about 10–35 minutes.
- The result is also copied to `jobs/<id>/v3_analysis.json`.
- Responses while v3 is in progress:
  - while it runs: HTTP 200 `{"status":"running","started_s_ago":12.3}`. The UI should poll.
  - adapter missing: HTTP 503 `{"status":"unavailable","error":"v3 analysis not available","reason":...}`
  - v3 failed: HTTP 500 `{"status":"failed","error":"v3 analysis failed","detail":...}`. To re-run, call `GET /jobs/{id}/dfm?retry=true`.
- Every ready response carries `v3_origin`: `"v3_adapter"`, or `"sample_fixture"` only when the env
  var `SHIAANX_V3_SAMPLE=1` is set for local testing.

---

## 1. `GET /jobs/{id}/dfm`

`{status, source:"v3", setups_needed, unreachable_mm3, directions[], findings[{severity:"ok"|"warn"|"block", title, detail, evidence}], forced_small_tools[], holes[], summary{verdict, counts, text, billet_mm, part_bbox_mm}}`

Fields beyond the contract: `engine_notes[]` (v3's own caveats, verbatim), `thresholds{}`, `v3_origin`, `v3_runtime_s`.
The findings are sorted with `block` first, then `warn`, then `ok`.

The thresholds are named constants at the top of `dfm.py`:

| Check | Severity |
|---|---|
| Unreachable volume ≤ 1 mm³ | ok (treated as noise) |
| Unreachable volume > 100 mm³ **and** > 1% of removal volume | block |
| Unreachable volume in between | warn |
| Setups > 3 | warn |
| Setups > 6 | block |
| Forced tool smaller than 1 mm | block |
| Any other forced small tool | warn |
| Hole L/D > 5 | warn |
| Hole L/D > 10 | block |
| Hole diameter < 1 mm | warn |
| No standard drill for a hole | warn |
| Removal > 85% of billet | warn |
| v3 failed to extract holes | warn ("Hole check not run") |

### Face-level DFM (added; all fields above are unchanged)

```
"face_count": int | null,            // B-rep faces in the job STEP; assert == occt-import-js brep_faces total
"categories": [
  {"id": "small_internal_corner", "label": "Small radius internal corner(s)",
   "severity": "block|warn|info",     // worst item in the category
   "color": "#D55E00", "count": int, "why": "one sentence",
   "items": [{"id": "small_internal_corner-1", "severity": "block|warn|info",
              "label": "Internal corner (2.85, 0.00)",
              "detail": "Expected minimum radius 2.85 mm, actual 0.00 mm ...",
              "measured": {...}, "expected": {...},
              "face_indices": [12, 13],          // [] = part-level (no faces to colour)
              "centroid_mm": [x, y, z] | null}]}
],
"geometry_error": string | null,     // face-level analysis failed; v3 findings still returned
"summary": {..., "face_level_counts": {"block", "warn", "info"}}
```

**Face numbering.** `face_indices` are 0-based in `TopExp_Explorer(shape, TopAbs_FACE)` order over the
job's STEP (`GET /jobs/{id}/step`). That is the order of `meshes[*].brep_faces` in occt-import-js 0.0.23,
concatenated over meshes in order. occt-import-js emits one mesh per solid and every face, including
untriangulated ones. It is also the order `*_features.json` uses. Parity was checked by running
occt-import-js in Node on both test STEPs: Motor Mount has 1096/1096 faces and RKSE-004-057 has 71/71.
Each face's area-weighted triangle centroid matches the B-rep centroid at the same index (worst case
0.45 mm, on one badly tessellated spline face).

**Verdict.** If a v3 finding is a blocker, the verdict is "Not manufacturable as-is on 3-axis". If only
face-level items are blockers, it is "Manufacturable on 3-axis after design changes". If there are any
warnings, it is "Manufacturable with notes".

Categories appear in this fixed order, with fixed colours (Okabe-Ito + Paul Tol, colour-blind safe).
Empty categories are omitted. The thresholds are constants in `dfm_geometry.py` and are echoed in
`thresholds.face_level`. Setup (tool) directions come from v3's planned setups plus its hole-drilling
directions.

| id | colour | rule (aluminium, 3-axis VMC) | severity |
|---|---|---|---|
| `small_internal_corner` | #D55E00 | Concave partial cylinder with its axis along a tool axis and r < max(0.5, depth / (2 × L/D 4)). Also any sharp concave wall-to-wall edge (interior angle ≤ 150°) along a tool axis that no setup can cut as a floor/wall step | warn; block if r < 0.5 mm or sharp |
| `non_standard_radius` | #E69F00 | A floor fillet (tangent to a setup floor, or a concave torus blend) or a vertical corner of R ≤ 10 mm whose radius is not within 0.02 mm of {0.2, 0.25, 0.5, 0.75, 1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10}. Grouped by radius | warn for floor fillets, info for vertical corners |
| `flat_bottom_hole` | #0072B2 | Full 360° concave cylinder, Ø ≤ 20 mm, closed by a single-loop plane (not a counterbore shoulder) | warn |
| `deep_hole` | #332288 | Hole depth / Ø > 5 | warn; block above 10 |
| `non_standard_hole` | #56B4E9 | Ø ≤ 20 mm and more than 0.02 mm off a DIN 338 size (0.1 mm steps to 13 mm, 0.5 mm to 20 mm). Reports the v3 drill and a possible ISO tap-drill match | warn; info if it is a tap-drill size with no v3 second op |
| `non_perpendicular_face` | #009E73 | Plane whose normal is neither parallel nor perpendicular (±0.5°) to any tool axis, and which is not a chamfer | warn |
| `thin_wall` | #F0E442 | Opposed planes facing away from each other with material between them (solid-classified), < 1.0 mm apart, overlapping by ≥ 0.5 mm² | warn; block if < 0.5 mm |
| `external_edge_fillet` | #CC79A7 | Convex round with R ≤ 6 mm that is not a vertical profile corner. Grouped by radius | info |
| `chamfer` | #882255 | Narrow (≤ 3 mm) tilted plane with only convex edges, or a convex-edged cone (hole edge). Grouped by size and angle | info |
| `engraving` | #44AA99 | A connected patch of ≥ 20 free-form faces, plus the small faces inside its box (lettering / logo). These faces are excluded from every other check | warn |
| `small_tool_region` | #999999 | v3 `forced_small_tools`. Part-level, so `face_indices: []` | warn |
| `unreachable_volume` | #661100 | v3 `unreachable_mm3` > 1 mm³. Part-level | warn; block if > 100 mm³ and > 1% of removal |

The facts are cached in `<job>/dfm_geometry.json`, keyed by the STEP's sha256. The first extraction
takes about 6 s for Motor Mount (1096 faces) and about 1 s for Rekise. It is warmed in the background
on the first `/dfm` call.

## 2. `GET /jobs/{id}/quote?qty=1&material=aluminium_6061`

`{status, machining{total_minutes, cutting_minutes, tool_change_minutes, tool_change_s, tool_change_basis:"atc"|"v3_total", v3_total_minutes, v3_tool_change_minutes, by_setup[], by_tool[], tool_changes}, setup_minutes, setups, rates{machine_inr_per_hr, margin_pct, tool_change_s, ...}, material{grade, billet_mm, required_stock_mm, density_g_cm3, blank_kg, price_inr_per_kg, inventory_item|null, in_stock, supplier|null{name, city, lead_days, price_inr_per_kg, sample}}, cost{material_inr, machining_inr, setup_inr, setup_batch_inr, subtotal_inr, margin_inr, unit_price_inr, qty, total_inr}, lead_time_days{material, machining, qc, dispatch, qc_dispatch (=qc+dispatch, kept for older readers), total (=material+machining+qc+dispatch; excludes the queue wait, which the app adds from the production board), machine_hours}, assumptions[], previous_manual_quote|null, calibration_note|null, v3_origin}`

**Cost** (INR per unit unless a field says otherwise):

- cycle minutes = v3 cutting minutes (sum of `plan.setups[].cutting_minutes`) + `plan.tool_changes` × `rates.tool_change_s` / 60.
  v3's own `plan.total_minutes` prices each tool change at 15 min (manual change); the shop VMC has an
  automatic tool changer at 15 s, so that figure is kept only as `machining.v3_total_minutes` and an assumption line.
  If v3 gives no cutting/tool-change split, `plan.total_minutes` is used (`tool_change_basis:"v3_total"`).
- `machining_inr` = cycle minutes / 60 × machine rate
- `setup_inr` = setups × 30 min × rate / qty. This is a one-time batch cost spread over the quantity. The un-split batch figure is `setup_batch_inr`.
- `material_inr` = blank kg × ₹/kg, where the blank is the v3 billet + 3 mm on each dimension
- `margin_inr` = margin % × subtotal

**Stock choice:** the smallest inventory item of that grade that contains the blank. If none fits, the
fastest supplier for the grade (cheapest breaks ties).

**Lead time** = material days (0 if in stock) + machining days + QC/dispatch days.
Machining days = ⌈(setup min + qty × cycle min) / 60 / (8 h × 85%)⌉.

**Comparison with the real quote:**

- `previous_manual_quote` is parsed live from `Quotation/*.xlsx`. Customer name and contact are not returned.
- `cycle_time_references` puts the quoted cycle (`quoted_cycle`) and v3's own total (`v3_plan`) next to every real shop program for the part. Each program's minutes are read from its own files:
  - PowerMill `.tap` files: feed-move length / F
  - Sinumerik `.MPF` files: the sum of the programmer's `;time =` header lines
  - For Motor Mount, the two shop programs differ by about 7× (496.5 and 69.8 min/part).
- `calibration_note` states:
  - the price at the manual quote's qty, against the manual unit price
  - the v3 minutes against each shop program, side by side

  It makes no claim about which figure is "right". No fudge factor is applied.
- `engine_notes[]` holds all of v3's warnings. The ones that affect price or time (drilling not priced, predicted stock, FINFLAT unmeasured, ~2x time model) are also copied into `assumptions`.
- v3 face order: `part_data.V3_FACE_ORDER` maps Motor Mount to `+Z,-Z,-Y` (the real programmer's settings). Every other part, Rekise included, uses greedy order (None). Rekise's greedy order is already `-Y,+Y`.

`material` accepts `aluminium`, `aluminium_6061`, `aluminium_6063`, `aluminium_6082`, `aluminium_7075`,
`aluminium_2024`, and also forms such as `Al 7075`. `qty` must be 1–100000, otherwise HTTP 400.

## 3. `POST /jobs/{id}/reply-draft`

Body: `{client_comment, topic:"price"|"lead_time"|"tolerance"|"finish", qty?, material?}`
Returns: `{draft, grounded_on:[fact strings], model:"gemini-2.5-flash-lite"}`

This is an internal tool for the ShiaanX team. It calls the Gemini REST API with `requests`, using
`GEMINI_API_KEY` from the process env, or from the Windows user env if the process doesn't have it.
The prompt only allows facts from:

- this job's quote, at `qty` (default 1)
- the DFM findings
- the drawing tolerances from the part's inspection report

Errors (none of them return canned text):

| Status | When |
|---|---|
| 503 | `price` or `lead_time` asked before the quote exists |
| 409 | No facts available at all |
| 502 | Missing key or Gemini failure. The body is `{error, grounded_on}`, so the UI can still show the facts. |
| 422 | Bad topic |

## 4. `GET /jobs/{id}/cmm`

`{status:"ok"|"needs_tolerances", tolerance_source, datum_source, datums[{label, face_index, type, normal, centroid, area_mm2, points[]}], features[{id, type, nominal, tolerance{plus,minus}, probe_strategy, points[{xyz, ijk}], characteristic, kind, matched, geometry, cad_nominal_mismatch, shop_instrument}], visual_checks[], program_format:"DMIS-like", program_text, count, matched_count, total_points}`

**Geometry:** read with PythonOCC from the job's STEP. Face indices follow TopExp order, the same as the
Datum Tagger. Points are sampled on the trimmed face. `ijk` is the outward surface normal. The extraction
takes about 30 s once, then is cached in `cmm_geometry.json`.

**Tolerances**, first source that has data wins:

1. job `tolerances.json`, keyed by the job's cluster_id
2. part-folder `tolerances.json`
3. the real QC report `Inspection Report/*.xlsx`, which holds the drawing characteristics

**Datums**, first available wins:

1. job `datums.json`
2. part-folder `*.datums.json`, used only if its `step_file_hash` matches the job's STEP
3. an auto 3-2-1 frame built from the largest perpendicular planes. This case is labelled in `datum_source`.

**Matching characteristics to geometry:**

- A diameter matches a full bore (arc ≥ 180°) whose CAD Ø is within tolerance. Points are a 4-point ring at mid-depth.
- A linear dimension matches two opposed parallel planes whose separation is within tolerance (3 + 3 points). If there are none, it falls back to the overall extent.
- If CAD differs from the drawing by more than the tolerance but by less than 0.5 mm, the feature still matches and has `cad_nominal_mismatch:true`.
- If nothing matches, the feature has `matched:false` and an empty `points` list.

If there are no tolerances anywhere, the response is `status:"needs_tolerances"` with a `missing[]` list (for example the Rekise part).

## 5. `GET /jobs/{id}/tracking`

`{status, available, actual_available, part_folder, source{planned, actual, telemetry_linked, actual_record?}, thresholds_pct, ops[{op, tool, setup, planned{rpm, feed_mm_min, minutes}, actual{rpm, feed_mm_min, minutes, ...}|null, deviations[{field, planned, actual, pct, flag}], flagged, note, nc_file}], summary{ops, ops_with_actual, flagged, planned_minutes, actual_minutes, planned_minutes_same_ops, qc_in_tolerance, v3_plan_minutes?}, qc{source, dimensions, in_tolerance, items[]}|null}`

The comparison is the program that was sent to the machine against what the machine actually did. The CAPP pipeline is not used.

| Side | Source |
|---|---|
| Planned | The real NC program, one op per toolpath file, parsed with `closed_loop.parse_tap`: programmed S, dominant cutting F, and minutes = feed-move path length / F. |
| Actual, first choice | Machine telemetry from the Krishna closed-loop records (closed-loop repo `krishna_metrics.json`, InfluxDB `cnc-data-v2`): rpm median, feed median, and cutting minutes taken from `machine_state`, never from the broken `cutting_time`. Covers SE-004-052 and RKSE-004-053. |
| Actual, second choice | `machine_data.json` in the job or part folder (output of `influx_job_linkage.py`). |
| Actual, when neither exists | `actual:null`. `source.actual` explains why, and `actual_available:false`. |
| `qc` | The real final-inspection report: measured values against drawing tolerance, scored strictly. |

**Motor Mount:**

- No machine is linked to the collector, so every op has `actual:null`.
- `qc` shows 8 of 13 dimensions in tolerance.
- `override_log.json` and `actual_process.json` are **not** used as the actual side. Both are parsed from the same NC programs: they record differences between CAPP and the program, not how the machine behaved.

**Other parts:**

- Flag thresholds: rpm ±15%, feed ±15%, minutes ±30%.
- A part with neither NC programs nor telemetry returns `available:false` with a `reason`. Rekise RKSE-004-057 is one: its part folder has only a PowerMill project.
- `summary.v3_plan_minutes` is the quoted AI cycle (v3 cutting + ATC tool changes), given as a separate reference; `summary.v3_raw_total_minutes` is v3's own total with 15-min manual tool changes.

---

## Real example responses (Motor Mount job, trimmed: lists cut to the first items)

### 1. GET /jobs/{id}/dfm

```json
{
 "status": "ok",
 "source": "v3",
 "setups_needed": 3,
 "unreachable_mm3": 851.6,
 "directions": [
  {
   "dir": "+X",
   "workplane": "XMAX_WP",
   "machinable_mm3": 111824.2,
   "machinable_mm3_reach_analysis": null,
   "clamp_area_mm2": 652.8,
   "jaw_reach_mm": 53.35,
   "best_tool": "EM_2FL_8MM",
   "recommended": false,
   "setup_order": null
  },
  {
   "dir": "-X",
   "workplane": "XMIN_WP",
   "machinable_mm3": 111498.4,
   "machinable_mm3_reach_analysis": null,
   "clamp_area_mm2": 652.8,
   "jaw_reach_mm": 53.35,
   "best_tool": "EM_2FL_8MM",
   "recommended": false,
   "setup_order": null
  }
 ],
 "findings": [
  {
   "severity": "warn",
   "title": "852 mm³ hard to reach",
   "detail": "A small volume is unreachable from the analysed directions — likely corner/undercut regions; confirm with the drawing whether it is functional.",
   "evidence": {
    "unreachable_mm3": 851.6,
    "removal_volume_mm3": 147765.9,
    "unreachable_pct_of_removal": 0.576
   }
  },
  {
   "severity": "warn",
   "title": "Small tool forced: EM_2FL_3MM (Ø3 mm)",
   "detail": "+Z: only this 3 mm cutter reaches 6,022 mm3 of stock / 178 mm2 of surface that no larger tool in the plan reaches (53.2 min, finishing at 8.0 mm2/min) Small cutters run slow and break easily — opening up the internal radius / slot width would cut cycle time.",
   "evidence": {
    "tool": "EM_2FL_3MM",
    "dia_mm": 3.0,
    "minutes": 23.8,
    "reason": "+Z: only this 3 mm cutter reaches 6,022 mm3 of stock / 178 mm2 of surface that no larger tool in the plan reaches (53.2 min, finishing at 8.0 mm2/min)"
   }
  },
  {
   "severity": "warn",
   "title": "90% of the billet becomes chips",
   "detail": "High material removal — consider near-net stock (extrusion / thinner plate) to cut material cost and cycle time.",
   "evidence": {
    "billet_mm": [
     59.346,
     108.795,
     25.516
    ],
    "billet_volume_mm3": 164745,
    "removal_volume_mm3": 147765.9,
    "removal_pct": 89.7,
    "part_volume_mm3": 16979.343
   }
  },
  {
   "severity": "warn",
   "title": "Drilling not priced in the plan",
   "detail": "The offline v3 run does not price drilling; holes are left to end mills or unreached, so hole time is not in the cycle time.",
   "evidence": {
    "source": "v3",
    "warning": "22 CAD holes found; drilling is NOT priced offline - v3 only drills holes PowerMill's recognition agrees with, which needs the bridge. The plans leave holes to the end mills or unreached"
   }
  },
  {
   "severity": "warn",
   "title": "Later setups planned on predicted stock",
   "detail": "Setups after the first are costed against v3's predicted remaining stock, not measured stock — times for those setups are less certain.",
   "evidence": {
    "source": "v3",
    "warning": "setups after the first are costed against v3's PREDICTED stock (billet minus the swept reach of the tools chosen before), not PowerMill's measured live stock - a live run re-plans after every cut"
   }
  },
  {
   "severity": "warn",
   "title": "22 holes need a second operation",
   "detail": "UNDERSIZE by 0.20 mm: hole Dia 3.20 drilled with Dia 3.00 - leaves 0.100 mm on radius to open out later; UNDERSIZE by 0.50 mm: hole Dia 3.00 drilled with Dia 2.50 - leaves 0.250 mm on radius to open out later; UNDERSIZE by 0.53 mm: hole Dia 2.53 drilled with Dia 2.00 - leaves 0.264 mm on radius to open out later (+1 more)",
   "evidence": {
    "holes": 22,
    "notes": [
     "UNDERSIZE by 0.20 mm: hole Dia 3.20 drilled with Dia 3.00 - leaves 0.100 mm on radius to open out later",
     "UNDERSIZE by 0.50 mm: hole Dia 3.00 drilled with Dia 2.50 - leaves 0.250 mm on radius to open out later",
     "UNDERSIZE by 0.53 mm: hole Dia 2.53 drilled with Dia 2.00 - leaves 0.264 mm on radius to open out later",
     "UNDERSIZE by 1.00 mm: hole Dia 11.00 drilled with Dia 10.00 - leaves 0.500 mm on radius to open out later"
    ]
   }
  },
  {
   "severity": "ok",
   "title": "3 setups on a 3-axis vise",
   "detail": "Setup count is within normal range for a 3-axis VMC.",
   "evidence": {
    "setups_needed": 3,
    "recommended_directions": [
     "+Z"
    ]
   }
  }
 ],
 "forced_small_tools": [
  {
   "tool": "EM_2FL_3MM",
   "reason": "+Z: only this 3 mm cutter reaches 6,022 mm3 of stock / 178 mm2 of surface that no larger tool in the plan reaches (53.2 min, finishing at 8.0 mm2/min)"
  }
 ],
 "holes": [
  {
   "dia_mm": 2.529,
   "depth_mm": 2.5,
   "dir": "-Z",
   "drill": "DRILL_2.0MM",
   "through": true,
   "notes": [
    "UNDERSIZE by 0.53 mm: hole Dia 2.53 drilled with Dia 2.00 - leaves 0.264 mm on radius to open out later"
   ]
  },
  {
   "dia_mm": 2.529,
   "depth_mm": 2.5,
   "dir": "-Z",
   "drill": "DRILL_2.0MM",
   "through": true,
   "notes": [
    "UNDERSIZE by 0.53 mm: hole Dia 2.53 drilled with Dia 2.00 - leaves 0.264 mm on radius to open out later"
   ]
  }
 ],
 "engine_notes": [
  "setup order = greedy cover of the planner's own jaw-capped sweep masks (stop when a face adds < 759 mm3, 0.5% of the stock to remove); v3 itself leaves the face order to the operator",
  "faces planned in the operator's order +Z,-Z,-Y; the greedy cover would have chosen +Y,-Y,+Z"
 ],
 "summary": {
  "verdict": "Manufacturable with notes",
  "counts": {
   "block": 0,
   "warn": 6,
   "ok": 1
  },
  "billet_mm": [
   59.346,
   108.795,
   25.516
  ],
  "part_bbox_mm": [
   55.345,
   104.795,
   21.516
  ],
  "text": "Manufacturable with notes: 0 blocker(s), 6 warning(s), 1 check(s) passed."
 },
 "thresholds": {
  "unreachable_noise_mm3": 1.0,
  "unreachable_block_mm3": 100.0,
  "unreachable_block_frac": 0.01,
  "setups_warn": 3,
  "setups_block": 6,
  "small_tool_warn_mm": 3.0,
  "small_tool_block_mm": 1.0,
  "hole_ddr_warn": 5.0,
  "hole_ddr_block": 10.0,
  "removal_frac_warn": 0.85
 },
 "v3_origin": "v3_adapter",
 "v3_runtime_s": 2080.1
}
```

### 2. GET /jobs/{id}/quote?qty=40&material=aluminium_6061

At qty 1 the same part is ₹5,288/unit; at qty 2, ₹4,631/unit.

```json
{
 "status": "ok",
 "machining": {
  "total_minutes": 252.6,
  "cutting_minutes": 249.6,
  "tool_change_minutes": 3.0,
  "tool_change_s": 15,
  "tool_change_basis": "atc",
  "v3_total_minutes": 429.6,
  "v3_tool_change_minutes": 180.0,
  "by_setup": [
   {
    "dir": "+Z",
    "workplane": "ZMAX_WP",
    "minutes": 191.8,
    "cutting_minutes": 101.8,
    "tool_change_minutes": 90.0,
    "tool_changes": 6,
    "left_mm3": 69035.8,
    "unfinished_mm2": 405.0,
    "jaw_reach_mm": 19.516,
    "stock": "raw billet",
    "plan_s": 1370.3
   },
   {
    "dir": "-Z",
    "workplane": "ZMIN_WP",
    "minutes": 200.3,
    "cutting_minutes": 140.3,
    "tool_change_minutes": 60.0,
    "tool_changes": 4,
    "left_mm3": 10793.8,
    "unfinished_mm2": 192.0,
    "jaw_reach_mm": 19.516,
    "stock": "v3-predicted stock after the previous setup(s)",
    "plan_s": 312.8
   },
   {
    "dir": "-Y",
    "workplane": "YMIN_WP",
    "minutes": 37.5,
    "cutting_minutes": 7.5,
    "tool_change_minutes": 30.0,
    "tool_changes": 2,
    "left_mm3": 1667.8,
    "unfinished_mm2": -3.0,
    "jaw_reach_mm": 102.795,
    "stock": "v3-predicted stock after the previous setup(s)",
    "plan_s": 69.1
   }
  ],
  "by_tool": [
   {
    "tool": "FACEMILL_63MM",
    "dia_mm": null,
    "minutes": 0.7,
    "role": "face",
    "setup": "+Z"
   },
   {
    "tool": "EM_2FL_16MM",
    "dia_mm": 16.0,
    "minutes": 8.5,
    "role": "restrough",
    "setup": "+Z",
    "mm3": 58303.4
   },
   {
    "tool": "EM_2FL_16MM",
    "dia_mm": 16.0,
    "minutes": 23.1,
    "role": "finish",
    "setup": "+Z",
    "mm2": 4831
   }
  ],
  "tool_changes": 12
 },
 "setup_minutes": 90,
 "rates": {
  "machine_inr_per_hr": 700,
  "margin_pct": 25,
  "setup_minutes_per_setup": 30,
  "shift_hours_per_day": 12,
  "machine_utilization_pct": 85,
  "qc_days": 1,
  "dispatch_days": 1,
  "stock_allowance_mm": 3,
  "tool_change_s": 15,
  "sample_fields": [
   "margin_pct",
   "setup_minutes_per_setup",
   "shift_hours_per_day",
   "machine_utilization_pct",
   "qc_days",
   "dispatch_days",
   "stock_allowance_mm"
  ]
 },
 "material": {
  "grade": "aluminium_6061",
  "billet_mm": [
   59.346,
   108.795,
   25.516
  ],
  "required_stock_mm": [
   62.3,
   111.8,
   28.5
  ],
  "density_g_cm3": 2.7,
  "blank_kg": 0.536,
  "price_inr_per_kg": 435,
  "inventory_item": {
   "id": "INV-AL6061-PL-40",
   "grade": "aluminium_6061",
   "temper": "T651",
   "form": "plate",
   "dims_mm": [
    40,
    250,
    400
   ],
   "qty": 1,
   "price_inr_per_kg": 435,
   "location": "Rack A3",
   "sample": true
  },
  "in_stock": true,
  "supplier": null
 },
 "cost": {
  "material_inr": 233.15,
  "machining_inr": 2947.0,
  "setup_inr": 26.25,
  "setup_batch_inr": 1050.0,
  "subtotal_inr": 3206.4,
  "margin_inr": 801.6,
  "unit_price_inr": 4008.0,
  "qty": 40,
  "total_inr": 160320.0,
  "currency": "INR",
  "excludes": [
   "GST 18%",
   "shipping"
  ]
 },
 "lead_time_days": {
  "material": 0,
  "machining": 17,
  "qc": 1,
  "dispatch": 1,
  "qc_dispatch": 2,
  "total": 19,
  "machine_hours": 169.9
 },
 "setups": 3,
 "assumptions": [
  "Cycle time = 252.6 min/part: v3 cutting time 249.6 min (v3 tool/strategy simulation; v3 notes its time model runs ~2x conservative) + 12 tool changes × 15 s on the shop's automatic tool changer (3.0 min).",
  "v3's own total is 429.6 min/part: the v3 default assumes 15 min per manual tool change (180.0 min); shop ATC = 15 s per change.",
  "Machine rate ₹700/hr (3-axis VMC, real rate).",
  "Margin 25% — placeholder, edit demo_data/rates.json.",
  "Setup 30 min (placeholder) × 3 setup(s), one-time per batch, amortised over qty 40.",
  "Blank = v3 billet + 3 mm per dimension; density 2.7 g/cm³.",
  "Lead time (placeholders): 12 h shift at 85% utilisation, QC 1 day(s) + dispatch 1 day(s); queue wait for the machine is added by the app from the live board.",
  "Inventory and supplier entries are SAMPLE data until replaced.",
  "Excludes GST, shipping, CAM programming, special inspection, surface treatment.",
  "v3: 22 CAD holes found; drilling is NOT priced offline - v3 only drills holes PowerMill's recognition agrees with, which needs the bridge. The plans leave holes to the end mills or unreached",
  "v3: +Z EM_2FL_16MM: 2892.0 mm2 of floor priced at offset-flat (FINFLAT), never measured; if PowerMill declines it the raster fallback alone is 29.3 min, not 23.1",
  "v3: -Z EM_2FL_8MM: 3159.0 mm2 of floor priced at offset-flat (FINFLAT), never measured; if PowerMill declines it the raster fallback alone is 117.4 min, not 75.0",
  "v3: setups after the first are costed against v3's PREDICTED stock (billet minus the swept reach of the tools chosen before), not PowerMill's measured live stock - a live run re-plans after every cut",
  "v3: v3's own time model is ~2x (planner.py docstring); each tool change is priced at 15 min"
 ],
 "previous_manual_quote": {
  "source_file": "Claude output for program sheet/Manufactured parts/Motor Mount/Quotation/Q_SX_2627_007.xlsx",
  "quote_date": "2026-05-28",
  "quote_id": "Q_SX_2627_007",
  "dispatch_terms": "4-5 weeks from the date of the PO",
  "part_name": "Motor Mount",
  "material": "Al 6063",
  "qty": 40,
  "unit_price_inr": 3897,
  "line_total_inr": 155880,
  "model_unit_price_at_same_qty_inr": 4008.0,
  "delta_pct": 2.8
 },
 "calibration_note": "Price: at the manual quote's qty (40) this model gives ₹4,008/unit vs the manual ₹3,897/unit (+3%); manual quote material was Al 6063, this quote uses aluminium_6061. Cycle time: quoted 252.6 min (249.6 v3 cutting + 3.0 ATC tool changes; v3's own total with 15-min manual changes is 429.6 min) vs real shop programs for this part — Shop program A: PowerMill NC (part folder): 496.5 min/part over 3 setups (feed-move toolpath length / programmed feed, summed over all .tap files); Shop program B: Sinumerik MPF (TS machine): 69.8 min/part over 4 setups (sum of the programmer's ';time =' header lines). The shop programs themselves differ by ~7.1×.",
 "cycle_time_references": {
  "quoted_cycle": {
   "total_minutes": 252.6,
   "cutting_minutes": 249.6,
   "tool_change_minutes": 3.0,
   "basis": "v3 cutting + tool changes at 15 s (ATC)"
  },
  "v3_plan": {
   "total_minutes": 429.6,
   "cutting_minutes": 249.6,
   "tool_change_minutes": 180.0,
   "setups": 3
  },
  "shop_programs": [
   {
    "label": "Shop program A: PowerMill NC (part folder)",
    "source": "Claude output for program sheet/Manufactured parts/Motor Mount/CAM Program/ncprograms/ncprograms",
    "setups": 3,
    "files": 20,
    "by_setup": [
     {
      "setup": "1st setting",
      "minutes": 204.7
     },
     {
      "setup": "2nd setting",
      "minutes": 275.3
     },
     {
      "setup": "3rd setting",
      "minutes": 16.5
     }
    ],
    "minutes_per_part": 496.5,
    "basis": "feed-move toolpath length / programmed feed, summed over all .tap files (rapids, tool changes, load/unload excluded)"
   },
   {
    "label": "Shop program B: Sinumerik MPF (TS machine)",
    "source": "G:/My Drive/Closed Loop/Clean Data/Motor Mount_TS/CAM files_TS",
    "setups": 4,
    "files": 4,
    "by_setup": [
     {
      "setup": "MOTOR_MOUNT_1_SETUP..MPF",
      "minutes": 33.93
     },
     {
      "setup": "MOTOR_MOUNT_2_SETUP..MPF",
      "minutes": 26.2
     },
     {
      "setup": "MOTOR_MOUNT_3_FINISH_SETUP..MPF",
      "minutes": 3.55
     },
     {
      "setup": "MOTOR_MOUNT_4_SETUP..MPF",
      "minutes": 6.1
     }
    ],
    "minutes_per_part": 69.8,
    "basis": "sum of the programmer's ';time =' header lines (CAM-estimated machining time; load/unload and changeovers excluded)"
   }
  ],
  "shop_programs_spread_x": 7.1
 },
 "engine_notes": [
  "setup order = greedy cover of the planner's own jaw-capped sweep masks (stop when a face adds < 759 mm3, 0.5% of the stock to remove); v3 itself leaves the face order to the operator",
  "faces planned in the operator's order +Z,-Z,-Y; the greedy cover would have chosen +Y,-Y,+Z",
  "22 CAD holes found; drilling is NOT priced offline - v3 only drills holes PowerMill's recognition agrees with, which needs the bridge. The plans leave holes to the end mills or unreached",
  "clamp_area_mm2 is the vise-jaw contact band from v3's hold plan (grip depth x held length on the billet), not a flat-face area",
  "+Z EM_2FL_16MM: 2892.0 mm2 of floor priced at offset-flat (FINFLAT), never measured; if PowerMill declines it the raster fallback alone is 29.3 min, not 23.1",
  "+Z EM_2FL_3MM finishes at only 8.0 mm2/min (23.8 min)",
  "+Z: 511 mm2 of curved surface no ball nose in the plan finishes - a flat cutter steps it",
  "-Z EM_2FL_8MM: 3159.0 mm2 of floor priced at offset-flat (FINFLAT), never measured; if PowerMill declines it the raster fallback alone is 117.4 min, not 75.0",
  "-Z: 337 mm2 of curved surface no ball nose in the plan finishes - a flat cutter steps it",
  "-Y: 32 mm2 of curved surface no ball nose in the plan finishes - a flat cutter steps it",
  "setups after the first are costed against v3's PREDICTED stock (billet minus the swept reach of the tools chosen before), not PowerMill's measured live stock - a live run re-plans after every cut",
  "v3's own time model is ~2x (planner.py docstring); each tool change is priced at 15 min"
 ],
 "v3_origin": "v3_adapter"
}
```

### 3. POST /jobs/{id}/reply-draft (HTTP 502 today: the Gemini key's prepaid credits are depleted)

```json
{
 "error": "Gemini returned HTTP 402: Your prepayment credits are depleted. Please go to AI Studio at https://ai.studio/projects to manage your project and billing. Learn more at https://ai.google.dev/gemini-api/docs/billing#prepay. ",
 "grounded_on": [
  "Quoted unit price ₹4,008 at qty 40 (material ₹233, machining ₹2,947, setup ₹26/unit, margin 25%), excl. GST & shipping.",
  "Machining time 429.6 min/part across 3 setup(s) on a 3-axis VMC at ₹700/hr.",
  "Material aluminium_6061, blank [62.3, 111.8, 28.5] mm, in stock (INV-AL6061-PL-40).",
  "Lead time 45 working days = material 0 + machining 43 + QC/dispatch 2.",
  "Our earlier manual quote Q_SX_2627_007 was ₹3,897/unit at qty 40 (Al 6063), dispatch 4-5 weeks from the date of the PO.",
  "DFM: Manufacturable with notes: 0 blocker(s), 6 warning(s), 1 check(s) passed."
 ]
}
```

### 4. GET /jobs/{id}/cmm

```json
{
 "status": "ok",
 "part_folder": "Motor Mount",
 "tolerance_source": "drawing characteristics from Motor Mount/Inspection Report",
 "datum_source": "auto 3-2-1 (no datums tagged: largest mutually-perpendicular planes)",
 "datums": [
  {
   "label": "A",
   "face_index": 6,
   "type": "plane",
   "normal": [
    0.0,
    0.0,
    -1.0
   ],
   "centroid": [
    -0.014,
    -7.7888,
    0.0
   ],
   "area_mm2": 3194.093,
   "points": [
    {
     "xyz": [
      0.0,
      -7.4385,
      0.0
     ],
     "ijk": [
      0.0,
      0.0,
      -1.0
     ]
    },
    {
     "xyz": [
      -13.9333,
      -60.5265,
      0.0
     ],
     "ijk": [
      0.0,
      0.0,
      -1.0
     ]
    },
    {
     "xyz": [
      -20.9,
      19.1055,
      0.0
     ],
     "ijk": [
      0.0,
      0.0,
      -1.0
     ]
    },
    {
     "xyz": [
      20.9,
      19.1055,
      0.0
     ],
     "ijk": [
      0.0,
      0.0,
      -1.0
     ]
    }
   ]
  }
 ],
 "features": [
  {
   "id": "CH01",
   "type": "circle_inner",
   "nominal": 16.1,
   "tolerance": {
    "plus": 0.2,
    "minus": 0.2
   },
   "probe_strategy": "4-pt bore circle at mid-depth, LSQ fit, report DIAM",
   "points": [
    {
     "xyz": [
      7.1711,
      -54.6,
      6.1575
     ],
     "ijk": [
      -0.89082,
      -0.0,
      -0.45435
     ]
    },
    {
     "xyz": [
      -7.1711,
      -54.6,
      -1.1575
     ],
     "ijk": [
      0.89082,
      0.0,
      0.45435
     ]
    },
    {
     "xyz": [
      -2.8838,
      -54.6,
      10.0157
     ],
     "ijk": [
      0.35824,
      -0.0,
      -0.93363
     ]
    },
    {
     "xyz": [
      2.8838,
      -54.6,
      -5.0157
     ],
     "ijk": [
      -0.35824,
      -0.0,
      0.93363
     ]
    }
   ],
   "characteristic": "DIA 16.1 (drawing item 1)",
   "kind": "diameter",
   "shop_instrument": "Digital Vernier Caliper",
   "matched": true,
   "geometry": {
    "cad_value_mm": 16.1,
    "centre": [
     0.0,
     -54.6,
     2.5
    ],
    "axis": [
     0.0,
     -1.0,
     0.0
    ],
    "face_indices": [
     1037,
     1070
    ]
   },
   "cad_nominal_mismatch": false
  },
  {
   "id": "CH02",
   "type": "distance_plane_plane",
   "nominal": 45.75,
   "tolerance": {
    "plus": 0.2,
    "minus": 0.2
   },
   "probe_strategy": "3 pts on each of 2 opposed planes, report DISTB along normal",
   "points": [
    {
     "xyz": [
      27.5,
      0.0,
      1.5
     ],
     "ijk": [
      1.0,
      -0.0,
      0.0
     ]
    },
    {
     "xyz": [
      27.5,
      -6.2312,
      0.36
     ],
     "ijk": [
      1.0,
      -0.0,
      0.0
     ]
    },
    {
     "xyz": [
      27.5,
      6.2312,
      0.36
     ],
     "ijk": [
      1.0,
      -0.0,
      0.0
     ]
    },
    {
     "xyz": [
      -18.0,
      -65.7296,
      3.9
     ],
     "ijk": [
      -1.0,
      0.0,
      0.0
     ]
    },
    "...(2 more)"
   ],
   "characteristic": "45.75 (drawing item 2)",
   "kind": "linear",
   "shop_instrument": "Digital Vernier Caliper",
   "matched": true,
   "geometry": {
    "cad_value_mm": 45.5,
    "direction": [
     1.0,
     -0.0,
     0.0
    ],
    "face_indices": [
     40,
     1036
    ]
   },
   "cad_nominal_mismatch": true
  }
 ],
 "visual_checks": [
  {
   "description": "Dents",
   "instrument": "Visual"
  }
 ],
 "program_format": "DMIS-like",
 "program_text": "DMISMN/'MOTOR MOUNT - ShiaanX auto CMM program',05.2\nUNITS/MM,ANGDEG\nFILNAM/'MOTOR_MOUNT_CMM'\n$$ Generated from STEP geometry + drawing tolerances. Review before running on machine.\nD(MCS)=DATSET/MCS\nMODE/MAN\n$$ --- Datum alignment ---\nF(DAT_A)=FEAT/PLANE,CART,-0.0140,-7.7888,0.0000,0.0000,0.0000,-1.0000\nMEAS/PLANE,F(DAT_A),4\n  PTMEAS/CART,0.0000,-7.4385,0.0000,0.0000,0.0000,-1.0000\n  PTMEAS/CART,-13.9333,-60.5265,0.0000,0.0000,0.0000,-1.0000\n  PTMEAS/CART,-20.9000,19.1055,0.0000,0.0000,0.0000,-1.0000\n  PTMEAS/CART,20.9000,19.1055,0.0000,0.0000,0.0000,-1.0000\nENDMES\nDATDEF/FA(DAT_A),DAT(A)\nF(DAT_B)=FEAT/PLANE,CART,-0.0000,31.6770,1.7500,0.0000,1.0000,0.0000\nMEAS/PLANE,F(DAT_B),4\n  PTMEAS/CART,0.0000,31.6770,1.7500,0.0000,1.0000,0.0000\n  PTMEAS/CART,-17.3848,31.6770,0.4200,0.0000,1.0000,0.0000\n  PTMEAS/CART,17.3848,31.6770,0.4200,0.0000,1.0000,0.0000\n  PTMEAS/CART,-11.5898,31.6770,3.0800,0.0000,1.0000,0.0000\nENDMES\nDATDEF/FA(DAT_B),DAT(B)\nF(DAT_C)=FEAT/PLANE,CART,-11.0000,-53.8500,9.2500,-1.0000,0.0000,0.0000\nMEAS/PLANE,F(DAT_C),4\n  PTMEAS/CART,-11.0000,-53.8500,9.2500,-1.0000,0.0000,0.0000\n  PTMEAS/CART,-11.0000,-39.2200,10.5800,-1.0000,0.0000,0.0000\n  PTMEAS/CART,-11.0000,-68.4800\n...",
 "count": 13,
 "matched_count": 13,
 "total_points": 80
}
```

### 4b. GET /jobs/{id}/cmm (Rekise, no tolerances)

```json
{
 "status": "needs_tolerances",
 "part_folder": "Al extrusion mount (Rekise)",
 "missing": [
  "No tolerances saved for this job (Inspection tab -> POST /jobs/{id}/tolerances)",
  "No tolerances.json with entries in the part folder",
  "No Inspection Report/*.xlsx with drawing characteristics in the part folder"
 ],
 "datums": null,
 "features": [],
 "program_format": "DMIS-like",
 "program_text": "",
 "count": 0
}
```

### 5. GET /jobs/{id}/tracking (Motor Mount, no telemetry link)

```json
{
 "status": "ok",
 "available": true,
 "actual_available": false,
 "part_folder": "Motor Mount",
 "source": {
  "planned": "NC programs sent to the machine: Claude output for program sheet/Manufactured parts/Motor Mount/CAM Program/ncprograms/ncprograms (programmed S/F; minutes = toolpath length / feed, rapids & tool changes excluded)",
  "actual": "No machine-run record linked to this part: it ran on a machine with no InfluxDB linkage, so per-op actuals are not available. override_log.json / actual_process.json are parsed from these same NC programs, so they are not used as \"actual\". The real outcome is the QC result below.",
  "telemetry_linked": false
 },
 "thresholds_pct": {
  "rpm": 15,
  "feed_mm_min": 15,
  "minutes": 30
 },
 "ops": [
  {
   "op": "1_12end_outer1",
   "tool": "Ø12 mm ENDMILL",
   "setup": 1,
   "planned": {
    "rpm": 3000,
    "feed_mm_min": 1000,
    "minutes": 17.55
   },
   "actual": null,
   "deviations": [],
   "flagged": false,
   "note": "no machine record for this op",
   "nc_file": "1st setting/1_12end_outer1.tap"
  },
  {
   "op": "2__12end",
   "tool": "Ø12 mm ENDMILL",
   "setup": 1,
   "planned": {
    "rpm": 3000,
    "feed_mm_min": 1000,
    "minutes": 69.09
   },
   "actual": null,
   "deviations": [],
   "flagged": false,
   "note": "no machine record for this op",
   "nc_file": "1st setting/2__12end.tap"
  }
 ],
 "summary": {
  "ops": 20,
  "ops_with_actual": 0,
  "flagged": 0,
  "planned_minutes": 496.47,
  "actual_minutes": null,
  "planned_minutes_same_ops": null,
  "qc_in_tolerance": "8/13",
  "v3_plan_minutes": 252.6,
  "v3_raw_total_minutes": 429.6
 },
 "qc": {
  "source": "Motor Mount/Inspection Report (shop final inspection, drawing tolerances)",
  "dimensions": 13,
  "in_tolerance": 8,
  "items": [
   {
    "sl_no": 1,
    "description": "Ø16.1",
    "kind": "diameter",
    "nominal_mm": 16.1,
    "tol_mm": [
     -0.2,
     0.2
    ],
    "measured": [
     16.01,
     16.02,
     16.03
    ],
    "in_tolerance": true,
    "worst_dev_mm": 0.09,
    "remark": "OK"
   },
   {
    "sl_no": 2,
    "description": "45.75",
    "kind": "linear",
    "nominal_mm": 45.75,
    "tol_mm": [
     -0.2,
     0.2
    ],
    "measured": [
     46.12,
     46.15
    ],
    "in_tolerance": false,
    "worst_dev_mm": 0.4,
    "remark": "As per cad ok"
   },
   {
    "sl_no": 3,
    "description": "104.78",
    "kind": "linear",
    "nominal_mm": 104.78,
    "tol_mm": [
     -0.3,
     0.3
    ],
    "measured": [
     104.79,
     104.8
    ],
    "in_tolerance": true,
    "worst_dev_mm": 0.02,
    "remark": "OK"
   }
  ]
 }
}
```

### 5b. GET /jobs/{id}/tracking (Rekise RKSE-004-057)

```json
{
 "status": "ok",
 "available": false,
 "part_folder": "Al extrusion mount (Rekise)",
 "reason": "No NC programs ('<Nth> setting/*.tap') or machine telemetry recorded for Al extrusion mount (Rekise)"
}
```



---

## 6. `GET /jobs/{id}/program`

The AI process plan and the CAM program for the job's part (module `demo_modules/program.py`). Always HTTP 200; `status` is `ok` when the v3 plan is ready, otherwise the v3 state (`running` / `unavailable` / `failed`) with `plan: null`.

```
{status, part, part_key,
 source: {plan, live_run},                       // file paths the values were read from
 approved: {by, at} | null,                      // <job_dir>/program_approval.json
 plan: {setups[{dir, workplane, minutes, cutting_minutes, tool_change_minutes, tool_changes, stock, jaw_reach_mm, left_mm3}],
        tools[{tool, dia_mm, minutes, role, setup, mm3?, mm2?}],
        total_minutes,          // v3's own total (15 min per manual tool change)
        cutting_minutes, tool_change_minutes, tool_change_min_each, tool_changes,
        cycle_minutes_atc,      // quote.cycle_minutes(): v3 cutting + tool_changes x rates.json tool_change_s, the quoted cycle
        cycle_basis, billet_mm, part_bbox_mm, requested_faces, face_order_source, warnings[]} | null,
 live_program: {available, run, status,
        toolpaths[{name, setup, setup_name, direction, tool, stage, role, strategy, workplane, rpm, feed_mm_min,
                   plunge_mm_min, stepdown_mm, stepover_mm, vc_m_min, fz_mm,
                   powermill_minutes,   // PowerMill 'TotalTime' of the toolpath (cut + links)
                   cutting_minutes, link_minutes, removed_mm3}],
        setups[{setup, name, direction, workplane, toolpaths, tools[], powermill_minutes, powermill_cutting_minutes,
                v3_planned_minutes, tool_changes, v3_planned_tool_changes, removed_mm3,
                vise{level, grip_axis, grip_axis_why, grip_depth_mm, jaw_gap_mm, jaw_reach_mm, clamp_clearance_mm, max_tool_dia_mm, held_on},
                stock_block_mm{XMin..ZMax}, first_planned_tools[], wall_minutes, started, finished}],
        powermill_cutting_minutes_total,        // sum of setups[].powermill_minutes
        powermill_minutes_basis, powermill_pure_cutting_minutes_total,
        toolpaths_tried, toolpaths_dropped_or_empty,
        billet{size_mm[3], allowance_mm_per_face, volume_mm3, part_bbox_mm, part_volume_mm3},
        final_stock_above_part_mm3, run_minutes, run_started, run_finished, step_import_seconds, v3_args[],
        project_path, project_decoded_from, images[{name, url}], sources[]} | null,
 notes[]}
```

Sources:
- `plan` is the job's cached v3 analysis (`v3_cache`, same face order as `/quote`).
- `live_program` comes from parts registered in `program.LIVE_RUNS`. Today that is Motor Mount only, read from `demo_backup/v3_motor_mount/`:
  - `live_events.ndjson` supplies the toolpaths, stages, tools, cutting params, vise/grip, stock block, billet and timings.
  - `run_folder/run_manifest.json` supplies the run status.
  - `pm_project_final_PRISTINE_copy` is decoded read-only with the repo's `pml_project.py` (strategy, workplane, feeds), plus each toolpath entity's `"TotalTime"`.

  The backup folder is never written to. Parts without a live run (for example Rekise) get `live_program: null` and a note.

Motor Mount values:
- **v3 plan:** 3 setups (+Z 191.8, −Z 200.3, −Y 37.5 min), `total_minutes` 429.6, 12 tool changes, `cycle_minutes_atc` **252.6**.
- **Live program:** 27 toolpaths. PowerMill time is +Z 213.0, −Z 57.5 and −Y 20.9 min, so `powermill_cutting_minutes_total` is **291.4**. Pure cutting-move time is 139.0 min.
- **Run:** `run_minutes` **81.7** (10:26:52 → 11:48:36).
- **Billet:** 59.34 × 108.8 × 25.52 mm (2 mm per face).

`GET /jobs/{id}/program/image/{name}` serves an image listed in `live_program.images[]`. Only image files inside that part's live-run folder can be served; anything else returns 404. The Motor Mount run saved no images, so `images` is `[]` (stated in `notes`).

`POST /jobs/{id}/program/approve` takes `{"by": "Siddhant"}` and returns `{"status":"ok","approved":{"by":"Siddhant","at":"2026-11-05T10:55:00+00:00"}}`. It writes `<job_dir>/program_approval.json`, and later GETs return it in `approved`. A blank `by` returns 400. The backend only records the approval; `/proto` moves the order status itself.

## 7. `GET /parts/{part_key}/production-history` and `GET /jobs/{id}/production-history`

Previous real production runs of the part (module `demo_modules/production_history.py`). `part_key` is any name form of the part: `motormount`, `Motor Mount` and `MOTOR_MOUNT` all match. The job variant resolves the part from the job.

```
{status, part_key, part, notes[],
 batches: [{id: "run1"|"run2", label, machine, program_type, setups, parts_made, parts[],
            program: {ops[{op, setup, tool, rpm, feed_mm_min, minutes, nc_file}], total_minutes, minutes_basis,
                      by_setup[]?, ops_minutes_sum?},
            qc: {dimensions, in_tol, close, out, checked_only, grading,
                 per_dimension[{dim, sl, nominal, tol[-,+], readings[], readings_by_part{P1:[..]}, notes, instrument, remark,
                                verdict: "in"|"close"|"out"|"checked"}]},
            defects_link: "/proto/closed-loop?view=defects&batch=run1|run2",
            sources[], snapshot: bool}]}
```

**Batch 1 (`run1`)** is read from the part folder:
- The NC programs in `CAM Program/ncprograms/<Nth> setting/*.tap` are parsed with `tracking._from_nc` (closed_loop.parse_tap). Minutes are feed-move length divided by programmed feed.
- QC comes from `Inspection Report/*.xlsx`.

**Batch 2 (`run2`)** is registered in `production_history.EXTERNAL_BATCHES` and read from `G:/My Drive/Closed Loop/Clean Data/Motor Mount_TS/`:
- Ops come from `CAM files_TS/*.MPF` (one file per setup, `MSG("<op> = h:mm:ss")` sections).
- The total is the sum of the programmer's `;time =` header lines.
- QC comes from `Inspection Report_TS/*.xlsx`.

If G: is unreachable, the response falls back to `capp_service/demo_data/production_history/motormount_run2.json`, a snapshot of the same files. That batch then has `snapshot: true`, the snapshot is listed in `sources`, and a note says so. To refresh the snapshot, run `python -m demo_modules.production_history motormount` from `capp_service/`.

QC grading is the same as `/proto` "Defects & why":
- Each reading is compared with nominal ± tol.
- A reading outside the band is `out`. One using ≥80% of its side of the band is `close`. Anything else is `in`.
- A dimension takes its worst reading.
- Visual or un-toleranced rows are `checked` and are not counted in `dimensions`.

Motor Mount values:

| Batch | Program | Setups | Parts | Minutes per part | QC (13 / 12 graded dims) |
|---|---|---|---|---|---|
| `run1` | PowerMill | 3 | 2 | 496.5, computed from the .tap path lengths | 6 in, 2 close, 5 out |
| `run2` | TS Sinumerik | 4 | 9 | **69.8**, the programmer's header times; 37 ops | 8 in, 0 close, 4 out |

A part with no history (for example Rekise) returns `{"status":"ok","batches":[],"notes":["No previous production run on record ..."]}`.

Full sample responses: the frontend worker's `program_samples/` scratch folder (`program_motor_mount.json`, `program_rekise.json`, `production_history_*.json`).

### 7a. `machine_data` on batch `run2` (controller log)

Batch `run2` of Motor Mount gains a `machine_data` block (module `demo_modules/telemetry_batch.py`). Other batches have no `machine_data` key. It is served **only** from the snapshot `capp_service/demo_data/production_history/motormount_run2_telemetry.json`; the endpoint never queries InfluxDB. The snapshot also records `fetched_at`, the decode used and every exact flux query.

```
machine_data: {available, source: "InfluxDB cnc_telemetry · ts/jyotiVMC", fetched_at, parts_inspected, method,
  setups: [{setup, program_name, recorded, not_recorded_reason?, first, last, samples,
            sessions: [{label, first, last, logging_sessions, full_cycles, median_cycle_minutes,
                        other_runs, repeated_short_runs[{minutes, count}], used_for_headline}],
            programmed_minutes, actual_machine_minutes, ratio, full_cycles, cycle_minutes_range[min,max],
            load_unload_median_minutes,
            spindle: {programmed_rpm, actual_median_rpm, at_programmed_pct, basis},
            feed_override: {median_pct, min_pct, max_pct, extreme_min_pct, extreme_max_pct,
                            off_default_pct, median_when_changed_pct, range_basis},
            state_split: {running_pct, hold_pct, manual_pct, idle_pct, alarm_pct,
                          cutting_pct: null, air_pct: null, logged_hours, running_minutes, manual_minutes, hold_events},
            interventions: {feed_hold_events, manual_minutes},
            headline}],
  summary: {headline_lines[3-4], note}}
```

- `actual_machine_minutes` is the median **full** cycle: a run whose start was seen (the Sinumerik `cycle_time` register resets) and whose controller cycle time reached at least 75% of the programmed `;time =` total. `ratio` = actual ÷ programmed.
- `cutting_time` is always 0 on jyotiVMC, so `cutting_pct` / `air_pct` are `null`. Time is split instead into running (AUTO, state 1), hold (state 2), manual (JOG/MDI) and idle (AUTO, state 0, i.e. load/unload). These are shares of **logged** time; the collector logs only while a program is loaded.
- The feed-override range counts only settings held for at least 1% of run time. `extreme_*` keeps the raw min and max.
- Lots more than 7 days apart are kept separate. The first lot (7–14 Jun) gives the headline numbers. The 4–5 Jul re-run of setups 1–2 is listed in `sessions` with `used_for_headline: false`.
- Setup 3 (finish) has `recorded: false`, because no matching program name is in the log.
- A missing snapshot returns `{available: false, reason}`.

Motor Mount values, snapshot of 2026-11-05:

| Setup | Programmed min | Real median min | Full cycles | Spindle at programmed S | Feed override (held) |
|---|---|---|---|---|---|
| 1 | 33.9 | 37.4 (+10%) | 18 | 97% | 95–105%, off 100% for 4% of run time |
| 2 | 26.2 | 28.5 (+9%) | 16, plus 15 runs of an 11.5-min version | 99% | 80–110%, 19% |
| 3 | 3.6 | not recorded | – | – | – |
| 4 | 6.1 | 7.1 (+17%) | 18 | 99% | 70–110%, 37% |

To refresh, run `python -m demo_modules.telemetry_batch refresh motormount` from `capp_service/`. It uses the closed-loop repo's `krishna_metrics` and `.env`, takes about 10 s, and writes atomically. Restart the service afterwards, or wait for the file-mtime cache to pick the new file up.


## POST /jobs/{id}/quote-pdf  (client quote PDF)

Body: `{customer, enquiry_number, part_name, qty, material, edits{unit_price_inr, total_inr, lead_days, validity_days, payment_terms, notes}, prepared_by, dfm_snapshot_png_base64?}`.
Returns `application/pdf` (A4). The route recomputes the quote and the DFM review from the job; only `edits` (price, lead time, validity, terms, notes) comes from the client. The PDF never contains margin, machine rate, cost breakdown, supplier or inventory names. Content: header + quote no., customer/part/qty/material, unit price and total (INR), lead time, validity, payment terms, notes, "Manufacturability review (DFM)" (verdict, counts, top findings, part size), the 3D snapshot if given, exclusions, footer. 409 while the analysis is still running.

## Quote edits contract (stored on the part's auto-quote by the UI)

`status` DRAFT|FINALIZED, `data = {_source:'capp_service', cappJobId, quote:<GET /quote response>, edits:{unit_price_inr, total_inr, lead_days, validity_days, payment_terms, notes, qty, material}, finalizedAt}`. `data.aiPlan` is preserved.

## Stock lists (quote material section)
The quote reads `demo_data/stock/inhouse_inventory.xlsx` and `supplier_directory.xlsx` directly (see `stock_lists.py` and `demo_data/stock/README.md`). `material.inventory_item` now carries `shape`, `size`, `pieces_per_item`, `items_needed`; `material.supplier` carries `supplier_id`, `shape`, `confidence`, `lead_days` (used), `lead_range` [min,max], `lead_basis` (`actual` | `planning estimate`), `verified`, `alternatives[]`. `material.price_is_sample` is true while `material_prices.json` is a placeholder.
