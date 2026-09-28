"""Pinned local Mask R-CNN / Big-LaMa installation; never called by inference."""
import collections
import hashlib
import io
import json
from pathlib import Path
import sys
import typing
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from photo_workflow.runtime import local_runtime, sha256


def adapt(name, data):
    if name.endswith('/ffc.py'):
        data = data.replace(b'from saicinpainting.utils import get_shape',
                            b'# Unused get_shape import removed; no training dependencies.')
    if name.endswith('/spatial_transform.py'):
        data = data.replace(b'from kornia.geometry.transform import rotate', b'# Optional training transform; lazy import below.')
        for signature in [b'    def transform(self, x):', b'    def inverse_transform(self, y_padded_rotated, orig_x):']:
            data = data.replace(signature, signature + b'\n        from kornia.geometry.transform import rotate')
    return data


def generator_weights(checkpoint):
    import torch
    # Only inert training metadata containers are permitted. Never unrestricted pickle.
    names = ['omegaconf.base.Metadata', 'omegaconf.dictconfig.DictConfig',
             'omegaconf.listconfig.ListConfig', 'omegaconf.nodes.AnyNode',
             'omegaconf.base.ContainerMetadata',
             'pytorch_lightning.callbacks.model_checkpoint.ModelCheckpoint']
    allowed = [(type(n.split('.')[-1], (), {}), n) for n in names]
    allowed += [(collections.defaultdict, 'collections.defaultdict'), (dict, 'builtins.dict'),
                (list, 'builtins.list'), (int, 'builtins.int'), (typing.Any, 'typing.Any')]
    with torch.serialization.safe_globals(allowed):
        value = torch.load(io.BytesIO(checkpoint), map_location='cpu', weights_only=True)
    state = {k.removeprefix('generator.'): v for k, v in value['state_dict'].items() if k.startswith('generator.')}
    if not state or any(not isinstance(v, torch.Tensor) for v in state.values()):
        raise ValueError('Invalid generator state dictionary')
    buffer = io.BytesIO(); torch.save(state, buffer)
    return buffer.getvalue()


def fetch(entry):
    import requests
    response = requests.get(entry['url'], timeout=180); response.raise_for_status()
    data = response.content
    if hashlib.sha256(data).hexdigest() != entry['sha256'] or len(data) != entry['bytes']:
        raise RuntimeError('Download checksum mismatch: ' + entry['url'])
    return data


def setup():
    local_runtime()
    manifest = json.loads((ROOT/'models/major-editing-manifest.json').read_text(encoding='utf-8'))
    archive = None
    for name, entry in manifest['files'].items():
        target = ROOT/name
        if target.exists() and sha256(target) == entry['sha256']:
            continue
        if entry.get('generated') == 'empty package initializer':
            data = b''
        elif 'generated' in entry:
            if archive is None:
                archive = zipfile.ZipFile(io.BytesIO(fetch(manifest['lama_archive'])))
            if name.endswith('config.yaml'):
                data = archive.read('big-lama/config.yaml')
            else:
                data = generator_weights(archive.read('big-lama/models/best.ckpt'))
        elif 'upstream_sha256' in entry:
            data = adapt(name, fetch(dict(entry, sha256=entry['upstream_sha256'], bytes=entry['upstream_bytes'])))
        else:
            data = fetch(entry)
        if len(data) != entry['bytes'] or hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise RuntimeError('Installed file checksum mismatch: ' + name)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix+'.partial')
        try:
            temporary.write_bytes(data); temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    print('Mask R-CNN / Big-LaMa pins verified. Existing Torch/CUDA/dependencies retained.')


if __name__ == '__main__':
    setup()
