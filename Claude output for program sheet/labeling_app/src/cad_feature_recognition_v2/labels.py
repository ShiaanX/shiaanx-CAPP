"""Label helpers for the MFCAD++ 25-class feature taxonomy."""

from __future__ import annotations

from pathlib import Path
import re


LABEL_RE = re.compile(r"^\s*(\d+)\s*-\s*(.+?)\s*$")

DEFAULT_LABELS: dict[int, str] = {
    0: "Chamfer",
    1: "Through hole",
    2: "Triangular passage",
    3: "Rectangular passage",
    4: "6-sided passage",
    5: "Triangular through slot",
    6: "Rectangular through slot",
    7: "Circular through slot",
    8: "Rectangular through step",
    9: "2-sided through step",
    10: "Slanted through step",
    11: "O-ring",
    12: "Blind hole",
    13: "Triangular pocket",
    14: "Rectangular pocket",
    15: "6-sided pocket",
    16: "Circular end pocket",
    17: "Rectangular blind slot",
    18: "Vertical circular end blind slot",
    19: "Horizontal circular end blind slot",
    20: "Triangular blind step",
    21: "Circular blind step",
    22: "Rectangular blind step",
    23: "Round",
    24: "Stock",
}


def load_label_names(dataset_root: str | Path) -> dict[int, str]:
    """Load labels from `feature_labels.txt`, falling back to built-in labels."""
    root = Path(dataset_root)
    labels_path = root / "feature_labels.txt"
    if not labels_path.exists():
        return dict(DEFAULT_LABELS)

    labels: dict[int, str] = {}
    for line in labels_path.read_text(errors="ignore").splitlines():
        match = LABEL_RE.match(line)
        if match:
            labels[int(match.group(1))] = match.group(2)

    return labels or dict(DEFAULT_LABELS)


def target_names(label_names: dict[int, str], *, num_classes: int = 25) -> list[str]:
    """Return sklearn-compatible target names in stable label-id order."""
    return [f"{index}: {label_names.get(index, str(index))}" for index in range(num_classes)]

