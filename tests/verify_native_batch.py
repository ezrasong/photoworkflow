"""Real folder + prompt test. Public fixture only; no cloud pixel inspection."""
import json
from pathlib import Path
import shutil
import tempfile
import uuid
from unittest.mock import patch

from photo_workflow.runtime import ROOT, json_write, sha256, local_runtime
from photo_workflow.native_batch import NativeWorkspace, inputs, run


def boundaries():
    from photo_workflow.chat import Workspace, control
    from photo_workflow import lightroom
    def rejects(action, kind=ValueError):
        try: action()
        except kind: return
        raise AssertionError('Unsafe action accepted')
    with tempfile.TemporaryDirectory(dir=ROOT/'.cache') as name:
        folder = Path(name)
        shutil.copyfile(ROOT/'tests/fixtures/astronaut.png', folder/'one.png')
        (folder/'note.txt').write_text('not an image')
        (folder/'nested').mkdir()
        shutil.copyfile(folder/'one.png', folder/'nested/two.png')
        files, skipped = inputs(folder)
        assert files == [folder/'one.png'] and len(skipped) == 2
        rejects(lambda: inputs(folder/'note.txt'))
        rejects(lambda: run(folder, 'edit', output=folder/'results'))
        w = NativeWorkspace(folder/'one.png', folder/'one.png', folder/'test.lrcat', str(uuid.uuid4()))
        assert len(Workspace.tools) == 11
        for tool in ('edit_photo', 'upscale_photo', 'choose_references', 'save_note', 'export_psd'):
            rejects(lambda: w.call(tool, {}))
        rejects(lambda: control(w, 'photo'))
        from photo_workflow.chat import running
        import requests
        with running(w) as broker:
            session=requests.Session();session.trust_env=False
            url=f'http://127.0.0.1:{broker.server_port}'
            headers={'Authorization':'Bearer '+broker.token}
            response=session.post(url+'/v1/chat/completions',headers=headers,
                json={'model':'qwen-photo','tools':[{'function':{'name':'upscale_photo'}}]},timeout=5)
            assert response.status_code==400 and broker.requests==0
            response=session.post(url+'/v1/chat/completions',headers=headers,
                json={'model':'qwen-photo','tools':[]},timeout=5)
            assert response.status_code==400 and broker.requests==0
            response=session.post(url+'/tool',headers=headers,
                json={'name':'edit_photo','arguments':{},'id':uuid.uuid4().hex},timeout=5)
            assert response.status_code==400 and not w.events
            session.close()
        rejects(lambda: w.call('lightroom_develop', {'scope':'whole_image','settings':{'Exposure2012':.5}}))
        w.read_status=True
        rejects(lambda: w.call('lightroom_develop', {'scope':'user_mask','settings':{'Exposure2012':.5}}))
        with patch.object(lightroom, 'request', side_effect=TimeoutError('In-flight Adobe request')) as request:
            rejects(lambda: w.call('lightroom_develop', {'scope':'whole_image','settings':{'Exposure2012':.5}}), TimeoutError)
            rejects(lambda: w.call('lightroom_develop', {'scope':'whole_image','settings':{'Exposure2012':.5}}))
            assert request.call_count == 1
        rejects(lambda: lightroom.request('import_photo', source=folder/'one.png'))
        rejects(lambda: lightroom.request('status', 'bad\noperation\texport'))
        # Cancellation before catalog access must publish a cancelled report without importing.
        import os
        marker=ROOT/'.cache/control'/('batch-test-'+uuid.uuid4().hex+'.cancel')
        marker.parent.mkdir(parents=True,exist_ok=True); marker.touch()
        output=ROOT/'.cache'/('batch-cancel-test-'+uuid.uuid4().hex)
        try:
            with patch.dict(os.environ, {'PHOTOWORKFLOW_CANCEL_FILE':str(marker)}), patch('photo_workflow.native_batch.connect_lightroom') as connect:
                rejects(lambda:run(folder,'Brighten slightly',output=output),KeyboardInterrupt)
                connect.assert_not_called()
            report=json.loads(next(output.glob('*/batch.json')).read_text())
            assert report['status']=='cancelled' and report['files'][0]['status']=='pending'
        finally: marker.unlink(missing_ok=True)
    print('Passed native-only tool boundaries, folder scope, output overlap and no mutation retry.')


def verify():
    local_runtime(); boundaries()
    source = ROOT/'tests/fixtures/astronaut.png'; digest = sha256(source)
    folder = ROOT/'tests/fixtures'/('native-batch-'+uuid.uuid4().hex[:8]); folder.mkdir()
    for name in ('one.png', 'two.png'): shutil.copyfile(source, folder/name)
    import win32com.client
    app = win32com.client.Dispatch('Photoshop.Application')
    before = [(d.Name, d.Saved) for d in app.Documents]
    report_path = run(folder, 'Set exposure to exactly +0.4 stops and highlights to -15 on each whole photo. Leave all other settings unchanged.')
    report = json.loads(report_path.read_text())
    assert report['status']=='passed' and len(report['files'])==2
    from tests.verify_expanded import check_psd
    results=[]
    for item in report['files']:
        assert item['status']=='passed' and sha256(item['source'])==digest
        job=Path(item['output'])
        record=json.loads((job/'model-evidence.json').read_text())
        assert record['model_requests']>=2 and not record['failures']
        assert all(set(names)==NativeWorkspace.tools for names in record['tool_sets'])
        edited=next(e['result'] for e in record['events'] if e['tool']=='lightroom_develop')
        assert edited['settings']['Exposure2012']==.4 and edited['settings']['Highlights2012']==-15
        assert edited['virtual_copy'] and edited['original_settings_preserved']
        assert (job/'review.psd').exists()
        checked=check_psd(job); assert checked['layers']==2 and checked['bit_depth']==16
        results.append(checked)
    assert [(d.Name,d.Saved) for d in app.Documents]==before
    assert sha256(source)==digest
    json_write(ROOT/'outputs/latest-native-batch-verification.json', {'status':'passed', 'report':str(report_path),
        'files':2, 'psds':results, 'originals_preserved':True, 'preexisting_photoshop_documents_preserved':True,
        'generative_tools_exposed':False, 'boundaries':'passed', 'quality':'local human review required'})
    print('Passed real two-photo folder -> local OMP -> native Lightroom -> TIFF and two-layer PSD.')


if __name__=='__main__':
    json_write(ROOT/'outputs/latest-native-batch-verification.json', {'status':'running'})
    try: verify()
    except BaseException as error:
        json_write(ROOT/'outputs/latest-native-batch-verification.json', {'status':'failed','error':repr(error)})
        raise
