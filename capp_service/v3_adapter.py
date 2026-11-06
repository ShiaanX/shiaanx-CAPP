"""Adapter: Rohit/Dishant's v3 standalone planner, offline, as one call.

    from v3_adapter import run_v3_analysis
    res = run_v3_analysis(r"...\\MOTOR MOUNT.step", cache_dir="demo_data/v3_cache")

v3 needs PythonOCC/VTK/scipy, so the work runs in v3's own conda env through
capp_service/v3_runner.py (a subprocess); this module is stdlib-only and can
be imported from any Python. Results are cached in `cache_dir` keyed by the
STEP file's SHA-256 + v3 commit + options, so a second call is instant.

Environment:
    V3_ROOT     v3 checkout (default C:\\Users\\Siddhant Gupta\\Documents\\shiaanx_v3_standalone)
    V3_PYTHON   python of v3's env (default <miniconda3>\\envs\\occ_env\\python.exe,
                falling back to envs\\occ)
    CONDA_ROOT  miniconda root, put on PATH for v3's own `conda run` calls

    V3_DISABLED  "1" = server mode (v3 / PowerMill / occ_env are not installed): only the saved
                analyses in demo_data/v3_cache are served, looked up by the STEP file's SHA-256
                through v3_cache/index.json; a miss raises V3Unavailable immediately. No
                subprocess is ever spawned and git is never called.

The first (uncached) call takes tens of minutes on a real part - the costed
planner sweeps ~28 tools per face. Pre-warm the cache before a demo.
"""

import hashlib
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_V3_ROOT = r"C:\Users\Siddhant Gupta\Documents\shiaanx_v3_standalone"
CONDA_ROOT = os.environ.get("CONDA_ROOT",
                            os.path.expanduser(r"~\miniconda3"))
RUNNER = os.path.join(HERE, "v3_runner.py")
SCHEMA_VERSION = 2
INDEX_NAME = "index.json"

V3_UNAVAILABLE_MSG = ("Part analysis (v3 planner) is not available on this environment; saved analyses "
                      "only. Ask the team to run it on the planning workstation.")


class V3Unavailable(RuntimeError):
    """Server mode (V3_DISABLED=1) and the part has no saved analysis. str(e) is shown to users as is."""


def v3_disabled():
    return os.environ.get("V3_DISABLED", "").strip().lower() in ("1", "true", "yes", "on")


def _v3_root():
    return os.environ.get("V3_ROOT", DEFAULT_V3_ROOT)


def _v3_python():
    p = os.environ.get("V3_PYTHON")
    if p:
        return p
    for env in ("occ_env", "occ"):
        cand = os.path.join(CONDA_ROOT, "envs", env, "python.exe")
        if os.path.exists(cand):
            return cand
    return sys.executable


def _v3_commit(root):
    try:
        return subprocess.run(["git", "-C", root, "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=20
                              ).stdout.strip() or None
    except Exception:
        return None


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _index_path(cache_dir):
    return os.path.join(cache_dir, INDEX_NAME)


def _load_index(cache_dir):
    try:
        with open(_index_path(cache_dir), encoding="utf-8") as f:
            return json.load(f).get("entries", [])
    except (OSError, ValueError):
        return []


def _index_add(cache_dir, sha256, faces, filename, part):
    """Record 'this STEP content + face order -> this cache file' so a server without git / v3
    (whose cache key cannot be recomputed) can still find the saved analysis by SHA-256."""
    try:
        entries = _load_index(cache_dir)
        faces = faces or ""
        if any(e.get("sha256") == sha256 and (e.get("faces") or "") == faces for e in entries):
            return
        entries.append({"sha256": sha256, "faces": faces, "file": filename, "part": part})
        tmp = _index_path(cache_dir) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"schema": 1, "entries": entries}, f, indent=1)
        os.replace(tmp, _index_path(cache_dir))
    except OSError:
        pass


def _serve_saved(step_path, cache_dir, faces, t0):
    """V3_DISABLED: saved analysis for this exact STEP content + face order, or V3Unavailable."""
    sha = _sha256(step_path)
    for e in _load_index(cache_dir):
        if e.get("sha256") == sha and (e.get("faces") or "") == (faces or ""):
            path = os.path.join(cache_dir, e["file"])
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    res = json.load(f)
                res["cached"] = True
                res["served_from"] = "saved_analysis"
                res["cache_runtime_s"] = round(time.time() - t0, 3)
                return res
    raise V3Unavailable(V3_UNAVAILABLE_MSG)


