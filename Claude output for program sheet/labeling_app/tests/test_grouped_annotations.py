from __future__ import annotations

import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest

from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_app.main import normalize_open_annotations, write_open_annotation_csv


class GroupedAnnotationTests(unittest.TestCase):
    def make_job(self, root: Path, total_faces: int = 8) -> dict[str, str]:
        (root / "features.json").write_text(
            json.dumps({"faces": {"total_faces": total_faces}}) + "\n"
        )
        return {
            "job_id": "group-test",
            "job_dir": str(root),
            "original_name": "sample.step",
        }

    def test_multiple_surfaces_form_one_feature_instance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = normalize_open_annotations(
                self.make_job(root),
                {
                    "annotations": [
                        {
                            "feature_instance_id": "slot_001",
                            "label": "Slot",
                            "face_indices": [4, 1, 3, 2],
                            "notes": "radius, plane, radius, plane",
                        }
                    ]
                },
            )

            self.assertEqual(payload["schema_version"], "1.1")
            self.assertEqual(payload["annotation_unit"], "feature_instance")
            self.assertEqual(payload["feature_instance_count"], 1)
            feature = payload["annotations"][0]
            self.assertEqual(feature["feature_instance_id"], "slot_001")
            self.assertEqual(feature["surface_indices"], [1, 2, 3, 4])
            self.assertEqual(feature["surface_count"], 4)

            csv_path = root / "labels.csv"
            write_open_annotation_csv(csv_path, payload)
            with csv_path.open(newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 4)
            self.assertEqual({row["feature_instance_id"] for row in rows}, {"slot_001"})
            self.assertEqual({row["surface_count"] for row in rows}, {"4"})

    def test_surface_cannot_belong_to_two_feature_instances(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(HTTPException):
                normalize_open_annotations(
                    self.make_job(root),
                    {
                        "annotations": [
                            {"feature_instance_id": "slot_001", "label": "Slot", "face_indices": [1, 2]},
                            {"feature_instance_id": "hole_001", "label": "Hole", "face_indices": [2, 3]},
                        ]
                    },
                )


if __name__ == "__main__":
    unittest.main()
