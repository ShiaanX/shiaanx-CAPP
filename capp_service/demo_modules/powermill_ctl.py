"""
powermill_ctl.py - open a generated program in the founder's PowerMill and step through it.

Everything PowerMill-facing goes through one HTTP bridge on localhost:5001 (the plugin inside
PowerMill). Only command forms already proven in the planner repo are used:
    PROJECT OPEN '<folder>'            (advisor/rewind.py, clamped_orchestrator.py)
    PROJECT SAVE                       (advisor/rewind.py; only ever into OUR working copy)
    DIALOGS MESSAGE OFF / DIALOGS ERROR OFF / UNITS MM      (the planner's preamble)
    ACTIVATE SETUP / ACTIVATE TOOLPATH "<name>"             (setup macros, toolpath macros)
    EDIT TOOLPATH "<name>" CALCULATE                        (toolpath macros)
    ROTATE TRANSFORM ISO1                                   (console project open)
    size(folder('Toolpath')), folder('Toolpath')[i].Name    (same parameter form as Tool / Setup)

Safety, in order of importance:
  * the saved projects (demo_backup/v3_motor_mount/pm_project_*) are never written: PowerMill only
    ever opens a fresh COPY under demo_backup/powermill_working/<name>/.
  * PROJECT OPEN into a session with unsaved changes raises a modal "save changes?" that blocks the
    bridge until a human clicks. So we never send it then: we read PowerMill's own window title
    (a "*" after "Project" = unsaved changes) and any extra window (a dialog) first, and refuse with
    a plain message. The one exception is a project that is itself one of our working copies:
    those hold nothing precious, so PROJECT SAVE into them first, then open.
  * We never wipe the session (DELETE ... ALL): that would destroy the founder's own work.
  * We never close or kill PowerMill and never retry a command that timed out.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from . import part_data, v3_runs

BRIDGE_URL = os.environ.get('POWERMILL_BRIDGE_URL', 'http://localhost:5001')
DEMO_BACKUP = part_data.REPO_ROOT / 'demo_backup'
WORK_ROOT = DEMO_BACKUP / 'powermill_working'
SAVED_ROOT = DEMO_BACKUP / 'v3_motor_mount'
SAVED_PROTECTED = (SAVED_ROOT / 'pm_project_final_all_3_setups', SAVED_ROOT / 'pm_project_final_PRISTINE_copy')
SAVED_FALLBACK = SAVED_PROTECTED[1]
KEEP_COPIES = 3
NAME_OK = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.\- ]{0,119}$')

MSG_DIALOG = ('A window is waiting for an answer inside PowerMill. Click Cancel (or close it) there, '
              'then try again. Nothing was changed.')
MSG_NO_BRIDGE = ('PowerMill is running but not answering. If a window is open in PowerMill, click '
                 'Cancel there; otherwise wait a moment and try again.')
MSG_NOT_RUNNING = 'PowerMill is not running.'
MSG_DIRTY = ('PowerMill has unsaved changes in the project "{name}". Save or close it there first '
             '(File > Save, or File > Close and answer the question yourself), then try again. '
             'Nothing was changed.')
MSG_TIMEOUT = ('PowerMill did not answer in time. If a window is open in PowerMill, click Cancel there. '
               'Nothing was retried.')

_lock = threading.Lock()   # the plugin's listener is single-threaded: one command at a time


class PmError(Exception):
    def __init__(self, code: str, message: str, http: int = 409):
        super().__init__(message)
        self.code, self.message, self.http = code, message, http

    def payload(self) -> dict:
        return {'ok': False, 'status': self.code, 'error': self.message}


# ── bridge (stdlib client, same endpoints as the planner's own client) ──────────────────────────

class BridgeTimeout(Exception):
    pass


class BridgeDown(Exception):
    pass


class Bridge:
    def __init__(self, base: str = BRIDGE_URL):
        self.base = base.rstrip('/')

    def _req(self, req, timeout):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode('utf-8', errors='replace')
        except TimeoutError as e:
            raise BridgeTimeout(str(e))
        except urllib.error.URLError as e:
            if isinstance(e.reason, TimeoutError) or 'timed out' in str(e.reason).lower():
                raise BridgeTimeout(str(e))
            raise BridgeDown(str(e))
        except OSError as e:
            if 'timed out' in str(e).lower():
                raise BridgeTimeout(str(e))
            raise BridgeDown(str(e))

    def alive(self, timeout: float = 4) -> bool:
        try:
            self._req(urllib.request.Request(self.base + '/status'), timeout)
            return True
        except (BridgeTimeout, BridgeDown):
            return False

    def execute(self, command: str, timeout: float = 60) -> dict:
        raw = self._req(urllib.request.Request(self.base + '/execute', data=command.encode('utf-8'),
                                               method='POST'), timeout)
        try:
            reply = json.loads(raw)
        except ValueError:
            raise BridgeDown(f'non-JSON reply to {command[:40]!r}')
        if not reply.get('success', False):
            raise BridgeDown(f"{command[:60]!r} failed: {reply.get('error')}")
        return reply

    def param(self, expr: str, timeout: float = 20) -> str:
        raw = self._req(urllib.request.Request(self.base + '/parameter?name=' + urllib.parse.quote(expr, safe='')),
                        timeout)
        try:
            reply = json.loads(raw)
        except ValueError:
            raise BridgeDown('non-JSON parameter reply')
        if not reply.get('success', False):
            raise BridgeDown(f"parameter {expr[:60]!r} failed: {reply.get('error')}")
        return str(reply.get('value', ''))


def _value(raw: str) -> str:
    """PowerMill prefixes values with type noise ending in ')': keep what follows the last one."""
    return str(raw).split(')')[-1].strip()


def _count(bridge, folder: str) -> int:
    try:
        return int(float(_value(bridge.param(f"size(folder('{folder}'))"))))
    except (ValueError, TypeError):
        return 0


def _names(bridge, folder: str) -> list[str]:
    return [_value(bridge.param(f"folder('{folder}')[{i}].Name")) for i in range(_count(bridge, folder))]


# ── the PowerMill window (title tells us the project and whether it has unsaved changes) ────────

TITLE_RE = re.compile(r'\[\s*(?:Editable\s+)?Project\s*(\*)?\s*(.*?)\s*\]\s*$', re.I)


def parse_title(title: str) -> dict:
    """'Autodesk PowerMill Ultimate 2020 [ Editable Project * name ]' -> project name + unsaved flag."""
    m = TITLE_RE.search(title or '')
    if not m:
        return {'project': None, 'dirty': False}
    return {'project': m.group(2) or None, 'dirty': bool(m.group(1))}


def _pmill_pids() -> list[int]:
    try:
        out = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq pmill.exe', '/FO', 'CSV', '/NH'],
                             capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return []
    return [int(m.group(1)) for m in re.finditer(r'"pmill\.exe","(\d+)"', out or '', re.I)]


def _visible_titles(pids: list[int]) -> list[str]:
    """Titles of PowerMill's visible top-level windows (the main window and any dialog)."""
    if os.name != 'nt' or not pids:
        return []
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    out: list[str] = []
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _l):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids and user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(400)
            user32.GetWindowTextW(hwnd, buf, 400)
            if buf.value.strip():
                out.append(buf.value.strip())
        return True

    user32.EnumWindows(proto(cb), 0)
    return out


