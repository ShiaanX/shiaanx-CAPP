"""
fixture_planner.py — ShiaanX Fixture Design Module

Takes *_setups.json + *_features.json and outputs a fixture_spec per setup.
Run standalone: python fixture_planner.py <setups.json> <features.json>
"""
import json
import math
import os
import sys


def _round_up_to_5(value: float) -> float:
    return math.ceil(value / 5.0) * 5.0


def _is_angled_direction(direction: list) -> bool:
    """Return True if spindle direction is not a principal axis."""
    if not direction:
        return False
    abs_comps = [abs(c) for c in direction]
    return max(abs_comps) < 0.95


def _bbox_dim_perpendicular_to_clamped(bbox: dict, clamp_faces: list) -> float:
    """Return the bounding-box dimension in the clamped axis direction."""
    clamp_axis = None
    for face in clamp_faces:
        if "X" in face.upper():
            clamp_axis = "x"
            break
        elif "Y" in face.upper():
            clamp_axis = "y"
            break
        elif "Z" in face.upper():
            clamp_axis = "z"
            break
    if clamp_axis == "x":
        return bbox.get("length_x", 0.0)
    elif clamp_axis == "y":
        return bbox.get("length_y", 0.0)
    elif clamp_axis == "z":
        return bbox.get("length_z", 0.0)
    return bbox.get("length_x", 0.0)


def _has_nonplanar_rest_face(setups_data: dict, setup: dict) -> bool:
    """
    Check if the rest face of a PREVIOUSLY MACHINED setup has non-planar geometry.
    Only relevant for setup 2+ where the rest face was machined in a prior setup.
    Raw billet rest faces (setup 1) are always flat — never flag those.
    """
    stock = setup.get("stock", {})
    if stock.get("type") == "raw_billet":
        return False

    machined_faces = stock.get("machined_faces", [])
    rest_face = setup.get("workholding", {}).get("rest_face", "")
    rest_axis = rest_face.lstrip("+-")

    if rest_face not in machined_faces:
        return False

    clusters = setups_data.get("clusters", [])
    for cluster in clusters:
        if not isinstance(cluster, dict):
            continue
        feature_type = cluster.get("feature_type", "")
        if feature_type in ("fillet", "bore", "blind_hole", "large_bore"):
            axis = cluster.get("feature_axis", [0, 0, 0])
            if not axis:
                continue
            if rest_axis == "Z" and abs(abs(axis[2]) - 1.0) < 0.1:
                return True
            if rest_axis == "Y" and abs(abs(axis[1]) - 1.0) < 0.1:
                return True
            if rest_axis == "X" and abs(abs(axis[0]) - 1.0) < 0.1:
                return True
    return False


def _determine_fixture_type(setup: dict, jaw_opening_raw: float, is_first_setup: bool) -> str:
    """
    First check if the existing workholding.type gives a specific fixture type.
    Fall back to rule cascade if the type is generic/missing.
    """
    workholding_type = setup.get("workholding", {}).get("type", "")
    if workholding_type in ("vise", "step_jaw_vise", "angle_plate", "sine_plate",
                            "fixture_plate", "custom_soft_jaw"):
        if jaw_opening_raw > 200 and workholding_type == "vise":
            return "fixture_plate"
        return workholding_type

    spindle = setup.get("spindle_direction", [0, 0, 0])
    if _is_angled_direction(spindle):
        if jaw_opening_raw > 100:
            return "sine_plate"
        return "angle_plate"
    if jaw_opening_raw > 200:
        return "fixture_plate"
    if not is_first_setup:
        return "vise"
    if jaw_opening_raw > 100:
        return "step_jaw_vise"
    return "vise"


def _determine_parallels(jaw_opening_mm: float):
    if jaw_opening_mm < 50:
        return None
    elif jaw_opening_mm <= 100:
        return 10.0
    else:
        return 20.0


def _determine_jaw_type(soft_jaw_required: bool, fixture_type: str, is_first_setup: bool) -> str:
    if soft_jaw_required:
        return "custom_profile"
    if fixture_type == "step_jaw_vise":
        return "step_jaw"
    return "standard_hard"


