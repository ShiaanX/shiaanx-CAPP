# Rule Coverage Matrix
Date: 2026-06-22  
Source: `process_selection.py` vs Motor Mount operations + Machinery's Handbook

**Legend:** COVERED = rule exists and is correct | PARTIAL = rule exists but incomplete or incorrect | GAP = no rule exists

---

## Coverage by Material × Operation

| Operation | Al 6061-T6 | Al 7075-T6 | SS 304 | Mild Steel EN8 |
|-----------|-----------|-----------|--------|----------------|
| **Centre / spot drill** | COVERED | COVERED | COVERED | COVERED |
| **Twist drill (d 1–13mm)** | COVERED | COVERED | PARTIAL (no Vc) | PARTIAL (no Vc) |
| **Pilot + core drill (d 13–32mm)** | COVERED | COVERED | PARTIAL | PARTIAL |
| **Peck drill cycle (DDR 3–5)** | COVERED | COVERED | COVERED | COVERED |
| **Deep peck (DDR > 5)** | COVERED | COVERED | COVERED | COVERED |
| **Micro drill (d < 1mm)** | COVERED | COVERED | GAP | GAP |
| **Reaming (H7/H8 tolerance)** | GAP | GAP | GAP | GAP |
| **Tapping M2–M12 (rigid)** | COVERED | COVERED | PARTIAL (no Vc, no tap stock) | PARTIAL |
| **Boring bar (d > 32mm)** | COVERED | COVERED | COVERED | COVERED |
| **Circular interp (d > 32mm)** | COVERED | COVERED | GAP | GAP |
| **Circular interp (d 13–32mm)** | **GAP** | **GAP** | GAP | GAP |
| **Countersink** | COVERED | COVERED | COVERED | COVERED |
| **Countersunk hole** | COVERED | COVERED | COVERED | COVERED |
| **Counterbore** | COVERED | COVERED | COVERED | COVERED |
| **Face milling** | COVERED | COVERED | COVERED | COVERED |
| **Dynamic/adaptive RF milling** | **GAP** | **GAP** | N/A | **GAP** |
| **Outer profile / contour mill** | COVERED | COVERED | COVERED | COVERED |
| **Pocket milling (RF + FINISH)** | COVERED | COVERED | COVERED | COVERED |
| **Slot milling** | COVERED | COVERED | COVERED | COVERED |
| **Corner clearing (CORNER_R)** | COVERED | COVERED | COVERED | COVERED |
| **Step / shoulder milling** | PARTIAL (mapped to pocket_mill) | PARTIAL | PARTIAL | PARTIAL |
| **Boss / OD contour** | COVERED | COVERED | COVERED | COVERED |
| **Chamfer milling (1-pass)** | COVERED | COVERED | COVERED | COVERED |
| **Chamfer milling (2-pass strategy)** | **GAP** | GAP | N/A | GAP |
| **Bull nose radius blending** | **GAP** | **GAP** | N/A | GAP |
| **Ball nose floor / step finish** | PARTIAL (fillet only) | PARTIAL | N/A | N/A |
| **Ball nose 3D surface contour** | COVERED (fillet type) | COVERED | N/A | N/A |
| **Thread milling** | GAP | GAP | GAP | GAP |
| **Deep narrow pocket (high DDR EM)** | PARTIAL (no DDR check for EM) | PARTIAL | GAP | GAP |

---

## SS304 — All Operations

Currently stainless_steel entry only appears in MATERIAL_STOCK_TABLE and FACE_MILL_MAX_AP. No material-specific operation sequences exist. Any SS304 job produces the same feature sequence as aluminium — which is incorrect (no dedicated speed/feed rules, wrong drill cycle assumptions, no tapping stack-up allowances).

| Operation | SS 304 | Notes |
|-----------|--------|-------|
| Spot drill | COVERED (sequence) | GAP: Vc/fpr values not in tool_database |
| Twist drill | PARTIAL | Sequence OK; Vc/fpr missing for SS |
| Tapping | PARTIAL | Sequence OK; no tap allowance or coolant rule |
| Face mill | COVERED | max_ap=0.5mm set in table |
| Profile/contour | COVERED | stock to leave set to 0.25mm |
| Pocket | COVERED | stock values set |
| Reaming | GAP | No sequence at all |
| Thread milling | GAP | No rule |
| Drilling > 13mm | PARTIAL | pilot+core sequence OK; Vc wrong |

---

## Gaps Summary

| Gap ID | Description | Severity | Motor Mount Evidence |
|--------|-------------|----------|---------------------|
| G-01 | Dynamic/adaptive milling (trochoidal) RF for aluminium | HIGH | All 4 setups use DYNAMIC RF as primary material removal |
| G-02 | Reaming sequence (H7/H8 tolerance holes) | HIGH | Not observed on motor mount; Machinery's Handbook required |
| G-03 | Circular interpolation for d=13–32mm bores | HIGH | Setup 4 — D16.1 bore machined with D10 EM profile |
| G-04 | Bull nose end mill for top radius blending | MEDIUM | Setups 1 and 2 — T8 D8R1 used for top R features |
| G-05 | Ball nose for step floors and pocket floors | MEDIUM | All setups use ball nose for step/cavity floor finishing |
| G-06 | Two-pass chamfer (slow plunge + fast profile) | MEDIUM | Setup 1 ops 18–19, Setup 4 op 3 |
| G-07 | Thread milling (large threads, blind holes, SS) | MEDIUM | Not observed; Machinery's Handbook |
| G-08 | SS304 cutting parameters (Vc/fz for all ops) | HIGH | No SS304 jobs in motor mount dataset |
| G-09 | Deep narrow pocket rule (DDR > 10 for EM) | MEDIUM | Setup 4 op 4 — D3 at -41.5mm |
| G-10 | Mild steel EN8 drilling parameters | LOW | No EN8 jobs in motor mount dataset |
