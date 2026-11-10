# ShiaanX investor demo: 10-minute run sheet (Motor Mount)

The story to tell: **a STEP file comes in, and AI handles every step after it.** On screen that means DFM, the quote, client replies, the program, where the job slots in, tracking, inspection, and learning from defects. Every number on screen is computed live from real part data. Placeholders carry a **SAMPLE DATA** badge.

Primary part: `Claude output for program sheet\Manufactured parts\Motor Mount\MOTOR MOUNT.step`
Backup part: `...\Al extrusion mount (Rekise)\RKSE-004-057.stp`

---

## Pre-call checklist (start 45 min before)

### 0. Local rehearsal in one step
`demo_backup\start_local_demo.ps1` starts the local database check, flow backend (8080), part-analysis service (8001), QC 3D service (8780) and the frontend (3000), skipping whatever is already running. Docker Desktop must be open (not needed when demoing on dev only).

### 1. Start the services, in this order

| # | What | How | Ready when |
|---|---|---|---|
| 1 | Docker Desktop | Start menu, then **Docker Desktop**. Wait for "Engine running". | `docker ps` answers |
| 2 | Flow backend (port 8080) | PowerShell: `& "C:\Users\Siddhant Gupta\Documents\ShiaanX\demo_backup\start_flow_backend.ps1"` | prints `Server running on port 8080` |
| 3 | capp_service (port 8001) | PowerShell: `cd "C:\Users\Siddhant Gupta\Documents\ShiaanX\capp_service"` then `& "C:\Users\Siddhant Gupta\miniconda3\envs\occ\python.exe" -m uvicorn main:app --port 8001` | `Application startup complete` |
| 4 | Admin app (port 3000) | PowerShell: `cd "C:\Users\Siddhant Gupta\Documents\ShiaanX\shiaanx-frontend-admin"` then `npm start` | `Compiled` |
| 5 | v3 console (port 8765) | Nothing to start by hand: **Open v3 console** in /proto starts it via capp_service (step 3 must be up) | console opens at http://localhost:8765 |
| 6 | PowerMill 2020 | File > Open Project > `demo_backup\v3_motor_mount\pm_project_final_all_3_setups`. Takes about 36 s. If it asks to save the current project, answer **No**. Do not save while this project is open: it is the backup. | 27 toolpaths, 3 setups (ZMAX / ZMIN / YMIN) |

> **Always (re)start capp_service on demo day, after any code change.** A server started before the last code edits serves stale numbers. Fresh code gives "Manufacturable on 3-axis after design changes" (2 blocking sharp corners) and ₹4,008. After a restart, wait for `[warm] demo caches ready` in its console before opening pages.

### 2. Log in

At http://localhost:3000/admin/#/proto, log in with **your dev.shiaanx.com account**. The local backend now runs on `sx_flow_devcopy`, a copy of dev's data taken 2026-11-05 11:11 (start script default). `admin@sx.com` exists only in the old test DB (`-Data test`). Browsers may autofill a different account, so check the email before you click Log in.

### 3. Pre-open these tabs (1280×720, zoom 100%)

1. `http://localhost:3000/admin/#/proto` (Enquiries & Orders)
2. The Motor Mount enquiry. On the dev-copy DB, create it once in the dry run (Beat 1 clicks), convert it to an order, and paste its URL here. (The old SX/26-27/00029 link exists only in the test DB.)
3. `http://localhost:3000/admin/#/proto/board?focus=motor-mount`
4. The Motor Mount order page from your dry run (scroll to "Program vs what the machine did")
5. `http://localhost:3000/admin/#/proto/inspection/Motor%20Mount` (scroll to "CMM program")
6. `http://localhost:3000/admin/#/proto/closed-loop?view=defects`
7. `demo_backup\v3_motor_mount\live_run.log`, scrolled to the first "PLAN -" block (+Z). The v3 console also works.
8. PowerMill, with `pm_project_final_all_3_setups` open

### 4. Warm the caches (5 min)

