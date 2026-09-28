"""SCUNet production worker, precision and transaction acceptance."""
import gc
import json
import uuid
from unittest.mock import patch

import numpy as np
import tifffile
import torch
from scipy.io import loadmat

from photo_workflow.runtime import ROOT, local_runtime, disable_network, sha256, json_write
from photo_workflow.edits import scunet, validate_recipe
from photo_workflow.imaging import save_rgb, save_mask, decode_working
from photo_workflow.pipeline import Pipeline, job_lock
from tests.denoiser_candidates import load_model, infer


def verify():
    local_runtime();disable_network()
    uid=uuid.uuid4().hex[:8]
    folder=ROOT/'outputs'/('scunet-pipeline-'+uid);folder.mkdir()
    report={'status':'running','folder':str(folder)}
    try:
        raw=loadmat(ROOT/'tests/fixtures/SIDD/ValidationNoisyBlocksSrgb.mat')['ValidationNoisyBlocksSrgb'][0,0]
        rgb=raw.astype(np.uint16)*257
        rgb=rgb[:131,:129].copy()
        rgb=np.minimum(rgb.astype(np.uint32)+np.arange(129)[None,:,None],65535).astype(np.uint16)
        source=ROOT/'tests/fixtures'/('scunet-'+uid+'.tif');save_rgb(source,rgb)
        mask=ROOT/'tests/fixtures'/('scunet-mask-'+uid+'.tif')
        mp=np.zeros(rgb.shape[:2],np.uint16);mp[10:110,10:110]=np.arange(10000).reshape(100,100)+1
        save_mask(mask,mp);hashes={str(p):sha256(p) for p in (source,mask)}
        pipeline=Pipeline(folder)
        recipe={'denoise':.35,'denoise_model':'scunet'}
        from photo_workflow.models import Models
        with patch.object(Models,'__init__',side_effect=AssertionError('Face/SR stack invoked')):
            result,skipped=pipeline.process(source,recipe=recipe,settle=0)
        assert not skipped
        job=json.loads((result/'job.json').read_text())
        detail=tifffile.imread(result/'edit-01.tif');actual=tifffile.imread(result/'composite.tif')
        expected=np.clip(np.rint(detail.astype(np.float32)*.35+rgb.astype(np.float32)*.65),0,65535).astype(np.uint16)
        assert np.array_equal(actual,expected) and detail.dtype==np.uint16 and np.unique(detail).size>256
        assert job['runtime']['denoiser']=='SCUNet color real_psnr' and job['settings']['denoise_manifest']==sha256(ROOT/'models/scunet-manifest.json')
        assert np.array_equal(tifffile.imread(result/'original.tif'),rgb)
        assert job['layers'][0]['name']=='SCUNet real PSNR denoise' and job['layers'][0]['opacity']==35
        again,skipped=pipeline.process(source,recipe=recipe,settle=0);assert skipped and again==result
        with job_lock(ROOT/'.cache/gpu.lock'):
            # Independent evaluation implementation must agree with the production route.
            model=load_model('scunet')
            old=(torch.backends.cuda.matmul.allow_tf32,torch.backends.cudnn.allow_tf32)
            try:
                torch.backends.cuda.matmul.allow_tf32=False;torch.backends.cudnn.allow_tf32=False
                reference=infer(model,'scunet',rgb)
            finally:
                torch.backends.cuda.matmul.allow_tf32,torch.backends.cudnn.allow_tf32=old
                del model;gc.collect();torch.cuda.empty_cache()
            assert np.array_equal(detail,reference)
        with patch('photo_workflow.edits.scunet',side_effect=AssertionError('Zero strength loaded model')):
            zero,_=pipeline.process(source,recipe={'denoise':0,'denoise_model':'scunet'},settle=0)
        assert np.array_equal(tifffile.imread(zero/'composite.tif'),rgb)
        masked,_=pipeline.process(source,recipe=dict(recipe,exposure=.2,grade_mask=str(mask)),settle=0)
        assert np.array_equal(tifffile.imread(masked/'composite.tif')[mp==0],actual[mp==0])
        assert np.array_equal(tifffile.imread(masked/'edit-02-mask.tif'),mp)
        legacy,_=pipeline.process(source,recipe={'denoise':.35},settle=0)
        assert legacy!=result and json.loads((legacy/'job.json').read_text())['runtime']['denoiser']=='DRUNet color'
        for bad in ('nafnet','remote',None,{},True):
            try:validate_recipe({'denoise_model':bad})
            except ValueError:pass
            else:raise AssertionError('Invalid denoiser accepted')
        before=set(folder.iterdir())
        # Fail inside the actual model call, after it has allocated on CUDA.
        with patch.object(torch.nn.Module,'_call_impl',side_effect=torch.cuda.OutOfMemoryError('simulated SCUNet forward OOM')):
            try:pipeline.process(source,recipe=dict(recipe,denoise=.371),settle=0)
            except torch.cuda.OutOfMemoryError:pass
            else:raise AssertionError('OOM swallowed')
        assert not list(folder.glob('.partial-*'))
        # Cancel at a tile boundary after a first real CUDA tile.
        calls=0
        def cancel():
            nonlocal calls
            calls+=1
            if calls==3:raise KeyboardInterrupt()
        large,_=decode_working((ROOT/'tests/fixtures/astronaut.png').read_bytes())
        large_source=ROOT/'tests/fixtures'/('scunet-cancel-'+uid+'.tif');save_rgb(large_source,large)
        with patch('photo_workflow.edits.check_cancel',side_effect=cancel):
            try:pipeline.process(large_source,recipe=recipe,settle=0)
            except KeyboardInterrupt:pass
            else:raise AssertionError('Cancellation swallowed')
        assert calls==3 and not list(folder.glob('.partial-*'))
        assert not [p for p in set(folder.iterdir())-before if p.name!='errors']
        with patch('photo_workflow.edits.sha256',return_value='bad'):
            try:scunet(rgb)
            except RuntimeError as e:assert 'checksum' in str(e)
            else:raise AssertionError('Tampering accepted')
        with job_lock(ROOT/'.cache/gpu.lock'):
            try:pipeline.process(source,recipe=recipe,settle=0)
            except RuntimeError as e:assert 'already' in str(e)
            else:raise AssertionError('GPU lock bypassed')
        assert all(sha256(p)==digest for p,digest in hashes.items())
        gc.collect();torch.cuda.empty_cache()
        report.update(status='passed',job=str(result),source_hashes=hashes,source_preserved=True,
                      production_matches_evaluation_exactly=True,odd_dimensions=True,precision='uint16; >256 unique levels',
                      exact_blend=True,mask_precision_preserved=True,legacy_recipe_uses_drunet=True,
                      distinct_model_identity=True,zero_strength_no_model=True,rerun_deduplicated=True,
                      simulated_forward_oom_atomic=True,cancellation_after_actual_tile_atomic=True,
                      checksum_rejection=True,gpu_lock_rejection=True,remaining_cuda_allocated_bytes=torch.cuda.memory_allocated())
    except BaseException as e:
        report.update(status='failed',error=repr(e));raise
    finally:
        json_write(folder/'verification.json',report);json_write(ROOT/'outputs/latest-scunet-pipeline-verification.json',report)
    print(json.dumps(report,indent=2))


if __name__=='__main__':verify()
