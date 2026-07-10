# TASK 4 — CAPP Rule Sheet Expansion (Machinery's Handbook + Motor Mount Validation)

**Session type:** Research → Structured output  
**Time estimate:** 3–5 hours  
**Git branch:** `feature/rule-sheet-expansion`  
**Output:** `proposed_rules.json` + `FINDINGS_rule_expansion.md`

---

## Context

ShiaanX has a living rule sheet that drives `process_selection.py` — the module that
assigns an ordered machining operation sequence to each detected feature.

The rule sheet has known gaps. Tonight's task is to:
1. Read the Motor Mount setup sheets as empirical ground truth — what operations
   were ACTUALLY used on a real production part
2. Cross-reference against Machinery's Handbook for the underlying principles
3. Propose new rules as structured JSON for any gap found

The Motor Mount setup sheets are more valuable than Machinery's Handbook alone —
they are real validated decisions made by an experienced programmer on actual parts.
Machinery's Handbook provides the "why" behind those decisions.

---

## Inputs — all confirmed paths

```
Motor Mount setup sheets (PRIMARY — read these first):
  G:\My Drive\Closed Loop\Motor Mount\CAM files\MOTOR_MOUNT_1_SETUP_SHEET.pdf
  G:\My Drive\Closed Loop\Motor Mount\CAM files\MOTOR_MOUNT_2_SETUP_SHEET.pdf
  G:\My Drive\Closed Loop\Motor Mount\CAM files\MOTOR_MOUNT_3_FINISH_SETUP_SHEET.pdf
  G:\My Drive\Closed Loop\Motor Mount\CAM files\MOTOR_MOUNT_4_SETUP_SHEET.pdf

Motor Mount G-code (feeds and speeds as actually run):
  G:\My Drive\Closed Loop\Motor Mount\CAM files\MOTOR_MOUNT_1_SETUP.MPF
  G:\My Drive\Closed Loop\Motor Mount\CAM files\MOTOR_MOUNT_2_SETUP.MPF
  G:\My Drive\Closed Loop\Motor Mount\CAM files\MOTOR_MOUNT_3_FINISH_SETUP.MPF
  G:\My Drive\Closed Loop\Motor Mount\CAM files\MOTOR_MOUNT_4_SETUP.MPF

Pipeline root:
  [FILL IN — path to your Python CAPP code, where CLAUDE.md lives]
  Key files: process_selection.py, tool_database.json, CLAUDE.md
```

---

## Materials in scope

```
Aluminium 6061-T6
Aluminium 7075-T6
Mild Steel (EN8 / 1045)
Stainless Steel 304 / 316
```

Do NOT propose rules for titanium, Inconel, or composites.

---

## Operations in scope

```
Drilling: centre drill, twist drill (through + blind), peck drill, ream, bore, tap,
          counterbore, countersink
Milling:  face mill, peripheral/profile mill, pocket (rectangular + circular),
          slot (open + closed), step/shoulder, chamfer, thread mill
```

---

## Step-by-step instructions

### Step 1 — Set up the branch
```bash
git checkout main
git pull
git checkout -b feature/rule-sheet-expansion
```

### Step 2 — Read and extract Motor Mount setup sheets
Use pdfplumber or PyMuPDF to read all 4 setup sheet PDFs.
Write `audit/setup_sheet_extract.py` to extract per-setup:
- Each operation in sequence
- Tool number and description
- Feeds and speeds if listed
- Any fixture or datum notes

Save to `audit/motor_mount_operations.json`:
```json
{
  "setup_1": {
    "operations": [
      {
        "seq": 1,
        "op_type": "face_milling",
        "tool": "T01 — 50mm face mill",
        "feed_mmpm": 800,
        "speed_rpm": 3000,
        "notes": "datum face"
      }
    ]
  }
}
```

If PDFs are not machine-readable, read them visually and write the JSON manually.
This step is mandatory — do not skip.

### Step 3 — Extract actual feeds and speeds from MPF files
Parse each MPF file to extract F (feed) and S (speed) values per tool call:

```python
import re

def extract_params_from_mpf(filepath):
    params = []
    current_tool = None
    with open(filepath, 'r', errors='replace') as f:
        for line in f:
            tool_match = re.search(r'T(\d+)', line)
            feed_match = re.search(r'F(\d+\.?\d*)', line)
            speed_match = re.search(r'S(\d+\.?\d*)', line)
            if tool_match:
                current_tool = tool_match.group(1)
            if feed_match and speed_match and current_tool:
                params.append({
                    'tool': current_tool,
                    'feed': float(feed_match.group(1)),
                    'speed': float(speed_match.group(1))
                })
    return params
```

Save to `audit/motor_mount_actual_params.json`.
These are the real cutting parameters — use them to validate proposed Vc and fz values.

### Step 4 — Read existing process_selection.py
Read `process_selection.py` fully. Build a coverage matrix in
`audit/rule_coverage_matrix.md` — for each material × operation combination,
mark: COVERED / PARTIAL / GAP.

### Step 5 — Propose rules for each gap