- On tab 2, click **Run on attached STEP**. DFM should appear within about 20 s; that proves the v3 cache is hit. Then open **auto-quote**: it should show ₹4,008 at qty 40.
- Open order **SX/26-27/00019** once, but do not click Generate or Approve. capp_service now warms the program, production-history and tracking caches itself about 4 s after it starts, so this is only a check that the page loads at once.
- On tab 4, tracking should appear in under a second.
- On tab 5, wait for the CMM program. The first extraction on a new job takes about 30 s, then it is cached.
- **Do the live upload once before the call** with the same `MOTOR MOUNT.step`. The v3 cache is keyed on the file's hash plus the face order, so the live upload on the call is then instant. A different or edited STEP takes **10–35 min** in v3.

---

## The 10 minutes

### Beat 1: Enquiry (0:00–0:45)
- **Where:** tab 1, Enquiries & Orders.
- **Clicks:** **+ New enquiry**. Pick a customer, set Part name *Motor Mount*, Qty *40*, Material *Aluminium 6061*, tick *CNC milling (3-axis)*, drop `MOTOR MOUNT.step` on CAD file, then **Create enquiry**.
- **On screen:** the enquiry page with the STEP listed under Documents received.
- **Say:** "Every job starts as a STEP file and a quantity. From here, the system does the engineering a planner used to do by hand."
- **Fallback:** if Create fails, switch to tab 2, the pre-made enquiry SX/26-27/00029.

### Beat 2a: Live part analysis + 3D DFM viewer (0:45–2:15)
- **Where:** the same page, card **"Live part analysis (v3 planner)"**.
- **Clicks:** **Run on attached STEP**. Wait about 20 s for the verdict. The 3D viewer then loads the STEP in the browser (a few seconds; the page stays responsive).
- **On screen:** verdict **"Manufacturable on 3-axis after design changes"**, 3 setups, 852 mm³ unreachable on 3-axis. Beside it, the part in 3D (1,096 faces) with faces coloured by issue, and a tree of categories: **2 sharp internal corners (blocking)**, 4 flat-bottom holes, 10 non-standard hole sizes (Ø2.529, likely M3 tap drills), engraved text/logo (915 faces, 1.5 mm deep), regions that force the Ø3 mm cutter (23.8 min), 2 non-standard fillet radii (R2.3, R8.05) and 2 groups of external edge fillets.
- **Clicks in the viewer (about 40 s):**
  1. Click the **"Small radius internal corner(s)"** category (red, 2): the model zooms to the two corners and highlights them. Hover one: radius 0 mm, 0.5 mm deep, 90°, needs at least R0.5.
  2. Click **"Engraved / embossed text or logo"**: the logo lights up.
  3. **ISO**, then **Fit** (or **Reset**) to come back to the whole part.
- **Key moment:** the two sharp corners. "A rotating cutter cannot make a zero-radius inside corner. The design needs R0.5 there, or an EDM step. The system finds that face by face, before anyone quotes."
- **Say:** "Every face of the CAD is checked against what a 3-axis machine and a real cutter can do. A customer gets this back in seconds, with the exact faces to change, not a PDF of opinions a week later."
- **Fallback:** if the viewer stays blank, the tree and the findings list still show; talk over them. If the verdict spins past 60 s, the STEP is not the cached one: click **Forget job**, then **Use an existing job id**, and paste the job id from your warm-up run. If capp_service is down, the card shows a red "Could not reach the part-analysis service": restart it (step 3 of the checklist).

