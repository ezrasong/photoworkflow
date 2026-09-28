"""Pinned MambaIRv2 Large classical SR, tiled float32 CUDA inference."""
import importlib.util
import json
import sys

from .runtime import asset_path, ROOT, check_cancel, sha256


class MambaUpscaler:
    tile = 192
    context = 32
    seed = 10

    def __init__(self):
        import torch
        import torchvision.transforms.functional as functional
        sys.modules.setdefault('torchvision.transforms.functional_tensor', functional)
        if not torch.cuda.is_available():
            raise RuntimeError('MambaIRv2 requires the local NVIDIA CUDA GPU')
        if torch.cuda.get_device_capability(0) != (12, 0):
            raise RuntimeError('This MambaIRv2 native build requires compute capability 12.0 (RTX 50-series). Choose Real-ESRGAN explicitly on other supported CUDA hardware.')
        self.torch = torch
        self.manifest = json.loads((ROOT / 'models/mambairv2-manifest.json').read_text())
        for name, entry in self.manifest['files'].items():
            if sha256(asset_path(name)) != entry['sha256']:
                raise RuntimeError('MambaIRv2 checksum mismatch: ' + name)
        name = 'photo_workflow._mambairv2_arch'
        if name not in sys.modules:
            spec = importlib.util.spec_from_file_location(name, ROOT / 'apps/MambaIR/basicsr/archs/mambairv2_arch.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            sys.modules[name] = module
        self.architecture = sys.modules[name].MambaIRv2
        self.model = None
        self.scale = None

    def upscale(self, rgb, scale):
        import numpy as np
        import yaml
        torch = self.torch
        if scale not in (2, 4):
            raise ValueError('MambaIRv2 supports native 2x or 4x only')
        if rgb.dtype not in (np.uint8, np.uint16) or rgb.ndim != 3 or rgb.shape[2] != 3:
            raise ValueError('MambaIRv2 expects uint8/uint16 RGB')
        check_cancel()
        if self.scale != scale:
            self.model = None
            torch.cuda.empty_cache()
            config = yaml.safe_load((ROOT / f'apps/MambaIR/options/test_MambaIRv2_SRLarge_x{scale}.yml').read_text())['network_g']
            config.pop('type')
            with torch.random.fork_rng(devices=[0]):
                torch.manual_seed(self.seed)
                model = self.architecture(**config)
            state = torch.load(ROOT / f'models/mambairv2_classicSR_Large_x{scale}.pth', map_location='cpu', weights_only=True)
            model.load_state_dict(state.get('params_ema', state.get('params', state)), strict=True)
            self.model = model.eval().to('cuda')
            self.scale = scale
        maximum = np.iinfo(rgb.dtype).max
        height, width = rgb.shape[:2]
        result = np.empty((height * scale, width * scale, 3), dtype=rgb.dtype)
        with torch.inference_mode(), torch.random.fork_rng(devices=[0]), torch.backends.cudnn.flags(benchmark=False, deterministic=True, allow_tf32=False):
            torch.manual_seed(self.seed)
            for y in range(0, height, self.tile):
                for x in range(0, width, self.tile):
                    check_cancel()
                    x1, y1 = min(x + self.tile, width), min(y + self.tile, height)
                    # Align context to the architecture's 16-pixel window grid.
                    px, py = max(0, x-self.context), max(0, y-self.context)
                    qx, qy = min(width, x1+self.context), min(height, y1+self.context)
                    pixels = rgb[py:qy, px:qx].astype(np.float32) / maximum
                    # Upstream padding doubles at most once; tiny images need >=8px.
                    pixels = np.pad(pixels, ((0,max(0,8-pixels.shape[0])), (0,max(0,8-pixels.shape[1])), (0,0)), mode='edge')
                    tensor = torch.from_numpy(pixels.transpose(2,0,1).copy()).unsqueeze(0).cuda()
                    output = self.model(tensor)
                    if not torch.isfinite(output).all():
                        raise RuntimeError('MambaIRv2 produced nonfinite pixels; output discarded')
                    output = output[0, :, (y-py)*scale:(y1-py)*scale, (x-px)*scale:(x1-px)*scale]
                    pixels = output.float().clamp(0,1).permute(1,2,0).cpu().numpy()
                    result[y*scale:y1*scale, x*scale:x1*scale] = np.rint(pixels*maximum).astype(rgb.dtype)
        check_cancel()
        return result

    def info(self):
        return {'upscaler': 'MambaIRv2 Large classical SR', 'native_scale': self.scale,
                'kernel': 'upstream Mamba 2.2.5 selective_scan CUDA; Windows compatibility build',
                'precision': 'float32', 'seed': self.seed, 'tile_core': self.tile, 'tile_context': self.context,
                'torch': self.torch.__version__, 'cuda_runtime': self.torch.version.cuda,
                'gpu': self.torch.cuda.get_device_name(0), 'models': self.manifest}
