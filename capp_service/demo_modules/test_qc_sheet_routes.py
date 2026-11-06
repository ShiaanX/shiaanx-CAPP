"""python -m unittest demo_modules.test_qc_sheet_routes   (from capp_service/)"""
import unittest

from demo_modules import qc_sheet


class QcSheet(unittest.TestCase):
    def test_find(self):
        p = qc_sheet.find('MOTOR_MOUNT')
        self.assertIsNotNone(p)
        self.assertEqual(p.suffix, '.xlsx')
        self.assertIsNone(qc_sheet.find('no such part'))
        self.assertIsNone(qc_sheet.find('../../main'))
        self.assertIsNone(qc_sheet.find(''))

    def test_routes(self):
        from fastapi.testclient import TestClient
        import main
        c = TestClient(main.app)
        self.assertTrue(c.get('/parts/motormount/has-qc-sheet').json()['available'])
        r = c.get('/parts/Motor Mount/qc-sheet')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content[:2], b'PK')
        n = c.get('/parts/nothing/qc-sheet')
        self.assertEqual(n.status_code, 404)
        self.assertEqual(n.json()['status'], 'none')
        self.assertFalse(c.get('/parts/nothing/has-qc-sheet').json()['available'])
        self.assertEqual(c.get('/parts/..%2F..%2Fmain/qc-sheet').status_code, 404)


if __name__ == '__main__':
    unittest.main()
