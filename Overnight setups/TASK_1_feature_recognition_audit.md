# TASK 1 — Feature Recognition Audit & Fix (Motor Mount)

**Session type:** Audit → Fix → Report  
**Time estimate:** 4–6 hours  
**Git branch:** `audit/feature-recognition-motor-mount`  
**Output:** `FINDINGS_feature_recognition.md` + fixed code committed on branch

---

## Context

ShiaanX has an 8-module CAPP pipeline that processes STEP files into CNC program sheets.
The feature recognition layer (modules 1–3) reports ~96% aggregate accuracy on a benchmark
dataset, but this is suspected to mask per-feature-type weaknesses.

Tonight's test part is the Motor Mount — a real production job with a complete dataset:
- STEP file (geometry input)
- 4 MPF G-code files (one per setup — ground truth for setup count)
- 4 Setup sheet PDFs (ground truth for operations, tools, and sequences)
- Drawing PDF (tolerance and GD&T callouts)

The setup sheets are the ground truth. Read them FIRST to establish what correct output
looks like, then run the pipeline, then compare.

---

## Inputs — all confirmed, use these exact paths

```
STEP file (pipeline input):
  G:\My Drive\Closed Loop\Motor Mount\input\MOTOR MOUNT.step

Drawing (tolerances and GD&T):
  G:\My Drive\Closed Loop\Motor Mount\input\motor mount.pdf

Setup sheets (ground truth — READ THESE FIRST):
  G:\My Drive\Closed Loop\Motor Mount\CAM files\MOTOR_MOUNT_1_SETUP_SHEET.pdf
  G:\My Drive\Closed Loop\Motor Mount\CAM files\MOTOR_MOUNT_2_SETUP_SHEET.pdf
  G:\My Drive\Closed Loop\Motor Mount\CAM files\MOTOR_MOUNT_3_FINISH_SETUP_SHEET.pdf
  G:\My Drive\Closed Loop\Motor Mount\CAM files\MOTOR_MOUNT_4_SETUP_SHEET.pdf

G-code files (secondary ground truth — tool changes and parameters):
  G:\My Drive\Closed Loop\Motor Mount\CAM files\MOTOR_MOUNT_1_SETUP.MPF
  G:\My Drive\Closed Loop\Motor Mount\CAM files\MOTOR_MOUNT_2_SETUP.MPF
  G:\My Drive\Closed Loop\Motor Mount\CAM files\MOTOR_MOUNT_3_FINISH_SETUP.MPF
  G:\My Drive\Closed Loop\Motor Mount\CAM files\MOTOR_MOUNT_4_SETUP.MPF

Pipeline root:
  [FILL IN — path to your Python CAPP code, where CLAUDE.md lives]
```

---

## Step-by-step instructions

### Step 1 — Set up the branch
```bash
git checkout main
git pull
git checkout -b audit/feature-recognition-motor-mount
```

### Step 2 — Extract ground truth from setup sheets (DO THIS BEFORE RUNNING PIPELINE)

Write a script `audit/extract_ground_truth.py` that reads each setup sheet PDF
using pdfplumber or PyMuPDF and extracts:
- Setup number
- Each operation listed (operation name, tool number, tool description)
- Any dimensions or tolerances mentioned per operation

Save extracted data to `audit/motor_mount_ground_truth.json`:
```json
{
  "part": "Motor Mount",
  "total_setups": 4,
  "setups": [
    {
      "setup_number": 1,
      "operations": [
        {
          "sequence": 1,
          "operation_name": "face milling",
          "tool_number": "T01",
          "tool_description": "50mm face mill",
          "notes": ""
        }
      ]
    }
  ],
  "total_operations": 0,
  "unique_tools": []
}
```

Fill in `total_operations` and `unique_tools` after parsing all 4 sheets.

If PDF parsing fails to extract structured data (scanned PDF, image-based):
- Note "PDF NOT MACHINE READABLE" in FINDINGS.md
- Manually read the PDFs yourself and write the JSON by hand from what you can see
- Do not skip this step — the ground truth JSON is required for the comparison

### Step 3 — Parse G-code files for tool changes
Write `audit/parse_gcode.py` to extract tool change sequences from each MPF file:

```python
import re

def extract_tools_from_mpf(filepath):
    tools = []
    with open(filepath, 'r', errors='replace') as f:
        for line in f:
            # Siemens MPF tool call format: T="TOOL_NAME" or T1 M6
            if re.search(r'\bT\d+\b.*M6', line) or 'T="' in line:
                tools.append(line.strip())
    return tools
```

