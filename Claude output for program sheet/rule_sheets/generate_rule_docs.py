"""
generate_rule_docs.py — Generate RULES.md from all rule sheet JSONs.

Usage:
    python "rule_sheets/generate_rule_docs.py"

Reads all 01–07 JSON files in the same directory and writes RULES.md
alongside them. Commit both the JSONs and RULES.md; the Markdown renders
on GitHub as a human-readable reference.
"""

import json
from pathlib import Path
from datetime import date

SHEET_DIR = Path(__file__).parent
OUTPUT = SHEET_DIR / "RULES.md"

# ── helpers ──────────────────────────────────────────────────────────────────

def load(filename: str) -> dict:
    with open(SHEET_DIR / filename, encoding="utf-8") as f:
        return json.load(f)

def status_badge(live: bool) -> str:
    return "🟢 Live" if live else "🔵 Documented"

def bool_icon(val) -> str:
    if val is True:
        return "✅"
    if val is False:
        return "❌"
    return "—"

def fmt_warnings(warnings) -> str:
    if not warnings:
        return ""
    if isinstance(warnings, str):
        warnings = [warnings]
    lines = "\n".join(f"> ⚠️ {w}" for w in warnings if w)
    return f"\n{lines}\n" if lines else ""

# ── section renderers ─────────────────────────────────────────────────────────

def render_sheet_header(d: dict, sheet_num: str, title: str) -> str:
    version      = d.get("schema_version", "—")
    ruleset_id   = d.get("ruleset_id", "—")
    updated_at   = d.get("updated_at", "—")
    description  = d.get("description", "")
    pipeline     = d.get("pipeline_stage", "—")
    return (
        f"## Sheet {sheet_num} — {title}\n\n"
        f"| Field | Value |\n"
        f"|-------|-------|\n"
        f"| Ruleset ID | `{ruleset_id}` |\n"
        f"| Schema version | {version} |\n"
        f"| Last updated | {updated_at} |\n"
        f"| Pipeline stage | `{pipeline}` |\n\n"
        f"{description}\n"
    )


def render_07(d: dict) -> str:
    lines = [render_sheet_header(d, "07", "Label / Taxonomy Map (MFCAD++ bridge)")]
    lines.append(
        "Bridges MFCAD++ class IDs (0–24) to ShiaanX internal `feature_type` strings. "
        "Required before ML can train or evaluate against the dataset.\n"
    )

    # readiness summary
    mappings = d.get("mappings", [])
    ready_proc  = sum(1 for m in mappings if m.get("process_selection_ready"))
    ready_class = sum(1 for m in mappings if m.get("classify_features_emits"))
    lines.append(
        f"**Coverage summary:** {ready_class}/25 classes emitted by classifier · "
        f"{ready_proc}/25 classes have a process rule\n"
    )

    lines.append(
        "| ID | MFCAD++ Name | Internal Feature Type | Classifier emits | Process rule | Notes |\n"
        "|----|-------------|----------------------|:----------------:|:------------:|-------|\n"
    )
    for m in mappings:
        warn = m.get("warnings") or ""
        lines.append(
            f"| {m['mfcad_id']} "
            f"| {m['mfcad_name']} "
            f"| `{m['internal_feature_type']}` "
            f"| {bool_icon(m.get('classify_features_emits'))} "
            f"| {bool_icon(m.get('process_selection_ready'))} "
            f"| {warn} |\n"
        )
    lines.append("\n")
    return "".join(lines)


def render_01(d: dict) -> str:
    lines = [render_sheet_header(d, "01", "Feature Classification Rules")]

    # Decision priority
    lines.append("### Decision Priority\n\n")
    for i, step in enumerate(d.get("decision_priority", []), 1):
        lines.append(f"{i}. {step}\n")
    lines.append("\n")

    # Thresholds
    lines.append("### Thresholds\n\n")
    lines.append("| Parameter | Value | Unit | Role |\n")
    lines.append("|-----------|-------|------|------|\n")
    for key, t in d.get("thresholds_mm", {}).items():
        lines.append(f"| `{key}` | **{t['value']}** | {t['unit']} | {t['role']} |\n")
    lines.append("\n")

    # Pocket rules
    pr = d.get("pocket_rules", {})
    if pr:
        lines.append("### Pocket Detection Rules\n\n")
        lines.append(f"- Minimum perpendicular walls for pocket: **{pr.get('min_perpendicular_wall_count')}**\n")
        lines.append(f"- High-confidence threshold: **{pr.get('confidence_high_min_perp_walls')}** walls\n")
        lines.append(f"- {pr.get('notes','')}\n\n")

    # Angled modifier
    am = d.get("angled_modifier", {})
    if am:
        lines.append("### Angled Modifier\n\n")
        lines.append(f"- Suffix applied: `{am.get('suffix')}`\n")
        lines.append(f"- Applies when: {am.get('applies_when')}\n")
        lines.append(f"- Excludes: {', '.join(f'`{x}`' for x in am.get('excludes', []))}\n\n")

    lines.append(fmt_warnings(d.get("warnings")))
    return "".join(lines)


