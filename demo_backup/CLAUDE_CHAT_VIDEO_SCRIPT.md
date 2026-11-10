# Claude chat video (Motor Mount) - recording plan

A recorded clip for the investor call, shown at your discretion (speed up or skip). Motor Mount only.
It uses Rohit's ShiaanX plugin in the Claude desktop app: Claude reads the planner's finished run,
answers questions about it, and edits the program through the console's own checker.
Not live, laptop only, separate from the dev.shiaanx.com demo.

Status: NOT yet rehearsed in the Claude app. Shot 3 in particular is untested.

## What the data says (read from the console, 10 Nov)

Finished run `MOTOR_MOUNT_20261105_102652` (the one "View program" shows):
- 37 cuts over 3 faces (+Z, -Z, -Y), **10 distinct tools**, 298.4 min measured by PowerMill.
- Minutes by tool: 16 mm end mill 130.0, 3 mm 46.5, 2 mm 35.6, **1 mm 33.3**, 12 mm 18.7, 10 mm ball 18.5, 4 mm 8.3, 6 mm ball 5.5, 8 mm 1.4, face mill 0.5.
- The 1, 2 and 3 mm end mills are about 115 min between them. That is where the tool-count question lands.
- This run is **not resumable**: it can be read, edited and checked, but not re-cut.

Partial run `MOTOR_MOUNT_20261106_144146` (+Z only, 12 cuts, 6 tools, 191.9 min) is the **only resumable one**.
A re-cut (Shot 3) can only start from it, or from a fresh run.

## Before recording

1. PowerMill: dismiss the "Bridge Exception" dialog, close the unsaved project. Do not open the saved demo projects
   (`pm_project_final_all_3_setups`, `...PRISTINE_copy`). Nothing in this video writes into them.
2. Console running on http://localhost:8765 (`start_v3_console.bat`). Claude app open on a NEW chat, ShiaanX plugin on.
3. Screen: console in the browser, Claude chat, PowerMill side by side (Rohit's layout), recorded as one screen.
   Windows: Win+Alt+R (Xbox Game Bar) or OBS.
4. Rehearse once. Replies vary. Keep what works.

## Shot 1 - ask about the tool count (read-only, about 1 min of video)

Prompt (type or dictate):
> Use shiaanx. Look at the finished Motor Mount run MOTOR_MOUNT_20261105_102652. How many tools does it use, and where do the minutes go? Could we cut the number of tools without hurting the part? Read the evidence before you answer.

Expect: tools and minutes as above, and a proposal to drop or merge the small end mills (1, 2, 3 mm).
Per the plugin's own rules a pass that removes a few hundred mm3 for a tool change is rarely worth it,
unless the region is a functional feature. Show the reasoning; do not promise a saving before the check.

## Shot 2 - make the change in the program, and let the console check it (read-only, about 1 min)

Prompt:
> Make that change in the program: edit the program for that run, then check it with the console and tell me the new total minutes, the tools left, and anything the check complains about.

This uses `shiaanx_program` -> edit -> `shiaanx_check_program`: the console's validator and cost model, not Claude's arithmetic.
Nothing in PowerMill changes and nothing is staged. If the check reports errors, show Claude fixing them: that is the point.

## Shot 3 (optional, needs a rehearsal) - stage it and re-cut, PowerMill shows it

Only from the resumable partial run, or from a fresh run. Prompt:
> Stage the checked program and re-cut it from the last clean checkpoint.

`shiaanx_stage_program` then `shiaanx_start_job`: restores the checkpoint, writes a **new run folder** in
`database_runtime`, and PowerMill rebuilds toolpaths on screen. Unproven on this laptop: PowerMill must be free of
dialogs, the run takes real time (speed it up), and the new run's totals will not match the 252.6 / 291.4 min in the app.
Claude will ask before starting (it should: that tool changes PowerMill). Say yes or no on camera.
If it misbehaves, stop the console's run and keep Shots 1 and 2 only.

## What to say

- "This is the same planner, asked in plain English. It reads the real run, explains where the time goes, and proposes fewer tools."
- "The change goes through the console's own checker, so the numbers are the planner's, not a guess."
- Be exact: PowerMill measured 298 min for the finished run, and these are planner estimates, not machine time.
  Do not quote a saving until the check gives one.

## After recording

- The console writes what happened into `knowledge/` inside Rohit's clone (`shiaanx_v3_standalone`). That shows up in `git status` there. Do not commit it; ask me and I will revert it.
- Shot 3 leaves a new folder under `database_runtime`. Delete it if you do not want it.
