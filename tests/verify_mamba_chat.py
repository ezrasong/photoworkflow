"""Actual default Oh My Pi prompt -> MambaIRv2 -> TIFF and layered PSD."""
import json
from pathlib import Path
import uuid

import cv2
import tifffile
import win32com.client

from photo_workflow.runtime import ROOT, json_write, local_runtime, sha256
from photo_workflow.prompt_chat import PromptWorkspace, SYSTEM
from photo_workflow.chat import run_session
from photo_workflow.pipeline import job_lock
from photo_workflow.imaging import decode_working, save_rgb
from tests.verify_expanded import check_psd


def verify():
    local_runtime()
    uid=uuid.uuid4().hex[:8]
    source=ROOT/'tests/fixtures'/('mamba-chat-'+uid+'.tif')
    pixels,_=decode_working((ROOT/'tests/fixtures/astronaut.png').read_bytes())
    save_rgb(source,cv2.resize(pixels,(128,128),interpolation=cv2.INTER_AREA))
    digest=sha256(source)
    app=win32com.client.Dispatch('Photoshop.Application')
    before=[(d.Name,d.Saved) for d in app.Documents]
    w=PromptWorkspace()
    evidence=ROOT/'outputs'/('mamba-chat-'+uid+'.json')
    prompt=(f'Upscale "{source}" 2x using local MambaIRv2 with detail strength 0.2. '
            'Do not change exposure or color and do not denoise or reconstruct faces. Save TIFF and PSD automatically.')
    print('EVIDENCE '+str(evidence),flush=True)
    with job_lock(ROOT/'.cache/prompt-chat.lock'),evidence.with_suffix('.log').open('w',encoding='utf-8') as log:
        code=run_session(w,prompt,evidence,SYSTEM,log,profile=ROOT/'apps/OhMyPiPromptData')
    outer=json.loads(evidence.read_text())
    assert code==0 and not outer['failures'],outer
    assert len([e for e in w.events if e['tool']=='edit_photos'])==1
    assert w.result['status']=='passed',w.result
    batch=json.loads(Path(w.result['report']).read_text())
    item=batch['files'][0]
    record=json.loads((Path(item['output'])/'model-evidence.json').read_text())
    assert not record['failures']
    upscales=[e for e in record['events'] if e['tool']=='upscale_photo' and e['result'].get('job')]
    assert len(upscales)==1 and upscales[0]['result']['model']=='mambairv2'
    assert not any(e['tool'] in {'lightroom_develop','edit_photo','photoshop_local'} for e in record['events'])
    final=Path(item['final_output'])
    job=json.loads((final/'job.json').read_text())
    assert job['settings']['upscale_model']=='mambairv2' and job['settings']['upscale_strength']==.2
    assert job['runtime']['upscaler']=='MambaIRv2 Large classical SR'
    assert not job['runtime']['restoration_invoked']
    actual=tifffile.imread(item['tiff'])
    assert str(actual.dtype)=='uint16' and actual.shape==(256,256,3)
    psd=check_psd(final)
    assert sha256(source)==digest
    assert [(d.Name,d.Saved) for d in app.Documents]==before
    json_write(ROOT/'outputs/latest-mamba-chat-verification.json',{'status':'passed',
        'evidence':str(evidence),'batch_report':w.result['report'],'job':str(final),'psd':psd,
        'source_preserved':True,'existing_photoshop_documents_preserved':True,
        'one_main_chat_prompt':True,'local_mambairv2':True,'face_restoration':False})
    print('Passed actual default OMP -> MambaIRv2 -> TIFF/layered 16-bit PSD.',flush=True)


if __name__=='__main__':verify()
