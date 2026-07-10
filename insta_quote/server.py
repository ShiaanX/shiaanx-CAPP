"""
insta_quote/server.py
Thin Flask wrapper around the ShiaanX CAPP pipeline that exposes the two
endpoints expected by shiaanx-backend's auto-quote.service.js:

    GET  /health   → {"status": "ok", "pipeline": "shiaanx-capp"}
    POST /process  → multipart: file=<step>, material=<str>, qty=<int>
                   ← {"state": { ...quote fields... }, "ok": true}

Run:
    & "C:\Users\Siddhant Gupta\miniconda3\envs\occ\python.exe" insta_quote/server.py
"""

import os
import sys
import json
import math
import uuid
import shutil
import tempfile
import importlib.util
from pathlib import Path
from flask import Flask, request, jsonify

# ─── Pipeline root ─────────────────────────────────────────────────────────────
PIPELINE_DIR = Path(__file__).parent.parent / "Claude output for program sheet"
PIPELINE_PYTHON = sys.executable  # same occ env

app = Flask(__name__)


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_pipeline(step_path: Path, material: str) -> dict:
    """Run all 8 pipeline stages and return the params dict."""
    import subprocess
    runner = PIPELINE_DIR / "10. run_pipeline.py"
    result = subprocess.run(
        [sys.executable, str(runner), str(step_path), "--material", material],
        capture_output=True, text=True, cwd=str(PIPELINE_DIR), timeout=300
    )
    if result.returncode != 0:
        raise RuntimeError(f"Pipeline failed:\n{result.stderr[-2000:]}")

    # pipeline writes params JSON next to the STEP file
    stem = step_path.stem
    params_path = step_path.parent / f"{stem}_params.json"
    if not params_path.exists():
        raise FileNotFoundError(f"params JSON not found at {params_path}")

    with open(params_path) as f:
        return json.load(f)


def _params_to_quote_state(params: dict, material: str, qty: int) -> dict:
    """Convert pipeline params JSON into the quote state schema."""
    clusters = params.get("clusters", [])
    setups_raw = params.get("setups", [])

    # Count setups from params (either top-level setups array or deduplicate from clusters)
    setup_ids = set()
    for c in clusters:
        sid = c.get("setup_id") or c.get("wcs")
        if sid is not None:
            setup_ids.add(sid)
    setup_count = len(setups_raw) if setups_raw else max(len(setup_ids), 1)

    # Feature counts
    feature_count = len(clusters)
    op_types = {}
    total_ops = 0
    for c in clusters:
        for op in c.get("process_sequence", []):
            op_name = op.get("operation", "")
            op_types[op_name] = op_types.get(op_name, 0) + 1
            total_ops += 1

    face_mill_count = op_types.get("face_mill", 0)
    circular_interp_count = op_types.get("circular_interp", 0)
    contour_mill_count = op_types.get("contour_mill", 0)

    # Cycle time estimate: sum vf_based cycle per op (rough: ap*ae/vf heuristic not available)
    # Use op count × avg time per op type (seconds) as a simple estimate
    OP_TIME_S = {
        "face_mill": 45, "contour_mill": 60, "pocket_mill": 90,
        "twist_drill": 20, "spot_drill": 15, "center_drill": 15,
        "circular_interp": 30, "boring_bar": 25, "chamfer_mill": 20,
        "slot_mill": 40, "tap_rh": 10,
    }
    cycle_s = sum(count * OP_TIME_S.get(op, 30) for op, count in op_types.items())
    cycle_min = round(cycle_s / 60, 2)

    # Bounding box → stock dimensions
    bb = params.get("bounding_box", {})
    stock_x = round(bb.get("x_mm", 0) * 1.05, 1)
    stock_y = round(bb.get("y_mm", 0) * 1.05, 1)
    stock_z = round(bb.get("z_mm", 0) * 1.05, 1)

    # Mass (aluminium 6061 density 2.70 g/cm³)
    DENSITY = {"aluminium": 2.70, "steel": 7.85, "mild_steel": 7.85, "titanium": 4.43}
    density = DENSITY.get(material.lower().replace(" ", "_"), 7.85)
    stock_vol_cm3 = (stock_x * stock_y * stock_z) / 1000
    stock_mass = round(stock_vol_cm3 * density / 1000, 3)

    mass_props = params.get("mass_properties", {})
    part_mass = round(mass_props.get("volume_mm3", stock_vol_cm3 * 1000) * density / 1e6, 3)
    removed_mass = round(max(stock_mass - part_mass, 0), 3)

    # Unique operation types
    unique_ops = len(op_types)
    weighted_features = round(feature_count * 1.4, 1)

    return {
        "partName": params.get("file", "Part").replace("_params", ""),
        "quantity": qty,
        "materialName": material,
        "setupCount": setup_count,
        "stepCount": total_ops,
        "cycleTimeMin": cycle_min,
        "uniqueOperations": unique_ops,
        "weightedFeatures": weighted_features,
        "featureCount": feature_count,
        "faceMillCount": face_mill_count,
        "circularInterpCount": circular_interp_count,
        "contourMillCount": contour_mill_count,
        "stockMassKg": stock_mass,
        "partMassKg": part_mass,
        "removedMassKg": removed_mass,
        "stockX": stock_x,
        "stockY": stock_y,
        "stockZ": stock_z,
        # Cost drivers — sensible defaults; frontend overrides with its own rates
        "materialRate": 75 if "aluminium" in material.lower() else 150,
        "machineRate": 400,
        "setupTimePerSetupMin": 30,
        "setupCostPerMin": 25,
        "fixtureCost": 0,
        "inspectionBaseHours": 1,
        "inspectionPerSetupHours": 0.35,
        "inspectionPerFeatureHours": 0.03,
        "inspectionRateCmm": 1000,
        "inspectionRateManual": 600,
        "packagingCost": 1500,
        "shippingCost": 1500,
        "miscCost": 350,
        "gstPercent": 18,
        "inspectionType": "Manual Inspection",
        "packagingType": "Wooden Box",
        "shippingType": "Train",
        "notes": f"Auto-generated by ShiaanX CAPP pipeline. Material: {material}.",
        "finishes": [],
        "secondaryOps": [],
        "extraCharges": [],
        "_source": "pipeline",
    }


# ─── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return jsonify({"status": "ok", "pipeline": "shiaanx-capp", "version": "1.0"})


@app.post("/process")
def process():
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "No file uploaded"}), 400

    file = request.files["file"]
    material = request.form.get("material", "aluminium")
    qty = int(request.form.get("qty", 1))

    # Save STEP to a temp dir
    tmp_dir = Path(tempfile.mkdtemp(prefix="shx_"))
    try:
        safe_name = Path(file.filename).name if file.filename else "part.step"
        step_path = tmp_dir / safe_name
        file.save(str(step_path))

        params = _run_pipeline(step_path, material)
        state = _params_to_quote_state(params, material, qty)
        return jsonify({"ok": True, "state": state})

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ─── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("INSTA_QUOTE_PORT", 5001))
    print(f"[ShiaanX Insta-Quote] Listening on http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
