"""
soft_jaw_generator.py — Generate STEP soft jaw solids using PythonOCC

For setups where soft_jaw_required=True, creates a pair of soft jaw STEP files
(LEFT and RIGHT) by boolean-subtracting the part solid from a jaw blank.

Run standalone:
    python soft_jaw_generator.py <fixture_spec.json> <part.step>
"""
import json
import os
import sys

try:
    from OCC.Core.STEPControl import STEPControl_Reader, STEPControl_Writer, STEPControl_AsIs
    from OCC.Core.IFSelect import IFSelect_RetDone
    from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
    from OCC.Core.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCC.Core.BRepOffsetAPI import BRepOffsetAPI_MakeOffsetShape
    from OCC.Core.BRepFilletAPI import BRepFilletAPI_MakeChamfer
    from OCC.Core.BRep import BRep_Builder
    from OCC.Core.TopoDS import TopoDS_Compound
    from OCC.Core.gp import gp_Pnt, gp_Vec, gp_Trsf, gp_Ax2, gp_Dir, gp_Ax1
    from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_Transform, BRepBuilderAPI_MirrorShape
    from OCC.Core.TopExp import TopExp_Explorer
    from OCC.Core.TopAbs import TopAbs_EDGE, TopAbs_FACE
    from OCC.Core.BRep import BRep_Tool
    from OCC.Core.GeomAbs import GeomAbs_Plane
    from OCC.Core.BRepAdaptor import BRepAdaptor_Surface
    OCC_AVAILABLE = True
except ImportError:
    OCC_AVAILABLE = False


def _load_part_shape(step_path: str):
    """Load a STEP file and return the compound shape."""
    reader = STEPControl_Reader()
    status = reader.ReadFile(step_path)
    if status != IFSelect_RetDone:
        raise RuntimeError(f"Failed to read STEP file: {step_path}")
    reader.TransferRoots()
    return reader.OneShape()


def _write_step(shape, output_path: str) -> bool:
    """Write a shape to a STEP file. Returns True on success."""
    writer = STEPControl_Writer()
    writer.Transfer(shape, STEPControl_AsIs)
    status = writer.Write(output_path)
    return status == IFSelect_RetDone


def _make_jaw_blank(jaw_width: float, jaw_depth: float, jaw_height: float):
    """Create a rectangular jaw blank solid."""
    return BRepPrimAPI_MakeBox(
        gp_Pnt(-jaw_width / 2, 0, 0),
        jaw_width, jaw_depth, jaw_height
    ).Shape()


def _translate_shape(shape, dx: float, dy: float, dz: float):
    """Apply a translation transform to a shape."""
    trsf = gp_Trsf()
    trsf.SetTranslation(gp_Vec(dx, dy, dz))
    return BRepBuilderAPI_Transform(shape, trsf, True).Shape()


def _make_screw_holes(jaw_width: float, jaw_depth: float, jaw_height: float):
    """Make two M8 clearance holes (dia=8.5mm) through the jaw."""
    cyl1 = BRepPrimAPI_MakeCylinder(
        gp_Ax2(gp_Pnt(-jaw_width / 2 + 30, 0, jaw_height / 2), gp_Dir(0, 1, 0)),
        4.25, jaw_depth
    ).Shape()
    cyl2 = BRepPrimAPI_MakeCylinder(
        gp_Ax2(gp_Pnt(jaw_width / 2 - 30, 0, jaw_height / 2), gp_Dir(0, 1, 0)),
        4.25, jaw_depth
    ).Shape()
    return cyl1, cyl2


def _apply_pocket_offset(part_shape, offset_mm: float = 0.1):
    """Apply a small positive offset to the part shape for interference fit."""
    try:
        offseter = BRepOffsetAPI_MakeOffsetShape()
        offseter.PerformBySimple(part_shape, offset_mm)
        if offseter.IsDone():
            return offseter.Shape()
    except Exception:
        pass
    return part_shape


def _mirror_shape(shape, axis: str = "YZ"):
    """Mirror a shape about the YZ plane (for right jaw)."""
    trsf = gp_Trsf()
    if axis == "YZ":
        trsf.SetMirror(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(1, 0, 0)))
    return BRepBuilderAPI_Transform(shape, trsf, True).Shape()


