"""
quote_pdf.py - the client-facing quote PDF (A4, reportlab).

Contains the quoted price and terms plus a manufacturability (DFM) summary. It must never carry
internal numbers: no margin, machine rate, cost breakdown, supplier / inventory names or internal
tool names. Everything comes from the server-side quote/DFM of the job; only the `edits` block
(price, lead time, validity, terms, notes) is taken from the caller.
"""

from __future__ import annotations

import base64
import binascii
import io
import re
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, KeepTogether

NAVY = colors.HexColor('#12263f')
GREY = colors.HexColor('#5b6672')
LINE = colors.HexColor('#d5dbe1')
SEV_COLOR = {'block': colors.HexColor('#b3261e'), 'warn': colors.HexColor('#a86400'), 'info': GREY, 'ok': GREY}
SEV_WORD = {'block': 'Needs a design change', 'warn': 'Worth a look', 'info': 'Note', 'ok': 'Fine'}

_JARGON = [(re.compile(r'(?<![A-Za-z0-9])v3(?![A-Za-z0-9])', re.I), 'machining plan'),
           (re.compile(r'(?<![A-Za-z0-9])CAPP(?![A-Za-z0-9])'), 'machining plan'),
           (re.compile(r'(?<![A-Za-z0-9])planner(?![A-Za-z0-9])', re.I), 'machining plan')]


def _clean(t) -> str:
    s = '' if t is None else str(t)
    for rx, rep in _JARGON:
        s = rx.sub(rep, s)
    for a, b in (('₹', 'INR '), ('³', '3'), ('×', 'x'), ('→', '->'), ('–', '-'),
                 ('—', '-'), ('’', "'"), ('≤', '<='), ('Ø', 'dia '), ('ø', 'dia '), ('⌀', 'dia '), ('°', ' deg'), ('±', '+/-'), ('≥', '>=')):
        s = s.replace(a, b)
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def inr(v) -> str:
    """INR with Indian digit grouping (12,34,567)."""
    if v is None:
        return '-'
    neg = float(v) < 0
    whole, frac = f'{abs(float(v)):.2f}'.split('.')
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ','.join(parts + [tail])
    out = f'INR {whole}' + ('' if frac == '00' else f'.{frac}')
    return '-' + out if neg else out


def _fmt_val(v) -> str:
    if isinstance(v, dict):
        return ', '.join(f"{_clean(k).replace('_', ' ')} {_fmt_val(x)}" for k, x in v.items())
    if isinstance(v, (list, tuple)):
        return ' x '.join(_fmt_val(x) for x in v)
    if isinstance(v, float):
        return f'{v:.2f}'.rstrip('0').rstrip('.')
    return _clean(v)


def part_size_mm(dfm: dict):
    s = (dfm or {}).get('summary') or {}
    b = s.get('part_bbox_mm') or s.get('billet_mm')
    if b and len(b) == 3:
        return [round(float(x), 1) for x in b]
    return None


def top_findings(dfm: dict, limit: int = 6) -> list:
    rank = {'block': 0, 'warn': 1}
    rows = []
    for cat in (dfm or {}).get('categories') or []:
        for it in cat.get('items') or []:
            if it.get('severity') in rank:
                rows.append({'sev': it['severity'], 'label': it.get('label'), 'why': cat.get('why') or it.get('detail'),
                             'measured': it.get('measured'), 'expected': it.get('expected')})
    for f in (dfm or {}).get('findings') or []:
        if f.get('severity') in rank:
            rows.append({'sev': f['severity'], 'label': f.get('title'), 'why': f.get('detail'),
                         'measured': None, 'expected': None})
    rows.sort(key=lambda r: rank[r['sev']])
    seen, out = set(), []
    for r in rows:
        k = (r['label'] or '').strip().lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out[:limit]


