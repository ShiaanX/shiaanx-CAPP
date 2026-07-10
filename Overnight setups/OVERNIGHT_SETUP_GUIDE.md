# Overnight Run — Setup Guide
**Date:** 22 June 2026  
**Sessions:** 3 parallel Claude Code runs  
**Reference part:** Motor Mount (G:\My Drive\Closed Loop\Motor Mount\)

---

## Before you start — verified, no fill-ins needed

All placeholders have been resolved and are pre-filled below. Do not edit them.

**CAPP code path (TASK 1 + TASK 4):**
`C:\Users\Siddhant Gupta\Documents\ShiaanX`

**Data sources for TASK 2 (pre-verified, all live):**
- InfluxDB (CNC controller logs): see TASK 2 file for connection details
- PostgreSQL (business data): local Docker at `postgresql://postgres:7009@localhost:5432/sx_dev`

Every path in all tasks points to confirmed files. No manual changes needed before launching.

---

## How to start each session

Open Claude Code and paste the entire contents of the TASK.md as your first message.
Then add this line at the end:

> "Please read CLAUDE.md first for project context, then follow this TASK.md exactly.
> Start with Step 1 and work through to the end. If you hit a hard stop condition,
> write the FINDINGS file and stop. Do not proceed past a stop condition."

---

## Session assignments (run in this priority order)

| Priority | Task file | Branch name | Risk level |
|----------|-----------|-------------|------------|
| 1st | TASK_1_feature_recognition_audit.md | audit/feature-recognition-motor-mount | Medium — writes code |
| 2nd | TASK_4_rule_sheet_expansion.md | feature/rule-sheet-expansion | Zero — JSON + writing only |
| 3rd | TASK_2_controller_logs_dashboard.md | feature/dashboard-data-model | Low — reads DB only |

If your machine can only run one session comfortably overnight: run TASK 1.
If two: TASK 1 + TASK 4.
All three together is fine if you have the memory — they work on separate branches
and will not conflict.

---

## What to check in the morning (in this order)

### 1. Read the FINDINGS files first — before looking at any code
```
FINDINGS_feature_recognition.md
FINDINGS_rule_expansion.md
FINDINGS_dashboard_data_model.md
```

### 2. Accuracy numbers (TASK 1)
```
audit/accuracy_breakdown_motormount.txt        ← before fixes
audit/accuracy_breakdown_motormount_postfix.txt ← after fixes
```

### 3. Review code changes (TASK 1 only — the other two write no code)
```bash
git diff main..audit/feature-recognition-motor-mount -- '*.py'
```
Read every diff before merging. Each fix should be a separate commit
so you can revert individual changes if needed.

### 4. Rule proposals (TASK 4)
```
audit/rule_coverage_matrix.md      ← what was covered vs. missing
proposed_rules.json                ← the actual proposals
```
Check the confidence breakdown. LOW confidence rules go to Danesh before
anything enters process_selection.py. HIGH confidence rules (Handbook +
Motor Mount observed) can be reviewed and merged by you directly.

### 5. Dashboard data model (TASK 2)
```
dashboard_data_model.json
audit/kpi_mapping.md
```
The key question: can FPR and FAR cycle time be computed from data today?
The FINDINGS file will answer this directly.

---

## What a good morning looks like

**TASK 1:** Per-feature accuracy breakdown for the Motor Mount exists.
3–6 deterministic bugs fixed and committed separately.
List of architectural decisions waiting for your call.

**TASK 4:** proposed_rules.json has structured rules for all 4 materials,
each with a Machinery's Handbook citation and Motor Mount validation where applicable.
Confidence levels tell you what goes to Danesh vs. what you can merge directly.

**TASK 2:** You know exactly what is in the database, what can be computed today,
and a concrete list of what needs to start being captured to compute FPR and FAR.

If any session hit a stop condition early, the FINDINGS file explains why.
A short run with a clear finding (e.g. "setup sheet PDFs are not machine readable")
is still a useful result — it tells you what to fix before the next run.
