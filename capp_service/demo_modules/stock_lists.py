"""In-house inventory and supplier directory for the quote.

The source of truth is two spreadsheets kept in git (demo_data/stock/): inhouse_inventory.xlsx and
supplier_directory.xlsx. The team edits them in Excel, commits and redeploys; there is no conversion step
(see demo_data/stock/README.md).

Rules, taken from the notes sheets of the two files:
  * Inventory: match on Material + Grade + Shape + Size. Qty is pieces on hand. While the Notes sheet says
    "dummy" or "demo data", every item is flagged sample (clears itself once the note is edited).
  * Suppliers: when in-house has no match, filter Supplier_Grade_Map by Grade + Shape, sort by Confidence
    (High, Medium, Low) then lead time, and show the supplier from the Suppliers sheet by Supplier ID.
    "Actual Lead Time (days)", once filled by the team, is preferred over the estimate.
  * Neither file has prices: demo_data/stock/material_prices.json (placeholder, sample) supplies INR/kg.
"""
import itertools
import json
import math
import os
import re
from pathlib import Path

import openpyxl

from . import file_cache

STOCK_DIR = Path(os.environ.get('SHIAANX_STOCK_DIR') or (Path(__file__).resolve().parent.parent / 'demo_data' / 'stock'))
INVENTORY_XLSX = STOCK_DIR / 'inhouse_inventory.xlsx'
SUPPLIERS_XLSX = STOCK_DIR / 'supplier_directory.xlsx'
PRICES_JSON = STOCK_DIR / 'material_prices.json'

# quote material key -> (Material, Grade) exactly as written in both spreadsheets
GRADES = {
    'aluminium': ('Aluminium', '6061-T6'),
    'aluminium_6061': ('Aluminium', '6061-T6'),
    'aluminium_6082': ('Aluminium', '6082-T6'),
    'aluminium_7075': ('Aluminium', '7075-T651'),
    'aluminium_2024': ('Aluminium', '2024-T351'),
    'aluminium_5083': ('Aluminium', '5083-H111'),
}
# Shapes a solid block can be cut from, in the order a supplier lookup tries them (least waste first).
SHAPE_ORDER = ['Plate', 'Flat Bar', 'Block', 'Square Bar', 'Round Bar']
CONF_RANK = {'High': 0, 'Medium': 1, 'Low': 2}
LEAD_BASIS = 'max'  # supplier estimates are ranges: 'max' (conservative), 'min' or 'mid'


# ── spreadsheet reading ─────────────────────────────────────────────────────────────────────────────

def _num(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r'-?\d+(?:\.\d+)?', str(v).replace(',', ''))
    return float(m.group()) if m else None


def _text(v):
    s = ('' if v is None else str(v)).strip()
    return None if s.lower() in ('', 'none', 'not stated', 'n/a') else s


def _read_sheet(wb, name):
    if name not in wb.sheetnames:
        return []
    rows = list(wb[name].iter_rows(values_only=True))
    if not rows:
        return []
    head = [('' if h is None else str(h).strip()) for h in rows[0]]
    out = []
    for r in rows[1:]:
        if not r or r[0] in (None, ''):
            continue
        out.append({head[i]: r[i] for i in range(min(len(head), len(r))) if head[i]})
    return out


def _notes_text(wb):
    if 'Notes' not in wb.sheetnames:
        return ''
    return ' '.join(str(c) for r in wb['Notes'].iter_rows(values_only=True) for c in r if c)


def _load_inventory():
    if not INVENTORY_XLSX.exists():
        return {'items': [], 'sample': True, 'source': INVENTORY_XLSX.name, 'error': 'file not found'}
    wb = openpyxl.load_workbook(INVENTORY_XLSX, data_only=True, read_only=True)
    try:
        rows = _read_sheet(wb, 'Inventory')
        sample = bool(re.search(r'dummy|demo data', _notes_text(wb), re.I))
    finally:
        wb.close()
    items = []
    for r in rows:
        items.append({
            'id': str(r.get('SKU')).strip(),
            'material': _text(r.get('Material')),
            'grade_label': _text(r.get('Grade')),
            'shape': _text(r.get('Shape')),
            'size': _text(r.get('Size Description')),
            'w': _num(r.get('Width / Dia (mm)')),
            'h': _num(r.get('Height (mm)')),
            't': _num(r.get('Thickness / Wall (mm)')),
            'length': _num(r.get('Length (mm)')),
            'unit_weight_kg': _num(r.get('Unit Weight (kg)')),
            'qty': _num(r.get('Qty Available')) or 0,
            'uom': _text(r.get('UoM')),
            'condition': _text(r.get('Condition')),
            'location': _text(r.get('Rack Location')),
            'availability': _text(r.get('Availability')),
            'sample': sample,
        })
    return {'items': items, 'sample': sample, 'source': INVENTORY_XLSX.name}


