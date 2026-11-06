import unittest
import tempfile
from pathlib import Path

from demo_modules import quote, quote_pdf, dfm, v3_cache
from demo_modules.test_demo_modules import FIXTURE_V3

JOBS = Path(__file__).resolve().parent.parent / 'jobs'


def _motor_job():
    for d in sorted(JOBS.glob('*')):
        if (d / 'Motor_Mount.step').exists() and (d / 'v3_analysis.json').exists():
            return d
    return None


class TestLeadTime(unittest.TestCase):
    def test_rows_and_total(self):
        r = quote.build(FIXTURE_V3, Path(tempfile.mkdtemp()), 10, 'aluminium_6061')
        lt = r['lead_time_days']
        self.assertEqual((lt['qc'], lt['dispatch'], lt['qc_dispatch']), (1, 1, 2))
        self.assertEqual(lt['total'], lt['material'] + lt['machining'] + 2)

    @unittest.skipIf(_motor_job() is None, 'no Motor Mount job')
    def test_motor_mount_qty40(self):
        j = _motor_job()
        st, v3 = v3_cache.get(j.name, j)
        if st != 'ready':
            self.skipTest('v3 cache not ready')
        lt = quote.build(v3, j, 40, 'aluminium_6061')['lead_time_days']
        self.assertEqual((lt['machining'], lt['total']), (17, 19))


class TestQuotePdf(unittest.TestCase):
    def test_content(self):
        import fitz
        q = quote.build(FIXTURE_V3, Path(tempfile.mkdtemp()), 10, 'aluminium_6061')
        d = dfm.build(FIXTURE_V3)
        pdf = quote_pdf.build_pdf(customer='Acme', enquiry_number='ENQ-9', part_name='Bracket', qty=10,
                                  material='aluminium_6061', quote=q, dfm=d, prepared_by='X',
                                  edits={'unit_price_inr': 1234.5, 'lead_days': 12, 'validity_days': 15,
                                         'payment_terms': 'Net 30', 'notes': 'Hello'})
        self.assertTrue(pdf.startswith(b'%PDF'))
        t = ''.join(p.get_text() for p in fitz.open(stream=pdf, filetype='pdf')).lower()
        for w in ('inr 1,234.5', 'inr 12,345', '12 working days', '15 days', 'net 30', d['summary']['verdict'].lower()):
            self.assertIn(w, t)
        for w in ('margin', 'v3', 'supplier', 'inv-', 'planner'):
            self.assertNotIn(w, t)
        self.assertEqual(quote_pdf.inr(1234567), 'INR 12,34,567')
        self.assertIsNone(quote_pdf.decode_snapshot('not png'))
