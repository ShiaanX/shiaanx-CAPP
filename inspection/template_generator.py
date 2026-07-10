"""
Inspection Template Generator — Component 3
Takes features_datumed.json + tolerances.json (+ optional program sheet metadata)
and produces an Excel inspection template ready for the inspector to fill in.

Pre-populated columns:
  Feature ID | Feature Type | Nominal (mm) | Upper Tol | Lower Tol |
  Datum Ref  | Measurement Type | Actual (blank) | Deviation (formula) |
  Pass/Fail (formula) | Notes (blank)

Usage:
    python inspection/template_generator.py \\
        <features_datumed.json> \\
        <tolerances.json> \\
        [--metadata <program_sheet_params.json>] \\
        [--output <output.xlsx>]
"""

import sys
import json
import argparse
import math
from pathlib import Path
from datetime import datetime

import openpyxl
from openpyxl.styles import (
    Font, PatternFill, Alignment, Border, Side, numbers
)
from openpyxl.utils import get_column_letter
from openpyxl.formatting.rule import FormulaRule


# ─── Colour palette (matches ShiaanX dark industrial theme in light Excel) ────
C_NAVY       = "1A1A2E"
C_ACCENT     = "0F3460"
C_LIGHT_BLUE = "E8F0FE"
C_WARN_BG    = "FFF3CD"
C_PASS_BG    = "D4EDDA"
C_FAIL_BG    = "F8D7DA"
C_HEADER_FG  = "FFFFFF"
C_BORDER     = "9EA8C0"
C_SECTION_BG = "C5D0E6"
C_ALT_ROW    = "F4F7FC"
C_DATUM_A    = "FFE0E0"
C_DATUM_B    = "E0FFF6"
C_DATUM_C    = "FFFDE0"
C_GENERAL    = "F8F9FA"

DEFAULT_TOLERANCE_MM = 0.1
DEFAULT_FALLBACK_TOL = {"upper_tol_mm": DEFAULT_TOLERANCE_MM, "lower_tol_mm": DEFAULT_TOLERANCE_MM}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def thin_border():
    s = Side(style="thin", color=C_BORDER)
    return Border(left=s, right=s, top=s, bottom=s)

def header_fill(hex_color):
    return PatternFill("solid", fgColor=hex_color)

def section_fill(section_label):
    mapping = {
        "DATUM_A": C_DATUM_A,
        "DATUM_B": C_DATUM_B,
        "DATUM_C": C_DATUM_C,
        "GENERAL": C_GENERAL,
    }
    color = mapping.get(section_label, C_GENERAL)
    return PatternFill("solid", fgColor=color)

def set_cell(ws, row, col, value, font=None, fill=None, align=None, border=None, number_format=None):
    cell = ws.cell(row=row, column=col, value=value)
    if font:    cell.font = font
    if fill:    cell.fill = fill
    if align:   cell.alignment = align
    if border:  cell.border = border
    if number_format: cell.number_format = number_format
    return cell


# ─── Extract nominal from feature geometry ────────────────────────────────────

def extract_nominal(cluster_or_feature, tol_entry):
    """
    Pull the most relevant nominal dimension from the feature geometry.
    Returns (nominal_mm, measurement_type).
    """
    if tol_entry:
        return tol_entry.get("nominal_mm"), tol_entry.get("measurement_type", "dimension")

    # Try to infer from geometry
    faces = cluster_or_feature.get("faces", [])
    for face in faces:
        if "cylinder" in face:
            r = face["cylinder"].get("radius")
            if r:
                return round(r * 2, 4), "diameter"
        if "cylinder_datum" in face:
            r = face["cylinder_datum"].get("radius")
            if r:
                return round(r * 2, 4), "diameter"

    # Bounding-box-based fallback for pocket/boss width
    bbox = cluster_or_feature.get("bounding_box")
    if bbox:
        dims = sorted([
            abs(bbox.get("length_x") or 0),
            abs(bbox.get("length_y") or 0),
            abs(bbox.get("length_z") or 0),
        ])
        return round(dims[1], 4), "width"

    return None, "dimension"


