"""Tests for stock_lists: built on tiny fixture workbooks, so they never depend on the real data."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import openpyxl

from demo_modules import stock_lists as S

INV_HEAD = ['SKU', 'Material', 'Grade', 'Shape', 'Size Description', 'Width / Dia (mm)', 'Height (mm)',
            'Thickness / Wall (mm)', 'Length (mm)', 'Unit Weight (kg)', 'Qty Available', 'UoM', 'Condition',
            'Rack Location', 'Availability']
SUP_HEAD = ['Supplier ID', 'Supplier Name', 'Supplier Type (as listed)', 'City', 'State', 'Region', 'Materials',
            'Product Forms (as listed)', 'Grades Listed', 'Certification / Docs (as listed)', 'Min Order (as listed)',
            'Est. Lead Time Min (days)', 'Est. Lead Time Max (days)', 'Lead Time Basis', 'Contact (as listed)',
            'Source URL', 'Data Confidence', 'ShiaanX Verified', 'Last Quote Date', 'Actual Lead Time (days)',
            'ShiaanX Rating (1-5)', 'Notes']
MAP_HEAD = ['Supplier ID', 'Supplier Name', 'Material', 'Grade', 'Shape', 'Confidence', 'Region',
            'Est. Lead Time Min (days)', 'Est. Lead Time Max (days)', 'Evidence (what the listing says)']


def inv_row(sku, grade, shape, size, w, h, t, ln, wt, qty, avail='Available'):
    return [sku, 'Aluminium', grade, shape, size, w, h, t, ln, wt, qty, 'Nos', 'Full Length', 'RA-01', avail]


def sup_row(sid, name, city, lo, hi, actual=None):
    r = [None] * len(SUP_HEAD)
    r[0], r[1], r[3], r[5] = sid, name, city, 'NCR'
    r[11], r[12], r[13] = lo, hi, 'Planning estimate'
    r[19] = actual
    return r


def map_row(sid, name, grade, shape, conf, lo, hi):
    return [sid, name, 'Aluminium', grade, shape, conf, 'NCR', lo, hi, 'listing']


class StockFixture(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.patches = [mock.patch.object(S, 'INVENTORY_XLSX', self.dir / 'inv.xlsx'),
                        mock.patch.object(S, 'SUPPLIERS_XLSX', self.dir / 'sup.xlsx'),
                        mock.patch.object(S, 'PRICES_JSON', self.dir / 'prices.json')]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def write_inventory(self, rows, note='Data | All quantities and locations are dummy values.'):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Inventory'
        ws.append(INV_HEAD)
        for r in rows:
            ws.append(r)
        wb.create_sheet('Notes').append(['Notes', note])
        wb.save(self.dir / 'inv.xlsx')

    def write_suppliers(self, sup_rows, map_rows):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Suppliers'
        ws.append(SUP_HEAD)
        for r in sup_rows:
            ws.append(r)
        wm = wb.create_sheet('Supplier_Grade_Map')
        wm.append(MAP_HEAD)
        for r in map_rows:
            wm.append(r)
        wb.save(self.dir / 'sup.xlsx')


class TestInventory(StockFixture):
    def test_block_yield_and_quantity_check(self):
        # block 200 x 150 x 250 yields 30 billets of 28.5 x 62.3 x 111.8; 40 parts need 2 blocks
        self.write_inventory([inv_row('B1', '6061-T6', 'Block', '200x150x250', 200, 150, None, 250, 20.0, 5)])
        it = S.pick_inventory([62.3, 111.8, 28.5], 'aluminium_6061', 40)
        self.assertEqual((it['id'], it['pieces_per_item'], it['items_needed']), ('B1', 30, 2))
        self.assertIsNone(S.pick_inventory([62.3, 111.8, 28.5], 'aluminium_6061', 500))   # 18 blocks needed, 5 on hand

    def test_thin_plate_cannot_yield_a_thick_billet(self):
        self.write_inventory([inv_row('P1', '6061-T6', 'Plate', '1000x2000x16', 1000, None, 16, 2000, 86.4, 9)])
        self.assertIsNone(S.pick_inventory([62.3, 111.8, 28.5], 'aluminium_6061', 1))

    def test_least_stock_per_billet_wins_and_availability_matters(self):
        self.write_inventory([
            inv_row('BIG', '6061-T6', 'Block', '250x150x400', 250, 150, None, 400, 40.5, 4),
            inv_row('SMALL', '6061-T6', 'Block', '100x120x120', 100, 120, None, 120, 2.0, 4),
            inv_row('RES', '6061-T6', 'Block', '70x120x120', 70, 120, None, 120, 2.8, 4, avail='Reserved'),
        ])
        it = S.pick_inventory([62.3, 111.8, 28.5], 'aluminium_6061', 1)
        self.assertEqual(it['id'], 'SMALL')       # RES (reserved) is skipped; SMALL wastes less than BIG

    def test_grade_must_match(self):
        self.write_inventory([inv_row('B7', '7075-T651', 'Block', '200x150x250', 200, 150, None, 250, 20.0, 5)])
        self.assertIsNone(S.pick_inventory([62.3, 111.8, 28.5], 'aluminium_6061', 1))
        self.assertEqual(S.pick_inventory([62.3, 111.8, 28.5], 'aluminium_7075', 1)['id'], 'B7')

    def test_round_bar_needs_the_diagonal(self):
        self.write_inventory([inv_row('R1', '6061-T6', 'Round Bar', 'D60', 60, None, None, 1000, 7.6, 3),
                              inv_row('R2', '6061-T6', 'Round Bar', 'D80', 80, None, None, 1000, 13.5, 3)])
        it = S.pick_inventory([62.3, 111.8, 28.5], 'aluminium_6061', 1)      # diag(62.3, 28.5) = 68.5 -> D80
        self.assertEqual(it['id'], 'R2')

    def test_dummy_note_flags_sample_and_clears(self):
        self.write_inventory([inv_row('B1', '6061-T6', 'Block', '200x150x250', 200, 150, None, 250, 20.0, 5)])
        self.assertTrue(S.load_inventory()['items'][0]['sample'])
        self.write_inventory([inv_row('B1', '6061-T6', 'Block', '200x150x250', 200, 150, None, 250, 20.0, 5)],
                             note='Data | Counted on 2026-11-10.')
        self.assertFalse(S.load_inventory()['items'][0]['sample'])


class TestSuppliers(StockFixture):
    def setUp(self):
        super().setUp()
        self.sups = [sup_row('S1', 'Slow High', 'Delhi', 7, 30), sup_row('S2', 'Fast Medium', 'Noida', 1, 3),
                     sup_row('S3', 'Fast High', 'Noida', 2, 5), sup_row('S4', 'Round Only', 'Pune', 1, 2)]

    def test_confidence_then_lead_and_shape_preference(self):
        self.write_suppliers(self.sups, [
            map_row('S1', 'Slow High', '6061-T6', 'Plate', 'High', 7, 30),
            map_row('S2', 'Fast Medium', '6061-T6', 'Plate', 'Medium', 1, 3),
            map_row('S3', 'Fast High', '6061-T6', 'Plate', 'High', 2, 5),
            map_row('S4', 'Round Only', '6061-T6', 'Round Bar', 'High', 1, 2)])
        o = S.pick_supplier('aluminium_6061')
        self.assertEqual((o['name'], o['shape'], o['confidence']), ('Fast High', 'Plate', 'High'))   # Plate before Round Bar
        self.assertEqual((o['lead_range'], o['lead_days'], o['lead_basis']), ([2, 5], 5, 'planning estimate'))  # upper end
        self.assertEqual(S.pick_supplier('aluminium_6061', basis='min')['lead_days'], 2)
        self.assertEqual([a['name'] for a in o['alternatives']], ['Slow High', 'Fast Medium'])

    def test_actual_lead_time_beats_the_estimate(self):
        sups = [sup_row('S3', 'Fast High', 'Noida', 2, 5, actual=3)]
        self.write_suppliers(sups, [map_row('S3', 'Fast High', '6061-T6', 'Plate', 'High', 2, 5)])
        o = S.pick_supplier('aluminium_6061')
        self.assertEqual((o['lead_days'], o['lead_basis']), (3, 'actual'))

    def test_falls_back_to_another_shape_and_unknown_grade_is_none(self):
        self.write_suppliers(self.sups, [map_row('S4', 'Round Only', '6082-T6', 'Round Bar', 'High', 1, 2)])
        self.assertEqual(S.pick_supplier('aluminium_6082')['shape'], 'Round Bar')
        self.assertIsNone(S.pick_supplier('aluminium_7075'))
        self.assertIsNone(S.pick_supplier('copper_c11000'))


class TestPricesAndMissingFiles(StockFixture):
    def test_prices(self):
        (self.dir / 'prices.json').write_text(json.dumps({'sample': True, 'prices_inr_per_kg': {'aluminium_6061': 440}}))
        self.assertEqual(S.price_per_kg('aluminium_6061')[:2], (440.0, True))
        self.assertEqual(S.price_per_kg('aluminium')[0], 440.0)
        self.assertIsNone(S.price_per_kg('aluminium_7075')[0])

    def test_missing_files_do_not_crash(self):
        self.assertEqual(S.load_inventory()['items'], [])
        self.assertIsNone(S.pick_inventory([10, 10, 10], 'aluminium_6061', 1))
        self.assertIsNone(S.pick_supplier('aluminium_6061'))


class TestRealFiles(unittest.TestCase):
    """The shipped spreadsheets load and cover the grades the quote offers."""

    def test_real_files_load(self):
        d = S.describe_sources()
        self.assertGreater(d['inventory']['items'], 50)
        self.assertGreater(d['suppliers']['suppliers'], 10)
        for g in ('aluminium_6061', 'aluminium_6082', 'aluminium_7075'):
            self.assertIsNotNone(S.pick_supplier(g), g)
            self.assertIsNotNone(S.price_per_kg(g)[0], g)


if __name__ == '__main__':
    unittest.main()
