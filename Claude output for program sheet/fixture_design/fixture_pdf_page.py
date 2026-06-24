"""
fixture_pdf_page.py — Platypus flowables for fixture specification pages.

Returns a list of reportlab Platypus flowables that can be appended to
the existing program sheet story before doc.build().

Called from 9. program_sheet.py.
"""
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import (
    Table, TableStyle, Paragraph, Spacer, PageBreak,
    HRFlowable, KeepTogether,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER


HEADER_COLOR = colors.HexColor("#1a3a5c")
ALT_ROW_COLOR = colors.HexColor("#f5f8fa")
WARN_BG = colors.HexColor("#fff3cd")
WARN_FG = colors.HexColor("#664d03")
SOFT_JAW_RED = colors.HexColor("#c0392b")


def _styles():
    ss = getSampleStyleSheet()
    return {
        "heading": ParagraphStyle(
            "FixtureHeading",
            parent=ss["Normal"],
            fontName="Helvetica-Bold",
            fontSize=12,
            textColor=colors.white,
            backColor=HEADER_COLOR,
            spaceBefore=0,
            spaceAfter=0,
            leading=16,
            leftIndent=4 * mm,
        ),
        "body": ParagraphStyle(
            "FixtureBody",
            parent=ss["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=12,
        ),
        "bold": ParagraphStyle(
            "FixtureBold",
            parent=ss["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=12,
        ),
        "warn": ParagraphStyle(
            "FixtureWarn",
            parent=ss["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10,
            textColor=WARN_FG,
            backColor=WARN_BG,
            borderColor=WARN_FG,
            borderWidth=1,
            borderPadding=6,
            leading=14,
        ),
    }


def _fixture_type_label(fixture_type: str) -> str:
    labels = {
        "vise": "Vise (Standard Hard Jaws)",
        "step_jaw_vise": "Step Jaw Vise",
        "angle_plate": "Angle Plate",
        "sine_plate": "Sine Plate",
        "fixture_plate": "Fixture Plate",
        "custom_soft_jaw": "Custom Soft Jaw Vise",
    }
    return labels.get(fixture_type, fixture_type.replace("_", " ").title())


def _jaw_type_label(jaw_type: str) -> str:
    labels = {
        "standard_hard": "Standard Hard Jaws",
        "soft_aluminum": "Soft Aluminium Jaws",
        "step_jaw": "Step Jaws",
        "custom_profile": "Custom Profile Soft Jaws",
    }
    return labels.get(jaw_type, jaw_type.replace("_", " ").title())


def build_fixture_page_flowables(fixture_spec: dict, setup: dict) -> list:
    """
    Build a list of platypus flowables for one fixture specification page.
    The caller should prepend a PageBreak before these flowables.
    """
    S = _styles()
    story = []

    setup_id = setup.get("setup_id", "?")
    axis_label = setup.get("axis_label", "")
    wcs = setup.get("wcs", "G54")

    # Section header
    header_text = (
        f"SETUP {setup_id}  —  FIXTURE SPECIFICATION    "
        f"<font size='8' color='#ccddee'>WCS: {wcs}  |  {axis_label}</font>"
    )
    story.append(Paragraph(header_text, S["heading"]))
    story.append(Spacer(1, 3 * mm))

    # Spec table
    f = fixture_spec
    parallels_str = (
        f"{int(f.get('parallels_mm', 0))} mm"
        if f.get("parallels_mm")
        else "None (part sits on jaw serrations)"
    )
    clamped_str = ", ".join(f.get("clamped_faces", []))

    rows = [
        ["Field", "Value"],
        ["Fixture Type", _fixture_type_label(f.get("fixture_type", ""))],
        ["Jaw Type", _jaw_type_label(f.get("jaw_type", ""))],
        ["Jaw Opening", f"{f.get('jaw_opening_mm', 0):.0f} mm"],
        ["Jaw Height", f"{f.get('jaw_height_mm', 38):.0f} mm"],
        ["Parallels", parallels_str],
        ["Clamped Faces", clamped_str],
        ["Rest Face", f.get("rest_face", "")],
        ["Datum Face", f.get("datum_face", "")],
        ["Z Zero Reference", f.get("z_zero_face", "").replace("_", " ").title()],
        ["WCS XY Zero", f.get("wcs_xy_zero", "").replace("_", " ").title()],
        ["Clamp Clearance", f"{f.get('clamp_clearance_mm', 0):.1f} mm"],
        ["Soft Jaws Required", "YES" if f.get("soft_jaw_required") else "No"],
    ]

    col_widths = [55 * mm, 115 * mm]
    table = Table(rows, colWidths=col_widths, repeatRows=1)

    ts = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_COLOR),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ALT_ROW_COLOR]),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ])

    if f.get("soft_jaw_required"):
        for row_idx, row in enumerate(rows):
            if row[0] == "Soft Jaws Required":
                ts.add("TEXTCOLOR", (1, row_idx), (1, row_idx), SOFT_JAW_RED)
                ts.add("FONTNAME", (1, row_idx), (1, row_idx), "Helvetica-Bold")
                break

    table.setStyle(ts)
    story.append(table)
    story.append(Spacer(1, 4 * mm))

    # Setup notes
    notes = f.get("setup_notes", [])
    if notes:
        story.append(Paragraph("<b>SETUP NOTES</b>", S["bold"]))
        story.append(Spacer(1, 1 * mm))
        note_rows = [["  •  " + note] for note in notes]
        note_table = Table(note_rows, colWidths=[170 * mm])
        note_table.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, ALT_ROW_COLOR]),
        ]))
        story.append(note_table)
        story.append(Spacer(1, 3 * mm))

    # Soft jaw warning
    if f.get("soft_jaw_required"):
        jaw_file = f.get("soft_jaw_profile_file", "")
        right_file = jaw_file.replace("_LEFT", "_RIGHT") if jaw_file else ""
        warn_text = (
            "<b>⚠  SOFT JAWS REQUIRED</b><br/>"
            f"<font size='8'>See: {jaw_file}  /  {right_file}</font>"
        )
        story.append(Paragraph(warn_text, S["warn"]))
        story.append(Spacer(1, 2 * mm))

    return story


def add_fixture_pages_to_story(story: list, fixture_spec_data: dict) -> None:
    """
    Append fixture pages (PageBreak + flowables) to an existing story list.
    Modifies story in-place. Call before doc.build().
    """
    setups = fixture_spec_data.get("setups", [])
    for setup in setups:
        fs = setup.get("fixture_spec")
        if not fs:
            continue
        story.append(PageBreak())
        story.extend(build_fixture_page_flowables(fs, setup))
