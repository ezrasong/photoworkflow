import ctypes
from ctypes import wintypes
import io
import os
from pathlib import Path
import time
import warnings

import cv2
import numpy as np
from PIL import Image, ImageCms, ImageOps

EXTENSIONS = {'.jpg', '.jpeg', '.png', '.tif', '.tiff'}
SRGB = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
MAX_INPUT_PIXELS = 64_000_000
MAX_DIMENSION = 30_000
Image.MAX_IMAGE_PIXELS = MAX_INPUT_PIXELS


def validate_dimensions(width, height):
    if width * height > MAX_INPUT_PIXELS or max(width, height) > MAX_DIMENSION:
        raise ValueError('Input exceeds 64 megapixels or 30,000 pixels per dimension; no automatic downsize')

def stable_read(path, settle=2.0, timeout=60.0, extensions=EXTENSIONS):
    """Wait for quiescence, then read under a Windows deny-write/delete handle."""
    path = Path(path)
    if path.suffix.lower() not in extensions:
        raise ValueError('Supported inputs: JPEG, PNG, TIFF. Export RAW to TIFF first.')
    deadline = time.monotonic() + timeout
    previous = None
    since = time.monotonic()
    while time.monotonic() < deadline:
        from .runtime import check_cancel
        check_cancel()
        stat = path.stat()
        state = (stat.st_size, stat.st_mtime_ns)
        if state != previous:
            previous, since = state, time.monotonic()
        if time.monotonic() - since >= settle:
            if not 0 < stat.st_size <= 512 * 1024**2:
                raise ValueError('Input must be nonempty and at most 512 MiB')
            try:
                if os.name == 'nt':
                    import msvcrt
                    api = ctypes.WinDLL('kernel32', use_last_error=True)
                    api.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                               wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
                    api.CreateFileW.restype = wintypes.HANDLE
                    handle = api.CreateFileW(str(path.resolve()), 0x80000000, 1, None, 3, 0x80, None)
                    if handle == wintypes.HANDLE(-1).value:
                        raise OSError(ctypes.get_last_error(), 'Input is still open for writing')
                    fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
                    with os.fdopen(fd, 'rb') as stream:
                        data = stream.read(512 * 1024**2 + 1)
                else:
                    data = path.read_bytes()
                after = path.stat()
                if (after.st_size, after.st_mtime_ns) == state and len(data) == stat.st_size:
                    return data
            except OSError:
                pass
            since = time.monotonic()
        time.sleep(0.2)
    raise TimeoutError('Input did not become stable within 60 seconds')

