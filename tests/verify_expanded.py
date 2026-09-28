"""Exercise fresh desktop controls -> local tool inference -> worker -> real PSD."""
import json
import time
import tkinter as tk
from types import SimpleNamespace

import numpy as np
import tifffile
from psd_tools import PSDImage

from photo_workflow.runtime import ROOT,json_write,local_runtime,sha256
from photo_workflow.photoshop import export, review_path

def check_psd(folder):
    from pathlib import Path
    folder=Path(folder)
    if not review_path(folder).exists():export(folder)
    job=json.loads((folder/'job.json').read_text());psd=PSDImage.open(review_path(folder))
    assert psd.depth==16 and psd.size==tuple(job['output_size'])
    assert [l.name for l in psd]==['Original - oriented sRGB baseline']+[l['name'] for l in job['layers']]
    errors=[]
    base=np.rint(list(psd)[0].numpy('color')*65535).astype(np.int32)
    assert np.abs(base-tifffile.imread(folder/job.get('baseline_file','original.tif')).astype(np.int32)).max()<=2
    for layer,spec in zip(list(psd)[1:],job['layers']):
        assert layer.has_mask() and not layer.mask.disabled
        full=np.full((psd.height,psd.width),layer.mask.background_color/255,dtype=np.float32)
        value=layer.numpy('mask');left,top,right,bottom=layer.mask.bbox
        if value is not None:full[top:bottom,left:right]=value.squeeze()
        expected=tifffile.imread(folder/spec['mask']).astype(np.int32)
        error=int(np.abs(np.rint(full*65535).astype(np.int32)-expected).max());assert error<=2
        errors.append({'name':layer.name,'max_16bit_error':error,'levels':len(np.unique(full))})
    return {'job':str(folder),'layers':len(list(psd)),'bit_depth':16,'dimensions':list(psd.size),'masks':errors}

def verify():
    local_runtime()
    from photo_workflow.harness import App
    from photo_workflow.edit_panel import Editor,MaskPainter
    import win32com.client
    app_adobe=win32com.client.Dispatch('Photoshop.Application')
    before=[(d.Name,d.Saved) for d in app_adobe.Documents]
    report=json.loads((ROOT/'outputs/latest-edits-verification.json').read_text())
    source=report['source'];source_hash=sha256(source)
    root=tk.Tk();root.withdraw();app=App(root);app.path.set(source)
    editor=Editor(app);editor.window.withdraw()
    psds=[]
    try:
        # Exercise a donor selection and manual removal from actual editor controls.
        clone=[]
        painter=MaskPainter(root,source,True,lambda path,r:clone.append(r));painter.window.withdraw()
        painter.donor(SimpleNamespace(x=320,y=100));painter.begin(SimpleNamespace(x=80,y=100));painter.save()
        editor.saved_removal(clone[0]['mask'],clone[0]);editor.apply()
        deadline=time.monotonic()+60
        while app.busy and time.monotonic()<deadline:root.update();time.sleep(.05)
        assert not app.busy and app.status['text']=='Completed.',app.log.get('1.0','end')
        from pathlib import Path
        manual=Path(next(x.split(' ',1)[1] for x in app.log.get('1.0','end').splitlines() if x.startswith(('DONE ','EXISTING '))))
        assert json.loads((manual/'job.json').read_text())['layers'][0]['name'].startswith('Clone removal')
        psds.append(check_psd(manual));editor.clear_removal()
        # Exercise the actual painter event handlers and saved selection, locally.
        painted=[]
        painter=MaskPainter(root,source,False,lambda path,r:painted.append(path));painter.window.withdraw()
        painter.begin(SimpleNamespace(x=240,y=200));painter.paint(SimpleNamespace(x=280,y=240));painter.save()
        assert painted and tifffile.imread(painted[0]).max()==65535
        editor.saved_mask(painted[0])
        editor.request.delete('1.0','end');editor.request.insert('1.0','Reduce noise moderately across the whole image and lift the selected subject by half a stop while keeping purple stage lighting.')
        editor.psd.set(True);editor.ask()
        deadline=time.monotonic()+150
        while app.busy and time.monotonic()<deadline:root.update();time.sleep(.05)
        assert not app.busy and app.status['text']=='Completed.',app.log.get('1.0','end')
        lines=app.log.get('1.0','end').splitlines()
        from pathlib import Path
        evidence_path=Path(next(x.split('AGENT EVIDENCE ',1)[1] for x in lines if x.startswith('AGENT EVIDENCE ')))
        evidence=json.loads(evidence_path.read_text());assert evidence['status']=='passed'
        assert evidence['tool_call']['function']['name']=='edit_photo' and evidence['model_unloaded_before_worker']
        recipe=evidence['recipe'];assert recipe['denoise']>0 and recipe['exposure']>0
        assert recipe['warmth']==recipe['tint']==0 and recipe['purple_saturation']==1
        psds.append(check_psd(evidence['job']))
        for key in ('grade','removal','precision_mask'):psds.append(check_psd(report['jobs'][key]))
        # Cancel a fresh real model launch through the desktop Stop control.
        editor.psd.set(False);editor.ask();app.stop()
        deadline=time.monotonic()+30
        while app.busy and time.monotonic()<deadline:root.update();time.sleep(.05)
        assert not app.busy and app.status['text']=='Cancelled safely.',app.log.get('1.0','end')
        after=[(d.Name,d.Saved) for d in app_adobe.Documents]
        assert all(x in after for x in before),'Preexisting Adobe documents changed'
        assert sha256(source)==source_hash
        result={'status':'passed','agent_evidence':str(evidence_path),'psds':psds,
            'checks':['fresh panel and editor launched','manual clone painter and Apply controls','mask brush events saved locally','actual local tool call',
            'language model unloaded before DRUNet','agent to layered PSD','saved PSD masks and precision',
            'real safe-stop cancellation from panel','source hash unchanged','preexisting Adobe document names/saved state preserved'],
            'visual_quality':'requires local human review','vision':False,'photos_uploaded':False}
        json_write(ROOT/'outputs/latest-expanded-verification.json',result);print(json.dumps(result,indent=2))
    finally:root.destroy()

if __name__=='__main__':verify()
