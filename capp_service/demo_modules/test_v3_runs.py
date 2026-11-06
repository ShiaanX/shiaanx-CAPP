"""
Tests for planner console runs (v3_runs): listing/summary from the REAL run folder (read-only),
path safety, publish validation/limits, and published-over-snapshot preference in /program.
Run from capp_service/:  python -m unittest demo_modules.test_v3_runs -v
"""

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from demo_modules import program, v3_runs

REAL_RUN = 'MOTOR_MOUNT_20261105_102652'
HAVE_RUN = (v3_runs.runtime_root() / REAL_RUN / 'logs' / 'journal.json').exists()


@unittest.skipUnless(HAVE_RUN, 'planner run folder not on this machine')
class RealRun(unittest.TestCase):
    def test_list_runs(self):
        runs = v3_runs.list_runs()
        by = {r['name']: r for r in runs}
        r = by[REAL_RUN]
        self.assertEqual((r['part_key'], r['status'], r['setups_done']), ('motormount', 'finished', 3))
        self.assertTrue(r['usable'])
        self.assertEqual([x['started'] for x in runs], sorted((x['started'] for x in runs), reverse=True))

    def test_summary_matches_known_numbers(self):
        live, _ = v3_runs.summarize_run(REAL_RUN)
        self.assertEqual(len(live['toolpaths']), 27)
        self.assertEqual(live['powermill_cutting_minutes_total'], 291.4)
        self.assertEqual(live['run_minutes'], 81.7)
        self.assertEqual([s['toolpaths'] for s in live['setups']], [18, 6, 3])
        self.assertEqual(live['setups'][0]['vise']['level'], 'VISE_ZMAX')
        self.assertEqual(live['edited_toolpaths'], [])
        self.assertEqual(live['run_name'], REAL_RUN)

    def test_same_as_frozen_motor_mount_decode(self):
        old, _ = program._live_program('motormount')
        new, _ = v3_runs.summarize_run(REAL_RUN)
        self.assertEqual(old['toolpaths'], new['toolpaths'])
        self.assertEqual(old['setups'], new['setups'])

    def test_empty_run_is_not_an_error(self):
        live, notes = v3_runs.summarize_run('MOTOR_MOUNT_20261105_131739')
        if live is None:
            self.assertTrue(notes)

    def test_path_safety(self):
        for bad in ('..', '../x', 'a/b', 'a' + chr(92) + 'b', '', '.hidden', 'C:' + chr(92) + 'x',REAL_RUN + '/..'):
            self.assertIsNone(v3_runs.run_dir(bad), bad)
            live, notes = v3_runs.summarize_run(bad)
            self.assertIsNone(live)


class Reconcile(unittest.TestCase):
    def test_added_and_deleted_toolpaths(self):
        tps = [{'name': 'A_01', 'setup': 1, 'powermill_minutes': 1.0, 'tool': 'T1', 'cutting_minutes': 0.5},
               {'name': 'A_02', 'setup': 1, 'powermill_minutes': 2.0, 'tool': 'T1', 'cutting_minutes': 1.0}]
        sus = [{'setup': 1, 'name': 'S1', 'direction': '+Z', 'workplane': 'WP1'}]
        pm = {'a_01': {'name': 'A_01'}, 'a_new': {'name': 'A_NEW', 'workplane': 'WP1', 'strategy': 's'}}
        notes = []
        edits = v3_runs._reconcile(tps, sus, pm, {'a_new': 4.0}, notes)
        self.assertEqual(sorted(e['change'] for e in edits), ['added in PowerMill', 'deleted in PowerMill'])
        self.assertEqual([t['name'] for t in tps], ['A_01', 'A_NEW'])
        self.assertEqual((sus[0]['toolpaths'], sus[0]['powermill_minutes']), (2, 5.0))
        self.assertTrue(notes)


def _summary():
    return {'toolpaths': [{'name': 'A_01', 'setup': 1}, {'name': 'A_02', 'setup': 1}],
            'setups': [{'setup': 1, 'name': 'S1'}], 'powermill_cutting_minutes_total': 12.5, 'images': [{'x': 1}]}


class Publish(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.dict(os.environ, {'CAPP_PUBLISHED_DIR': self.tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_roundtrip_and_label(self):
        rec = v3_runs.publish('motormount', _summary(), REAL_RUN, 'Siddhant')
        self.assertEqual(rec['run_name'], REAL_RUN)
        got = v3_runs.load_published('motormount')
        self.assertEqual(got['live']['powermill_cutting_minutes_total'], 12.5)
        self.assertEqual(got['live']['images'], [])
        self.assertIn(f'published from planner run {REAL_RUN} on ', v3_runs.source_label(got))
        self.assertTrue(v3_runs.source_label(got).endswith(' by Siddhant'))
        self.assertEqual([p.name for p in Path(self.tmp.name).iterdir()], ['motormount.json'])   # no temp left

    def test_validation(self):
        bad = [
            ('motormount', None, REAL_RUN, 'x'), ('motormount', [], REAL_RUN, 'x'),
            ('motormount', {**_summary(), 'toolpaths': []}, REAL_RUN, 'x'),
            ('motormount', {**_summary(), 'setups': [{'name': 'no index'}]}, REAL_RUN, 'x'),
            ('motormount', {**_summary(), 'powermill_cutting_minutes_total': 'a'}, REAL_RUN, 'x'),
            ('motormount', {**_summary(), 'toolpaths': [{'setup': 1}]}, REAL_RUN, 'x'),
            ('motormount', _summary(), '../evil', 'x'), ('motormount', _summary(), REAL_RUN, '  '),
            ('../evil', _summary(), REAL_RUN, 'x'), (None, _summary(), REAL_RUN, 'x'),
            ('Motor Mount', _summary(), REAL_RUN, 'x'),
        ]
        for args in bad:
            with self.assertRaises(ValueError, msg=str(args)[:80]):
                v3_runs.publish(*args)
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])

    def test_size_limit(self):
        big = _summary()
        big['toolpaths'][0]['blob'] = 'x' * (v3_runs.MAX_PUBLISH_BYTES + 10)
        with self.assertRaises(ValueError):
            v3_runs.publish('motormount', big, REAL_RUN, 'x')
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])

    def test_program_prefers_published_over_snapshot(self):
        before, _ = program.live_program('motormount')
        pub = copy.deepcopy(before)
        pub['powermill_cutting_minutes_total'] = 111.1
        v3_runs.publish('motormount', pub, REAL_RUN, 'Rohit')
        live, _ = program.live_program('motormount')
        self.assertEqual(live['powermill_cutting_minutes_total'], 111.1)
        self.assertIn('published from planner run', live['source_label'])
        self.assertEqual(live['published']['published_by'], 'Rohit')
        # a part without a published run is unaffected
        other, _ = program.live_program('rekise')
        self.assertIsNone(other if other is None else other.get('published'))


if __name__ == '__main__':
    unittest.main()
