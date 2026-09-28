"""Installation only. Official upstream release artifacts; never called by processing."""
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MODELS = {
    'GFPGANv1.4.pth': 'https://github.com/TencentARC/GFPGAN/releases/download/v1.3.0/GFPGANv1.4.pth',
    'RealESRGAN_x4plus.pth': 'https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth',
    'detection_Resnet50_Final.pth': 'https://github.com/xinntao/facexlib/releases/download/v0.1.0/detection_Resnet50_Final.pth',
    'parsing_parsenet.pth': 'https://github.com/xinntao/facexlib/releases/download/v0.2.2/parsing_parsenet.pth',
}

def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

if __name__ == '__main__':
    folder = ROOT / 'models'
    folder.mkdir(exist_ok=True)
    manifest = folder / 'manifest.json'
    prior = json.loads(manifest.read_text()) if manifest.exists() else {}
    result = {}
    for name, url in MODELS.items():
        target = folder / name
        if not target.exists():
            temp = target.with_suffix('.download')
            print('Downloading', name, flush=True)
            urllib.request.urlretrieve(url, temp)
            if name in prior and digest(temp) != prior[name]['sha256']:
                temp.unlink()
                raise RuntimeError('Model checksum mismatch: ' + name)
            temp.replace(target)
        sha = digest(target)
        if name in prior and sha != prior[name]['sha256']:
            raise RuntimeError('Existing model checksum mismatch: ' + name)
        result[name] = {'url': url, 'sha256': sha, 'bytes': target.stat().st_size}
        print(name, sha, flush=True)
    manifest.write_text(json.dumps(result, indent=2) + '\n')
