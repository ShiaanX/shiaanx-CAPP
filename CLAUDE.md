# ShiaanX Product Context

This file provides permanent context about ShiaanX for Claude Code. Read this before working on anything in this project.


## What ShiaanX Is

ShiaanX is an AI-driven intelligent manufacturing company building software to automate the end-to-end journey from CAD file to finished precision part. The vision is a single platform where a STEP file comes in and the system handles everything downstream — process planning, CAM, execution tracking, inspection, shipping — with humans in the loop for exceptions only.

Think Hadrian or Daedalus, built for India, starting with software-defined process intelligence before owning machines.

**Company Details:**
- Stage: MVP / Early product
- Target sectors: Aerospace, Drones (starting point)
- Geography: India-first, with international clients in scope from Phase 1
- Revenue model: Manufacturing-led (not software-led); partner-based operations in Phase 1, moving to hybrid ownership

**What ShiaanX is NOT:**
- Not a CAM software (we sit above it)
- Not a job portal or marketplace for machining
- Not competing on price — competing on reliability, traceability, and engineering depth


## The Problem Being Solved

Precision manufacturing for advanced industries (aerospace, drones, defence) is bottlenecked by manual, knowledge-intensive process planning. Getting from a CAD file to a correct first part requires experienced engineers making hundreds of decisions — machine selection, tooling, setup sequence, feeds and speeds, fixturing — most of which live in people's heads, not systems. This causes slow quotes, long lead times, high scrap rates, and inconsistent quality. ShiaanX is automating these decisions.


## Product — The Pipeline

The core technical system is an automated CAD-to-part process planning pipeline.

- Target materials (priority): Aluminium 6061
- Target machine type (initial): 3-axis VMC


## Competitors to Be Aware Of

Hadrian, Daedalus, CloudNC (CAM Assist), Forge Automation, Jeh Aerospace, Limitless CNC


## Architectural Decisions

Document every major decision here so future sessions don't relitigate them.

---

### AD-001 — Tool database does not store machine-specific post-process fields
**Date:** 2026-04-11
**Decision:** `tool_number`, `length_offset`, `diameter_offset`, `turret_position` are NOT stored in `tool_database.json`.
**Reason:** These are machine-specific assignments (a 6mm end mill is T03 on one machine, T07 on another). They belong in a job setup sheet generated at runtime, not in the tool definition.

---

### AD-002 — Toolpath.ai inch-based tool library will not be imported
**Date:** 2026-04-11
**Decision:** No translation layer will be built to import Toolpath's `toolpath_generic_tools.json` into our schema.
**Reason:** Their library is inch-based (US tooling, US machines). Geometry converts cleanly but feeds/speeds do not — values are calibrated to different machine characteristics. Risk of incorrect cutting parameters on shop floor is too high for aerospace parts. We populate the database directly from Sandvik/Kennametal metric catalogues where every value is traceable.

---

### AD-003 — Tool database is metric-first, Sandvik/Kennametal sourced
**Date:** 2026-04-11
**Decision:** All tool parameters derived from published Sandvik Coromant and Kennametal catalogues for aluminium alloys (6061, 7075). Values are conservative mid-range recommendations.
**Reason:** Traceable, verified source. India machining shops use metric tooling. Catalogue values are a safe starting point before shop-specific tuning.

---

### AD-004 — Ramp/plunge stored as percentages, not absolute feed rates
**Date:** 2026-04-11
**Decision:** `ramp_plunge` in tool entries stores `vf_ramp_pct_of_feed` and `vf_plunge_pct_of_feed` as percentages of the normal cutting feed, not absolute mm/min values.
**Reason:** Absolute values would need to be different per material (aluminium vs steel). Percentages let `parameter_calculation.py` compute the actual feed rate at runtime after the material and cutting feed are known.

---

### AD-005 — Bounding box and metadata must flow through the full pipeline
**Date:** 2026-04-11
**Decision:** `cluster_features.py` explicitly passes through `bounding_box`, `mass_properties`, `file`, and `topology_counts` from the features JSON into its output.
**Reason:** Downstream steps (setup_planning, workholding, WCS origin) need part geometry. Originally these were dropped at the clustering stage, causing `jaw_opening_mm` and `wcs_origin_mm` to always be null.

---

### AD-006 — WCS origin uses CORNER zero when part is placed at CAD origin
**Date:** 2026-04-11
**Decision:** If `xmin ≈ 0` (within 2% of part dimension), the WCS origin is set to the CAD-origin corner rather than part centre.
**Reason:** Most MFCAD parts and manufactured parts place the bounding box min at (0,0,0). Corner zero keeps all G-code coordinates positive, which is easier for the machinist to verify and reduces sign errors. Centre zero is used for parts not aligned to the CAD origin.

---

### AD-007 — shiaanx-backend is a separate independent git repo
**Date:** 2026-04-11
**Decision:** `shiaanx-backend/` (another developer's work) is NOT included in the `shiaanx-CAPP` repo. It lives at `github.com/siddhantg2311/shiaanx-backend` independently.
**Reason:** It has its own `.git` folder and remote. The two codebases serve different purposes and have different owners. Git treats it as a nested repo and skips it automatically.

---

### AD-008 — Dataset STEP files excluded from git
**Date:** 2026-04-11
**Decision:** `Claude output for program sheet/Dataset/` is in `.gitignore` and not committed.
**Reason:** 8,949 STEP files are too large for a git repo. The MFCAD++ dataset is a standard public dataset that can be re-downloaded. Only intermediate pipeline outputs for specific tested parts (e.g. `Basic Design/`, `Botlabs Hub/`, `Botlabs Hinge/`) are committed.
