"""One pinned Big-LaMa generator, bounded native-pixel context, no remote fallback."""
import sys
import time

import numpy as np

from .runtime import ROOT, check_cancel
from .selection import verify_installation


def inpaint(rgb, mask):
    import torch
    verify_installation('inpaint')
    if rgb.dtype != np.uint16 or mask.dtype != np.uint16 or mask.shape != rgb.shape[:2] or not mask.any():
        raise ValueError('Inpainting requires RGB16 and a nonempty, aligned uint16 mask')
    if np.count_nonzero(mask) > mask.size*.25:
        raise ValueError('Removal exceeds 25% of the image. Concealed content cannot be reliably recovered.')
    yy, xx = np.nonzero(mask)
    x0, y0 = max(0, int(xx.min())-128), max(0, int(yy.min())-128)
    x1, y1 = min(rgb.shape[1], int(xx.max())+129), min(rgb.shape[0], int(yy.max())+129)
    if max(x1-x0, y1-y0) > 2048:
        raise ValueError('Removal context exceeds 2048px. Request a smaller target or an explicit crop; no automatic downsize.')
    if not torch.cuda.is_available():
        raise RuntimeError('Inpainting requires local CUDA')
    check_cancel(); started = time.monotonic(); torch.cuda.reset_peak_memory_stats()
    sys.path.insert(0, str(ROOT/'apps/LaMa'))
    try:
        from saicinpainting.training.modules.ffc import FFCResNetGenerator
    finally:
        sys.path.pop(0)
    model = FFCResNetGenerator(input_nc=4, output_nc=3, ngf=64, n_downsampling=3, n_blocks=18,
        add_out_act='sigmoid', init_conv_kwargs=dict(ratio_gin=0, ratio_gout=0, enable_lfu=False),
        downsample_conv_kwargs=dict(ratio_gin=0, ratio_gout=0, enable_lfu=False),
        resnet_conv_kwargs=dict(ratio_gin=.75, ratio_gout=.75, enable_lfu=False))
    model.load_state_dict(torch.load(ROOT/'models/big-lama-generator.pth', map_location='cpu', weights_only=True), strict=True)
    try:
        model.eval().requires_grad_(False).cuda()
        crop = rgb[y0:y1, x0:x1].astype(np.float32)/65535
        hole = (mask[y0:y1, x0:x1] > 0).astype(np.float32)
        # Upstream uses symmetric padding to modulo 8 and concatenates the binary hole.
        ph, pw = (-(y1-y0)) % 8, (-(x1-x0)) % 8
        crop = np.pad(crop, ((0, ph), (0, pw), (0, 0)), mode='symmetric')
        hole = np.pad(hole, ((0, ph), (0, pw)), mode='symmetric')
        tensor = torch.from_numpy(np.concatenate((crop*(1-hole[..., None]), hole[..., None]), axis=2).transpose(2, 0, 1).copy()).unsqueeze(0).cuda()
        with torch.inference_mode():
            result = model(tensor)[0].permute(1, 2, 0).cpu().numpy()
        if not np.isfinite(result).all():
            raise RuntimeError('Nonfinite inpainting result')
        check_cancel(); torch.cuda.synchronize()
        layer = rgb.copy()
        layer[y0:y1, x0:x1] = np.rint(np.clip(result[:y1-y0, :x1-x0], 0, 1)*65535).astype(np.uint16)
        return layer, {'model': 'Big-LaMa', 'context_rectangle': [x0, y0, x1, y1],
                       'padding_right_bottom': [pw, ph], 'resize': False, 'precision': 'float32 to uint16',
                       'device': torch.cuda.get_device_name(0), 'seconds': time.monotonic()-started,
                       'peak_allocated_bytes': torch.cuda.max_memory_allocated(),
                       'meaning': 'Estimated replacement, not recovered concealed content'}
    finally:
        del model
        torch.cuda.empty_cache()
