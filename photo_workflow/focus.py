"""Bounded, non-generative correction of mild defocus in linear-light luminance."""
import math
import cv2
import numpy as np
from .runtime import check_cancel

ITERATIONS = 12


def validate(value):
    if not isinstance(value, dict) or set(value) != {'radius', 'strength'}:
        raise ValueError('Focus correction requires radius and strength')
    for key, low, high in [('radius', .4, 3), ('strength', 0, .75)]:
        number = value[key]
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or not low <= number <= high:
            raise ValueError(f'Focus {key} must be a finite number in [{low}, {high}]')
    return {key: float(value[key]) for key in ('radius', 'strength')}


def correct(rgb, radius):
    """12 damped Richardson–Lucy steps with a Gaussian PSF, tiled with full halo.

    Radius is Gaussian sigma in source pixels, not a claim of measured lens blur.
    No downloaded model, identity reconstruction or invented texture. Strong blur,
    wrong PSFs and noise can still produce ringing; the caller owns blend/mask.
    """
    validate({'radius': radius, 'strength': .5})
    if rgb.dtype != np.uint16 or rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError('Focus correction requires uint16 RGB')
    support = math.ceil(3 * radius)
    halo = 2 * support * ITERATIONS
    kernel = cv2.getGaussianKernel(2 * support + 1, radius, cv2.CV_32F)
    def blur(value):
        return cv2.sepFilter2D(value, -1, kernel, kernel, borderType=cv2.BORDER_REFLECT_101)
    output = np.empty_like(rgb)
    height, width = rgb.shape[:2]
    for y in range(0, height, 512):
        for x in range(0, width, 512):
            check_cancel()
            y0, x0 = max(0, y-halo), max(0, x-halo)
            y1, x1 = min(height, y+512+halo), min(width, x+512+halo)
            srgb = rgb[y0:y1, x0:x1].astype(np.float32)/65535
            linear = np.where(srgb <= .04045, srgb/12.92, ((srgb+.055)/1.055)**2.4)
            observed = linear @ np.array([.2126, .7152, .0722], np.float32)
            estimate = np.maximum(observed, 1e-6)
            for _ in range(ITERATIONS):
                check_cancel()
                predicted = np.maximum(blur(estimate), 1e-6)
                # Suppress updates driven by tiny residuals and cap each step.
                residual = observed-predicted
                ratio = 1 + residual/predicted * np.minimum(1, np.abs(residual)/.001)
                estimate *= np.clip(blur(ratio), .5, 2)
                np.clip(estimate, 0, 1, out=estimate)
            gain = np.clip(estimate/np.maximum(observed, 1e-6), .5, 2)
            restored = np.clip(linear * gain[:, :, None], 0, 1)
            restored = np.where(restored <= .0031308, restored*12.92, 1.055*restored**(1/2.4)-.055)
            pixels = np.rint(np.clip(restored, 0, 1)*65535).astype(np.uint16)
            h, w = min(512, height-y), min(512, width-x)
            output[y:y+h, x:x+w] = pixels[y-y0:y-y0+h, x-x0:x-x0+w]
    return output