def decode(data, allow_8bit=False):
    conversions = []
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        src = Image.open(io.BytesIO(data))
        if src.format not in {'JPEG', 'PNG', 'TIFF'}:
            raise ValueError('Image content is not JPEG, PNG or TIFF')
        if getattr(src, 'n_frames', 1) != 1:
            raise ValueError('Multi-page TIFF and animated PNG are unsupported; export one frame')
        validate_dimensions(src.width, src.height)
        profile = src.info.get('icc_profile')
        orientation = src.getexif().get(274, 1)
        bits = max(src.tag_v2.get(258, (8,))) if src.format == 'TIFF' else (data[24] if src.format == 'PNG' else 8)
        if 'A' in src.getbands() or 'transparency' in src.info:
            raise ValueError('Transparency is unsupported; export an opaque RGB TIFF/PNG')
        if bits > 8 or src.mode in {'I', 'F', 'I;16', 'I;16B'}:
            if not allow_8bit:
                raise ValueError('High bit depth requires --allow-8bit; inference and derivatives are 8-bit sRGB')
            if bits != 16 or src.mode == 'F':
                raise ValueError('Only unsigned 16-bit high-depth inputs supported; export RGB TIFF')
            pixels = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
            if pixels is None or pixels.dtype != np.uint16:
                raise ValueError('Cannot safely decode 16-bit input')
            if pixels.ndim == 3:
                if pixels.shape[2] != 3:
                    raise ValueError('Only RGB or gray 16-bit images supported')
                pixels = cv2.cvtColor(pixels, cv2.COLOR_BGR2RGB)
            src = Image.fromarray(((pixels.astype(np.uint32) + 128) // 257).astype(np.uint8))
            src.getexif()[274] = orientation
            conversions.append('16-bit to 8-bit rounded before ICC conversion; original bytes retained')
        src.load()
        src = ImageOps.exif_transpose(src)
        if orientation != 1:
            conversions.append('EXIF orientation applied')
        if profile:
            try:
                src = ImageCms.profileToProfile(src, ImageCms.ImageCmsProfile(io.BytesIO(profile)),
                                                ImageCms.createProfile('sRGB'), outputMode='RGB')
            except Exception as error:
                raise ValueError('Invalid/unsupported ICC profile; export an sRGB TIFF') from error
            conversions.append('Embedded ICC profile converted to sRGB')
        else:
            if src.mode == 'CMYK':
                raise ValueError('CMYK input requires an embedded ICC profile')
            if src.mode != 'RGB':
                conversions.append(src.mode + ' converted to RGB')
            src = src.convert('RGB')
            conversions.append('No ICC profile: assumed sRGB')
        return src, conversions

def save_rgb(path, array):
    if isinstance(array, np.ndarray) and array.dtype == np.uint16:
        import tifffile
        tifffile.imwrite(path, array, photometric='rgb', metadata=None,
                         extratags=[(34675, 'B', len(SRGB), SRGB, False)])
        return
    image = Image.fromarray(array) if isinstance(array, np.ndarray) else array
    image.save(path, icc_profile=SRGB)

def decode_working(data, bit_depth=16, allow_8bit=False):
    """16-bit color-managed working pixels; model tensors remain float32.

    Keep the existing explicitly lossy 8-bit path for compatibility.
    """
    if bit_depth == 8:
        image, notes = decode(data, allow_8bit)
        return np.array(image), notes
    if bit_depth != 16:
        raise ValueError('Output bit depth must be 8 or 16')
    import imagecodecs
    import tifffile
    notes = []
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        src = Image.open(io.BytesIO(data))
        if src.format not in {'JPEG', 'PNG', 'TIFF'} or getattr(src, 'n_frames', 1) != 1:
            raise ValueError('Expected single-frame JPEG, PNG or TIFF')
        validate_dimensions(src.width, src.height)
        if 'A' in src.getbands() or 'transparency' in src.info:
            raise ValueError('Transparency is unsupported; export an opaque RGB image')
        orientation = src.getexif().get(274, 1)
        profile = src.info.get('icc_profile')
        mode = src.mode
        if src.format == 'TIFF':
            with tifffile.TiffFile(io.BytesIO(data)) as tif:
                page = tif.pages[0]
                if page.dtype not in (np.dtype('uint8'), np.dtype('uint16')):
                    raise ValueError('Only unsigned 8/16-bit TIFF is supported')
                if page.planarconfig != 1:
                    raise ValueError('Export an interleaved RGB/gray TIFF')
                pixels = page.asarray()
                if page.photometric == 0:
                    pixels = np.iinfo(pixels.dtype).max - pixels
                elif page.photometric not in (1, 2, 3, 5):
                    raise ValueError('Export an RGB/gray TIFF; this TIFF color encoding is unsupported')
        elif src.format == 'PNG':
            pixels = imagecodecs.png_decode(data)
        else:
            src.load()
            pixels = np.array(src)
        if mode == 'P':
            src.load(); pixels = np.array(src.convert('RGB')); mode = 'RGB'
        if pixels.dtype not in (np.uint8, np.uint16):
            raise ValueError('Only unsigned 8/16-bit pixels supported')
        if pixels.dtype == np.uint8:
            pixels = pixels.astype(np.uint16) * 257
            notes.append('8-bit source expanded to 16-bit working precision; no extra source detail implied')
        else:
            notes.append('16-bit source precision retained through color management and compositing')
        transforms = {2: lambda a: np.flip(a, 1), 3: lambda a: np.rot90(a, 2),
            4: lambda a: np.flip(a, 0), 5: lambda a: np.swapaxes(a, 0, 1),
            6: lambda a: np.rot90(a, 3), 7: lambda a: np.flip(np.swapaxes(a, 0, 1), (0, 1)),
            8: lambda a: np.rot90(a, 1)}
        if orientation in transforms:
            pixels = transforms[orientation](pixels)
            notes.append('EXIF orientation applied')
        channels = 1 if pixels.ndim == 2 else pixels.shape[2]
        space = {1: 'GRAY', 3: 'RGB', 4: 'CMYK'}.get(channels)
        if space is None or (channels == 4 and mode != 'CMYK'):
            raise ValueError('Unsupported pixel layout')
        pixels = np.ascontiguousarray(pixels, dtype=np.uint16)
        if profile:
            try:
                pixels = imagecodecs.cms_transform(pixels, profile, SRGB,
                    colorspace=space, outcolorspace='RGB', outdtype='uint16', intent=0)
            except Exception as error:
                raise ValueError('Invalid/unsupported ICC profile; export an sRGB TIFF') from error
            notes.append('Embedded ICC converted to sRGB using 16-bit LittleCMS transform')
        elif space == 'CMYK':
            raise ValueError('CMYK input requires an embedded ICC profile')
        else:
            if channels == 1:
                pixels = np.repeat(pixels[:, :, None], 3, axis=2)
            notes.append('No ICC profile: assumed sRGB')
        return np.ascontiguousarray(pixels), notes

def sony_preview(data):
    """Read the camera's embedded JPEG for display only, never decode/edit RAW pixels."""
    import tifffile
    from itertools import islice

    message = 'Sony RAW preview is missing or unreadable. Choose another photo or export a JPEG/TIFF preview from Lightroom. The RAW original is unchanged.'
    try:
        candidates = []
        with tifffile.TiffFile(io.BytesIO(data)) as tif:
            # Sony stores previews in the main IFD chain; SubIFDs hold sensor data.
            for page in islice(tif.pages, 32):
                def scalar(code, default=None):
                    tag = page.tags.get(code)
                    value = tag.value if tag else default
                    if isinstance(value, tuple):
                        return value[0] if len(value) == 1 else None
                    return value
                offset, length = scalar(513), scalar(514)
                if not isinstance(offset, int) or not isinstance(length, int):
                    continue
                if offset < 8 or not 0 < length <= 64*1024*1024 or offset + length > len(data):
                    continue
                jpeg = data[offset:offset+length]
                if not jpeg.startswith(b'\xff\xd8'):
                    continue
                with warnings.catch_warnings():
                    warnings.simplefilter('error', Image.DecompressionBombWarning)
                    with Image.open(io.BytesIO(jpeg)) as image:
                        if image.format != 'JPEG': continue
                        validate_dimensions(image.width, image.height)
                        orientation = image.getexif().get(274, scalar(274, 1))
                        candidates.append((image.width*image.height, offset, length, orientation))
        if not candidates: raise ValueError(message)
        _, offset, length, orientation = max(candidates, key=lambda item: item[0])
        jpeg = data[offset:offset+length]
        # Reuse the raster decoder's ICC handling. It already applies any JPEG
        # orientation; use the enclosing TIFF's orientation only when absent.
        with Image.open(io.BytesIO(jpeg)) as embedded:
            has_orientation = 274 in embedded.getexif()
        image, _ = decode(jpeg)
        if not has_orientation:
            image.getexif()[274] = orientation
            image = ImageOps.exif_transpose(image)
        return image
    except (tifffile.TiffFileError, ValueError, OSError, SyntaxError,
            Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise ValueError(message) from error


def preview(array, max_size=None):
    if max_size:
        h, w = array.shape[:2]
        ratio = min(1, max_size[0]/w, max_size[1]/h)
        if ratio < 1:
            array = cv2.resize(array, (max(1, round(w*ratio)), max(1, round(h*ratio))), interpolation=cv2.INTER_AREA)
    if array.dtype == np.uint16:
        array = ((array.astype(np.uint32) + 128) // 257).astype(np.uint8)
    return Image.fromarray(array)

def save_mask(path, array):
    if array.dtype == np.uint16:
        import tifffile
        tifffile.imwrite(path, array, photometric='minisblack', metadata=None)
    else:
        Image.fromarray(array).save(path)
