"""Bounded 16-bit edits. Paths come from the user, never from model output."""
import hashlib
import json
import math
import sys

import cv2
import numpy as np

from .imaging import stable_read, save_mask, save_rgb
from .references import local_path
from .runtime import ROOT, check_cancel, sha256

DEFAULTS = dict(exposure=0.0, warmth=0.0, tint=0.0, contrast=1.0,
                shadows=0.0, highlights=0.0, saturation=1.0,
                purple_saturation=1.0, denoise=0.0, noise_sigma=15.0)
LIMITS = dict(exposure=(-3, 3), warmth=(-1, 1), tint=(-1, 1), contrast=(.5, 1.5),
              shadows=(-.3, .3), highlights=(-.3, .3), saturation=(0, 2),
              purple_saturation=(0, 2), denoise=(0, 1), noise_sigma=(1, 50))
REGIONAL_FIELDS = {'selection', 'denoise_scope', 'inpaint', 'restore_faces'}

def validate_recipe(value):
    if not isinstance(value, dict) or set(value) - set(DEFAULTS) - {'grade_mask', 'removal', 'denoise_model'} - REGIONAL_FIELDS:
        raise ValueError('Unknown edit recipe fields')
    result = dict(DEFAULTS)
    for key, (low, high) in LIMITS.items():
        v = value.get(key, DEFAULTS[key])
        if isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) or not low <= v <= high:
            raise ValueError(f'{key} must be a finite number in [{low}, {high}]')
        result[key] = float(v)
    # Missing model preserves historical recipes and the manual panel's DRUNet path.
    model = value.get('denoise_model', 'drunet')
    if not isinstance(model, str) or model not in ('drunet', 'scunet'):
        raise ValueError('Denoise model must be drunet or scunet')
    if 'denoise_model' in value:
        result['denoise_model'] = model
    if value.get('grade_mask'):
        result['grade_mask'] = str(local_path(value['grade_mask']))
    if value.get('removal') is not None:
        r = value['removal']
        if not isinstance(r, dict) or set(r) != {'mask', 'dx', 'dy', 'feather'}:
            raise ValueError('Clone removal needs mask, dx, dy and feather')
        for key in ('dx', 'dy', 'feather'):
            if type(r[key]) is not int:
                raise ValueError('Clone offsets and feather must be integer pixels')
        if not 0 <= r['feather'] <= 64 or abs(r['dx']) > 30000 or abs(r['dy']) > 30000:
            raise ValueError('Invalid clone offsets or feather (0–64 pixels)')
        if not r['dx'] and not r['dy']:
            raise ValueError('Choose a separate donor area for clone removal')
        result['removal'] = dict(r, mask=str(local_path(r['mask'])))
    from .selection import validate_target
    if 'selection' in value:
        s = value['selection']
        if not isinstance(s, dict) or set(s)-{'category', 'position', 'invert', 'feather'}:
            raise ValueError('Invalid automatic selection')
        target = validate_target({k: s[k] for k in ('category', 'position') if k in s})
        if type(s.get('invert', False)) is not bool:
            raise ValueError('Selection invert must be boolean')
        radius = s.get('feather', 0)
        if type(radius) is not int or not 0 <= radius <= 64:
            raise ValueError('Selection feather must be 0–64 integer pixels')
        if 'grade_mask' in result:
            raise ValueError('Choose an automatic selection or a supplied mask, not both')
        result['selection'] = dict(target, invert=s.get('invert', False), feather=radius)
    if 'denoise_scope' in value:
        if value['denoise_scope'] not in ('whole_image', 'selection'):
            raise ValueError('Invalid denoise scope')
        if value['denoise_scope'] == 'selection' and not ('selection' in result or 'grade_mask' in result):
            raise ValueError('Masked denoising requires a selection')
        result['denoise_scope'] = value['denoise_scope']
    if 'inpaint' in value:
        r = value['inpaint']
        if not isinstance(r, dict) or set(r)-{'target', 'mask', 'feather', 'expand'} or ('target' in r) == ('mask' in r):
            raise ValueError('Removal needs exactly one target or supplied mask')
        result['inpaint'] = ({'target': validate_target(r['target'])} if 'target' in r else {'mask': str(local_path(r['mask']))})
        for key, default, cap in [('feather', 4, 64), ('expand', 8, 32)]:
            v = r.get(key, default)
            if type(v) is not int or not 0 <= v <= cap:
                raise ValueError(f'Removal {key} must be an integer from 0 to {cap}')
            result['inpaint'][key] = v
        if 'removal' in result:
            raise ValueError('Choose clone or inpainting in one raster job')
    if 'restore_faces' in value:
        f = value['restore_faces']
        if not isinstance(f, dict) or set(f) != {'position', 'strength'}:
            raise ValueError('Face restoration needs position and strength')
        validate_target({'position': f['position']}, face=True)
        strength = f['strength']
        if isinstance(strength, bool) or not isinstance(strength, (int, float)) or not math.isfinite(strength) or not 0 <= strength <= .5:
            raise ValueError('Face strength must be 0–0.5; reconstructed detail can alter likeness')
        result['restore_faces'] = dict(f)
    return result

