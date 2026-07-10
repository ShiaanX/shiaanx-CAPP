# Overnight Task — Fixture 3D Viewer Tab

## Context (read this first)

Read `CLAUDE.md` and `SESSION_STATE.md` in the repo root before doing anything else.

**What this task builds:** A "Fixture" tab in the ShiaanX frontend that shows the part and its soft jaws together in 3D — so a machinist can visually verify the clamping setup before running the job.

---

## Architecture to understand before starting

**Frontend** (`capp-frontend/src/`):
- Main viewer page: `src/pages/CappViewer.js` — 3-panel layout: left = 3D iframe, right = tab panel
- Existing tabs wired in CappViewer.js: Overview, Strategy, Program Sheet
- Other tab files exist but are NOT wired in: `FeatureMapTab.js`, `ClosedLoopTab.js`, etc.
- 3D viewer: an `<iframe src="/step-viewer.html?url=...">` — loads a single STEP file via OpenCASCADE WASM
- Tab components live in: `src/components/viewer/tabs/`
- Service layer: `src/services/cappService.js` — `getStepUrl(jobId)` returns the part STEP URL

**Backend** (`capp_service/main.py` — FastAPI):
- `GET /jobs/{job_id}/step` — serves the part STEP file
- `GET /jobs/{job_id}/output/{stage}` — serves JSON pipeline outputs
- `GET /jobs/{job_id}/pdf` — serves the program sheet PDF
- Jobs stored in `capp_service/jobs/{job_id}/` — each job folder contains the STEP file and pipeline outputs

**Fixture outputs** (written by the previous overnight session, `feature/fixture-design` branch):
- `*_fixture_spec.json` — fixture specification per setup (jaw type, opening, parallels, soft jaw flag, etc.)
- `*_setup{N}_soft_jaw_LEFT.step` and `*_setup{N}_soft_jaw_RIGHT.step` — soft jaw STEP solids
- These are written to the same job folder as the part STEP during pipeline run

**Git:** Work on a new branch `feature/fixture-viewer`. First `git pull origin main` and `git merge origin/feature/fixture-design` to get the fixture files from the previous session.

---

## Goal

Build the Fixture tab so:
1. **Fixture spec panel** — shows structured fixture data per setup (type, jaw opening, parallels, WCS zero, soft jaw flag, machinist notes)
2. **3D assembly viewer** — shows part + left jaw + right jaw together in a single 3D scene, colour-coded (part = steel blue, jaws = orange), for the selected setup
3. **Setup selector** — dropdown or buttons to switch between setups
4. Works within the existing React + iframe 3D viewer architecture

---

## Step 1 — Add backend endpoints to `capp_service/main.py`

Add three new endpoints. Study the existing endpoint patterns in `main.py` before writing.

**1a. Fixture spec endpoint:**
```python
@app.get('/jobs/{job_id}/fixture')
def get_fixture_spec(job_id: str):
    """Return the fixture_spec JSON for this job."""
```
- Look in the job folder for `*_fixture_spec.json`
- Return it as JSON
- If not found, return `{"error": "fixture spec not generated", "setups": []}`

**1b. Soft jaw STEP endpoint:**
```python
@app.get('/jobs/{job_id}/jaw/{setup_index}/{side}')
def get_jaw_step(job_id: str, setup_index: int, side: str):
    """Serve the soft jaw STEP file. side = 'left' or 'right'."""
```
- Look for `*_setup{setup_index}_soft_jaw_{side.upper()}.step` in the job folder
- Return as `FileResponse` with `media_type='application/octet-stream'`
- 404 if not found

**1c. Fixture assembly endpoint** — the key one:
```python
@app.get('/jobs/{job_id}/fixture_assembly/{setup_index}')
def get_fixture_assembly(job_id: str, setup_index: int):
    """
    Merge part STEP + left jaw STEP + right jaw STEP into a single
    assembly STEP and return it. Colours are embedded as STEP product names
    so the viewer can colour-code by compound name.
    """
```

Use PythonOCC (`C:\Users\Siddhant Gupta\miniconda3\envs\occ\python.exe`) via a subprocess call — FastAPI runs on standard Python, not the occ env. Do it like this:

```python
import subprocess, tempfile, os

def get_fixture_assembly(job_id: str, setup_index: int):
    job_dir = JOBS_DIR / job_id
    part_step = next(job_dir.glob('*.step'), None)  # the original part
    left_jaw = next(job_dir.glob(f'*_setup{setup_index}_soft_jaw_LEFT.step'), None)
    right_jaw = next(job_dir.glob(f'*_setup{setup_index}_soft_jaw_RIGHT.step'), None)

    if not part_step:
        raise HTTPException(404, 'Part STEP not found')

    # Write a small Python script to a temp file, run it in occ env
    script = f"""
import sys
from OCC.Core.STEPControl import STEPControl_Reader, STEPControl_Writer, STEPControl_AsIs
from OCC.Core.BRep import BRep_Builder
from OCC.Core.TopoDS import TopoDS_Compound
from OCC.Core.TDocStd import TDocStd_Document
from OCC.Core.XCAFDoc import XCAFDoc_DocumentTool
from OCC.Core.XCAFApp import XCAFApp_Application

# Simple approach: write all shapes to one STEP file as separate shells
reader = STEPControl_Reader()
writer = STEPControl_Writer()

# Load and transfer part
reader.ReadFile(r'{part_step}')
reader.TransferRoots()
part_shape = reader.OneShape()
writer.Transfer(part_shape, STEPControl_AsIs)

# Load and transfer left jaw if exists
left_path = r'{left_jaw or ""}'
if left_path:
    reader2 = STEPControl_Reader()
    reader2.ReadFile(left_path)
    reader2.TransferRoots()
    writer.Transfer(reader2.OneShape(), STEPControl_AsIs)

# Load and transfer right jaw if exists
right_path = r'{right_jaw or ""}'
if right_path:
    reader3 = STEPControl_Reader()
    reader3.ReadFile(right_path)
    reader3.TransferRoots()
    writer.Transfer(reader3.OneShape(), STEPControl_AsIs)

writer.Write(sys.argv[1])
"""
    out_path = str(job_dir / f'fixture_assembly_{setup_index}.step')
    tmp = tempfile.NamedTemporaryFile(suffix='.py', delete=False, mode='w')
    tmp.write(script)
    tmp.close()
    try:
        subprocess.run(
            [r'C:\Users\Siddhant Gupta\miniconda3\envs\occ\python.exe', tmp.name, out_path],
            timeout=30, check=True, capture_output=True
        )
    finally:
        os.unlink(tmp.name)

    if not os.path.exists(out_path):
        raise HTTPException(500, 'Assembly generation failed')
    return FileResponse(out_path, media_type='application/octet-stream')
```

Cache the result — if `fixture_assembly_{setup_index}.step` already exists in the job folder, skip regeneration and serve it directly.

Also add `getFixtureUrl`, `getJawUrl`, `getFixtureSpecUrl` to `cappService.js`:
```js
export function getFixtureAssemblyUrl(jobId, setupIndex) {
  return `${api.defaults.baseURL}/jobs/${jobId}/fixture_assembly/${setupIndex}`;
}
export async function getFixtureSpec(jobId) {
  return api.get(`/jobs/${jobId}/fixture`);
}
```

---

## Step 2 — Create `FixtureTab.js`

**File:** `capp-frontend/src/components/viewer/tabs/FixtureTab.js`

**Props:** `{ jobId, viewerRef, active, onLoadAssembly }`
- `jobId` — current job
- `active` — whether this tab is visible (use to defer data loading)
- `onLoadAssembly(url)` — callback that tells CappViewer.js to load a new URL in the 3D viewer iframe

**State:**
- `fixtureSpec` — the full fixture spec JSON (fetched on mount)
- `selectedSetup` — index of currently selected setup (default 0)
- `loading` — bool

**On mount / when active:** fetch fixture spec via `getFixtureSpec(jobId)`. If error or no data, show a "Fixture data not available — re-run pipeline to generate" message.

**Layout:**

```
┌──────────────────────────────────────────┐
│  FIXTURE SETUP                           │
│  [Setup 1] [Setup 2] [Setup 3]  ← tabs  │
├──────────────────────────────────────────┤
│  Type          Vise (Soft Jaws)          │
│  Jaw Opening   75 mm                     │
│  Jaw Height    38 mm                     │
│  Parallels     10 mm                     │
│  Clamped       +X, -X                    │
│  Rest Face     -Z                        │
│  Z Zero        Top of stock              │
│  WCS XY Zero   Centre of part            │
├──────────────────────────────────────────┤
│  ⚠ SOFT JAWS REQUIRED                   │  ← only if soft_jaw_required
│  Jaw files generated for this setup      │
├──────────────────────────────────────────┤
│  SETUP NOTES                             │
│  • Zero off top face of raw billet       │
│  • Minimum 25mm jaw engagement each side │
├──────────────────────────────────────────┤
│  [Load in 3D Viewer]   ← button          │
└──────────────────────────────────────────┘
```

**"Load in 3D Viewer" button:**
When clicked, call `onLoadAssembly(getFixtureAssemblyUrl(jobId, selectedSetup))`. This triggers the iframe to load the assembly STEP showing part + jaws together.

**Setup tabs:** Small pill buttons at the top (Setup 1, Setup 2, etc.) — switching updates `selectedSetup` and calls `onLoadAssembly` automatically.

