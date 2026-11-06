"""
Build a QC sheet the labeling/QC service (labeling_app/local_app) can seed a 3D QC view from,
with the balloon -> CAD face links pre-made, so no manual tagging is needed.

Inputs (all real, nothing invented):
  --step        the part STEP
  --drawing-report  shop QC report whose rows are the drawing characteristics (SL No., Description, TOL+, TOL-)
  --readings    one or more shop QC reports; every sheet's per-part observations are merged as readings
Output: .xlsx with sheets
  "QC sheet"   SL No. | Description | TOL+ | TOL- | Instrument | P1..Pn readings | Remark   (the format the service parses)
  "Face links" Balloon | Faces A | Faces B | Dim type | Notes   (+ STEP sha256 / total faces) - ingested by /dimensions/seed
  "Notes"      provenance and drawing-vs-CAD flags

Face links come from capp_service.demo_modules.cmm matching (same logic as the CMM program):
diameter -> the cylinder faces of the matched bore; linear -> the matched opposed plane pair (A, B).

Run with the occ env:  python inspection/build_qc_sheet.py --step ... --drawing-report ... --readings ... -o out.xlsx
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import sys
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _load_qc_sheet():
    spec = importlib.util.spec_from_file_location(
        "qc_sheet_mod", ROOT / "Claude output for program sheet" / "labeling_app" / "local_app" / "qc_sheet.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


qs = _load_qc_sheet()


def read_report(path: Path):
    """Return (rows, per_sheet_readings). rows: first sheet's numbered rows; readings: {balloon: [floats]}."""
    wb = openpyxl.load_workbook(path, data_only=True)
    rows, readings, remarks = {}, {}, {}
    for ws in wb.worksheets:
        in_table, obs_col, rem_col = False, 5, 9
        for cells in ws.iter_rows(values_only=True):
            first = cells[0] if cells else None
            if isinstance(first, str) and first.strip().lower().startswith("sl"):
                in_table = True
                obs_col = qs._header_column(cells, "observ", 5)
                rem_col = qs._header_column(cells, "remark", 9)
                continue
            if not in_table:
                continue
            n = qs._number(first)
            if n is None or n != int(n) or n < 1:
                if isinstance(first, str) and first.strip():
                    in_table = False
                continue
            b = int(n)
            dim_type, nominal = qs.parse_description(cells[1])
            rows.setdefault(b, {"balloon": b, "dim_type": dim_type, "nominal": nominal,
                                "tol_plus": qs._number(cells[2]), "tol_minus": qs._number(cells[3]),
                                "instrument": cells[4], "description": cells[1]})
            vals = qs._readings(cells, obs_col, rem_col)
            readings.setdefault(b, []).extend(vals)
            rem = qs._cell(cells, rem_col)
            if rem:
                remarks.setdefault(b, []).append(str(rem).strip())
    return rows, readings, remarks


def count_faces(step: Path) -> int:
    from OCC.Core.IFSelect import IFSelect_RetDone
    from OCC.Core.STEPControl import STEPControl_Reader
    from OCC.Core.TopAbs import TopAbs_FACE
    from OCC.Core.TopExp import TopExp_Explorer
    r = STEPControl_Reader()
    if r.ReadFile(str(step)) != IFSelect_RetDone:
        raise RuntimeError("cannot read STEP")
    r.TransferRoots()
    e = TopExp_Explorer(r.OneShape(), TopAbs_FACE)
    n = 0
    while e.More():
        n += 1
        e.Next()
    return n


