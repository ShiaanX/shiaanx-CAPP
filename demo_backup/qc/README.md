# Motor Mount QC sheet for the 3D QC view

Files here:
- `Motor Mount QC sheet.xlsx` - upload this on the Motor Mount order, "Inspection report" line.
- `verify_flow.py` - replays the exact calls the Inspection page makes (`python verify_flow.py "Motor Mount QC sheet.xlsx"`, QC service on 127.0.0.1:8790).
- Rebuild: `inspection/build_qc_sheet.py` (repo root), see the header of that file.

No ballooned drawing is needed. The view only offers it as an optional reference ("Open ballooned drawing"); it is never read by the QC service. The customer drawing is `Manufactured parts/Motor Mount/motor mount.pdf` and can be uploaded unballooned or left out.

## What the sheet contains
- Sheet "QC sheet": 13 balloons exactly as on the drawing (nominal, TOL+, TOL-), plus every numeric reading from both real shop reports (batch 1: P1-P2, batch 2: P1-P9; 'tapping' entries are non-numeric and ignored). Shop remarks are kept.
- Sheet "Face links": for each balloon the CAD face indices (A, and B for linear dims), made by the CMM matcher (`capp_service/demo_modules/cmm.py`). 13/13 matched. The service applies them while seeding, so no manual tagging. It also stores the STEP sha256 and face count (1096) so links are only applied to the same CAD (or one with the same face count).
- Sheet "Notes": provenance and flags.

## Flags (read before the demo)
- Balloon 2: drawing says 45.75, CAD is 46.0 / 45.5 across the pitch (matched to 45.5). Shop remark "As per cad ok"; batch 2 even changed the nominal to 46.1. We keep the drawing value, so it shows red (readings ~46.1-46.2 vs limits 45.55-45.95). This is the honest drawing-vs-CAD story.
- Balloon 6: drawing dia 3.09, CAD hole is 3.0; batch 2 lists dia 2.5 "tapping". Only 2 numeric readings (2.46, 2.48) so it shows red. Balloons 6 and 8 are CAD twins (same diameter), so which hole is which is by order.
- Readings of all 11 parts are pooled, so one outlier part turns a balloon red. Result on the real data: 5 pass, 0 near limit, 8 fail (balloons 2, 4, 5, 6, 8, 10, 11, 13). Balloons 4 and 5 fail on batch 1 readings of 3.02 (limit 3.1-3.3). 7 of the 8 fails contradict the shop's "OK" remark, which the page flags as a remark disagreement.
  If you want a greener rehearsal, build from one batch only: `python inspection/build_qc_sheet.py --step ... --drawing-report ... --readings <only that file>` (nothing else changes).

## Upload clicks (dev server and localhost:3000 are the same)
1. Open the Motor Mount order, Documents / the part's "Inspection report" line, click Upload (or Update), choose `Motor Mount QC sheet.xlsx`. It must be .xlsx.
2. Make sure the part has its CAD file (`MOTOR MOUNT.step`) on the order. The sha must match the one in the sheet (otherwise the face count 1096 is used; if neither matches the balloons seed but untagged).
3. Open the Inspection page for the part. In the "3D QC view" card click "Set up 3D QC view". Wait for "Preparing the 3D model" (about 10-30 s).
4. The card opens on "Result" (because tagged > 0): the model with 13 balloons coloured pass / near limit / fail. The "Tag dimensions (13 of 13 done)" pill shows the links.
5. Later changes to readings: "Re-read the uploaded QC sheet".

Already-set-up parts: if the part was set up earlier without the sheet (job has 0 balloons), "Re-read the uploaded QC sheet" re-seeds (the page does this when total = 0). If it has balloons already, click "Set it up again" is only offered when the job is missing; otherwise delete the link by setting up on a fresh part/order.

## Local rehearsal (localhost:3000)
Start the QC service (needs OCP; the `occ` env does not have it, use the labeling app env from `labeling_app/setup.bat`, i.e. `labeling_app\.venv`):
```
cd "Claude output for program sheet\labeling_app"
.venv\Scripts\python.exe -m uvicorn local_app.main:app --host 127.0.0.1 --port 8780
```
Start the frontend with `REACT_APP_QC_URL=http://127.0.0.1:8780` (PowerShell: `$env:REACT_APP_QC_URL="http://127.0.0.1:8780"; npm start`; it is read at build/start time, restart the dev server to change it). No login cookie is needed locally (CORS is open). Do not use 8001/8080/3000.

## Frontend changes needed
None. `Inspection.js` PUTs the seeded dimensions as returned, so the links carried by the seed response are saved as-is.

## Deploy notes (dev `qc` container)
- Changed files, all already inside the CAPP tree that `Dockerfile.dockerignore` allow-lists for `labeling_app/local_app`: `local_app/main.py`, `local_app/qc_sheet.py`. No new runtime files. The dev container must be rebuilt/redeployed with these two files; until then the old service ignores the "Face links" sheet (balloons still seed, but untagged).
- `inspection/build_qc_sheet.py` and the tests are not needed in the container. Tests: `labeling_app/tests/test_qc_face_links.py`.
- Risk: if the order's STEP is a re-export with different bytes and face count, links are skipped (response has `face_links.skipped_reason`) and tagging is manual.
