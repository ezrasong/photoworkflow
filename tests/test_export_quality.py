"""Synthetic export precision checks; no models, Adobe, network or private photos."""
import io
from pathlib import Path
import tempfile
import unittest

import imagecodecs
import numpy as np
from PIL import Image
import tifffile

from photo_workflow.imaging import SRGB, decode_working, preview, save_mask, save_rgb
from photo_workflow.edits import edit_layers, validate_recipe


def precision_ramp():
    values = np.arange(65536, dtype=np.uint16).reshape(256, 256)
    return np.stack((values, np.flipud(values), np.fliplr(values)), axis=2)


class ExportQualityTests(unittest.TestCase):
    def test_all_65536_levels_survive_tiff_and_icc_roundtrip(self):
        source = precision_ramp()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'ramp.tif'
            save_rgb(path, source)
            with tifffile.TiffFile(path) as tif:
                self.assertEqual(tif.pages[0].bitspersample, 16)
                self.assertEqual(tif.pages[0].tags[34675].value, SRGB)
                np.testing.assert_array_equal(tif.asarray(), source)
            pixels, _ = decode_working(path.read_bytes())
            np.testing.assert_array_equal(pixels, source)

    def test_repeated_save_load_does_not_accumulate_quantization(self):
        source = precision_ramp()
        pixels = source.copy()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'roundtrip.tif'
            for _ in range(10):
                save_rgb(path, pixels)
                pixels, _ = decode_working(path.read_bytes())
            np.testing.assert_array_equal(pixels, source)

    def test_png_and_gray_inputs_retain_low_bits(self):
        source = precision_ramp()
        pixels, _ = decode_working(imagecodecs.png_encode(source))
        np.testing.assert_array_equal(pixels, source)
        gray = source[:, :, 0]
        stream = io.BytesIO()
        tifffile.imwrite(stream, gray, photometric='minisblack', metadata=None)
        pixels, _ = decode_working(stream.getvalue())
        np.testing.assert_array_equal(pixels, np.repeat(gray[:, :, None], 3, axis=2))

    def test_all_exif_orientations_preserve_channel_values(self):
        source = precision_ramp()[:7, :11]
        expected = [source, source[:, ::-1], source[::-1, ::-1], source[::-1],
                    source.transpose(1, 0, 2), np.rot90(source, -1),
                    source.transpose(1, 0, 2)[::-1, ::-1], np.rot90(source)]
        for orientation, target in enumerate(expected, 1):
            with self.subTest(orientation=orientation):
                stream = io.BytesIO()
                tifffile.imwrite(stream, source, photometric='rgb', metadata=None,
                                 extratags=[(274, 'H', 1, orientation, False)])
                pixels, _ = decode_working(stream.getvalue())
                np.testing.assert_array_equal(pixels, target)

    def test_preview_is_lossy_but_leaves_export_pixels_and_masks_untouched(self):
        source = precision_ramp()
        before = source.copy()
        self.assertEqual(np.asarray(preview(source)).dtype, np.uint8)
        thumbnail = preview(source, (63, 47))
        self.assertLessEqual(thumbnail.width, 63)
        self.assertLessEqual(thumbnail.height, 47)
        np.testing.assert_array_equal(source, before)
        with tempfile.TemporaryDirectory() as directory:
            mask = Path(directory) / 'mask.tif'
            save_mask(mask, source[:, :, 0])
            np.testing.assert_array_equal(tifffile.imread(mask), source[:, :, 0])

    def test_exposure_tracks_float64_reference_without_unexpected_clipping(self):
        source = precision_ramp()
        x = source.astype(np.float64) / 65535
        for stops in (-3, -.125, .125, 3):
            with self.subTest(stops=stops), tempfile.TemporaryDirectory() as directory:
                linear = np.where(x <= .04045, x / 12.92, ((x + .055) / 1.055)**2.4) * 2**stops
                expected = np.rint(np.clip(np.where(linear <= .0031308, linear * 12.92,
                    1.055 * linear**(1/2.4) - .055), 0, 1) * 65535).astype(np.int32)
                layers = list(edit_layers(source, validate_recipe({'exposure': stops}), {}, Path(directory)))
                actual = layers[-1][-1].astype(np.int32)
                self.assertLessEqual(int(np.abs(actual - expected).max()), 1)
                self.assertTrue(np.all(actual[expected == 0] == 0))
                self.assertTrue(np.all(actual[expected == 65535] == 65535))

    def test_invalid_profile_and_unsupported_hdr_fail_explicitly(self):
        stream = io.BytesIO()
        tifffile.imwrite(stream, precision_ramp(), photometric='rgb', metadata=None,
                         extratags=[(34675, 'B', 7, b'invalid', False)])
        with self.assertRaisesRegex(ValueError, 'ICC'):
            decode_working(stream.getvalue())
        stream = io.BytesIO()
        tifffile.imwrite(stream, np.full((8, 9, 3), 1.5, np.float32), photometric='rgb')
        with self.assertRaises((ValueError, Image.UnidentifiedImageError)):
            decode_working(stream.getvalue())


if __name__ == '__main__':
    unittest.main()
