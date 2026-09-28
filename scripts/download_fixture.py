"""Installation-only public-domain NASA fixture, via scikit-image's pinned release."""
import hashlib
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
URL = 'https://raw.githubusercontent.com/scikit-image/scikit-image/v0.25.2/skimage/data/astronaut.png'
SHA = '88431cd9653ccd539741b555fb0a46b61558b301d4110412b5bc28b5e3ea6cb5'
path = ROOT / 'tests/fixtures/astronaut.png'
path.parent.mkdir(parents=True, exist_ok=True)
data = urllib.request.urlopen(URL, timeout=30).read()
if hashlib.sha256(data).hexdigest() != SHA:
    raise RuntimeError('Fixture checksum mismatch')
path.write_bytes(data)
print(path)
