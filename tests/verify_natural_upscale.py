"""Actual conservative upscale, no face model, blend/precision/source invariants."""
import json
import uuid
from unittest.mock import patch

import cv2
import numpy as np
import tifffile

from photo_workflow.runtime import ROOT, local_runtime, disable_network, sha256, json_write


def verify():
    local_runtime();disable_network()
    from photo_workflow.pipeline import Pipeline
    from photo_workflow.models import Models
    from photo_workflow.imaging import decode_working,save_rgb
    run=uuid.uuid4().hex[:10];folder=ROOT/'tests/fixtures'/('natural-'+run);folder.mkdir()
    original,_=decode_working((ROOT/'tests/fixtures/astronaut.png').read_bytes())
    small=cv2.resize(original,(256,256),interpolation=cv2.INTER_AREA)
    source=folder/'public-portrait.tif';save_rgb(source,small);digest=sha256(source)
    out=ROOT/'outputs'/('natural-'+run);pipeline=Pipeline(out)
    # A pure interpolation run must not initialize any image model.
    with patch.object(Models,'__init__',side_effect=AssertionError('Model invoked for zero detail')):
        baseline,_=pipeline.process(source,scale=2,upscale_strength=0,settle=0)
    expected=cv2.resize(small,(512,512),interpolation=cv2.INTER_LANCZOS4)
    assert np.array_equal(tifffile.imread(baseline/'composite.tif'),expected)
    # Real ESRGAN, but GFPGAN must never be constructed or invoked.
    import sys
    import torchvision.transforms.functional as functional
    sys.modules.setdefault('torchvision.transforms.functional_tensor',functional)
    from gfpgan.archs.gfpganv1_clean_arch import GFPGANv1Clean
    with patch.object(GFPGANv1Clean,'__init__',side_effect=AssertionError('Face model constructed')):
        detail,_=pipeline.process(source,scale=2,upscale_strength=.2,settle=0,upscale_model='realesrgan')
    job=json.loads((detail/'job.json').read_text())
    base=tifffile.imread(detail/'original.tif');ai=tifffile.imread(detail/'upscaled.tif');actual=tifffile.imread(detail/'composite.tif')
    blended=np.clip(np.rint(base.astype(np.float32)*.8+ai.astype(np.float32)*.2),0,65535).astype(np.uint16)
    assert np.array_equal(actual,blended) and np.array_equal(base,expected)
    assert actual.dtype==np.uint16 and actual.shape==(512,512,3)
    assert job['faces']==0 and job['runtime']['restoration_invoked'] is False
    assert job['layers'][0]['opacity']==20 and len(job['layers'])==1
    again,skipped=pipeline.process(source,scale=2,upscale_strength=.2,settle=0,upscale_model='realesrgan')
    assert skipped and again==detail and sha256(source)==digest
    for value in [-1,.51,float('nan'),True]:
        try:pipeline.process(source,scale=2,upscale_strength=value,settle=0)
        except ValueError:pass
        else:raise AssertionError('Invalid strength accepted')
    json_write(ROOT/'outputs/latest-natural-upscale-verification.json',{'status':'passed','job':str(detail),
        'source_preserved':True,'face_model_constructed':False,'precision':'uint16',
        'blend_matches_exactly':True,'non_generative_baseline_matches':True,'rerun_deduplicated':True,
        'reference_conditioned':False,'visual_quality':'Human local review required; no fidelity guarantee'})
    print('Passed actual Real-ESRGAN conservative blend, no-face-model, 16-bit and original-preservation checks.')


if __name__=='__main__':verify()
