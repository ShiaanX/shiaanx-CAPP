"""
telemetry_batch.py — a few headline machine facts per setup for a past production batch, from the
real controller log (InfluxDB cnc_telemetry), in the spirit of the closed-loop report
(C:/Users/Siddhant Gupta/Documents/closed-loop: krishna_metrics.py / closed_loop.py).

The endpoint NEVER touches InfluxDB. `refresh` pulls once, computes, and writes a snapshot:
    demo_data/production_history/<key>_<batch>_telemetry.json
which production_history.py serves as batch[...].machine_data. Refresh (from capp_service/):
    python -m demo_modules.telemetry_batch refresh motormount

Decoding of the TS machine (jyotiVMC, Sinumerik 828D). Worked out from the Motor Mount data itself,
not from vendor docs:
  machine_state  1 = program running, 2 = interrupted / feed-hold, 0 = stopped / reset
  machine_mode   2 = AUTO (program execution), 0 = JOG / MDI (operator hand moves)
  cycle_time     SECONDS (float; the Mitsubishi MM·SS packing in krishna_metrics does NOT apply).
                 Resets to ~0 at cycle start, climbs while the program runs, holds its final value
                 after M30 until the next cycle start. Its peak = that cycle's controller run time.
  cutting_time   always 0 on this machine (known bug), so a cutting-vs-air split is NOT reported.

Metrics (closed-loop definitions, adapted to the fields this machine actually sends):
  1. Planned vs actual cycle: programmer's ';time =' header total for the setup vs the median
     controller cycle time of FULL cycles (peak >= FULL_CYCLE_FRAC x programmed, start observed).
  2. Spindle actual vs programmed: median actual RPM while running in AUTO vs the minutes-weighted
     median programmed S of the setup's ops, plus the share of spindle-on running time that sat
     within ±RPM_MATCH_PCT of one of the setup's programmed S values.
  3. Feed override: krishna_metrics._override_stats over AUTO-running samples (0 = not feeding,
     excluded); plus the plain median over the same samples.
  4. State split over logged time (gaps > krishna_metrics.SAMPLE_DT_CAP_S are untracked):
     running (AUTO, state 1) / hold (state 2) / manual (JOG/MDI) / idle (AUTO, state 0: program
     loaded, not running = load/unload). Alarm = share of logged time with alarm_active = 1.
  5. Operator interventions: feed-hold events (entries into state 2) and minutes in JOG/MDI.
  6. Load/unload: median gap between one full cycle ending and the next starting, same session.

Lots: samples more than LOT_GAP_DAYS apart are separate lots. The EARLIEST lot carries the headline
numbers (it is the one where setups 1 -> 2 -> 4 ran in order); later lots are listed, not mixed in.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import file_cache

CLOSED_LOOP = Path(r'C:\Users\Siddhant Gupta\Documents\closed-loop')
SNAPSHOT_DIR = Path(__file__).resolve().parent.parent / 'demo_data' / 'production_history'

STATE_IDLE, STATE_RUNNING, STATE_HOLD = 0, 1, 2
MODE_AUTO = 2
FULL_CYCLE_FRAC = 0.75       # a cycle counts as full when it ran >= 75% of the programmed time
OVERRIDE_SETTING_MIN_SHARE = 0.01  # a knob setting held < 1% of run time is a transient (knob being turned)
MIN_RUN_S = 60               # runs shorter than this are prove-outs / restarts, ignored
SESSION_GAP_S = 30 * 60      # logging gap that starts a new session
LOT_GAP_DAYS = 7             # gap that starts a new lot (a separate production run)
LOAD_GAP_MAX_S = 30 * 60     # a cycle-to-cycle gap longer than this is not a load/unload
RPM_MATCH_PCT = 3.0
REPEAT_MIN_COUNT = 5         # partial runs repeating this often at one length = a trimmed program

FIELDS = ['machine_state', 'machine_mode', 'spindle_speed', 'feed_override', 'spindle_override',
          'cycle_time', 'alarm_active', 'tool_number']

BATCHES = {
    'motormount': {
        'batch_id': 'run2',
        'factory_id': 'ts', 'machine_id': 'jyotiVMC',
        'parts_inspected': 9,
        'setups': [
            {'setup': 1, 'program_name': 'MOTOR_MOUNT_1_SETUP.',
             'windows': [('2026-06-06T00:00:00Z', '2026-06-09T00:00:00Z'),
                         ('2026-07-03T00:00:00Z', '2026-07-06T00:00:00Z')]},
            {'setup': 2, 'program_name': 'MOTOR_MOUNT_2_SETUP.',
             'windows': [('2026-06-08T00:00:00Z', '2026-06-14T00:00:00Z'),
                         ('2026-07-03T00:00:00Z', '2026-07-06T00:00:00Z')]},
            {'setup': 3, 'program_name': None, 'windows': [],
             'not_recorded_reason': 'No program with a Motor/Mount name for the finish setup was found '
                                    'in the controller log.'},
            {'setup': 4, 'program_name': 'MOTOR_MOUNT_4_SETUP.',
             'windows': [('2026-06-13T00:00:00Z', '2026-06-15T00:00:00Z')]},
        ],
    },
}


# ── closed-loop repo import (read-only) ──────────────────────────────────────

def _km(load_env: bool = False):
    if str(CLOSED_LOOP) not in sys.path:
        sys.path.insert(0, str(CLOSED_LOOP))
    import krishna_metrics as km
    if load_env and not km.BASE_URL:
        # km loads ".env" relative to the cwd at import; point it at the repo's own file instead.
        km._load_dotenv(str(CLOSED_LOOP / '.env'))
        km.BASE_URL = os.environ.get('INFLUX_BASE_URL', '')
        km.ORG = os.environ.get('INFLUX_ORG', km.ORG)
        km.BUCKET = os.environ.get('INFLUX_BUCKET', km.BUCKET)
        km.USERNAME = os.environ.get('INFLUX_USERNAME', '')
        km.PASSWORD = os.environ.get('INFLUX_PASSWORD', '')
    return km


# ── fetch ────────────────────────────────────────────────────────────────────

def flux_for(bucket: str, measurement: str, factory_id: str, machine_id: str,
             program_name: str, start: str, stop: str) -> str:
    flt = ' or '.join(f'r._field == "{f}"' for f in FIELDS)
    return (f'from(bucket: "{bucket}")\n'
            f'  |> range(start: {start}, stop: {stop})\n'
            f'  |> filter(fn: (r) => r._measurement == "{measurement}" and r.factory_id == "{factory_id}"'
            f' and r.machine_id == "{machine_id}" and r.program_name == "{program_name}")\n'
            f'  |> filter(fn: (r) => {flt})\n'
            f'  |> drop(columns: ["program", "tool_name"])\n'
            f'  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")')


def fetch(cfg: dict) -> tuple[dict, list]:
    """-> ({setup_no: [samples]}, [query records]). Raises on any query failure."""
    import time
    km = _km(load_env=True)
    session = km.get_session()
    raw, queries = {}, []
    for s in cfg['setups']:
        if not s['program_name']:
            continue
        out = []
        for start, stop in s['windows']:
            flux = flux_for(km.BUCKET, km.MEASUREMENT, cfg['factory_id'], cfg['machine_id'],
                            s['program_name'], start, stop)
            t0 = time.time()
            rows = km.query(session, flux)
            queries.append({'setup': s['setup'], 'program_name': s['program_name'],
                            'range': [start, stop], 'rows': len(rows),
                            'seconds': round(time.time() - t0, 1), 'flux': flux})
            for r in rows:
                t = r.get('_time')
                if not t:
                    continue
                d = {'_time': t, 't': km._parse_ts(t)}
                for f in FIELDS:
                    d[f] = km._num(r.get(f))
                out.append(d)
        out.sort(key=lambda d: d['t'])
        raw[s['setup']] = out
    return raw, queries


# ── compute (pure; unit-tested on synthetic samples) ────────────────────────

def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def _day_label(t0: float, t1: float) -> str:
    a = datetime.fromtimestamp(t0, timezone.utc)
    b = datetime.fromtimestamp(t1, timezone.utc)
    if a.date() == b.date():
        return f"{a.day} {a:%b %Y}"
    if a.month == b.month:
        return f"{a.day}–{b.day} {b:%b %Y}"
    return f"{a.day} {a:%b} – {b.day} {b:%b %Y}"


def split_gaps(samples: list[dict], gap_s: float) -> list[list[dict]]:
    groups: list[list[dict]] = []
    for s in samples:
        if not groups or s['t'] - groups[-1][-1]['t'] > gap_s:
            groups.append([])
        groups[-1].append(s)
    return groups


def find_cycles(samples: list[dict]) -> list[dict]:
    """Program runs whose START was observed (cycle_time reset). Each: start_t, end_t (time of the
    peak), seconds (peak cycle_time). A value held over from before the window is never a cycle."""
    cycles, cur = [], None
    for a, b in zip(samples, samples[1:]):
        ca, cb = a.get('cycle_time') or 0, b.get('cycle_time') or 0
        if ca > 5 and cb < 0.5 * ca:                      # reset = cycle start pressed again
            if cur:
                cycles.append(cur)
            cur = {'start_t': b['t'], 'end_t': b['t'], 'seconds': cb}
        elif cur is not None and b['t'] - a['t'] > SESSION_GAP_S:
            cycles.append(cur)                            # logging stopped; close the run
            cur = None
        if cur is not None and cb > cur['seconds']:      # strictly rising: the held value after
            cur['seconds'], cur['end_t'] = cb, b['t']    # M30 must not push end_t forward
    if cur:
        cycles.append(cur)
    return [c for c in cycles if c['seconds'] >= MIN_RUN_S]


def state_split(samples: list[dict], dt_cap: float) -> dict:
    sec = Counter()
    alarm = holds = 0.0
    hold_events = 0
    for a, b in zip(samples, samples[1:]):
        dt = b['t'] - a['t']
        if dt <= 0:
            continue
        if dt > dt_cap:
            sec['untracked'] += dt
            continue
        st, md = b.get('machine_state'), b.get('machine_mode')
        if md is not None and md != MODE_AUTO:
            k = 'manual'
        elif st == STATE_RUNNING:
            k = 'running'
        elif st == STATE_HOLD:
            k = 'hold'
        else:
            k = 'idle'
        sec[k] += dt
        if b.get('alarm_active') == 1:
            alarm += dt
        if st == STATE_HOLD and a.get('machine_state') != STATE_HOLD and md == MODE_AUTO:
            hold_events += 1
    tracked = sum(sec[k] for k in ('running', 'hold', 'manual', 'idle')) or 1.0
    pct = lambda v: round(100 * v / tracked, 1)
    return {'running_pct': pct(sec['running']), 'hold_pct': pct(sec['hold']),
            'manual_pct': pct(sec['manual']), 'idle_pct': pct(sec['idle']),
            'alarm_pct': pct(alarm),
            'cutting_pct': None, 'air_pct': None,
            'logged_hours': round(tracked / 3600, 1),
            'running_minutes': round(sec['running'] / 60, 1),
            'manual_minutes': round(sec['manual'] / 60, 1),
            'hold_events': hold_events}


def programmed_for_setup(ops: list[dict], setup: int) -> dict:
    ops = [o for o in ops if o.get('setup') == setup and o.get('rpm')]
    rpms = sorted({float(o['rpm']) for o in ops})
    weighted = sorted((float(o['rpm']), float(o.get('minutes') or 0)) for o in ops)
    total = sum(w for _, w in weighted)
    med, acc = None, 0.0
    for r, w in weighted:
        acc += w
        if acc >= total / 2:
            med = r
            break
    return {'rpm_values': rpms, 'rpm_weighted_median': med}


def _fmt_min(m):
    return None if m is None else round(m, 1)


def compute_setup(spec: dict, samples: list[dict], programmed_minutes: float | None,
                  prog_rpm: dict, km) -> dict:
    base = {'setup': spec['setup'], 'program_name': spec['program_name'],
            'programmed_minutes': _fmt_min(programmed_minutes)}
    if not spec['program_name'] or len(samples) < 2:
        return {**base, 'recorded': False, 'sessions': [], 'first': None, 'last': None,
                'actual_machine_minutes': None, 'ratio': None, 'spindle': None,
                'feed_override': None, 'state_split': None,
                'headline': f"Setup {spec['setup']}: not recorded in the controller log."}

    dt_cap = km.SAMPLE_DT_CAP_S
    lots = split_gaps(samples, LOT_GAP_DAYS * 86400)
    prog_s = (programmed_minutes or 0) * 60
    lot_recs = []
    for i, lot in enumerate(lots):
        cyc = find_cycles(lot)
        full = [c for c in cyc if prog_s and c['seconds'] >= FULL_CYCLE_FRAC * prog_s]
        partial = [c for c in cyc if c not in full]
        lot_recs.append({'lot': lot, 'full': full, 'partial': partial, 'primary': i == 0})

    sessions = []
    for r in lot_recs:
        lot, full = r['lot'], r['full']
        rep = Counter(round(c['seconds'] / 30) * 0.5 for c in r['partial'])
        repeated = [{'minutes': m, 'count': n} for m, n in rep.most_common() if n >= REPEAT_MIN_COUNT]
        sessions.append({
            'label': _day_label(lot[0]['t'], lot[-1]['t']),
            'first': lot[0]['_time'], 'last': lot[-1]['_time'],
            'logging_sessions': len(split_gaps(lot, SESSION_GAP_S)),
            'full_cycles': len(full),
            'median_cycle_minutes': _fmt_min(statistics.median(c['seconds'] for c in full) / 60) if full else None,
            'other_runs': len(r['partial']),
            'repeated_short_runs': repeated,
            'used_for_headline': r['primary'],
        })

    prim = lot_recs[0]
    lot, full = prim['lot'], prim['full']
    actual = statistics.median(c['seconds'] for c in full) / 60 if full else None
    cyc_spread = ([round(min(c['seconds'] for c in full) / 60, 1), round(max(c['seconds'] for c in full) / 60, 1)]
                  if full else None)

    gaps = []
    for c1, c2 in zip(full, full[1:]):
        g = c2['start_t'] - c1['end_t']
        if 0 <= g <= LOAD_GAP_MAX_S:
            gaps.append(g)
    load_unload = round(statistics.median(gaps) / 60, 1) if gaps else None

    running = [s for s in lot if s.get('machine_state') == STATE_RUNNING and s.get('machine_mode') == MODE_AUTO]
    rpm_on = [s['spindle_speed'] for s in running if (s.get('spindle_speed') or 0) > 0]
    at_prog = None
    if rpm_on and prog_rpm['rpm_values']:
        hit = sum(1 for v in rpm_on
                  if any(abs(v - p) <= p * RPM_MATCH_PCT / 100 for p in prog_rpm['rpm_values']))
        at_prog = round(100 * hit / len(rpm_on), 1)
    spindle = {'programmed_rpm': prog_rpm['rpm_weighted_median'],
               'actual_median_rpm': round(statistics.median(rpm_on)) if rpm_on else None,
               'at_programmed_pct': at_prog,
               'basis': f'programmed = minutes-weighted median S of the setup ops; actual = median RPM '
                        f'while running in AUTO; at_programmed = share of spindle-on running samples '
                        f'within ±{RPM_MATCH_PCT:g}% of one of the setup\'s programmed S values'}

    ov = km._override_stats(running, 'feed_override', 100)
    fo_vals = [s['feed_override'] for s in running
               if s.get('feed_override') is not None and 0 < s['feed_override'] <= 300]
    feed_override = None
    if ov.get('available') and fo_vals:
        share = Counter(round(v) for v in fo_vals)
        held = [v for v, n in share.items() if n >= OVERRIDE_SETTING_MIN_SHARE * len(fo_vals)] or [100]
        feed_override = {'median_pct': round(statistics.median(fo_vals)),
                         'min_pct': min(held), 'max_pct': max(held),
                         'extreme_min_pct': round(min(fo_vals)), 'extreme_max_pct': round(max(fo_vals)),
                         'range_basis': f'min/max = settings held for >= {OVERRIDE_SETTING_MIN_SHARE:.0%} of '
                                        'run time (momentary values while the knob is turned excluded)',
                         'off_default_pct': round(ov['pct_time'], 1),
                         'median_when_changed_pct': (round(ov['median_active'])
                                                     if ov.get('median_active') is not None else None)}

    split = state_split(lot, dt_cap)
    ratio = round(actual / programmed_minutes, 2) if actual and programmed_minutes else None

    bits = [f"Setup {spec['setup']}:"]
    if actual is not None:
        bits.append(f"{actual:.1f} min real cycle vs {programmed_minutes:.1f} programmed "
                    f"({'+' if ratio >= 1 else ''}{round((ratio - 1) * 100)}%), {len(full)} full cycles")
    else:
        bits.append('no full cycle observed')
    rep_runs = sessions[0]['repeated_short_runs']
    if rep_runs:
        r0 = rep_runs[0]
        bits.append(f"plus {r0['count']} runs of a shorter {r0['minutes']:.1f}-min version of the program")
    if spindle['actual_median_rpm']:
        bits.append(f"spindle at programmed S {at_prog:.0f}% of the time" if at_prog is not None else
                    f"spindle median {spindle['actual_median_rpm']} rpm")
    if feed_override:
        bits.append(f"feed override {feed_override['min_pct']}–{feed_override['max_pct']}%, off 100% for "
                    f"{feed_override['off_default_pct']:.0f}% of run time")
    headline = bits[0] + ' ' + '; '.join(bits[1:]) + '.'

    return {**base, 'recorded': True,
            'sessions': sessions,
            'first': samples[0]['_time'], 'last': samples[-1]['_time'],
            'samples': len(samples),
            'full_cycles': len(full),
            'cycle_minutes_range': cyc_spread,
            'actual_machine_minutes': _fmt_min(actual),
            'ratio': ratio,
            'load_unload_median_minutes': load_unload,
            'spindle': spindle,
            'feed_override': feed_override,
            'state_split': split,
            'interventions': {'feed_hold_events': split['hold_events'],
                              'manual_minutes': split['manual_minutes']},
            'headline': headline}


def compute(cfg: dict, raw: dict, program: dict, fetched_at: str) -> dict:
    """program = the run2 batch's 'program' block ({ops[], by_setup[]}) from production_history."""
    km = _km()
    by_setup = {s['setup']: s.get('minutes') for s in program.get('by_setup', [])}
    setups = []
    for spec in cfg['setups']:
        rec = compute_setup(spec, raw.get(spec['setup'], []), by_setup.get(spec['setup']),
                            programmed_for_setup(program.get('ops', []), spec['setup']), km)
        if not rec['recorded'] and spec.get('not_recorded_reason'):
            rec['not_recorded_reason'] = spec['not_recorded_reason']
        setups.append(rec)

    rec = [s for s in setups if s['recorded'] and s['actual_machine_minutes'] is not None]
    lines = []
    if rec:
        act = sum(s['actual_machine_minutes'] for s in rec)
        prog = sum(s['programmed_minutes'] for s in rec)
        names = ', '.join(str(s['setup']) for s in rec)
        lines.append(f"Real machine time per part was {act:.0f} min against {prog:.0f} min programmed "
                     f"for setups {names} ({'+' if act >= prog else ''}{round(100 * (act / prog - 1))}%); "
                     f"every setup ran longer than the programmer's estimate."
                     if all(s['ratio'] and s['ratio'] > 1 for s in rec) else
                     f"Real machine time per part was {act:.0f} min against {prog:.0f} min programmed "
                     f"for setups {names}.")
        per = '; '.join(f"S{s['setup']} {s['actual_machine_minutes']:.1f} vs {s['programmed_minutes']:.1f}"
                        for s in rec)
        lines.append(f"Median full-cycle minutes, real vs programmed: {per}. "
                     f"Setup 3 (finish) is not in the controller log.")
    sp = [s['spindle']['at_programmed_pct'] for s in rec if s['spindle'] and s['spindle']['at_programmed_pct'] is not None]
    fo = [s['feed_override'] for s in rec if s['feed_override']]
    if sp and fo:
        lines.append(f"Spindle held the programmed RPM {min(sp):.0f}–{max(sp):.0f}% of the time; the operator "
                     f"moved the feed knob between {min(f['min_pct'] for f in fo)}% and "
                     f"{max(f['max_pct'] for f in fo)}%, off 100% for "
                     f"{min(f['off_default_pct'] for f in fo):.0f}–{max(f['off_default_pct'] for f in fo):.0f}% "
                     f"of run time.")
    later = [(s['setup'], x) for s in setups if s['recorded'] for x in s['sessions'] if not x['used_for_headline']]
    first_lot = [x for s in setups if s['recorded'] for x in s['sessions'] if x['used_for_headline']]
    if first_lot:
        t0 = min(x['first'] for x in first_lot)
        t1 = max(x['last'] for x in first_lot)
        a = _day_label(datetime.fromisoformat(t0.replace('Z', '+00:00')).timestamp(),
                       datetime.fromisoformat(t1.replace('Z', '+00:00')).timestamp())
        txt = f"Figures are from the {a} run"
        if later:
            ts = lambda v: datetime.fromisoformat(v.replace('Z', '+00:00')).timestamp()
            lab = _day_label(min(ts(x['first']) for _, x in later), max(ts(x['last']) for _, x in later))
            n = sum(x['full_cycles'] for _, x in later)
            txt += (f"; a later {lab} run of setup{'s' if len(later) > 1 else ''} "
                    f"{', '.join(str(k) for k, _ in later)} ({n} more full cycles) is listed separately")
        lines.append(txt + '.')

    return {'available': bool(rec),
            'source': f"InfluxDB cnc_telemetry · {cfg['factory_id']}/{cfg['machine_id']}",
            'fetched_at': fetched_at,
            'parts_inspected': cfg.get('parts_inspected'),
            'setups': setups,
            'summary': {'headline_lines': lines[:4], 'note': _cycles_note(cfg, rec)},
            'method': ('Full cycle = a program run whose start was observed and whose controller cycle '
                       f'time reached >= {int(FULL_CYCLE_FRAC * 100)}% of the programmed time; actual '
                       'minutes = median full cycle of the first lot. State split is over logged time '
                       '(the collector only logs while a program is loaded). cutting_time is always 0 on '
                       'this machine, so no cutting-vs-air split is given.')}


