"""Explicit HEIF preparation: original retained, decoded RGB stored without loss."""
import hashlib
import io
from pathlib import Path

import numpy as np
import tifffile
from PIL import Image, ImageCms

from .imaging import SRGB, stable_read, validate_dimensions
from .runtime import check_cancel, json_write, sha256, workspace_path

EXTENSIONS = {'.heic', '.heif'}


def color_profile(info):
    """Keep embedded ICC bytes or describe supported SDR NCLX primaries in ICC."""
    nclx = info.get('nclx_profile') or {}
    xmp = info.get('xmp') or b''
    if isinstance(xmp, str): xmp = xmp.encode('utf-8')
    if any(marker in xmp.lower() for marker in (b'hdrgm:', b'gainmap', b'hdrgainmap')):
        raise ValueError('HEIF contains HDR gain-map metadata; no automatic flattening into SDR')
    if nclx.get('transfer_characteristics') in (16, 18):
        raise ValueError('HDR PQ/HLG HEIF requires an HDR workflow; no automatic tone mapping')
    if info.get('aux') or info.get('depth_images') or any(info.get(k) is not None for k in (
            'content_light_level', 'mastering_display_colour_volume', 'nominal_diffuse_white_luminance')):
        raise ValueError('HEIF has auxiliary/depth/HDR data. This SDR workflow cannot preserve all of it; original retained')
    icc = info.get('icc_profile')
    if icc:
        profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        if profile.profile.xcolor_space.strip() != 'RGB':
            raise ValueError('HEIF ICC must describe RGB color')
        description = ImageCms.getProfileDescription(profile).strip()
        if info['bit_depth'] > 8 and not any(name in description.casefold() for name in ('srgb', 'display p3', 'adobe rgb')):
            raise ValueError('High-depth HEIF transfer is not verified SDR; refusing possible HDR flattening')
        return icc, 'Embedded ICC preserved: '+description
    if nclx.get('transfer_characteristics') != 13 or nclx.get('color_primaries') not in (1, 12):
        raise ValueError('HEIF has missing/unsupported color metadata; refusing to guess a color space')
    if nclx['color_primaries'] == 1:
        return SRGB, 'sRGB ICC from declared sRGB NCLX'
    import imagecodecs
    # Display P3 uses the sRGB transfer curve, D65 white and P3 primaries.
    x = np.linspace(0, 1, 65536, dtype=np.float64)
    curve = np.where(x <= .04045, x / 12.92, ((x + .055) / 1.055) ** 2.4).astype(np.float32)
    icc = imagecodecs.cms_profile('rgb', whitepoint=(.3127, .3290),
        primaries=(.68, .32, .265, .69, .15, .06), transferfunction=curve)
    return icc, 'Display P3 ICC from declared Display P3 NCLX; RGB values unchanged'


def prepare(source, folder):
    """Return an importable source and conversion record. Other types pass through."""
    source = Path(source).resolve()
    if source.suffix.lower() not in EXTENSIONS:
        return source, None
    import pillow_heif
    if pillow_heif.__version__ != '1.8.0':
        raise RuntimeError('Run scripts/setup_heif.py for the pinned local HEIF decoder')
    folder = workspace_path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    record = {'status':'running', 'source':str(source), 'decoder':'pillow-heif 1.8.0 / libheif '+pillow_heif.libheif_info()['libheif']}
    try:
        check_cancel()
        data = stable_read(source, extensions=EXTENSIONS)
        digest = hashlib.sha256(data).hexdigest(); record['source_sha256'] = digest
        # Keep every original item, metadata block and auxiliary byte locally.
        snapshot = folder/('original'+source.suffix.lower()); snapshot.write_bytes(data)
        heif = pillow_heif.open_heif(data, convert_hdr_to_8bit=False, hdr_to_16bit=True)
        primary = heif[heif.primary_index]
        validate_dimensions(*primary.size)
        if primary.has_alpha or primary.mode not in ('RGB', 'RGB;16'):
            raise ValueError('HEIF must be opaque RGB; no automatic alpha removal or mode conversion')
        icc, color_note = color_profile(primary.info)
        exif = Image.Exif()
        if primary.info.get('exif'): exif.load(primary.info['exif'])
        camera = {'camera_make':exif.get(271), 'camera_model':exif.get(272)}
        iso = exif.get_ifd(34665).get(34855) if exif.get(34665) else None
        if iso is not None: camera['iso'] = 'ISO '+str(iso)
        camera = {k:v for k,v in camera.items() if v is not None}
        # libheif applies container crop/rotation/mirroring; do not rotate a second time.
        pixels = np.asarray(primary)
        validate_dimensions(pixels.shape[1], pixels.shape[0])
        if pixels.dtype == np.uint8: pixels = pixels.astype(np.uint16) * 257
        if pixels.dtype != np.uint16 or pixels.ndim != 3 or pixels.shape[2] != 3:
            raise ValueError('Decoder did not provide supported RGB integer samples')
        tags = [(34675, 'B', len(icc), icc, False), (274, 'H', 1, 1, False)]
        for tag in (271, 272):
            if exif.get(tag): tags.append((tag, 's', 0, str(exif[tag]), False))
        # Full original metadata is retained separately without stale TIFF/EXIF offsets.
        for key in ('exif', 'xmp'):
            value = primary.info.get(key)
            if value:
                (folder/('source.'+key)).write_bytes(value.encode('utf-8') if isinstance(value,str) else value)
        output = folder/'converted.tif'; pending = folder/'converted.partial.tif'
        check_cancel()
        tifffile.imwrite(pending, pixels, photometric='rgb', metadata=None, compression=None, extratags=tags)
        with tifffile.TiffFile(pending) as tif:
            if not np.array_equal(tif.asarray(), pixels) or tif.pages[0].tags[34675].value != icc:
                raise RuntimeError('Converted TIFF failed exact pixel/profile readback')
        if sha256(source) != digest or sha256(snapshot) != digest:
            raise RuntimeError('Original HEIF changed during conversion')
        check_cancel(); pending.rename(output)
        record.update(status='passed', output=str(output), output_sha256=sha256(output),
            original_copy=str(snapshot), camera=camera, source_bit_depth=primary.info['bit_depth'],
            output_bit_depth=16, dimensions=[pixels.shape[1], pixels.shape[0]],
            primary_index=heif.primary_index, top_level_images=len(heif),
            color=color_note, orientation='Container transformations applied by libheif; TIFF orientation 1',
            exact_decoded_pixel_readback=True, source_preserved=True,
            note='Primary photograph converted; full original container retained. No resize, tone map, denoise or JPEG recompression. Subsequent Lightroom/raster edits use sRGB SDR.')
        return output, record
    except BaseException as error:
        record.update(status='failed', error=str(error)); raise
    finally:
        json_write(folder/'conversion.json', record)


def context(record):
    if not record: return {}
    return dict(record['camera'], original_source=record['source'], source_encoding='rendered_heif',
                conversion={'bit_depth':16, 'color':record['color'], 'source_preserved':True})
