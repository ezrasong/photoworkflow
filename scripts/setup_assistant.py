"""Install only the pinned local assistant files. No processing-time downloads."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from photo_workflow.runtime import local_runtime,sha256,workspace_path
import requests

def setup():
    local_runtime()
    manifest=json.loads((ROOT/'models/assistant-manifest.json').read_text())
    for name,entry in manifest['files'].items():
        target=workspace_path(ROOT/name)
        if target.exists() and sha256(target)==entry['sha256']:
            print('Verified '+name,flush=True);continue
        target.parent.mkdir(parents=True,exist_ok=True)
        partial=target.with_suffix(target.suffix+'.partial')
        try:
            with requests.get(entry['url'],stream=True,timeout=(30,90)) as response:
                response.raise_for_status()
                with partial.open('wb') as out:
                    for block in response.iter_content(4*1024*1024):out.write(block)
            if partial.stat().st_size!=entry['bytes'] or sha256(partial)!=entry['sha256']:
                raise RuntimeError('Pinned download digest/size mismatch: '+name)
            partial.replace(target)
        finally:partial.unlink(missing_ok=True)
    for name in ('llama.zip','cudart.zip'):
        with zipfile.ZipFile(ROOT/'apps/llama-downloads'/name) as archive:
            for member in archive.infolist():
                if member.is_dir():continue
                target=(ROOT/'apps/llama'/member.filename).resolve()
                if not target.is_relative_to(ROOT/'apps/llama'):raise ValueError('Unsafe archive entry')
                key=target.relative_to(ROOT).as_posix()
                if key not in manifest['llama_files']:raise ValueError('Unpinned archive member')
                expected=manifest['llama_files'][key]
                if target.exists() and sha256(target)==expected:continue
                data=archive.read(member)
                if hashlib.sha256(data).hexdigest()!=expected:raise ValueError('Runtime digest mismatch')
                target.parent.mkdir(parents=True,exist_ok=True)
                temporary=target.with_suffix(target.suffix+'.partial')
                temporary.write_bytes(data);temporary.replace(target)
    for name,digest in manifest['llama_files'].items():
        if sha256(ROOT/name)!=digest:raise RuntimeError('Installed runtime mismatch: '+name)
    from scripts.setup_scunet import setup as setup_scunet
    setup_scunet()
    from scripts.setup_major_editing import setup as setup_major_editing
    setup_major_editing()
    from scripts.setup_heif import setup as setup_heif
    setup_heif()
    print('Local assistant installed and verified. Use Chat with Photo Assistant.cmd or the desktop editor.')

if __name__=='__main__':setup()
