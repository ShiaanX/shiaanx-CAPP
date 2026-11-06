"""Run Rohit/Dishant's v3 planner OFFLINE (no PowerMill) on a STEP file.

Runs INSIDE v3's own conda env (occ_env) - called by capp_service/v3_adapter.py
as a subprocess:

    <occ_env python> v3_runner.py --step PART.step --out result.json
                                  [--allowance 2] [--max-setups 4]

Nothing here re-implements a v3 algorithm. It drives v3's own classes the way
`job.py --dry-run --auto --faces ...` does (PlannedOrchestrator, dry run, no
bridge), then reads back what they computed:

  geometry        orchestrator/geometry_probe (via the orchestrator)
  billet          clamped_orchestrator._billet  (part box + allowance)
  reach           ui/reach.analyse_billet       (the planner's own sweep, jaw-capped)
  setup order     orchestrator.machinability -> app/machinability_billet.py
                  (v3's "--reach-analysis" greedy setup plan)
  holes           drill_test/cad_holes.extract + drill_test/operations.pick_drill
  per-face plan   PlannedOrchestrator.build_plan -> app/planner.plan_face

The ONE thing that differs from a live run: after a face is planned, PowerMill
would cut it and export the live stock STL that the next face is planned
against. Offline there is no STL, so the next face is planned against v3's
own PREDICTED stock - the billet minus the union of the swept masks
(planner.sweep_all) of the tools the previous plan chose. This is the
planner's own statement of what that tool set removes; it is reported as a
warning in the output.
"""

import argparse
import contextlib
import io
import json
import os
import sys
import time
import traceback

V3_ROOT = os.environ.get(
    "V3_ROOT", r"C:\Users\Siddhant Gupta\Documents\shiaanx_v3_standalone")


def _jsonable(o):
    try:
        import numpy as np
        if isinstance(o, np.generic):
            return o.item()
        if isinstance(o, np.ndarray):
            return o.tolist()
    except Exception:
        pass
    if isinstance(o, (set, tuple)):
        return list(o)
    return str(o)


def _principal(vec):
    """Direction label of the FACE a tool enters from, for a hole whose
    world_axis points INTO the material: the tool travels along the axis, so
    it enters from the face whose outward normal is -axis."""
    ax = max(range(3), key=lambda i: abs(vec[i]))
    sign = "-" if vec[ax] > 0 else "+"
    return sign + "XYZ"[ax]


def cad_holes(model):
    """CAD holes (drill_test/cad_holes.extract) with v3's drill choice
    (drilling_stage._tools_for + operations.pick_drill). -> (holes, error)."""
    import layout
    holes = []
    try:
        import cad_holes as CAD
        import operations as OPS
        import drilling_stage as DS
        dtools = OPS.load_tools(layout.TOOL_DB, layout.TOOL_CAP)
        for h in CAD.load(model):
            hh = {"diameter": h["diameter"]}
            ts = DS.DrillingOrchestrator._tools_for(None, hh, dtools)
            best, notes = OPS.pick_drill(h["diameter"], h["depth"],
                                         ts.get("twist") or [])
            holes.append({
                "dia_mm": round(h["diameter"], 3),
                "depth_mm": round(h["depth"], 3),
                "dir": _principal(h["world_axis"]),
                "drill": best.get("tool_id") if best else None,
                "through": h.get("is_through"),
                "notes": notes,
            })
    except Exception as e:
        return holes, "CAD hole extraction failed: %s" % e
    return holes, None