def render_02(d: dict) -> str:
    lines = [render_sheet_header(d, "02", "Process Selection Rules")]

    # Drill diameter bands
    bands = d.get("drill_diameter_bands_mm", {})
    lines.append("### Drill Diameter Bands\n\n")
    lines.append("| Band | Diameter range | Operation sequence |\n")
    lines.append("|------|---------------|--------------------|\n")
    micro_max = bands.get("micro_drill_max_exclusive", 1.0)
    twist_max = bands.get("twist_drill_max_inclusive", 13.0)
    core_max  = bands.get("core_drill_max_inclusive", 32.0)
    pf        = bands.get("pilot_diameter_fraction_of_final", 0.6)
    lines.append(f"| Micro | d < {micro_max} mm | `micro_drill` only |\n")
    lines.append(f"| Twist | {micro_max} – {twist_max} mm | `spot_drill` → `twist_drill` |\n")
    lines.append(f"| Core  | {twist_max} – {core_max} mm | `spot_drill` → `pilot_drill` ({int(pf*100)}% D) → `core_drill` |\n")
    lines.append(f"| Large | > {core_max} mm | `circular_interp` or `boring_bar` |\n\n")

    # DDR cycles
    ddr = d.get("ddr_drill_cycle", {})
    lines.append("### Depth-to-Diameter Ratio (DDR) → Drill Cycle\n\n")
    lines.append(f"*DDR = depth / nominal hole diameter*\n\n")
    lines.append("| DDR range | Cycle |\n")
    lines.append("|-----------|-------|\n")
    lines.append(f"| ≤ {ddr.get('ddr_standard_max_inclusive')} | Standard (G81) |\n")
    lines.append(f"| ≤ {ddr.get('ddr_peck_max_inclusive')} | Peck (G83) |\n")
    lines.append(f"| > {ddr.get('ddr_peck_max_inclusive')} | Deep peck |\n\n")

    # Stock to leave
    stl = d.get("material_stock_to_leave_mm", {})
    lines.append("### Material Stock-to-Leave for Roughing Passes (mm)\n\n")
    lines.append("| Material | XY stock | Z stock |\n")
    lines.append("|----------|---------|--------|\n")
    for mat, vals in stl.get("per_material", {}).items():
        lines.append(f"| {mat} | {vals['xy']} | {vals['z']} |\n")
    lines.append("\n")

    # Face mill max ap
    fm = d.get("face_mill_max_ap_mm", {})
    lines.append("### Face Mill Max Axial Depth (ap) per Material\n\n")
    lines.append("| Material | Max ap (mm) |\n")
    lines.append("|----------|------------|\n")
    for mat, val in fm.get("per_material", {}).items():
        lines.append(f"| {mat} | {val} |\n")
    lines.append(f"\n*Rule: {fm.get('rule','')}*\n\n")

    # Tap drill table
    tdt = d.get("tap_drill_table_mm", {})
    lines.append("### ISO 68-1 Tap Drill Table\n\n")
    lines.append("| Thread (M) | Tap drill diameter (mm) |\n")
    lines.append("|-----------|------------------------|\n")
    for k, v in tdt.items():
        if k != "comment":
            lines.append(f"| M{k} | {v} |\n")
    lines.append("\n")

    lines.append(fmt_warnings(d.get("warnings")))
    return "".join(lines)


def render_03(d: dict) -> str:
    lines = [render_sheet_header(d, "03", "Tool Matching Policy")]

    # Tolerances
    tol = d.get("tolerances_mm", {})
    lines.append("### Match Tolerances\n\n")
    lines.append("| Setting | Value (mm) |\n")
    lines.append("|---------|----------|\n")
    for k, v in tol.items():
        lines.append(f"| `{k}` | {v} |\n")
    lines.append("\n")

    # Diameter resolution rules
    lines.append("### Tool Selection Rules by Operation\n\n")
    lines.append("| Operation | Selection rule |\n")
    lines.append("|-----------|---------------|\n")
    for op, policy in d.get("diameter_resolution", {}).items():
        if isinstance(policy, dict):
            rule = policy.get("rule", "")
            frac = policy.get("target_fraction_of_bore_diameter") or policy.get("target_fraction_of_boss_diameter") or policy.get("default_feature_diameter_mm_if_missing")
            extra = f" (fraction: {frac})" if frac else ""
            lines.append(f"| `{op}` | {rule}{extra} |\n")
        else:
            lines.append(f"| `{op}` | {policy} |\n")
    lines.append("\n")

    # No-tool steps
    no_tool = d.get("database_query_policy", {}).get("no_tool_steps", [])
    if no_tool:
        lines.append(f"**Steps that require no tool:** {', '.join(f'`{s}`' for s in no_tool)}\n\n")

    lines.append(fmt_warnings(d.get("warnings")))
    return "".join(lines)


