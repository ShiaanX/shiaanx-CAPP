# ShiaanX Investor Demo Plan

## Context

We want to share an investor demo of what we are looking to build. The goal is to show a working, credible closed-loop manufacturing intelligence platform — not slides, but a live system processing a real part. You have a real vendor part (referred to below as **DEMO-PART-001**, a precision aluminium component) with nearly complete data: CAD ✅, CAM ✅, Controller logs ✅, inspection template ✅. The pipeline outputs can be generated for this part.

The strongest story for investors in aerospace/defense manufacturing is not just "AI generates a process plan" — it's **"here is a real part, here is what our AI planned, here is what the machine actually cut, here is how it came out."** That closed loop — CAD → AI plan → machine execution → QC — is the moat and the differentiator.

---

## Demo Narrative (the story to tell)

**"A component, from STEP file to inspected part, in one platform."**

1. **Drop the STEP file** → pipeline runs live, 3D viewer shows the part, 9 stages complete in ~10s
2. **Process plan appears** → setups, operations, cutting conditions, tool list, WCS — all AI-generated
3. **Program sheet PDF** → "this is what goes to the machinist"
4. **"Here's where it gets interesting"** → show the same part already machined by the vendor
   - Side-by-side: AI plan vs actual CAM program the machinist used
   - Show where they match, where they differ (honest — this builds credibility)
5. **Inspection close-out** → open the filled Excel template with actual QC measurements
   - Green PASS / red FAIL cells showing real dimensional data
   - "This is the traceability record that aerospace customers require"
6. **Controller log** → "and this is what the machine actually did — spindle load, feed overrides, cycle time — feeding back to improve the next plan"

**Punchline:** "Every part that goes through this system teaches it. No one in India has this closed loop."

---

## What to Build / Complete in the Next Few Days

### Priority 1 — Complete the vendor dataset (your action, not code)

You need from the vendor for DEMO-PART-001:
- **Controller log** — any CNC controller output: cycle time, spindle overrides, alarm history, actual feed/speed data. Even a screenshot or printout works for demo.
- **QC report** — CMM report or hand-measured inspection sheet with actual dimensions
- **CAM program** — the actual NC G-code or CAM toolpath summary (operations used, tools, cycle time)

These don't need to be in a database — printed on screen next to your inspection template is enough for a demo.

#### Why the controller log matters

A controller log contains: spindle load over time, actual feed/speed overrides the machinist applied, cycle time per operation, alarms, tool wear flags, and sometimes axis position data.

**For the demo, it does three things:**

1. **Proves the closed loop is real** — without it, you're just an AI outputting a plan into a void. The controller log is evidence that the plan was actually executed and you can show the delta: if the AI said 8000 RPM and the machinist dialled it to 6500 RPM due to chatter, that deviation is your training signal and your improvement flywheel.

2. **Differentiates from pure software** — investors in manufacturing know the gap between "plan" and "reality" is where every other software company fails. Showing controller data says "we are connected to the machine, not just the office."

3. **Sets up the feedback loop story** — "Every deviation the machine records feeds back to refine the next process plan. This is how we get better with every part, without hiring more process engineers."

If the vendor can't provide a full log, even a hand-written note from the machinist ("actual cycle time 47 mins, reduced feed on Setup 2 due to chatter") is enough to make the point live.

### Priority 2 — Demo polish on the frontend (code work)

The existing React frontend already handles upload → 3D viewer → program sheet. Two targeted additions will make the demo compelling:

**2a. "Real Part" mode in the viewer** — add a toggle or tab in CappViewer that shows:
- The AI-generated program sheet PDF (already works)
- A side-by-side comparison panel: "AI Plan vs Actual" — a simple table showing AI operations vs what the vendor actually did (hardcoded for demo using the real data you collect)

**2b. Inspection tab — fill in actuals** — the InspectionTab.js is already wired. Populate the inspection template with actual QC measurements so the PASS/FAIL cells light up live in the demo. This is the highest-impact single screen for investors.

**2c. Pre-load the demo part** — ensure DEMO-PART-001.stp is uploaded and pre-processed in the demo backend so the pipeline doesn't need to run from scratch (removes live failure risk). Have it as a "load demo part" button or URL param.

### Priority 3 — Rehearsal script

Prepare a 5-minute spoken walkthrough:
1. (30s) Problem statement: "Getting from CAD to first good part takes weeks of manual work by expensive engineers"
2. (90s) Live upload + pipeline run — let it breathe, show the 3D viewer
3. (90s) Walk the program sheet — point to a specific operation and explain what it means
4. (90s) Show the real machined part + QC data — "this part was actually machined"
5. (30s) Punchline + ask

---

## What NOT to build for this demo

- Do NOT spend time on the autonomous agent (needs API keys, not demo-stable)
- Do NOT try to get Fusion 360 running live (too many manual steps, high failure risk)
- Do NOT build new backend features — the FastAPI pipeline is solid as-is
- Do NOT polish ML accuracy — 66% is fine; frame it as "baseline before real-part feedback"

---

## Files checklist for demo part

Replace with your chosen part's files before the meeting.

| Asset | What you need |
|-------|--------------|
| STEP file | `<part>.stp` — the CAD input |
| Program sheet PDF | `<part>_program_sheet.pdf` — AI-generated output |
| Inspection template (Excel) | `<part>_inspection_template.xlsx` — with real QC actuals filled in |
| CAM project | Vendor CAM program or toolpath summary |
| Controller log | Vendor-supplied log, or machinist notes on overrides + cycle time |
| Tolerances | `tolerances.json` — filled from the engineering drawing |
| Datumed features | `<part>_features_datumed.json` — for inspection section grouping |

---

## Verification

To confirm the demo is runnable end-to-end:
1. Start backend: `& "C:\Users\Siddhant Gupta\miniconda3\envs\occ\python.exe" -m uvicorn main:app --reload --port 8001` (from `capp_service/`)
2. Start frontend: `npm start` (from `capp-frontend/`)
3. Upload your demo part `.stp` via the UI
4. Confirm all 9 pipeline stages complete, 3D viewer renders, PDF appears
5. Open inspection template in Excel — confirm PASS/FAIL formulas work with real QC data
6. Have the controller log / machinist notes open in a second window
7. Run through the 5-minute script once solo before the investor meeting
