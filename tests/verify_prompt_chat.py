"""Chat path -> native batch acceptance; public fixture only, no cloud pixels."""
import json
from pathlib import Path
import shutil
import tempfile
import uuid
from unittest.mock import patch

from photo_workflow.runtime import ROOT, json_write, local_runtime, sha256
from photo_workflow.prompt_chat import PromptWorkspace, launch


def rejects(action):
    try: action()
    except (ValueError, RuntimeError): return
    raise AssertionError('Expected rejection')


def boundaries():
    from photo_workflow.chat import configure, running
    from photo_workflow.pipeline import job_lock
    import requests
    local_runtime()
    w = PromptWorkspace()
    source = str(ROOT/'tests/fixtures/astronaut.png')
    rejects(lambda: w.authorized_path(source))
    w.accept_prompt(uuid.uuid4().hex, f'Edit "{source}". Set exposure to +0.2.')
    assert w.authorized_path(source) == Path(source)
    assert w.authorized_path(source.replace('\\','/').upper()) == Path(source)
    rejects(lambda: w.authorized_path(str(Path(source).parent)))
    rejects(lambda: w.call('upscale_photo', {}))
    w.attempted = True
    rejects(lambda: w.call('edit_photos', {'path': source}))
    w.accept_prompt(uuid.uuid4().hex, 'What did you change?')
    rejects(lambda: w.authorized_path(source))
    w.accept_prompt(uuid.uuid4().hex, 'Edit "tests/fixtures/astronaut.png" please')
    assert w.authorized_path('tests/fixtures/astronaut.png') == Path(source)
    # Both profile files and Adobe ownership stay isolated without bypassing locks.
    with tempfile.TemporaryDirectory(dir=ROOT/'.cache') as name, running(w) as broker:
        folder = Path(name)
        env1, _ = configure(broker, folder/'outer')
        env2, _ = configure(broker, folder/'inner')
        assert env1['PI_CODING_AGENT_DIR'] != env2['PI_CODING_AGENT_DIR']
        assert env1['USERPROFILE'] != env2['USERPROFILE']
        session = requests.Session(); session.trust_env = False
        url = f'http://127.0.0.1:{broker.server_port}'
        data = {'submission': uuid.uuid4().hex, 'prompt': f'Edit "{source}".'}
        assert session.post(url+'/prompt', json=data).status_code == 401
        headers = {'Authorization': 'Bearer '+broker.token}
        assert session.post(url+'/prompt', json=data, headers=headers).status_code == 200
        call_id = uuid.uuid4().hex
        assert session.post(url+'/cancel', json={'id': call_id}, headers=headers).status_code == 200
        with patch('photo_workflow.prompt_chat.subprocess.Popen') as child:
            response = session.post(url+'/tool', json={'id': call_id, 'name': 'edit_photos',
                'arguments': {'path': source}}, headers=headers)
            assert response.status_code == 400 and 'Cancelled' in response.json()['error']
            child.assert_not_called()
        marker = ROOT/'.cache/control'/('prompt-test-'+uuid.uuid4().hex)
        marker.touch()
        try:
            with patch('photo_workflow.prompt_chat.subprocess.Popen') as child:
                rejects(lambda: w.call('edit_photos', {'path': source}, marker))
                child.assert_not_called()
        finally: marker.unlink()
        with job_lock(ROOT/'.cache/chat.lock'):
            result = w.call('edit_photos', {'path': source})
        assert result['status'] == 'failed' and 'already being processed' in result['error']
        report = json.loads(Path(result['report']).read_text())
        assert all(item['status'] == 'pending' for item in report['files'])
        rejects(lambda: w.call('edit_photos', {'path': source}))
        w.accept_prompt(data['submission'], data['prompt'])
        assert w.attempted  # Re-entering the same submission cannot permit a retry.
        # Cancel after tool authorization but before the child can import anything.
        w.accept_prompt(uuid.uuid4().hex, data['prompt'])
        import subprocess
        spawn = subprocess.Popen
        def cancelled_spawn(*args, **kwargs):
            marker.touch()
            return spawn(*args, **kwargs)
        try:
            with patch('photo_workflow.prompt_chat.subprocess.Popen', side_effect=cancelled_spawn):
                result = w.call('edit_photos', {'path': source}, marker)
            assert result['status'] == 'cancelled' and result['completed'] == 0
            report = json.loads(Path(result['report']).read_text())
            assert all(item['status'] == 'pending' for item in report['files'])
        finally: marker.unlink(missing_ok=True)
        session.close()
    print('Prompt authorization, cancellation, profile isolation and Adobe lock checks passed.', flush=True)


def verify():
    boundaries()
    source = ROOT/'tests/fixtures/astronaut.png'; digest = sha256(source)
    folder = ROOT/'tests/fixtures'/('prompt chat '+uuid.uuid4().hex[:8]); folder.mkdir()
    shutil.copyfile(source, folder/'one.png')
    prompt = f'Edit "{folder}". Set exposure to exactly +0.25 stops and highlights to -12 for each whole photo. Leave other settings unchanged.'
    evidence = ROOT/'outputs'/('prompt-chat-'+uuid.uuid4().hex+'.json')
    import win32com.client
    app = win32com.client.Dispatch('Photoshop.Application')
    before = [(d.Name, d.Saved) for d in app.Documents]
    with evidence.with_suffix('.log').open('w', encoding='utf-8') as log:
        code = launch(prompt, evidence, log)
    record = json.loads(evidence.read_text())
    assert code == 0 and not record['failures'], record
    assert all(set(names) == PromptWorkspace.tools for names in record['tool_sets'])
    calls = [e for e in record['events'] if e['tool'] == 'edit_photos']
    assert len(calls) == 1, record
    result = calls[0]['result']
    assert result['status'] == 'passed', result
    report = json.loads(Path(result['report']).read_text())
    assert report['prompt'] == prompt and len(report['files']) == 1
    job = Path(report['files'][0]['output'])
    inner = json.loads((job/'model-evidence.json').read_text())
    assert inner['model_requests'] >= 2 and not inner['failures']
    edit = next(e['result'] for e in inner['events'] if e['tool'] == 'lightroom_develop')
    assert edit['settings']['Exposure2012'] == .25 and edit['settings']['Highlights2012'] == -12
    assert edit['original_settings_preserved'] and edit['virtual_copy']
    from tests.verify_expanded import check_psd
    psd = check_psd(job)
    assert psd['bit_depth'] == 16 and psd['layers'] == 2
    assert sha256(source) == sha256(folder/'one.png') == digest
    assert [(d.Name, d.Saved) for d in app.Documents] == before
    json_write(ROOT/'outputs/latest-prompt-chat-verification.json', {
        'status': 'passed', 'outer_evidence': str(evidence), 'batch_report': result['report'],
        'psd': psd, 'originals_preserved': True, 'preexisting_documents_preserved': True,
        'full_original_prompt_forwarded': True, 'chooser_or_manual_selection_required': False,
        'boundaries': 'passed', 'generative_tools_exposed': False})
    print('Passed real prompt in OMP -> folder import -> native edits -> TIFF + PSD.', flush=True)


if __name__ == '__main__': verify()
