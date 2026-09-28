"""Local UI and shutdown guards; never capture or transmit images."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import tkinter as tk

from photo_workflow.finish import close_adobe, finish_batch
from photo_workflow.review_panel import ReviewPanel
from photo_workflow.runtime import ROOT, json_write, local_runtime


def verify():
    local_runtime()
    root=ROOT/'outputs/finish-boundaries';root.mkdir(exist_ok=True)
    evidence=json.loads((ROOT/'outputs/latest-major-combined-chat-verification.json').read_text())
    report=json.loads(Path(evidence['batch_report']).read_text())
    path=root/'batch.json';json_write(path,report)
    window=tk.Tk();panel=ReviewPanel(window,path)
    try:
        window.update()
        assert len(panel.pixels)==2 and len(panel.images)==2
        panel.mode.set('100%');panel.draw();window.update()
        panel.start_pan(SimpleNamespace(x=100,y=100))
        panel.pan(SimpleNamespace(x=50,y=60,widget=panel.canvases[0]))
        assert panel.center!=[.5,.5]
        panel.select(1);window.update()
        assert panel.index==0
        assert json.loads((root/'review-ui-status.json').read_text())['status']=='ready'
    finally:window.destroy()
    session=SimpleNamespace(app=SimpleNamespace(Documents=[SimpleNamespace(Saved=False)]),verify=lambda:None)
    with patch('photo_workflow.finish.adobe_windows',return_value={'photoshop.exe':[(12,34)]}),patch('win32gui.PostMessage') as post:
        result=close_adobe(report['catalog'],session)
        assert result['Photoshop']['status']=='left open';post.assert_not_called()
    with patch('photo_workflow.finish.adobe_windows',return_value={'lightroom.exe':[(12,34)]}),patch('photo_workflow.lightroom.request',return_value={'catalog':str(ROOT/'different.lrcat')}),patch('win32gui.PostMessage') as post:
        result=close_adobe(report['catalog'])
        assert result['Lightroom']['status']=='left open';post.assert_not_called()
    with patch('photo_workflow.finish.close_adobe') as close,patch('subprocess.Popen') as launch:
        assert finish_batch(path,{'status':'failed','files':[]})['status']=='skipped'
        close.assert_not_called();launch.assert_not_called()
    with patch('photo_workflow.finish.close_adobe',side_effect=RuntimeError('simulated Adobe unavailable')),patch('subprocess.Popen',return_value=SimpleNamespace(pid=123)) as launch:
        result=finish_batch(path,report)
        assert result['review']=='launched' and result['adobe']['shutdown']['status']=='left open'
        launch.assert_called_once()
    json_write(root/'verification.json',{'status':'passed','checks':['Real Tk before/after and fit/100% pan/navigation without image transmission','Unsaved Photoshop and changed Lightroom catalog prevent close','Failed batch neither closes apps nor opens success UI','Review launch survives shutdown failure'],'shutdown_guard_tests':'mocked; actual successful shutdown recorded separately'})
    print('Passed local review UI and safe shutdown boundaries.')


if __name__=='__main__':verify()
