# ShiaanX CAPP Frontend — Implementation Plan
_Last updated: 2026-04-27 (session 2 — pipeline working end-to-end)_

---

## What We're Building

A standalone CAPP Part Viewer frontend that lives in this repo (`shiaanx-CAPP`). The dev team will later integrate it into `shiaanx-frontend-admin`. It is **not** built inside the admin or backend repos.

The core product: engineer uploads a STEP file → 8-stage Python pipeline runs → results displayed as an interactive 3D view with Overview and Strategy tabs + downloadable Program Sheet.

**Primary inspiration: Toolpath.ai** (screenshots in `Files for one time reference/`)
**Design reference: shiaanx-frontend-admin** (same visual language — light blue bg, white cards, dark navy icon sidebar, dark blue CTAs)

---

## Decisions Made

### What's already built (don't rebuild)
- Auth (login/register/OTP) — in `shiaanx-frontend-admin` + `shiaanx-backend`
- Admin panel (users, enquiries, orders, vendors) — in `shiaanx-frontend-admin`
- Business backend (Node.js) — in `shiaanx-backend`

### What we build here
- `capp-frontend/` — standalone React app, CAPP viewer only
- `capp_service/` — FastAPI wrapper around the Python pipeline

### 3D Viewer — OpenCascade.js (not glTF)
Lifted from `shiaanx-insta-quote/cad_viewer2.html`. Loads STEP files **natively in the browser** via OpenCascade.js WASM — no server-side conversion to glTF needed. Face-level tessellation already done; face highlighting to be added on top.

---

## 1. Tech Stack

| Layer | Choice | Reason |
|---|---|---|
| Framework | React 18 (Create React App) | Matches existing frontend exactly |
| Language | JavaScript (no TypeScript) | Matches existing frontend |
| Styling | CSS files per component | Matches existing frontend pattern |
| Routing | React Router v7 (HashRouter) | Matches existing frontend |
| HTTP | Axios | Matches existing frontend |
| Icons | React Icons (Feather) | Matches existing frontend |
| 3D viewer | OpenCascade.js + Three.js | Lifted from shiaanx-insta-quote, loads STEP natively |
| Notifications | React Hot Toast | Matches existing frontend |
| Pipeline backend | FastAPI (Python) | Thin wrapper around existing pipeline scripts |

---

## 2. Repo Structure

```
ShiaanX/
├── capp-frontend/                  ← standalone React app
│   ├── public/
│   └── src/
│       ├── components/
│       │   ├── layout/
│       │   │   ├── Sidebar.js
│       │   │   ├── Topbar.js
│       │   │   └── MainLayout.js
│       │   └── viewer/
│       │       ├── StepViewer3D.js     (OpenCascade.js + Three.js)
│       │       ├── ViewerToolbar.js
│       │       ├── PipelineProgress.js
│       │       └── tabs/
│       │           ├── OverviewTab.js
│       │           ├── StrategyTab.js
│       │           └── ProgramSheetTab.js
│       ├── pages/
│       │   ├── Upload.js               (upload STEP file)
│       │   └── CappViewer.js           (main part viewer)
│       ├── services/
│       │   ├── api.js                  (axios instance)
│       │   └── cappService.js          (job CRUD + polling)
│       ├── App.js
│       └── index.js
│
├── capp_service/                   ← FastAPI pipeline wrapper
│   ├── main.py
│   ├── runner.py
│   └── requirements.txt
│
└── Claude output for program sheet/  ← existing pipeline (unchanged)
```

---

## 3. Color & Visual Design

Match `shiaanx-frontend-admin` exactly:
- **Page background:** Light blue `#e8eef7`
- **Cards/panels:** White `#ffffff` with light border/shadow
- **Sidebar:** Dark navy (icon-only on desktop, expands on mobile)
- **Primary CTA:** Dark blue `#1e3a5f`
- **Active nav item:** Blue highlight
- **Feature highlight on 3D model:** Orange `#f97316`
- **Typography:** System font stack (matches existing)
- **Status badges:** Green (complete), blue (processing), red (error)

