"""Bundled creative MCP inventory and bounded inspection for the desktop broker.

Upstream mutation tools are available to explicitly configured external clients.
The photo assistant admits only the fixed inspections below, through its broker.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from .runtime import CODE_ROOT, ROOT, json_write

NAMES = ('photoshop', 'lightroom', 'resolve')
LABELS = ('Photoshop', 'Lightroom Classic', 'DaVinci Resolve')
REQUIRED = {
    'photoshop': ('node/node.exe', 'photoshop/dist/index.js'),
    'lightroom': ('lightroom/lightroom.exe',),
    'resolve': ('resolve/src/server.py', 'python-libs/mcp/__init__.py'),
}


def inventory():
    payload = CODE_ROOT/'creative-mcp'
    manifest = payload/'manifest.json'
    pins = json.loads(manifest.read_text()) if manifest.is_file() else {}
    return [dict(id=name, name=label, version=pins.get(name, {}).get('version'),
                 bundled=name in pins and all((payload/p).is_file() for p in REQUIRED[name]),
                 repository='https://github.com/'+pins[name]['repository'] if name in pins else None)
            for name, label in zip(NAMES, LABELS)]


def write_config():
    """Relocate our own opt-in config after installation/upgrade; no client edits."""
    path = ROOT/'desktop/mcp/servers.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    servers = {name: {'command': str(Path(sys.executable).resolve()),
                      'args': ['-I', str(CODE_ROOT/'integrations/creative-mcp.py'), 'serve', name],
                      'env': {'PHOTOWORKFLOW_HOME': str(ROOT)}} for name in NAMES}
    json_write(path, {'mcpServers': servers})
    return str(path)


def inspect(name, *, probe=False, cancel_file=None):
    if name not in NAMES:
        raise ValueError('Choose Photoshop, Lightroom or Resolve')
    if not next(x for x in inventory() if x['id'] == name)['bundled']:
        raise RuntimeError('Creative MCP payload is missing. Install the new Photo Studio build.')
    if cancel_file and Path(cancel_file).exists():
        raise RuntimeError('Cancelled before MCP inspection')
    env = dict(os.environ, PHOTOWORKFLOW_HOME=str(ROOT))
    process = subprocess.Popen([sys.executable, '-I', str(CODE_ROOT/'integrations/creative-mcp.py'),
                                'probe' if probe else 'inspect', name],
                               env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, encoding='utf-8',
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    deadline = time.monotonic()+50
    try:
        while True:
            if cancel_file and Path(cancel_file).exists():
                raise RuntimeError('MCP inspection cancelled')
            if time.monotonic() >= deadline:
                raise TimeoutError('MCP inspection timed out; no edit was requested')
            try:
                output, error = process.communicate(timeout=.25)
                break
            except subprocess.TimeoutExpired:
                continue
        if process.returncode:
            raise RuntimeError('MCP check failed: '+(error or output)[-3000:])
        return json.loads(output)
    finally:
        if process.poll() is None:
            # This process can only perform reads. Stop its owned server tree too.
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
            else:
                process.kill()
            process.communicate(timeout=10)
