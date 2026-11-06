# v3 (PowerMill costed face planner): demo notes

Status: 2026-11-05 (Worker C). v3 = `github.com/ShiaanX/shiaanx_v3_standalone` @ `54092b7`,
cloned to `C:\Users\Siddhant Gupta\Documents\shiaanx_v3_standalone`.

**Short version.** The offline adapter works on both parts (cached, returns in under 0.1 s).
**The live PowerMill run is done:** Motor Mount, all 3 setups, 27 toolpaths, 82 min wall
clock. The backup project is saved and has been re-opened in PowerMill. Section 0 has the real
timings and the demo-day steps. Two things are still open: **a PowerMill dialog is waiting
for a click (Cancel)**, and the Rekise setup was not run.

---

## 0. Live run, 2026-11-05: read this first

The founder registered the bridge (every `--check` line ok) and started PowerMill 2020
(PID 10112). v3 then ran **Motor Mount end to end in PowerMill**, all 3 setups, exit 0. The
command was run from the v3 folder, with occ_env python, and with miniconda `condabin` +
`Scripts` on PATH:

```
python -u job.py --model MOTOR_MOUNT.step --no-drill --allowance 2 --max-tool-dia 16 --faces "+Z:2:2,-Z:2:2,-Y:2:2" --auto --emit-events <backup>\live_events.ndjson
```
Run folder: `shiaanx_v3_standalone\database_runtime\MOTOR_MOUNT_20261105_102652`.

### Measured live timings (wall clock)

| phase | from | to | took |
|---|---|---|---|
| job start + geometry probe | 10:26:47 | 10:27:05 | 18 s |
| bridge, session check, saved 57-tool project opened (session reset) | 10:27:05 | 10:29:00 | 1 min 55 s |
| import model + 6 principal workplanes | 10:29:00 | 10:29:31 | 31 s |
| CAPP feature table (stages 1-3) | 10:29:31 | 10:29:50 | 19 s |
| +Z hold, then **plan printed** (16 mm start; 191.8 min, identical to the offline plan) | 10:29:50 | 10:35:39 | **5 min 49 s** |
| +Z setup build (vise, setup, stock model) | 10:35:39 | 10:37:20 | 1 min 41 s |
| **+Z toolpaths** (18 kept, including the mop-up re-plans with D4/D3/D2/D1 from 11:01) | 10:37:20 | 11:21:34 | **44 min** |
| +Z checkpoint saved | | 11:22:03 | |
| -Z: plan (65 s) + 6 toolpaths | 11:22:04 | ~11:36 | ~14 min |
| -Y: plan + 3 toolpaths | 11:36:44 | 11:48:37 | ~12 min |
| **whole job** | 10:26:47 | 11:48:37 | **81 min 50 s** |
| NC written | - | - | **not done.** No post processor is installed (`tooling/post/machine.pmoptz` is missing), so v3 writes no NC |
| re-open the backup project (`PROJECT OPEN`) | | | 36 s |

### What PowerMill computed (its own toolpath times)

| setup | ops | removed mm3 | PowerMill cutting | changes | v3 total at 15 min/change | v3 plan before cutting | real programmer NC |
|---|---|---|---|---|---|---|---|
| +Z | 18 | 75,811 | **213.0 min** | 9 | 348 min | 311.9 + 150 | setting 1: 208 min |
| -Z | 6 | 7,888 | **57.5 min** | 3 | 103 min | 79.9 + 45 | setting 2: 293 min |
| -Y | 3 | 7,487 | **20.9 min** | 2 | 51 min | 41.2 + 45 | setting 3: 17 min |
| **total** | 27 | 91,186 | **291.4 min** | 14 | **501 min (8.4 h)** | | **518 min** |

- **Totals:** the live cutting time is 0.56x the real NC. **+Z alone matches the programmer
  almost exactly (213 vs 208 min).**
  > **Correction (2026-11-05):** an offline re-run with the REAL billet (+11 mm on -Z, `--allowance "2,-Z:13"`) gives +Z 146.0 / -Z 63.9 / -Y 26.4 = 236.3 min cutting (vs 249.6 on the 2 mm billet). The per-setup match above is partly coincidental. Do not use it in the demo. Compare totals only. Note: v3's total went DOWN with more stock, which looks like an offline-model quirk worth raising with Rohit.
- **Why -Z is short:**
  - v3's +Z already took most of the bulk;
  - the real setting 2 also faced off a billet about 11 mm thicker.
