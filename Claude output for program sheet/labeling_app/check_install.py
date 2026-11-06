#!/usr/bin/env python3
"""Validate runtime dependencies and bundled assets without starting the server."""

from __future__ import annotations

import importlib
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
MODULES = ("fastapi", "uvicorn", "multipart", "numpy", "h5py", "networkx", "torch", "OCP")
ASSETS = (
    ROOT / "model" / "hier_v1_model.pt",
    ROOT / "viewer" / "step-viewer.html",
    ROOT.parent / "2. cluster_features.py",
    ROOT / "resources" / "MFCAD++_labels" / "feature_labels.txt",
)


def main() -> int:
    errors: list[str] = []
    if sys.version_info < (3, 11):
        errors.append("Python 3.11 or newer is required.")

    for name in MODULES:
        try:
            importlib.import_module(name)
        except Exception as exc:
            errors.append(f"Cannot import {name}: {exc}")

    for path in ASSETS:
        if not path.is_file():
            errors.append(f"Missing bundled asset: {path.relative_to(ROOT)}")

    if errors:
        print("Installation check failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Installation check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
