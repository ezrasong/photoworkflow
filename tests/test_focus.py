import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import cv2
import numpy as np
from photo_workflow.focus import correct, validate
from photo_workflow.edits import edit_layers, validate_recipe


class FocusTests(unittest.TestCase):
    def test_recovers_known_mild_blur_without_changing_shape_or_precision(self):
        y, x = np.mgrid[:128, :160]
        original = (.35+.2*np.sin(x*.5)*np.cos(y*.3)).astype(np.float32)
        blurred = cv2.GaussianBlur(original, (7, 7), 1)
        def encode(a):return np.rint((1.055*a**(1/2.4)-.055)*65535).astype(np.uint16)
        source = np.repeat(encode(blurred)[:, :, None], 3, axis=2)
        target = encode(original)
        output = correct(source, 1)
        self.assertEqual(output.shape, source.shape)
        self.assertEqual(output.dtype, np.uint16)
        crop = np.s_[12:-12, 12:-12]
        mse = lambda a: np.mean((a[crop].astype(float)-target[crop])**2)
        self.assertLess(mse(output[:, :, 0]), mse(source[:, :, 0])*.6)
        np.testing.assert_array_equal(source[:, :, 0], encode(blurred))

    def test_flat_field_and_tiled_boundary(self):
        source = np.full((40, 700, 3), 30000, np.uint16)
        np.testing.assert_array_equal(correct(source, 1), source)
        # Identical repeated features must not acquire a seam at the tile boundary.
        pattern = (.4+.15*np.sin(np.arange(700)*np.pi/8)).astype(np.float32)
        source[:] = np.rint(pattern[None,:,None]*65535).astype(np.uint16)
        output = correct(source, 1)
        np.testing.assert_allclose(output[20,496:512], output[20,512:528],atol=3)

    def test_bounds_cancel_and_mask_preservation(self):
        for value in ({'radius':0,'strength':.3},{'radius':1,'strength':1},{'radius':True,'strength':.3},{'radius':1,'strength':float('nan')}):
            with self.assertRaises(ValueError):validate(value)
        source=np.full((20,30,3),30000,np.uint16)
        with patch('photo_workflow.focus.check_cancel',side_effect=InterruptedError):
            with self.assertRaises(InterruptedError):correct(source,1)
        with tempfile.TemporaryDirectory() as temp:
            mask=np.zeros((20,30),np.uint16);mask[:,:15]=65535
            ok,encoded=cv2.imencode('.png',mask);self.assertTrue(ok)
            path=Path(temp)/'mask.png';path.write_bytes(encoded.tobytes())
            source[:,10:20]=40000
            recipe=validate_recipe({'focus':{'radius':1,'strength':.5},'grade_mask':str(path)})
            layers=list(edit_layers(source,recipe,{'grade':(path,path.read_bytes())},Path(temp)))
            self.assertEqual(len(layers),1)
            np.testing.assert_array_equal(layers[-1][-1][:,15:],source[:,15:])

if __name__=='__main__':unittest.main()
