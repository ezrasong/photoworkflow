"""Natural-language -> real visual tool -> natural upscale -> visual review -> PSD."""
import json
from pathlib import Path
import subprocess
import sys
import uuid

from photo_workflow.runtime import ROOT,json_write,sha256,local_runtime
from photo_workflow.chat import Workspace,TOOLS


def verify():
    local_runtime()
    # A newly generated public-domain fixture variant ensures new processing.
    from PIL import Image,PngImagePlugin
    source=ROOT/'tests/fixtures'/('visual-chat-'+uuid.uuid4().hex+'.png')
    metadata=PngImagePlugin.PngInfo();metadata.add_text('test_id',uuid.uuid4().hex)
    with Image.open(ROOT/'tests/fixtures/astronaut.png') as image:
        image.resize((256,256),Image.Resampling.LANCZOS).save(source,pnginfo=metadata)
    digest=sha256(source)
    evidence=ROOT/'outputs'/('visual-chat-'+uuid.uuid4().hex[:8]+'.json')
    prompt=('Inspect the selected photograph locally and briefly note visible details. '
            'Then use upscale_photo on the source at exactly 2x with detail_strength 0.15 and no face reconstruction. '
            'Inspect a source/result comparison for invented details or excessive smoothing. '
            'Finally export a layered PSD. Do not search online or save a note for this test. '
            'Do not claim references conditioned the upscale.')
    with evidence.with_suffix('.log').open('w',encoding='utf-8') as log:
        run=subprocess.run([sys.executable,'-m','photo_workflow.chat','--source',str(source),'--prompt',prompt,
                            '--evidence',str(evidence)],cwd=ROOT,stdout=log,stderr=log,timeout=600,
                           creationflags=subprocess.CREATE_NO_WINDOW)
    assert run.returncode==0
    record=json.loads(evidence.read_text())
    names=[x['tool'] for x in record['events']]
    assert names.count('inspect_photo')>=2 and 'upscale_photo' in names and 'export_psd' in names,names
    assert not record['failures'],record['failures']
    assert all(set(x)==TOOLS for x in record['tool_sets'])
    result=next(x['result'] for x in record['events'] if x['tool']=='upscale_photo')
    job=Path(result['job']);data=json.loads((job/'job.json').read_text())
    assert data['output_size']==[512,512] and data['settings']['upscale_strength']==.15
    assert data['runtime']['restoration_invoked'] is False and data['faces']==0
    from tests.verify_expanded import check_psd
    psd=check_psd(job)
    from psd_tools import PSDImage
    saved=PSDImage.open(job/'review.psd');assert abs(list(saved)[1].opacity/255-.15)<.005
    assert sha256(source)==digest
    json_write(ROOT/'outputs/latest-visual-chat-verification.json',{'status':'passed','model':record['model'],
        'evidence':str(evidence),'tools':names,'psd':psd,'source_preserved':True,'face_reconstruction':False,
        'reference_conditioned_upscale':False,'quality':'Visual judgment remains fallible; local human review required'})
    print('Passed actual visual chat -> conservative upscale -> visual comparison -> layered 16-bit PSD.')


if __name__=='__main__':
    json_write(ROOT/'outputs/latest-visual-chat-verification.json',{'status':'running'})
    try:verify()
    except BaseException as error:
        json_write(ROOT/'outputs/latest-visual-chat-verification.json',{'status':'failed','error':repr(error)})
        raise
