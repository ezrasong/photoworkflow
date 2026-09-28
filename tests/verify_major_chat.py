"""Natural requests through omp.cmd's DEFAULT route; real TIFF and PSD inspection."""
import argparse
import json
from pathlib import Path
import subprocess
import time
import uuid

import numpy as np
import tifffile
import win32com.client

from photo_workflow.runtime import ROOT, json_write, local_runtime, sha256
from photo_workflow.imaging import decode_working, save_rgb
from tests.verify_expanded import check_psd


def verify(case):
    local_runtime(); uid=uuid.uuid4().hex[:8]
    evidence=ROOT/'outputs'/f'major-chat-{case}-{uid}.json'
    report=dict(status='running',case=case,evidence=str(evidence),launcher='omp.cmd default')
    record=ROOT/'outputs'/f'major-chat-{case}-{uid}-verification.json'
    started=time.monotonic()
    try:
        if case=='face':
            rgb,_=decode_working((ROOT/'tests/fixtures/astronaut.png').read_bytes(),16,False)
            source=ROOT/'tests/fixtures'/f'major-faces-{uid}.tif'
            save_rgb(source,np.concatenate((rgb,rgb),axis=1))
        else:
            source=ROOT/'tests/fixtures/COCO/000000252219.jpg'
        digest=sha256(source)
        requests={
            'selective':'Brighten only the person on the left by half a stop. Leave the background and other people unchanged.',
            'removal':'Remove only the person on the right using local inpainting. Leave everything outside the removal region unchanged.',
            'face':'Restore only the face on the left with strength 0.25. Leave the other face and background unchanged.',
            'combined':'Crop to the central 95 percent of the image width, keeping the full height. Denoise only the person on the left with blend strength 0.25 and brighten that person by 0.3 stop. Leave other pixels unchanged after the crop.'}
        prompt=f'Edit {source.relative_to(ROOT).as_posix()} . {requests[case]} Save TIFF and layered PSD automatically.'
        app=win32com.client.Dispatch('Photoshop.Application')
        before=[(d.Name,d.Saved) for d in app.Documents]
        report.update(source=str(source),source_sha256=digest,photoshop_documents_before=before)
        json_write(record,report)
        print('EVIDENCE '+str(evidence),flush=True)
        with evidence.with_suffix('.log').open('w',encoding='utf-8') as log:
            run=subprocess.run([str(ROOT/'omp.cmd'),'--prompt',prompt,'--evidence',str(evidence)],cwd=ROOT,
                stdout=log,stderr=subprocess.STDOUT,text=True,timeout=1800,creationflags=subprocess.CREATE_NO_WINDOW)
        outer=json.loads(evidence.read_text(encoding='utf-8'))
        assert run.returncode==0 and not outer['failures'],outer.get('failures')
        edits=[e for e in outer['events'] if e['tool']=='edit_photos'];assert len(edits)==1
        result=edits[0]['result'];assert result['status']=='passed',result
        batch=json.loads(Path(result['report']).read_text(encoding='utf-8'));item=batch['files'][0]
        inner=json.loads((Path(item['output'])/'model-evidence.json').read_text(encoding='utf-8'))
        assert not inner['failures']
        assert len([e for e in inner['events'] if e['tool']=='edit_photo'])==1
        final=Path(item['final_output']);job=json.loads((final/'job.json').read_text(encoding='utf-8'))
        recipe=job['settings']['recipe']
        if case=='selective':
            assert recipe['exposure']==.5 and recipe['selection']['position']=='leftmost'
            assert not recipe['selection']['invert'] and not recipe['denoise']
        elif case=='removal':
            assert recipe['inpaint']['target']==dict(category='person',position='rightmost')
            assert job['runtime']['inpainting_invoked']
        elif case=='face':
            assert recipe['restore_faces']==dict(position='leftmost',strength=.25)
            assert job['faces']==1 and len(job['runtime']['face']['selection']['detected_boxes'])==2
        elif case=='combined':
            assert recipe['denoise_scope']=='selection' and recipe['denoise']==.25 and recipe['exposure']==.3
            assert len([e for e in inner['events'] if e['tool']=='lightroom_develop'])==1
            crop=next(e['result']['settings'] for e in inner['events'] if e['tool']=='lightroom_develop')
            assert abs(crop['CropLeft']-.025)<.002 and abs(crop['CropRight']-.975)<.002, crop
            assert abs(job['input_size'][0]-608)<=2
            denoise=json.loads((final/'denoise-selection.json').read_text())
            grade=json.loads((final/'grade-selection.json').read_text())
            assert denoise['source_pixel_sha256']!=grade['source_pixel_sha256']
        original=tifffile.imread(final/'original.tif');after=tifffile.imread(final/'composite.tif')
        support=np.zeros(original.shape[:2],bool)
        for layer in job['layers']:support|=tifffile.imread(final/layer['mask'])>0
        assert np.array_equal(original[~support],after[~support])
        assert np.any(original!=after) and after.dtype==np.uint16
        psd=check_psd(final)
        assert psd['layers']==len(job['layers'])+1 and psd['bit_depth']==16
        report.update(batch_report=result['report'],job=str(final),recipe=recipe,psd=psd,
                      source_preserved=sha256(source)==digest,outside_effective_masks_exact=True,
                      one_outer_edit_call=True,one_raster_attempt=True,images_remained_local=True)
        json_write(record,report)
        assert sha256(source)==digest and [(d.Name,d.Saved) for d in app.Documents]==before
        report.update(status='passed',batch_report=result['report'],job=str(final),recipe=recipe,psd=psd,
                      source_sha256=digest,source_preserved=True,existing_photoshop_documents_preserved=True,
                      outside_effective_masks_exact=True,images_remained_local=True,
                      one_outer_edit_call=True,one_raster_attempt=True,seconds=time.monotonic()-started)
    except BaseException as e:
        report.update(status='failed',error=repr(e));raise
    finally:
        json_write(record,report)
        json_write(ROOT/'outputs'/f'latest-major-{case}-chat-verification.json',report)
    print('Passed '+case+' default launcher -> TIFF/layered16 PSD.',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('case',choices=['selective','removal','face','combined'])
    verify(parser.parse_args().case)
