import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

CODE_ROOT = Path(__file__).resolve().parents[1]
# Installed code is read-only. The desktop owns a separate persistent workspace.
ROOT = Path(os.environ.get('PHOTOWORKFLOW_HOME', CODE_ROOT)).resolve()
PYTHON = Path(sys.executable).resolve()
PYTHONW = PYTHON.with_name('pythonw.exe') if os.name == 'nt' else PYTHON

def asset_path(name):
    """Resolve maintained code separately from downloaded runtime/model assets."""
    if str(name).replace('\\', '/').startswith(('photo_workflow/', 'scripts/')):
        return CODE_ROOT / name
    return ROOT / name

def local_runtime():
    for key, folder in {'TORCH_HOME': 'torch', 'HF_HOME': 'huggingface',
                        'NUMBA_CACHE_DIR': 'numba', 'MPLCONFIGDIR': 'matplotlib',
                        'TEMP': 'temp', 'TMP': 'temp'}.items():
        path = ROOT / '.cache' / folder
        path.mkdir(parents=True, exist_ok=True)
        os.environ[key] = str(path)
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    sys.dont_write_bytecode = True

def disable_network():
    """Enforce no Python socket egress or child-process escape in processing.

    This is not an OS firewall. Audited dependencies perform inference locally;
    Adobe export and installation are deliberately separate commands.
    """
    def audit(event, args):
        if event in {'socket.connect', 'socket.getaddrinfo', 'socket.sendto',
                     'socket.bind', 'subprocess.Popen', 'os.system', 'os.posix_spawn'}:
            raise PermissionError('Offline processing: network and child processes disabled')
    sys.addaudithook(audit)

def check_cancel():
    marker = os.environ.get('PHOTOWORKFLOW_CANCEL_FILE')
    if marker:
        path = workspace_path(marker)
        if path.is_relative_to(ROOT / '.cache/control') and path.exists():
            raise KeyboardInterrupt()

def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def workspace_path(path):
    path = Path(path).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError('Generated files must remain inside the workspace')
    return path

def json_write(path, data):
    path = Path(path)
    temporary = path.with_name('.' + path.name + '.' + uuid.uuid4().hex + '.partial')
    try:
        temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