def _z_zero_face_from_setup(setup: dict) -> str:
    stock = setup.get("stock", {})
    stock_type = stock.get("type", "raw_billet")
    if stock_type == "raw_billet":
        return "top_of_stock"
    return "top_of_part"


def _datum_face_from_spindle(spindle_direction: list) -> str:
    """Infer datum face from spindle direction. The face facing the spindle is the datum."""
    if not spindle_direction:
        return "+Z"
    sd = spindle_direction
    abs_sd = [abs(c) for c in sd]
    principal_idx = abs_sd.index(max(abs_sd))
    axes = ["X", "Y", "Z"]
    sign = "+" if sd[principal_idx] < 0 else "-"
    return sign + axes[principal_idx]


def _wcs_xy_zero(setup: dict, bbox: dict) -> str:
    """Use corner zero if part bbox min is near origin (within 2%), else center."""
    xmin = bbox.get("xmin", -1)
    length_x = bbox.get("length_x", 1)
    if length_x > 0 and abs(xmin) < 0.02 * length_x:
        return "corner_of_part"
    return "center_of_part"


def _clamp_clearance(setup: dict, jaw_height_mm: float, parallels_mm) -> float:
    """Estimate clearance between top of jaw and lowest toolpath Z."""
    parallels = parallels_mm or 0.0
    part_height = setup.get("setup_depth", 20.0)
    exposure = part_height - parallels
    clearance = max(1.0, min(exposure * 0.1, 10.0))
    return round(clearance, 1)


def _setup_notes(setup: dict, fixture_spec: dict, is_first_setup: bool) -> list:
    notes = []
    z_zero = fixture_spec["z_zero_face"]
    jaw_open = fixture_spec["jaw_opening_mm"]
    parallels = fixture_spec["parallels_mm"]
    soft = fixture_spec["soft_jaw_required"]
    fixture_type = fixture_spec["fixture_type"]

    if z_zero == "top_of_stock":
        notes.append("Zero off top face of raw billet")
    else:
        notes.append("Zero off previously machined face (probe before clamping)")

    if parallels:
        notes.append(f"Use {int(parallels)}mm parallels under part — seat firmly before torquing vise")

    engagement = (jaw_open - setup.get("setup_face_width", jaw_open)) / 2.0
    if engagement > 0:
        notes.append(f"Minimum {engagement:.0f}mm jaw engagement each side")
    else:
        notes.append(f"Jaw opening set to {jaw_open:.0f}mm — verify engagement before cutting")

    if soft:
        notes.append("SOFT JAWS REQUIRED — machine jaws before loading part")

    if fixture_type == "angle_plate":
        notes.append("Angle plate setup — verify squareness to spindle before zeroing")
    elif fixture_type == "step_jaw_vise":
        notes.append("Step jaw vise — confirm step height clears all features")
    elif fixture_type == "fixture_plate":
        notes.append("Fixture plate — locate on dowel pins, clamp with M8 bolts")

    if not is_first_setup:
        datum_from = setup.get("workholding", {}).get("datum_from_setup")
        if datum_from:
            notes.append(f"Datum from Setup {datum_from} — use finished face as reference")

    return notes


