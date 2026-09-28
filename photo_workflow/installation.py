"""Explicit, resumable setup. Never imported by an inference worker."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import urllib.request
import zipfile
import zlib

from .runtime import CODE_ROOT, ROOT, json_write, sha256

COMPLETE_GROUPS = ('runtime', 'assistant', 'photo', 'legacy', 'obsidian')


def catalog():
    return json.loads((CODE_ROOT/'packaging/downloads.json').read_text(encoding='utf-8'))['files']

def target_path(name):
    path=(ROOT/name).resolve()
    if not path.is_relative_to(ROOT) or path==ROOT: raise ValueError('Unsafe installation path')
    return path

def inventory():
    groups={}
    for name,entry in catalog().items():
        group=groups.setdefault(entry['group'],{'group':entry['group'],'bytes':0,'missingBytes':0,'files':[]})
        path=target_path(name)
        # Size is only a setup estimate. Installation and inference verify hashes.
        present=path.is_file() and path.stat().st_size==entry['bytes']
        group['bytes']+=entry['bytes']
        if not present:group['missingBytes']+=entry['bytes']
        group['files'].append({'name':name,'bytes':entry['bytes'],'downloaded':present})
    return list(groups.values())

def download(url, destination, size, digest, progress=lambda n:None, cancelled=lambda:False):
    if not url.startswith('https://'): raise ValueError('Setup requires HTTPS')
    destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.exists() and destination.stat().st_size==size and sha256(destination)==digest:return
    partial=destination.with_name(destination.name+'.partial')
    offset=partial.stat().st_size if partial.exists() else 0
    if offset>size:partial.unlink();offset=0
    if offset==size:
        if sha256(partial)==digest:partial.replace(destination);return
        partial.unlink();offset=0
    request=urllib.request.Request(url,headers={'Range':f'bytes={offset}-'} if offset else {})
    with urllib.request.urlopen(request,timeout=60) as response:
        if not response.url.startswith('https://'):raise ValueError('Insecure setup redirect')
        if offset and response.status==206:
            if not response.headers.get('Content-Range','').startswith(f'bytes {offset}-'):raise ValueError('Invalid resume response')
        else:offset=0
        with partial.open('ab' if offset else 'wb') as stream:
            while True:
                if cancelled(): raise InterruptedError('Setup paused. Run Install / repair again to resume.')
                block=response.read(4*1024*1024)
                if not block:break
                offset+=len(block)
                if offset>size:raise ValueError('Download exceeds pinned size')
                stream.write(block);progress(offset)
    if offset!=size:raise ValueError('Download interrupted; retry to resume')
    if sha256(partial)!=digest:
        partial.unlink()
        raise ValueError('Download integrity check failed; invalid partial removed. Retry to download again.')
    partial.replace(destination)

def extract_wheel(path, cancelled):
    folder=ROOT/'runtime/python-libs'
    folder.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(path) as archive:
        for member in archive.infolist():
            if cancelled():raise InterruptedError('Setup paused during extraction. Run repair to finish.')
            target=(folder/member.filename).resolve()
            if not target.is_relative_to(folder.resolve()):raise ValueError('Unsafe wheel member')
            if member.is_dir():continue
            if target.is_file() and target.stat().st_size==member.file_size:
                crc=0
                with target.open('rb') as current:
                    for block in iter(lambda:current.read(4*1024*1024),b''):crc=zlib.crc32(block,crc)
                if crc==member.CRC:continue
            target.parent.mkdir(exist_ok=True,parents=True)
            temp=target.with_name(target.name+'.installing')
            with archive.open(member) as src,temp.open('wb') as out:shutil.copyfileobj(src,out)
            temp.replace(target)

def extract_llama():
    manifest=json.loads((ROOT/'models/assistant-manifest.json').read_text())
    for archive_name in ['llama.zip','cudart.zip']:
        path=ROOT/'apps/llama-downloads'/archive_name
        if not path.exists():continue
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                if member.is_dir():continue
                name='apps/llama/'+member.filename
                if name not in manifest['llama_files']:raise ValueError('Unpinned llama archive member')
                data=archive.read(member)
                if hashlib.sha256(data).hexdigest()!=manifest['llama_files'][name]:raise ValueError('Runtime integrity failure')
                target=target_path(name);target.parent.mkdir(parents=True,exist_ok=True)
                temp=target.with_name(target.name+'.installing');temp.write_bytes(data);temp.replace(target)

def extract_lama(path):
    from scripts.setup_major_editing import generator_weights
    manifest=json.loads((ROOT/'models/major-editing-manifest.json').read_text())
    with zipfile.ZipFile(path) as archive:
        for name in ('models/big-lama-generator.pth','models/config.yaml'):
            entry=manifest['files'][name]
            data=archive.read('big-lama/config.yaml') if name.endswith('yaml') else generator_weights(archive.read('big-lama/models/best.ckpt'))
            if len(data)!=entry['bytes'] or hashlib.sha256(data).hexdigest()!=entry['sha256']:raise ValueError('LaMa derived weights integrity failure')
            target=target_path(name);target.parent.mkdir(exist_ok=True,parents=True)
            temp=target.with_name(target.name+'.installing');temp.write_bytes(data);temp.replace(target)

def install(group, emit, marker):
    if group == 'all':
        # Runtime precedes LaMa conversion. A group completion must not unlock
        # the desktop while the rest of the setup still owns its job slot.
        required = sum(e['bytes'] for e in catalog().values()) * 3 + 1024**3
        if shutil.disk_usage(ROOT).free < required:
            raise ValueError(f'Need {required/1024**3:.1f} GiB free for complete setup')
        def progress(event):
            if event['type'] == 'setup_complete':
                event = {**event, 'type': 'setup_group_complete'}
            emit(event)
        for name in COMPLETE_GROUPS:
            if marker.exists():raise InterruptedError('Setup paused. Run complete setup again to resume.')
            install(name, progress, marker)
        from .vault import initialize
        initialize()
        if marker.exists():raise InterruptedError('Setup paused')
        emit({'type':'setup_complete','group':'all'})
        return {'installed':list(COMPLETE_GROUPS),'restartRecommended':True}
    entries={k:v for k,v in catalog().items() if v['group']==group}
    if not entries:raise ValueError('Unknown setup group')
    required=sum(e['bytes'] for e in entries.values())*3+1024**3
    if shutil.disk_usage(ROOT).free<required:raise ValueError(f'Need {required/1024**3:.1f} GiB free for download and extraction')
    cancelled=lambda:marker.exists()
    for name,entry in entries.items():
        if cancelled():raise InterruptedError('Setup paused')
        target=target_path(name)
        emit({'type':'setup_progress','file':name,'done':0,'total':entry['bytes']})
        download(entry['url'],target,entry['bytes'],entry['sha256'],
                 lambda count:emit({'type':'setup_progress','file':name,'done':count,'total':entry['bytes']}),cancelled)
        if entry.get('extract')=='wheel':extract_wheel(target,cancelled)
        if entry.get('extract')=='lama':extract_lama(target)
    if group=='assistant':extract_llama()
    if group=='runtime':
        import importlib
        importlib.invalidate_caches()
    if group=='obsidian':
        import subprocess
        # Reuse the pinned portable extraction and publisher check. No system install.
        flags={'creationflags':subprocess.CREATE_NO_WINDOW}
        signature=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',
            "$ErrorActionPreference='Stop'; Import-Module (Join-Path $PSHOME 'Modules/Microsoft.PowerShell.Security/Microsoft.PowerShell.Security.psd1'); "
            "$s=Get-AuthenticodeSignature -LiteralPath $env:PHOTO_OBSIDIAN_INSTALLER; if ($s.Status -ne 'Valid' -or $s.SignerCertificate.Subject -notlike '*O=Dynalist Inc*') {exit 1}"],
            env={**os.environ,'PHOTO_OBSIDIAN_INSTALLER':str(ROOT/'.cache/Obsidian-1.13.7.exe')},capture_output=True,**flags)
        if signature.returncode:raise ValueError('Obsidian publisher signature validation failed')
        commands=[
            [str(ROOT/'.cache/7zr.exe'),'x',str(ROOT/'.cache/7z2603-x64.exe'),'-o'+str(ROOT/'.cache/7zip'),'-y'],
            [str(ROOT/'.cache/7zip/7z.exe'),'x',str(ROOT/'.cache/Obsidian-1.13.7.exe'),'-o'+str(ROOT/'.cache/obsidian-installer'),'-i!$PLUGINSDIR\\app-64.7z','-y'],
            [str(ROOT/'.cache/7zip/7z.exe'),'x',str(ROOT/'.cache/obsidian-installer/$PLUGINSDIR/app-64.7z'),'-o'+str(ROOT/'apps/Obsidian'),'-y']]
        for command in commands:
            if cancelled():raise InterruptedError('Setup paused during Obsidian extraction')
            subprocess.run(command,check=True,capture_output=True,**flags)
        if not (ROOT/'apps/Obsidian/Obsidian.exe').is_file():raise ValueError('Obsidian extraction did not produce the application')
        from .vault import initialize
        initialize()
    if cancelled():raise InterruptedError('Setup paused; run repair to verify completion')
    (ROOT/'desktop').mkdir(parents=True,exist_ok=True)
    json_write(ROOT/'desktop'/('installed-'+group+'.json'),{'group':group,'verified':True})
    emit({'type':'setup_complete','group':group})
    return {'installed':group,'restartRecommended':group=='runtime'}