**Colour note in UI:** Add a small legend below the viewer button:
```
🔵 Part   🟠 Left Jaw   🟠 Right Jaw
```
(The viewer shows them as separate shells — the legend explains what's what. Full colour-coding in the viewer is a future enhancement.)

**Style:** Match the existing tab style — use the same CSS variables/classes as `OverviewTab.js` and `StrategyTab.js`. Dark headers (`#1a1a2e` background, white text), clean table rows, no external UI libraries.

---

## Step 3 — Wire FixtureTab into `CappViewer.js`

**3a. Add to tabs array:**
```js
import FixtureTab from '../components/viewer/tabs/FixtureTab';

const tabs = [
  { key: 'overview',      label: 'Overview' },
  { key: 'strategy',      label: 'Strategy' },
  { key: 'program_sheet', label: 'Program Sheet' },
  { key: 'fixture',       label: 'Fixture' },   // ← add this
];
```

**3b. Add state for viewer URL** (so the iframe URL can be changed dynamically):
```js
const [viewerUrl, setViewerUrl] = useState(null);

// Set default once job is complete
useEffect(() => {
  if (job?.status === 'COMPLETE' && !viewerUrl) {
    setViewerUrl(getStepUrl(jobId));
  }
}, [job]);
```

**3c. Update the iframe** to use `viewerUrl` instead of hardcoded `stepUrl`:
```jsx
<iframe
  ref={viewerIframeRef}
  src={viewerUrl ? `/step-viewer.html?url=${encodeURIComponent(viewerUrl)}` : ''}
  ...
/>
```

**3d. Pass callback to FixtureTab:**
```jsx
{activeTab === 'fixture' && (
  <FixtureTab
    jobId={jobId}
    active={activeTab === 'fixture'}
    onLoadAssembly={(url) => setViewerUrl(url)}
  />
)}
```

**3e. Reset viewer URL when switching back to other tabs** — add `onClick` to tab buttons:
```js
onClick={() => {
  setActiveTab(t.key);
  if (t.key !== 'fixture') setViewerUrl(getStepUrl(jobId));
}}
```

---

## Step 4 — Test end-to-end

Start the CAPP service and frontend:
```powershell
# Terminal 1 — backend
cd "C:\Users\Siddhant Gupta\Documents\ShiaanX\capp_service"
& "C:\Users\Siddhant Gupta\miniconda3\envs\occ\python.exe" -m uvicorn main:app --reload --port 8001

# Terminal 2 — frontend
cd "C:\Users\Siddhant Gupta\Documents\ShiaanX\capp-frontend"
npm start
```

Use the Motor Mount demo job that already exists:
- Job folder: `capp_service/jobs/` — find the most recent Motor Mount job (look for `MOTOR_MOUNT.step` inside)
- If `*_fixture_spec.json` is not in that job folder, copy it from `Claude output for program sheet/Manufactured parts/Motor Mount/MOTOR MOUNT_fixture_spec.json`
- Similarly copy the soft jaw STEP files if present

Verify:
1. Fixture tab appears in the tab bar
2. Fixture spec loads and displays correctly per setup
3. "Load in 3D Viewer" button triggers the assembly STEP to load in the iframe
4. Part + jaws appear in the viewer (as separate shells, even if same colour is fine for now)
5. Switching setups updates the assembly
6. Switching to another tab resets the viewer to the part-only STEP

---

## Step 5 — Update SESSION_STATE.md and write session update

**5a. Write `audit/SESSION_UPDATE_fixture_viewer.md`:**
```markdown
# Session Update — Fixture 3D Viewer Tab

**Date:** 2026-06-24
**Branch:** feature/fixture-viewer

## What was completed
- [ ] Step 1: Backend endpoints (fixture spec, jaw STEP, assembly)
- [ ] Step 2: FixtureTab.js component
- [ ] Step 3: CappViewer.js wiring
- [ ] Step 4: End-to-end test

## What the tab looks like
[describe what you see — fixture spec fields, setup selector, viewer behaviour]

## Assembly generation
[describe — does it work? how long does it take? any OCC issues?]

## Blockers / deferred items
[anything that didn't complete]

## Files created / modified
[list all files touched]
```

**5b. Update `SESSION_STATE.md`** in the repo root:

Add a new subsection under the existing `## Fixture Design Module` section (added by the previous session). Title it `### Fixture 3D Viewer Tab` and include:
- What was built (FixtureTab.js, backend endpoints, CappViewer.js changes)
- How the assembly viewer works (OCC subprocess merge → single STEP → iframe)
- How to use it (Fixture tab → click "Load in 3D Viewer")
- Branch: `feature/fixture-viewer`
- Any known limitations

---

## Commit instructions

```bash
cd "C:\Users\Siddhant Gupta\Documents\ShiaanX"
git checkout -b feature/fixture-viewer
git merge origin/feature/fixture-design   # get fixture files from previous session
# ... do the work ...
git add capp-frontend/src/ capp_service/main.py audit/
git commit -m "feat(fixture-viewer): 3D assembly tab showing part + soft jaws"
git push origin feature/fixture-viewer
```

Do NOT push to main.

---

## What NOT to do

- Do not rewrite the existing 3D viewer (`step-viewer.html` or the OpenCASCADE WASM setup) — just pass it a new URL
- Do not add colour-coding inside the STEP viewer — that requires XCAF/STEP colour attributes which are complex; the legend text is enough for now
- Do not run the full pipeline again — use the existing Motor Mount outputs
- Do not modify any pipeline Python scripts
