"""
Tests for GET /jobs/{id}/program (+ approve, image) and production history, against the REAL job
folders, the live-run backup and the shop files (no fixtures). Run from capp_service/:
    python -m unittest demo_modules.test_program_history -v
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from demo_modules import part_data, program, production_history as ph, v3_cache

SERVICE = Path(__file__).resolve().parent.parent
JOBS = SERVICE / 'jobs'


def _job_for(fname):
    for d in sorted(JOBS.iterdir()):
        m = d / 'job.json'
        if m.exists() and (d / 'v3_analysis.json').exists():
            try:
                if json.loads(m.read_text(encoding='utf-8')).get('original_filename') == fname:
                    return d
            except Exception:
                pass
    return None


MM_JOB = _job_for('MOTOR MOUNT.step')
RK_JOB = _job_for('RKSE-004-057.stp')
LIVE = program.LIVE_RUNS['motormount']['folder'].exists()


@unittest.skipIf(MM_JOB is None, 'no Motor Mount job with a v3 cache')
class MotorMountProgram(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        state, v3 = v3_cache.get(MM_JOB.name, MM_JOB)
        cls.r = program.build(MM_JOB, state, v3)

    def test_plan(self):
        p = self.r['plan']
        self.assertEqual(self.r['status'], 'ok')
        self.assertEqual([s['dir'] for s in p['setups']], ['+Z', '-Z', '-Y'])
        self.assertEqual(p['tool_changes'], 12)
        self.assertAlmostEqual(p['cycle_minutes_atc'], 252.6, places=1)
        self.assertTrue(p['tools'] and all('role' in t for t in p['tools']))

    @unittest.skipUnless(LIVE, 'live-run backup not present')
    def test_live_program(self):
        lp = self.r['live_program']
        self.assertTrue(lp['available'])
        self.assertEqual(len(lp['toolpaths']), 27)
        self.assertEqual([s['direction'] for s in lp['setups']], ['+Z', '-Z', '-Y'])
        self.assertEqual([s['powermill_minutes'] for s in lp['setups']], [213.0, 57.5, 20.9])
        self.assertAlmostEqual(lp['powermill_cutting_minutes_total'], 291.4, places=1)
        self.assertAlmostEqual(lp['run_minutes'], 82, delta=0.5)
        self.assertTrue(all(t['tool'] and t['powermill_minutes'] is not None for t in lp['toolpaths']))
        self.assertTrue(all(s['vise']['jaw_gap_mm'] for s in lp['setups']))
        # PowerMill TotalTime agrees with the event stream -> no mismatch notes
        self.assertFalse([n for n in self.r['notes'] if 'TotalTime' in n])


@unittest.skipIf(RK_JOB is None, 'no Rekise job with a v3 cache')
class RekiseProgram(unittest.TestCase):
    def test_no_live_run(self):
        state, v3 = v3_cache.get(RK_JOB.name, RK_JOB)
        r = program.build(RK_JOB, state, v3)
        self.assertIsNone(r['live_program'])
        self.assertTrue(any('No live PowerMill run' in n for n in r['notes']))

    def test_history_empty(self):
        r = ph.build(part_data.find_part_dir(RK_JOB), 'RKSE-004-057')
        self.assertEqual(r['batches'], [])
        self.assertEqual(ph.build_for_key('no-such-part')['batches'], [])


class ProgramHelpers(unittest.TestCase):
    def test_image_path_blocks_traversal(self):
        self.assertIsNone(program.image_path('motormount', '../live_run.log'))
        self.assertIsNone(program.image_path('motormount', 'live_run.log'))   # not an image
        self.assertIsNone(program.image_path('rkse004057', 'x.png'))

    def test_approval_roundtrip(self):
        d = Path(tempfile.mkdtemp())
        self.assertIsNone(program.load_approval(d))
        rec = program.approve(d, ' Siddhant ')
        self.assertEqual(rec['by'], 'Siddhant')
        self.assertTrue(rec['at'])
        self.assertEqual(program.load_approval(d), rec)


def _dim(sl, nominal, vals, notes=None):
    tol = 0.1 if nominal is not None else None
    return {'label': str(sl), 'sl': sl, 'nominal': nominal, 'tol_plus': tol, 'tol_minus': tol,
            'instrument': None, 'remark': None, 'readings': {'P1': vals} if vals else {}, 'notes': notes or {}}


class History(unittest.TestCase):
    def test_grading_rules(self):
        g = ph.grade([_dim(1, 10.0, [10.05]), _dim(2, 10.0, [9.92]), _dim(3, 10.0, [10.11]),
                      _dim(4, None, [], {'P1': 'Not Found'})])
        self.assertEqual([p['verdict'] for p in g['per_dimension']], ['in', 'close', 'out', 'checked'])
        self.assertEqual((g['dimensions'], g['in_tol'], g['close'], g['out']), (3, 1, 1, 1))

    def test_motor_mount(self):
        r = ph.build_for_key('Motor Mount')
        ids = {b['id']: b for b in r['batches']}
        b1 = ids['run1']
        self.assertEqual((b1['setups'], b1['parts_made'], len(b1['program']['ops'])), (3, 2, 20))
        self.assertEqual(b1['qc']['dimensions'], 13)
        self.assertTrue(b1['defects_link'].endswith('batch=run1'))
        b2 = ids['run2']
        self.assertEqual((b2['setups'], b2['parts_made']), (4, 9))
        self.assertAlmostEqual(b2['program']['total_minutes'], 69.8, places=1)
        self.assertEqual(b2['qc']['dimensions'], 12)
        for b in r['batches']:
            q = b['qc']
            self.assertEqual(q['in_tol'] + q['close'] + q['out'], q['dimensions'])
            self.assertTrue(b['sources'])

    def test_snapshot_fallback(self):
        if not ph._snapshot_path('motormount', 'run2').exists():
            self.skipTest('no snapshot written')
        spec = dict(ph.EXTERNAL_BATCHES['motormount'][0], root=Path(r'Z:\definitely\missing'))
        with mock.patch.dict(ph.EXTERNAL_BATCHES, {'motormount': [spec]}):
            r = ph.build_for_key('motormount')
        b2 = [b for b in r['batches'] if b['id'] == 'run2'][0]
        self.assertTrue(b2['snapshot'])
        self.assertAlmostEqual(b2['program']['total_minutes'], 69.8, places=1)


@unittest.skipIf(MM_JOB is None or RK_JOB is None, 'jobs missing')
class Routes(unittest.TestCase):
    def test_routes(self):
        from fastapi.testclient import TestClient
        import main
        c = TestClient(main.app)
        r = c.get(f'/jobs/{MM_JOB.name}/program')
        self.assertEqual(r.status_code, 200)
        self.assertAlmostEqual(r.json()['plan']['cycle_minutes_atc'], 252.6, places=1)
        self.assertEqual(c.get(f'/jobs/{MM_JOB.name}/program/image/..%2F..%2Fmain.py').status_code, 404)
        self.assertIsNone(c.get(f'/jobs/{RK_JOB.name}/program').json()['live_program'])
        self.assertEqual(len(c.get('/parts/motormount/production-history').json()['batches']), 2)
        self.assertEqual(c.get(f'/jobs/{RK_JOB.name}/production-history').json()['batches'], [])
        self.assertEqual(len(c.get(f'/jobs/{MM_JOB.name}/production-history').json()['batches']), 2)


if __name__ == '__main__':
    unittest.main()
