# Claude chat video (Motor Mount) - recording plan

A recorded clip for the investor call, played or sped up at your discretion. Motor Mount only.
Rohit's ShiaanX plugin in the Claude desktop app drives the v3 console, which drives PowerMill, so
the toolpaths appear in PowerMill while Claude makes the choices. Not live, laptop only, separate
from the dev.shiaanx.com demo. The video stops before "Use this run"; the app's own plan is approved
afterwards with the normal **Approve plan** button.

Status: NOT yet rehearsed in the Claude app.

## Order of the video

1. **App, order page (the Motor Mount order):** click **Generate with AI (v3)**, then **View program**.
   This is the planner's estimate: 3 setups (+Z, -Z, -Y), the tools, 170.1 min per part including tool changes. No PowerMill involved.
   NEEDS the planner result already saved, so Generate is instant on camera (it is, for Motor Mount, once committed and deployed).
2. **Say the bridging line, then switch to the Claude chat:**
   "That's the plan, an estimate in seconds. Now watch the same engine build it as real toolpaths in PowerMill, and I'll just ask it in plain English."
3. **Claude chat, the run (PowerMill builds on screen):** Claude opens the part, sets the stock, starts the job, answers the plan prompts.
   Speed this up: the full job is about 80 min of real time. Keep the start, the first plan being read, a few toolpaths appearing, the end.
4. **Back in the app: Approve plan** (the app's plan, not Claude's run). Do NOT press **Use this run**.

No tool-reduction question in this video: building the program from a prompt already shows what the Claude integration does.

## Prompt for step 3 (dictated or typed)

> Hi Claude. I want to machine the Motor Mount in PowerMill. Build the plan we just generated: use MOTOR_MOUNT.step from the parts folder, the Aluminium tools library, 2 mm of stock on every side, and the faces in the order +Z, then -Z, then -Y. Decide the holding so every face can be reached, and answer the plan prompts yourself.

The plan has the same three setups, so the PowerMill tree (ZMAX, ZMIN, YMIN setups) reads as the plan being carried out, not a second plan.

Expect (from Rohit's video): Claude finds the part and opens it in PowerMill, sets the stock, and may ask a multiple-choice question
about the jaw grip: pick an option on screen (the "Keep ... flip" option, or the recommended one). It may say "before you approve, I'd question
the roughing tool": answer on camera. If it needs you to click **Start over** in the console, do.

Optional, as Rohit did: "Let's start with -Z first instead." Claude stops, asks for Start over, restarts. Only if it rehearses cleanly.

## Cautions for the voiceover

- **Do not claim the run equals the plan.** The run's tool count and minutes can differ from the plan's. Say "builds it", not "reproduces it".
  The one PowerMill-measured run on the program card shows 291 min (27 toolpaths); the plan is 170.1 min, a planner estimate.
  Do not show the two totals side by side.
- **Tool-change cost.** The console's cost model charges 15 MINUTES per change; our machine's changer is about 15 SECONDS.
  If a console total appears on screen, do not quote it as a cycle time.
- **If Claude offers to change tools or passes**, say "keep the plan as it is".

## Before recording

1. The planner result for the Motor Mount order is saved (so "Generate with AI" is instant).
2. PowerMill: dismiss the "Bridge Exception" dialog, close the unsaved project, no saved demo project open
   (`pm_project_final_all_3_setups`, `...PRISTINE_copy` are never written to).
3. Console running on http://localhost:8765 (`start_v3_console.bat`). Claude app on a NEW chat, ShiaanX plugin on.
4. Screen: app/console in the browser, Claude chat, PowerMill, side by side (Rohit's layout), recorded as one screen
   (Win+Alt+R, or OBS).
5. Rehearse once. Replies vary.

## Limits and risks

- A real run is about 80 min. Record it and speed it up; PowerMill must be free of dialogs the whole time.
- Starting a run empties the PowerMill session.
- The run's totals will not match the app's, which is why the video stops before **Use this run**.
- The run writes a new folder under `database_runtime` in Rohit's clone and notes into its `knowledge/` folder. Do not commit those; ask me to revert, delete the run folder if unwanted.
- Not proven on this laptop yet: the first full run through the plugin.
