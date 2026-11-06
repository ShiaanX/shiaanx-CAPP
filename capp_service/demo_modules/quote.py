"""
quote.py — instant quote from the v3 machining plan + shop rates + stock.

  machining  = (v3 cutting minutes + v3 tool changes × rates.tool_change_s) per part × machine_inr_per_hr.
               v3's own total prices every tool change at 15 min (manual change); the shop has an
               ATC, so its real tool_change_s is used instead. v3's total stays in the response
               as machining.v3_total_minutes for reference.
  setup      = setups × setup_minutes_per_setup, one-time per batch, amortised over qty
  material   = blank (v3 billet + stock allowance) mass × price/kg of the chosen stock
  margin     = margin_pct × subtotal
Lead time  = material (0 if in stock, else supplier lead days)
           + machining days (setup + qty × cycle, over shift hours × utilisation)
           + QC days + dispatch days (queue wait is added by the app).

Rates: demo_data/rates.json. Stock: the two spreadsheets in demo_data/stock/ (in-house inventory first, then
the supplier directory; see stock_lists.py and that folder's README). All cost fields are INR,
per unit unless named *_batch_* / total_inr.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from . import part_data, stock_lists

DATA_DIR = Path(__file__).resolve().parent.parent / 'demo_data'


def _load(name):
    return json.loads((DATA_DIR / name).read_text(encoding='utf-8'))


def _grade_key(material: str) -> str:
    m = (material or 'aluminium_6061').lower().replace(' ', '_').replace('-', '_')
    if m in ('aluminium', 'aluminum', 'al'):
        return 'aluminium_6061'
    m = m.replace('aluminum', 'aluminium')
    if m.startswith('al_'):
        m = 'aluminium_' + m[3:]
    return m


def _blank_volume(item, req):
    """Volume actually consumed: a cylinder slice for round bar stock, else the required block."""
    r = sorted(req)
    if item and item.get('shape') == 'Round Bar' and item.get('w'):
        return math.pi * (item['w'] / 2) ** 2 * r[0 if math.hypot(r[1], r[2]) <= item['w'] else 2]
    return r[0] * r[1] * r[2]


def _sum(rows, key):
    vals = [r.get(key) for r in (rows or []) if isinstance(r.get(key), (int, float))]
    return round(sum(vals), 2) if vals else None


def _compute(v3, qty, grade, rates, inventory, suppliers):
    plan = v3.get('plan') or {}
    v3_total = float(plan.get('total_minutes') or 0)
    v3_cut = _sum(plan.get('setups'), 'cutting_minutes')
    v3_tc_min = _sum(plan.get('setups'), 'tool_change_minutes')
    tool_changes = plan.get('tool_changes')
    tc_s = rates.get('tool_change_s')
    if v3_cut is not None and isinstance(tool_changes, (int, float)) and tc_s is not None:
        tc_min = round(tool_changes * tc_s / 60, 2)          # shop ATC time, not v3's 15 min/change
        total_min = round(v3_cut + tc_min, 2)
        tc_basis = 'atc'
    else:                                                     # no cutting/tool-change split from v3
        tc_min, total_min, tc_basis = v3_tc_min, v3_total, 'v3_total'
    setups = v3.get('setups_needed') or len(plan.get('setups') or []) or 1
    setup_min = setups * rates['setup_minutes_per_setup']
    rate_hr = rates['machine_inr_per_hr']
    margin_pct = rates['margin_pct']
    density = rates['density_g_cm3'].get(grade, rates['density_g_cm3']['aluminium'])
    billet = v3.get('billet_mm') or v3.get('part_bbox_mm')
    allow = rates['stock_allowance_mm']
    req = [round(float(b) + allow, 1) for b in billet] if billet else None

    # Stock: the team's in-house inventory first; otherwise the supplier directory (stock_lists.py).
    # Neither spreadsheet carries prices, so INR/kg comes from demo_data/stock/material_prices.json.
    inv_item, supplier, in_stock = None, None, False
    price_kg, price_is_sample, _ = stock_lists.price_per_kg(grade)
    if req:
        inv_item = stock_lists.pick_inventory(req, grade, qty)
        if inv_item:
            in_stock = True
        else:
            supplier = stock_lists.pick_supplier(grade)
        if supplier is not None and price_kg is not None:
            supplier['price_inr_per_kg'] = price_kg
        if inv_item is not None and price_kg is not None:
            inv_item['price_inr_per_kg'] = price_kg

    blank_mm3 = _blank_volume(inv_item, req) if req else None
    blank_kg = blank_mm3 * density / 1e6 if blank_mm3 else None
    material_inr = round(blank_kg * price_kg, 2) if (blank_kg and price_kg) else None
    machining_inr = round(total_min / 60 * rate_hr, 2)
    setup_batch_inr = round(setup_min / 60 * rate_hr, 2)
    setup_inr = round(setup_batch_inr / qty, 2)
    subtotal = round((material_inr or 0) + machining_inr + setup_inr, 2)
    margin_inr = round(subtotal * margin_pct / 100, 2)
    unit = round(subtotal + margin_inr, 2)

    hours_per_day = rates['shift_hours_per_day'] * rates['machine_utilization_pct'] / 100
    machine_hours = (setup_min + qty * total_min) / 60
    lt_mat = 0 if in_stock else (supplier.get('lead_days') if supplier else None)
    lt_mach = max(1, math.ceil(machine_hours / hours_per_day))
    lt_qc, lt_disp = rates['qc_days'], rates['dispatch_days']
    return {
        'machining': {'total_minutes': round(total_min, 2),
                      'cutting_minutes': v3_cut,
                      'tool_change_minutes': tc_min,
                      'tool_change_s': tc_s,
                      'tool_change_basis': tc_basis,
                      'v3_total_minutes': round(v3_total, 2),
                      'v3_tool_change_minutes': v3_tc_min,
                      'by_setup': plan.get('setups') or [],
                      'by_tool': plan.get('tools') or [], 'tool_changes': tool_changes},
        'setup_minutes': setup_min,
        'setups': setups,
        'rates': {'machine_inr_per_hr': rate_hr, 'margin_pct': margin_pct,
                  'setup_minutes_per_setup': rates['setup_minutes_per_setup'],
                  'shift_hours_per_day': rates['shift_hours_per_day'],
                  'machine_utilization_pct': rates['machine_utilization_pct'],
                  'qc_days': rates['qc_days'], 'dispatch_days': rates['dispatch_days'],
                  'stock_allowance_mm': rates['stock_allowance_mm'],
                  'tool_change_s': tc_s,
                  'sample_fields': rates.get('_sample_fields', [])},
        'material': {
            'grade': grade,
            'billet_mm': billet,
            'required_stock_mm': req,
            'density_g_cm3': density,
            'blank_kg': round(blank_kg, 3) if blank_kg else None,
            'price_inr_per_kg': price_kg,
            'price_is_sample': price_is_sample,
            'inventory_item': inv_item,
            'in_stock': in_stock,
            'supplier': supplier,
        },
        'cost': {
            'material_inr': material_inr,
            'machining_inr': machining_inr,
            'setup_inr': setup_inr,
            'setup_batch_inr': setup_batch_inr,
            'subtotal_inr': subtotal,
            'margin_inr': margin_inr,
            'unit_price_inr': unit,
            'qty': qty,
            'total_inr': round(unit * qty, 2),
            'currency': 'INR', 'excludes': ['GST 18%', 'shipping'],
        },
        'lead_time_days': {
            'material': lt_mat,
            'machining': lt_mach,
            'qc': lt_qc,
            'dispatch': lt_disp,
            'qc_dispatch': lt_qc + lt_disp,
            'total': (lt_mat + lt_mach + lt_qc + lt_disp) if lt_mat is not None else None,
            'machine_hours': round(machine_hours, 2),
        },
    }


def cycle_minutes(v3: dict) -> dict:
    """The quoted per-part cycle (v3 cutting + ATC tool changes) and v3's own total, for other endpoints."""
    m = _compute(v3, 1, 'aluminium_6061', _load('rates.json'), None, None)['machining']
    return {'total_minutes': m['total_minutes'], 'v3_total_minutes': m['v3_total_minutes'],
            'basis': m['tool_change_basis']}