def holes_only(step):
    os.chdir(V3_ROOT)
    if V3_ROOT not in sys.path:
        sys.path.insert(0, V3_ROOT)
    import layout
    layout.install()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        holes, err = cad_holes(os.path.abspath(step))
    print(json.dumps({"holes": holes, "error": err}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--allowance", default="2")
    ap.add_argument("--max-setups", type=int, default=4)
    ap.add_argument("--log", default=None)
    ap.add_argument("--faces", default=None,
                    help="plan these faces in this order (e.g. \"+Z,-Z,-Y\") "
                         "instead of the greedy cover - v3 itself leaves the "
                         "face order to the operator")
    ap.add_argument("--legacy-reach", action="store_true",
                    help="also run v3's jaw-unaware machinability_billet "
                         "reach analysis (slow) and report its setup plan")
    a = ap.parse_args()

    t_start = time.time()
    warnings = []
    timings = {}
    step = os.path.abspath(a.step).replace("\\", "/")
    log_path = a.log or (os.path.splitext(a.out)[0] + ".log")

    os.chdir(V3_ROOT)
    if V3_ROOT not in sys.path:
        sys.path.insert(0, V3_ROOT)
    import importlib.util
    import layout
    layout.install()
    spec = importlib.util.spec_from_file_location(
        "v3_job", os.path.join(V3_ROOT, "job.py"))
    job = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(job)

    logf = io.open(log_path, "w", encoding="utf-8", buffering=1)
    out = {"source": "v3", "part": os.path.splitext(os.path.basename(step))[0]}

    with contextlib.redirect_stdout(logf), contextlib.redirect_stderr(logf):
        import planned_orchestrator as PO
        import planner as PL
        import tool_choice as TC

        sys.argv = ["job.py", "--model", step, "--dry-run", "--auto",
                    "--drill", "--allowance", str(a.allowance)]
        args = job.parse_args()
        o = PO.PlannedOrchestrator(args)
        o.events = None

        # ---- the run's own prefix, exactly as orchestrator.run() orders it
        t = time.time()
        o.pick_part()
        o.open_run_folder()
        o.open_events()
        o.load_recipes()
        o.check_tool_library()
        o.load_revision()
        o.load_program()
        o.probe_geometry()
        o.run_capp_pipeline()
        try:
            o.prewarm()
        except Exception as e:
            warnings.append("v3 prewarm (CAD surface types) not started: %s" % e)
        o.connect()
        o.prepare_part()
        timings["prepare_s"] = round(time.time() - t, 1)

        geo = o.geometry or {}
        bb = geo.get("bbox") or {}
        billet = o._billet()
        bsize = [billet["XMax"] - billet["XMin"], billet["YMax"] - billet["YMin"],
                 billet["ZMax"] - billet["ZMin"]]
        part_vol = geo.get("part_volume_mm3")
        out["run_dir"] = o.paths.root
        out["billet_mm"] = [round(v, 3) for v in bsize]
        out["billet_box"] = billet
        out["allowance_mm"] = o._allowance()
        out["part_bbox_mm"] = ([round(bb["size_x"], 3), round(bb["size_y"], 3),
                                round(bb["size_z"], 3)] if bb else None)
        out["part_volume_mm3"] = part_vol
        out["removal_volume_mm3"] = (round(bsize[0] * bsize[1] * bsize[2]
                                           - part_vol, 1)
                                     if part_vol is not None else None)

        # ---- reach: the planner's own sweep, jaw-capped, on the billet
        t = time.time()
        reach = {}
        try:
            sys.path.insert(0, os.path.join(V3_ROOT, "ui"))
            import reach as UIR
            reach = UIR.analyse_billet(o.paths.root, billet) or {}
            if reach.get("error"):
                warnings.append("ui/reach: %s" % reach["error"])
        except Exception as e:
            warnings.append("ui/reach.analyse_billet failed: %s" % e)
        timings["reach_s"] = round(time.time() - t, 1)
        out["unreachable_mm3"] = reach.get("unreachable_mm3")

        per = reach.get("per_direction") or {}
        # ---- v3's own --reach-analysis (machinability_billet): optional.
        # It is jaw- and holder-UNAWARE (README "known limits"; its note says
        # "ignores holder/fixture collision") - on Motor Mount it puts +X
        # first with a 20 mm cutter 94 mm deep - so it is reported, not used
        # for the order. ~4-11 min, so off unless --legacy-reach.
        mach = None
        if a.legacy_reach:
            t = time.time()
            try:
                mach = o.machinability()
            except BaseException as e:
                warnings.append("v3 reach analysis (machinability_billet) "
                                "failed: %s" % str(e)[:200])
            timings["legacy_reach_s"] = round(time.time() - t, 1)
            if mach and mach.get("setup_plan"):
                out["legacy_setup_plan"] = [
                    {k: p[k] for k in ("setup", "direction", "gain_mm3",
                                       "cumulative_pct")}
                    for p in mach["setup_plan"]]

        # ---- setup order: greedy cover, jaw-aware. Each face's mask is the
        # planner's own sweep (planner.sweep_all over the run's plan tools,
        # capped at that face's jaw reach - exactly what ui/reach sums); the
        # face that adds the most still-uncovered stock goes next (the same
        # greedy rule as v3's setup_plan), until a face adds < MIN_SETUP_GAIN.
        t = time.time()
        order = []
        try:
            import tool_sim as TS
            pitch = PO.PLAN_PITCH_MM
            part, stock = TS.grids(o.a.model, None, billet, pitch,
                                   o.paths.log_file(""))
            left = stock & ~part
            vox = pitch ** 3
            tools = o._plan_tools()
            jaws = reach.get("jaw_reach") or {}
            masks = {}
            for d in ("+X", "-X", "+Y", "-Y", "+Z", "-Z"):
                sw = PL.sweep_all(part, tools, d, pitch, jaws.get(d))
                m = None
                for mm in sw.values():
                    m = mm.copy() if m is None else (m | mm)
                if m is not None:
                    masks[d] = m & left
            total_left = float(left.sum()) * vox
            min_gain = max(PL.MIN_GAIN_MM3, 0.005 * total_left)
            covered = None
            plan_rows = []
            while True:
                best, gain = None, 0.0
                for d, m in masks.items():
                    if d in order:
                        continue
                    g = float((m if covered is None else (m & ~covered)).sum()) * vox
                    if g > gain:
                        best, gain = d, g
                if best is None or gain < min_gain:
                    break
                order.append(best)
                covered = masks[best].copy() if covered is None else (covered | masks[best])
                plan_rows.append({"setup": len(order), "direction": best,
                                  "gain_mm3": round(gain, 1),
                                  "cumulative_pct": round(100.0 * float(covered.sum()) * vox
                                                          / max(total_left, 1e-9), 1)})
            out["setups_needed"] = len(order)
            out["setup_plan"] = plan_rows
            out["setup_plan_residual_mm3"] = round(
                total_left - (float(covered.sum()) * vox if covered is not None else 0.0), 1)
            warnings.append("setup order = greedy cover of the planner's own "
                            "jaw-capped sweep masks (stop when a face adds < "
                            "%.0f mm3, 0.5%% of the stock to remove); v3 itself "
                            "leaves the face order to the operator" % min_gain)
        except Exception as e:
            traceback.print_exc()
            order = [d for d, v in sorted(per.items(), key=lambda kv: -(kv[1] or 0))
                     if v]
            out["setups_needed"] = None
            warnings.append("setups_needed unavailable (%s); plan order falls "
                            "back to reachable volume per face" % e)
        timings["setup_plan_s"] = round(time.time() - t, 1)
        out["greedy_order"] = list(order)
        if a.faces:
            order = [f.strip().upper() for f in a.faces.split(",") if f.strip()]
            out["face_order_source"] = "operator (--faces)"
            warnings.append("faces planned in the operator's order %s; the "
                            "greedy cover would have chosen %s"
                            % (",".join(order), ",".join(out["greedy_order"])))
        else:
            out["face_order_source"] = "greedy cover"

        # ---- directions table
        import holding as HOLD
        dirs = []
        for d in ("+X", "-X", "+Y", "-Y", "+Z", "-Z"):
            hold = HOLD.plan_hold(TC.DIR_TO_WP[d], billet,
                                  grip_mm=o._grip_for(d))
            ax = hold["up_axis"]
            third = [x for x in "XYZ" if x not in (ax, hold["grip_axis"])][0]
            held_len = billet[third + "Max"] - billet[third + "Min"]
            dirs.append({
                "dir": d, "workplane": TC.DIR_TO_WP[d],
                "machinable_mm3": per.get(d),
                "machinable_mm3_reach_analysis":
                    ((mach or {}).get("per_direction_total_mm3") or {}).get(d),
                "clamp_area_mm2": round(hold["grip_depth_mm"] * held_len, 1),
                "jaw_reach_mm": round(hold["jaw_reach_mm"], 2),
                "best_tool": (reach.get("best_tool") or {}).get(d),
                "recommended": bool(order) and d == order[0],
                "setup_order": (order.index(d) + 1) if d in order else None,
            })
        out["directions"] = dirs
        warnings.append("clamp_area_mm2 is the vise-jaw contact band from v3's "
                        "hold plan (grip depth x held length on the billet), "
                        "not a flat-face area")

        # ---- holes, from the CAD (PowerMill recognition is not available)
        holes, herr = cad_holes(o.a.model)
        if herr:
            warnings.append(herr)
        out["holes"] = holes
        if holes:
            warnings.append("%d CAD holes found; drilling is NOT priced "
                            "offline - v3 only drills holes PowerMill's "
                            "recognition agrees with, which needs the bridge. "
                            "The plans below leave holes to the end mills or "
                            "unreached" % len(holes))

        # ---- per-face plans, in setup order
        plan_order = order[:max(1, a.max_setups)]
        if len(order) > len(plan_order):
            warnings.append("only the first %d of %d setups were planned "
                            "(--max-setups)" % (len(plan_order), len(order)))
        o.a.faces = ",".join("%s:3:2" % d for d in plan_order)
        setups, tools_out, forced, raw = [], [], [], []
        total = 0.0
        changes = 0
        change_min = 0.0
        first = True
        for i, d0 in enumerate(plan_order):
            t = time.time()
            try:
                d = o.choose_direction(first)
                if d is None:
                    break
                plan = o.build_plan(d)
            except BaseException as e:
                warnings.append("planning %s failed: %s" % (d0, str(e)[:200]))
                traceback.print_exc()
                break
            secs = round(time.time() - t, 1)
            if not plan:
                setups.append({"dir": d, "minutes": 0.0, "plan_s": secs})
                first = False
                continue
            raw.append({"dir": d, "plan": plan})
            mins = float(plan.get("minutes") or 0.0)
            total += mins
            changes += int(plan.get("changes") or 0)
            ch = 0.0
            for r in plan.get("facing") or []:
                ch += r.get("change_min") or 0.0
                tools_out.append({"tool": r["tool"], "dia_mm": None,
                                  "minutes": round(r["minutes"], 1),
                                  "role": "face", "setup": d})
            for r in plan.get("drills") or []:
                ch += r.get("change_min") or 0.0
                tools_out.append({"tool": r["tool"], "dia_mm": None,
                                  "minutes": round(r["minutes"], 1),
                                  "role": "drill", "setup": d})
            for r in plan.get("sized") or []:
                ch += r.get("change_min") or 0.0
                tools_out.append({"tool": r["tool"],
                                  "dia_mm": r.get("diameter_mm"),
                                  "minutes": round(r["minutes"], 1),
                                  "role": "restrough", "setup": d,
                                  "note": "feature %s cut to size"
                                          % r.get("feature")})
            for j, r in enumerate(plan.get("rows") or []):
                ch += r.get("change_min") or 0.0
                if r.get("roughed") and r.get("rough_min"):
                    role = ("rough" if (first and j == 0
                                        and not plan.get("facing"))
                            else "restrough")
                    tools_out.append({"tool": r["tool"],
                                      "dia_mm": r.get("diameter_mm"),
                                      "minutes": r["rough_min"], "role": role,
                                      "setup": d,
                                      "mm3": r.get("rough_mm3")})
                if r.get("finish_min"):
                    tools_out.append({"tool": r["tool"],
                                      "dia_mm": r.get("diameter_mm"),
                                      "minutes": r["finish_min"],
                                      "role": "finish", "setup": d,
                                      "mm2": round((r.get("steep_mm2") or 0)
                                                   + (r.get("shallow_mm2") or 0)
                                                   + (r.get("sloped_mm2") or 0))})
                dia = r.get("diameter_mm") or 0
                if dia and dia <= 4.0:
                    forced.append({
                        "tool": r["tool"],
                        "reason": "%s: only this %g mm cutter reaches %s mm3 of "
                                  "stock / %s mm2 of surface that no larger "
                                  "tool in the plan reaches (%.1f min%s)" % (
                                      d, dia, format(r.get("rough_mm3") or 0, ",.0f"),
                                      format((r.get("steep_mm2") or 0)
                                             + (r.get("shallow_mm2") or 0), ",.0f"),
                                      (r.get("minutes") or 0),
                                      (", finishing at %s mm2/min"
                                       % r["mm2_per_min"])
                                      if r.get("mm2_per_min") else "")})
                if r.get("flat_fallback_min") and r["flat_fallback_min"] > (
                        r.get("finish_min") or 0):
                    warnings.append(
                        "%s %s: %s mm2 of floor priced at offset-flat "
                        "(FINFLAT), never measured; if PowerMill declines it "
                        "the raster fallback alone is %s min, not %s"
                        % (d, r["tool"], r.get("flat_mm2"),
                           r["flat_fallback_min"], r.get("finish_min")))
                if r.get("mm2_per_min") and r["mm2_per_min"] < PL.SLOW_FINISH_MM2_MIN:
                    warnings.append("%s %s finishes at only %s mm2/min (%s min)"
                                    % (d, r["tool"], r["mm2_per_min"],
                                       r.get("finish_min")))
            change_min += ch
            if (plan.get("uncovered_curved_mm2") or 0) >= PL.FINISH_SHORTFALL_MM2:
                warnings.append("%s: %.0f mm2 of curved surface no ball nose "
                                "in the plan finishes - a flat cutter steps it"
                                % (d, plan["uncovered_curved_mm2"]))
            setups.append({"dir": d, "workplane": TC.DIR_TO_WP[d],
                           "minutes": round(mins, 1),
                           "cutting_minutes": round(mins - ch, 1),
                           "tool_change_minutes": round(ch, 1),
                           "tool_changes": int(plan.get("changes") or 0),
                           "left_mm3": plan.get("left_mm3"),
                           "unfinished_mm2": plan.get("unfinished_mm2"),
                           "jaw_reach_mm": o.jaw_reach,
                           "stock": ("raw billet" if first else
                                     "v3-predicted stock after the previous "
                                     "setup(s)"),
                           "plan_s": secs})

            # ---- the next face sees what THIS plan's tool set removes
            try:
                part, stock = o._grids()
                names = {r["tool"] for r in plan.get("rows") or []}
                names |= {r["tool"] for r in plan.get("sized") or []}
                seen, tl = set(), []
                for tt in o._plan_tools() + o._sized_tools():
                    if tt["name"] in names and tt["name"] not in seen:
                        seen.add(tt["name"])
                        tl.append(tt)
                sw = PL.sweep_all(part, tl, d, PO.PLAN_PITCH_MM, o.jaw_reach,
                                  obstacles=o._obstacles(part.shape))
                removed = None
                for m in sw.values():
                    removed = m.copy() if removed is None else (removed | m)
                if removed is not None:
                    new_stock = stock & ~removed
                    o._grids = (lambda p=part, s=new_stock: (p, s))
            except Exception as e:
                warnings.append("stock after %s could not be predicted (%s) - "
                                "later setups were planned against the "
                                "previous stock" % (d, e))
            o.setups_done.append(d)
            if plan.get("facing"):
                o._faced = (getattr(o, "_faced", None) or set()) | {d}
            o.state = (o.state or 0) + 1
            o._plan = None
            o._committed = None
            o._plan_rows_run = set()
            first = False

        if len(setups) > 1:
            warnings.append("setups after the first are costed against v3's "
                            "PREDICTED stock (billet minus the swept reach of "
                            "the tools chosen before), not PowerMill's "
                            "measured live stock - a live run re-plans after "
                            "every cut")
        warnings.append("v3's own time model is ~2x (planner.py docstring); "
                        "each tool change is priced at %g min"
                        % PL.TOOL_CHANGE_MIN)
        out["plan"] = {"tools": tools_out, "setups": setups,
                       "total_minutes": round(total, 1),
                       "cutting_minutes": round(total - change_min, 1),
                       "tool_change_minutes": round(change_min, 1),
                       "tool_change_min_each": PL.TOOL_CHANGE_MIN,
                       "tool_changes": changes}
        out["forced_small_tools"] = forced
        out["timings"] = timings
        try:
            with io.open(os.path.splitext(a.out)[0] + "_rawplans.json", "w",
                         encoding="utf-8") as fh:
                json.dump(raw, fh, default=_jsonable, indent=1)
        except Exception:
            pass

    out["warnings"] = warnings
    out["runtime_s"] = round(time.time() - t_start, 1)
    out["log"] = log_path
    with io.open(a.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, default=_jsonable, indent=1)
    print(json.dumps({"ok": True, "out": a.out, "runtime_s": out["runtime_s"]}))


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--holes-only":
        holes_only(sys.argv[2])
        sys.exit(0)
    try:
        main()
    except BaseException as e:
        print(json.dumps({"ok": False, "error": "%s: %s" % (type(e).__name__, e),
                          "trace": traceback.format_exc()[-2000:]}))
        sys.exit(1)