def _cycles_note(cfg: dict, rec: list[dict]) -> str | None:
    parts = cfg.get('parts_inspected')
    if not parts or not rec:
        return None
    n = [s['full_cycles'] for s in rec]
    return (f"The log holds {min(n)}–{max(n)} full cycles per setup in the first run, more than the {parts} "
            f"parts in the inspection report, so the report likely covers a sample of a larger lot. "
            f"Minutes are per cycle (one part per clamping assumed).")


# ── snapshot ─────────────────────────────────────────────────────────────────

def snapshot_path(key: str, batch_id: str) -> Path:
    return SNAPSHOT_DIR / f'{key}_{batch_id}_telemetry.json'


def _program_block(key: str, batch_id: str) -> dict:
    from . import production_history as ph
    for spec in ph.EXTERNAL_BATCHES.get(key, []):
        if spec['id'] != batch_id:
            continue
        b = None
        if spec['root'].exists():
            b = ph._batch_external(spec)
        if b is None:
            p = ph._snapshot_path(key, batch_id)
            if p.exists():
                b = json.loads(p.read_text(encoding='utf-8'))
        if b is not None:
            return b['program']
    raise RuntimeError(f'no programmed values for {key}/{batch_id}')


def refresh(key: str) -> Path:
    cfg = BATCHES[key]
    program = _program_block(key, cfg['batch_id'])
    raw, queries = fetch(cfg)
    fetched_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
    md = compute(cfg, raw, program, fetched_at)
    km = _km()
    out = {'part_key': key, 'batch_id': cfg['batch_id'], 'fetched_at': fetched_at,
           'bucket': km.BUCKET, 'measurement': km.MEASUREMENT,
           'decode': {'machine_state': {'1': 'running', '2': 'hold / interrupted', '0': 'stopped / reset'},
                      'machine_mode': {'2': 'AUTO', '0': 'JOG / MDI'},
                      'cycle_time': 'seconds; resets at cycle start, holds after M30',
                      'cutting_time': 'always 0 on this machine; not used'},
           'queries': queries, 'machine_data': md}
    p = snapshot_path(key, cfg['batch_id'])
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix('.tmp')
    tmp.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding='utf-8')
    tmp.replace(p)
    return p


