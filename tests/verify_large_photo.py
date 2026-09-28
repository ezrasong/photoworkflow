"""61MP resource/precision acceptance using repeated public pixels and synthetic noise."""
import ctypes
import json
import time
import uuid

import numpy as np
import tifffile

from photo_workflow.imaging import decode_working, save_rgb, validate_dimensions
from photo_workflow.pipeline import Pipeline
from photo_workflow.photoshop import export, review_path
from photo_workflow.runtime import ROOT, json_write, local_runtime, sha256


def verify():
    local_runtime()
    root=ROOT/'outputs'/('large-photo-'+uuid.uuid4().hex[:8]);root.mkdir()
    report=dict(status='running',folder=str(root),pixels_remained_local=True,
                fixture='Repeated public NASA astronaut, synthetic Gaussian noise; resource test, not A7CR sensor data')
    record=root/'verification.json';json_write(record,report)
    started=time.monotonic()
    try:
        h,w=6336,9504
        public,_=decode_working((ROOT/'tests/fixtures/astronaut.png').read_bytes())
        clean=np.tile(public,(13,19,1))[:h,:w].copy()
        source=root/'source.tif';rgb=clean.copy(); rng=np.random.default_rng(904)
        for y in range(0,h,128):
            chunk=rgb[y:y+128]
            chunk[:]=np.clip(np.rint(chunk.astype(np.float32)+rng.normal(0,1200,chunk.shape)),0,65535).astype(np.uint16)
        save_rgb(source,rgb);digest=sha256(source)
        decoded,_=decode_working(source.read_bytes());assert np.array_equal(decoded,rgb);del decoded
        for size in [(8001,8000),(30001,1)]:
            try:validate_dimensions(*size)
            except ValueError:pass
            else:raise AssertionError('Oversize input accepted')
        print('61MP input decoded exactly; starting actual tiled SCUNet.',flush=True)
        folder,skipped=Pipeline(root/'jobs').process(source,settle=.05,
            recipe=dict(denoise_model='scunet',denoise=.25,exposure=.1))
        assert not skipped
        report['job']=str(folder);json_write(record,report)
        denoised=tifffile.memmap(folder/'edit-01.tif');before=tifffile.memmap(folder/'original.tif')
        assert np.array_equal(before,rgb)
        noisy_error=0.;cleaned_error=0.
        for y in range(0,h,128):
            noisy_error+=float(np.square(before[y:y+128].astype(np.float64)-clean[y:y+128]).sum())
            cleaned_error+=float(np.square(denoised[y:y+128].astype(np.float64)-clean[y:y+128]).sum())
        assert cleaned_error < noisy_error
        del denoised,before,clean,rgb
        assert sha256(source)==digest
        print('61MP CUDA pipeline passed; exporting layered PSB.',flush=True)
        adobe=export(folder,close_created=True)
        assert adobe['format']=='PSB' and adobe['bit_depth']==16
        from psd_tools import PSDImage
        psb=PSDImage.open(review_path(folder))
        assert psb.size==(w,h) and psb.depth==16 and len(list(psb))==3
        assert psb.image_resources.get_data(1039), 'Embedded ICC profile missing'
        del psb
        report.update(status='passed',dimensions=[w,h],pixels=w*h,source_preserved=True,
                      decoder_exact=True,actual_scunet=True,psb=adobe,
                      noisy_psnr_db=float(10*np.log10(65535**2/(noisy_error/(w*h*3)))),
                      full_denoised_psnr_db=float(10*np.log10(65535**2/(cleaned_error/(w*h*3)))),
                      seconds=time.monotonic()-started,
                      limits='Input/output <=64MP and <=30000px; full61MP 2x/4x upscale still exceeds output cap')
    except BaseException as error:
        report.update(status='failed',error=repr(error));raise
    finally:
        json_write(record,report);json_write(ROOT/'outputs/latest-large-photo-verification.json',report)
    print('Passed 61MP input, real denoise/grade and layered 16-bit PSB.',flush=True)


if __name__=='__main__':verify()