def render_04(d: dict) -> str:
    lines = [render_sheet_header(d, "04", "Cutting Parameter Rules")]

    # Machine defaults
    md = d.get("machine_defaults", {})
    lines.append("### Machine Defaults\n\n")
    lines.append("| Setting | Value |\n")
    lines.append("|---------|-------|\n")
    lines.append(f"| Max spindle RPM | **{md.get('max_spindle_rpm')}** |\n")
    lines.append(f"| Default coolant | `{md.get('coolant_default')}` |\n")
    lines.append(f"| Allowed coolant modes | {', '.join(f'`{c}`' for c in md.get('coolant_allowed', []))} |\n\n")

    # Peck fractions
    lines.append("### Peck Depth Fractions (Q = D × fraction)\n\n")
    lines.append("| Coolant mode | Peck | Deep peck |\n")
    lines.append("|-------------|------|----------|\n")
    for coolant, fracs in d.get("peck_fractions_of_tool_diameter", {}).items():
        if coolant != "comment":
            lines.append(f"| `{coolant}` | {fracs.get('peck')} × D | {fracs.get('deep_peck')} × D |\n")
    lines.append("\n")

    # TSC boost
    tsc = d.get("tsc_small_drill_boost", {})
    lines.append("### Through-Spindle Coolant (TSC) Speed Boost\n\n")
    lines.append(
        f"For drills < **{tsc.get('max_tool_diameter_mm_exclusive')} mm** with `{tsc.get('applies_when_coolant')}` coolant: "
        f"multiply Vc by **{tsc.get('vc_multiplier')}×**\n\n"
    )

    # Formulas
    lines.append("### Formulas\n\n")
    for name, formula in d.get("formulas", {}).items():
        lines.append(f"- **{name}:** `{formula}`\n")
    lines.append("\n")

    # Vc/fz source
    lines.append("### Vc / fz Source by Pass Type\n\n")
    lines.append("| Pass type | Source |\n")
    lines.append("|-----------|--------|\n")
    for pass_type, source in d.get("vc_fz_source_by_pass_type", {}).items():
        lines.append(f"| `{pass_type}` | {source} |\n")
    lines.append("\n")

    # ae rules
    ae = d.get("radial_depth_ae", {})
    lines.append("### Radial Depth (ae) Rules\n\n")
    lines.append("| Operation | RF | FINISH | CORNER_R |\n")
    lines.append("|-----------|----|---------|---------|\n")

    def fmt_ae(v):
        if v is None: return "—"
        if isinstance(v, (int, float)): return f"{int(v*100)}% of D"
        return str(v)

    for op in ["contour_mill_by_pass", "pocket_mill_by_pass"]:
        vals = ae.get(op, {})
        label = op.replace("_by_pass", "")
        lines.append(f"| `{label}` | {fmt_ae(vals.get('RF'))} | {fmt_ae(vals.get('FINISH'))} | {fmt_ae(vals.get('CORNER_R'))} |\n")
    lines.append(f"| `face_mill` | {ae.get('face_mill','')} | — | — |\n")
    lines.append("\n")

    lines.append(fmt_warnings(d.get("warnings")))
    return "".join(lines)


def render_05(d: dict) -> str:
    lines = [render_sheet_header(d, "05", "Setup Planning Rules")]

    # VMC convention
    vmc = d.get("vmc_convention", {})
    lines.append("### VMC Convention\n\n")
    lines.append(f"- Default spindle direction (CAD): `{vmc.get('default_spindle_direction_cad')}`\n")
    lines.append(f"- {vmc.get('comment','')}\n\n")

    # Grouping rules
    lines.append("### Grouping Algorithm\n\n")
    for step in d.get("grouping_algorithm", []):
        lines.append(f"- {step}\n")
    lines.append("\n")

    # Axis sort
    sort = d.get("axis_group_sort", {})
    lines.append("### Setup Sort Order\n\n")
    lines.append(f"1. {sort.get('primary','')}\n")
    lines.append(f"2. {sort.get('secondary','')}\n\n")

    # WCS
    wcs = d.get("wcs", {})
    lines.append("### WCS Assignment\n\n")
    lines.append(f"Sequence: {' → '.join(wcs.get('sequence', []))}\n\n")
    lines.append(f"{wcs.get('assignment','')}\n\n")

    # Corner zero heuristic
    czh = d.get("wcs_origin_corner_heuristic", {})
    lines.append("### Corner-Zero Heuristic (AD-006)\n\n")
    lines.append(f"- Tolerance: **{czh.get('fraction_of_dimension')*100:.0f}%** of part dimension\n")
    lines.append(f"- Rule: {czh.get('rule','')}\n\n")

    # Stock state
    ss = d.get("stock_state", {})
    lines.append("### Stock State Carryover\n\n")
    lines.append(f"- Setup 1: `{ss.get('setup_1_type')}`\n")
    lines.append(f"- Later setups: `{ss.get('later_setups')}`\n")
    lines.append(f"- Machined faces: {ss.get('machined_face_accumulation','')}\n\n")

    lines.append(fmt_warnings(d.get("warnings")))
    return "".join(lines)