def build_pdf(*, customer, enquiry_number, part_name, qty, material, edits, prepared_by, quote, dfm,
              snapshot_png: bytes | None = None) -> bytes:
    edits = edits or {}
    cost = quote['cost']
    lead = quote['lead_time_days']
    qty = int(qty or cost.get('qty') or 1)
    unit = edits.get('unit_price_inr')
    unit = float(unit) if unit not in (None, '') else float(cost['unit_price_inr'])
    total = round(unit * qty, 2)
    lead_days = edits.get('lead_days')
    lead_days = int(lead_days) if lead_days not in (None, '') else lead.get('total')
    validity = int(edits.get('validity_days') or 30)
    terms = _clean(edits.get('payment_terms') or 'As per PO')
    notes = _clean(edits.get('notes') or '').strip()
    mat_label = _clean((material or quote['material'].get('grade') or '').replace('_', ' '))

    ss = getSampleStyleSheet()
    body = ParagraphStyle('b', parent=ss['BodyText'], fontName='Helvetica', fontSize=9.5, leading=13)
    small = ParagraphStyle('s', parent=body, fontSize=8, leading=10.5, textColor=GREY)
    h2 = ParagraphStyle('h2', parent=body, fontName='Helvetica-Bold', fontSize=12, textColor=NAVY, spaceBefore=12, spaceAfter=5)
    title = ParagraphStyle('t', parent=body, fontName='Helvetica-Bold', fontSize=20, leading=24, textColor=NAVY)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                            bottomMargin=18 * mm, title='Quotation', author='ShiaanX')

    def footer(c, d):
        c.saveState()
        c.setFont('Helvetica', 7.5)
        c.setFillColor(GREY)
        c.drawString(18 * mm, 10 * mm, 'ShiaanX - precision manufacturing. This quotation is subject to the terms above.')
        c.drawRightString(A4[0] - 18 * mm, 10 * mm, f'Page {d.page}')
        c.restoreState()

    el = []
    head = Table([[Paragraph('Quotation', title),
                   Paragraph(f'<b>Quote no.</b> {_clean(enquiry_number) or "-"}<br/><b>Date</b> {date.today().strftime("%d %b %Y")}'
                             + (f'<br/><b>Prepared by</b> {_clean(prepared_by)}' if prepared_by else ''), body)]],
                 colWidths=[100 * mm, 74 * mm])
    head.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
                              ('LINEBELOW', (0, 0), (-1, 0), 1.2, NAVY), ('BOTTOMPADDING', (0, 0), (-1, 0), 8)]))
    el += [head, Spacer(1, 8)]

    def kv(rows, widths=(48 * mm, 126 * mm)):
        t = Table([[Paragraph(f'<b>{a}</b>', body), Paragraph(b if str(b).startswith('<b>') else _clean(b), body)] for a, b in rows],
                  colWidths=widths)
        t.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LINEBELOW', (0, 0), (-1, -1), 0.4, LINE),
                               ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3)]))
        return t

    el.append(kv([('Customer', customer or '-'), ('Part', part_name or '-'), ('Quantity', f'{qty} pcs'), ('Material', mat_label)]))

    el.append(Paragraph('Price and delivery', h2))
    el.append(kv([('Unit price', inr(unit)), (f'Order total ({qty} pcs)', f'<b>{inr(total)}</b>'),
                  ('Lead time', f'{lead_days} working days from order confirmation' if lead_days is not None else 'To be confirmed'),
                  ('Quote valid for', f'{validity} days'), ('Payment terms', terms)]))
    if lead.get('total') is not None:
        el.append(Spacer(1, 3))
        el.append(Paragraph(f"Typical build-up: material {lead.get('material', 0)} + machining {lead.get('machining')} + "
                            f"quality check {lead.get('qc', 1)} + dispatch {lead.get('dispatch', 1)} working days, "
                            'plus any wait for machine time.', small))
    if notes:
        el.append(Spacer(1, 5))
        el.append(Paragraph(f'<b>Notes</b><br/>{notes.replace(chr(10), "<br/>")}', body))

    s = (dfm or {}).get('summary') or {}
    el.append(Paragraph('Manufacturability review (DFM)', h2))
    counts, fc = s.get('counts') or {}, s.get('face_level_counts') or {}
    blockers = (counts.get('block') or 0) + (fc.get('block') or 0)
    warns = (counts.get('warn') or 0) + (fc.get('warn') or 0)
    el.append(Paragraph(f"<b>{_clean(s.get('verdict') or 'Review not available')}</b>. "
                        f"{blockers} item(s) needing a design change, {warns} worth a look, "
                        f"{counts.get('ok') or 0} checks passed.", body))
    size = part_size_mm(dfm)
    if size:
        el.append(Paragraph(f'Part size: {size[0]:g} x {size[1]:g} x {size[2]:g} mm', body))
    finds = top_findings(dfm)
    if finds:
        rows = [[Paragraph('<b>Finding</b>', small), Paragraph('<b>Why it matters</b>', small),
                 Paragraph('<b>Measured / expected</b>', small)]]
        for f in finds:
            mv = ''
            if f['measured'] is not None or f['expected'] is not None:
                mv = f"{_fmt_val(f['measured'])} / {_fmt_val(f['expected'])}"
            c = SEV_COLOR[f['sev']]
            rows.append([Paragraph(f'<font color="{c.hexval()}"><b>{SEV_WORD[f["sev"]]}</b></font><br/>{_clean(f["label"])}', small),
                         Paragraph(_clean(f['why']), small), Paragraph(mv, small)])
        t = Table(rows, colWidths=[52 * mm, 78 * mm, 44 * mm], repeatRows=1)
        t.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#eef1f4')),
                               ('LINEBELOW', (0, 0), (-1, -1), 0.4, LINE)]))
        el += [Spacer(1, 5), t]
    else:
        el.append(Paragraph('No manufacturability concerns were found.', body))

    if snapshot_png:
        try:
            from reportlab.lib.utils import ImageReader
            w, h = ImageReader(io.BytesIO(snapshot_png)).getSize()
            iw = 120 * mm
            el.append(Spacer(1, 8))
            el.append(KeepTogether([Image(io.BytesIO(snapshot_png), width=iw, height=iw * h / w),
                                    Paragraph('3D view of the part', small)]))
        except Exception:
            pass  # a bad image must never fail the PDF

    el.append(Paragraph('Exclusions', h2))
    ex = [_clean(x) for x in (cost.get('excludes') or [])] + ['special inspection', 'surface treatment']
    el.append(Paragraph('Prices exclude ' + ', '.join(dict.fromkeys(ex)) + '.', body))
    doc.build(el, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


def decode_snapshot(b64: str | None) -> bytes | None:
    if not b64:
        return None
    if ',' in b64[:80]:
        b64 = b64.split(',', 1)[1]
    try:
        data = base64.b64decode(b64, validate=False)
    except (binascii.Error, ValueError):
        return None
    return data if data[:8] == b'\x89PNG\r\n\x1a\n' else None
