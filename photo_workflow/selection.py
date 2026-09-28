"""Local instance masks and strict positional selection in oriented render coordinates."""
import hashlib
import json
import time

import cv2
import numpy as np

from .runtime import ROOT, check_cancel, json_write, sha256


def pixel_hash(rgb):
    digest = hashlib.sha256(str((rgb.shape, rgb.dtype.str)).encode())
    digest.update(np.ascontiguousarray(rgb).tobytes())
    return digest.hexdigest()


def validate_target(value, face=False):
    required = {'position'} if face else {'category', 'position'}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError('Specify category and position (single, leftmost, rightmost or all)')
    if value['position'] not in ('single', 'leftmost', 'rightmost', 'all'):
        raise ValueError('Ambiguous target: specify single, leftmost, rightmost or all')
    if not face:
        from torchvision.models.detection import MaskRCNN_ResNet50_FPN_V2_Weights
        categories = MaskRCNN_ResNet50_FPN_V2_Weights.COCO_V1.meta['categories']
        if value['category'] not in categories or value['category'] in ('N/A', '__background__'):
            raise ValueError('Unsupported object category; use a COCO category or a locally painted mask')
    return dict(value)


def choose_indices(boxes, position, width):
    """Never substitute a largest/central object for an ambiguous singular request."""
    if not len(boxes):
        raise ValueError('No reliable target detected. Select/correct a mask locally; no pixels changed.')
    if position == 'all':
        return list(range(len(boxes)))
    if len(boxes) == 1:
        return [0]
    if position == 'single':
        raise ValueError(f'Ambiguous target: {len(boxes)} candidates. Specify leftmost/rightmost or supply a local mask.')
    centers = np.asarray([(b[0]+b[2])/2 for b in boxes])
    order = np.argsort(centers)
    if position == 'rightmost':
        order = order[::-1]
    if abs(centers[order[0]]-centers[order[1]]) < width*.05:
        raise ValueError('Targets overlap horizontally; use a local selection instead of guessing')
    return [int(order[0])]


def verify_installation(kind):
    manifest = json.loads((ROOT/'models/major-editing-manifest.json').read_text(encoding='utf-8'))
    for name, entry in manifest['files'].items():
        relevant = ('maskrcnn' in name) if kind == 'mask' else ('apps/LaMa/' in name or name.endswith(('big-lama-generator.pth', 'config.yaml')))
        if relevant and sha256(ROOT/name) != entry['sha256']:
            raise RuntimeError('Major editing checksum mismatch: ' + name)
    return manifest


def feather(mask, radius):
    if type(radius) is not int or not 0 <= radius <= 64:
        raise ValueError('Feather must be an integer from 0 to 64 pixels')
    if not radius:
        return mask.copy()
    distance = cv2.distanceTransform((mask > 0).astype(np.uint8), cv2.DIST_L2, 5)
    return np.rint(mask.astype(np.float32)*np.minimum(distance/radius, 1)).astype(np.uint16)


def automatic_mask(rgb, target):
    import torch
    import torchvision
    from torchvision.models.detection import maskrcnn_resnet50_fpn_v2, MaskRCNN_ResNet50_FPN_V2_Weights
    target = validate_target(target)
    manifest = verify_installation('mask')
    if torchvision.__version__ != manifest['torchvision_version']:
        raise RuntimeError('Unverified torchvision version for automatic masks')
    if not torch.cuda.is_available():
        raise RuntimeError('Automatic masks require the local CUDA GPU')
    check_cancel()
    started = time.monotonic(); torch.cuda.reset_peak_memory_stats()
    model = maskrcnn_resnet50_fpn_v2(weights=None, weights_backbone=None)
    model.load_state_dict(torch.load(ROOT/'models/maskrcnn_resnet50_fpn_v2_coco.pth', map_location='cpu', weights_only=True))
    # Bound mask materialization; model returns masks at this analysis size.
    h, w = rgb.shape[:2]; factor = min(1., 1333/max(h, w))
    aw, ah = max(1, round(w*factor)), max(1, round(h*factor))
    analysis = cv2.resize(rgb.astype(np.float32)/65535, (aw, ah), interpolation=cv2.INTER_AREA)
    try:
        model.eval().requires_grad_(False).cuda()
        with torch.inference_mode():
            result = model([torch.from_numpy(analysis.transpose(2, 0, 1).copy()).cuda()])[0]
        check_cancel()
        categories = MaskRCNN_ResNet50_FPN_V2_Weights.COCO_V1.meta['categories']
        label = categories.index(target['category'])
        candidates = ((result['labels'] == label) & (result['scores'] >= .5)).nonzero().flatten()
        boxes = result['boxes'][candidates].cpu().numpy()
        selected = choose_indices(boxes, target['position'], aw)
        indexes = candidates[selected]
        if bool((result['scores'][indexes] < .8).any()):
            raise ValueError('Target confidence below 0.8; use a local corrected mask')
        probabilities = result['masks'][indexes, 0].amax(0).cpu().numpy()
        # Finite support is essential for exact preservation outside the mask.
        binary = (probabilities >= .5).astype(np.uint8)
        mask = cv2.resize(binary, (w, h), interpolation=cv2.INTER_NEAREST).astype(np.uint16)*65535
        if not mask.any():
            raise ValueError('Selected target produced an empty mask')
        torch.cuda.synchronize()
        record = {'method': 'torchvision Mask R-CNN ResNet50 FPN v2 COCO', 'target': target,
                  'source_pixel_sha256': pixel_hash(rgb), 'dimensions': [w, h],
                  'analysis_dimensions': [aw, ah], 'coordinate_transform': [w/aw, 0, 0, 0, h/ah, 0],
                  'network_resize': 'torchvision min_size=800 max_size=1333; ROI masks 28x28, threshold .5',
                  'candidate_count': len(candidates), 'selected_boxes_analysis': boxes[selected].tolist(),
                  'scores': result['scores'][indexes].cpu().tolist(), 'device': torch.cuda.get_device_name(0),
                  'precision': 'float32; binary uint16 mask at original dimensions',
                  'seconds': time.monotonic()-started, 'peak_allocated_bytes': torch.cuda.max_memory_allocated(),
                  'manifest_sha256': sha256(ROOT/'models/major-editing-manifest.json')}
        return mask, record
    finally:
        del model
        torch.cuda.empty_cache()


def assert_binding(record, rgb):
    if record.get('dimensions') != [rgb.shape[1], rgb.shape[0]] or record.get('source_pixel_sha256') != pixel_hash(rgb):
        raise ValueError('Stale mask: source pixels/geometry changed. Recompute or correct on the current render.')


def save_selection(folder, name, mask, record, rgb=None):
    from .imaging import save_mask, save_rgb
    if rgb is not None:
        source = folder/(name+'-selection-source.tif'); save_rgb(source, rgb)
        record = dict(record, rendered_source_file=source.name)
    path = folder/(name+'-selection.tif'); save_mask(path, mask)
    json_write(folder/(name+'-selection.json'), dict(record, mask_file=path.name, mask_sha256=sha256(path)))
