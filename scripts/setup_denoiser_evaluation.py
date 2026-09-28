"""Reproduce the pinned evaluation installation; does not register chat models."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from photo_workflow.runtime import local_runtime, sha256
import requests
from scripts.setup_scunet import adapt_scunet


def adapted_sources():
    source=ROOT/'docs/denoiser-research'
    norm=(source/'naf-util.py').read_text()
    norm=norm[norm.index('class LayerNormFunction'):norm.index('# handle multiple input')]
    naf=(source/'naf-arch.py').read_text().replace(
        'from basicsr.models.archs.arch_util import LayerNorm2d','from .naf_norm import LayerNorm2d').replace(
        'from basicsr.models.archs.local_arch import Local_Base','from .naf_local import Local_Base')
    scu=adapt_scunet((source/'scunet-arch.py').read_text())
    return {
        '__init__.py':'"""Pinned denoiser architectures for local evaluation only."""\n',
        'naf_norm.py':'# Extracted unchanged from pinned NAFNet arch_util.py. See LICENSE-NAFNet.txt\nimport torch\nfrom torch import nn\n\n'+norm,
        'naf_arch.py':naf, 'scunet_arch.py':scu,
    }


def setup():
    local_runtime()
    manifest=json.loads((ROOT/'models/denoiser-evaluation-manifest.json').read_text())
    for name,entry in manifest['files'].items():
        target=ROOT/name
        if name.startswith('apps/denoiser_eval/'):continue
        if target.exists() and sha256(target)==entry['sha256']:continue
        if not entry.get('url'):
            raise RuntimeError('Restore pinned source from workspace backup: '+name)
        target.parent.mkdir(parents=True,exist_ok=True)
        partial=target.with_suffix(target.suffix+'.partial')
        try:
            with requests.get(entry['url'],stream=True,timeout=(30,90)) as r:
                r.raise_for_status()
                with partial.open('wb') as f:
                    for block in r.iter_content(4*1024*1024):f.write(block)
            if partial.stat().st_size!=entry['bytes'] or sha256(partial)!=entry['sha256']:
                raise RuntimeError('Pinned download mismatch: '+name)
            partial.replace(target)
        finally:partial.unlink(missing_ok=True)
    # Build in memory and check the recorded adaptation before replacing any file.
    sources=adapted_sources()
    source=ROOT/'docs/denoiser-research'
    raw={'naf_local.py':(source/'naf-local.py').read_bytes(),
         'LICENSE-NAFNet.txt':(source/'naf-license.txt').read_bytes(),
         'LICENSE-SCUNet.txt':(source/'scunet-license.txt').read_bytes()}
    import hashlib
    for name,text in sources.items():
        # The original Windows installation used Path.write_text newline translation.
        raw[name]=text.replace('\n','\r\n').encode('utf-8')
    for name,data in raw.items():
        target=ROOT/'apps/denoiser_eval'/name
        entry=manifest['files'][target.relative_to(ROOT).as_posix()]
        if hashlib.sha256(data).hexdigest()!=entry['sha256']:
            raise RuntimeError('Architecture adaptation mismatch: '+name)
        if not target.exists() or sha256(target)!=entry['sha256']:
            target.parent.mkdir(parents=True,exist_ok=True)
            partial=target.with_suffix(target.suffix+'.partial')
            partial.write_bytes(data);partial.replace(target)
    for name,entry in manifest['files'].items():
        assert sha256(ROOT/name)==entry['sha256'],name
    print('All evaluation sources, checkpoints and fixtures verified. Production setup unchanged.')


if __name__=='__main__':setup()
