"""Bounded, file-only bridge to the workspace Lightroom Classic SDK plug-in."""
import json
import math
import time
import uuid

from .runtime import ROOT, check_cancel, json_write

QUEUE = ROOT / '.cache/lightroom'
INPUT_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.tif', '.tiff', '.dng', '.cr2', '.cr3',
                    '.nef', '.nrw', '.arw', '.raf', '.orf', '.rw2', '.pef', '.heic', '.heif'}
# Native Lightroom units; absolute settings, not relative deltas.
LIMITS = {'Exposure2012': (-3, 3), 'Contrast2012': (-100, 100),
          'Highlights2012': (-100, 100), 'Shadows2012': (-100, 100),
          'Whites2012': (-100, 100), 'Blacks2012': (-100, 100),
          'Vibrance': (-100, 100), 'Saturation': (-100, 100),
          'Temperature': (2000, 50000), 'Tint': (-150, 150),
          'SaturationAdjustmentPurple': (-100, 100),
          'LuminanceSmoothing': (0, 100), 'ColorNoiseReduction': (0, 100),
          'LuminanceNoiseReductionDetail': (0, 100), 'LuminanceNoiseReductionContrast': (0, 100),
          'ColorNoiseReductionDetail': (0, 100), 'ColorNoiseReductionSmoothness': (0, 100)}
LIMITS.update({
    'CropTop': (0, 1), 'CropBottom': (0, 1), 'CropLeft': (0, 1), 'CropRight': (0, 1),
    'CropAngle': (-15, 15), 'ParametricShadows': (-100, 100), 'ParametricDarks': (-100, 100),
    'ParametricLights': (-100, 100), 'ParametricHighlights': (-100, 100),
    'LensProfileEnable': (0, 1), 'AutoLateralCA': (0, 1),
    'LensManualDistortionAmount': (-100, 100), 'VignetteAmount': (-100, 100),
    'VignetteMidpoint': (0, 100)})
CURVES = {'ToneCurvePV2012', 'ToneCurvePV2012Red', 'ToneCurvePV2012Green', 'ToneCurvePV2012Blue'}
CROP = {'CropTop', 'CropBottom', 'CropLeft', 'CropRight'}


def source_encoding(source):
    """Read DNG layout tags only; never assume every DNG is a sensor mosaic."""
    from pathlib import Path
    path = Path(source)
    if path.suffix.lower() != '.dng':
        return 'rendered' if path.suffix.lower() in {'.jpg', '.jpeg', '.png', '.tif', '.tiff', '.heic', '.heif'} else 'camera_raw'
    import tifffile
    try:
        with tifffile.TiffFile(path) as tif:
            pending = list(tif.pages)
            found = set()
            for _ in range(128):
                if not pending: break
                page = pending.pop()
                tag = page.tags.get('PhotometricInterpretation')
                if tag and int(tag.value) in (32803, 34892): found.add(int(tag.value))
                if page.pages: pending.extend(page.pages)
            if not pending and len(found) == 1:
                return 'mosaic_dng' if 32803 in found else 'linear_dng'
    except (OSError, ValueError, TypeError, KeyError, IndexError, tifffile.TiffFileError):
        pass
    return 'unknown_dng'


def validate_curve(values):
    if not isinstance(values, list) or not 4 <= len(values) <= 32 or len(values) % 2:
        raise ValueError('Curve needs 2–16 x,y points in a flat list')
    if any(type(v) is not int or not 0 <= v <= 255 for v in values):
        raise ValueError('Curve points must be integers from 0 to 255')
    if values[0] != 0 or values[-2] != 255 or any(a >= b for a, b in zip(values[::2], values[2::2])):
        raise ValueError('Curve inputs must increase strictly from 0 to 255')
    if any(a > b for a, b in zip(values[1::2], values[3::2])):
        raise ValueError('Curve outputs must not decrease')
    return values