def get_datum_ref(cluster, datums_list):
    """Return which datum section this cluster is in, or '—'."""
    section = cluster.get("inspection_section", "GENERAL")
    if section.startswith("DATUM_"):
        return section.replace("DATUM_", "Datum ")
    # Check if any face matches a datum
    face_indices = {f.get("face_index") for f in cluster.get("faces", []) if "face_index" in f}
    for d in datums_list:
        if d["face_index"] in face_indices:
            return f"Datum {d['label']}"
    return "—"


# ─── Feature ID generation ────────────────────────────────────────────────────

def make_feature_id(cluster, index):
    """
    Generate a human-readable feature ID like BORE_001, POCKET_002, etc.
    Uses cluster_id if available, otherwise derives from feature_type.
    """
    if cluster.get("cluster_id"):
        return cluster["cluster_id"]

    feature_type = cluster.get("feature_type") or cluster.get("type") or "FEATURE"
    type_prefix = {
        "through_hole": "BORE",
        "blind_hole": "BORE",
        "tapped_hole": "TAP",
        "counterbore": "CBORE",
        "countersink": "CSINK",
        "pocket": "POCKET",
        "rectangular_pocket": "POCKET",
        "circular_pocket": "POCKET",
        "boss": "BOSS",
        "slot": "SLOT",
        "chamfer": "CHAM",
        "fillet": "FILLET",
        "planar_face": "FACE",
        "large_bore": "BORE",
    }.get(feature_type.lower(), feature_type[:4].upper())

    return f"{type_prefix}_{index:03d}"


# ─── Main ─────────────────────────────────────────────────────────────────────

