"""Build pinned, offline-launchable creative MCPs into the NSIS backend."""
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import zipfile

from build_backend import ROOT, CACHE, fetch


def extract(archive, destination, prefix=''):
    """Reject traversal, Windows drive/ADS paths and archive links before writing."""
    destination = Path(destination).resolve()
    with zipfile.ZipFile(archive) as z:
        entries = []
        for item in z.infolist():
            name = item.filename.replace('\\', '/')
            path = PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts or ':' in name:
                raise ValueError('Unsafe MCP archive path')
            if (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('MCP archive links are not permitted')
            if not name.startswith(prefix) or item.is_dir():
                continue
            target = (destination / name[len(prefix):]).resolve()
            if not target.is_relative_to(destination):
                raise ValueError('MCP archive escaped destination')
            entries.append((item, target))
        for item, target in entries:
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(item) as source, target.open('wb') as output:
                shutil.copyfileobj(source, output)


def build(bundle):
    pins = json.loads((ROOT/'packaging/creative-mcp.json').read_text())
    downloads = CACHE/'creative-mcp-downloads'
    files = {}
    for name, pin in pins.items():
        target = downloads/name
        fetch(pin, target)
        if target.stat().st_size != pin['bytes']:
            raise ValueError('MCP download size mismatch: ' + name)
        files[name] = target
    # Replace only the owned build payload, never installed or user data.
    payload = (bundle/'creative-mcp').resolve()
    if not payload.is_relative_to(CACHE.resolve()):
        raise ValueError('MCP build destination must be inside packaging cache')
    if payload.exists():
        shutil.rmtree(payload)
    payload.mkdir(parents=True)
    extract(files['photoshop'], payload/'photoshop', 'server/')
    extract(files['node'], payload/'node', f"node-v{pins['node']['version']}-win-x64/")
    (payload/'lightroom').mkdir()
    shutil.copy2(files['lightroom'], payload/'lightroom/lightroom.exe')
    shutil.copy2(files['lightroom-license'], payload/'lightroom/LICENSE')
    # Kept apart from the executable so upstream does not auto-install a global plug-in.
    extract(files['lightroom-plugin'], bundle/'packaging/seed/apps')
    extract(files['resolve'], payload/'resolve', 'davinci-resolve-mcp-'+pins['resolve']['commit']+'/')
    # Upstream eagerly creates a log directory beside its source on import.
    # Redirect that one default to our writable profile; fail if upstream changes.
    server = payload/'resolve/src/server.py'
    source = server.read_text(encoding='utf-8')
    original = 'log_dir = os.path.join(project_dir, "logs")'
    if source.count(original) != 1:
        raise ValueError('Resolve log relocation patch no longer matches')
    server.write_text(source.replace(original,
        'log_dir = os.environ["PHOTOSTUDIO_MCP_LOG_DIR"]'), encoding='utf-8')
    subprocess.run(['uv', 'pip', 'install', '--python', str(bundle/'python/python.exe'),
                    '--target', str(payload/'python-libs'), '--only-binary=:all:',
                    '--no-deps', '--require-hashes', '-r',
                    str(ROOT/'packaging/creative-mcp-requirements.txt')], check=True)
    shutil.copy2(ROOT/'packaging/creative-mcp.json', payload/'manifest.json')
    shutil.copy2(ROOT/'packaging/creative-mcp-requirements.txt', payload/'requirements.txt')
    print('Bundled Photoshop, Lightroom and DaVinci Resolve MCPs')


if __name__ == '__main__':
    build(CACHE/'bundle')
