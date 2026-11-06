"""
reply.py — internal (ShiaanX team only) draft reply to a client comment, written by
Gemini and grounded strictly on this job's computed facts: quote, DFM findings and
drawing tolerances. No canned fallback: if the model call fails the caller gets an
error, never invented text.
"""

from __future__ import annotations

import os

import requests

# Google retires pinned models for newer accounts (gemini-2.5-flash-lite already answers 404 "no longer
# available to new users" for new keys). The "-latest" alias keeps drafting working; pin a model with
# the GEMINI_MODEL environment variable if you want a fixed one.
MODEL = os.environ.get('GEMINI_MODEL') or 'gemini-flash-lite-latest'
ENDPOINT = f'https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent'
TIMEOUT_S = 30


class ReplyError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _api_key() -> str | None:
    key = os.environ.get('GEMINI_API_KEY')
    if key:
        return key
    # Windows user env var set after this server's parent shell started
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as k:
            return winreg.QueryValueEx(k, 'GEMINI_API_KEY')[0] or None
    except Exception:
        return None


def collect_facts(topic: str | None, quote: dict | None, dfm: dict | None, tolerances: list[dict]) -> list[str]:
    facts = []
    if quote:
        c, lt, m = quote['cost'], quote['lead_time_days'], quote['material']
        facts.append(f"Quoted unit price ₹{c['unit_price_inr']:,.0f} at qty {c['qty']} "
                     f"(material ₹{(c['material_inr'] or 0):,.0f}, machining ₹{c['machining_inr']:,.0f}, "
                     f"setup ₹{c['setup_inr']:,.0f}/unit, margin {quote['rates']['margin_pct']}%), excl. GST & shipping.")
        facts.append(f"Machining time {quote['machining']['total_minutes']} min/part across {quote.get('setups')} "
                     f"setup(s) on a 3-axis VMC at ₹{quote['rates']['machine_inr_per_hr']}/hr.")
        stock = ('in stock (' + m['inventory_item']['id'] + ')') if m.get('in_stock') else \
                (f"to be procured ({m['supplier']['lead_days']} days)" if m.get('supplier') else 'source not identified')
        facts.append(f"Material {m['grade']}, blank {m.get('required_stock_mm')} mm, {stock}.")
        if lt.get('total') is not None:
            facts.append(f"Lead time {lt['total']} working days = material {lt['material']} + machining "
                         f"{lt['machining']} + QC/dispatch {lt['qc_dispatch']}.")
        if quote.get('previous_manual_quote'):
            p = quote['previous_manual_quote']
            facts.append(f"Our earlier manual quote {p.get('quote_id')} was ₹{p['unit_price_inr']:,.0f}/unit at qty "
                         f"{p.get('qty')} ({p.get('material')}), dispatch {p.get('dispatch_terms')}.")
    if dfm:
        facts.append(f"DFM: {dfm['summary']['text']}")
        for f in dfm['findings']:
            if f['severity'] != 'ok':
                facts.append(f"DFM {f['severity']}: {f['title']} — {f['detail']}")
    for t in tolerances:
        if t.get('kind') == 'visual':
            facts.append(f"Drawing visual check: {t['description']} ({t.get('instrument')}).")
        else:
            facts.append(f"Drawing {'Ø' if t['kind'] == 'diameter' else ''}{t['nominal_mm']} mm "
                         f"+{t['upper_tol_mm']}/-{t['lower_tol_mm']} (checked by {t.get('instrument')}).")
    return facts


def draft(client_comment: str, topic: str | None, part_name: str, facts: list[str]) -> dict:
    key = _api_key()
    if not key:
        raise ReplyError(502, 'GEMINI_API_KEY is not set for the capp_service process')
    prompt = (
        'You are drafting a reply for the ShiaanX team (a precision CNC machining company in India) to send '
        'to a client. This draft is internal — a ShiaanX engineer will review and edit it before sending.\n'
        f'Part: {part_name}\n'
        f'Client comment:\n"""{client_comment}"""\n\n'
        'The comment may raise several topics at once (price, lead time, tolerance, surface finish, or anything '
        'else). Address each topic the client raised, briefly, in the order they raised them. For anything the '
        'facts below do not cover, say the team will confirm it.\n\n'
        'Facts you may use (computed by our system for this exact part). Use ONLY these facts for any number, '
        'date, price, tolerance or capability. If the client asks for something these facts do not cover, say '
        'the team will confirm, do not guess. Do not promise discounts or dates beyond these facts.\n'
        'CONFIDENTIAL — never put these in the reply: our margin or markup %, the cost breakdown (material / '
        'machining / setup amounts), our hourly machine rate, our earlier internal quotes, inventory or supplier '
        'names, or internal analysis wording (e.g. "% of billet becomes chips", "v3", "DFM warning"). '
        'Use them only to reason. Speak to the client in terms of the part: complexity, setups, '
        'tolerances, material, quantity and schedule.\n'
        + '\n'.join(f'- {f}' for f in facts) +
        '\n\nWrite a concise, professional reply (80-200 words), plain text, no subject line, no placeholders '
        'like [Name]. Explain the key driver behind our position on each topic raised and offer one '
        'concrete option if the facts support one (e.g. a design change from a DFM finding, or a different qty).'
    )
    try:
        r = requests.post(ENDPOINT, headers={'x-goog-api-key': key, 'Content-Type': 'application/json'},
                          json={'contents': [{'parts': [{'text': prompt}]}],
                                'generationConfig': {'temperature': 0.3, 'maxOutputTokens': 600}},
                          timeout=TIMEOUT_S)
    except requests.RequestException as e:
        raise ReplyError(502, f'Gemini request failed: {type(e).__name__}')
    if r.status_code != 200:
        msg = ''
        try:
            msg = r.json().get('error', {}).get('message', '')
        except Exception:
            pass
        raise ReplyError(502, f'Gemini returned HTTP {r.status_code}: {msg[:300]}')
    try:
        text = ''.join(p.get('text', '') for p in r.json()['candidates'][0]['content']['parts']).strip()
    except (KeyError, IndexError, ValueError):
        raise ReplyError(502, 'Gemini response had no text candidate')
    if not text:
        raise ReplyError(502, 'Gemini returned an empty draft')
    return {'draft': text, 'grounded_on': facts, 'model': MODEL}
