"""
Re-run stages 3–8 of the CAPP pipeline on existing clustered_motormount.json.
Saves all outputs as *_motormount_postfix.* in the audit directory.
"""
import sys
import os
import json
import time
import importlib.util

PIPELINE_DIR = r"C:\Users\Siddhant Gupta\Documents\ShiaanX\Claude output for program sheet"
AUDIT_DIR    = r"C:\Users\Siddhant Gupta\Documents\ShiaanX\audit"
sys.path.insert(0, PIPELINE_DIR)


def load_module(script_name):
    path = os.path.join(PIPELINE_DIR, script_name)
    spec = importlib.util.spec_from_file_location("mod_" + script_name[:2], path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def save_json(data, name):
    out = os.path.join(AUDIT_DIR, name)
    with open(out, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  Saved: {out}")
    return out


def run_stage(label, fn):
    print(f"\n{'='*60}")
    print(f"Stage: {label}")
    t0 = time.time()
    result = fn()
    elapsed = time.time() - t0
    print(f"  Done in {elapsed:.1f}s")
    return result


def main():
    # Load existing clustered JSON (stages 1+2 already done)
    clustered_path = os.path.join(AUDIT_DIR, "clustered_motormount.json")
    with open(clustered_path) as f:
        clustered = json.load(f)
    print(f"Loaded: {clustered_path}")
    print(f"  Clusters: {len(clustered.get('clusters', []))}")

    # Stage 3 — Classify Features
    classify_mod = load_module("3. classify_features.py")
    classified = run_stage("3. classify_features",
                           lambda: classify_mod.classify_clusters(clustered))
    save_json(classified, "classified_motormount_postfix.json")

    # Verify the 16.1mm bore (id=22) and shallow bores (id=7,8)
    for c in classified.get("clusters", []):
        cid = c.get("cluster_id")
        if cid in (7, 8, 22):
            r = c.get("radii", [])
            print(f"  id={cid} type={c['feature_type']} r={r} "
                  f"depth={c.get('depth')} face_count={c.get('face_count')}")

    # Stage 4 — Process Selection
    process_mod = load_module("4. process_selection.py")
    processes = run_stage("4. process_selection",
                          lambda: process_mod.select_processes(classified))
    save_json(processes, "processes_motormount_postfix.json")

    # Stage 5 — Setup Planning
    setup_mod = load_module("5. setup_planning.py")
    setups = run_stage("5. setup_planning",
                       lambda: setup_mod.plan_setups(processes))
    save_json(setups, "setups_motormount_postfix.json")

    # Stage 6 — Tool Selection
    tool_mod = load_module("7. tool_selection.py")
    tools = run_stage("6. tool_selection",
                      lambda: tool_mod.select_tools(setups))
    save_json(tools, "tools_motormount_postfix.json")

    # Stage 7 — Parameter Calculation
    param_mod = load_module("8. parameter_calculation.py")
    params = run_stage("7. parameter_calculation",
                       lambda: param_mod.calculate_parameters(tools))
    save_json(params, "params_motormount_postfix.json")

    # Stage 8 — Program Sheet
    try:
        sheet_mod = load_module("9. program_sheet.py")
        out_pdf = os.path.join(AUDIT_DIR, "program_sheet_motormount_postfix.pdf")
        run_stage("8. program_sheet",
                  lambda: sheet_mod.generate_program_sheet(params, out_pdf))
        print(f"  PDF: {out_pdf}")
    except Exception as e:
        print(f"  WARNING: program_sheet failed: {e}")

    print("\n" + "=" * 60)
    print("Postfix pipeline complete.")


if __name__ == "__main__":
    main()