def machine_data_for(key: str, batch_id: str) -> dict | None:
    """Snapshot-only read for the endpoint (never queries InfluxDB). None = no telemetry registered."""
    cfg = BATCHES.get(key)
    if not cfg or cfg['batch_id'] != batch_id:
        return None
    p = snapshot_path(key, batch_id)
    if not p.exists():
        return {'available': False, 'reason': f'no telemetry snapshot yet ({p.name}); run '
                                              f'python -m demo_modules.telemetry_batch refresh {key}'}

    def _load():
        return json.loads(p.read_text(encoding='utf-8'))['machine_data']
    try:
        return file_cache.memo(f'telemetry:{p}', [p], _load)
    except Exception as e:
        return {'available': False, 'reason': f'snapshot unreadable ({type(e).__name__})'}


if __name__ == '__main__':
    args = sys.argv[1:]
    if len(args) == 2 and args[0] == 'refresh':
        path = refresh(args[1])
        md = json.loads(path.read_text(encoding='utf-8'))['machine_data']
        print(f'wrote {path}')
        for line in md['summary']['headline_lines']:
            print(' -', line)
        for s in md['setups']:
            print(' ', s['headline'])
    else:
        print('usage: python -m demo_modules.telemetry_batch refresh <part_key>   (e.g. motormount)')
        sys.exit(2)