def validate_settings(settings):
    if isinstance(settings, dict) and 'Crop' in settings:
        edges = settings['Crop']
        if not isinstance(edges, list) or len(edges) != 4 or CROP & settings.keys():
            raise ValueError('Crop is one [left, top, right, bottom] rectangle; do not mix crop formats')
        settings = {k:v for k,v in settings.items() if k != 'Crop'}
        settings.update(zip(('CropLeft','CropTop','CropRight','CropBottom'),edges))
    if not isinstance(settings, dict) or not settings or set(settings) - (set(LIMITS) | CURVES):
        raise ValueError('Supply supported Lightroom Develop settings')
    for key, value in settings.items():
        if key in CURVES:
            validate_curve(value)
            continue
        low, high = LIMITS[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f'{key} must be between {low} and {high}')
        if key in {'LensProfileEnable', 'AutoLateralCA'} and value not in (0, 1):
            raise ValueError(f'{key} must be 0 or 1')
    if CROP & settings.keys():
        if not CROP <= settings.keys(): raise ValueError('Supply all four absolute crop edges')
        if settings['CropRight'] - settings['CropLeft'] < .05 or settings['CropBottom'] - settings['CropTop'] < .05:
            raise ValueError('Crop must retain at least 5% on each axis')
    return settings


def request(operation, selection=None, settings=None, timeout=120, cancel_file=None,
            source=None, catalog=None):
    if operation not in {'status', 'develop', 'export', 'import_fixture', 'catalog', 'import_photo'}:
        raise ValueError('Unsupported Lightroom operation')
    if operation in {'develop', 'export'} or selection is not None:
        try: uuid.UUID(selection)
        except (ValueError, TypeError, AttributeError): raise ValueError('Read the current Lightroom selection first')
    fields = {'operation': operation, 'expires': str(int(time.time() + 25)), 'token': str(uuid.uuid4())}
    if operation == 'import_photo':
        from .references import local_path
        path = local_path(source)
        if not path.is_file() or path.suffix.lower() not in INPUT_EXTENSIONS:
            raise ValueError('Choose a supported local photograph')
        if not catalog:
            raise ValueError('Read the target Lightroom catalog first')
        fields['source'] = str(path)
    elif source is not None:
        raise ValueError('Source paths are accepted only by the controller import operation')
    if catalog is not None:
        from .references import local_path
        fields['catalog'] = str(local_path(catalog))
    if any(any(c in value for c in '\t\r\n\0') for value in fields.values()):
        raise ValueError('Invalid queue field')
    if selection: fields['selection'] = selection
    if settings: fields.update({k: ','.join(map(str, v)) if isinstance(v, list) else str(v)
                                for k, v in validate_settings(settings).items()})
    if operation == 'develop' and not settings: raise ValueError('No Develop settings')
    QUEUE.mkdir(parents=True, exist_ok=True)
    folder = QUEUE / uuid.uuid4().hex
    folder.mkdir()
    pending = folder / 'request.partial'
    pending.write_text(''.join(k + '\t' + v + '\n' for k, v in fields.items()), encoding='utf-8')
    pending.rename(folder / 'request.txt')
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            check_cancel()
            if cancel_file and cancel_file.exists(): raise RuntimeError('Lightroom request cancelled; an already-started catalog operation may finish. Inspect the copy before retrying.')
            response = folder / 'response.json'
            if response.exists():
                result = json.loads(response.read_text(encoding='utf-8'))
                if not result.get('ok'): raise RuntimeError(result.get('error', 'Lightroom request failed'))
                if result.get('source'):
                    result['source_encoding'] = source_encoding(result['source'])
                return result
            time.sleep(.15)
        raise TimeoutError('Lightroom did not respond. Open Lightroom and enable Photo Studio in Plug-in Manager. Do not retry an edit until checking its virtual copy.')
    finally:
        # A queued, unclaimed command must never execute after its caller has gone.
        (folder / 'request.txt').unlink(missing_ok=True)