### Beat 2b: Auto-quote (2:15–3:30)
- **Clicks:** **Open auto-quote** (top right of the card).
- **On screen, Summary:** **₹4,008/unit**, total ₹1,60,320 for 40 pcs, **27 days**. Material ₹233, machining 252.6 min at ₹700/hr = ₹2,947, setup ₹26/unit, margin 25%.
- **Machining tab:** minutes per tool and per setup (+Z 103.3, −Z 141.3, −Y 8.0 min). The footer line reads: "249.6 min cutting + 12 tool changes × 15 s (ATC). v3's own total is 429.6 min because it assumes 15 min per manual tool change."
- **Material & stock tab:** 62.3 × 111.8 × 28.5 mm blank, in inventory (INV-AL6061-PL-40, **SAMPLE DATA**).
- **Lead time tab:** 0 days material + 25 days machining + 2 days QC & dispatch.
- **Live change:** set **Material** to *aluminium 7075*. The stock is not in inventory, so the quote switches to a supplier (Sample Supplier C, Bengaluru, 3 days, SAMPLE) and the price and lead time move. Set it back to 6061. Optionally set Qty to 2: the unit price rises to ₹4,631 because setup is spread over fewer parts.
- **Say:** "The quote is built from the machining plan itself, minute by minute, tool by tool. It checks our stock and falls back to a supplier with their lead time. Margin is a placeholder we set."
- **Do NOT click** the "vs manual quote" tab on the call (see the honest-framing lines below).
- **Fallback:** if the quote errors, close and reopen it. If capp_service is down, restart it.

### Beat 3: Client feedback & comments (AI draft reply) (3:30–4:15)
- **Where:** close the quote, then the **Client feedback & comments** tab on the same card.
- **Clicks:** paste a client comment, for example "Your price is higher than our current vendor — can you do better?". Set Topic *Price*, then **Draft reply with AI**.
- **On screen:** a drafted reply appears in about 3–5 s (Gemini 2.5 Flash-Lite, labelled with its model). Below it is the list of **facts the draft is grounded on**: the quote, the lead time, the DFM warnings and the drawing tolerances. The draft explains the price through the part itself (setups, tolerances, material) and never shows our margin, cost breakdown, rates or supplier names. That is deliberate, so point it out.
- **Say:** "The assistant can only use facts from this job: the quote, the DFM and the drawing tolerances. No invented promises. It is internal; the team edits before anything goes out."
- **Fallback:** if the draft errors (network, or Gemini credits run out), the panel says so plainly and still shows the grounded facts. Talk over those facts.

### Beat 4: Program generation, AI plan + PowerMill, then approve (4:15–6:00)
- **Where:** the order. Convert the enquiry, or open order **SX/26-27/00019**, which sits at **Process planning**. Card **"Process plan & CAM program"**.
- **Clicks (about 100 s):**
  1. (10 s) Click the status timeline to show where the part is (Process planning).
  2. (10 s) **Generate with AI (v3)**. The plan appears: 3 setups, the tools, and **27 toolpaths (PowerMill)**.
  3. (20 s) **View program**: every toolpath with its tool, strategy, rpm, feed and PowerMill minutes. Total **291.4 PowerMill minutes** for the whole job.
  4. (40 s) Click **Open v3 console (drives PowerMill) ↗**. This is Rohit's console, already running the Motor Mount job live (see "Start the live v3 run" below). Show its progress and the +Z PLAN table (minutes per tool: the 16 mm rough, and the 3 mm only where nothing bigger reaches). Then switch to **PowerMill**, where the toolpaths are being built right now, live: the vise, the billet, the stock model updating.
  5. (20 s) Back in the app: **Approve plan**. It says "Plan approved — Motor Mount is now in Scheduling". Click **See it on the production board →**, which leads into Beat 5.
- **Start the live v3 run** in Rohit's console when you begin the deck (about 10–15 min before Beat 4). The full job takes about 82 min (first plan about 6 min, +Z toolpaths about 44 min), so by Beat 4 it is mid-run with PowerMill visibly working.
  - **Console:** no command line needed. Click **Open v3 console (drives PowerMill) ↗** on the order's program card. The backend starts Rohit's console in about 4 s if it isn't already running, and opens http://localhost:8765. (Manual fallback: Anaconda Prompt, then `cd` to the v3 folder, `conda activate occ_env`, `python ui\server.py`.)
  - **The run tab:**
    1. choose a part: `MOTOR_MOUNT.step`; tool library: all tools; **use this part** (opens PowerMill, imports the part);
    2. stock: 2 in all six, then **keep this stock**;
    3. steps: +Z, then −Z, then −Y, milling;
    4. **start**.
  - **Note:** starting a run empties the PowerMill session, so the backup project cannot be open in the same PowerMill at the same time.
