"""Embedded Sony preview fixtures; no RAW demosaicing or Adobe catalog access."""
import base64
import io
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from photo_workflow.desktop import Desktop
from photo_workflow.imaging import SRGB, sony_preview


def jpeg(size, color, orientation=None):
    image = Image.new('RGB', size, color)
    output = io.BytesIO()
    exif = Image.Exif()
    if orientation is not None: exif[274] = orientation
    image.save(output, format='JPEG', exif=exif, icc_profile=SRGB)
    return output.getvalue()


def arw(previews, orientation=1):
    """Standard TIFF IFD chain containing JPEGInterchangeFormat previews."""
    count = 7
    ifd_size = 2 + count*12 + 4
    offset = 8 + len(previews)*ifd_size
    data = bytearray(b'II\x2a\x00' + struct.pack('<I', 8))
    for index, preview in enumerate(previews):
        tags = [(256, 4, 1), (257, 4, 1), (259, 3, 6), (262, 3, 6),
                (274, 3, orientation), (513, 4, offset), (514, 4, len(preview))]
        data.extend(struct.pack('<H', count))
        for tag, kind, value in tags:
            data.extend(struct.pack('<HHII', tag, kind, 1, value))
        data.extend(struct.pack('<I', 8 + (index+1)*ifd_size if index+1 < len(previews) else 0))
        offset += len(preview)
    return bytes(data) + b''.join(previews)


class SonyPreviewTests(unittest.TestCase):
    def test_largest_embedded_preview_and_color(self):
        data = arw([jpeg((20, 10), 'red'), jpeg((8, 4), 'green'), jpeg((80, 40), 'blue')])
        image = sony_preview(data)
        self.assertEqual(image.size, (80, 40))
        self.assertEqual(image.mode, 'RGB')
        self.assertGreater(image.getpixel((0, 0))[2], 240)

    def test_outer_orientation_and_no_double_rotation(self):
        for orientation in range(1, 9):
            with self.subTest(orientation=orientation):
                image = sony_preview(arw([jpeg((20, 10), 'red')], orientation))
                self.assertEqual(image.size, (10, 20) if orientation >= 5 else (20, 10))
        image = sony_preview(arw([jpeg((20, 10), 'red', orientation=6)], orientation=6))
        self.assertEqual(image.size, (10, 20))

    def test_invalid_missing_truncated_and_out_of_bounds_previews(self):
        valid = arw([jpeg((20, 10), 'red')])
        invalid_offset = bytearray(valid)
        # IFD entry 5 is JPEGInterchangeFormat; values start eight bytes into each entry.
        struct.pack_into('<I', invalid_offset, 10+5*12+8, len(valid)+1)
        invalid_length = bytearray(valid)
        struct.pack_into('<I', invalid_length, 10+6*12+8, 0xffffffff)
        for data in (b'not raw', valid[:20], arw([b'no JPEG preview']),
                     bytes(invalid_offset), bytes(invalid_length), valid[:-100]):
            with self.subTest(size=len(data)), self.assertRaisesRegex(ValueError, 'Sony RAW preview.*RAW original is unchanged'):
                sony_preview(data)

    def test_excessive_dimensions_are_rejected_before_decode(self):
        data = bytearray(jpeg((20, 10), 'red'))
        start = data.index(b'\xff\xc0')
        struct.pack_into('>HH', data, start+5, 30001, 30001)
        with self.assertRaisesRegex(ValueError, 'Sony RAW preview'):
            sony_preview(arw([bytes(data)]))

    def test_desktop_preview_preserves_original_and_recovers_after_failure(self):
        with tempfile.TemporaryDirectory() as directory, patch('photo_workflow.lightroom.request') as bridge:
            path = Path(directory)/'photo.ARW'
            desktop = Desktop.__new__(Desktop)
            path.write_bytes(b'broken')
            with self.assertRaisesRegex(ValueError, 'Sony RAW preview'):
                desktop.dispatch('preview', {'path': str(path)})
            original = arw([jpeg((2200, 1400), 'blue')])
            path.write_bytes(original)
            for full, expected in ((False, (1800, 1145)), (True, (2200, 1400))):
                result = desktop.dispatch('preview', {'path': str(path), 'full': full})
                self.assertTrue(result.startswith('data:image/png;base64,'))
                with Image.open(io.BytesIO(base64.b64decode(result.split(',', 1)[1]))) as image:
                    self.assertEqual(image.size, expected)
                    self.assertEqual(image.format, 'PNG')
                self.assertEqual(path.read_bytes(), original)
            bridge.assert_not_called()


if __name__ == '__main__':
    unittest.main()
