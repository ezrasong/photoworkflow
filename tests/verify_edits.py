"""Real DRUNet inference and edit invariants; no image leaves local software."""
import json
import time
import uuid
from unittest.mock import patch

import numpy as np
import tifffile

from photo_workflow.runtime import ROOT, local_runtime, disable_network, json_write, sha256

def verify():
    local_runtime(); disable_network()
    from photo_workflow.imaging import decode_working, save_rgb, save_mask
    from photo_workflow.pipeline import Pipeline, job_lock
    from photo_workflow.edits import validate_recipe
    from photo_workflow.models import Models
    import torch
    run=time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]
    fixtures=ROOT/'tests/fixtures'/('edits-'+run);fixtures.mkdir()
    out=ROOT/'outputs'/('edits-'+run);p=Pipeline(out)
    original,_=decode_working((ROOT/'tests/fixtures/astronaut.png').read_bytes())
    # Public-domain photo with reproducible low-light signal and known Gaussian noise.
    clean=np.rint(original.astype(np.float32)*.55+6000).astype(np.uint16)
    rng=np.random.default_rng(31415)
    noisy=np.clip(np.rint(clean.astype(np.float32)+rng.normal(0,15/255*65535,clean.shape)),0,65535).astype(np.uint16)
    source=fixtures/'noisy-stage.tif';save_rgb(source,noisy)
    mask=np.zeros(noisy.shape[:2],np.uint16);mask[60:180,50:130]=65535
    mask_path=fixtures/'mask.tif';save_mask(mask_path,mask)
    corrupt=fixtures/'corrupt.tif';corrupt.write_bytes(b'not a TIFF')
    hashes={str(x):sha256(x) for x in (source,mask_path,corrupt)}
    def process(recipe):return p.process(source,recipe=recipe,settle=0)[0]
    # Fail loudly if any edit attempts to initialize the restoration stack.
    with patch.object(Models,'__init__',side_effect=AssertionError('Restoration was invoked')):
        grade=process({'exposure':.5,'contrast':1.1,'shadows':.05,'saturation':1.05})
        j=json.loads((grade/'job.json').read_text());a=tifffile.imread(grade/'composite.tif')
        assert a.shape==noisy.shape and a.dtype==np.uint16 and np.any(a!=noisy)
        assert len(j['layers'])==3 and not j['runtime']['restoration_invoked']
        assert np.array_equal(tifffile.imread(grade/'original.tif'),noisy)
        assert len(np.unique(a))>256
        nothing=process({});assert np.array_equal(tifffile.imread(nothing/'composite.tif'),noisy)
        again,skipped=p.process(source,recipe={},settle=0);assert skipped and again==nothing
        denoise=process({'denoise':1,'noise_sigma':15})
        denoised=tifffile.imread(denoise/'composite.tif')
        def psnr(x):return float(10*np.log10(65535**2/np.mean((x.astype(np.float64)-clean)**2)))
        before,after=psnr(noisy),psnr(denoised)
        assert after>before+3,(before,after)
        remove=process({'removal':{'mask':str(mask_path),'dx':200,'dy':0,'feather':8}})
        removed=tifffile.imread(remove/'composite.tif')
        assert np.array_equal(removed[mask==0],noisy[mask==0]) and np.any(removed[mask>0]!=noisy[mask>0])
        masked=process({'exposure':.4,'grade_mask':str(mask_path)})
        masked_pixels=tifffile.imread(masked/'composite.tif')
        assert np.array_equal(masked_pixels[mask==0],noisy[mask==0])
        # Preserve genuinely high-precision user masks through saved layer assets.
        gradient=np.zeros_like(mask);gradient[50:250,50:250]=np.arange(40000,dtype=np.uint16).reshape(200,200)+1
        precision=fixtures/'precision-mask.tif';save_mask(precision,gradient)
        precise=process({'exposure':.2,'grade_mask':str(precision)})
        assert np.array_equal(tifffile.imread(precise/'edit-01-mask.tif'),gradient)
        for err in (torch.cuda.OutOfMemoryError('injected OOM'),KeyboardInterrupt()):
            with patch('photo_workflow.edits.drunet',side_effect=err):
                try:process({'denoise':.777});raise AssertionError('Failure swallowed')
                except type(err):pass
            assert not list(out.glob('.partial-*'))
    for recipe in ({'exposure':float('nan')},{'shell':'anything'},{'denoise':True},
                   {'removal':{'mask':str(mask_path),'dx':-9000,'dy':0,'feather':0}}):
        try:process(recipe);raise AssertionError('Invalid recipe accepted')
        except ValueError:pass
    try:p.process(corrupt,recipe={},settle=0);raise AssertionError('Corrupt image accepted')
    except (ValueError,OSError):pass
    # Reruns must never replace edited outputs or a collided destination.
    manifest_path=nothing/'job.json';saved=manifest_path.read_bytes()
    bad=json.loads(saved);bad['job_id']='collision';json_write(manifest_path,bad)
    try:
        try:process({});raise AssertionError('Collision accepted')
        except RuntimeError as e:assert 'collision' in str(e)
    finally:manifest_path.write_bytes(saved)
    composite=nothing/'composite.tif';saved=composite.read_bytes();composite.write_bytes(b'modified')
    try:
        try:process({});raise AssertionError('Modified output accepted')
        except RuntimeError as e:assert 'modified' in str(e)
    finally:composite.write_bytes(saved)
    assert hashes=={x:sha256(x) for x in hashes}
    assert not list(out.glob('.partial-*'))
    report={'status':'passed','run_id':run,'source':str(source),'jobs':{'grade':str(grade),'denoise':str(denoise),
        'removal':str(remove),'masked_grade':str(masked),'precision_mask':str(precise),'no_op':str(nothing)},
        'actual_denoise_model':'DRUNet color CUDA float32','noise_sigma':15,'psnr_noisy_db':before,'psnr_denoised_db':after,
        'checks':['grade-only no restoration/upscale','original dimensions and 16-bit precision','actual neural denoise PSNR improvement',
        'clone changed mask with exact outside preservation','masked grade exact outside preservation','40000 mask levels retained',
        'no-op equality','hash-stable rerun','source hashes','corrupt rejection','invalid recipe rejection','output collision rejected',
        'modified outputs preserved','injected OOM and cancellation rollback'],
        'human_quality_review':'pending locally; numerical checks do not establish photographic quality'}
    json_write(out/'verification.json',report);json_write(ROOT/'outputs/latest-edits-verification.json',report)
    print(json.dumps(report,indent=2))
    return report

if __name__=='__main__':verify()