def generate_template(features_datumed_path, tolerances_path, metadata_path=None, output_path=None):
    print(f"[*] Reading features: {features_datumed_path}")
    with open(features_datumed_path) as f:
        features = json.load(f)

    print(f"[*] Reading tolerances: {tolerances_path}")
    if Path(tolerances_path).exists():
        with open(tolerances_path) as f:
            tolerances = json.load(f)
    else:
        print(f"[WARN] tolerances.json not found — using default ±{DEFAULT_TOLERANCE_MM} mm for all features")
        tolerances = {}

    metadata = {}
    if metadata_path and Path(metadata_path).exists():
        with open(metadata_path) as f:
            metadata = json.load(f)

    datums = features.get("datum_frame", {})
    datums_list = []
    for label in ["A", "B", "C"]:
        key = f"datum_{label.lower()}_face_index"
        if datums.get(key) is not None:
            datums_list.append({"label": label, "face_index": datums[key]})

    part_name  = metadata.get("part_name")  or Path(features_datumed_path).stem.replace("_features_datumed", "").replace("_", " ")
    job_id     = metadata.get("job_id")     or "—"
    material   = metadata.get("material")   or "—"
    programmer = metadata.get("programmer") or "—"
    date_str   = datetime.utcnow().strftime("%Y-%m-%d")

    # Collect clusters (or top-level faces if no clusters key)
    clusters = features.get("clusters")
    if not clusters:
        # Raw features.json — wrap each face as a pseudo-cluster
        clusters = []
        faces_container = features.get("faces", [])
        face_list = faces_container.get("faces", []) if isinstance(faces_container, dict) else faces_container
        for i, face in enumerate(face_list):
            clusters.append({
                "faces": [face],
                "feature_type": face.get("surface_type", "face").lower(),
                "inspection_section": "GENERAL",
            })

    # Determine output path
    if not output_path:
        stem = Path(features_datumed_path).stem.replace("_datumed", "")
        output_path = Path(features_datumed_path).parent / f"{stem}_inspection_template.xlsx"

    # ─── Build workbook ────────────────────────────────────────────────────────
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Inspection"

    bold_white = Font(name="Calibri", bold=True, color=C_HEADER_FG, size=11)
    bold_dark  = Font(name="Calibri", bold=True, color=C_NAVY, size=11)
    normal     = Font(name="Calibri", size=10)
    bold_small = Font(name="Calibri", bold=True, size=10)
    center     = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left       = Alignment(horizontal="left", vertical="center")
    right_al   = Alignment(horizontal="right", vertical="center")
    bdr        = thin_border()

    # ─── Title block (rows 1–5) ────────────────────────────────────────────────
    ws.merge_cells("A1:K1")
    t = ws["A1"]
    t.value = "SHIAANX — INSPECTION RECORD"
    t.font = Font(name="Calibri", bold=True, size=16, color=C_HEADER_FG)
    t.fill = header_fill(C_NAVY)
    t.alignment = center

    fields = [
        ("Part Name",  part_name,   "A2", "C2"),
        ("Job ID",     job_id,      "D2", "E2"),
        ("Material",   material,    "F2", "G2"),
        ("Revision",   metadata.get("revision", "—"), "H2", "I2"),
        ("Programmer", programmer,  "J2", "K2"),
        ("Date",       date_str,    "A3", "B3"),
        ("Inspector",  "",          "C3", "D3"),
        ("Machine",    metadata.get("machine", "—"), "E3", "F3"),
        ("Part No.",   metadata.get("part_number", "—"), "G3", "H3"),
        ("Sheet",      "1 of 1",    "I3", "J3"),
    ]

    for label, value, start, end in fields:
        ws.merge_cells(f"{start}:{end}")
        lc = ws[start]
        lc.value = f"{label}: {value}"
        lc.font  = normal
        lc.fill  = header_fill(C_LIGHT_BLUE)
        lc.alignment = left
        lc.border = bdr

    # Default tolerance note
    ws.merge_cells("A4:K4")
    note = ws["A4"]
    note.value = f"General tolerance (unless specified): ±{DEFAULT_TOLERANCE_MM} mm"
    note.font = Font(name="Calibri", italic=True, size=9, color="555555")
    note.alignment = left

    # Blank row
    ws.row_dimensions[5].height = 6

    # ─── Column headers (row 6) ────────────────────────────────────────────────
    COLS = [
        ("Feature ID",        14),
        ("Feature Type",      18),
        ("Nominal (mm)",      13),
        ("Upper Tol (mm)",    13),
        ("Lower Tol (mm)",    13),
        ("Datum Ref",         11),
        ("Meas. Type",        13),
        ("Actual (mm)",       13),
        ("Deviation (mm)",    14),
        ("Pass / Fail",       12),
        ("Notes",             24),
    ]

    HEADER_ROW = 6
    for col_idx, (header, width) in enumerate(COLS, start=1):
        cell = ws.cell(row=HEADER_ROW, column=col_idx, value=header)
        cell.font  = bold_white
        cell.fill  = header_fill(C_ACCENT)
        cell.alignment = center
        cell.border = bdr
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    ws.row_dimensions[HEADER_ROW].height = 30
    ws.freeze_panes = "A7"

    # Column letter aliases for readability
    COL_NOMINAL   = get_column_letter(3)   # C
    COL_UPPER_TOL = get_column_letter(4)   # D
    COL_LOWER_TOL = get_column_letter(5)   # E
    COL_ACTUAL    = get_column_letter(8)   # H
    COL_DEV       = get_column_letter(9)   # I
    COL_PASS      = get_column_letter(10)  # J

    # ─── Data rows ────────────────────────────────────────────────────────────
    data_row = HEADER_ROW + 1
    feature_counter = {}
    section_starts = {}   # label -> first data_row of section
    current_section = None

    for cluster in clusters:
        section = cluster.get("inspection_section", "GENERAL")

        # Section separator row
        if section != current_section:
            current_section = section
            section_starts[section] = data_row
            ws.merge_cells(f"A{data_row}:K{data_row}")
            sec_cell = ws[f"A{data_row}"]

            orient_hint = ""
            if section == "DATUM_A":
                orient_hint = " — Orient part with Datum A face perpendicular to measurement axis"
            elif section == "DATUM_B":
                orient_hint = " — Orient part with Datum B face as reference"
            elif section == "DATUM_C":
                orient_hint = " — Orient part with Datum C face as reference"

            sec_cell.value = f"▶  {section.replace('_', ' ')}{orient_hint}"
            sec_cell.font  = Font(name="Calibri", bold=True, size=10, color=C_NAVY)
            sec_cell.fill  = header_fill(C_SECTION_BG)
            sec_cell.alignment = left
            sec_cell.border = bdr
            ws.row_dimensions[data_row].height = 20
            data_row += 1

        # Feature ID
        feature_type = cluster.get("feature_type") or "feature"
        feature_counter[feature_type] = feature_counter.get(feature_type, 0) + 1
        feature_id = make_feature_id(cluster, feature_counter[feature_type])

        tol_entry = tolerances.get(feature_id)
        nominal, meas_type = extract_nominal(cluster, tol_entry)

        upper_tol = (tol_entry or DEFAULT_FALLBACK_TOL)["upper_tol_mm"]
        lower_tol = (tol_entry or DEFAULT_FALLBACK_TOL)["lower_tol_mm"]
        datum_ref = get_datum_ref(cluster, datums_list)

        # Row fill
        row_fill = section_fill(section)
        alt = (data_row % 2 == 0)
        if alt:
            row_fill = PatternFill("solid", fgColor=C_ALT_ROW if section == "GENERAL" else row_fill.fgColor)

        row_data = [
            feature_id,
            feature_type.replace("_", " ").title(),
            nominal,
            upper_tol,
            lower_tol,
            datum_ref,
            meas_type,
            None,  # Actual — blank for inspector
        ]

        for col_idx, value in enumerate(row_data, start=1):
            cell = ws.cell(row=data_row, column=col_idx, value=value)
            cell.font   = normal
            cell.fill   = row_fill
            cell.border = bdr
            cell.alignment = center if col_idx not in (1, 2) else left
            if col_idx in (3, 4, 5, 8) and value is not None:
                cell.number_format = "0.000"

        # Deviation formula: =H{r}-C{r}   (Actual - Nominal)
        dev_cell = ws.cell(row=data_row, column=9)
        if nominal is not None:
            dev_cell.value = f"={COL_ACTUAL}{data_row}-{COL_NOMINAL}{data_row}"
        else:
            dev_cell.value = None
        dev_cell.font = normal
        dev_cell.fill = row_fill
        dev_cell.border = bdr
        dev_cell.alignment = center
        dev_cell.number_format = "0.000"

        # Pass/Fail formula: =IF(H{r}="","",IF(AND(I{r}>=-E{r},I{r}<=D{r}),"PASS","FAIL"))
        pf_cell = ws.cell(row=data_row, column=10)
        if nominal is not None:
            pf_cell.value = (
                f'=IF({COL_ACTUAL}{data_row}="","",IF(AND('
                f'{COL_DEV}{data_row}>=-{COL_LOWER_TOL}{data_row},'
                f'{COL_DEV}{data_row}<={COL_UPPER_TOL}{data_row}'
                f'),"PASS","FAIL"))'
            )
        else:
            pf_cell.value = None
        pf_cell.font = normal
        pf_cell.fill = row_fill
        pf_cell.border = bdr
        pf_cell.alignment = center

        # Notes — blank
        notes_cell = ws.cell(row=data_row, column=11, value="")
        notes_cell.font = normal
        notes_cell.fill = row_fill
        notes_cell.border = bdr

        ws.row_dimensions[data_row].height = 18
        data_row += 1

    # ─── Conditional formatting for PASS/FAIL column ─────────────────────────
    if data_row > HEADER_ROW + 1:
        pf_range = f"{COL_PASS}{HEADER_ROW+1}:{COL_PASS}{data_row-1}"
        ws.conditional_formatting.add(pf_range, FormulaRule(
            formula=[f'{COL_PASS}{HEADER_ROW+1}="PASS"'],
            fill=PatternFill("solid", fgColor=C_PASS_BG),
            font=Font(bold=True, color="155724"),
        ))
        ws.conditional_formatting.add(pf_range, FormulaRule(
            formula=[f'{COL_PASS}{HEADER_ROW+1}="FAIL"'],
            fill=PatternFill("solid", fgColor=C_FAIL_BG),
            font=Font(bold=True, color="721C24"),
        ))
        # Yellow for deviation warning (>50% of tolerance)
        dev_range = f"{COL_DEV}{HEADER_ROW+1}:{COL_DEV}{data_row-1}"
        ws.conditional_formatting.add(dev_range, FormulaRule(
            formula=[f'AND({COL_PASS}{HEADER_ROW+1}<>"",ABS({COL_DEV}{HEADER_ROW+1})>0.5*{COL_UPPER_TOL}{HEADER_ROW+1})'],
            fill=PatternFill("solid", fgColor=C_WARN_BG),
        ))

    # ─── Summary block ────────────────────────────────────────────────────────
    summary_row = data_row + 2
    ws.merge_cells(f"A{summary_row}:C{summary_row}")
    ws[f"A{summary_row}"].value = "SUMMARY"
    ws[f"A{summary_row}"].font = bold_white
    ws[f"A{summary_row}"].fill = header_fill(C_NAVY)
    ws[f"A{summary_row}"].alignment = center
    ws[f"A{summary_row}"].border = bdr

    first_data = HEADER_ROW + 1
    last_data  = data_row - 1
    pf_col     = COL_PASS

    summary_items = [
        ("Total Features",  f"=COUNTA({COL_NOMINAL}{first_data}:{COL_NOMINAL}{last_data})"),
        ("Measured",        f"=COUNTA({COL_ACTUAL}{first_data}:{COL_ACTUAL}{last_data})"),
        ("PASS",            f"=COUNTIF({pf_col}{first_data}:{pf_col}{last_data},\"PASS\")"),
        ("FAIL",            f"=COUNTIF({pf_col}{first_data}:{pf_col}{last_data},\"FAIL\")"),
        ("Pass Rate",       f'=IFERROR(COUNTIF({pf_col}{first_data}:{pf_col}{last_data},"PASS")/COUNTA({pf_col}{first_data}:{pf_col}{last_data}),"-")'),
    ]

    for i, (label, formula) in enumerate(summary_items):
        r = summary_row + 1 + i
        lc = ws.cell(row=r, column=1, value=label)
        lc.font   = bold_small
        lc.fill   = header_fill(C_LIGHT_BLUE)
        lc.border = bdr
        lc.alignment = left

        vc = ws.cell(row=r, column=2, value=formula)
        vc.font   = normal
        vc.border = bdr
        vc.alignment = center
        if label == "Pass Rate":
            vc.number_format = "0.0%"

        ws.merge_cells(f"B{r}:C{r}")
        ws.row_dimensions[r].height = 18

    # ─── Print setup ─────────────────────────────────────────────────────────
    ws.print_title_rows = f"1:{HEADER_ROW}"
    ws.page_setup.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.page_setup.orientation = "landscape"

    wb.save(output_path)
    print(f"[OK] Inspection template written: {output_path}")
    return str(output_path)


def main():
    parser = argparse.ArgumentParser(description="Generate inspection template Excel")
    parser.add_argument("features_datumed", help="Path to features_datumed.json")
    parser.add_argument("tolerances", help="Path to tolerances.json")
    parser.add_argument("--metadata", help="Path to program sheet params JSON (for job header)")
    parser.add_argument("--output", help="Output Excel path (default: auto-named alongside input)")
    args = parser.parse_args()

    generate_template(args.features_datumed, args.tolerances, args.metadata, args.output)


if __name__ == "__main__":
    main()
