"""Record installation hashes after the pinned source/weights/kernel build."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
names = ['models/mambairv2_classicSR_Large_x2.pth', 'models/mambairv2_classicSR_Large_x4.pth',
         'apps/MambaIR/options/test_MambaIRv2_SRLarge_x2.yml',
         'apps/MambaIR/options/test_MambaIRv2_SRLarge_x4.yml',
         'apps/MambaIR/basicsr/archs/mambairv2_arch.py',
         'apps/mamba-scan-build/selective_scan_cuda.pyd', 'scripts/build_mamba_scan.py',
         'photo_workflow/mamba_scan.py', 'photo_workflow/mambair.py']
manifest = {'architecture_source': 'https://github.com/csguoh/MambaIR',
    'revision': '33d7b3460c4665229334cc8de38c7f4c766ed3be',
    'weights_release': 'https://github.com/csguoh/MambaIR/releases/tag/v1.0',
    'scan_source': 'https://github.com/state-spaces/mamba/tree/v2.2.5',
    'architecture_patch': 'Selective-scan import redirected to inference-only local CUDA adapter',
    'kernel_patches': 'NVIDIA branches selected; static constexpr BOOL_SWITCH; forward-only binding; Windows build flags',
    'files': {}}
for name in names:
    p = root / name
    with p.open('rb') as f:
        digest = hashlib.file_digest(f, 'sha256').hexdigest()
    manifest['files'][name] = {'sha256': digest, 'bytes': p.stat().st_size}
(root/'models/mambairv2-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
