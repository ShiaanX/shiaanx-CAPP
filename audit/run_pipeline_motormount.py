"""
Run the full ShiaanX CAPP pipeline on the Motor Mount STEP file.
Saves all intermediate outputs with _motormount_ prefix in the audit/ directory.
"""
import sys
import os
import json
import shutil
import time

PIPELINE_DIR = r"C:\Users\Siddhant Gupta\Documents\ShiaanX\Claude output for program sheet"
STEP_FILE    = r"G:\My Drive\Closed Loop\Motor Mount\input\MOTOR MOUNT.step"
AUDIT_DIR    = r"C:\Users\Siddhant Gupta\Documents\ShiaanX\audit"
PYTHON_EXE   = r"C:\Users\Siddhant Gupta\miniconda3\envs\occ\python.exe"

sys.path.insert(0, PIPELINE_DIR)

import importlib.util

def load_module(script_name):
    path = os.path.join(PIPELINE_DIR, script_name)
    spec = importlib.util.spec_from_file_location("mod", path)
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
    os.makedirs(AUDIT_DIR, exist_ok=True)

    if not os.path.exists(STEP_FILE):
        print(f"HARD STOP: STEP file not found: {STEP_FILE}")
        sys.exit(1)

    print(f"Pipeline starting on: {STEP_FILE}")
    print(f"Output directory: {AUDIT_DIR}")

    # Stage 1 — Feature Extraction
    try:
        extract_mod = load_module("1. extract_features.py")
        features = run_stage("1. extract_features", lambda: extract_mod.extract_features(STEP_FILE))
        save_json(features, "features_motormount.json")
    except Exception as e:
        print(f"\nHARD STOP at Stage 1 (extract_features): {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)

    # Stage 2 — Cluster Features
    try:
        cluster_mod = load_module("2. cluster_features.py")
        clustered = run_stage("2. cluster_features", lambda: cluster_mod.cluster_features(features))
        save_json(clustered, "clustered_motormount.json")
    except Exception as e:
        print(f"\nERROR at Stage 2 (cluster_features): {e}")
        import traceback; traceback.print_exc()
        sys.exit(2)

    # Stage 3 — Classify Features
    try:
        classify_mod = load_module("3. classify_features.py")
        classified = run_stage("3. classify_features", lambda: classify_mod.classify_features(clustered))
        save_json(classified, "classified_motormount.json")
    except Exception as e:
        print(f"\nERROR at Stage 3 (classify_features): {e}")
        import traceback; traceback.print_exc()
        sys.exit(3)

    # Stage 4 — Process Selection
    try:
        process_mod = load_module("4. process_selection.py")
        processes = run_stage("4. process_selection", lambda: process_mod.select_processes(classified))
        save_json(processes, "processes_motormount.json")
    except Exception as e:
        print(f"\nERROR at Stage 4 (process_selection): {e}")
        import traceback; traceback.print_exc()
        sys.exit(4)

    # Stage 5 — Setup Planning
    try:
        setup_mod = load_module("5. setup_planning.py")
        setups = run_stage("5. setup_planning", lambda: setup_mod.plan_setups(processes))
        save_json(setups, "setups_motormount.json")
    except Exception as e:
        print(f"\nERROR at Stage 5 (setup_planning): {e}")
        import traceback; traceback.print_exc()
        sys.exit(5)

    # Stage 6 — Tool Selection
    try:
        tool_mod = load_module("7. tool_selection.py")
        tools = run_stage("6. tool_selection", lambda: tool_mod.select_tools(setups))
        save_json(tools, "tools_motormount.json")
    except Exception as e:
        print(f"\nERROR at Stage 6 (tool_selection): {e}")
        import traceback; traceback.print_exc()
        sys.exit(6)

    # Stage 7 — Parameter Calculation
    try:
        param_mod = load_module("8. parameter_calculation.py")
        params = run_stage("7. parameter_calculation", lambda: param_mod.calculate_parameters(tools))
        save_json(params, "params_motormount.json")
    except Exception as e:
        print(f"\nERROR at Stage 7 (parameter_calculation): {e}")
        import traceback; traceback.print_exc()
        sys.exit(7)

    # Stage 8 — Program Sheet
    try:
        sheet_mod = load_module("9. program_sheet.py")
        out_pdf = os.path.join(AUDIT_DIR, "program_sheet_motormount.pdf")
        run_stage("8. program_sheet", lambda: sheet_mod.generate_program_sheet(params, out_pdf))
        print(f"  PDF: {out_pdf}")
    except Exception as e:
        print(f"\nERROR at Stage 8 (program_sheet): {e}")
        import traceback; traceback.print_exc()

    print("\n" + "="*60)
    print("Pipeline complete.")

if __name__ == "__main__":
    main()
