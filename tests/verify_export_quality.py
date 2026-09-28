"""Opt-in synthetic TIFF/real Photoshop PSD+PSB precision acceptance.

Run with `python -m tests.verify_export_quality`; requires licensed Photoshop,
but no model downloads. Leaves synthetic artifacts and a measured JSON report.
"""
import json
import uuid
from unittest.mock import patch

import numpy as np
from psd_tools import PSDImage
import tifffile

from photo_workflow.imaging import SRGB, save_mask, save_rgb
from photo_workflow.photoshop import PhotoshopSession, export, review_path
from photo_workflow.pipeline import Pipeline
from photo_workflow.runtime import ROOT, json_write, sha256
from tests.test_export_quality import precision_ramp


def error(actual, expected):
    difference = np.abs(actual.astype(np.int32) - expected.astype(np.int32))
    return {'max_lsb': int(difference.max()), 'mean_lsb': float(difference.mean())}


def verify():
    folder = ROOT / 'outputs' / ('export-quality-' + uuid.uuid4().hex[:8])
    folder.mkdir(parents=True)
    report = {'status': 'running', 'fixture': 'Synthetic 65536-level RGB ramp and mask',
              'folder': str(folder), 'model_inference': False, 'results': []}
    record = folder / 'verification.json'
    try:
        source = folder / 'source.tif'
        mask_path = folder / 'mask.tif'
        rgb = precision_ramp()
        mask = rgb[:, :, 0].copy()
        save_rgb(source, rgb)
        save_mask(mask_path, mask)
        hashes = {p: sha256(p) for p in (source, mask_path)}
        pipeline = Pipeline(folder / 'jobs')
        no_op, _ = pipeline.process(source, recipe={'denoise': 0}, settle=.01)
        np.testing.assert_array_equal(tifffile.imread(no_op / 'composite.tif'), rgb)
        report['no_op_tiff_max_lsb'] = 0
        jobs = []
        for stops in (-.25, -.5):
            job, _ = pipeline.process(source, recipe={'exposure': stops, 'grade_mask': str(mask_path)}, settle=.01)
            original = tifffile.imread(job / 'original.tif')
            composite = tifffile.imread(job / 'composite.tif')
            np.testing.assert_array_equal(original, rgb)
            np.testing.assert_array_equal(composite[mask == 0], rgb[mask == 0])
            manifest = json.loads((job / 'job.json').read_text())
            for asset in ['original.tif', 'composite.tif'] + [l['file'] for l in manifest['layers']]:
                with tifffile.TiffFile(job / asset) as tif:
                    assert tif.pages[0].bitspersample == 16
                    assert tif.pages[0].tags[34675].value == SRGB
            np.testing.assert_array_equal(tifffile.imread(job / manifest['layers'][0]['mask']), mask)
            again, skipped = pipeline.process(source, recipe={'exposure': stops, 'grade_mask': str(mask_path)}, settle=.01)
            assert again == job and skipped
            jobs.append(job)
        session = PhotoshopSession()
        before = session.before.copy()
        for index, job in enumerate(jobs):
            # Exercise the real PSB save/read path on a small fixture, without a huge allocation.
            with patch('photo_workflow.photoshop.PSD_SAFE_BYTES', 1 if index else 1536 * 1024**2):
                result = export(job, close_created=True, session=session)
            assert session.verify() == before
            psd = PSDImage.open(review_path(job))
            assert psd.depth == 16 and psd.size == (256, 256)
            assert psd.image_resources.get_data(1039), 'Missing embedded ICC profile'
            assert len(list(psd)) == 2
            baseline = error(np.rint(list(psd)[0].numpy('color') * 65535), rgb)
            assert baseline['max_lsb'] <= 2, baseline
            layer = list(psd)[1]
            values = layer.numpy('mask')
            full = np.full((psd.height, psd.width), layer.mask.background_color / 255, np.float32)
            left, top, right, bottom = layer.mask.bbox
            if values is not None:
                full[top:bottom, left:right] = values.squeeze()
            mask_error = error(np.rint(full * 65535), mask)
            levels = len(np.unique(full))
            assert mask_error['max_lsb'] <= 2 and levels > 256, (mask_error, levels)
            merged = error(np.rint(psd.numpy('color') * 65535), tifffile.imread(job / 'composite.tif'))
            report['results'].append({'format': result['format'], 'path': str(review_path(job)),
                'baseline': baseline, 'mask': mask_error, 'mask_levels': levels,
                'merged_composite': merged, 'photoshop_version': result['photoshop_version']})
            # Photoshop uses a different 16-bit internal scale; tolerate bounded rounding only.
            assert merged['max_lsb'] <= 6, merged
        assert all(sha256(p) == value for p, value in hashes.items())
        report.update(status='passed', source_and_mask_preserved=True,
                      existing_photoshop_documents_preserved=True,
                      limitations=['Synthetic SDR export fidelity, not perceptual model quality',
                                   'PSB format exercised on a small fixture, not a >2 GiB stress test',
                                   'Wide-gamut/HDR output remains unimplemented'])
    except BaseException as exc:
        report.update(status='failed', error=repr(exc))
        raise
    finally:
        json_write(record, report)
        json_write(ROOT / 'outputs/latest-export-quality-verification.json', report)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    verify()
