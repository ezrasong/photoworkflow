import hashlib
import json
from pathlib import Path
import re
import shutil
import time
import uuid

import numpy as np
from PIL import Image

from . import VERSION
from .imaging import decode_working, stable_read, save_rgb, save_mask, preview
from .photoshop import write_import
from .references import write_review, local_path
from .runtime import ROOT, json_write, sha256, workspace_path, check_cancel, job_lock

class Pipeline:
    def __init__(self, output=ROOT / 'outputs'):
        self.output = workspace_path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.models = None

    def process(self, path, scale=1, blend=.35, allow_8bit=False, context=None, settle=2.0, bit_depth=16, recipe=None, upscale_strength=None, upscale_model='mambairv2'):
        cache = ROOT / '.cache'; cache.mkdir(exist_ok=True)
        with job_lock(cache / 'gpu.lock'):
            try:
                return self._process(path, scale, blend, allow_8bit, context, settle, bit_depth, recipe, upscale_strength, upscale_model)
            finally:
                self.release_models()

    def release_models(self):
        if self.models is not None:
            torch = self.models.torch
            self.models = None
            torch.cuda.empty_cache()

    def _process(self, path, scale=1, blend=.35, allow_8bit=False, context=None, settle=2.0, bit_depth=16, recipe=None, upscale_strength=None, upscale_model='mambairv2'):
        check_cancel()
        if scale not in (1, 2, 4) or not 0 <= blend <= 1 or bit_depth not in (8, 16):
            raise ValueError('Scale must be 1, 2 or 4; blend must be between 0 and 1')
        if upscale_strength is not None:
            if upscale_model not in ('mambairv2', 'realesrgan'):
                raise ValueError('Unknown upscale model')
            if isinstance(upscale_strength, bool) or not isinstance(upscale_strength, (int, float)) or not 0 <= upscale_strength <= .5:
                raise ValueError('Conservative upscale detail strength must be between 0 and 0.5')
            if scale not in (2, 4) or bit_depth != 16 or recipe is not None:
                raise ValueError('Conservative upscale uses 2x/4x and 16-bit output; run grading as a separate stage')
        masks = {}; mask_hashes = {}
        if recipe is not None:
            from .edits import prepare
            if scale != 1 or bit_depth != 16:
                raise ValueError('Editing uses original dimensions and 16-bit output')
            recipe, masks, mask_hashes = prepare(recipe, settle)
        path = local_path(path)
        if path.is_relative_to(self.output):
            raise ValueError('Input must be outside the output folder')
        started = time.monotonic()
        data = stable_read(path, settle)
        original_hash = hashlib.sha256(data).hexdigest()
        settings = {'version': VERSION, 'scale': scale, 'blend': blend, 'allow_8bit': allow_8bit,
                    'context': context, 'bit_depth': bit_depth, 'model_manifest': sha256(ROOT / 'models/manifest.json')}
        if recipe is not None:
            settings.update(edit_version=1, recipe=recipe, mask_hashes=mask_hashes,
                            edit_models=sha256(ROOT / 'models/assistant-manifest.json'))
            if recipe['denoise'] and recipe.get('denoise_model') == 'scunet':
                settings['denoise_manifest'] = sha256(ROOT / 'models/scunet-manifest.json')
            if any(k in recipe for k in ('selection', 'inpaint', 'restore_faces', 'denoise_scope')):
                settings['regional_edit_version'] = 1
                if 'selection' in recipe or 'inpaint' in recipe:
                    settings['regional_models'] = sha256(ROOT/'models/major-editing-manifest.json')
        if upscale_strength is not None:
            settings.update(upscale_version=2, upscale_strength=upscale_strength, face_restoration=False,
                            upscale_model=upscale_model)
            if upscale_model == 'mambairv2' and upscale_strength:
                settings['upscale_manifest'] = sha256(ROOT / 'models/mambairv2-manifest.json')
        identity = hashlib.sha256(data + json.dumps(settings, sort_keys=True).encode()).hexdigest()
        # Same content and settings intentionally deduplicate, regardless of filename.
        destination = self.output / identity[:24]
        lock_folder = self.output / '.locks'; lock_folder.mkdir(exist_ok=True)
        with job_lock(lock_folder / (identity + '.lock')):
            if destination.exists():
                job = json.loads((destination / 'job.json').read_text(encoding='utf-8'))
                if job['job_id'] != identity:
                    raise RuntimeError('Output hash collision')
                for name, checksum in job['artifacts'].items():
                    if sha256(destination / name) != checksum:
                        raise RuntimeError('Output was modified; choose another --output folder to rerun')
                return destination, True
            temporary = self.output / ('.partial-' + uuid.uuid4().hex)
            temporary.mkdir()
            try:
                import cv2
                rgb, conversions = decode_working(data, bit_depth, allow_8bit)
                width, height = rgb.shape[1] * scale, rgb.shape[0] * scale
                maximum = np.iinfo(rgb.dtype).max
                extension = '.tif' if bit_depth == 16 else '.png'
                if width * height > 64_000_000 or max(width, height) > 30_000:
                    raise ValueError('Output exceeds 64 megapixels or PSD 30,000-pixel dimension limit')
                (temporary / ('source' + path.suffix.lower())).write_bytes(data)
                original = cv2.resize(rgb, (width, height), interpolation=cv2.INTER_LANCZOS4) if scale != 1 else rgb
                baseline_file = 'original' + extension
                save_rgb(temporary / baseline_file, original)
                if scale != 1:
                    conversions.append('Original baseline resized with Lanczos to match output canvas')
                inference_start = time.monotonic()
                layers = []; face_count = 0
                runtime = {'method': 'deterministic float32 edits', 'restoration_invoked': False, 'upscale_invoked': False}
                if recipe is not None:
                    from .edits import edit_layers
                    composite = rgb.copy()
                    json_write(temporary / 'recipe.json', recipe)
                    for index, (name, pixels, mask, opacity, composite) in enumerate(edit_layers(rgb, recipe, masks, temporary), 1):
                        check_cancel()
                        asset = f'edit-{index:02}'
                        save_rgb(temporary / (asset + extension), pixels)
                        save_mask(temporary / (asset + '-mask' + extension), mask)
                        layers.append({'file': asset + extension, 'mask': asset + '-mask' + extension,
                                       'name': name, 'opacity': opacity * 100})
                    if recipe['denoise']:
                        import torch
                        runtime.update(denoiser='SCUNet color real_psnr' if recipe.get('denoise_model') == 'scunet' else 'DRUNet color',
                                       precision='float32; uint16 output', torch=torch.__version__, cuda=torch.version.cuda,
                                       gpu=torch.cuda.get_device_name(0), tiling='384 px cores, 64 px context')
                    runtime['removal'] = 'User-selected clone donor; synthetic replacement' if 'removal' in recipe else None
                    runtime['denoise_scope'] = recipe.get('denoise_scope', 'whole_image')
                    for name in ('inpaint', 'face'):
                        info = temporary/(name+'-runtime.json')
                        if info.exists():
                            runtime[name] = json.loads(info.read_text(encoding='utf-8'))
                    runtime['restoration_invoked'] = 'face' in runtime
                    runtime['inpainting_invoked'] = 'inpaint' in runtime
                    if 'face' in runtime:
                        face_count = len(runtime['face']['selection']['selected_indices'])
                    for selection in temporary.glob('*-selection.json'):
                        record = json.loads(selection.read_text(encoding='utf-8'))
                        record.update(source_file_sha256=original_hash, job_id=identity)
                        json_write(selection, record)
                elif upscale_strength is not None:
                    composite = original.copy()
                    model_name = 'MambaIRv2 Large' if upscale_model == 'mambairv2' else 'Real-ESRGAN'
                    runtime = {'method': f'Lanczos baseline with optional {model_name} detail layer',
                               'upscale_model': upscale_model,
                               'restoration_invoked': False, 'upscale_invoked': bool(upscale_strength),
                               'reference_conditioned': False, 'detail_strength': upscale_strength}
                    if upscale_strength:
                        if upscale_model == 'mambairv2':
                            from .mambair import MambaUpscaler
                            self.models = MambaUpscaler()
                        else:
                            from .models import Models
                            self.models = Models(restoration=False)
                        detail = self.models.upscale(rgb, scale)
                        composite = np.clip(np.rint(original.astype(np.float32) * (1 - upscale_strength) +
                                                   detail.astype(np.float32) * upscale_strength), 0, maximum).astype(rgb.dtype)
                        save_rgb(temporary / ('upscaled' + extension), detail)
                        save_mask(temporary / ('upscale-mask' + extension), np.full((height, width), maximum, rgb.dtype))
                        layers.append({'file': 'upscaled' + extension, 'mask': 'upscale-mask' + extension,
                                       'name': f'{model_name} detail - review texture', 'opacity': upscale_strength * 100})
                        self.models.torch.cuda.synchronize()
                        runtime.update(self.models.info())
                else:
                    from .models import Models
                    if self.models is None:
                        self.models = Models()
                    composite = self.models.upscale(rgb, scale) if scale != 1 else rgb.copy()
                    layers = []
                    if scale != 1:
                        save_rgb(temporary / ('upscaled' + extension), composite)
                        save_mask(temporary / ('upscale-mask' + extension), np.full((height, width), maximum, rgb.dtype))
                        layers.append({'file': 'upscaled' + extension, 'mask': 'upscale-mask' + extension,
                                       'name': 'Real-ESRGAN background', 'opacity': 100})
                    face_count = 0
                    for face_count, (face, mask, crop) in enumerate(self.models.faces(rgb, scale), 1):
                        name = f'face-{face_count:02}'
                        save_rgb(temporary / (name + extension), face)
                        save_rgb(temporary / (name + '-crop' + extension), crop)
                        save_mask(temporary / (name + '-mask' + extension), mask)
                        alpha = mask[:, :, None].astype(np.float32) / maximum * blend
                        composite = np.clip(np.rint(face * alpha + composite * (1 - alpha)), 0, maximum).astype(rgb.dtype)
                        layers.append({'file': name + extension, 'mask': name + '-mask' + extension,
                                       'name': f'GFPGAN face {face_count}', 'opacity': blend * 100})
                    self.models.torch.cuda.synchronize()
                    runtime = self.models.info()
                check_cancel()
                inference_seconds = time.monotonic() - inference_start
                composite_file = 'composite' + extension
                save_rgb(temporary / composite_file, composite)
                before = preview(original, (1600, 1600)); after = preview(composite, (1600, 1600))
                comparison = Image.new('RGB', (before.width * 2, before.height))
                comparison.paste(before); comparison.paste(after, (before.width, 0))
                save_rgb(temporary / 'comparison.jpg', comparison)
                write_import(temporary, width, height, layers, bit_depth, baseline_file)
                write_review(temporary, context)
                for key, (mask_path, _) in masks.items():
                    if sha256(mask_path) != mask_hashes[key]:
                        raise RuntimeError('Mask changed during processing; retry after saving it')
                    sidecar = mask_path.with_suffix('.json')
                    actual = sha256(sidecar) if sidecar.exists() else None
                    if actual != mask_hashes.get(key+'-binding'):
                        raise RuntimeError('Mask binding changed during processing; result discarded')
                if sha256(path) != original_hash:
                    raise RuntimeError('Source changed during processing; result discarded, retry after writing finishes')
                report = {'job_id': identity, 'source_sha256': original_hash, 'source_name': path.name,
                    'settings': settings, 'input_size': [rgb.shape[1], rgb.shape[0]], 'output_size': [width, height],
                    'bit_depth': bit_depth, 'baseline_file': baseline_file, 'composite_file': composite_file,
                    'faces': face_count, 'layers': layers, 'conversions': conversions,
                    'inference_seconds': inference_seconds, 'total_seconds': time.monotonic() - started,
                    'runtime': runtime, 'network': 'Python socket egress and subprocesses denied',
                    'adobe': 'Not exported; run photoshop command or import-photoshop.jsx',
                    'artifacts': {p.name: sha256(p) for p in temporary.iterdir() if p.is_file()}}
                json_write(temporary / 'job.json', report)
                check_cancel()
                temporary.rename(destination)
                return destination, False
            except BaseException as error:
                # Delete only this job's known workspace temporary directory.
                shutil.rmtree(temporary)
                errors = self.output / 'errors'; errors.mkdir(exist_ok=True)
                json_write(errors / (uuid.uuid4().hex + '.json'), {
                    'source_name': path.name, 'source_sha256': original_hash,
                    'error_type': type(error).__name__, 'error': str(error),
                    'settings': settings, 'seconds': time.monotonic() - started})
                error.workflow_logged = True
                # process() releases whichever model owns this job in its finally block.
                raise
