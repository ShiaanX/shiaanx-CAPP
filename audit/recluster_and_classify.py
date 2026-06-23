"""
Re-run stages 2–8 from existing features_motormount.json.
Saves all outputs as *_motormount_postfix.* in the audit directory.
Used to test changes to cluster_features.py (Z-level plane separation).
"""
import sys
import os
import json
import time
import importlib.util
from collections import Counter

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
    # Load existing features JSON (stage 1 output)
    features_path = os.path.join(AUDIT_DIR, "features_motormount.json")
    with open(features_path) as f:
        features = json.load(f)
    print(f"Loaded: {features_path}")
    print(f"  Faces: {features['topology_counts']['Faces']}")

    # Stage 2 — Cluster Features (using updated connected-component seeding)
    cluster_mod = load_module("2. cluster_features.py")
    clustered   = run_stage("2. cluster_features",
                            lambda: cluster_mod.cluster_features(features))
    # cluster_features returns a LIST of cluster dicts; save_clusters wraps it
    clustered_out = {'clusters': clustered}
    # Pass through metadata from features
    for key in ['file', 'bounding_box', 'mass_properties', 'surface_area', 'topology_counts']:
        if key in features:
            clustered_out[key] = features[key]
    save_json(clustered_out, "clustered_motormount_postfix.json")

    n_plane  = sum(1 for c in clustered if c.get('seed_type') == 'plane')
    n_bore   = sum(1 for c in clustered if c.get('seed_type') == 'bore')
    n_bg     = sum(1 for c in clustered if c.get('seed_type') == 'background')
    print(f"  Clusters: {len(clustered)} total  (plane={n_plane}, bore={n_bore}, background={n_bg})")

    # Stage 3 — Classify Features
    classify_mod = load_module("3. classify_features.py")
    classified   = run_stage("3. classify_features",
                             lambda: classify_mod.classify_clusters(clustered_out))
    save_json(classified, "classified_motormount_postfix.json")

    # Print feature type distribution
    clusters_out = classified.get('clusters', [])
    type_counts  = Counter(c.get('feature_type') for c in clusters_out)
    print("  Feature type distribution:")
    for ft, n in sorted(type_counts.items()):
        print(f"    {ft:<30}: {n}")

    # Spot-check key clusters
    print("\n  Key cluster checks:")
    for c in clusters_out:
        cid = c.get('cluster_id')
        if c.get('feature_type') in ('pocket', 'planar_face', 'large_bore') or (
                c.get('face_count', 0) > 100):
            print(f"    id={cid} type={c['feature_type']} area={c.get('face_area')} "
                  f"perp_walls={c.get('perp_wall_count')} face_count={c.get('face_count')}")

    # Stage 4 — Process Selection
    process_mod = load_module("4. process_selection.py")
    processes   = run_stage("4. process_selection",
                            lambda: process_mod.select_processes(classified))
    save_json(processes, "processes_motormount_postfix.json")

    # Stage 5 — Setup Planning
    setup_mod = load_module("5. setup_planning.py")
    setups    = run_stage("5. setup_planning",
                          lambda: setup_mod.plan_setups(processes))
    save_json(setups, "setups_motormount_postfix.json")

    # Stage 6 — Tool Selection
    tool_mod = load_module("7. tool_selection.py")
    tools    = run_stage("6. tool_selection",
                         lambda: tool_mod.select_tools(setups))
    save_json(tools, "tools_motormount_postfix.json")

    # Stage 7 — Parameter Calculation
    param_mod = load_module("8. parameter_calculation.py")
    params    = run_stage("7. parameter_calculation",
                          lambda: param_mod.calculate_parameters(tools))
    save_json(params, "params_motormount_postfix.json")

    # Stage 8 — Program Sheet
    try:
        sheet_mod = load_module("9. program_sheet.py")
        out_pdf   = os.path.join(AUDIT_DIR, "program_sheet_motormount_postfix.pdf")
        run_stage("8. program_sheet",
                  lambda: sheet_mod.generate_program_sheet(params, out_pdf))
        print(f"  PDF: {out_pdf}")
    except Exception as e:
        print(f"  WARNING: program_sheet failed: {e}")

    print("\n" + "=" * 60)
    print("Recluster + classify complete.")


if __name__ == "__main__":
    main()
