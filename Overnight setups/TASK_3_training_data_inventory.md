# TASK 3 — Training Data Inventory: PMPL + G-code Pairs

**Session type:** Inventory → Audit → Report  
**Time estimate:** 2–3 hours  
**Git branch:** `feature/training-data-inventory`  
**Output:** `training_data_inventory.csv` + `FINDINGS_training_data.md`

---

## Context

ShiaanX is building a closed-loop intelligence layer that will eventually learn from
real machining jobs to improve CAPP accuracy. The ideal training data pair is:

  **PMPL file** (PowerMill project) — complete ground truth for tool selection,
  setup sequencing, and CAM strategy decisions

  **+**

  **G-code file** (MPF format for Siemens 828D, or Fanuc NC format) — provides
  actual cutting parameters: feeds, speeds, depths of cut as executed on the machine

Together, PMPL + G-code is a complete supervision signal. STEP/SLDPRT vendor files
alone are NOT training data — they are pure geometry with no CAM intent embedded.

Before building anything on the intelligence layer, we need to know:
- How many complete PMPL + G-code pairs exist?
- What parts / jobs do they cover?
- Is there enough variety to train anything meaningful?

This audit answers those questions. No model building happens tonight.

---

## Objective

Locate every PMPL file and every G-code file in the project. For each, determine
whether a matching pair exists. Produce a CSV inventory and a written findings report.

---

## Inputs — verify these exist before starting

```
Likely locations to check (search all of these):
  - The main project directory and all subdirectories
  - MinIO buckets (check bucket listing from TASK 2 if it ran first)
  - Any /data/, /jobs/, /orders/, /parts/, /cam/, /nc/ directories
  - Network drives or shared folders if accessible

File extensions to search for:
  PMPL files:    *.pmpl, *.ppf, *.pmpx    (PowerMill project formats)
  G-code files:  *.mpf, *.spf             (Siemens MPF/SPF format)
                 *.nc, *.cnc, *.tap       (Fanuc / generic NC formats)
  Setup sheets:  *setup*.pdf, *SETUP*.pdf (may contain structured operation data)
  SolidCAM:      *.prz                    (SolidCAM project — lower value, no CAM params)
  Mastercam:     *.mcam                   (Mastercam project)
```

---

## Step-by-step instructions

### Step 1 — Set up the branch
```bash
git checkout main
git pull  
git checkout -b feature/training-data-inventory
```

### Step 2 — Find all CAM and NC files
Run a filesystem search from the project root (and home directory):

```bash
# Find all relevant file types
find ~ -type f \( \
  -name "*.pmpl" -o -name "*.ppf" -o -name "*.pmpx" \
  -o -name "*.mpf" -o -name "*.spf" \
  -o -name "*.nc" -o -name "*.cnc" -o -name "*.tap" \
  -o -name "*.prz" -o -name "*.mcam" \
\) 2>/dev/null | sort

# Also search for setup sheet PDFs
find ~ -type f -iname "*setup*" -name "*.pdf" 2>/dev/null
```

Save the full output to `audit/file_discovery.txt`.

**If no PMPL files are found at all:** Write this in FINDINGS.md and skip to Step 5.
Do not proceed with building anything — this is the critical decision gate.

### Step 3 — Inspect each PMPL file
For each `.pmpl` file found, extract the following information.
PMPL files are ZIP archives — use Python's `zipfile` module to inspect:

```python
import zipfile
import os
import json

pmpl_path = "path/to/file.pmpl"

with zipfile.ZipFile(pmpl_path, 'r') as z:
    # List all internal files
    file_list = z.namelist()
    print("Internal files:", file_list)
    
    # Try to read the main project XML or JSON
    for f in file_list:
        if f.endswith('.xml') or f.endswith('.json'):
            try:
                content = z.read(f).decode('utf-8', errors='replace')
                print(f"=== {f} (first 500 chars) ===")
                print(content[:500])
            except:
                print(f"Could not read {f}")
```

For each PMPL, extract and record:
- Filename and full path
- Part name / job ID (from internal XML/metadata if available)
- Number of toolpaths (proxy for number of operations)
- Number of tools referenced
- Material if stated
- Any timestamp metadata

### Step 4 — Inspect each G-code file
For each `.mpf` or `.nc` file found, parse the header and body to extract:

```python
def parse_gcode_summary(filepath):
    """Extract key metadata from a G-code file."""
    summary = {
        'filepath': filepath,
        'filename': os.path.basename(filepath),
        'file_size_bytes': os.path.getsize(filepath),
        'line_count': 0,
        'tool_changes': [],          # T[number] occurrences
        'estimated_ops': 0,
        'has_feeds': False,          # F[value] present
        'has_speeds': False,         # S[value] present
        'controller_hint': None,     # 'siemens' if MPF, 'fanuc' if .nc
        'part_name_from_header': None
    }
    
    with open(filepath, 'r', errors='replace') as f:
        lines = f.readlines()
    
    summary['line_count'] = len(lines)
    
    for line in lines[:20]:  # Header comments often contain part name
        if line.startswith(';') or line.startswith('('):
            summary['part_name_from_header'] = line.strip()
            break
    
    for line in lines:
        if line.strip().startswith('T') and 'M6' in line:
            tool_num = line.strip().split('T')[1].split()[0].strip()
            summary['tool_changes'].append(tool_num)
        if 'F' in line and any(c.isdigit() for c in line):
            summary['has_feeds'] = True
        if 'S' in line and any(c.isdigit() for c in line):
            summary['has_speeds'] = True
    
    summary['estimated_ops'] = len(set(summary['tool_changes']))
    return summary
```

### Step 5 — Match PMPL files to G-code files
Attempt to match each PMPL to a corresponding G-code file. Matching criteria (in order):
1. Same job ID or part number in the filename or internal metadata
2. Same part name in directory structure (e.g., both in a `/RKSE-004-057/` folder)
3. Similar tool count (within ±2 tools)

Do NOT force matches. If unsure, mark as UNMATCHED.

### Step 6 — Write the inventory CSV
Create `training_data_inventory.csv` with one row per discovered PMPL file:

```
job_id, part_name, pmpl_path, pmpl_tool_count, pmpl_op_count, pmpl_material,
gcode_path, gcode_tool_changes, gcode_has_feeds, gcode_has_speeds,
pair_status, notes
```

`pair_status` values:
- `COMPLETE` — PMPL + G-code matched, both have meaningful data
- `PMPL_ONLY` — PMPL found, no matching G-code
- `GCODE_ONLY` — G-code found, no matching PMPL
- `INCOMPLETE` — matched but G-code missing feeds/speeds

### Step 7 — Also check setup sheet PDFs
For any setup sheet PDFs found, note them separately in `audit/setup_sheets.txt`:
- Filename, path, file size
- Page count if readable
These are supplementary training data (operation sequences, QC callouts) —
not a substitute for PMPL+G-code pairs, but useful.

### Step 8 — Write FINDINGS_training_data.md

---

## Output files required (all committed to branch)

| File | Description |
|------|-------------|
| `audit/file_discovery.txt` | Raw filesystem search results |
| `training_data_inventory.csv` | One row per PMPL, with match status |
| `audit/setup_sheets.txt` | List of any setup sheet PDFs found |
| `FINDINGS_training_data.md` | Written findings and recommendation |

---

## FINDINGS_training_data.md template

```markdown
# Training Data Inventory — Findings
Date: [date]

## Summary
Total PMPL files found: [N]
Total G-code files found: [N]
Complete pairs (PMPL + G-code with feeds/speeds): [N]
PMPL-only: [N]
G-code-only: [N]

## Complete pairs breakdown
| Job ID | Part | Ops | Tools | Material |
|--------|------|-----|-------|----------|
| ...    | ...  | ... | ...   | ...      |

## Data quality assessment
[Are the G-code files complete? Do they have feeds and speeds, or are they just toolpath geometry?]
[Are the PMPL files from a consistent CAM software version?]
[Is there enough variety — different materials, part complexities, feature types?]

## Viability verdict
[ ] VIABLE — X complete pairs, sufficient variety to begin intelligence layer design
[ ] MARGINAL — X complete pairs but limited variety; need to collect more before building
[ ] NOT VIABLE — fewer than 5 complete pairs; do not invest in intelligence layer until more data exists

## Fusion 360 subscription decision
[Based on data volume above:]
If VIABLE: Fusion 360 subscription is NOT urgent — build first on real data
If MARGINAL: Fusion 360 Gallery Dataset (free, open source) can supplement real data 
              before committing to subscription — check github.com/AutodeskAILab/Fusion360GalleryDataset
If NOT VIABLE: Prioritise collecting real PMPL+G-code pairs from the next 10 jobs
              before any ML investment

## Recommended next step
[One concrete action for the human to take based on the above]
```

---

## What NOT to do tonight

- Do NOT build any machine learning model or training pipeline
- Do NOT write any data to files you did not create (read-only on all source files)
- Do NOT download the Fusion 360 Gallery Dataset or any external dataset
- Do NOT design the intelligence layer architecture — that depends on the inventory result
- Do NOT attempt to parse binary PMPL files if the zipfile approach fails —
  log "PMPL format not parseable" and move on

---

## Hard stop conditions

Stop immediately and write FINDINGS.md if:
- Zero PMPL files are found anywhere — this is the most important finding possible
- Filesystem search takes more than 30 minutes (may indicate very large storage — sample instead)
- Cannot read any PMPL file (format issue) — note and move on, do not try to reverse-engineer