def match_links(step: Path, dims: list[dict]):
    """balloon -> {faces_a, faces_b, dim_type, cad_value, mismatch, how}"""
    import tempfile
    from capp_service.demo_modules import cmm, step_geometry
    geo = step_geometry.load_or_extract(Path(tempfile.mkdtemp()), step)
    holes, pairs = cmm._holes(geo), cmm._plane_pairs(geo)
    used_h, used_p = set(), set()
    out = {}
    for d in dims:
        ch = {"nominal_mm": d["nominal"], "upper_tol_mm": d["tol_plus"] or 0, "lower_tol_mm": d["tol_minus"] or 0}
        if d["dim_type"] == "diameter":
            m = cmm._match_diameter(ch, holes, used_h)
            if m:
                out[d["balloon"]] = {"faces_a": m["geometry"]["face_indices"], "faces_b": [], "dim_type": "diameter",
                                     "cad_value": m["geometry"]["cad_value_mm"], "mismatch": m["cad_nominal_mismatch"]}
        else:
            m = cmm._match_linear(ch, pairs, used_p, geo)
            if m and m["type"] == "distance_plane_plane":
                a, b = m["geometry"]["face_indices"]
                out[d["balloon"]] = {"faces_a": [a], "faces_b": [b], "dim_type": "linear",
                                     "cad_value": m["geometry"]["cad_value_mm"], "mismatch": m["cad_nominal_mismatch"]}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", required=True)
    ap.add_argument("--drawing-report", required=True)
    ap.add_argument("--readings", nargs="+", required=True)
    ap.add_argument("--part-name", default="Motor mount")
    ap.add_argument("--note", action="append", default=[], help="BALLOON=text extra note (repeatable)")
    ap.add_argument("-o", "--output", required=True)
    a = ap.parse_args()
    step = Path(a.step)

    rows, drawing_readings, drawing_remarks = read_report(Path(a.drawing_report))
    dims = [r for r in sorted(rows.values(), key=lambda r: r["balloon"]) if r["nominal"] is not None]
    links = match_links(step, dims)

    # readings: drawing report first (its own parts), then each extra report; each sheet column group is one batch
    all_readings = {d["balloon"]: list(drawing_readings.get(d["balloon"], [])) for d in dims}
    last_remark = {b: (v[-1] if v else "") for b, v in drawing_remarks.items()}
    sources = [Path(a.drawing_report).name]
    for rp in a.readings:
        if Path(rp).resolve() == Path(a.drawing_report).resolve():
            continue
        _, rd, rm = read_report(Path(rp))
        sources.append(str(rp))
        for d in dims:
            all_readings[d["balloon"]].extend(rd.get(d["balloon"], []))
        for b, v in rm.items():
            last_remark[b] = v[-1]

    extra = dict(n.split("=", 1) for n in a.note)
    sha = hashlib.sha256(step.read_bytes()).hexdigest()
    total_faces = count_faces(step)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "QC sheet"
    bold = Font(bold=True)
    ws.append(["ShiaanX", None, "FINAL INSPECTION REPORT (QC sheet for 3D QC view)"])
    ws.append([f"Part Name: {a.part_name}", None, None, None, "Material: Aluminum"])
    ws.append(["Drawing: motor mount.pdf (Aviocian Technologies), dimensions as on drawing"])
    ws.append([])
    max_n = max(len(v) for v in all_readings.values()) if all_readings else 0
    ws.append(["SL No.", "Description", "TOL+", "TOL-", "Measuring Instrument", "Observation"] + [None] * (max_n - 1) + ["Remark"])
    for c in ws[ws.max_row]:
        c.font = bold
        c.fill = PatternFill("solid", fgColor="C5D0E6")
    rem_col = 6 + max_n
    for d in dims:
        b = d["balloon"]
        desc = ("Ø%g" % d["nominal"]) if d["dim_type"] == "diameter" else d["nominal"]
        row = [b, desc, d["tol_plus"], d["tol_minus"], d["instrument"]]
        vals = all_readings[b]
        row += vals + [None] * (max_n - len(vals))
        row.append(last_remark.get(b, ""))
        ws.append(row)
    for col, w in zip("ABCDE", (8, 14, 8, 8, 24)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A6"

    fl = wb.create_sheet("Face links")
    fl.append(["STEP sha256:", sha])
    fl.append(["Total faces:", total_faces])
    fl.append(["Balloon", "Faces A", "Faces B", "Dim type", "Notes"])
    for c in fl[3]:
        c.font = bold
    notes_rows = []
    for d in dims:
        b = d["balloon"]
        l = links.get(b)
        note = []
        if l is None:
            note.append("No CAD geometry matched; tag manually.")
        else:
            note.append(f"Auto-linked from CAD: CAD value {l['cad_value']} vs drawing {d['nominal']}.")
            if l["mismatch"]:
                note.append("DRAWING-VS-CAD MISMATCH beyond tolerance.")
        if str(b) in extra:
            note.append(extra[str(b)])
        fl.append([b, ",".join(map(str, l["faces_a"])) if l else "", ",".join(map(str, l["faces_b"])) if l else "",
                   l["dim_type"] if l else "", " ".join(note)])
        notes_rows.append((b, d["nominal"], l and l["cad_value"], l and l["mismatch"], " ".join(note)))
    fl.column_dimensions["E"].width = 90

    nt = wb.create_sheet("Notes")
    nt.append(["Provenance"])
    nt.append(["Dimensions, tolerances: drawing characteristics from " + Path(a.drawing_report).name])
    nt.append(["Readings (merged, all parts): " + "; ".join(sources)])
    nt.append(["Face links: CMM matching (capp_service/demo_modules/cmm.py) against " + step.name])
    nt.append(["Readings are only those recorded by the shop; no values were invented. Non-numeric entries (e.g. 'tapping') are ignored."])
    nt.append([])
    nt.append(["Balloon", "Drawing nominal", "CAD value", "Mismatch", "Note"])
    for r in notes_rows:
        nt.append(list(r))
    for c in nt[1]:
        c.font = bold
    wb.save(a.output)
    print(f"wrote {a.output}: {len(dims)} balloons, {sum(1 for d in dims if d['balloon'] in links)} linked, "
          f"{max_n} reading columns, total_faces={total_faces}")


if __name__ == "__main__":
    main()
