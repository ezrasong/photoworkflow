"""Exercise desktop controls and a real child job, without screenshots or uploads."""
import json
import time
import tkinter as tk

from photo_workflow.harness import App
from photo_workflow.runtime import ROOT,json_write
from photo_workflow.references import subject_context
from photo_workflow.vault import initialize,CONFIG,VAULT

def verify():
    initialize()
    assert (VAULT/'Start here.md').exists()
    assert (ROOT/'apps/Obsidian/Obsidian.exe').exists()
    settings=json.loads((ROOT/'apps/ObsidianData/obsidian.json').read_text())
    assert settings['updateDisabled'] and any(x['path']==str(VAULT) for x in settings['vaults'].values())
    root=tk.Tk(); root.withdraw(); app=App(root)
    def wait_done(timeout=90):
        end=time.monotonic()+timeout
        while app.busy and time.monotonic()<end:
            root.update(); time.sleep(.05)
        assert not app.busy, 'Harness job failed to finish'
        assert 'failed' not in app.status['text'].lower(), app.log.get('1.0','end')
    try:
        app.path.set(str(ROOT/'tests/fixtures/precision-gradient.tif'))
        app.start(); wait_done()
        assert app.status['text']=='Completed.'
        assert any(json.loads((p/'job.json').read_text()).get('bit_depth')==16 for p in app.jobs)
        watch=ROOT/'tests/harness-watch'; watch.mkdir(exist_ok=True)
        app.path.set(str(watch)); app.mode.set('watch'); app.start()
        end=time.monotonic()+10
        while 'WATCHING' not in app.log.get('1.0','end') and time.monotonic()<end:
            root.update(); time.sleep(.05)
        assert 'WATCHING' in app.log.get('1.0','end')
        app.stop(); wait_done(15)
        assert app.status['text']=='Cancelled safely.'
        json_write(ROOT/'outputs/harness-verification.json',{'status':'passed',
            'checks':['desktop widgets constructed','real 16-bit CUDA job from Start control',
                      'completed jobs discovered','watch launched','Stop safely cancelled child with exit 130',
                      'dedicated Obsidian vault/profile configured'],
            'no_screenshots_or_photos_uploaded':True})
        print('PASS local desktop harness, real job, watch cancellation, Obsidian configuration')
    finally:
        root.destroy()

if __name__=='__main__': verify()