---

## 4. Routes

```
/                   → redirect to /upload
/upload             → Upload STEP file page
/parts/:jobId       → CAPP Part Viewer (3D + tabs)
```

No auth routes — dev team wires auth during integration into shiaanx-frontend-admin.

---

## 5. Screen Specifications

### 5A. Upload Page (`/upload`)

- Dark navy sidebar (matching admin frontend)
- Center card: drag-and-drop zone for `.step` / `.stp` files
- Part name input (pre-filled from filename)
- Material dropdown (default: Aluminium 6061)
- "Analyse Part" CTA button
- On submit: POST to `capp_service`, redirect to `/parts/:jobId` with progress bar

### 5B. CAPP Part Viewer (`/parts/:jobId`)

```
┌─────────────────────────────────────────────────────────────────┐
│ TOPBAR: [← Back] Part Name          [Download PDF]  [ShiaanX]  │
│         [Overview] [Strategy] [Program Sheet]                   │
├─────────────────────────────────────┬───────────────────────────┤
│                                     │                           │
│   3D VIEWER                         │   RIGHT PANEL             │
│   OpenCascade.js + Three.js         │   (tab-dependent)         │
│                                     │                           │
│   Toolbar: Stock | Axes | Wireframe │                           │
│   Zoom % | Reset view               │                           │
│                                     │                           │
│   [Pipeline progress bar — hidden   │                           │
│    once complete]                   │                           │
└─────────────────────────────────────┴───────────────────────────┘
```

**Tab: Overview** (right panel)
- Part dimensions (X × Y × Z mm)
- Part volume (cm³)
- Stock size (bounding box + 1.5mm)
- Feature count
- Setup count
- Machine type (3 Axis VMC)
- Material
- Machinability badge (green = all machinable)
- Warnings (substituted drills, RPM caps)

**Tab: Strategy** (right panel)
- Collapsible setup sections
- Each setup: operation list (Roughing, Facing Finishing, Finishing Wall, Drilling, etc.)
- Expand operation → cutting conditions:
  - Surface Speed, Feed per Tooth, Stepdown, Stepover
  - Cycle time, MRR, Removal volume
  - Tool name + diameter
- Clicking operation highlights affected features on 3D model (orange)

**Tab: Program Sheet**
- Embedded PDF viewer (browser native `<iframe>`)
- Download button

---

## 6. FastAPI capp_service

```
capp_service/
├── main.py        FastAPI app
│                  POST /jobs       { step_file, part_name, material } → { job_id }
│                  GET  /jobs/{id}  → { status, stage, outputs, pdf_url, warnings }
├── runner.py      Runs pipeline stages 1–8 sequentially in background thread
│                  Updates job status dict after each stage
└── requirements.txt  fastapi, uvicorn, python-multipart, aiofiles
```

Jobs stored in-memory (dict) for now — no database. Files saved to `capp_service/jobs/{job_id}/`.

---

## 7. 3D Viewer Implementation

Based on `cad_viewer2.html` from `shiaanx-insta-quote`:

1. Wrap OpenCascade.js + Three.js logic into `StepViewer3D.js` React component
2. Accept `stepFileUrl` prop — fetches and loads the STEP file
3. During tessellation, track `faceIndex → meshGroup` mapping
4. Expose `highlightFaces(faceIds)` method via `useImperativeHandle`
5. Strategy tab calls `highlightFaces()` when operation selected
6. Toolbar buttons: toggle stock box wireframe, toggle axes, toggle wireframe mode

---

## 8. Implementation Phases (Revised — ~3 days)

### Day 1 — FastAPI service + Upload page
- Scaffold `capp_service/` FastAPI app
- `POST /jobs` endpoint: accepts STEP file, saves to disk, queues pipeline run
- `GET /jobs/{id}` endpoint: returns status + stage outputs
- Scaffold `capp-frontend/` React app (CRA)
- Sidebar + Topbar matching admin frontend design
- Upload page with drag-and-drop

