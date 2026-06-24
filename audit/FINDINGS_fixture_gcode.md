# Fixture G-Code Audit — Motor Mount (Krishna Engineering)

**Date:** 2026-06-24  
**Part:** Motor Mount, Al 6061-T6  
**Source:** 20 `.tap` files across 3 settings  

---

## Part Dimensions (from MOTOR MOUNT_features.json)

| Axis | Value |
|------|-------|
| X (short) | 55.35 mm |
| Y (long) | 104.79 mm |
| Z (height) | 21.52 mm |

---

## Setting 1 — Raw Billet, First Face

**WCS:** G54 (reset between settings)  
**Z Clearance:** 22.5 mm (just clears the 21.5mm part height)  
**Z Zero:** Top of raw stock (Z0 ≈ top of billet)  
**XY Zero:** Centre of part (toolpaths symmetric ±X and ±Y)

**Toolpath evidence:**
- Tool (12mm EM) travels to X±58.5mm → part edge at X±52.5mm → part long dim = **105 mm** ✓
- Tool travels to Y±33.6mm → part edge at Y±27.6mm → part short dim = **55 mm** ✓
- First cut at Z−0.396mm (just below stock top), cuts down to Z−21mm (full part height)
- Header: `STOCK: +.10` = 0.1mm finish stock on outer profile

**Fixture inferred:**
- **Type:** Standard vise (hard jaws)
- **Long axis (104mm):** Along machine X-axis
- **Short axis (55mm):** Gripped by vise jaws in machine Y direction
- **Jaw opening:** ~65mm (55mm part + 5mm each side clearance, rounded)
- **Parallels:** 10mm (raises part above jaw line for full Z access)
- **Rest face:** −Z (raw billet bottom sits on parallels)

---

## Setting 2 — Flip, Second Face

**WCS:** G54 (reset — same offset code as setting 1)  
**Z Clearance:** 100 mm (much higher — part elevated on taller parallels or stack-up after flip)  
**Z Zero:** Top of newly exposed face — face mill descends from Z10.802 to Z0  
**XY Zero:** Centre of part

**Toolpath evidence:**
- Face mill (`12end_face11MM.tap`) cuts from Z10.802 down to Z0 in 0.198mm steps (fine finish)
- After face mill: 2D pocket operations (blind holes, bores)
- X range: ±54.4mm → part edge ±48.4mm → part still ~97mm in machine X direction

**Fixture inferred:**
- **Type:** Standard vise (same hard jaws)
- **Part position:** Flipped 180° — setting 1 machined face now rests on parallels
- **Z datum:** Probed off the machined flat from Setting 1 (now bottom, resting face)
- **Jaw opening:** ~65mm (same short dimension clamped)
- **Parallels:** 10mm (possibly higher to clear features machined in setting 1)
- **Z stock above datum:** 10.802mm (raw billet thickness above final face)

**Setup-to-setup relationship:**
Setting 1 machined the outer profile and possibly one face. Setting 2 flips the part 180°, the previously machined face becomes the reference (sits on parallels), and the remaining raw face is face-milled flat before detail features are machined.

---

## Setting 3 — Side Face

**WCS:** G54 (reset again)  
**Z Clearance:** 100 mm  
**Z Zero:** Side face of part (probed from +X or -X face)  
**XY Zero:** Centre of part feature (small bore/pocket near centre)

**Toolpath evidence:**
- First move: X1.162, Y-2.905 (near centre — this is a small bore or pocket)
- Only 2 programs (10mm EM, 4mm EM) — minor operations
- Very limited Z depth (cuts start at Z-0.05)

**Fixture inferred:**
- **Type:** Angle plate (part on its side) or re-gripped in vise with stop
- **Clamped faces:** Previously machined faces from settings 1+2
- **Jaw opening:** 55mm (the part short dimension, now the height in the new orientation)
- **Soft jaws:** Not required (clamping on flat machined surfaces)

---

## Key Findings Summary

| Item | Finding |
|------|---------|
| WCS strategy | Single G54 offset, reset between each setting |
| XY zero | Always centre of part (symmetric toolpaths) |
| Z zero | Setting 1: top of stock. Settings 2+3: top of machined face |
| Fixture type | Standard hard-jaw vise (settings 1+2), angle plate (setting 3) |
| Jaw opening | ~65mm for settings 1+2 (55mm part + 10mm clearance) |
| Parallels | 10mm (setting 1). Higher stack or standoffs for settings 2+3 |
| Soft jaws | Not used — part geometry allows standard hard jaws throughout |
| Z clearance jump | 22.5mm (setting 1) → 100mm (settings 2+3): indicates taller workholding stack after flip |
| Face removed in setting 2 | 10.802mm of stock face-milled flat |

---

## Implications for fixture_planner.py

1. The pipeline's `workholding.jaw_opening_mm` should use **part_short_dim + 10mm** (not the raw bbox dim)
2. Z zero rule: setup 1 → `top_of_stock`; setup 2+ → `top_of_part`
3. Parallels: always recommend 10mm for jaw_opening 50–100mm
4. The angle_plate fixture for setting 3 is correct for side-face access
5. Soft jaws only needed if rest face is non-planar (curved or has features from prior setup)
