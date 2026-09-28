"""Actual default chat denoise request -> SCUNet -> verified TIFF/layered PSD."""
import json
from pathlib import Path
import uuid

import numpy as np
import tifffile
import win32com.client
from scipy.io import loadmat

from photo_workflow.runtime import ROOT,json_write,local_runtime,sha256
from photo_workflow.prompt_chat import PromptWorkspace,SYSTEM
from photo_workflow.chat import run_session
from photo_workflow.pipeline import job_lock
from photo_workflow.imaging import save_rgb
from tests.verify_expanded import check_psd


def verify():
    local_runtime()
    uid=uuid.uuid4().hex[:8]
    evidence=ROOT/'outputs'/('scunet-chat-'+uid+'.json')
    report=dict(status='running',evidence=str(evidence))
    latest=ROOT/'outputs/latest-scunet-chat-verification.json';json_write(latest,report)
    try:
        source=ROOT/'tests/fixtures'/('scunet-chat-'+uid+'.tif')
        pixels=loadmat(ROOT/'tests/fixtures/SIDD/ValidationNoisyBlocksSrgb.mat')['ValidationNoisyBlocksSrgb'][0,0]
        save_rgb(source,pixels.astype(np.uint16)*257);digest=sha256(source)
        app=win32com.client.Dispatch('Photoshop.Application')
        before=[(d.Name,d.Saved) for d in app.Documents]
        w=PromptWorkspace()
        prompt=(f'Denoise "{source}" using the default local denoiser with blend strength exactly 0.35. '
                'Keep exposure, colors and dimensions unchanged. Do not upscale, reconstruct faces, '
                'or apply Lightroom noise reduction. Save TIFF and layered PSD automatically.')
        print('EVIDENCE '+str(evidence),flush=True)
        with job_lock(ROOT/'.cache/prompt-chat.lock'),evidence.with_suffix('.log').open('w',encoding='utf-8') as log:
            code=run_session(w,prompt,evidence,SYSTEM,log,profile=ROOT/'apps/OhMyPiPromptData')
        outer=json.loads(evidence.read_text())
        assert code==0 and not outer['failures'],outer
        assert len([e for e in w.events if e['tool']=='edit_photos'])==1
        assert w.result['status']=='passed',w.result
        batch=json.loads(Path(w.result['report']).read_text());item=batch['files'][0]
        inner=json.loads((Path(item['output'])/'model-evidence.json').read_text())
        assert not inner['failures']
        calls=[e for e in inner['events'] if e['tool']=='edit_photo'];assert len(calls)==1
        assert not any(e['tool'] in {'lightroom_develop','photoshop_local','upscale_photo'} for e in inner['events'])
        final=Path(item['final_output']);job=json.loads((final/'job.json').read_text())
        assert job['settings']['recipe']['denoise']==.35 and job['settings']['recipe']['denoise_model']=='scunet'
        assert job['runtime']['denoiser']=='SCUNet color real_psnr'
        assert not job['runtime']['restoration_invoked'] and not job['runtime']['upscale_invoked']
        tiff=tifffile.imread(item['tiff']);assert tiff.dtype==np.uint16 and tiff.shape==(256,256,3)
        psd=check_psd(final);assert psd['layers']==2 and psd['bit_depth']==16
        assert sha256(source)==digest and [(d.Name,d.Saved) for d in app.Documents]==before
        report.update(status='passed',batch_report=w.result['report'],job=str(final),psd=psd,
                      source_sha256=digest,source_preserved=True,existing_photoshop_documents_preserved=True,
                      one_outer_edit_call=True,one_raster_attempt=True,default_denoiser='SCUNet color real_psnr',
                      images_remained_local=True)
    except BaseException as e:
        report.update(status='failed',error=repr(e));raise
    finally:json_write(latest,report)
    print('Passed actual default OMP -> SCUNet -> TIFF/layered 16-bit PSD.',flush=True)


if __name__=='__main__':verify()