### Day 2 — Part Viewer + Pipeline progress
- `CappViewer.js` page shell (3-panel layout)
- `PipelineProgress.js` — stage pill bar (polling GET /jobs/{id} every 2s)
- `OverviewTab.js` — reads from classified.json + setups.json outputs
- `StrategyTab.js` — reads from params.json, collapsible operations

### Day 3 — 3D Viewer + Program Sheet
- `StepViewer3D.js` — OpenCascade.js + Three.js, wrapped as React component
- Toolbar toggles (wireframe, axes, stock)
- Face highlight on operation select
- `ProgramSheetTab.js` — iframe PDF viewer + download button
- End-to-end test with a real STEP file

---

---

## STATUS AS OF 2026-05-02 (End of Session 5)

### What Is Working ✅
- Full pipeline runs end-to-end (all 9 steps) for a real STEP file and produces a PDF
- Upload page: drag-and-drop, part name, material, submits to FastAPI
- CappViewer: polls job status every 2s, stops on COMPLETE/FAILED
- PipelineProgress pill bar: shows live stage progress (green/spinning/red), stage numbering correct (gap at 6)
- **Overview tab**: part dimensions, stock size, volume, feature count, setups, machine type, machinability badge — all populated from real data
- **Strategy tab**: 24 clusters grouped by setup, collapsible operations with tool info and cutting conditions
- **Download PDF button**: live, fetches from `/jobs/{id}/pdf`
- **3D viewer**: `occt-import-js@0.0.18` via CDN — STEP file loads and renders. `result.meshes` is a flat array; `result.root.meshes` holds indices into it. Both confirmed working in browser.
- FastAPI service (`capp_service/main.py` + `runner.py`) running on port 8001
- `capp-frontend` React app running on port 3000
- Program Sheet tab: iframe wired to `/jobs/{id}/pdf`
- **Face highlighting (Session 5)**: clicking an operation in Strategy tab sends `postMessage` to the 3D viewer iframe, turning the relevant faces orange (`#f97316`). Clicking a different operation clears the previous highlight. Implemented via `cluster.face_indices` from `params.json`.

### What Is NOT Working / Deferred 🔧
1. **pocket_mill tool_dia=0**: Some pocket operations show `tool_diameter_mm=0` and `rpm=None` — tool lookup returning a fallback tool with no diameter. Low priority — upstream tool selection issue.

2. **Extract stage pill not turning green**: Stage completes too fast; PipelineProgress returns `null` on COMPLETE status before the pill renders green. Cosmetic only.

3. **Face highlight index alignment**: `occt-import-js` and PythonOCC should enumerate faces in the same order for standard STEP files, but this has not been tested end-to-end. If highlighted faces look wrong on a real part, the fix is to embed the OCC face index during tessellation in `step-viewer.html`. Low priority — verify on first test.

### 3D Viewer — Session 4 Fix

