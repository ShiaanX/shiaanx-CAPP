# Program Sheet Validation — Motor Mount
**Date:** 2026-06-23  
**Branch at run:** main (post all chamfer/Z-level fixes)  
**STEP file:** `G:\My Drive\Closed Loop\Motor Mount_TS\input\MOTOR MOUNT.step`  
**Ground truth:** `motor_mount_ground_truth.json` (vendor CNC program, 37 ops, 4 setups)

---

## 1. Pipeline Run Status

All 9 stages completed successfully. One bug fixed during this session:

- **Bug fixed:** `setup_planning.py` line 1167 — `print_setup_summary()` crashed with  
  `TypeError: unsupported format string passed to NoneType.__format__`  
  when `wcs_origin_mm.x_mm` was `None` for angled setups.  
  Fix: `wo.get('x_mm') or 0` instead of `wo.get('x_mm', 0)`.

Pipeline wall time: ~20s (steps 2–9; step 1 re-used cached features from prior run).

---

## 2. Operation Count: Pipeline vs Vendor

| Metric | Pipeline | Vendor | Delta |
|--------|----------|--------|-------|
| Setups | **12** | **4** | +8 extra |
| Clusters/features | 100 | ~15 implied | over-segmented |
| Total operation steps | **187** | **37** | 5× more |
| Unique tool diameters | 12 | 8 | different set |

### Setup breakdown (pipeline)

| Setup | Axis | Clusters | Steps |
|-------|------|----------|-------|
| 1 | -Z (rear/bottom) | 70 | 128 |
| 2 | +Z (front/top) | 7 | 12 |
| 3 | +Y (top VMC position) | 6 | 10 |
| 4 | -Y (flipped bottom) | 5 | 9 |
| 5 | -X (left side) | 3 | 6 |
| 6 | +X (right side) | 2 | 4 |
| 7–12 | Angled (6 variants) | 1 each | 3 each |

### Vendor setups

| Setup | Description | Ops |
|-------|-------------|-----|
| 1 | Top face — main body roughing + all pockets/holes | 19 |
| 2 | Bottom face (flipped) | 11 |
| 3 | Re-clamp (same as 1) — finishing only | 3 |
| 4 | Side rotated — 16.1mm bore + 41.5mm deep slot | 4 |

**Root cause of setup explosion:** Setup planner creates one setup per unique feature axis direction. For a part with angled chamfers/bosses at 6 different angles, this produces 12 setups. A real machinist merges all features reachable from one clamping position into one setup.

---

## 3. Per-Feature Accuracy

### Features pipeline gets right (type and ops)

| Feature | Pipeline | Vendor | Match? |
|---------|----------|--------|--------|
| Through holes (small) | spot_drill → twist_drill | spot_drill → twist_drill | YES — correct sequence |
| Pockets | pocket_mill RF + FINISH | 8mm endmill RF + FINISH | YES — right sequence, wrong tool dia |
| Chamfers | chamfer_mill (4 clusters) | chamfer_mill (3 ops across 2 setups) | PARTIAL — count close, wrong dia/params |
| Planar faces | face_mill | face_mill (via dynamic roughing in vendor) | PARTIAL — pipeline uses large face mill dia |
| Counterbores | spot_drill → twist_drill → counterbore_mill RF+FINISH | spot_drill → twist_drill → endmill | YES — correct 4-step sequence |

### Features pipeline misses entirely

| Feature | Vendor ops | Pipeline | Impact |
|---------|-----------|----------|--------|
| Step/shoulder features | 8 ops (STEP-1, STEP-2 in setups 1–3) | Not classified; subsumed into boss/planar_face | HIGH — no step recognition |
| Floor radii / fillets | 5 ballnose ops (5mm R2.5, 3mm R1.5) | 0 ballnose ops | HIGH — no radius floor ops |
| Bull-nose edge fillets | 2 bull-nose ops (8mm R1) | 0 bull-nose ops | MEDIUM — no edge radius ops |
| Large bore (16.1mm, 37mm deep) | circular_interp RF + FINISH | Detected as `large_bore` → face_mill (wrong op!) | HIGH — wrong process for bore |
| Deep narrow slot (41.5mm deep) | long-reach 3mm endmill | Not detected | HIGH — not recognized |
| Dynamic roughing strategy | 2 dynamic-roughing ops | No equivalent | LOW — CAM strategy, not CAPP level |

### Boss over-detection
Pipeline found **24 boss clusters** → 48 contour_mill steps. Vendor has ~2 boss-like contour ops. The classifier is labelling external profile faces as individual "boss" clusters rather than recognising one outer-profile contour.

---

## 4. Tool Diameter Accuracy

| Tool | Pipeline selects | Vendor uses | In-range? |
|------|-----------------|-------------|-----------|
| Spot drill | 2mm (correct) | 2mm | YES |
| Small hole drill | 2.5mm, 3mm (correct) | 2.5mm, 3mm, 3.2mm | YES (3.2mm rounded to 3mm — flagged as SUBSTITUTION) |
| Pocket endmill | 8mm (correct) | 8mm, 3mm, 4mm | PARTIAL |
| Contour endmill | 1mm, 2mm, 3mm... (wrong — too small) | 10mm | NO — primary tool missing |
| Chamfer mill | 6mm | 10mm | NO — undersized |
| Face mill | 20mm, 40mm, 63mm | 10mm (long reach) | NO — oversized for part |
| Ballnose / bull-nose | Not selected | 5mm, 3mm ballnose; 8mm bull-nose | MISSING |