def window_state() -> dict:
    pids = _pmill_pids()
    titles = _visible_titles(pids)
    main = next((t for t in titles if 'PowerMill' in t and TITLE_RE.search(t)), None) \
        or next((t for t in titles if 'PowerMill' in t), None)
    dialogs = [t for t in titles if t != main]
    return {'running': bool(pids), 'title': main, 'dialogs': dialogs, **parse_title(main or '')}


# ── working copies ─────────────────────────────────────────────────────────────────────────────

def _inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


def is_protected(path: Path) -> bool:
    return any(_inside(path, p) for p in SAVED_PROTECTED)


def pick_source(run_name: str | None = None) -> tuple[Path, str, str | None]:
    """(project folder to copy, label, run name). Newest finished planner run with a saved
    PowerMill project; falls back to the saved Motor Mount project."""
    if run_name:
        d = v3_runs.run_dir(run_name)
        if d is None:
            raise PmError('run_not_found', f'No program run named {run_name!r} on this computer.', 404)
        proj = v3_runs._pick_project(d)
        if proj is None:
            raise PmError('run_has_no_project', f'The run {run_name} has no saved PowerMill project yet.', 404)
        return proj, run_name, run_name
    try:
        runs = v3_runs.list_runs(60)
    except Exception:
        runs = []
    for r in runs:
        if r.get('status') == 'finished' and r.get('has_log'):
            d = v3_runs.run_dir(r['name'])
            proj = v3_runs._pick_project(d) if d else None
            if proj is not None:
                return proj, r['name'], r['name']
    if SAVED_FALLBACK.is_dir() and list(SAVED_FALLBACK.glob('*.pmlprj')):
        return SAVED_FALLBACK, 'saved Motor Mount program', None
    raise PmError('no_program', 'There is no finished program on this computer to open in PowerMill.', 404)


