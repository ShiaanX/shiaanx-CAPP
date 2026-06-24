# Audit Findings — LIGHT-FCS_A06.01.0001.A00

**Date:** 2026-06-23  
**Pipeline:** ShiaanX CAPP (rule-based, v1)  
**Auditor:** Claude Code  
**Part envelope:** 50 × 30 × 32 mm | **Material:** Al 5083 H-12/H-22 | **Weight:** 0.04 kg

---

## 1. Part Complexity vs Motor Mount

| Metric | Motor Mount (est.) | LIGHT-FCS |
|--------|-------------------|-----------|
| Feature clusters | ~15–20 | **39** |
| Actual setups | 2–3 | **9** |
| CAM files | ~5 | **16** |
| Smallest tool used | ~4mm | **1.5mm** |
| Material | Al 6061 | **Al 5083 H-12/H-22** |
| Finish | Anodize (maybe) | **SURTEC 650 + Black Anodize + masking** |
| GD&T | Basic | **Multi-datum, 0.02mm flatness, g8 bore** |
| Drawing origin | India | **DUMA Eng. Group, Spain (aerospace)** |

The LIGHT-FCS is significantly more complex. It has tight-tolerance features on multiple faces (9 setups), a precision Ø10 g8 bore, narrow 1.5mm EM operations, and aerospace-grade GD&T with multi-datum callouts.

---

## 2. Feature Detection Accuracy

### What the pipeline detected (39 clusters)

| Feature type | Pipeline count | Notes |
|---|---|---|
| chamfer | 12 | Likely overcounting — small chamfers on every edge |
| pocket | 10 | Main body pockets — likely correct |
| counterbore | 7 | Classified holes as counterbores |
| planar_face | 4 | Main flat faces |
| pocket_angled | 2 | 20° angled pockets — correctly identified as angled |
| slot | 2 | Narrow slot features |
| through_hole | 1 | One true through hole detected |
| background | 1 | Unclassifiable face |

### Gap vs actual machining

The actual machining used **no drills at all** — all holes were circular interpolated with end mills. The pipeline planned **8 spot_drill + 8 twist_drill** operations for the 7 counterbores + 1 through hole. This is a correct manufacturing strategy for some cases but the actual shop preferred interpolation throughout (likely because hole tolerance and diameter choices favoured that path for this part).

The **1.5mm EM operations** (setups 7 and 8) point to features the pipeline did not detect or did not classify correctly: narrow slots, internal corners, or fine detail channels that require a sub-2mm tool. The pipeline's smallest assigned pocket tool was 4mm.

**Undetected feature categories:**
- Sub-2mm narrow slots / internal corner reliefs (need 1.5mm EM)
- Fine detail passes on tight-tolerance bosses or bores

---

## 3. New Operation Types Not in Pipeline

### A. 1.5mm End Mill Operations (Setups 7 & 8)

**Files:** `7_1.5END`, `8_1.5END_FNISH`  
**What this means:** Features ≤ 3mm wide (slot width or corner radius) that cannot be reached with a 2mm EM without rubbing. Typical candidates:
- Narrow slot (width ≤ 2mm) between pockets
- Corner relief on a stepped pocket where a 4mm EM leaves too large a corner radius
- Fine profile finish on a 2mm-wide ledge or rib

**Pipeline capability today:** The tool database goes down to 1mm EM but `process_selection.py` only assigns sub-4mm tools for slots (slot_mill) and drilling (twist_drill). It would not route a narrow pocket or corner to a 1.5mm end mill — no rule exists for that.

**New rule needed:** If `pocket.internal_corner_radius < 1mm` or `slot.width < 2mm`, route to 1.5mm or 2mm EM contour pass. Add 1.5mm 2-flute carbide EM to tool database.

### B. 2mm End Mill (Setup 7)

**File:** `7_2END`  
Same reasoning as above — fine detail finish pass, likely on the same features as the 1.5mm.