- **"View program" in /proto** shows the complete result of the full run on 2026-11-05 (27 toolpaths, 291.4 PowerMill min). That is what gets approved; the live console run shows the same planner working in real time.
- **Say:**
  - "Before a single chip is cut, every face is priced in minutes. Each tool is simulated as a real solid, with cutter, shank and holder, against the part and the vise. Each smaller tool only gets the material no bigger tool can reach."
  - "v3 then drove PowerMill command by command: 3 setups, 27 toolpaths, 82 minutes, unattended. The engineer's job becomes review and approve."
  - Use totals only: "PowerMill measured 291 minutes of cutting for the AI program." Do NOT quote a per-setup match (213 vs 208 on the top face); a real-billet re-run (2026-11-05) showed that match was partly coincidental.
  - Do not quote v3's 501 min as a cycle time: it assumes 15 min per manual tool change. The programmer's total is 518 min of cutting, against v3's 291.
- **Fallback:** if the live run misbehaves, click **stop** in the console and open the finished project in PowerMill: `demo_backup\v3_motor_mount\pm_project_final_all_3_setups` (27 toolpaths). A read-only copy is in `pm_project_final_PRISTINE_copy`. A lighter one is `pm_project_after_ZMAX` (18 toolpaths). If PowerMill will not start, stay in **View program** ("this is the same program, toolpath by toolpath"). If Approve errors, the card says so; the board then falls back to the programmer time, which is still a real number.
- **After each rehearsal:** 00019 ends approved and in Scheduling. Reset it before the call (see founder to-dos).

### Beat 5: Production board after approval (6:00–6:45)
- **Where:** the board, opened from **See it on the production board →** (or tab 3).
- **Board layout (one machine):** the columns are **Production on machine 1** (1 place) and **Scheduled for machine 1** (2 places). Their counts read "1 / 1" and "2 / 2", and turn amber if a column is over its places. Every card shows **Start → End dates** (cards not yet scheduled show "Earliest start …" in lighter text), and a card turns red with "after deadline" if its end date is past the deadline.
- **Stage it before the call:** drag the job that is cutting now (e.g. Motor Mount SX/26-27/00007) into **Production on machine 1**. Then approving 00019 lands it in **Scheduled** as the second place (2 / 2), which is the clean story. If Scheduled already holds 2, approving makes it 3 / 2 and the count turns amber: that is intended, not a bug.
- **On screen:** click the Motor Mount card: "Where Motor Mount slots in", queued with the **AI plan (v3)** as its time source: 252.6 min per part including tool changes, approved by you, with the time. Then its start, finish and deadline status. Jobs ahead with no estimate show **"not counted"** in the hours column, never 0, and a note says the start and finish are therefore the earliest possible.
- **Deadline at qty 40:** the 19 Nov deadline shows **"Deadline · will be missed"**. That is real: 40 × 252.6 min ≈ 168 h of cutting, about 170 h with setups, on one VMC. Two options:
  - Keep it, and say: "And it tells us the truth: 40 pieces on one VMC don't make this date. Today we find that out on day 10; here we find it out before we accept the order, and we split it across machines or agree a date now."
  - Or, before the call, give the demo order a smaller qty (about 5) or a deadline after early December, so it reads "on track". This also changes the quote, so decide first.
- **Say:** "Approve the plan and the job lands on the machine queue with its real minutes, against everything already there."
- **Plan reuse:** an approved plan is reused by every order of the same part. Before you approve 00019, the other Motor Mount order (00007) is timed from the programmer's 69.8 min (48.5 h); the moment you approve, both read the AI plan (169.9 h), labelled "Reused from the approved plan on …". Nice moment: *"approve one plan and every order of that part is rescheduled."*
- **The gate:** dropping a part with no plan and no cycle time into Scheduled or Production (or clicking those stages on the order page) first shows "has no process plan yet" with **Open order to generate the plan** / **Move anyway** / **Cancel**. Battery Plate v1 (00006) is the example: it is carbon fibre, which the aluminium-only planner doesn't cover, so it has no estimate and shows "no estimate yet". If asked: "Parts outside the planner's scope get a manual estimate (not built yet)."
- **Never delete these orders.** The queue is the team's real orders.