**Critical gap:** The pipeline never selects a 10mm endmill for the primary contour/roughing operations. The vendor's workhorse tool (10mm flat endmill, used 20+ times) appears nowhere in the pipeline output.  
**Likely cause:** Boss classification maps to `contour_mill` which picks smallest endmill >= boss-profile diameter. Many boss clusters have sub-10mm profile widths after over-segmentation, so a 1–4mm tool gets selected instead of the 10mm used for the full outer profile.

---

## 5. Parameter Quality (Feeds & RPM)

### Drilling — most comparable ops

| Op | Pipeline RPM | Vendor RPM | Pipeline Vf | Vendor Vf | Within ±30%? |
|----|-------------|-----------|------------|----------|--------------|
| Spot/center drill 2mm | 10000 (capped) | 1000 | 300 mm/min | 80 mm/min | NO — 10× too high |
| Twist drill 2.5mm | 10000 (capped) | 1500 | 380 mm/min | 70 mm/min | NO — 5× too high |
| Twist drill 3mm | 10000 (capped) | 1200 | 450 mm/min | 80 mm/min | NO — 5× too high |

**Root cause:** Pipeline calculates Vc=80–130 m/min for small drills, which gives theoretical RPM of 12,000–19,000 — capped to 10,000. Vendor uses very conservative RPM for small drills (1000–1500 RPM). The catalog Vc values assume rigid HSS machines; these values need a separate "small drill conservatism" scaling factor.

### Milling — endmill ops (8mm pocket milling)

| Op | Pipeline RPM | Vendor RPM | Pipeline Vf | Vendor Vf | Within ±30%? |
|----|-------------|-----------|------------|----------|--------------|
| 8mm endmill pocket RF | 10000 (capped) | 2200 | 600 mm/min | 500 mm/min | RPM: NO; Vf: YES |
| 3mm endmill contour | 10000 (capped) | 2200–3000 | 300 mm/min | 250–800 | Vf: borderline |

**Vf is reasonable for endmills.** The primary issue is RPM being pegged at the machine max for all operations. This happens because catalog Vc values for aluminium (300–500 m/min) give theoretical RPM of 15,000–50,000 for small tools, all capped at 10,000.

### Chamfer milling

| Op | Pipeline | Vendor |
|----|----------|--------|
| Chamfer mill (hole edges) | 6mm, 10000 RPM, 1000 Vf | 10mm, 900 RPM, 80 Vf |
| Chamfer mill (profile edge) | 6mm, 10000 RPM, 1000 Vf | 10mm, 4500 RPM, 700 Vf |

Pipeline chamfer parameters are completely off — vendor is very conservative for hole chamfering (slow and careful) vs aggressive for edge chamfering. Pipeline uses same params for both.

---

## 6. PDF Program Sheet Quality

- **Pages:** 20 (1 cover + 1 tool list + 18 setup/operation pages)
- **Readability:** Machine readable — structured table format, correct header
- **NOT_FOUND flags:** 0
- **MANUAL_REVIEW flags:** 0
- **Warning lines:** 130 total
  - RPM CAPPED (majority) — all small tools hitting 10,000 RPM cap
  - SUBSTITUTION (6 instances) — 2.529mm hole → 2.5mm, 3.2mm → 3.0mm drill

The PDF looks professional and machine-readable. A machinist could use it as a starting point. Main readability issue is 12 setups on the sheet — a real job card would have 3–4.

**The program sheet does NOT look like a real machinist job card yet** because:
1. 12 setups instead of 4
2. 187 steps visible (would need to scroll 20 pages)
3. RPM values all show 10,000 (capped) — machinist would see this as suspicious
4. Missing key features (radii, step features, large bore)

---

## 7. Top 3 Gaps to Fix Next

### Gap 1: Setup consolidation (CRITICAL)
**Problem:** 12 setups generated vs 4 actual.  
**Fix needed:** In `setup_planning.py`, after assigning clusters to setups by feature axis, merge setups that have very similar spindle directions within a consolidation tolerance (e.g., angled setups within ±15° of a principal axis should be merged into the nearest principal-axis setup). Also add a maximum-setups budget (e.g., 4 for a 3-axis VMC) that forces merging of rare-axis features into the nearest practical setup.

### Gap 2: RPM scaling for small-diameter tools (HIGH)
**Problem:** All small drills (≤6mm) and endmills hit the 10,000 RPM cap, giving Vf values 5–10× higher than real practice.  
**Fix needed:** In `parameter_calculation.py`, introduce a drill conservatism factor for center/spot drills (use 30–50% of catalog Vc for fragile tip tools, not 100%). For twist drills ≤4mm, cap actual Vc at 60 m/min regardless of catalog value.

### Gap 3: Missing feature types — step, floor radius, large bore (HIGH)
**Problem:** Step/shoulder features, floor radii (ballnose), and large bores (≥13mm) not generating correct ops.  
**Fix needed:**  
- Add `step_feature` classification and map to `contour_mill` (walls) + `face_mill` (floor).  
- Add ballnose cleanup pass for any cluster with `internal_corner_radius > 0`.  
- Fix `large_bore` process selection to generate `circular_interp` RF + FINISH instead of `face_mill`.