def _safe_stem(s: str) -> str:
    s = re.sub(r'[^A-Za-z0-9_.\-]+', '_', s).strip('_.-') or 'program'
    return s[:60]


def make_working_copy(src: Path, label: str, root: Path | None = None, now: datetime | None = None) -> Path:
    """Fresh copy of a PowerMill project folder under WORK_ROOT. Never touches `src`."""
    root = root or WORK_ROOT
    if not src.is_dir() or not list(src.glob('*.pmlprj')):
        raise PmError('bad_source', 'The program has no PowerMill project to copy.', 404)
    root.mkdir(parents=True, exist_ok=True)
    dest = root / f"{_safe_stem(label)}_{(now or datetime.now()).strftime('%H%M%S')}"
    n = 1
    while dest.exists():
        n += 1
        dest = root / f"{_safe_stem(label)}_{(now or datetime.now()).strftime('%H%M%S')}_{n}"
    if not _inside(dest, root) or is_protected(dest) or _inside(dest, src) or _inside(src, dest):
        raise PmError('unsafe_path', 'Refusing to use that location for the working copy.', 500)
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns('lockfile', '*.lock'))
    _prune(root, keep=KEEP_COPIES, current=dest)
    return dest


def _prune(root: Path, keep: int, current: Path) -> None:
    """Delete older working copies. Best effort: a copy PowerMill still has locked is left alone."""
    dirs = sorted((d for d in root.iterdir() if d.is_dir() and d != current), key=lambda d: d.stat().st_mtime,
                  reverse=True)
    for d in dirs[max(keep - 1, 0):]:
        if _inside(d, root) and not is_protected(d):
            shutil.rmtree(d, ignore_errors=True)


def working_names(root: Path | None = None) -> set[str]:
    """Names PowerMill may show for one of our working copies: the folder name or the project file name."""
    root = root or WORK_ROOT
    out: set[str] = set()
    if root.is_dir():
        for d in root.iterdir():
            if d.is_dir():
                out.add(d.name)
                out.update(f.stem for f in d.glob('*.pmlprj'))
    return out


def is_working_project(project_name: str | None, root: Path | None = None) -> bool:
    return bool(project_name) and project_name in working_names(root)


# ── status ─────────────────────────────────────────────────────────────────────────────────────

def _blocker(w: dict, bridge: Bridge) -> PmError | None:
    if not w['running']:
        return PmError('not_running', MSG_NOT_RUNNING)
    if w['dialogs']:
        return PmError('dialog_waiting', MSG_DIALOG)
    if not bridge.alive():
        return PmError('bridge_not_answering', MSG_NO_BRIDGE)
    return None