def _load_suppliers():
    if not SUPPLIERS_XLSX.exists():
        return {'suppliers': {}, 'map': [], 'source': SUPPLIERS_XLSX.name, 'error': 'file not found'}
    wb = openpyxl.load_workbook(SUPPLIERS_XLSX, data_only=True, read_only=True)
    try:
        sup_rows = _read_sheet(wb, 'Suppliers')
        map_rows = _read_sheet(wb, 'Supplier_Grade_Map')
    finally:
        wb.close()
    suppliers = {}
    for r in sup_rows:
        sid = str(r.get('Supplier ID')).strip()
        suppliers[sid] = {
            'id': sid,
            'name': _text(r.get('Supplier Name')) or sid,
            'type': _text(r.get('Supplier Type (as listed)')),
            'city': _text(r.get('City')),
            'state': _text(r.get('State')),
            'region': _text(r.get('Region')),
            'lead_min': _num(r.get('Est. Lead Time Min (days)')),
            'lead_max': _num(r.get('Est. Lead Time Max (days)')),
            'lead_basis': _text(r.get('Lead Time Basis')),
            'contact': _text(r.get('Contact (as listed)')),
            'source_url': _text(r.get('Source URL')),
            'data_confidence': _text(r.get('Data Confidence')),
            'verified': (_text(r.get('ShiaanX Verified')) or '').lower() in ('yes', 'y', 'true', 'verified'),
            'last_quote_date': _text(r.get('Last Quote Date')),
            'actual_lead_days': _num(r.get('Actual Lead Time (days)')),
            'rating': _num(r.get('ShiaanX Rating (1-5)')),
            'notes': _text(r.get('Notes')),
        }
    entries = []
    for r in map_rows:
        entries.append({
            'supplier_id': str(r.get('Supplier ID')).strip(),
            'material': _text(r.get('Material')),
            'grade': _text(r.get('Grade')),
            'shape': _text(r.get('Shape')),
            'confidence': _text(r.get('Confidence')),
            'region': _text(r.get('Region')),
            'lead_min': _num(r.get('Est. Lead Time Min (days)')),
            'lead_max': _num(r.get('Est. Lead Time Max (days)')),
            'evidence': _text(r.get('Evidence (what the listing says)')) or _text(r.get('Evidence (what the listing s')),
        })
    return {'suppliers': suppliers, 'map': entries, 'source': SUPPLIERS_XLSX.name}


def load_inventory():
    return file_cache.memo('stock_inventory', [INVENTORY_XLSX], _load_inventory)


def load_suppliers():
    return file_cache.memo('stock_suppliers', [SUPPLIERS_XLSX], _load_suppliers)


def price_per_kg(grade_key):
    """(price INR/kg or None, is_sample, note). Neither spreadsheet has prices."""
    def _read():
        try:
            return json.loads(PRICES_JSON.read_text(encoding='utf-8'))
        except Exception:
            return {}
    d = file_cache.memo('stock_prices', [PRICES_JSON], _read)
    key = 'aluminium_6061' if grade_key == 'aluminium' else grade_key
    p = (d.get('prices_inr_per_kg') or {}).get(key)
    return (float(p) if p else None), bool(d.get('sample', True)), d.get('_note')


def describe_sources():
    inv, sup = load_inventory(), load_suppliers()
    return {'inventory': {'file': inv.get('source'), 'items': len(inv.get('items', [])), 'sample': inv.get('sample')},
            'suppliers': {'file': sup.get('source'), 'suppliers': len(sup.get('suppliers', {})), 'grade_map_rows': len(sup.get('map', []))},
            'prices': {'file': PRICES_JSON.name, 'sample': price_per_kg('aluminium_6061')[1]}}


# ── in-house matching ───────────────────────────────────────────────────────────────────────────────

def _prism(item):
    """Side lengths (d0, d1, d2) of a rectangular stock piece, or None for shapes that cannot yield a block."""
    s, w, h, t, ln = item['shape'], item['w'], item['h'], item['t'], item['length']
    if s in ('Plate', 'Flat Bar') and w and t and ln:
        return (t, w, ln)
    if s == 'Square Bar' and w and ln:
        return (w, h or w, ln)
    if s == 'Block' and w and h and ln:
        return (w, h, ln)
    return None