Replaced opencascade.js 1.1.1 (which had `NbRootsForTransfer()=0` because the WASM build's local JS was only the Emscripten loader with no OCC bindings, and the CDN WASM lacked STEP resource files) with **`occt-import-js@0.0.18`** — a purpose-built library for browser STEP reading that bundles all OCC resources.

New API (in `step-viewer.html`):
```js
occt = await occtimportjs({ locateFile: name => `https://cdn.jsdelivr.net/npm/occt-import-js@0.0.18/dist/${name}` });
const result = occt.ReadStepFile(uint8Array, null);
// result.success, result.root.meshes[].attributes.position/normal, result.root.meshes[].index
```

Geometry traversal: walk `result.root` tree recursively, build Three.js BufferGeometry from each mesh's `attributes.position`, `attributes.normal`, and `index` arrays.

### Face Highlighting — Session 5 Implementation

Communication: React `CappViewer` → iframe `step-viewer.html` via `window.postMessage`.

Message format:
```js
{ type: 'highlight', faceIndices: [0, 3, 7] }  // highlight these faces
{ type: 'highlight', faceIndices: [] }           // clear all highlights
```

Data source: `cluster.face_indices` from `*_params.json` — each cluster records which STEP face indices it covers.

Files changed:
- `capp-frontend/public/step-viewer.html` — added `message` listener; colors `currentMeshes[i]` orange on match, resets others to default blue
- `capp-frontend/src/pages/CappViewer.js` — added `viewerIframeRef` on iframe; `onSelectFaces` posts message to `contentWindow`
- `capp-frontend/src/components/viewer/tabs/StrategyTab.js` — `onSelectFaces` prop threaded `StrategyTab → SetupSection → FeatureGroup → OperationRow`; fires on row expand

### Bugs Fixed This Session
| Bug | Fix |
|-----|-----|
| `program_sheet.py` line 540: `f'T{t_numbers.get(tid, "?"):02d}'` → ValueError for missing tools | Changed to `(f'T{t_numbers[tid]:02d}' if tid in t_numbers else 'T??') if tid != '--' else '--'` |
| PipelineProgress active-stage pill wrong (stage 6 gap made tools/params/sheet indices off) | Added explicit `stageNum` to each stage entry, compare against `job.stage` directly |
| Stub `opencascade.wasm.js/.wasm` files in `public/` were jsDelivr 404 error pages | Deleted — viewer uses dynamic `import()` + unpkg CDN correctly |
| `opencascade is not defined` — ES module loaded via `<script src>` | Switched to `await import('/opencascade.wasm.js')` |
| `TransferRoots called with 1 arguments, expected 0` | Removed `Message_ProgressRange_1` arg — 0 args confirmed |
| `BRepMesh_IncrementalMesh_2 invalid number of parameters (2)` | Fixed to 5 args: `(shape, 0.1, false, 0.5, false)` |

### How to Start Next Session
1. `cd capp_service && "C:\Users\Siddhant Gupta\miniconda3\envs\occ\python.exe" -m uvicorn main:app --port 8001`
2. `cd capp-frontend && npm start`
3. Go to `http://localhost:3000` → upload a STEP file → verify Overview, Strategy, Program Sheet tabs all load
4. **3D viewer test**: upload a STEP file and confirm the model renders. If `occt-import-js` CDN fails (network/CORS), download `occt-import-js.js` + `.wasm` locally to `public/` and change `locateFile` to `/occt-import-js.wasm`.
5. **Face highlight test**: go to Strategy tab, click any operation row — verify the corresponding faces turn orange on the 3D model.

---

## 9. Standalone Public URL — Deferred

Not worth doing standalone since this will be integrated into `shiaanx-frontend-admin`. Revisit only if a standalone demo URL is needed before integration.

When needed, two options:
- **Quick demo**: ngrok on :8001 (backend) + set `REACT_APP_CAPP_API_URL` in `.env.local` + ngrok on :3000 (frontend). URLs are temporary.
- **Permanent frontend**: Deploy React build to GitHub Pages (`gh-pages` package, `"homepage"` in package.json). Backend needs Cloudflare Tunnel or similar for a fixed public URL. OCC dependency means backend can't be deployed to standard cloud without Docker.

Rules sheet already public at: `https://shiaanx.github.io/shiaanx-CAPP/docs/RULES.html` — linked from sidebar (bottom icon).

---

## 10. What We Deliberately Skip (dev team adds during integration)

| Feature | Reason skipped |
|---|---|
| Auth / login | Already in shiaanx-frontend-admin |
| Projects list / multi-part management | Already in admin frontend |
| Enquiry / quote / order workflow | Already in admin frontend |
| Setups tab (detailed face/hole breakdown) | Lower priority, add in v2 |
| Tools tab | Lower priority, add in v2 |
| Feature click → face highlight (Setups tab) | Add in v2 |
| Section view, machining direction teardrops | Add in v2 |
| Admin panel | Already in admin frontend |
