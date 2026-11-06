"""Prepared QC sheets: <part folder>/qc/*.xlsx. The part is found by the same normalised key as the
other part data; the caller's text never becomes a path."""
from __future__ import annotations

from pathlib import Path

from . import part_data


def find(part_key: str) -> Path | None:
    k = part_data.norm(part_key)
    if not k:
        return None
    for d in part_data.part_dirs():
        if k in part_data._part_keys(d):
            qc = d / 'qc'
            if qc.is_dir():
                files = sorted(p for p in qc.glob('*.xlsx') if p.is_file() and not p.name.startswith('~$'))
                if files:
                    return files[0]
    return None
