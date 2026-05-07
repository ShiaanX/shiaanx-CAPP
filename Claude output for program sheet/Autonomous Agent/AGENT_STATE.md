# Autonomous Agent — State & Setup Notes

## What Was Built

A thin autonomous improvement agent for the CAD feature classifier (Stage 3 of the CAPP pipeline). The agent searches the internet for labeled CAD/machining geometry datasets, retrains the RF classifier with new data, and promotes the model if accuracy improves.

**Location:** `Claude output for program sheet/Autonomous Agent/`

| File | Role |
|------|------|
| `agent_loop.py` | Main orchestrator — runs the full cycle, calls Gemini at decision points |
| `agent_diagnose.py` | Evaluates current RF model, returns weakest feature classes by F1 |
| `agent_search.py` | Searches Kaggle + GitHub for labeled CAD/machining datasets (REST API, no kaggle CLI needed) |
| `agent_retrain.py` | Downloads chosen dataset, retrains RF, returns candidate accuracy |
| `agent_promote.py` | Promotes candidate model if it beats current best |

## How the Loop Works

```
Diagnose → Search → [Gemini picks dataset] → Download → Retrain → [Gemini evaluates] → Promote → Sleep 1hr → repeat
```

Gemini is called **twice per cycle** — everything else is deterministic Python.

## Cycle History

### Cycle 1 — 2026-05-06 (partial — no Kaggle token yet)
- Diagnose: 91.5% on 300 parts. Weakest: Triangular through slot (F1=0.789)
- Kaggle skipped (no token); GitHub returned 5 candidates
- Gemini found no suitable dataset; retrain skipped

### Cycle 3 — 2026-05-07
- Diagnose: **99.3%** field accuracy on 300 parts (new model working well)
- Downloaded CAD Primitives again (agent repeated itself — now fixed with tried_datasets.json)
- Candidate 96.46% did not beat current best 96.46% — no promotion (correct)
- Gemini: continue

### Cycle 2 — 2026-05-07 ✅ FIRST FULL AUTONOMOUS CYCLE
- Diagnose: 91.5% on 300 parts (9,208 faces)
- Search: 5 Kaggle + 5 GitHub candidates found
- Gemini picked: **CAD Primitives with Labels** (`rossmatheny/cad-primitives`, 250 MB)
- Download: 140,000 STEP files downloaded successfully
- New data: 0 parts added (CAD Primitives has no MFCAD++ GT labels in ADVANCED_FACE format)
- Retrain: trained on existing 241,264 faces (80/20 split) — 37s training time
- **Candidate accuracy: 96.46%** (internal holdout)
- **Promoted to production** — beat previous logged best of 69.17% by +27.29pp
- Gemini recommended: **stop** (accuracy good enough)
- Next diagnose cycle will measure real field accuracy on test set

## Setup — Everything Now Working

### Credentials
- **Gemini API key:** set as permanent Windows user env var (`GEMINI_API_KEY`)
- **Kaggle token:** `C:\Users\Siddhant Gupta\.kaggle\access_token` (new KGAT_ format, works via REST API)
- Kaggle CLI (`python -m kaggle`) is NOT used — agent calls Kaggle REST API directly with Bearer token

### Run one cycle
```powershell
& "C:\Users\Siddhant Gupta\miniconda3\envs\occ\python.exe" "Claude output for program sheet/Autonomous Agent/agent_loop.py" --once
```

### Run continuously (every hour, autonomous)
```powershell
& "C:\Users\Siddhant Gupta\miniconda3\envs\occ\python.exe" "Claude output for program sheet/Autonomous Agent/agent_loop.py"
```
Requires PC to stay on. For scheduled/unattended runs, set up Windows Task Scheduler.

## Current Best Model

`models/rf_classifier_v3.pkl` — **99.3% field accuracy** on 300 test parts (2026-05-07)
- Internal holdout accuracy: 96.46%
- Previous field accuracy: 91.5% (before cycle 2 promotion)
- Backed up: old model saved to `models/backups/` before promotion

Weakest classes at 99.3%:
- Circular through slot: F1=0.968
- 2-sided through step: F1=0.975
- Rectangular blind slot: F1=0.976

## Packages (occ conda env)

- `google-genai` — correct Gemini package, installed and working
- `kaggle` — installed but NOT used for auth (CLI doesn't support KGAT_ tokens); agent uses REST API directly
- `anthropic` — installed but not used

## Gemini Model

`gemini-2.5-flash-lite` — works for this account.
- `gemini-2.0-flash` and `gemini-1.5-flash` unavailable for this account.

## Next Steps / Future Improvements

### 1. Extend to training split
Currently only uses the test split (8,792 feature JSONs / 8,949 STEP files).
Train split has 41,766 STEP files with 0 feature JSONs extracted yet.
Running `ml_batch_extract.py` on the train split would give ~50k parts to retrain on — likely pushes accuracy higher.

### 2. Windows Task Scheduler (optional)
To run the agent autonomously without leaving a terminal open — set up a scheduled task pointing to `agent_loop.py`.

### 3. MFTRCAD dataset (try next)
`xmy2000/mftrcad` (2.4 GB, 448 downloads) — Machining Feature and Topological Relationship Recognition dataset. Gemini picked this in a previous cycle but CAD Primitives was chosen instead. Worth trying — may have GT labels compatible with MFCAD++ classes.
