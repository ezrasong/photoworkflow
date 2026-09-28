"""Install the pinned production SCUNet files without new dependencies."""
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from photo_workflow.runtime import local_runtime, sha256
import requests


def adapt_scunet(source):
    return source.replace('from thop import profile\n','').replace(
        'from timm.models.layers import trunc_normal_, DropPath','from torch.nn.init import trunc_normal_').replace(
        'self.drop_path = DropPath(drop_path) if drop_path > 0. else nn.Identity()',
        "assert drop_path == 0., 'Evaluation build supports inference with drop_path=0 only'\n        self.drop_path = nn.Identity()")


def setup():
    local_runtime()
    manifest=json.loads((ROOT/'models/scunet-manifest.json').read_text())
    for name,entry in manifest['files'].items():
        target=ROOT/name
        if target.exists() and sha256(target)==entry['sha256']:continue
        if name.endswith('network_scunet.py'):
            original=manifest['upstream_architecture']
            r=requests.get(original['url'],timeout=60);r.raise_for_status()
            if hashlib.sha256(r.content).hexdigest()!=original['sha256']:
                raise RuntimeError('Upstream architecture checksum mismatch')
            data=adapt_scunet(r.text.replace('\r\n','\n')).replace('\n','\r\n').encode('utf-8')
        else:
            r=requests.get(entry['url'],timeout=90);r.raise_for_status();data=r.content
        if len(data)!=entry['bytes'] or hashlib.sha256(data).hexdigest()!=entry['sha256']:
            raise RuntimeError('Pinned SCUNet file mismatch: '+name)
        target.parent.mkdir(exist_ok=True,parents=True)
        temporary=target.with_suffix(target.suffix+'.partial')
        try:temporary.write_bytes(data);temporary.replace(target)
        finally:temporary.unlink(missing_ok=True)
    print('SCUNet real_psnr installed and verified; Torch/CUDA unchanged.')


if __name__=='__main__':setup()