def prepare(value, settle):
    recipe = validate_recipe(value)
    masks = {}
    for key, path in [('grade', recipe.get('grade_mask')),
                      ('removal', recipe.get('removal', {}).get('mask')),
                      ('inpaint', recipe.get('inpaint', {}).get('mask'))]:
        if path:
            data = stable_read(path, settle)
            masks[key] = (local_path(path), data)
    identities = {k: hashlib.sha256(data).hexdigest() for k, (_, data) in masks.items()}
    for key, (path, _) in masks.items():
        if path.with_suffix('.json').exists():
            identities[key+'-binding'] = sha256(path.with_suffix('.json'))
    return recipe, masks, identities

def mask_pixels(data, shape):
    import io
    from PIL import Image
    with Image.open(io.BytesIO(data)) as im:
        if im.size != (shape[1], shape[0]) or getattr(im, 'n_frames', 1) != 1:
            raise ValueError('Mask must match the oriented input dimensions exactly')
    arr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
    if arr is None or arr.ndim != 2 or arr.dtype not in (np.uint8, np.uint16):
        raise ValueError('Use a single-channel unsigned 8/16-bit mask: white edits, black protects')
    if not np.any(arr):
        raise ValueError('Mask is empty; paint the intended area first')
    return np.rint(arr.astype(np.float32) / np.iinfo(arr.dtype).max * 65535).astype(np.uint16)

def quantize(x):
    return np.rint(np.clip(x, 0, 1) * 65535).astype(np.uint16)

def drunet(rgb, sigma):
    return _denoise(rgb, sigma, 'drunet')


def scunet(rgb):
    return _denoise(rgb, None, 'scunet')


