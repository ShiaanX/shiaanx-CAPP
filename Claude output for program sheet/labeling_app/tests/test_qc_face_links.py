from __future__ import annotations

from io import BytesIO
from pathlib import Path
import sys
import unittest

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_app.qc_sheet import apply_face_links, parse_face_links, parse_qc_results, parse_qc_sheet  # noqa: E402


def make_sheet(with_links: bool, sha: str = "abc", total: int = 100) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["SL No.", "Description", "TOL+", "TOL-", "Instrument", "Observation", None, "Remark"])
    ws.append([1, "Ø10", 0.1, 0.1, "caliper", 10.02, None, "OK"])
    ws.append([2, 25, 0.2, 0.2, "caliper", 25.5, None, "OK"])
    if with_links:
        fl = wb.create_sheet("Face links")
        fl.append(["STEP sha256:", sha])
        fl.append(["Total faces:", total])
        fl.append(["Balloon", "Faces A", "Faces B", "Dim type", "Notes"])
        fl.append([1, "5,6", "", "diameter", "bore"])
        fl.append([2, "7", "9", "linear", "width"])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


class FaceLinkTests(unittest.TestCase):
    def test_plain_sheet_has_no_links_and_is_unchanged(self):
        data = make_sheet(False)
        self.assertEqual(parse_face_links(data)["links"], {})
        rows = parse_qc_sheet(data)
        self.assertEqual([r["balloon"] for r in rows], [1, 2])
        self.assertNotIn("faces_a", rows[0])

    def test_links_sheet_does_not_disturb_results_parsing(self):
        data = make_sheet(True)
        self.assertEqual(len(parse_qc_sheet(data)), 2)
        self.assertEqual(parse_qc_results(data)[1]["readings"], [25.5])

    def test_parse_and_apply_by_hash(self):
        data = make_sheet(True)
        links = parse_face_links(data)
        self.assertEqual(links["links"][2]["faces_b"], [9])
        rows = parse_qc_sheet(data)
        res = apply_face_links(rows, links, job_sha256="abc", job_faces=100)
        self.assertEqual(res["applied"], 2)
        self.assertEqual(rows[0]["faces_a"], [5, 6])
        self.assertEqual(rows[1]["dim_type"], "linear")

    def test_apply_by_face_count_when_hash_differs(self):
        rows = parse_qc_sheet(make_sheet(True))
        res = apply_face_links(rows, parse_face_links(make_sheet(True)), job_sha256="zzz", job_faces=100)
        self.assertEqual(res["applied"], 2)
        self.assertEqual(res["matched_by"], "face_count")

    def test_skipped_for_different_cad(self):
        rows = parse_qc_sheet(make_sheet(True))
        res = apply_face_links(rows, parse_face_links(make_sheet(True)), job_sha256="zzz", job_faces=50)
        self.assertEqual(res["applied"], 0)
        self.assertIsNotNone(res["skipped_reason"])
        self.assertNotIn("faces_a", rows[0])

    def test_out_of_range_face_is_not_applied(self):
        rows = parse_qc_sheet(make_sheet(True, total=100))
        links = parse_face_links(make_sheet(True, total=8))
        res = apply_face_links(rows, links, job_sha256="abc", job_faces=8)
        self.assertEqual(res["applied"], 1)  # balloon 2 uses face 9 >= 8, skipped


if __name__ == "__main__":
    unittest.main()