### Beat 6: Earlier production (6:45–7:30)
- **Where:** enquiry **SX/26-27/00007** (Motor Mount, qty 40, at QC / Dispatch), order page, card **"Earlier production of this part"**. It is batch 2 only (the Sinumerik program on the TS machine, 9 parts).
- **On screen:** the headline "73 min per part against 66 planned (+10%)", then one row per setup with **cycle time** (programmed -> real), **spindle speed** (programmed -> real) and the **feed override** range. Setup 3 reads "not recorded". Nothing else: no QC strip, no batches, no sources.
- **Batch switch on the card:** it opens on batch 2. Click **Batch 1 - as first made** to show the programmer ran the feed 2.8x to 11x the auto-plan's (the Ø2 tool: 90 -> 1000 mm/min) and the spindle at 7,500 against 4,500. The column on batch 2 is the operator's feed *override* knob, not the programmed feed.
- **Say:** "We made this part before. This is what the machine actually did against what the programmer planned: it ran 10% longer, and the operator was riding the feed knob. That gap is exactly what the next plan learns from."

### Beat 7: QC in 3D + CMM program (7:30–9:00)
- **Where:** the same order page, bottom section **"QC - 3D view"** (the Inspection report line's **View** button scrolls down to it), then the Inspection page card **"CMM program"**.
- **Set up once, before the call:** upload `demo_backup\qc\Motor Mount QC - batch 1.xlsx` on enquiry 7's **Inspection report** line (Upload). The batch switch loads batch 2 from the server by itself. The 3D view then builds itself in about a minute. It needs the QC service: locally `demo_backup\start_local_demo.ps1` starts it; on dev the QC container must be redeployed with this round's code first.
- **On screen:** the 3D part opens on **Batch 1 (as first made)**: balloons 4 and 5 (the Ø3.2 holes) are red at 3.02. Scroll to **Why defects happen**, open #4: Ø2 end mill, 10 mm long, F1000 against the auto-plan's F90, deflection, **Rule R-02**. Switch to **Batch 2 (after the change)**: 4 and 5 go green (3.15-3.20, now drilled with a Ø3.2 drill) and the **Fixed since batch 1** block shows R-02 confirmed. Batch 2 still has real reds (8, 10, 11, 13) with their own causes. Then the CMM program: 13 / 13 features matched, 80 touch points.
- **Be exact:** the feed was NOT lowered; the shop changed the method (end mill to drill). Say the AI recommends bringing the feed back toward the auto-plan or drilling.
- **Say:** "Every measurement the inspector recorded sits on the part itself, so you can see where it is, not read a table. And the CMM program writes itself from the geometry and the drawing tolerances."

### Beat 8: Closed loop, defects and why (8:45–9:45)
- **Where:** tab 6 (`#/proto/closed-loop?view=defects`).
- **On screen:** 2 parts, 13 dimensions: 6 in, 2 close to limit, 5 out. Each defect shows the toolpath and tool that cut it and the likely cause. Examples: the Ø3.2 holes undersize from small-cutter deflection (Ø2 end mill); the drawing and CAD disagreeing on 45.75; a thickness made across two settings (datum transfer). Switch the batch selector to show batch 2.
- **Say:** "Every defect is traced to the cut that made it, with a reason. That is the loop: the next plan avoids the Ø2-mill-for-a-Ø3.2-hole choice. This is where our learning compounds."

### Close (9:45–10:00)
"STEP in, then DFM, quote, program, schedule, tracking, inspection and learning, in one system. The engineering judgement is the AI, and we built it."

---

## Honest-framing lines (have these ready)

- **Quote vs the manual quote (only if asked):** "At qty 40 the auto-quote is ₹4,008 against our engineer's ₹3,897, about 3% apart. The manual quote was for 6063, this one is 6061." It is visible in the auto-quote's "vs manual quote" tab; keep that tab off the click path. Background: before pricing the shop's 15 s tool changer, v3's default of 15 min per manual change put the quote at +69%.
- **The two shop programs differ ~7×:** "We have two real programs for this part: one estimates 69.8 min, the other's toolpaths add up to about 500 min. Even human programs disagree 7×. That is exactly why a consistent, explainable planner matters. Our plan, about 240–290 min of cutting (offline estimate / PowerMill-measured), sits between them." Same billet: v3 236 min vs the 518-min shop program. The gap is mostly the programmer's 0.1–0.2 mm roughing layers. Do not claim per-setup agreement.
- **v3 minutes are conservative:** v3 calls its own time model "~2×, for ranking plans, not a promise". Do not present 252.6 min as a cycle-time guarantee.
- **Machine data caveats (batch 2):** "This is the TS machine's June run. Setup 3, the finish program, isn't in the controller log. The log shows 16-18 full cycles per setup, more than the 9 parts inspected, so we read the inspection as a sample of a larger lot. Shares are of logged time, because the collector only logs while a program is loaded." State and mode codes were read from the data itself, not from Siemens documentation.
- **Drilling is not priced offline:** "The 22 holes aren't in this quote's cycle time yet. Drilling is priced once PowerMill's hole recognition is in the loop, which needs the bridge."
- **If the reply assistant errors on the call:** "The drafting call failed just now; you can see exactly which facts it is allowed to use, and it never makes up a number."
- **Board vs quote cycle:** after Approve, the board uses the approved AI plan's 252.6 min/part, the same figure as the quote. Before approval it falls back to the programmer's 69.8 min/part. Saving the auto-quote again keeps the approved plan time.
- **SAMPLE DATA badges:** inventory and supplier entries are placeholders until the team replaces them. Margin, setup minutes and shift hours are also placeholders. The real values are ₹700/hr and the 15 s tool change.

---

## Backup part: Rekise RKSE-004-057

Use it if the Motor Mount run misbehaves, with the same clicks on a new enquiry (STEP `RKSE-004-057.stp`). It is cached in v3.

- DFM: 0 blockers, 6 warnings.
- Quote at qty 1: ₹1,754, 51.9 min (v3 raw total 169.9 min).
- Tracking shows "No tracking data for this job yet" (no NC programs on file).
- CMM shows "Tolerances are needed" (no inspection report on file).
- There is no closed-loop data for it, so for beats 6–8 go back to Motor Mount.

---

## Founder to-dos before the call

1. ~~Register the PowerMill bridge as admin~~. Done on 2026-11-05. ~~Motor Mount pre-run~~ done 2026-11-05: all 3 setups, 27 toolpaths, backup re-opened and verified in `demo_backup/v3_motor_mount/`. **Click Cancel** on the PowerMill dialog "Do you want to save changes before opening a new project?" that is waiting on screen; Motor Mount stays loaded. Rekise has not been run yet, and NC needs the shop's post (`.pmoptz`). Details: `V3_DEMO_NOTES.md` section 0.
2. ~~Top up the Gemini API credits~~. Done on 2026-11-05 and verified with real drafts. Before the call, send one test draft to confirm.
3. **Board estimates:** the orders in the flow DB are **real orders. Do not delete them.** They lack machining-time estimates, so the queue reads 0.0 h ahead. The fix (pending decision) is to estimate each from its quote or a v3 run and mark the rest "no estimate yet".
4. Decide whether the **"Dev environment — shared with the team"** header pill should be visible on the call (`shiaanx-frontend-admin/src/proto/ProtoApp.js:98`).
5. Do one full dry run at 1280×720 with the warm caches.
6. **00019's header shows "Repeated as SX/26-27/00019_R1".** That is a side effect of testing: the test order 00019_R1 was made as a repeat of 00019. Leave it (harmless and true) or remove the link on the test order before the call. Do not delete either order.
7. **Deadline vs qty:** decide on Beat 5's "will be missed": keep it and use the line, or change the demo qty or deadline before the call.
8. **After each rehearsal on 00019:** it ends approved and in Scheduling. Put it back to Process planning, and delete `capp_service\jobs\<00019's job id>\program_approval.json`, so Generate → Approve works live again.
