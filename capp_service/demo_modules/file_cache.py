"""
file_cache.py — in-process memo for results parsed from files, keyed by the files' mtimes.

A cached value is reused only while every file it was read from has the same path, mtime and
size; touch or replace any of them and the next call re-reads. Nothing is written to disk and
the source files are only ever read. Results are deep-copied out so callers can't mutate the cache.
"""

from __future__ import annotations

import copy
import threading
from pathlib import Path
from typing import Callable, Iterable

_cache: dict = {}
_locks: dict = {}
_guard = threading.Lock()


def stamp(paths: Iterable[Path]) -> tuple:
    out = []
    for p in paths:
        try:
            st = Path(p).stat()
            out.append((str(p), st.st_mtime_ns, st.st_size))
        except OSError:
            out.append((str(p), None, None))
    return tuple(sorted(out))


def memo(name: str, paths: Iterable[Path], compute: Callable[[], object]):
    """Return compute()'s result, cached under `name` until any of `paths` changes."""
    key_stamp = stamp(paths)
    with _guard:
        lock = _locks.setdefault(name, threading.Lock())
    with lock:  # one computation per name at a time; concurrent callers wait and reuse it
        hit = _cache.get(name)
        if hit is not None and hit[0] == key_stamp:
            return copy.deepcopy(hit[1])
        val = compute()
        _cache[name] = (key_stamp, val)
        return copy.deepcopy(val)


def clear() -> None:
    with _guard:
        _cache.clear()