- **Ledger:** 99.3% of the 147,766 mm3 removed; 986 mm3 still above the part.
- **Holes:** not drilled or checked (`--no-drill`).
- **Watch in the saved project:**
  - -Z jaws are "close to 22.49 mm, measured from stock model": the grip band after +Z is
    narrow. Look at the -Z vise before showing it.
  - On +Z the mop-up ran a D1 for 33.3 min to remove 28.5 mm3 (v3's 25 mm3 chip floor).
    That is why +Z is 213 min.
  - Several finishing passes "computed nothing" and were deleted, as designed.
- **`tooling/learned_delivery.json` was updated by this real run** (+39/-31 lines: per-tool
  delivery and time ratios). Left as is (real learning), not committed. Future plans read it.

### Backup (verified)

`C:\Users\Siddhant Gupta\Documents\ShiaanX\demo_backup\v3_motor_mount\`:
- `pm_project_final_all_3_setups\`: the project after all 3 setups. **Re-opened in PowerMill
  and checked: 27 toolpaths, 3 setups, 57 tools, 1 stock model.** The folder is byte-identical
  to v3's `checkpoints\after_YMIN`.
- `pm_project_after_ZMAX\`: after +Z only (18 toolpaths), a lighter fallback.
- `run_folder\`: v3's `logs\` (journal.json, feature table, residual maps), `run_manifest.json` and `part\`.
- `live_run.log` (the full v3 transcript), `live_events.ndjson` (event stream) and `live_start.txt`.

### PowerMill right now: ONE CLICK NEEDED

The backup project is loaded. To keep a Rekise run from writing into the backup, I then sent
`PROJECT OPEN` on the identical run-folder copy. PowerMill answered with the modal
**"PowerMill Query: Do you want to save changes before opening a new project?"**. It is on
screen now, and the bridge is blocked behind it. (My permissions do not allow clicking dialogs
or killing PowerMill.) **Click Cancel.** Motor Mount stays loaded and the backup on disk is not
touched. **Do not click Yes.** While the backup project is open, do not save in PowerMill: it
is that project's home folder.

### Not done

- **Rekise first setup:** not run, because the dialog above blocks the bridge. After clicking
  Cancel:
  `job.py --model RKSE-004-057.stp --no-drill --allowance 2 --faces "-Y:2:2" --auto`
  (offline, the -Y plan took about 6 min; toolpaths come on top). Then copy
  `database_runtime\RKSE-004-057_<stamp>\checkpoints\after_YMIN` to `demo_backup\v3_rekise\`.
  job.py wipes the open session, so re-open the Motor Mount backup afterwards
  (File > Open Project; answer **No** to "save changes").
- **NC:** blocked until the shop's `.pmoptz` post is available.

### Demo-day steps for v3 (about 90 s live)

1. **Before the call:** open PowerMill, then File > Open Project >
   `demo_backup\v3_motor_mount\pm_project_final_all_3_setups` (36 s). If it asks to save
   the current project, answer **No**. Have `demo_backup\v3_motor_mount\live_run.log` open
   at the first "PLAN -" block (+Z), or the v3 console.
2. **Live:**
   - (20 s) The +Z PLAN table: costed minutes per tool, the 16 mm rough, the 3 mm rest only
     where nothing bigger reaches, the ball and bull nose only on curved faces and fillets.
   - (50 s) In PowerMill: the Setups folder (ZMAX / ZMIN / YMIN). Activate ZMAX_SETUP and
     show the vise and billet. Click the ZMAX RESTROUGH EM16 toolpath, then the EM3 rest
     pass, then the ball FIN3D. Show the stock model.
   - (20 s) The whole-job table at the end of `live_run.log`: 27 operations, 291 min
     PowerMill cutting across 3 setups, against the programmer's 518 min.
3. **Say:**
   - "v3 priced every face in minutes, chose the tools, built the vise from the live stock and
     drove PowerMill command by command. All 3 setups, 27 toolpaths, in 82 minutes,
     unattended."
   - "On the top face it came out at 213 minutes of cutting; our programmer's program for the
     same face is 208."
   - Do not quote 501 min as a cycle time: that total assumes 15 min per manual tool change.
4. **Fallback:** `pm_project_after_ZMAX`. If PowerMill is down, use the app's Machining tab.

---

## 1. (DONE 2026-11-05) Bridge registration, kept for reference

v3 sends every PowerMill command through a C# add-in (`SamplePluginCS`), which serves HTTP on
`localhost:5001`. That add-in is not registered on this laptop
(`machine_setup.py`: "CLSID not COM-registered, 0 of 2 plugin categories, not enabled").
Registering it writes to HKLM, so it needs admin.

1. **Close PowerMill completely.** A `pmill.exe` was running during this session (PID 26732)
   and it was not started by me. Save whatever is open in it first.
2. Start menu, type **Anaconda Prompt**, right-click it, **Run as administrator**.
3. Run:
   ```
   cd "C:\Users\Siddhant Gupta\Documents\shiaanx_v3_standalone"
   conda activate occ_env
   python powermill_bridge\install_bridge.py --install
   python powermill_bridge\install_bridge.py --check
   ```
   `--check` must show three `ok` lines: registered, categories, enabled.
   The registration stores this folder's absolute path. If you move the folder, run it again.
4. Start PowerMill 2020. If a licence or "new add-in" dialog appears, accept it. Wait about 20 s,
   then in a normal prompt run:
   ```
   curl http://localhost:5001/status
   ```
   It should answer with JSON. If it does not, open PowerMill, go to **Add-in Manager**,
   tick **SamplePluginCS**, and restart PowerMill.
5. Check that the whole machine is ready:
   `python tooling\machine_setup.py` should print "every required check passed"
   (the post-processor line is only a note: no G-code is needed for the demo).

## 2. Setup already done (no action needed)

| what | done |
|---|---|
| clone | `git clone https://github.com/ShiaanX/shiaanx_v3_standalone` into `Documents\shiaanx_v3_standalone` (main, 54092b7) |
| env | `conda create -n occ_env --clone occ --offline`. The existing `occ` env already had the exact v3 pins (py3.10, OCC 7.9, numpy 2.2.6, vtk 9.5.2, networkx 3.4.2, reportlab 4.4.10, matplotlib 3.10.8). `occ` itself is untouched. |
| selftest | `occ_env python selftest.py`: **"all behaviours pinned - safe to run"**, 68 s |
| parts | copied into v3 `parts/` (gitignored): `MOTOR_MOUNT.step` (renamed, no space) and `RKSE-004-057.stp` |
| machine.json | `python tooling\machine_setup.py --write` (gitignored): PowerMill 2020 path, bridge URL, env occ_env |
| v3 code | **not modified.** `git status` in v3 is clean (`tooling/learned_delivery.json` was touched by a dry run and reverted; see Known issues, item 6) |

`conda` is NOT on PATH in a plain PowerShell. v3 calls `conda run -n occ_env ...` internally,
so on demo day **start everything from an Anaconda Prompt**, or put
`C:\Users\Siddhant Gupta\miniconda3\condabin` and `...\miniconda3\Scripts` on PATH.

## 3. Demo-day commands

```
:: Anaconda Prompt (not admin)
cd "C:\Users\Siddhant Gupta\Documents\shiaanx_v3_standalone"
conda activate occ_env
python ui\server.py            :: console at http://localhost:8765, launches PowerMill itself if needed
```

Headless alternative (one face, the plan is approved automatically):
```
git checkout -- tooling/learned_delivery.json
conda run -n occ_env --no-capture-output python job.py --model MOTOR_MOUNT.step --no-drill --allowance 2 --max-tool-dia 16 --faces "+Z:2:2" --auto
```
Backup part (v3's own reference part):
```
conda run -n occ_env --no-capture-output python job.py --model RKSE-004-057.stp --no-drill --allowance 2 --faces "-Y:2:2" --auto
```
Use `--drill` instead of `--no-drill` if you want holes. v3 will then ask PowerMill to recognise
holes, which is another step that can go wrong live.

Offline numbers for the ShiaanX app (no PowerMill needed):
```python
# capp_service/v3_adapter.py, any Python
from v3_adapter import run_v3_analysis
run_v3_analysis(r"...\Motor Mount\MOTOR MOUNT.step", faces="+Z,-Z,-Y")   # cached, 0.05 s
run_v3_analysis(r"...\Al extrusion mount (Rekise)\RKSE-004-057.stp")     # cached, 0.07 s
```

## 4. Timings

### Measured offline (dry run and adapter, this laptop, 16 cores)

| phase | Motor Mount | Rekise |
|---|---|---|
| geometry probe + CAPP stages 1-3 feature table | ~100 s (2.6 MB STEP) | ~30 s |
| CAD surface types (first time per part; cached on disk after that) | 150 s | - |
| reach map, 6 directions | 64-128 s | 106 s |
| **first face plan** (all 28 tools searched) | **+Z: 11 min alone, 23 min with other jobs running** | -Y: 6 min |
| later face plans | -Z 5 min, -Y 1 min | +Y 1 min |
| whole adapter run, first time | 29-35 min | 10.6 min |
| adapter, cached | 0.05 s | 0.07 s |

**The first plan on Motor Mount takes 11 minutes or more before any toolpath exists.** That
is too long to run live on a video call. `--max-tool-dia 16` (start the face with the 16 mm cutter)
cuts the first +Z plan to **5 min 51 s** (fewer start options searched) and gives the same
191.8 min plan. From job start to the printed plan that is about 7 min (geometry 11 s, feature
table 55 s, surface types from cache 10 s, plan 351 s). That is still too long for a live
segment, so pre-run it.

### Live PowerMill phases (NOT measured, the bridge is not registered)

From v3's own docs: PowerMill window to bridge listening takes about 18 s. Opening the saved
56-tool project takes about 4 s (3.5 min if the project cannot be read). The phase-1 replay on
RKSE took about 4 min. Each toolpath is computed by PowerMill and was not measured here.
**Measure launch, import, plan, first setup and full run after section 1 is done.**

## 5. The safest live segment (2 minutes or less)

Do not run the planner live. Prepare it before the call:

1. **Before the call:** run the Motor Mount +Z face through the console (or the headless
   command above) until the first toolpaths exist. Then save the PowerMill project to
   `demo_backup\v3_motor_mount\` (PowerMill: File > Save Project As).
2. **Live (about 90 s):** show the console with the run folder already open. Scroll the
   **PLAN** table for +Z (the costed tool list, minutes per tool, 15 min per tool change).
   Switch to PowerMill with the saved project open: the vise around the billet, the toolpaths
   for the 16 mm rough and the 3 mm rest pass, the stock model. Then press **run** on one more
   short step if one is waiting.
3. **Fallback:** if PowerMill or the bridge misbehaves, File > Open Project on the saved
   backup. If PowerMill will not start at all, show the offline v3 numbers in the ShiaanX app
   (adapter output, `capp_service/demo_data/v3_motor_mount_sample.json`).

What to say while it runs:

- "Before a single chip is cut, every face is priced in minutes. Each tool is simulated as a
  real solid (cutter, shank, holder) against the part and the vise. Only then are the big
  tools assigned, smallest last."
- "Each smaller tool only gets the material that no bigger tool can reach. That is why the
  3 mm cutter appears only where it is needed."
- "After every cut it re-measures the real stock in PowerMill and re-plans."
- Do **not** quote v3's minutes as a cycle-time promise. v3's own docstring calls it "a ~2x
  model, ample for RANKING plans, useless as a promise", and see section 6.

## 6. Calibration: v3 against the real programmer (Motor Mount)

The real programmer's NC (`CAM Program/ncprograms`, 20 `.tap` files) was integrated move by
move: G1/G2/G3 at the programmed F, rapids at 10 m/min. The feeds are a flat F1000 with
plunge at F500, so this gives cutting time with no feed override applied.

| | real (NC) cutting + rapid | real tools | v3 cutting | v3 changes | v3 total |
|---|---|---|---|---|---|
| setting 1 (top face, profile to Z-19) ~ v3 **+Z** | 206.9 + 1.3 = **208 min** | 12 EM, 4 EM, 2 EM, 4 ball | **101.8** | 6 x 15 | 191.8 |
| setting 2 (other face, faces 11 mm) ~ v3 **-Z** | 290.7 + 2.0 = **293 min** | 12, 8, 4, 2 EM, 3 ball | **140.3** | 4 x 15 | 200.3 |
| setting 3 (side bore, Z-43, narrow X) ~ v3 **-Y** | 16.8 + 0.1 = **17 min** | 10 EM, 4 EM | **7.5** | 2 x 15 | 37.5 |
| **total** | **518 min cutting** (11 tool loads) | | **249.6 min** | 12 x 15 = 180 | **429.6** |

Which of setting 1/2 is +Z and which is -Z was inferred from the NC extents; the CAM project
was not opened. v3 order used: `+Z,-Z,-Y` (operator order, matching the real 3 settings).

**v3's cutting time is about 0.48x the real NC on every setup (0.49 / 0.48 / 0.44).** v3's
total looks close to the real time only because its 15 min per tool change makes up the gap.

Likely causes, largest first:

1. **Depth of cut.** The programmer roughs in very light layers: `2__12end` steps down
   0.148 mm, `12end_face11MM` 0.198 mm, `1_8end` 0.1 mm, all at F1000. v3 prices roughing at
   catalogue `ap_max` (full flute: 16 mm on the D16, 8 mm on the D8), `ae` = 50%, and its
   feeds (D16: 5968 rpm x 2 x 0.06 = 716 mm/min), times a single EFFICIENCY = 0.10. That
   factor was calibrated on PowerMill's own computed times for v3's own toolpaths, not on this
   programmer's style. Volume per minute differs by far more than 2x per pass. The two
   effects partly cancel, and v3 still ends up about 2x optimistic.
2. **Billet.** v3 assumes 2 mm all round (59.3 x 108.8 x 25.5). The real setting 2 faces off
   about 11 mm (`12end_face11MM`, 65 min on its own), so the real billet was thicker. v3's
   facing on -Z is 0.7 min.
3. **Small tools.** The real program uses a 2 mm end mill and 3/4 mm ball noses
   (`9_4boll` 25 min, `7_3boll` 47 min). v3 puts the detail on a D3/D4 and a D10 ball, and
   leaves 405 + 192 mm2 unfinished plus about 850 mm3 that nothing reaches.
4. **FINFLAT (the known issue from SE-004-052 again).** Floors are priced at offset-flat,
   which has never been measured. On -Z the D8's 3159 mm2 of floor is priced at 75.0 min, but
   the raster fallback is **117.4 min**. On +Z the D16 is priced at 23.1 min against a 29.3 min
   fallback. In this run it shows up as uncertainty, not as the 622 min inflation seen on 052.
   On 052 the learned x3.155 factor did the inflating. On this part the learned finish factors
   were not triggered by the first plan.
5. **Holes are not priced offline** (22 CAD holes; drilling needs PowerMill's recognition).
   The real NC has no drilling cycles either: every hole is milled.

Nothing in v3 was changed to close the gap. This is reported only.

## 7. Known issues

1. **The bridge is not registered.** No live run has been done and there is no backup project
   (section 1).
2. **The first plan takes 11-23 min on Motor Mount.** Pre-run it; do not plan live.
3. **v3 does not choose the face order.** The operator picks it. The adapter's default order
   is a greedy cover of v3's own jaw-capped reach masks. On Motor Mount that gives `+Y,-Y,+Z`:
   the plate stood on its 25 mm edge with a 102 mm reach. That is mathematically valid but not
   how anyone would hold this part. **For the demo, call the adapter with
   `faces="+Z,-Z,-Y"`.** `v3_motor_mount_sample.json` is that version. The greedy version is
   saved as `v3_motor_mount_greedy_order.json` (274 min total).
   v3's older reach analysis (`machinability_billet.py`, jaw and holder unaware) gives
   `+X,-Y,+Z` with a 20 mm cutter 94 mm deep. It is not used.
4. **Setups after the first are planned offline against v3's PREDICTED stock**: the billet
   minus the union of the swept reach of the tools already chosen (`planner.sweep_all`). A
   live run re-plans against PowerMill's measured stock.
5. `clamp_area_mm2` in the adapter output is the vise-jaw contact band from v3's hold plan
   (grip 6 mm x held length), not a flat-face area. v3 has no flat-face clamp area any more.
6. A plain `job.py --dry-run` that runs the cut loop updates `tooling/learned_delivery.json`
   (one counter changed during my dry runs; already reverted). If it shows as modified again, revert it with
   `git checkout tooling/learned_delivery.json` before a live run, so the live plan is not
   influenced by dry runs. The adapter never reaches the cut loop.
7. v3's library has aluminium cutting data only. Motor Mount is quoted as Al 6063; fine.

## 8. Files

- `capp_service/v3_adapter.py`: `run_v3_analysis(step_path, material="aluminium", cache_dir=None, allowance_mm=2.0, max_setups=4, timeout_s=10800, force=False, faces=None) -> dict`
- `capp_service/v3_runner.py`: runs inside occ_env and drives v3's own classes (`--holes-only` mode too)
- `capp_service/demo_data/v3_motor_mount_sample.json`: operator order `+Z,-Z,-Y`, 429.6 min
- `capp_service/demo_data/v3_motor_mount_greedy_order.json`: greedy `+Y,-Y,+Z`, 274.1 min
- `capp_service/demo_data/v3_rekise_sample.json`: `-Y,+Y`, 169.9 min
- `capp_service/demo_data/v3_cache/`: cache, raw plans (`*_rawplans.json`) and full v3 transcripts (`*.raw.log`)
- `demo_backup/v3_motor_mount/`: **empty**. Put the saved PowerMill project here after the live run.