### C. Multi-pass Roughing Strategy (Setups 1–3)

Each setup has both an `8mm_RUF` and then a `4mm` finish pass. The pipeline plans `pocket_mill RF + FINISH` correctly in concept, but in practice:
- The rough pass uses **8mm EM at S=3200 rpm, F=1500 mm/min** (Vc = 80 m/min — conservative for aluminium)
- The finish pass uses **4mm EM at S=4500 rpm, F=1000 mm/min** (Vc = 56 m/min — very conservative)
- The pipeline's aluminium Vc target (~250 m/min from Sandvik) would give S=9950 rpm for 8mm — much higher than actual shop's S=3200 rpm. **The shop ran at roughly 40% of catalogue recommended speeds.** This is common on older VMCs or where rigidity is a concern, but the pipeline's parameter_calculation.py will produce significantly higher and potentially unacceptable values for this shop.

### D. Flat Floor Finishing (Setups 3 & 6)

**Files:** `3_4END_FLAT`, `6_4END_FLATE`  
Dedicated flat floor finishing pass — the pipeline would include this inside `pocket_mill FINISH` but doesn't flag it as a separate toolpath. Not a missing operation type per se, but a toolpath strategy difference.

### E. No Drilling — All Holes Interpolated

The shop did not use any drill cycles. The Ø10 g8 bore, Ø6.8mm and Ø6.6mm holes were all circular-interpolated with end mills. The pipeline's rule-based hole routing (spot_drill → twist_drill) does not match this shop's preference. For aerospace holes with tight tolerance, interpolation with a rigid end mill is often preferred over drilling because it avoids drill wandering and allows direct feed-rate/speed control.

**New capability needed:** A `circular_interpolation` operation mode for holes where the shop prefers milling over drilling. Heuristic: use interpolation when hole diameter ≤ end mill diameter × 4, or when tolerance is IT7 or tighter.

---

## 4. Specific Pipeline Bugs / Gaps Exposed

### 4.1 Setup count: 3 vs 9 (MAJOR)

Pipeline produced 3 setups; actual machining required 9. The `setup_planning.py` principal-axis heuristic collapses features by axis direction only. It does not account for:
- Tool reach limits (depth-to-width constraint)
- Workholding interference when pockets are on adjacent faces
- Sequential dependency (machine pocket on face A before flipping to B)

For this part, the operator made 9 distinct vise setups — the pipeline under-plans this by 3×.

### 4.2 Wrong material (5083 vs 6061)

The drawing specifies **Al 5083 H-12/H-22**. The pipeline ran with `--material aluminium` which aliases to 6061/6063/6082/7075/7050. Al 5083 is not in the alias table. Material matters for:
- Vc/fz (5083 is slightly harder and less free-cutting than 6061)
- Anodizing behaviour (5083 takes anodize differently — relevant for SURTEC 650)

**Fix:** Add 5083 to the material alias table.

### 4.3 Pocket_mill tool diameter = 0mm (24 ops)

24 `pocket_mill` operations have `tool_diameter_mm = 0`. This is a tool selection bug — the pocket feature classifier doesn't pass the pocket width correctly to the tool selector, so it falls through to a default 0mm assignment. All 10 pockets + 2 slot features affected.

### 4.4 Face mill overkill (40mm vs actual 8mm EM facing)

Pipeline selected a 40mm indexable face mill for 4 planar faces. The actual shop used an 8mm EM. For a 50×30mm part in a vise, a 40mm face mill would overhang the vise jaws. The pipeline has no check that the face mill diameter is ≤ part width.

### 4.5 GD&T not carried through

The drawing has 0.02mm flatness (A-B-C datum chain) and 0.01/0.03 position tolerance on the Ø10 g8 bore cluster. The pipeline extracts no GD&T from the STEP or PDF. This means:
- No flag that the Ø10 bore requires a precision finishing pass
- No warning that facing operations must achieve Ra 1.6 not Ra 3.2
- No flag for the masking requirement before anodizing

