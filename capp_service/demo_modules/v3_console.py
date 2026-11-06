"""Start Rohit's v3 console (shiaanx_v3_standalone/ui/server.py) on demand.

The /proto "Open v3 console" button calls ensure_running() through capp_service, so the founder
never has to open an Anaconda Prompt: if nothing is listening on the console port, the console is
launched detached (it outlives capp_service restarts) with the occ_env python and conda on PATH,
since v3 calls `conda run` internally. Output goes to v3's own database_runtime folder.
"""
import os
import socket
import subprocess
import threading
import time

import v3_adapter

PORT = int(os.environ.get('V3_CONSOLE_PORT', '8765'))
URL = 'http://localhost:%d' % PORT
STARTUP_TIMEOUT_S = 30

_lock = threading.Lock()


def disabled():
    """Server mode (V3_DISABLED=1): v3 is not installed, so the console can never be started."""
    return v3_adapter.v3_disabled()


def _listening():
    try:
        with socket.create_connection(('127.0.0.1', PORT), timeout=0.5):
            return True
    except OSError:
        return False


def ensure_running():
    """Return {url, ready, started, log}; launch the console first if it isn't up."""
    if disabled():
        raise RuntimeError(v3_adapter.V3_UNAVAILABLE_MSG)   # never spawns anything in server mode
    with _lock:
        if _listening():
            return {'url': URL, 'ready': True, 'started': False}
        root = v3_adapter._v3_root()
        env = dict(os.environ)
        env['PYTHONIOENCODING'] = 'utf-8'
        env['PATH'] = os.pathsep.join([os.path.join(v3_adapter.CONDA_ROOT, 'condabin'),
                                       os.path.join(v3_adapter.CONDA_ROOT, 'Scripts'),
                                       env.get('PATH', '')])
        log_dir = os.path.join(root, 'database_runtime')
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, 'console_autostart.log')
        log = open(log_path, 'ab')
        flags = 0
        if os.name == 'nt':
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        subprocess.Popen([v3_adapter._v3_python(), '-u', os.path.join('ui', 'server.py')],
                         cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, creationflags=flags, close_fds=True)
        deadline = time.time() + STARTUP_TIMEOUT_S
        while time.time() < deadline:
            if _listening():
                return {'url': URL, 'ready': True, 'started': True, 'log': log_path}
            time.sleep(0.5)
        return {'url': URL, 'ready': False, 'started': True, 'log': log_path}