def generate_soft_jaw(
    part_step_path: str,
    fixture_spec: dict,
    setup: dict,
    output_dir: str,
    part_stem: str,
    setup_id: int,
) -> dict:
    """
    Generate left and right soft jaw STEP files for one setup.

    Returns dict with:
        left_file: path to left jaw STEP
        right_file: path to right jaw STEP
        simplified: True if boolean subtraction fell back to simplified profile
        notes: list of warnings
    """
    if not OCC_AVAILABLE:
        return {"error": "PythonOCC not available", "left_file": None, "right_file": None}

    notes = []
    simplified = False

    jaw_opening_mm = fixture_spec.get("jaw_opening_mm", 70.0)
    parallels_mm = fixture_spec.get("parallels_mm") or 0.0
    jaw_height_mm = fixture_spec.get("jaw_height_mm", 38.0)

    setup_depth = setup.get("setup_depth", 30.0)
    part_grip_height = min(setup_depth, 20.0)

    jaw_width = jaw_opening_mm + 40.0
    jaw_depth = 60.0
    total_jaw_height = parallels_mm + part_grip_height + 5.0

    try:
        part_shape = _load_part_shape(part_step_path)
    except Exception as e:
        return {"error": str(e), "left_file": None, "right_file": None}

    jaw_blank = _make_jaw_blank(jaw_width, jaw_depth, total_jaw_height)

    try:
        part_offset = _apply_pocket_offset(part_shape, 0.1)
        part_positioned = _translate_shape(part_offset, 0, jaw_depth / 2, parallels_mm)

        cut_result = BRepAlgoAPI_Cut(jaw_blank, part_positioned)
        if not cut_result.IsDone():
            raise RuntimeError("Boolean cut failed")
        jaw_with_pocket = cut_result.Shape()
    except Exception as e:
        notes.append(f"WARNING: Boolean subtraction failed ({e}). Using simplified rectangular pocket.")
        simplified = True
        bbox = setup.get("setup_face_width", jaw_opening_mm - 10)
        pocket_depth = part_grip_height
        try:
            pocket_solid = BRepPrimAPI_MakeBox(
                gp_Pnt(-bbox / 2, 0, parallels_mm),
                bbox, jaw_depth / 2, pocket_depth
            ).Shape()
            cut2 = BRepAlgoAPI_Cut(jaw_blank, pocket_solid)
            if cut2.IsDone():
                jaw_with_pocket = cut2.Shape()
            else:
                jaw_with_pocket = jaw_blank
        except Exception:
            jaw_with_pocket = jaw_blank
            notes.append("WARNING: Simplified pocket also failed. Outputting blank jaw only.")

    try:
        c1, c2 = _make_screw_holes(jaw_width, jaw_depth, total_jaw_height)
        jaw_drilled = BRepAlgoAPI_Cut(jaw_with_pocket, c1).Shape()
        jaw_drilled = BRepAlgoAPI_Cut(jaw_drilled, c2).Shape()
    except Exception as e:
        jaw_drilled = jaw_with_pocket
        notes.append(f"Note: Screw holes skipped ({e})")

    suffix = "_SIMPLIFIED" if simplified else ""

    left_filename = f"{part_stem}_setup{setup_id}_soft_jaw_LEFT{suffix}.step"
    right_filename = f"{part_stem}_setup{setup_id}_soft_jaw_RIGHT{suffix}.step"
    left_path = os.path.join(output_dir, left_filename)
    right_path = os.path.join(output_dir, right_filename)

    ok_left = _write_step(jaw_drilled, left_path)
    if not ok_left:
        notes.append(f"WARNING: Failed to write left jaw STEP to {left_path}")

    try:
        right_jaw = _mirror_shape(jaw_drilled, "YZ")
        ok_right = _write_step(right_jaw, right_path)
        if not ok_right:
            notes.append(f"WARNING: Failed to write right jaw STEP to {right_path}")
    except Exception as e:
        right_path = None
        notes.append(f"Note: Right jaw mirroring failed ({e})")

    for note in notes:
        print(note)

    print(f"  Left jaw  → {left_path}")
    if right_path:
        print(f"  Right jaw → {right_path}")

    return {
        "left_file": left_path if ok_left else None,
        "right_file": right_path,
        "simplified": simplified,
        "notes": notes,
    }


def main():
    if len(sys.argv) < 3:
        print("Usage: soft_jaw_generator.py <fixture_spec.json> <part.step>")
        sys.exit(1)

    fixture_spec_path = sys.argv[1]
    part_step_path = sys.argv[2]

    with open(fixture_spec_path, encoding="utf-8") as f:
        data = json.load(f)

    part_stem = os.path.splitext(os.path.basename(part_step_path))[0]
    output_dir = os.path.dirname(part_step_path)

    setups = data.get("setups", [])
    generated = 0
    for i, setup in enumerate(setups):
        fs = setup.get("fixture_spec", {})
        if not fs.get("soft_jaw_required", False):
            continue

        setup_id = setup.get("setup_id", i + 1)
        print(f"\nGenerating soft jaws for Setup {setup_id}...")
        result = generate_soft_jaw(
            part_step_path=part_step_path,
            fixture_spec=fs,
            setup=setup,
            output_dir=output_dir,
            part_stem=part_stem,
            setup_id=setup_id,
        )
        if result.get("error"):
            print(f"  ERROR: {result['error']}")
        else:
            generated += 1

    if generated == 0:
        print("No soft jaws required for any setup.")
    else:
        print(f"\nGenerated soft jaw pairs for {generated} setup(s).")


if __name__ == "__main__":
    main()
