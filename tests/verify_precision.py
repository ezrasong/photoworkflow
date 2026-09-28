"""Actual CUDA precision checks using only public and generated fixtures."""
import json
from pathlib import Path
import time
import uuid

import numpy as np
from PIL import Image
import tifffile

from photo_workflow.runtime import ROOT,local_runtime,disable_network,json_write,sha256

def verify():
    local_runtime(); disable_network()
    from photo_workflow.imaging import SRGB,decode_working,save_rgb
    from photo_workflow.pipeline import Pipeline
    fixtures=ROOT/'tests/fixtures'; fixtures.mkdir(exist_ok=True)
    # More than 256 genuinely distinct levels, including the low 8 bits.
    gradient=np.arange(64*256*3,dtype=np.uint16).reshape(64,256,3)
    source=fixtures/'precision-gradient.tif'; save_rgb(source,gradient)
    decoded,notes=decode_working(source.read_bytes(),16)
    assert np.array_equal(decoded,gradient), '16-bit ICC decode discarded precision'
    dark=fixtures/'precision-dark.tif'; save_rgb(dark,np.full((64,64,3),100,np.uint16))
    astronaut=fixtures/'astronaut.png'
    source_hashes={str(p):sha256(p) for p in (source,dark,astronaut)}
    run_id=time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]
    pipeline=Pipeline(ROOT/'outputs'/('precision-'+run_id))
    results=[]
    for path,scale,faces in [(source,1,0),(dark,2,0),(astronaut,2,1)]:
        folder,skipped=pipeline.process(path,scale=scale,bit_depth=16,settle=.05)
        assert not skipped
        job=json.loads((folder/'job.json').read_text())
        composite=tifffile.imread(folder/job['composite_file'])
        assert composite.dtype==np.uint16 and job['faces']==faces
        assert composite.shape[:2]==(job['output_size'][1],job['output_size'][0])
        with tifffile.TiffFile(folder/job['composite_file']) as file:
            assert file.pages[0].bitspersample==16 and file.pages[0].tags[34675].value
        if path==source: assert np.array_equal(composite,gradient)
        if path==dark: assert composite.max()<2000, 'Dark uint16 incorrectly normalized as 8-bit'
        if faces:
            face=tifffile.imread(folder/'face-01-crop.tif')
            assert np.count_nonzero(face.astype(np.uint32)%257)>face.size//2
            assert tifffile.imread(folder/'face-01-mask.tif').dtype==np.uint16
        before={p.name:sha256(p) for p in folder.iterdir()}
        again,skipped=pipeline.process(path,scale=scale,bit_depth=16,settle=.05)
        assert skipped and again==folder and before=={p.name:sha256(p) for p in folder.iterdir()}
        results.append({'job':str(folder),'source':path.name,'faces':faces,'bit_depth':16,
                        'size':job['output_size'],'inference_seconds':job['inference_seconds']})
        print('PASS 16-bit CUDA:',path.name,flush=True)
    assert source_hashes=={name:sha256(name) for name in source_hashes}
    report={'status':'passed','run_id':run_id,'actual_gpu_inference':results,
            'checks':['16-bit ICC input precision','16-bit TIFF assets/masks','nonquantized model output',
                      'dark uint16 scale normalization','no-face exact preservation','hash-stable rerun','unchanged sources'],
            'network':'Python audit hook only; OS isolation requires verify_offline.ps1',
            'gpu':job['runtime'],'photoshop':'pending','visual_quality':'awaiting local human review'}
    json_write(ROOT/'outputs/latest-precision-verification.json',report)
    json_write(pipeline.output/'verification.json',report)
    return report

if __name__=='__main__': verify()