def status(bridge: Bridge | None = None, window=window_state) -> dict:
    bridge = bridge or Bridge()
    w = window()
    out = {'ok': True, 'running': w['running'], 'bridge_answering': False, 'dialog_waiting': bool(w['dialogs']),
           'dialogs': w['dialogs'], 'project': w['project'], 'unsaved_changes': w['dirty'],
           'is_working_copy': is_working_project(w['project']), 'toolpaths': None, 'state': None, 'message': None}
    if not w['running']:
        out['state'] = 'not_running'
        out['message'] = MSG_NOT_RUNNING
        return out
    if w['dialogs']:
        out['state'] = 'dialog_waiting'
        out['message'] = MSG_DIALOG
        return out
    out['bridge_answering'] = bridge.alive()
    if not out['bridge_answering']:
        out['state'] = 'bridge_not_answering'
        out['message'] = MSG_NO_BRIDGE
        return out
    out['state'] = 'ready'
    try:
        out['toolpaths'] = _count(bridge, 'Toolpath')
    except (BridgeTimeout, BridgeDown):
        pass
    return out


# ── open the program ───────────────────────────────────────────────────────────────────────────

def _launch_if_needed(w: dict, bridge: Bridge, wait_s: int = 240) -> None:
    """Only when PowerMill is not running at all (so the session is certainly empty)."""
    if w['running']:
        return
    exe = None
    try:
        import v3_adapter
        sys_path = os.path.join(v3_adapter._v3_root(), 'orchestrator')
        import importlib.util
        spec = importlib.util.spec_from_file_location('_v3_pm_bridge', os.path.join(sys_path, 'pm_bridge.py'))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        exe = mod.DEFAULT_EXE
    except Exception:
        exe = r'C:\Program Files\Autodesk\PowerMill 2020\sys\exec64\pmill.exe'
    if not os.path.isfile(exe):
        raise PmError('not_installed', 'PowerMill is not installed on this computer.', 501)
    subprocess.Popen([exe])
    deadline = time.time() + wait_s
    while time.time() < deadline:
        if bridge.alive():
            return
        time.sleep(3)
    raise PmError('bridge_not_answering', 'PowerMill was started but is still loading. Wait a minute, then try again.')


def _guard_open(w: dict) -> str:
    """'empty' | 'clean' | 'ours' - or raise. Decides whether PROJECT OPEN is safe."""
    if w['dirty']:
        if is_working_project(w['project']):
            return 'ours'
        raise PmError('unsaved_changes', MSG_DIRTY.format(name=w['project'] or 'current'))
    return 'clean' if w['project'] else 'empty'


def open_program(run_name: str | None = None, bridge: Bridge | None = None, window=window_state,
                 root: Path | None = None) -> dict:
    t0 = time.time()
    bridge = bridge or Bridge()
    w = window()
    if w['dialogs']:
        raise PmError('dialog_waiting', MSG_DIALOG)
    if w['running']:
        if not bridge.alive():
            raise PmError('bridge_not_answering', MSG_NO_BRIDGE)
        mode = _guard_open(w)
    else:
        mode = 'empty'
    src, label, run = pick_source(run_name)
    if not _lock.acquire(blocking=False):
        raise PmError('busy', 'PowerMill is busy with the previous step. Wait a moment and try again.')
    try:
        _launch_if_needed(w, bridge)
        dest = make_working_copy(src, label, root=root)
        try:
            if mode == 'ours':
                bridge.execute('PROJECT SAVE', timeout=120)   # into our own scratch copy only
            r = bridge.execute("PROJECT OPEN '%s'" % str(dest).replace('\\', '/'), timeout=300)
            if r.get('returnCode') not in (0, None):
                raise PmError('open_failed', f"PowerMill would not open the program (code {r.get('returnCode')}).", 502)
            for c in ('DIALOGS MESSAGE OFF', 'DIALOGS ERROR OFF', 'UNITS MM'):
                bridge.execute(c, timeout=60)
            toolpaths = _names(bridge, 'Toolpath')
            setups = _names(bridge, 'Setup')
            if setups:
                bridge.execute('ACTIVATE SETUP "%s"' % setups[0], timeout=60)
            bridge.execute('ROTATE TRANSFORM ISO1', timeout=60)
        except BridgeTimeout:
            raise PmError('dialog_waiting', MSG_TIMEOUT)
        except BridgeDown as e:
            raise PmError('bridge_not_answering', MSG_NO_BRIDGE + ' (' + str(e)[:120] + ')')
    finally:
        _lock.release()
    return {'ok': True, 'status': 'opened', 'project': dest.name, 'source': label, 'run_name': run,
            'toolpaths': len(toolpaths), 'setups': setups, 'toolpath_names': toolpaths,
            'seconds': round(time.time() - t0, 1)}


