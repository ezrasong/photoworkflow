"""Build a relocatable backend from pinned redistributables, never from .venv.

Run with any build Python and uv on PATH. This script needs no CUDA compiler.
The separately pinned native Mamba release asset is verified before inclusion.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
CACHE=ROOT/'.cache/packaging'

def digest(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def fetch(entry,path):
    path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists() or digest(path)!=entry['sha256']:
        temp=path.with_suffix('.download')
        urllib.request.urlretrieve(entry['url'],temp)
        if digest(temp)!=entry['sha256']:raise ValueError('Build download checksum mismatch')
        temp.replace(path)

def build(native):
    CACHE.mkdir(parents=True,exist_ok=True)
    pin=json.loads((ROOT/'packaging/python-runtime.json').read_text())
    archive=CACHE/'python-runtime.tar.gz';fetch(pin,archive)
    fresh=CACHE/'clean-python'
    if not (fresh/'python/python.exe').exists():
        fresh.mkdir(parents=True,exist_ok=True)
        with tarfile.open(archive) as tar:tar.extractall(fresh,filter='data')
    python=fresh/'python/python.exe'
    # The official wheel brings CUDA/cuDNN DLLs; large wheels are downloaded during NSIS installation.
    full=(ROOT/'packaging/requirements-hashed.txt').read_text()
    lines=full.splitlines(keepends=True);filtered=[];skip=False
    for line in lines:
        if line and not line[0].isspace() and not line.startswith('#'):
            skip=line.startswith(('torch==','torchvision=='))
        if not skip:filtered.append(line)
    requirements=CACHE/'base-requirements.txt';requirements.write_text(''.join(filtered))
    subprocess.run(['uv','pip','install','--python',str(python),'--break-system-packages','--no-deps','--require-hashes',
                    '-r',str(requirements)],check=True)
    bundle=CACHE/'bundle';bundle.mkdir(parents=True,exist_ok=True)
    # Ignore build caches but retain all DLLs, Tk, package metadata and licenses.
    shutil.copytree(fresh/'python',bundle/'python',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for folder in ('photo_workflow','scripts','integrations'):
        shutil.copytree(ROOT/folder,bundle/folder,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copytree(ROOT/'packaging/seed',bundle/'packaging/seed',dirs_exist_ok=True)
    shutil.copy2(ROOT/'packaging/downloads.json',bundle/'packaging/downloads.json')
    shutil.copy2(ROOT/'packaging/python-runtime.json',bundle/'packaging/python-runtime.json')
    manifest=json.loads((bundle/'packaging/seed/models/mambairv2-manifest.json').read_text())
    expected=manifest['files']['apps/mamba-scan-build/selective_scan_cuda.pyd']['sha256']
    if not native.exists() or digest(native)!=expected:raise ValueError('Obtain the checksum-pinned native Mamba release asset before packaging')
    target=bundle/'packaging/seed/apps/mamba-scan-build/selective_scan_cuda.pyd'
    target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(native,target)
    # Integrity pins track maintained source, not paths on the build computer.
    for name,entry in manifest['files'].items():
        if name.startswith(('photo_workflow/','scripts/')):
            entry.update(sha256=digest(bundle/name),bytes=(bundle/name).stat().st_size)
    (bundle/'packaging/seed/models/mambairv2-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    legal=bundle/'licenses';legal.mkdir(exist_ok=True)
    shutil.copy2(ROOT/'desktop/vendor/opencode/LICENSE',legal/'OpenCode-MIT.txt')
    shutil.copy2(ROOT/'THIRD-PARTY-NOTICES.txt',legal/'THIRD-PARTY-NOTICES.txt')
    from build_creative_mcp import build as build_creative_mcp
    build_creative_mcp(bundle)
    subprocess.run([str(bundle/'python/python.exe'),'-c','import tkinter, numpy, PIL, cv2, imagecodecs, win32api, yaml, pillow_heif; print("Bundled runtime imports passed")'],check=True)
    print('Relocatable backend: '+str(bundle))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--native',type=Path,required=True);args=p.parse_args();build(args.native.resolve())
