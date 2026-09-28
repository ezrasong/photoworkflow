"""Install only the pinned local HEIF decoder; never upgrade existing packages."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys
import requests

ROOT = Path(__file__).resolve().parents[1]

def setup():
    pin = json.loads((ROOT/'docs/heif-converter-research/decoder-pin.json').read_text())
    try:
        if importlib.metadata.version('pillow-heif') == pin['version']: return
    except importlib.metadata.PackageNotFoundError:
        pass
    if Path(sys.prefix).resolve() != (ROOT/'.venv').resolve():
        raise RuntimeError('Use the workspace .venv Python; system installs are forbidden')
    uv = shutil.which('uv')
    if not uv: raise RuntimeError('The existing uv installer is required')
    wheel = ROOT/'.cache/downloads'/pin['url'].rsplit('/',1)[1]
    wheel.parent.mkdir(parents=True, exist_ok=True)
    if not wheel.exists() or hashlib.sha256(wheel.read_bytes()).hexdigest() != pin['sha256']:
        session = requests.Session(); session.trust_env = False
        response = session.get(pin['url'],timeout=90); response.raise_for_status()
        if hashlib.sha256(response.content).hexdigest() != pin['sha256']: raise RuntimeError('Decoder wheel checksum mismatch')
        wheel.write_bytes(response.content)
    subprocess.run([uv,'pip','install','--python',sys.executable,'--no-deps','--no-index',str(wheel)],check=True)

if __name__ == '__main__': setup()
