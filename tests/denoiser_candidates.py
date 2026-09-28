"""Evaluation-only candidate loading. No runtime downloads or production registration."""
import contextlib
import importlib
import io
import json
import sys

import numpy as np
import torch

from photo_workflow.runtime import ROOT, check_cancel, sha256
from photo_workflow.edits import quantize


def verify_pins():
    manifest = json.loads((ROOT/'models/denoiser-evaluation-manifest.json').read_text())
    for name, entry in manifest['files'].items():
        if sha256(ROOT/name) != entry['sha256']:
            raise RuntimeError('Evaluation checksum mismatch: '+name)
    return manifest


def load_model(name):
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA required for this evaluation')
    # Import the isolated copied architectures, without touching installed BasicSR.
    sys.path.insert(0, str(ROOT/'apps'))
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            if name == 'nafnet':
                cls = importlib.import_module('denoiser_eval.naf_arch').NAFNet
                model = cls(width=64, enc_blk_nums=[2,2,4,8], middle_blk_num=12,
                            dec_blk_nums=[2,2,2,2])
                state = torch.load(ROOT/'models/denoiser-evaluation/NAFNet-SIDD-width64.pth',
                                   map_location='cpu', weights_only=True)['params']
            elif name == 'scunet':
                cls = importlib.import_module('denoiser_eval.scunet_arch').SCUNet
                model = cls(in_nc=3, config=[4]*7, dim=64, drop_path_rate=0.)
                state = torch.load(ROOT/'models/denoiser-evaluation/scunet_color_real_psnr.pth',
                                   map_location='cpu', weights_only=True)
            elif name == 'drunet':
                manifest = json.loads((ROOT/'models/assistant-manifest.json').read_text())
                for file in ('models/drunet_color.pth', 'apps/DPIR/models/network_unet.py',
                             'apps/DPIR/models/basicblock.py'):
                    assert sha256(ROOT/file) == manifest['files'][file]['sha256']
                sys.path.insert(0, str(ROOT/'apps/DPIR'))
                try:
                    cls = importlib.import_module('models.network_unet').UNetRes
                finally:
                    sys.path.pop(0)
                model = cls(in_nc=4, out_nc=3, nc=[64,128,256,512], nb=4, act_mode='R',
                            downsample_mode='strideconv', upsample_mode='convtranspose')
                state = torch.load(ROOT/'models/drunet_color.pth', map_location='cpu', weights_only=True)
            else:
                raise ValueError('Unknown evaluation model')
    finally:
        sys.path.pop(0)
    model.load_state_dict(state, strict=True)
    return model.eval().requires_grad_(False).cuda()


@torch.inference_mode()
def infer(model, name, rgb, sigma=15, tile=384, context=64):
    """Same core/context geometry as production DRUNet, uint16 RGB in and out."""
    assert rgb.dtype == np.uint16 and rgb.ndim == 3 and rgb.shape[2] == 3
    h, w = rgb.shape[:2]
    output = np.empty_like(rgb)
    for y in range(0, h, tile):
        for x in range(0, w, tile):
            check_cancel()
            y1, x1 = min(y+tile,h), min(x+tile,w)
            ya, xa, yb, xb = max(0,y-context), max(0,x-context), min(h,y1+context), min(w,x1+context)
            inp = torch.from_numpy(np.ascontiguousarray(rgb[ya:yb,xa:xb].transpose(2,0,1))).float().div_(65535).unsqueeze(0).cuda()
            if name == 'drunet':
                inp = torch.nn.functional.pad(inp,(0,(-(xb-xa))%8,0,(-(yb-ya))%8),mode='replicate')
                inp = torch.cat((inp,torch.full_like(inp[:,:1],sigma/255)),dim=1)
            result = model(inp)[0].permute(1,2,0).cpu().numpy()
            if not np.isfinite(result).all():
                raise RuntimeError('Nonfinite candidate output')
            output[y:y1,x:x1] = quantize(result[y-ya:y1-ya,x-xa:x1-xa])
    torch.cuda.synchronize()
    check_cancel()
    return output