def pieces_per_item(item, req):
    """How many billets of size req (mm, any order) can be cut from ONE stock piece (0 = none)."""
    best = 0
    if item['shape'] == 'Round Bar' and item['w'] and item['length']:
        dia, ln = item['w'], item['length']
        for z in range(3):
            x, y = [req[i] for i in range(3) if i != z]
            if math.hypot(x, y) <= dia and req[z] <= ln:
                best = max(best, int(ln // req[z]))
        return best
    d = _prism(item)
    if not d:
        return 0
    for p in itertools.permutations(req):
        if all(p[i] <= d[i] for i in range(3)):
            best = max(best, int(d[0] // p[0]) * int(d[1] // p[1]) * int(d[2] // p[2]))
    return best


def pick_inventory(req_mm, grade_key, qty):
    """Best in-house stock item for qty billets of req_mm, or None. Least stock weight consumed per billet
    wins; the item must have enough pieces on hand and be Available (not Reserved / Out of Stock)."""
    material, grade = GRADES.get(grade_key, (None, None))
    if not (req_mm and material):
        return None
    best = None
    for it in load_inventory()['items']:
        if it['material'] != material or it['grade_label'] != grade or not it['qty'] or it['qty'] <= 0:
            continue
        if (it['availability'] or 'available').lower() != 'available':
            continue
        n = pieces_per_item(it, req_mm)
        if n < 1:
            continue
        need = math.ceil(qty / n)
        if need > it['qty']:
            continue
        per_billet = (it['unit_weight_kg'] or 0) / n if it['unit_weight_kg'] else float('inf')
        key = (per_billet, need, it['id'])
        if best is None or key < best[0]:
            best = (key, it, n, need)
    if not best:
        return None
    _, it, n, need = best
    return {**it, 'pieces_per_item': n, 'items_needed': need}


# ── supplier fallback ───────────────────────────────────────────────────────────────────────────────

def _lead(entry, sup, basis):
    """(days used or None, [lo, hi], 'actual' | 'planning estimate')."""
    if sup.get('actual_lead_days') is not None:
        a = sup['actual_lead_days']
        return a, [a, a], 'actual'
    lo = entry.get('lead_min') if entry.get('lead_min') is not None else sup.get('lead_min')
    hi = entry.get('lead_max') if entry.get('lead_max') is not None else sup.get('lead_max')
    if lo is None and hi is None:
        return None, [None, None], 'planning estimate'
    lo, hi = (lo if lo is not None else hi), (hi if hi is not None else lo)
    used = hi if basis == 'max' else lo if basis == 'min' else round((lo + hi) / 2)
    return used, [lo, hi], 'planning estimate'


def pick_supplier(grade_key, basis=None):
    """Supplier offer for a grade, or None. Per the directory's own rules: filter the grade map by Grade +
    Shape, sort by Confidence then lead time (an Actual Lead Time wins over the estimate)."""
    material, grade = GRADES.get(grade_key, (None, None))
    if not material:
        return None
    basis = basis or LEAD_BASIS
    data = load_suppliers()
    for shape in SHAPE_ORDER:
        cands = [e for e in data['map'] if e['material'] == material and e['grade'] == grade and e['shape'] == shape
                 and e['supplier_id'] in data['suppliers']]
        if not cands:
            continue

        def sort_key(e):
            s = data['suppliers'][e['supplier_id']]
            used, rng, _ = _lead(e, s, 'min')
            return (CONF_RANK.get(e['confidence'], 9), rng[0] if rng[0] is not None else 9999, e['supplier_id'])

        cands.sort(key=sort_key)
        e = cands[0]
        s = data['suppliers'][e['supplier_id']]
        used, rng, lead_basis = _lead(e, s, basis)
        alts = []
        for a in cands[1:4]:
            sa = data['suppliers'][a['supplier_id']]
            _, arng, _ = _lead(a, sa, basis)
            alts.append({'name': sa['name'], 'city': sa['city'] or sa['region'], 'confidence': a['confidence'], 'lead_range': arng})
        return {
            'supplier_id': s['id'], 'name': s['name'], 'city': s['city'] or s['region'], 'region': s['region'],
            'shape': shape, 'grade': grade, 'confidence': e['confidence'],
            'lead_days': used, 'lead_range': rng, 'lead_basis': lead_basis,
            'verified': s['verified'], 'sample': False,
            'evidence': (e['evidence'] or '')[:200], 'alternatives': alts,
        }
    return None
