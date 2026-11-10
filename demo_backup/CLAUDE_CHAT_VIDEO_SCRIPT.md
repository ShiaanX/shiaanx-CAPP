# Claude chat video (Motor Mount) - recording plan

A recorded clip for the investor call, played or sped up at your discretion. Motor Mount only.
Rohit's ShiaanX plugin in the Claude desktop app drives the v3 console, which drives PowerMill, so
the toolpaths appear in PowerMill while Claude makes the choices. Not live, laptop only, separate
from the dev.shiaanx.com demo. The video stops before "Use this run"; the app's own plan is approved
afterwards with the normal **Approve plan** button.

Status: NOT yet rehearsed in the Claude app. Shot 1 was tried once and worked (see "What we already know").

## Order of the video

1. **App, order page (Motor Mount, SX/26-27/00019 or the demo order):** click **Generate with AI (v3)**, then **View program**.
   This is the planner's estimate (27 toolpaths, 291.4 PowerMill min for the approved run; plan 170.1 min with changes). No PowerMill involved.
   NEEDS the planner result cached for the current v3 version: the first Generate takes about 35 min after the v3 clone was updated.
   Run it once before recording.
2. **Claude chat, Shot 1 (read-only, optional):** where do the minutes go in the finished run, can the tool count come down.
3. **Claude chat, the run (PowerMill builds on screen):** Claude opens the part, sets the stock, starts the job, answers the plan prompts.
   This is the part to speed up (about 80 min of real time for the full job; record the start, the first plan, a few toolpaths appearing, the end).
4. **Back in the app: Approve plan** (the app's plan, not Claude's run). Do NOT press **Use this run**.

## What we already know (read from the console, 10 Nov)

Finished run `MOTOR_MOUNT_20261105_102652` (what "View program" shows): 37 cuts in the program record, **10 distinct tools** over +Z, -Z, -Y, 298.4 min measured.
Minutes by tool: 16 mm end mill 130, 3 mm 46.5, 2 mm 35.6, 1 mm 33.3, 12 mm 18.7, 10 mm ball 18.5, 4 mm 8.3, 6 mm ball 5.5, 8 mm 1.4, face mill 0.5.
Shot 1 reply (Claude): could go from 10 tools to about 6 (drop 1, 4, 8 mm and both balls); the 1 mm took 33 min for 28.5 mm3; keep 12 mm for the 16.1 bore and probably 2 mm for the 2.5 mm slots.

Two cautions for the voiceover:
- **Tool-change cost.** The console's cost model charges 15 MINUTES per change. Our machine's changer is about 15 SECONDS. Do not quote Claude's "40% saving" (mostly 150 min of tool changes at 15 min each). The honest saving is cutting minutes, roughly 22%.
- **Two totals.** The app says 27 toolpaths / 291.4 min (PowerMill project; 39 of 66 tried toolpaths were dropped or empty). The console record says 37 ops / 298.4 min. Do not show both on screen. If asked: "Claude reads the planner's own program record."

## Before recording

1. v3 planner result for the demo order is cached (step 1 above), so Generate is instant on camera.
2. PowerMill: dismiss the "Bridge Exception" dialog, close the unsaved project, no saved demo project open
   (`pm_project_final_all_3_setups`, `...PRISTINE_copy` are never written to).
3. Console running on http://localhost:8765 (`start_v3_console.bat`). Claude app on a NEW chat, ShiaanX plugin on.
4. Screen: app/console in the browser, Claude chat, PowerMill, side by side (Rohit's layout), recorded as one screen
   (Win+Alt+R, or OBS).
5. Rehearse once. Replies vary.

## Prompts

Shot 1 (read-only):
> Use shiaanx. Look at the finished Motor Mount run MOTOR_MOUNT_20261105_102652. How many tools does it use, and where do the minutes go? Could we cut the number of tools without hurting the part? Read the evidence before you answer.

The run (step 3), dictated or typed:
> Hi Claude. I want to machine the Motor Mount in PowerMill. Use MOTOR_MOUNT.step from the parts folder, the Aluminium tools library, and 2 mm of stock on every side. Use as few tools as you can: one roughing cutter per face, and drop any pass that only removes a few hundred cubic millimetres. Faces in the order +Z, then -Z, then -Y. Decide the holding so every face can be reached, and answer the plan prompts yourself.

Expect (from Rohit's video): Claude finds the part and opens it in PowerMill, sets the stock, and asks one multiple-choice question about the jaw grip
(pick "Keep ... flip" or the recommended one on screen). It may also say "before you approve, I'd question the roughing tool" - answer on camera.
If it needs you to click **Start over** in the console, do.

Optional, to show a change of mind, as Rohit did: "Let's start with -Z first instead." Claude stops, asks for Start over, restarts.

## What to say

- "This is the same planner, asked in plain English. It opens the part in PowerMill, picks the setups and the holding, and answers each plan itself."
- "We asked for the fewest tools, so it drops the passes that do not earn a tool change."
- Compare the new tool count with the 10-tool original. Do not quote a time saving unless the console's own totals give one, and remember the 15 min change assumption.

## Limits and risks

- A real run is about 80 min. Record it and speed it up; PowerMill must be free of dialogs the whole time.
- Starting a run empties the PowerMill session.
- The run's totals will not match the app's 170.1 / 291.4 min, which is why the video stops before **Use this run**.
- The run writes a new folder under `database_runtime` in Rohit's clone and notes into its `knowledge/` folder. Do not commit those; ask me to revert, delete the run folder if unwanted.
- Not proven on this laptop yet: the first full run through the plugin.
