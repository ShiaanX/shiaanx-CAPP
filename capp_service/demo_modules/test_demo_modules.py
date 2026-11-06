"""
Unit tests for the demo modules against a HAND-WRITTEN v3 fixture (test data only,
never served). Run from capp_service/:
    python -m unittest demo_modules.test_demo_modules -v
"""

import tempfile
import unittest
from pathlib import Path

from demo_modules import dfm, dfm_geometry, quote, part_data

FIXTURE_V3 = {
    'source': 'v3',
    'billet_mm': [60.0, 110.0, 26.0],
    'part_bbox_mm': [55.3, 104.8, 21.5],
    'part_volume_mm3': 16979.3,
    'removal_volume_mm3': 154620.7,
    'directions': [
        {'dir': '+Z', 'workplane': 'top', 'machinable_mm3': 120000.0, 'clamp_area_mm2': 3194.1, 'recommended': True},
        {'dir': '-Z', 'workplane': 'bottom', 'machinable_mm3': 30000.0, 'clamp_area_mm2': 1857.6, 'recommended': True},
        {'dir': '+X', 'workplane': 'side', 'machinable_mm3': 4000.0, 'clamp_area_mm2': None, 'recommended': False},
    ],
    'unreachable_mm3': 12.5,
    'setups_needed': 4,
    'holes': [
        {'dia_mm': 3.2, 'depth_mm': 5.0, 'dir': '+Z', 'drill': 'DRILL_3.2'},
        {'dia_mm': 2.5, 'depth_mm': 14.0, 'dir': '+Z', 'drill': 'DRILL_2.5'},
        {'dia_mm': 0.8, 'depth_mm': 2.0, 'dir': '-Z', 'drill': None},
    ],
    'plan': {
        'tools': [{'tool': 'EM12', 'dia_mm': 12, 'minutes': 40.0, 'role': 'rough'},
                  {'tool': 'EM2', 'dia_mm': 2, 'minutes': 25.0, 'role': 'finish'}],
        'setups': [{'dir': '+Z', 'minutes': 50.0, 'cutting_minutes': 5.0, 'tool_change_minutes': 45.0},
                   {'dir': '-Z', 'minutes': 15.0, 'cutting_minutes': 0.0, 'tool_change_minutes': 15.0}],
        'total_minutes': 65.0,
        'tool_changes': 4,
    },
    'forced_small_tools': [{'tool': 'EM2', 'reason': 'internal corner radius 1.0 mm'}],
    'warnings': ['test warning'],
    'runtime_s': 1.0,
}


class TestDfm(unittest.TestCase):
    def test_findings(self):
        r = dfm.build(FIXTURE_V3)
        sev = {f['title']: f['severity'] for f in r['findings']}
        self.assertEqual(r['setups_needed'], 4)
        self.assertEqual(sev['4 setups needed'], 'warn')
        self.assertIn('12 mm³ hard to reach', sev)          # 12.5 < 100 and < 1% of removal
        self.assertEqual(sev['Deep hole Ø2.5 × 14 mm (L/D 5.6)'], 'warn')
        self.assertEqual(sev['Micro hole Ø0.8 mm'], 'warn')
        self.assertTrue(any(t.startswith('Small tool forced: EM2') for t in sev))
        self.assertEqual(r['findings'][0]['severity'] in ('block', 'warn'), True)

    def test_block_on_large_unreachable(self):
        r = dfm.build({**FIXTURE_V3, 'unreachable_mm3': 5000.0})
        self.assertEqual(r['summary']['counts']['block'], 1)

    def test_nulls_tolerated(self):
        r = dfm.build({k: None for k in FIXTURE_V3})
        self.assertEqual(r['findings'], [])


def _plane(i, n, c, a=100.0, nw=1, bb=None):
    return {'i': i, 't': 'plane', 'n': n, 'c': c, 'a': a, 'nw': nw, 'bb': bb or [0, 0, 0, 1, 1, 1]}


def _cyl(i, r, ax, loc, span, ext, cc=True, a=10.0):
    return {'i': i, 't': 'cylinder', 'r': r, 'ax': ax, 'loc': loc, 'span': span, 'ext': ext, 'cc': cc,
            'c': loc, 'a': a, 'nw': 2, 'bb': [0, 0, 0, 1, 1, 1]}