# ── step through the toolpaths ─────────────────────────────────────────────────────────────────

def _checked_session(bridge: Bridge, window) -> dict:
    w = window()
    err = _blocker(w, bridge)
    if err:
        raise err
    return w


def list_toolpaths(bridge: Bridge | None = None, window=window_state) -> dict:
    bridge = bridge or Bridge()
    w = _checked_session(bridge, window)
    try:
        names = _names(bridge, 'Toolpath')
    except BridgeTimeout:
        raise PmError('dialog_waiting', MSG_TIMEOUT)
    except BridgeDown as e:
        raise PmError('bridge_not_answering', MSG_NO_BRIDGE + ' (' + str(e)[:120] + ')')
    return {'ok': True, 'project': w['project'], 'toolpaths': names, 'count': len(names)}


def _check_name(name, names: list[str]) -> str:
    if not isinstance(name, str) or not name or '"' in name or "'" in name or '\n' in name or name not in names:
        raise PmError('toolpath_not_found', 'That toolpath is not in the open program.', 404)
    return name


def show_toolpath(name: str, bridge: Bridge | None = None, window=window_state) -> dict:
    bridge = bridge or Bridge()
    _checked_session(bridge, window)
    if not _lock.acquire(blocking=False):
        raise PmError('busy', 'PowerMill is busy with the previous step. Wait a moment and try again.')
    try:
        names = _names(bridge, 'Toolpath')
        _check_name(name, names)
        bridge.execute('ACTIVATE TOOLPATH "%s"' % name, timeout=60)
    except BridgeTimeout:
        raise PmError('dialog_waiting', MSG_TIMEOUT)
    except BridgeDown as e:
        raise PmError('bridge_not_answering', MSG_NO_BRIDGE + ' (' + str(e)[:120] + ')')
    finally:
        _lock.release()
    return {'ok': True, 'status': 'shown', 'toolpath': name, 'index': names.index(name), 'total': len(names)}


def recalculate(name: str, bridge: Bridge | None = None, window=window_state, wait_s: int = 150) -> dict:
    """Recalculate one toolpath of OUR working copy, live in PowerMill. Refused on any other project."""
    bridge = bridge or Bridge()
    w = _checked_session(bridge, window)
    if not is_working_project(w['project']):
        raise PmError('not_working_copy', 'Open the program from this page first; only that copy is recalculated.')
    if not _lock.acquire(blocking=False):
        raise PmError('busy', 'PowerMill is busy with the previous step. Wait a moment and try again.')
    t0 = time.time()
    try:
        names = _names(bridge, 'Toolpath')
        _check_name(name, names)
        bridge.execute('ACTIVATE TOOLPATH "%s"' % name, timeout=60)   # CALCULATE refuses a non-active toolpath
        bridge.execute('EDIT TOOLPATH "%s" CALCULATE' % name, timeout=wait_s)
    except BridgeTimeout:
        # not proof it failed: PowerMill answers late while calculating
        return {'ok': True, 'status': 'still_running', 'toolpath': name,
                'message': 'PowerMill is still calculating this toolpath; watch it there.',
                'seconds': round(time.time() - t0, 1)}
    except BridgeDown as e:
        raise PmError('bridge_not_answering', MSG_NO_BRIDGE + ' (' + str(e)[:120] + ')')
    finally:
        _lock.release()
    return {'ok': True, 'status': 'done', 'toolpath': name, 'seconds': round(time.time() - t0, 1)}