def plan_fixture(setups_data: dict, features_data: dict) -> dict:
    """
    Add fixture_spec to each setup in setups_data.
    Returns updated dict with fixture_spec on each setup.
    """
    result = dict(setups_data)
    setups = result.get("setups", [])
    bbox = features_data.get("bounding_box", {})

    for i, setup in enumerate(setups):
        is_first_setup = (i == 0)
        workholding = setup.get("workholding", {})
        clamp_faces = workholding.get("clamp_faces", ["+X", "-X"])
        rest_face = workholding.get("rest_face", "-Z")
        spindle = setup.get("spindle_direction", [0, 0, -1])

        existing_jaw = workholding.get("jaw_opening_mm", None)
        if existing_jaw and existing_jaw > 0:
            jaw_opening_raw = existing_jaw + 10.0
        else:
            part_dim_in_clamp_dir = _bbox_dim_perpendicular_to_clamped(bbox, clamp_faces)
            jaw_opening_raw = part_dim_in_clamp_dir + 10.0
        jaw_opening_mm = _round_up_to_5(jaw_opening_raw)

        fixture_type = _determine_fixture_type(setup, jaw_opening_raw, is_first_setup)

        nonplanar_rest = _has_nonplanar_rest_face(setups_data, setup)
        soft_jaw_required = (
            nonplanar_rest
            or jaw_opening_mm < 30
        )

        parallels_mm = _determine_parallels(jaw_opening_mm)
        jaw_type = _determine_jaw_type(soft_jaw_required, fixture_type, is_first_setup)
        z_zero_face = _z_zero_face_from_setup(setup)
        datum_face = _datum_face_from_spindle(spindle)
        wcs_xy = _wcs_xy_zero(setup, bbox)
        jaw_height_mm = 38.0
        clamp_clearance = _clamp_clearance(setup, jaw_height_mm, parallels_mm)

        soft_jaw_file = None
        if soft_jaw_required:
            part_name = os.path.splitext(os.path.basename(
                features_data.get("file", "part")))[0]
            setup_id = setup.get("setup_id", i + 1)
            soft_jaw_file = f"{part_name}_setup{setup_id}_soft_jaw_LEFT.step"

        fixture_spec = {
            "fixture_type": fixture_type,
            "vise_model": None,
            "jaw_type": jaw_type,
            "jaw_opening_mm": jaw_opening_mm,
            "jaw_height_mm": jaw_height_mm,
            "parallels_mm": parallels_mm,
            "clamped_faces": clamp_faces,
            "rest_face": rest_face,
            "datum_face": datum_face,
            "z_zero_face": z_zero_face,
            "wcs_xy_zero": wcs_xy,
            "clamp_clearance_mm": clamp_clearance,
            "soft_jaw_required": soft_jaw_required,
            "soft_jaw_profile_file": soft_jaw_file,
            "setup_notes": [],
        }

        fixture_spec["setup_notes"] = _setup_notes(setup, fixture_spec, is_first_setup)

        setup["fixture_spec"] = fixture_spec

    result["setups"] = setups
    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description="ShiaanX fixture planner")
    parser.add_argument("setups_json", help="Path to *_setups.json")
    parser.add_argument("features_json", help="Path to *_features.json")
    parser.add_argument("--out", default=None,
                        help="Output path for fixture_spec JSON (default: <stem>_fixture_spec.json alongside setups)")
    args = parser.parse_args()

    setups_path = args.setups_json
    features_path = args.features_json

    with open(setups_path, encoding="utf-8") as f:
        setups_data = json.load(f)
    with open(features_path, encoding="utf-8") as f:
        features_data = json.load(f)

    result = plan_fixture(setups_data, features_data)

    if args.out:
        out_path = args.out
    else:
        out_dir = os.path.dirname(setups_path)
        part_stem = os.path.splitext(os.path.basename(setups_path))[0].replace("_setups", "")
        out_path = os.path.join(out_dir, f"{part_stem}_fixture_spec.json")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"Fixture spec written to: {out_path}")
    print()
    print("=" * 60)
    print("FIXTURE SUMMARY")
    print("=" * 60)
    for setup in result.get("setups", []):
        sid = setup.get("setup_id")
        fs = setup.get("fixture_spec", {})
        print(f"\nSetup {sid} ({setup.get('axis_label', '')})")
        print(f"  Fixture type : {fs.get('fixture_type')}")
        print(f"  Jaw type     : {fs.get('jaw_type')}")
        print(f"  Jaw opening  : {fs.get('jaw_opening_mm')} mm")
        print(f"  Parallels    : {fs.get('parallels_mm')} mm")
        print(f"  Z reference  : {fs.get('z_zero_face')}")
        print(f"  Soft jaws    : {'YES — ' + str(fs.get('soft_jaw_profile_file')) if fs.get('soft_jaw_required') else 'No'}")
    print()


if __name__ == "__main__":
    main()