def render_06(d: dict) -> str:
    lines = [render_sheet_header(d, "06", "Workholding / Fixture Rules")]

    # Datum cascade
    dc = d.get("datum_cascade", {})
    lines.append(f"**Datum rule:** {dc.get('datum_from_setup','')}\n\n")

    # Angled setup
    ang = d.get("angled_setup", {})
    if ang:
        t = ang.get("template", {})
        lines.append("### Angled Setup Template\n\n")
        lines.append("| Field | Value |\n")
        lines.append("|-------|-------|\n")
        lines.append(f"| Type | `{t.get('type')}` |\n")
        lines.append(f"| Clamp faces | {t.get('clamp_faces')} |\n")
        lines.append(f"| Rest face | {t.get('rest_face')} |\n")
        lines.append(f"| Clearance faces | {t.get('clearance_faces')} |\n")
        lines.append(f"| Jaw opening | {t.get('jaw_opening_mm_from_bbox')} |\n\n")

    # Principal spindle templates
    lines.append("### Principal Spindle Templates\n\n")
    lines.append("| Spindle approach | Fixture type | Clamp faces | Rest face | Jaw opening |\n")
    lines.append("|-----------------|-------------|------------|----------|-------------|\n")
    for t in d.get("principal_spindle_templates", []):
        ftype = t.get("type") or f"{t.get('type_setup_1')} (setup 1) / {t.get('type_later')} (later)"
        lines.append(
            f"| {t.get('label_hint','')} "
            f"| `{ftype}` "
            f"| {t.get('clamp_faces')} "
            f"| {t.get('rest_face')} "
            f"| {t.get('jaw_opening_mm_from_bbox')} |\n"
        )
    lines.append("\n")

    # Fallback
    fb = d.get("fallback", {})
    lines.append(f"**Fallback:** `{fb.get('type')}` — {fb.get('notes','')}\n\n")

    lines.append(fmt_warnings(d.get("warnings")))
    return "".join(lines)


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    sheets = {
        "07_label_taxonomy.json":       render_07,
        "01_feature_classification.json": render_01,
        "02_process_selection.json":    render_02,
        "03_tool_matching_policy.json": render_03,
        "04_cutting_parameters.json":   render_04,
        "05_setup_planning.json":       render_05,
        "06_workholding.json":          render_06,
    }

    sections = []
    for filename, renderer in sheets.items():
        data = load(filename)
        sections.append(renderer(data))

    today = date.today().isoformat()
    header = (
        f"# ShiaanX CAPP — Rule Sheets Reference\n\n"
        f"*Auto-generated on {today} from JSON rule sheets in this directory.*  \n"
        f"*Do not edit this file directly — edit the JSON and re-run `generate_rule_docs.py`.*\n\n"
        f"---\n\n"
        f"## Contents\n\n"
        f"| # | Sheet | Pipeline stage |\n"
        f"|---|-------|----------------|\n"
        f"| 07 | [Label / Taxonomy Map](#sheet-07--label--taxonomy-map-mfcad-bridge) | Training & evaluation bridge |\n"
        f"| 01 | [Feature Classification](#sheet-01--feature-classification-rules) | `3. classify_features.py` |\n"
        f"| 02 | [Process Selection](#sheet-02--process-selection-rules) | `4. process_selection.py` |\n"
        f"| 03 | [Tool Matching Policy](#sheet-03--tool-matching-policy) | `7. tool_selection.py` |\n"
        f"| 04 | [Cutting Parameters](#sheet-04--cutting-parameter-rules) | `8. parameter_calculation.py` |\n"
        f"| 05 | [Setup Planning](#sheet-05--setup-planning-rules) | `5. setup_planning.py` |\n"
        f"| 06 | [Workholding / Fixtures](#sheet-06--workholding--fixture-rules) | `5. setup_planning.py` |\n\n"
        f"---\n\n"
    )

    output = header + "\n---\n\n".join(sections)
    OUTPUT.write_text(output, encoding="utf-8")
    print(f"Written: {OUTPUT}")
    print(f"  {len(sections)} sheets, {len(output):,} characters")


if __name__ == "__main__":
    main()