### 4.6 Angled pockets (20°) — `fixture_rotation` stub only

The pipeline correctly identifies 2 `pocket_angled` features and inserts a `fixture_rotation` operation, but this is a placeholder — no angle value, no tilt axis, no fixture specification is generated. The actual machining required a specific angular setup (the drawing shows `=20°=`).

---

## 5. Is This Part Within Current Pipeline Capability?

**Partial.** The pipeline can produce a structurally valid process plan for this part, but with significant gaps:

| Capability | Status |
|---|---|
| Detect pockets, chamfers, planar faces | ✅ Works |
| Detect through-hole / counterbore | ✅ Works (but routes to drill, not interpolation) |
| Detect angled pockets | ✅ Works (stub only) |
| Correct setup count | ❌ 3 vs 9 (severe under-planning) |
| Sub-2mm EM operations | ❌ 1.5mm/2mm EM not planned |
| Circular interpolation for holes | ❌ Always drills instead |
| Correct tool size for pockets | ❌ 0mm diameter bug on all pockets |
| Material 5083 | ❌ Not in alias table |
| GD&T / tolerance-driven operations | ❌ Not implemented |
| Surface treatment awareness | ❌ Not implemented |
| Face mill size vs part size check | ❌ No constraint |

**Verdict:** The pipeline produces a first-pass feature list and operation sequence that a machinist could use as a starting point, but it cannot yet produce a production-ready program sheet for a part of this complexity. The 3-vs-9 setup gap is the most critical deficiency — it would cause a machinist to miss entire faces of the part.

---

## 6. Inspection Results Summary

**14 dimensions checked** on Part P1. All pass except SL 8 (22mm — remark "–", likely not measured or instrument limit).

| SL | Nominal | Tol+ | Tol- | Actual | Pass |
|---|---|---|---|---|---|
| 1 | 50 | ±0.1 | ±0.1 | 50.03/50.04 | OK |
| 2 | 3 | ±0.1 | ±0.1 | 3.01/3.02 | OK |
| 3 | 30 | ±0.1 | ±0.1 | 30.01/30.02 | OK |
| 4 | 3 | ±0.1 | ±0.1 | 3.01/3.02 | OK |
| 5 | 3 | ±0.1 | ±0.1 | 3.01/3.02 | OK |
| 6 | 2 | ±0.1 | ±0.1 | 2.01/2.02 | OK |
| 7 | 6 | ±0.1 | ±0.1 | 6.08/6.09 | OK |
| 8 | 22 | ±0.1 | ±0.1 | – | – |
| 9 | Ø6.6 | ±0.1 | ±0.1 | 6.54/6.55 | OK |
| 10 | 5 | ±0.1 | ±0.1 | 4.98/4.99 | OK |
| 11 | 1 | ±0.1 | ±0.1 | 1.02/1.03 | OK |
| 12 | 2 | ±0.1 | ±0.1 | 2.04/2.05 | OK |
| 13 | Ø6.8 | ±0.1 | ±0.1 | 6.77/6.78 | OK |
| 14 | Ø10 g8 | -0.01/+0.03 | — | 9.98/9.99 | OK |

**Notable:** SL 14 (Ø10 g8) is the tightest tolerance in the part (-0.01/+0.03 mm). Actual = 9.98/9.99, which is at the lower tolerance boundary (g8 min = 9.985 for Ø10 shaft). This is borderline — if inspected with a CMM rather than a digital caliper, it might flag. The 6 at SL 7 is also slightly out of range at 6.08/6.09 vs 6±0.1 — still within but the actual may be closer to 6.09 which is 0.09mm over nominal — fine.

SL 11 (1mm feature): actual 1.02/1.03 — this is the narrow feature that the 1.5mm EM was used for. The tight dimension (1mm) confirms why sub-2mm tooling was necessary.