def build(v3: dict, job_dir: Path, qty: int, material: str) -> dict:
    rates = _load('rates.json')
    inventory = suppliers = None  # stock comes from demo_data/stock via stock_lists
    grade = _grade_key(material)
    q = _compute(v3, qty, grade, rates, inventory, suppliers)

    m = q['machining']
    if m['tool_change_basis'] == 'atc':
        cycle_line = (f"Cycle time = {m['total_minutes']} min/part: v3 cutting time {m['cutting_minutes']} min "
                      f"(v3 tool/strategy simulation; v3 notes its time model runs ~2x conservative) + "
                      f"{m['tool_changes']} tool changes × {m['tool_change_s']:g} s on the shop's automatic tool changer "
                      f"({m['tool_change_minutes']} min).")
        v3_line = (f"v3's own total is {m['v3_total_minutes']} min/part: the v3 default assumes 15 min per manual "
                   f"tool change ({m['v3_tool_change_minutes']} min); shop ATC = {m['tool_change_s']:g} s per change.")
    else:
        cycle_line = (f"Cycle time = v3 machining plan total ({m['total_minutes']} min/part); v3 gave no "
                      'cutting/tool-change split, so its own tool-change pricing is used.')
        v3_line = None
    inv_item, sup = q['material']['inventory_item'], q['material']['supplier']
    stock_notes = []
    if inv_item:
        stock_notes.append(
            f"Material from in-house stock {inv_item['id']} ({inv_item['shape']} {inv_item['size']}, "
            f"{inv_item['items_needed']} of {int(inv_item['qty'])} on hand)"
            + (' — the inventory file is dummy data until the real stock is entered.' if inv_item.get('sample') else '.'))
    elif sup:
        lo, hi = sup['lead_range']
        stock_notes.append(
            f"Not in stock: {sup['name']} ({sup['city'] or 'city not stated'}), {sup['confidence']}-confidence listing, "
            + (f"lead time {lo:g}–{hi:g} days ({sup['lead_basis']}; the upper end is used)." if sup['lead_basis'] != 'actual'
               else f"actual lead time {lo:g} days.")
            + ('' if sup.get('verified') else ' Supplier not yet verified by ShiaanX.'))
    if q['material'].get('price_is_sample'):
        stock_notes.append('Material price per kg is a placeholder (demo_data/stock/material_prices.json) until the real price list is added.')
    assumptions = [
        cycle_line,
        *([v3_line] if v3_line else []),
        f"Machine rate ₹{rates['machine_inr_per_hr']}/hr (3-axis VMC, real rate).",
        f"Margin {rates['margin_pct']}% — placeholder, edit demo_data/rates.json.",
        f"Setup {rates['setup_minutes_per_setup']} min (placeholder) × {q['setups']} setup(s), one-time per batch, "
        f'amortised over qty {qty}.',
        f"Blank = v3 billet + {rates['stock_allowance_mm']} mm per dimension; density "
        f"{q['material']['density_g_cm3']} g/cm³.",
        f"Lead time (placeholders): {rates['shift_hours_per_day']} h shift at {rates['machine_utilization_pct']}% utilisation, "
        f"QC {rates['qc_days']} day(s) + dispatch {rates['dispatch_days']} day(s); "
        'queue wait for the machine is added by the app from the live board.',
        *stock_notes,
        'Excludes GST, shipping, CAM programming, special inspection, surface treatment.',
    ]
    if q['material']['price_inr_per_kg'] is None:
        assumptions.append(f'No inventory item or supplier for grade {grade} — material cost not included.')

    # v3's own caveats that bear on price / time are surfaced, not hidden
    notes = [str(w) for w in (v3.get('warnings') or [])]
    for w in notes:
        lw = w.lower()
        if any(k in lw for k in ('drilling is not priced', 'predicted stock', 'time model', 'never measured')):
            assumptions.append(f'v3: {w}')

    part_dir = part_data.find_part_dir(job_dir)
    from . import tracking  # lazy: loads repo closed_loop.parse_tap for the NC reference
    refs = part_data.shop_cycle_references(part_dir, tracking._cl())
    v3_cut = q['machining'].get('cutting_minutes')
    cycle_refs = None
    if refs:
        cycle_refs = {
            'quoted_cycle': {'total_minutes': q['machining']['total_minutes'], 'cutting_minutes': v3_cut,
                             'tool_change_minutes': q['machining'].get('tool_change_minutes'),
                             'basis': f"v3 cutting + tool changes at {q['machining'].get('tool_change_s')} s (ATC)"},
            'v3_plan': {'total_minutes': q['machining']['v3_total_minutes'], 'cutting_minutes': v3_cut,
                        'tool_change_minutes': q['machining'].get('v3_tool_change_minutes'),
                        'setups': q['setups']},
            'shop_programs': refs,
        }
        if len(refs) >= 2:
            mins = [r['minutes_per_part'] for r in refs if r['minutes_per_part']]
            cycle_refs['shop_programs_spread_x'] = round(max(mins) / min(mins), 1) if mins and min(mins) else None

    prev = part_data.load_previous_quote(part_dir)
    note_parts = []
    if prev and prev.get('qty') and prev.get('unit_price_inr'):
        pq = int(prev['qty'])
        same = q if pq == qty else _compute(v3, pq, grade, rates, inventory, suppliers)
        model_unit = same['cost']['unit_price_inr']
        diff = (model_unit - prev['unit_price_inr']) / prev['unit_price_inr'] * 100
        note_parts.append(
            f"Price: at the manual quote's qty ({pq}) this model gives ₹{model_unit:,.0f}/unit vs the manual "
            f"₹{prev['unit_price_inr']:,.0f}/unit ({diff:+.0f}%); manual quote material was "
            f"{prev.get('material')}, this quote uses {grade}.")
        prev = {**prev, 'model_unit_price_at_same_qty_inr': model_unit, 'delta_pct': round(diff, 1)}
    if refs:
        side = '; '.join(f"{r['label']}: {r['minutes_per_part']} min/part over {r['setups']} setups "
                         f"({r['basis'].split(' (')[0]})" for r in refs)
        txt = (f"Cycle time: quoted {q['machining']['total_minutes']} min"
               + (f" ({v3_cut} v3 cutting + {q['machining'].get('tool_change_minutes')} ATC tool changes; "
                  f"v3's own total with 15-min manual changes is {q['machining']['v3_total_minutes']} min)"
                  if v3_cut is not None and q['machining']['tool_change_basis'] == 'atc' else '')
               + f" vs real shop programs for this part — {side}.")
        if cycle_refs.get('shop_programs_spread_x'):
            txt += f" The shop programs themselves differ by ~{cycle_refs['shop_programs_spread_x']:g}×."
        note_parts.append(txt)
    note = ' '.join(note_parts) or None

    return {
        'status': 'ok',
        **{k: q[k] for k in ('machining', 'setup_minutes', 'rates', 'material', 'cost', 'lead_time_days')},
        'setups': q['setups'],
        'assumptions': assumptions,
        'previous_manual_quote': prev,
        'calibration_note': note,
        'cycle_time_references': cycle_refs,
        'engine_notes': notes,
        'v3_origin': v3.get('v3_origin'),
    }