Save to `audit/gcode_tool_summary.json` — one entry per setup file with tool list.
Cross-check tool counts against what the setup sheets showed.

### Step 4 — Run the full pipeline on the Motor Mount STEP file
Run the complete pipeline end-to-end on `MOTOR MOUNT.step`.
Save all intermediate JSON outputs with `_motormount_` prefix:

```
features_motormount.json
clustered_motormount.json
classified_motormount.json
processes_motormount.json
setups_motormount.json
tools_motormount.json
params_motormount.json
program_sheet_motormount.pdf
```

If the pipeline errors at feature_extraction.py: record exact error, stop, write FINDINGS.md.
Do not attempt to fix PythonOCC environment issues overnight.

### Step 5 — Build the accuracy comparison
Write `audit/compare_motor_mount.py` that loads:
- `audit/motor_mount_ground_truth.json` (from Step 2)
- `classified_motormount.json` (pipeline output)

Compare each ground truth operation against pipeline detections.
Classify each discrepancy:
- **GROUPING** — faces that should be one feature are split
- **TAXONOMY** — wrong feature type label
- **MISSED** — in ground truth, not detected
- **EXTRA** — detected by pipeline, not in ground truth (false positive)

Output `audit/accuracy_breakdown_motormount.txt`:
```
Feature Type          | Expected | Detected | Grouping | Taxonomy | Missed | Extra
----------------------|----------|----------|----------|----------|--------|------
through_hole          |    X     |    X     |    X     |    X     |   X    |   X
blind_hole            |    X     |    X     |    X     |    X     |   X    |   X
pocket_rectangular    |    X     |    X     |    X     |    X     |   X    |   X
...
TOTAL                 |    X     |    X     |    X     |    X     |   X    |   X

Overall accuracy: X%
```

### Step 6 — Fix GROUPING errors (deterministic only)
For every GROUPING error:
- Trace to the rule in `cluster_features.py` or `geometry_utils.py`
- Fix only if the correct behaviour is geometrically unambiguous
- Commit each fix separately:
  `fix: correct wall face grouping for Motor Mount pocket [G6]`

Stop condition: if fixing requires changing core BFS traversal logic, flag in
FINDINGS.md as "requires architectural decision" — do NOT change overnight.

### Step 7 — Fix TAXONOMY errors (deterministic only)
For every TAXONOMY error:
- Locate the rule in `classify_features.py`
- Fix only if the correct label is unambiguous from geometry
- Commit separately:
  `fix: reclassify counterbore detection threshold for Motor Mount`

### Step 8 — Re-run pipeline after fixes
Re-run on Motor Mount STEP. Save as `*_motormount_postfix.*`.
Regenerate accuracy breakdown as `audit/accuracy_breakdown_motormount_postfix.txt`.

### Step 9 — Write FINDINGS_feature_recognition.md

---

## Output files required

| File | Description |
|------|-------------|
| `audit/motor_mount_ground_truth.json` | Extracted ground truth from setup sheets |
| `audit/gcode_tool_summary.json` | Tool sequences from MPF files |
| `audit/accuracy_breakdown_motormount.txt` | Pre-fix accuracy by feature type |
| `audit/accuracy_breakdown_motormount_postfix.txt` | Post-fix accuracy |
| `FINDINGS_feature_recognition.md` | Full written report |

---

## FINDINGS_feature_recognition.md template

```markdown
# Feature Recognition Audit — Motor Mount
Date: [date]

## Ground truth established
Total setups: 4
Total operations: [N] (from setup sheets)
Unique tools: [N]
PDF readability: MACHINE READABLE / NOT MACHINE READABLE

## Accuracy results
Pre-fix: [X]% overall | see accuracy_breakdown_motormount.txt
Post-fix: [X]% overall | see accuracy_breakdown_motormount_postfix.txt

## Fixes applied
1. [Description — file changed — error resolved]
2. ...

## Issues requiring human decision
1. [GROUPING/TAXONOMY/MISSED] — [feature] — [description of ambiguity]

## Recommended next steps (P0/P1/P2)
```

---

## What NOT to do tonight
- Do NOT modify `process_selection.py`, `tool_selection.py`, or `parameter_calculation.py`
- Do NOT add new feature types without a concrete Motor Mount example showing the gap
- Do NOT commit to `main`
- Do NOT skip Step 2 — running the pipeline without ground truth first makes the comparison meaningless

---

## Hard stop conditions
- STEP file not found at the specified path → stop, write FINDINGS.md
- Pipeline errors at feature_extraction.py → stop, write FINDINGS.md
- Setup sheet PDFs are completely unreadable AND cannot be interpreted visually → stop, write FINDINGS.md
