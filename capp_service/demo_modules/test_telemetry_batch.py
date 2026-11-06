"""
Tests for telemetry_batch.py: the cycle / state / override logic on synthetic Sinumerik samples,
and the snapshot-only serving path (no InfluxDB). Run from capp_service/:
    python -m unittest demo_modules.test_telemetry_batch -v
"""

import json
import time
import unittest
from pathlib import Path
from unittest import mock

from demo_modules import production_history as ph, telemetry_batch as tb

T0 = 1781000000.0  # an arbitrary UTC epoch


def _s(t, st=1, md=2, cyc=0.0, rpm=2500.0, fo=100, alarm=0, tool=13):
    return {'_time': tb._iso(t), 't': t, 'machine_state': st, 'machine_mode': md, 'cycle_time': cyc,
            'spindle_speed': rpm, 'feed_override': fo, 'spindle_override': 100,
            'alarm_active': alarm, 'tool_number': tool}


def _cycle(t, seconds, fo=100, rpm=2500.0):
    """One program run sampled every 2 s: cycle_time climbs to `seconds`, then held while idle."""
    out = [_s(t + k, cyc=float(k), fo=fo, rpm=rpm) for k in range(0, int(seconds) + 1, 2)]
    end = t + seconds
    out += [_s(end + k, st=0, cyc=float(seconds), rpm=0) for k in range(2, 120, 2)]  # 2 min load/unload
    return out, end + 120


def _batch(n, seconds, t=T0, fo=100):
    out = [_s(t - 2, st=0, cyc=500.0, rpm=0)]  # held value from before the window: not a cycle
    for _ in range(n):
        c, t = _cycle(t, seconds, fo=fo)
        out += c
    return out


SPEC = {'setup': 4, 'program_name': 'X.', 'windows': []}
PROG = {'rpm_values': [2500.0, 900.0], 'rpm_weighted_median': 2500.0}


class CycleLogic(unittest.TestCase):
    def test_cycles_counted_and_held_value_ignored(self):
        cyc = tb.find_cycles(_batch(3, 420))
        self.assertEqual(len(cyc), 3)
        self.assertTrue(all(abs(c['seconds'] - 420) <= 2 for c in cyc))

    def test_short_runs_ignored(self):
        self.assertEqual(tb.find_cycles(_batch(2, 30)), [])

    def test_setup_metrics(self):
        km = tb._km()
        rec = tb.compute_setup(SPEC, _batch(5, 420), 6.0, PROG, km)
        self.assertTrue(rec['recorded'])
        self.assertEqual(rec['full_cycles'], 5)
        self.assertAlmostEqual(rec['actual_machine_minutes'], 7.0, delta=0.1)
        self.assertAlmostEqual(rec['ratio'], 1.17, delta=0.02)
        self.assertAlmostEqual(rec['load_unload_median_minutes'], 2.0, delta=0.1)
        self.assertEqual(rec['spindle']['actual_median_rpm'], 2500)
        self.assertEqual(rec['spindle']['at_programmed_pct'], 100.0)
        self.assertEqual(rec['feed_override']['median_pct'], 100)
        sp = rec['state_split']
        self.assertIsNone(sp['cutting_pct'])          # cutting_time is 0 on this machine: not guessed
        self.assertAlmostEqual(sp['running_pct'] + sp['hold_pct'] + sp['manual_pct'] + sp['idle_pct'],
                               100, delta=0.3)
        self.assertGreater(sp['running_pct'], sp['idle_pct'])

    def test_partial_cycles_not_full(self):
        rec = tb.compute_setup(SPEC, _batch(4, 120), 6.0, PROG, tb._km())   # 2 min vs 6 programmed
        self.assertEqual(rec['full_cycles'], 0)
        self.assertIsNone(rec['actual_machine_minutes'])

    def test_feed_override_transients_excluded_from_range(self):
        s = _batch(3, 420, fo=90)
        s[5]['feed_override'] = 3                     # one sample while the knob is being turned
        rec = tb.compute_setup(SPEC, s, 6.0, PROG, tb._km())
        fo = rec['feed_override']
        self.assertEqual(fo['min_pct'], 90)
        self.assertEqual(fo['extreme_min_pct'], 3)

    def test_later_lot_kept_separate(self):
        s = _batch(3, 420) + _batch(2, 480, t=T0 + 20 * 86400)
        rec = tb.compute_setup(SPEC, s, 6.0, PROG, tb._km())
        self.assertEqual(len(rec['sessions']), 2)
        self.assertTrue(rec['sessions'][0]['used_for_headline'])
        self.assertFalse(rec['sessions'][1]['used_for_headline'])
        self.assertAlmostEqual(rec['actual_machine_minutes'], 7.0, delta=0.1)   # first lot only

    def test_unrecorded_setup(self):
        rec = tb.compute_setup({'setup': 3, 'program_name': None, 'windows': []}, [], 3.5, PROG, tb._km())
        self.assertFalse(rec['recorded'])
        self.assertIn('not recorded', rec['headline'])


class Serving(unittest.TestCase):
    def test_snapshot_shape(self):
        p = tb.snapshot_path('motormount', 'run2')
        self.assertTrue(p.exists(), 'run: python -m demo_modules.telemetry_batch refresh motormount')
        snap = json.loads(p.read_text(encoding='utf-8'))
        self.assertTrue(snap['queries'] and all('flux' in q for q in snap['queries']))
        md = snap['machine_data']
        self.assertTrue(md['available'])
        self.assertTrue(md['fetched_at'])
        self.assertIn('ts/jyotiVMC', md['source'])
        self.assertTrue(3 <= len(md['summary']['headline_lines']) <= 4)
        by = {s['setup']: s for s in md['setups']}
        self.assertEqual(sorted(by), [1, 2, 3, 4])
        self.assertFalse(by[3]['recorded'])
        for k in (1, 2, 4):
            s = by[k]
            self.assertTrue(s['recorded'])
            for f in ('programmed_minutes', 'actual_machine_minutes', 'ratio', 'spindle',
                      'feed_override', 'state_split', 'headline', 'first', 'last', 'sessions'):
                self.assertIn(f, s)
            self.assertGreater(s['actual_machine_minutes'], 0)

    def test_production_history_never_queries_influx(self):
        km = tb._km()
        with mock.patch.object(km, 'query', side_effect=AssertionError('influx hit')), \
                mock.patch.object(km, 'get_session', side_effect=AssertionError('influx hit')):
            t = time.time()
            out = ph.build_for_key('motormount')
            self.assertLess(time.time() - t, 5)
        run2 = next(b for b in out['batches'] if b['id'] == 'run2')
        self.assertTrue(run2['machine_data']['available'])
        run1 = [b for b in out['batches'] if b['id'] == 'run1']
        self.assertTrue(all('machine_data' not in b for b in run1))

    def test_missing_snapshot_is_unavailable_not_error(self):
        with mock.patch.object(tb, 'snapshot_path', return_value=Path('Z:/nope/x.json')):
            md = tb.machine_data_for('motormount', 'run2')
        self.assertFalse(md['available'])
        self.assertIsNone(tb.machine_data_for('rekise', 'run2'))


if __name__ == '__main__':
    unittest.main()
