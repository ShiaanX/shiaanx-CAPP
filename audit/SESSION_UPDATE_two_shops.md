# SESSION UPDATE — Two-Shop Motor Mount Audit
**Date:** 2026-06-23
**Branch:** audit/motor-mount-two-shops

---

## What Was Done

Parsed and compared the Motor Mount G-code and inspection data from two production shops:
- TS (Sinumerik 828D, 4 MPF setups, NX CAM)
- Krishna Engineering (PowerMILL/Fanuc, 3 settings, TAP files)

Both shops machined the same Al 6061 motor mount for Aviocian Technologies (SX_2627_007).

---

## Files Created

| File | Description |
|------|-------------|
| audit/motor_mount_operations.json | TS shop: all 4 MPF setups parsed, 37 operation blocks with S, F, tool |
| audit/motor_mount_krishna_operations.json | Krishna: all 20 TAP files parsed, 3 settings |
| audit/motor_mount_inspection_comparison.json | 15 dimensions side-by-side, TS vs Krishna, with pass/fail |
| audit/motor_mount_shop_comparison.md | Tabular op-by-op comparison |
| audit/motor_mount_new_rules.json | 11 new/updated rules in proposed_rules.json schema |
| audit/FINDINGS_two_shops.md | Narrative findings, key differences, pipeline update recommendations |
| audit/parse_two_shops.py | Script used to generate all above (reproducible) |

---

## HIGH CONFIDENCE Rules Discovered (Both Shops Agree)

These are physics-driven — both shops independently converged on the same decision:

1. **SR-MM-001** — For bore 14-32mm: use 10mm EM circular interpolation (not boring bar)
2. **SR-MM-002** — For pocket width 8-15mm: use 8mm EM as roughing tool
3. **SR-MM-003** — Add ball_nose_finish step for any feature with fillet_radius > 0
4. **SR-MM-004** — Separate setup for second major face (flip) is a physics requirement
5. **SR-MM-005** — Bore and long pocket go in last setup (accumulated error minimisation)
6. **SR-MM-008** — Roughing tool = largest EM that fits (max dia for MRR)

---

## Notable Findings

- **TS uses 4 setups, Krishna 3** — TS has a dedicated finish re-setup that Krishna skips.
  Both pass inspection (except SL 13). Extra setup is shop preference for tighter floors.

- **Krishna has NO drill TAP files** — Drilling is either on a separate machine or programs
  not shared. The spot_drill -> twist_drill pipeline rule remains valid.

- **No chamfer TAP files in Krishna** — Chamfer may be done by EM edge or hand deburring.

- **5mm shoulder (SL 13) failed at BOTH shops** — Both shops marked this Not OK / borderline.
  This is a known-difficult feature, likely dominated by tool deflection, not process error.

- **Bore phi16.1 independently chosen as 10mm EM circular interp at both shops** — Strong
  confirmation this is the correct approach for this diameter range.

- **Inspection quality:** TS inspected 9 parts across 2 sheets (P1-5 and P6-9); Krishna
  inspected 5 parts on 1 sheet. TS had slightly better dimensional consistency on the
  phi3.0 hole (TS: 3.05-3.12, Krishna: 2.90-2.95 — Krishna slightly under nominal).

---

## Next Steps

1. Apply SR-MM-001 to tool_selection.py: extend circular_interp range to 14mm minimum
2. Apply SR-MM-003 to process_selection.py: add ball_nose_finish for fillet features
3. Apply SR-MM-005 to setup_planning.py: bore_last_setup flag
4. Run updated pipeline against audit/MOTOR MOUNT.step to verify changes produce correct ops
5. Consider a third part audit (e.g. Al extrusion mount from Rekise) to triangulate rules
