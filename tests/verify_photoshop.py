"""Verify saved Adobe artifacts locally; never displays or uploads image pixels."""
import json
from pathlib import Path

import numpy as np
from PIL import Image
from psd_tools import PSDImage
import win32com.client

from photo_workflow.photoshop import export
from photo_workflow.runtime import ROOT, json_write

def verify():
    report = json.loads((ROOT / 'outputs/latest-verification.json').read_text())
    app = win32com.client.Dispatch('Photoshop.Application')
    existing = set(app.DoJavaScript('var a=[]; for(var i=0;i<app.documents.length;i++) a.push(app.documents[i].id); a.join(",");').split(',')) - {''}
    results = []
    for entry in report['actual_gpu_inference'][:2]:
        folder = Path(entry['job'])
        if not (folder / 'review.psd').exists():
            result = export(folder)
        else:
            result = json.loads((folder / 'photoshop-verification.json').read_text())
        psd = PSDImage.open(folder / 'review.psd')
        job = json.loads((folder / 'job.json').read_text())
        baseline = np.asarray(Image.open(folder / 'original.png').convert('RGB'))
        assert np.array_equal(np.asarray(list(psd)[0].topil().convert('RGB')), baseline)
        for layer, spec in zip(list(psd)[1:], job['layers']):
            assert abs(layer.opacity / 255 * 100 - spec['opacity']) < .5
            mask = layer.mask
            assert not mask.disabled
            reconstructed = Image.new('L', psd.size, mask.background_color)
            pixels = mask.topil()
            if pixels is not None:
                reconstructed.paste(pixels, (mask.left, mask.top))
            expected = np.asarray(Image.open(folder / spec['mask']))
            assert np.array_equal(np.asarray(reconstructed), expected), layer.name
        composite = np.asarray(psd.composite().convert('RGB'), dtype=float)
        expected = np.asarray(Image.open(folder / 'composite.png'), dtype=float)
        difference = float(np.abs(composite - expected).mean())
        assert difference < 1, difference
        result.update({'baseline_pixels_unchanged': True, 'mask_pixels_match_assets': True,
                       'opacity_verified': True, 'composite_mean_absolute_error': difference})
        json_write(folder / 'photoshop-verification.json', result)
        results.append({'job': str(folder), **result})
    after = set(app.DoJavaScript('var a=[]; for(var i=0;i<app.documents.length;i++) a.push(app.documents[i].id); a.join(",");').split(','))
    assert existing <= after, 'An existing Photoshop document was closed'
    report['photoshop'] = results
    report['existing_adobe_documents_preserved'] = True
    json_write(ROOT / 'outputs/latest-verification.json', report)
    json_write(Path(report['actual_gpu_inference'][0]['job']).parent / 'verification.json', report)
    print(json.dumps(results, indent=2))

if __name__ == '__main__':
    verify()