def _denoise(rgb, sigma, name):
    """Pinned float32 CUDA inference, shared bounded tiles and cleanup."""
    import torch
    import torch.nn.functional as F
    check_cancel()
    if rgb.dtype != np.uint16 or rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError('Denoising requires uint16 RGB')
    is_scunet = name == 'scunet'
    manifest = json.loads((ROOT / ('models/scunet-manifest.json' if is_scunet else 'models/assistant-manifest.json')).read_text())
    files = tuple(manifest['files']) if is_scunet else ('models/drunet_color.pth', 'apps/DPIR/models/network_unet.py', 'apps/DPIR/models/basicblock.py')
    for file in files:
        if sha256(ROOT / file) != manifest['files'][file]['sha256']:
            raise RuntimeError('Denoiser checksum mismatch: ' + file)
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA unavailable; denoising requires the local NVIDIA GPU')
    if is_scunet:
        import contextlib
        import importlib.util
        import io
        spec = importlib.util.spec_from_file_location('photo_workflow_scunet', ROOT/'apps/SCUNet/network_scunet.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with contextlib.redirect_stdout(io.StringIO()):
            model = module.SCUNet(in_nc=3, config=[4]*7, dim=64, drop_path_rate=0.)
    else:
        # Import upstream modules in their original package; no installed files are changed.
        sys.path.insert(0, str(ROOT / 'apps/DPIR'))
        try:
            from models.network_unet import UNetRes
        finally:
            sys.path.pop(0)
        model = UNetRes(in_nc=4, out_nc=3, nc=[64,128,256,512], nb=4, act_mode='R',
                        downsample_mode='strideconv', upsample_mode='convtranspose')
    output = np.empty_like(rgb)
    h, w = rgb.shape[:2]
    previous_tf32 = (torch.backends.cuda.matmul.allow_tf32, torch.backends.cudnn.allow_tf32)
    try:
        if is_scunet:
            torch.backends.cuda.matmul.allow_tf32 = False
            torch.backends.cudnn.allow_tf32 = False
        weights = 'models/scunet_color_real_psnr.pth' if is_scunet else 'models/drunet_color.pth'
        model.load_state_dict(torch.load(ROOT / weights, map_location='cpu', weights_only=True), strict=True)
        model.eval().requires_grad_(False).cuda()
        with torch.inference_mode():
            for y in range(0, h, 384):
                for x in range(0, w, 384):
                    check_cancel()
                    y1, x1 = min(y+384, h), min(x+384, w)
                    ya, xa, yb, xb = max(0,y-64), max(0,x-64), min(h,y1+64), min(w,x1+64)
                    tile = torch.from_numpy(np.ascontiguousarray(rgb[ya:yb,xa:xb].transpose(2,0,1))).float().div_(65535).unsqueeze(0).cuda()
                    if is_scunet:
                        inp = tile  # SCUNet owns replication padding to multiples of 64.
                    else:
                        tile = F.pad(tile, (0, (-(xb-xa))%8, 0, (-(yb-ya))%8), mode='replicate')
                        inp = torch.cat((tile, torch.full_like(tile[:, :1], sigma/255)), dim=1)
                    result = model(inp)[0].permute(1,2,0).cpu().numpy()
                    if not np.isfinite(result).all():
                        raise RuntimeError('Nonfinite denoiser output')
                    output[y:y1,x:x1] = quantize(result[y-ya:y1-ya,x-xa:x1-xa])
                    del tile, inp, result
        torch.cuda.synchronize()
        check_cancel()
        return output
    finally:
        if is_scunet:
            torch.backends.cuda.matmul.allow_tf32, torch.backends.cudnn.allow_tf32 = previous_tf32
        del model
        torch.cuda.empty_cache()

def edit_layers(rgb, recipe, masks, folder):
    """Yield independent raster operations and their actual blend masks."""
    full = np.full(rgb.shape[:2], 65535, np.uint16)
    grade_mask = mask_pixels(masks['grade'][1], rgb.shape) if 'grade' in masks else full
    for key, (path, data) in masks.items():
        (folder / (key + '-source-mask' + path.suffix.lower())).write_bytes(data)
    current = rgb.copy()
    from .selection import automatic_mask, feather, save_selection, pixel_hash, assert_binding
    from .runtime import json_write
    # Bound supplied masks with sidecars are rejected even for same-size pixel/geometry changes.
    for key, (path, _) in masks.items():
        sidecar = path.with_suffix('.json')
        if sidecar.exists():
            record = json.loads(sidecar.read_text(encoding='utf-8'))
            assert_binding(record, rgb)
            if record.get('mask_sha256') != sha256(path):
                raise ValueError('Mask changed without updated binding; correct/save it locally again')
    def selected(name, pixels):
        if 'selection' not in recipe:
            record = {'method': 'explicit supplied mask' if 'grade' in masks else 'whole image',
                      'source_pixel_sha256': pixel_hash(pixels), 'dimensions': [pixels.shape[1], pixels.shape[0]],
                      'coordinate_transform': [1, 0, 0, 0, 1, 0]}
            mask = grade_mask
        else:
            s = recipe['selection']
            mask, record = automatic_mask(pixels, {k:s[k] for k in ('category', 'position')})
            if s['invert']:
                mask = 65535-mask
            mask = feather(mask, s['feather'])
            record.update(invert=s['invert'], feather=s['feather'])
        if 'selection' in recipe or 'grade' in masks:
            save_selection(folder, name, mask, record, pixels)
        return mask
    def layer(name, pixels, mask, opacity=1):
        nonlocal current
        a = mask[:,:,None].astype(np.float32) / 65535 * opacity
        current = np.clip(np.rint(pixels.astype(np.float32)*a + current.astype(np.float32)*(1-a)),0,65535).astype(np.uint16)
        return name, pixels, mask, opacity, current
    if recipe['denoise']:
        denoise_mask = selected('denoise', current) if recipe.get('denoise_scope') == 'selection' else full
        if recipe.get('denoise_model', 'drunet') == 'scunet':
            yield layer('SCUNet real PSNR denoise', scunet(current), denoise_mask, recipe['denoise'])
        else:
            yield layer('DRUNet denoise', drunet(current, recipe['noise_sigma']), denoise_mask, recipe['denoise'])
    if 'removal' in recipe:
        r = recipe['removal']; mask = mask_pixels(masks['removal'][1], rgb.shape)
        if np.count_nonzero(mask) > mask.size * .25:
            raise ValueError('Removal exceeds 25% of the image. Use a smaller mask and suitable donor; hidden content cannot be recovered.')
        # Feather inward only: pixels outside the painted mask stay exactly unchanged.
        if r['feather']:
            distance = cv2.distanceTransform((mask>0).astype(np.uint8), cv2.DIST_L2, 5)
            mask = np.rint(mask * np.minimum(distance / r['feather'], 1)).astype(np.uint16)
        yy, xx = np.nonzero(mask); sx, sy = xx+r['dx'], yy+r['dy']
        if sx.min()<0 or sy.min()<0 or sx.max()>=rgb.shape[1] or sy.max()>=rgb.shape[0]:
            raise ValueError('Donor area extends outside the image; choose another source point')
        if np.any(mask[sy,sx]):
            raise ValueError('Donor overlaps the removal mask; choose clear replacement pixels')
        copied = current.copy(); copied[yy,xx] = current[sy,sx]
        yield layer('Clone removal - synthetic replacement', copied, mask)
    if 'inpaint' in recipe:
        from .inpainting import inpaint
        r = recipe['inpaint']
        if 'target' in r:
            mask, record = automatic_mask(current, r['target'])
        else:
            mask = mask_pixels(masks['inpaint'][1], rgb.shape)
            record = {'method': 'explicit supplied mask', 'dimensions': [current.shape[1], current.shape[0]],
                      'source_pixel_sha256': pixel_hash(current), 'coordinate_transform': [1,0,0,0,1,0]}
        save_selection(folder, 'removal-target', mask, record, current)
        if r['expand']:
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2*r['expand']+1, 2*r['expand']+1))
            mask = cv2.dilate(mask, kernel)
        mask = feather(mask, r['feather'])
        save_selection(folder, 'removal-effective', mask, dict(record, expand=r['expand'], feather=r['feather']))
        replacement, runtime = inpaint(current, mask)
        json_write(folder/'inpaint-runtime.json', runtime)
        yield layer('Big-LaMa removal - estimated concealed content', replacement, mask)
    if recipe.get('restore_faces', {}).get('strength', 0):
        import time
        from .models import Models
        f = recipe['restore_faces']; model = Models()
        started = time.monotonic(); model.torch.cuda.reset_peak_memory_stats()
        face_input = current.copy()
        try:
            for index, (pixels, mask, crop) in enumerate(model.faces(face_input, 1, {'position': f['position']}), 1):
                save_rgb(folder/f'face-{index:02}-restored-crop.tif', crop)
                save_selection(folder, f'face-{index:02}', mask, dict(source_pixel_sha256=pixel_hash(face_input),
                    dimensions=[rgb.shape[1], rgb.shape[0]], coordinate_transform=model.face_selection['affine_matrices'][-1],
                    selection=model.face_selection), face_input)
                yield layer(f'GFPGAN selected face {index} - estimated detail; likeness may change', pixels, mask, f['strength'])
            model.torch.cuda.synchronize()
            json_write(folder/'face-runtime.json', dict(model.info(), selection=model.face_selection,
                seconds=time.monotonic()-started, peak_allocated_bytes=model.torch.cuda.max_memory_allocated(),
                precision='float32 restoration to uint16; uint8 detection; 512px aligned face'))
        finally:
            torch = model.torch; del model; torch.cuda.empty_cache()
    if any(recipe[k] != DEFAULTS[k] for k in DEFAULTS if k not in ('denoise', 'noise_sigma')):
        grade_mask = selected('grade', current)
    if recipe['exposure']:
        x = current.astype(np.float32)/65535
        linear = np.where(x<=.04045,x/12.92,((x+.055)/1.055)**2.4) * 2**recipe['exposure']
        x = np.where(linear<=.0031308,linear*12.92,1.055*np.maximum(linear,0)**(1/2.4)-.055)
        yield layer('Exposure', quantize(x), grade_mask)
    if recipe['warmth'] or recipe['tint']:
        x=current.astype(np.float32)/65535
        gains=np.array([2**(.35*recipe['warmth']+.15*recipe['tint']),2**(-.3*recipe['tint']),2**(-.35*recipe['warmth']+.15*recipe['tint'])],np.float32)
        yield layer('White balance and tint', quantize(x*gains), grade_mask)
    if recipe['contrast']!=1 or recipe['shadows'] or recipe['highlights']:
        x=current.astype(np.float32)/65535
        x=x+(recipe['contrast']-1)*(x-.5)*4*x*(1-x)
        x=x+recipe['shadows']*4*x*(1-x)**2+recipe['highlights']*4*x*x*(1-x)
        yield layer('Contrast and tonal curve',quantize(x),grade_mask)
    if recipe['saturation']!=1 or recipe['purple_saturation']!=1:
        x=current.astype(np.float32)/65535
        luma=np.sum(x*np.array([.2126,.7152,.0722],np.float32),axis=2,keepdims=True)
        hsv=cv2.cvtColor(x,cv2.COLOR_RGB2HSV)
        purple=np.maximum(0,1-np.abs(hsv[:,:,0]-285)/55)*np.minimum(1,hsv[:,:,1]*4)
        factor=recipe['saturation']*(1+(recipe['purple_saturation']-1)*purple[:,:,None])
        yield layer('Saturation and selective purple',quantize(luma+(x-luma)*factor),grade_mask)
