"""Mamba pipeline identity, precision, no-face, cancellation and atomic failures."""
import json
import os
import uuid
from unittest.mock import patch

import cv2
import numpy as np
import tifffile
import torch

from photo_workflow.runtime import ROOT, local_runtime, disable_network, sha256, json_write


def verify():
    local_runtime();disable_network()
    from photo_workflow.pipeline import Pipeline
    from photo_workflow.mambair import MambaUpscaler
    from photo_workflow.models import Models
    from photo_workflow.imaging import decode_working,save_rgb
    uid=uuid.uuid4().hex[:8]
    out=ROOT/'outputs'/('mamba-pipeline-'+uid);out.mkdir()
    source=ROOT/'tests/fixtures'/('mamba-'+uid+'.tif')
    image,_=decode_working((ROOT/'tests/fixtures/astronaut.png').read_bytes())
    pixels=cv2.resize(image,(35,33),interpolation=cv2.INTER_AREA)
    # Include actual 16-bit steps rather than only promoted 8-bit values.
    pixels=np.minimum(pixels.astype(np.uint32)+np.arange(35)[None,:,None],65535).astype(np.uint16)
    save_rgb(source,pixels);digest=sha256(source)
    pipeline=Pipeline(out)
    with patch.object(MambaUpscaler,'__init__',side_effect=AssertionError('Zero-strength model load')):
        zero,_=pipeline.process(source,scale=2,upscale_strength=0,settle=0)
    with patch.object(Models,'__init__',side_effect=AssertionError('Legacy/face model loaded')):
        result,_=pipeline.process(source,scale=2,upscale_strength=.2,settle=0)
    job=json.loads((result/'job.json').read_text())
    original=tifffile.imread(result/'original.tif')
    detail=tifffile.imread(result/'upscaled.tif')
    actual=tifffile.imread(result/'composite.tif')
    assert np.array_equal(actual,np.clip(np.rint(original.astype(np.float32)*.8+detail.astype(np.float32)*.2),0,65535).astype(np.uint16))
    assert actual.shape==(66,70,3) and actual.dtype==np.uint16
    assert job['settings']['upscale_model']=='mambairv2' and job['faces']==0
    assert job['runtime']['kernel'].startswith('upstream Mamba')
    assert not job['runtime']['restoration_invoked']
    assert 'MambaIRv2' in job['layers'][0]['name']
    again,skipped=pipeline.process(source,scale=2,upscale_strength=.2,settle=0)
    assert skipped and again==result and pipeline.models is None
    zero_old,_=pipeline.process(source,scale=2,upscale_strength=0,upscale_model='realesrgan',settle=0)
    assert zero_old!=zero
    before=set(out.iterdir())
    for failure in (torch.cuda.OutOfMemoryError('simulated OOM'), KeyboardInterrupt()):
        with patch.object(MambaUpscaler,'upscale',side_effect=failure):
            try: pipeline.process(source,scale=4,upscale_strength=.2,settle=0)
            except type(failure): pass
            else: raise AssertionError('Failure not propagated')
        assert pipeline.models is None and not list(out.glob('.partial-*'))
        assert not [p for p in set(out.iterdir())-before if p.name!='errors']
    marker=ROOT/'.cache/control'/('mamba-'+uid+'.cancel');marker.parent.mkdir(exist_ok=True);marker.touch()
    try:
        with patch.dict(os.environ,{'PHOTOWORKFLOW_CANCEL_FILE':str(marker)}), patch.object(MambaUpscaler,'__init__',side_effect=AssertionError('Cancelled model load')):
            try:pipeline.process(source,scale=4,upscale_strength=.2,settle=0)
            except KeyboardInterrupt:pass
            else:raise AssertionError('Cancelled job executed')
    finally:marker.unlink()
    with patch('photo_workflow.mambair.sha256',return_value='bad'):
        try:MambaUpscaler()
        except RuntimeError as e:assert 'checksum' in str(e)
        else:raise AssertionError('Tampered model accepted')
    assert sha256(source)==digest
    json_write(ROOT/'outputs/latest-mamba-pipeline-verification.json',{'status':'passed','job':str(result),
        'precision':'uint16 RGB, float32 inference/blend','zero_load':False,'source_preserved':True,
        'rerun_deduplicated':True,'different_model_identity':True,'face_model_loaded':False,
        'simulated_oom_and_cancellation_atomic':True,'checksum_rejection':True,
        'initial_cancellation_prevents_inference':True})
    print('Mamba pipeline precision, identity, checksum, cancellation and simulated OOM checks passed.',flush=True)


if __name__=='__main__':verify()