# Hand-written face facts: 0 top face (+Z), 1-2 a flat-bottom Ø3 x 20 hole,
# 3 a R1.3 x 12 deep vertical pocket corner, 4/5 walls with a sharp concave Z edge,
# 6/7 a 0.4 mm thin wall, 8 a 30° tilted face.
FIXTURE_FACTS = {
    'face_count': 9,
    'faces': [
        _plane(0, [0, 0, 1], [0, 0, 20], a=1000.0, nw=3),
        _cyl(1, 1.5, [0, 0, 1], [0, 0, 0], 360.0, [0.0, 20.0]),
        _plane(2, [0, 0, 1], [0, 0, 0], a=7.07),
        _cyl(3, 1.3, [0, 0, 1], [10, 10, 0], 90.0, [8.0, 20.0]),
        _plane(4, [1, 0, 0], [20, 5, 15]),
        _plane(5, [0, 1, 0], [25, 0, 15]),
        _plane(6, [1, 0, 0], [40, 0, 10]),
        _plane(7, [-1, 0, 0], [39.6, 0, 10]),
        _plane(8, [0.5, 0, 0.866025], [50, 0, 10], a=50.0),
    ],
    'edges': [
        {'f': [0, 1], 'kind': 'circle', 'len': 9.4, 'conv': 'convex', 'ang': 90.0, 'n': [[0, 0, 1], [1, 0, 0]]},
        {'f': [1, 2], 'kind': 'circle', 'len': 9.4, 'conv': 'concave', 'ang': 90.0, 'n': [[1, 0, 0], [0, 0, 1]]},
        {'f': [4, 5], 'kind': 'line', 'len': 10.0, 'dir': [0, 0, 1], 'conv': 'concave', 'ang': 90.0,
         'n': [[1, 0, 0], [0, 1, 0]]},
        {'f': [0, 8], 'kind': 'line', 'len': 20.0, 'dir': [0, 1, 0], 'conv': 'convex', 'ang': 30.0,
         'n': [[0, 0, 1], [0.5, 0, 0.866025]]},
        {'f': [6, 8], 'kind': 'line', 'len': 20.0, 'dir': [0, 1, 0], 'conv': 'concave', 'ang': 60.0,
         'n': [[1, 0, 0], [0.5, 0, 0.866025]]},
    ],
    'thin_wall_pairs': [{'faces': [6, 7], 'thickness': 0.4, 'overlap_frac': 1.0, 'overlap_area_mm2': 40.0}],
}


class TestDfmGeometry(unittest.TestCase):
    def setUp(self):
        v3 = {**FIXTURE_V3, 'plan': {**FIXTURE_V3['plan'], 'setups': [{'dir': '+Z'}, {'dir': '-Z'}]}, 'holes': []}
        self.cats = {c['id']: c for c in dfm_geometry.categories(FIXTURE_FACTS, v3)}

    def test_contract_shape(self):
        for c in self.cats.values():
            self.assertTrue({'id', 'label', 'severity', 'color', 'items', 'why'} <= set(c))
            self.assertRegex(c['color'], r'^#[0-9A-F]{6}$')
            self.assertTrue(c['items'])
            for it in c['items']:
                self.assertTrue({'id', 'label', 'detail', 'measured', 'expected', 'face_indices', 'centroid_mm'} <= set(it))

    def test_flat_bottom_and_deep_hole(self):
        fb = self.cats['flat_bottom_hole']['items'][0]
        self.assertEqual(fb['face_indices'], [1, 2])
        deep = self.cats['deep_hole']['items'][0]
        self.assertEqual(deep['severity'], 'warn')             # L/D 20 / 3 = 6.7: 5 < 6.7 <= 10
        self.assertAlmostEqual(deep['measured']['depth_to_dia'], 6.67, places=2)

    def test_internal_corners(self):
        items = self.cats['small_internal_corner']['items']
        sharp = [it for it in items if it['measured']['radius_mm'] == 0.0]
        self.assertEqual(sharp[0]['face_indices'], [4, 5])
        self.assertEqual(sharp[0]['severity'], 'block')
        r13 = [it for it in items if it['measured']['radius_mm'] == 1.3][0]
        self.assertEqual(r13['expected']['min_radius_mm'], 1.5)  # 12 mm deep / (2 x L/D 4)
        self.assertEqual(r13['label'], 'Internal corner (1.50, 1.30)')
        ns = self.cats['non_standard_radius']['items'][0]
        self.assertEqual(ns['expected']['nearest_standard_radius_mm'], 1.5)

    def test_thin_wall_and_tilted_face(self):
        tw = self.cats['thin_wall']['items'][0]
        self.assertEqual((tw['severity'], tw['face_indices']), ('block', [6, 7]))
        tilt = self.cats['non_perpendicular_face']['items'][0]
        self.assertEqual(tilt['face_indices'], [8])
        self.assertAlmostEqual(tilt['measured']['angle_from_axis_deg'], 30.0, places=1)

    def test_part_level_v3_categories(self):
        self.assertEqual(self.cats['small_tool_region']['items'][0]['face_indices'], [])

    def test_build_merges_categories(self):
        r = dfm.build(FIXTURE_V3, FIXTURE_FACTS)
        self.assertEqual(r['face_count'], 9)
        self.assertTrue(r['categories'])
        self.assertIn('face_level_counts', r['summary'])
        self.assertIn('findings', r)                           # old contract kept