def run_v3_analysis(step_path: str, material: str = "aluminium",
                    cache_dir: "str | None" = None, allowance_mm: float = 2.0,
                    max_setups: int = 4, timeout_s: int = 3 * 3600,
                    force: bool = False, faces: "str | None" = None) -> dict:
    """Run v3's reach analysis + costed face planner on a STEP file, offline.

    Returns the schema documented in V3_DEMO_NOTES.md (source, v3_commit,
    part, billet_mm, part_bbox_mm, part_volume_mm3, removal_volume_mm3,
    directions, unreachable_mm3, setups_needed, holes, plan,
    forced_small_tools, warnings, runtime_s) plus a few extra keys.
    """
    t0 = time.time()
    step_path = os.path.abspath(step_path)
    if not os.path.exists(step_path):
        raise FileNotFoundError(step_path)
    cache_dir = cache_dir or os.path.join(HERE, "demo_data", "v3_cache")
    if v3_disabled():
        return _serve_saved(step_path, cache_dir, faces, t0)
    root = _v3_root()
    commit = _v3_commit(root)
    os.makedirs(cache_dir, exist_ok=True)
    key = hashlib.sha1(json.dumps(
        [SCHEMA_VERSION, _sha256(step_path), commit, float(allowance_mm),
         int(max_setups), faces or ""]).encode()).hexdigest()[:20]
    cached = os.path.join(cache_dir, "v3_%s.json" % key)
    if os.path.exists(cached) and not force:
        with open(cached, encoding="utf-8") as f:
            res = json.load(f)
        res["cached"] = True
        res["cache_runtime_s"] = round(time.time() - t0, 3)
        _index_add(cache_dir, _sha256(step_path), faces, os.path.basename(cached), res.get("part"))
        return res

    env = dict(os.environ)
    env["V3_ROOT"] = root
    env["PYTHONIOENCODING"] = "utf-8"
    env["PATH"] = os.pathsep.join([os.path.join(CONDA_ROOT, "condabin"),
                                   os.path.join(CONDA_ROOT, "Scripts"),
                                   env.get("PATH", "")])
    out_json = os.path.join(cache_dir, "v3_%s.raw.json" % key)
    cmd = [_v3_python(), RUNNER, "--step", step_path, "--out", out_json,
           "--allowance", str(allowance_mm), "--max-setups", str(max_setups)]
    if faces:
        cmd += [f"--faces={faces}"]  # = form: a value like "-Y,+Y" would otherwise parse as a flag
    p = subprocess.run(cmd, capture_output=True, text=True, env=env,
                       timeout=timeout_s, stdin=subprocess.DEVNULL, cwd=root)
    if p.returncode != 0 or not os.path.exists(out_json):
        tail = (p.stdout or "")[-1500:] + (p.stderr or "")[-1500:]
        raise RuntimeError("v3 runner failed (rc=%s): %s" % (p.returncode, tail))
    with open(out_json, encoding="utf-8") as f:
        res = json.load(f)

    res["source"] = "v3"
    res["v3_commit"] = commit
    res["v3_root"] = root
    res["material"] = material
    if "alumin" not in (material or "").lower():
        res.setdefault("warnings", []).append(
            "v3's tool library carries aluminium cutting data only; "
            "material %r was ignored" % material)
    res["runtime_s"] = round(time.time() - t0, 1)
    res["cached"] = False
    with open(cached, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1)
    _index_add(cache_dir, _sha256(step_path), faces, os.path.basename(cached), res.get("part"))
    return res


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("step")
    ap.add_argument("--cache-dir", default=None)
    ap.add_argument("--max-setups", type=int, default=4)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--faces", default=None,
                    help='operator face order, e.g. "+Z,-Z,-Y"')
    ap.add_argument("--out", default=None, help="also write the result here")
    a = ap.parse_args()
    r = run_v3_analysis(a.step, cache_dir=a.cache_dir,
                        max_setups=a.max_setups, force=a.force,
                        faces=a.faces)
    txt = json.dumps(r, indent=1)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(txt)
    print(txt)
