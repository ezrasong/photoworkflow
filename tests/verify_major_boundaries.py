"""Trust-boundary checks for new fields without GPU or Adobe mutations."""
from unittest.mock import patch
import json
import subprocess
import io

from photo_workflow.chat import Workspace
from photo_workflow.runtime import ROOT
from photo_workflow.unified_batch import reconstruction_permissions, authorize_reconstruction
from tests.verify_unified_chat import rejects, boundaries


def verify():
    from PIL import Image
    from photo_workflow.edits import mask_pixels
    for mode, size, color in [('L',(2,2),255),('RGB',(4,4),(255,255,255)),('L',(4,4),0)]:
        buffer=io.BytesIO();Image.new(mode,size,color).save(buffer,format='PNG')
        rejects(lambda:mask_pixels(buffer.getvalue(),(4,4,3)))
    source=ROOT/'tests/fixtures/astronaut.png'
    w=Workspace(source);w.request_prompt='Remove the person on the right'
    args=dict(scope='automatic',exposure=0,denoise=0,
              inpaint=dict(target=dict(category='person',position='rightmost'),use_user_mask=False))
    captured=[]
    def worker(command,**kwargs):
        path=command[command.index('--recipe')+1]
        captured.append(json.loads(open(path,encoding='utf-8').read()))
        return subprocess.CompletedProcess(command,0,'DONE '+str(ROOT/'outputs/boundary-placeholder')+'\n','')
    with patch('photo_workflow.chat.subprocess.run',side_effect=worker):
        w.call('edit_photo',args)
    assert captured[0]['inpaint']==dict(target=dict(category='person',position='rightmost'),expand=8,feather=4)
    assert not captured[0]['exposure'] and not captured[0]['denoise']
    rejects(lambda:w.call('edit_photo',dict(args,exposure=.3)))
    rejects(lambda:w.call('edit_photo',dict(scope='whole_image',inpaint=dict(mask=str(source)))))
    rejects(lambda:w.call('edit_photo',dict(scope='automatic',selection=dict(category='person',position='single'),exposure=0,denoise=.25)))
    rejects(lambda:w.call('edit_photo',dict(scope='automatic',selection=dict(category='person',position='single'),exposure=0,denoise=0)))
    assert reconstruction_permissions('Denoise and upscale this photo')==[]
    assert reconstruction_permissions('Remove noise and grain from the person')==[]
    assert reconstruction_permissions('Remove the noise from this photo')==[]
    assert reconstruction_permissions('Remove the person on the right')==['inpaint']
    assert reconstruction_permissions('Restore only the face on the left')==['restore_faces']
    assert reconstruction_permissions('Do not remove anything. Do not restore faces.')==[]
    assert reconstruction_permissions('Improve "D:\\Photos\\restore face.png"')==[]
    assert reconstruction_permissions("Improve 'D:\\Photos\\restore face.png'")==[]
    assert reconstruction_permissions('Improve `D:\\Photos\\restore face.png`')==[]
    rejects(lambda:authorize_reconstruction('Restore the face',dict(restore_faces=dict(position='all'))))
    boundaries()
    print('Major-editing schemas, reconstruction opt-in, optional false flag and selection/no-op guards passed.')


if __name__=='__main__':verify()
