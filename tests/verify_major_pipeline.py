"""Regional precision, selected GFPGAN, geometry, correction and failure boundaries."""
import json
import os
from pathlib import Path
from types import SimpleNamespace
import uuid
from unittest.mock import patch

import cv2
import numpy as np
import tifffile

from photo_workflow.runtime import ROOT, local_runtime, json_write, sha256
from photo_workflow.imaging import decode_working, save_rgb, save_mask
from photo_workflow.pipeline import Pipeline, job_lock
from photo_workflow.edits import validate_recipe, prepare, edit_layers
from photo_workflow.selection import assert_binding, automatic_mask, pixel_hash, feather, choose_indices
from photo_workflow.unified_batch import authorize_reconstruction


def rejects(action):
    try: action()
    except (ValueError, RuntimeError): return
    raise AssertionError('Expected rejection')


def verify():
    local_runtime();uid=uuid.uuid4().hex[:8]
    folder=ROOT/'outputs'/('major-pipeline-'+uid);folder.mkdir()
    report=dict(status='running',folder=str(folder),checks=[])
    marker=ROOT/'.cache/control'/('major-cancel-'+uid);marker.parent.mkdir(exist_ok=True)
    try:
        for value in [dict(restore_faces=dict(position='single',strength=float('nan'))),
                      dict(restore_faces=dict(position='single',strength=.6)),
                      dict(selection=dict(category='unknown thing',position='single')),
                      dict(inpaint=dict(target=dict(category='person',position='single'),expand=33)),
                      dict(denoise_scope='selection')]:
            rejects(lambda:validate_recipe(value))
        for request in ['Improve this photo','Denoise and upscale 2x','Do not restore faces','Upscale without face reconstruction']:
            rejects(lambda:authorize_reconstruction(request,dict(restore_faces=dict(position='single',strength=.25))))
        rejects(lambda:authorize_reconstruction('Do not remove the person',dict(inpaint=dict(target=dict(category='person',position='single')))))
        rejects(lambda:authorize_reconstruction('Restore one face',dict(restore_faces=dict(position='all',strength=.25))))
        rejects(lambda:choose_indices([[0,0,10,10],[20,0,30,10]],'single',30))
        rejects(lambda:choose_indices([[0,0,10,10],[1,10,11,20]],'leftmost',100))
        report['checks'].append('argument, ambiguity, positional authorization, no implicit/negated face invocation')
        rgb,_=decode_working((ROOT/'tests/fixtures/astronaut.png').read_bytes(),16,False)
        # Introduce sub-8-bit differences into a licensed fixture to prove preservation.
        low=(np.arange(rgb.size).reshape(rgb.shape)%127).astype(np.int32)
        rgb=np.clip(rgb.astype(np.int32)+low,0,65535).astype(np.uint16)
        source=folder/'two-faces.tif';save_rgb(source,np.concatenate((rgb,rgb),axis=1));digest=sha256(source)
        original=tifffile.imread(source)
        pipe=Pipeline(folder/'jobs')
        with patch('photo_workflow.models.Models',side_effect=AssertionError('Zero strength loaded a model')):
            zero,_=pipe.process(source,settle=0,recipe=dict(restore_faces=dict(position='leftmost',strength=0)))
        assert np.array_equal(tifffile.imread(zero/'composite.tif'),original)
        job,_=pipe.process(source,settle=0,recipe=dict(restore_faces=dict(position='leftmost',strength=.25)))
        data=json.loads((job/'job.json').read_text());sel=data['runtime']['face']['selection']
        assert len(sel['selected_indices'])==1 and len(sel['detected_boxes'])==2
        assert len(data['layers'])==1 and data['layers'][0]['opacity']==25
        mask=tifffile.imread(job/data['layers'][0]['mask']);output=tifffile.imread(job/'composite.tif')
        assert np.array_equal(output[mask==0],original[mask==0])
        assert np.array_equal(output[:,512:],original[:,512:])
        layer=tifffile.imread(job/data['layers'][0]['file']);alpha=mask[...,None].astype(np.float32)/65535*.25
        expected=np.rint(layer.astype(np.float32)*alpha+original.astype(np.float32)*(1-alpha)).astype(np.uint16)
        assert np.array_equal(output,expected) and np.any(output!=original)
        assert len(np.unique(mask))>256
        _,reused=pipe.process(source,settle=0,recipe=dict(restore_faces=dict(position='leftmost',strength=.25)));assert reused
        report.update(face_job=str(job),face_runtime=data['runtime']['face'])
        report['checks'].append('actual selected GFPGAN; only left face; zero bypass; exact strength and non-face preservation; mask precision; reuse')
        # Imported mask precision and explicit masked denoising use the same blend owner.
        mask=np.zeros(original.shape[:2],np.uint16)
        mask[200:300,200:300]=np.arange(10000,dtype=np.uint16).reshape(100,100)*6
        supplied=folder/'manual.tif';save_mask(supplied,mask)
        masked,_=pipe.process(source,settle=0,recipe=dict(grade_mask=str(supplied),denoise=.25,denoise_model='scunet',denoise_scope='selection',exposure=.1))
        after=tifffile.imread(masked/'composite.tif');assert np.array_equal(after[mask==0],original[mask==0])
        report['checks'].append('real SCUNet explicit mask blend preserves low bits outside mask')
        # Reuse the real segmentation model on an oriented/cropped render.
        from PIL import Image
        from io import BytesIO
        photo=ROOT/'tests/fixtures/COCO/000000252219.jpg'
        with Image.open(photo) as im:
            rotated=im.transpose(Image.Transpose.ROTATE_90)
            exif=Image.Exif();exif[274]=6
            buffer=BytesIO();rotated.save(buffer,format='JPEG',quality=98,exif=exif)
        oriented,_=decode_working(buffer.getvalue(),16,False)
        cropped=oriented[:,10:-10].copy()
        with job_lock(ROOT/'.cache/gpu.lock'):
            auto,record=automatic_mask(cropped,dict(category='person',position='leftmost'))
        assert_binding(record,cropped)
        for stale in (oriented,cropped[:,::-1],np.rot90(cropped),cv2.resize(cropped,None,fx=2,fy=2)):
            rejects(lambda:assert_binding(record,stale))
        complement=65535-auto;assert np.all(auto.astype(np.uint32)+complement==65535)
        assert np.all(feather(auto,8)[auto==0]==0)
        report['checks'].append('actual mask after EXIF orientation/crop; exact complement; inward feather; changed/cropped/rotated/upscaled stale rejection')
        # Existing painter loads precise masks, erases locally and records the new binding.
        import tkinter as tk
        from photo_workflow.edit_panel import MaskPainter
        root=tk.Tk();root.withdraw();saved=[]
        try:
            painter=MaskPainter(root,str(source),False,lambda p,r:saved.append(p),initial_mask=str(supplied))
            painter.window.withdraw();painter.erase.set(True);painter.radius.set(2)
            painter.begin(SimpleNamespace(x=205/painter.scale,y=205/painter.scale));painter.save()
            corrected=tifffile.imread(saved[0]);assert np.array_equal(corrected[250:],mask[250:])
            binding=json.loads(Path(saved[0]).with_suffix('.json').read_text());assert_binding(binding,original)
        finally:root.destroy()
        report['checks'].append('real local correction UI preserves untouched 16-bit mask values and writes binding')
        # Failure proof uses an explicit supplied small hole; each attempt has a fresh output root.
        hole=np.zeros(original.shape[:2],np.uint16);hole[80:100,80:100]=65535
        holepath=folder/'hole.tif';save_mask(holepath,hole)
        recipe=dict(inpaint=dict(mask=str(holepath),expand=0,feather=2))
        from photo_workflow import inpainting
        with patch.object(inpainting,'inpaint',side_effect=RuntimeError('simulated CUDA out of memory')):
            rejects(lambda:Pipeline(folder/'oom').process(source,settle=0,recipe=recipe))
        real=inpainting.inpaint
        def cancel_after_real(*args):
            result=real(*args);marker.touch();return result
        with patch.dict(os.environ,PHOTOWORKFLOW_CANCEL_FILE=str(marker)),patch.object(inpainting,'inpaint',side_effect=cancel_after_real):
            try:Pipeline(folder/'cancel').process(source,settle=0,recipe=recipe)
            except KeyboardInterrupt:pass
            else:raise AssertionError('Cancellation did not stop publication')
        marker.unlink(missing_ok=True)
        for name in ('oom','cancel'):
            assert not list((folder/name).glob('.partial-*'))
            assert len(list((folder/name/'errors').glob('*.json')))==1
            assert not list((folder/name).glob('*/job.json'))
        with job_lock(ROOT/'.cache/gpu.lock'):
            rejects(lambda:Pipeline(folder/'locked').process(source,settle=0,recipe={}))
        # Existing artifact corruption must never be overwritten by deduplication.
        with (zero/'recipe.json').open('a') as f:f.write(' ')
        rejects(lambda:pipe.process(source,settle=0,recipe=dict(restore_faces=dict(position='leftmost',strength=0))))
        assert sha256(source)==digest
        from tests.verify_unified_chat import boundaries
        boundaries()
        report['checks'].append('simulated OOM and cancellation after real inpainting clean partial output, retain failure; GPU lock, collision, original hash, unified no-retry/authorization')
        report['status']='passed'
    except BaseException as e:
        report.update(status='failed',error=repr(e));raise
    finally:
        marker.unlink(missing_ok=True)
        json_write(folder/'verification.json',report)
        json_write(ROOT/'outputs/latest-major-pipeline-verification.json',report)
    print('Major pipeline checks passed: '+str(folder),flush=True)


if __name__=='__main__':verify()