Work through materials in this order. Complete each material before moving on:
1. Aluminium 6061-T6 (most common — complete coverage required)
2. Aluminium 7075-T6 (aerospace jobs)
3. Stainless Steel 304 (currently no rules — any stainless job fails)
4. Mild Steel EN8 (fill gaps only)

For each GAP or PARTIAL row, write a proposed rule in `proposed_rules.json`.

**Rule schema — follow exactly:**

```json
{
  "rule_id": "PS-AL6061-REAM-001",
  "status": "PROPOSED",
  "material": "Al 6061-T6",
  "operation": "reaming",
  "trigger_condition": "hole_tolerance <= H7 AND hole_diameter BETWEEN 3 AND 20",
  "operation_sequence": [
    {
      "step": 1,
      "operation": "centre_drill",
      "notes": "Always precede reaming with a drilled hole"
    },
    {
      "step": 2,
      "operation": "twist_drill",
      "diameter_offset_mm": -0.2,
      "notes": "Drill to reaming allowance: nominal minus 0.1–0.3mm"
    },
    {
      "step": 3,
      "operation": "ream",
      "diameter": "nominal"
    }
  ],
  "cutting_parameters": {
    "vc_m_per_min": {"min": 8, "max": 12, "recommended": 10},
    "feed_per_rev_mm": {"formula": "0.3 * diameter_mm"},
    "coolant": "flood"
  },
  "tool_specification": {
    "tool_type": "HSS or carbide reamer",
    "geometry": "straight flute for through holes, spiral for blind"
  },
  "decision_logic": {
    "prefer_reaming_over_boring_when": "diameter < 20mm AND tolerance H7 or tighter",
    "prefer_boring_over_reaming_when": "diameter >= 20mm OR tolerance H6 or tighter"
  },
  "source": {
    "primary": "Machinery's Handbook — Reaming, Speeds and Feeds",
    "motor_mount_validation": "observed in MOTOR_MOUNT_2_SETUP_SHEET.pdf — T04 HSS reamer on 8mm hole",
    "notes": ""
  },
  "confidence": "HIGH",
  "open_issues": [],
  "added_by": "Claude Code — overnight rule expansion"
}
```

**Confidence levels:**
- `HIGH` — Machinery's Handbook citation AND observed in Motor Mount setup sheets
- `MEDIUM` — Machinery's Handbook citation only, not yet seen on a real job
- `LOW` — inferred from general principles, needs validation

### Step 6 — Decision logic rules
Add a `"decision_rules"` section in `proposed_rules.json` covering at minimum:
- Tap vs. thread mill (by thread size, material, through vs. blind)
- Ream vs. bore (by diameter, tolerance, standard vs. non-standard size)
- Peck drilling trigger (depth-to-diameter ratio threshold per material)
- Finish pass trigger (when to add a dedicated finish pass vs. one-pass)

Format same as main rules — source + confidence required for each.

### Step 7 — Write FINDINGS_rule_expansion.md

---

## Output files required

| File | Description |
|------|-------------|
| `audit/motor_mount_operations.json` | Operations extracted from setup sheets |
| `audit/motor_mount_actual_params.json` | Feeds/speeds extracted from MPF files |
| `audit/rule_coverage_matrix.md` | Coverage status per material × operation |
| `proposed_rules.json` | All proposed rules in structured JSON |
| `FINDINGS_rule_expansion.md` | Summary report |

---

## FINDINGS_rule_expansion.md template

```markdown
# Rule Sheet Expansion — Findings
Date: [date]

## Motor Mount setup sheet summary
Operations observed across 4 setups: [list]
Unique tools used: [N]
PDF readability: MACHINE READABLE / NOT MACHINE READABLE

## Rules proposed tonight
Total: [N]
  Al 6061-T6: [N] — coverage now [COMPLETE / PARTIAL]
  Al 7075-T6: [N] — coverage now [COMPLETE / PARTIAL]
  Stainless 304: [N] — coverage now [COMPLETE / PARTIAL]
  Mild Steel: [N] — coverage now [COMPLETE / PARTIAL]

## Confidence breakdown
  HIGH (Handbook + Motor Mount observed): [N]
  MEDIUM (Handbook only): [N]
  LOW (inferred): [N] — flag for Danesh review before implementing

## Still uncovered (ran out of time or genuinely ambiguous)
[List]

## Recommended implementation order
1. [Rule ID] — [reason]
```

---

## What NOT to do tonight
- Do NOT modify `process_selection.py` — proposals only
- Do NOT modify `tool_database.json`
- Do NOT propose rules for out-of-scope materials
- Do NOT write any rule as HIGH confidence without both a Machinery's Handbook
  citation AND a Motor Mount (or other real job) observation to back it up
- Do NOT propose rules for 5-axis simultaneous machining

---

## Hard stop conditions
- `process_selection.py` not found → stop, note path issue in FINDINGS.md
- All 4 setup sheet PDFs completely unreadable (no text, no structure) → stop,
  write FINDINGS.md noting this — do not proceed without empirical ground truth