class TestDfmGeometryStep(unittest.TestCase):
    """Real-STEP regression on RKSE-004-057 (needs pythonocc; skipped otherwise)."""
    STEP = part_data.PARTS_ROOT / 'Al extrusion mount (Rekise)' / 'RKSE-004-057.stp'

    def test_rkse(self):
        try:
            import OCC  # noqa: F401
        except ImportError:
            self.skipTest('pythonocc not installed')
        if not self.STEP.exists():
            self.skipTest('part STEP not present')
        facts = dfm_geometry.extract(self.STEP)
        self.assertEqual(facts['face_count'], 71)               # = occt-import-js brep_faces count
        cats = {c['id']: c for c in dfm_geometry.categories(facts, None)}
        self.assertIn('chamfer', cats)
        for c in cats.values():
            for it in c['items']:
                self.assertTrue(all(0 <= i < 71 for i in it['face_indices']))


class TestQuote(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_math(self):
        r = quote.build(FIXTURE_V3, self.tmp, 10, 'aluminium_6061')
        c = r['cost']
        # v3 total 65 min = 5 min cutting + 4 changes x 15 min (manual); shop ATC = 15 s per change
        self.assertAlmostEqual(r['machining']['total_minutes'], 5 + 4 * 15 / 60, places=2)
        self.assertEqual(r['machining']['v3_total_minutes'], 65.0)
        self.assertAlmostEqual(c['machining_inr'], round((5 + 1) / 60 * 700, 2), places=2)
        self.assertEqual(r['setup_minutes'], 4 * 30)
        self.assertAlmostEqual(c['setup_inr'], 120 / 60 * 700 / 10, places=2)
        self.assertAlmostEqual(c['unit_price_inr'], round(c['subtotal_inr'] * 1.25, 2), places=1)
        self.assertEqual(r['material']['required_stock_mm'], [63.0, 113.0, 29.0])
        # 29 mm thick blank does not fit the 25 mm plate -> 40 mm plate
        self.assertTrue(r['material']['in_stock'])
        self.assertEqual(r['material']['inventory_item']['id'], 'INV-AL6061-PL-40')
        self.assertEqual(r['lead_time_days']['material'], 0)

    def test_no_split_falls_back_to_v3_total(self):
        plan = {**FIXTURE_V3['plan'], 'setups': [{'dir': '+Z', 'minutes': 65.0}]}
        r = quote.build({**FIXTURE_V3, 'plan': plan}, self.tmp, 1, 'aluminium_6061')
        self.assertEqual(r['machining']['total_minutes'], 65.0)
        self.assertEqual(r['machining']['tool_change_basis'], 'v3_total')

    def test_supplier_path(self):
        r = quote.build(FIXTURE_V3, self.tmp, 1, 'aluminium_7075')
        self.assertFalse(r['material']['in_stock'])
        self.assertIsNotNone(r['material']['supplier'])
        self.assertEqual(r['lead_time_days']['material'], r['material']['supplier']['lead_days'])

    def test_grade_aliases(self):
        self.assertEqual(quote._grade_key('aluminium'), 'aluminium_6061')
        self.assertEqual(quote._grade_key('Al 7075'), 'aluminium_7075')


class TestPartData(unittest.TestCase):
    def test_mapping(self):
        for name, folder in (('MOTOR_MOUNT.step', 'Motor Mount'), ('motor mount.step', 'Motor Mount'),
                             ('RKSE-004-057.step', 'Al extrusion mount (Rekise)')):
            d = Path(tempfile.mkdtemp())
            (d / name).write_text('x')
            self.assertEqual(part_data.find_part_dir(d).name, folder)

    def test_unknown_part(self):
        d = Path(tempfile.mkdtemp())
        (d / 'SOMETHING_ELSE.step').write_text('x')
        self.assertIsNone(part_data.find_part_dir(d))


if __name__ == '__main__':
    unittest.main()
