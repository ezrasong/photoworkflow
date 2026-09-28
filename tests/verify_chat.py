"""Real OMP -> local Qwen -> vault, DRUNet and Photoshop; boundary tests."""
import json
from pathlib import Path
import subprocess
import sys
import uuid

import requests
import tifffile

from photo_workflow.chat import Workspace, TOOLS, running
from photo_workflow.runtime import ROOT, json_write, local_runtime, sha256
from photo_workflow.vault import VAULT


def rejected(action):
    try: action()
    except (ValueError, RuntimeError): return
    raise AssertionError('Invalid action accepted')


def verify():
    local_runtime()
    from PIL import Image, PngImagePlugin
    source = ROOT / 'tests/fixtures' / ('chat-test-' + uuid.uuid4().hex + '.png')
    metadata = PngImagePlugin.PngInfo(); metadata.add_text('verification', uuid.uuid4().hex)
    with Image.open(ROOT/'tests/fixtures/astronaut.png') as image: image.save(source, pnginfo=metadata)
    original = sha256(source)
    w = Workspace(source)
    rejected(lambda: w.call('shell', {'cmd': 'anything'}))
    rejected(lambda: w.call('edit_photo', {'scope': 'user_mask', 'exposure': .5}))
    rejected(lambda: w.call('edit_photo', {'scope': 'whole_image', 'path': 'anything'}))
    rejected(lambda: w.call('lightroom_develop', {'scope':'whole_image','settings': {'Exposure2012': float('nan')}}))
    rejected(lambda: w.call('lightroom_develop', {'scope':'user_mask','settings': {'Exposure2012': .5}}))
    rejected(lambda: w.select_notes([ROOT / 'README.md']))
    rejected(lambda: w.call('save_note', {'title': 'x', 'text': 'x', 'path': '../README.md'}))
    with running(w) as broker:
        url = f'http://127.0.0.1:{broker.server_port}'
        s = requests.Session(); s.trust_env = False
        assert s.post(url+'/tool',json={'name':'read_notes','arguments':{}}).status_code == 401
        headers = {'Authorization': 'Bearer '+broker.token}
        assert s.post(url+'/v1/chat/completions',headers=headers,json={'model':'cloud'}).status_code == 400
        assert s.post(url+'/v1/chat/completions',headers=headers,json={'model':'qwen-photo','tools':[{'function':{'name':'bash'}}]}).status_code == 400
        assert s.post(url+'/tool',headers=dict(headers,Origin='https://example.com'),json={}).status_code == 403
        assert s.request('CONNECT',url).status_code == 403
        s.close()
    # Authored synthetic context only. Never select existing private notes for tests.
    fixture = VAULT / 'Templates/Assistant integration test.md'
    if not fixture.exists():
        fixture.write_text('# Local assistant test\n\nThis is synthetic test context. The test phrase is violet lantern.\nPreserve intentional purple stage lighting.\n',encoding='utf-8')
    before = sha256(fixture)
    report = ROOT/'outputs'/('chat-integration-'+uuid.uuid4().hex[:8]+'.json')
    log = report.with_suffix('.log')
    prompt = ('Read my selected Obsidian note and use its test phrase in a new session note. '
              'On the whole selected raster, set exposure to 0.35 stops and DRUNet denoise strength to 0.25. '
              'Leave all color controls neutral. Then export the result to a layered PSD. '
              'Finally save a new Obsidian note recording what you actually completed and the test phrase. '
              'Do not touch Lightroom for this test.')
    with log.open('w',encoding='utf-8') as stream:
        run = subprocess.run([sys.executable,'-m','photo_workflow.chat','--source',str(source),
               '--note',str(fixture),'--prompt',prompt,'--evidence',str(report)],cwd=ROOT,
               stdout=stream,stderr=stream,timeout=600,creationflags=subprocess.CREATE_NO_WINDOW)
    assert run.returncode == 0, str(log)
    result = json.loads(report.read_text())
    names = [event['tool'] for event in result['events']]
    assert {'read_notes','edit_photo','export_psd','save_note'} <= set(names),names
    assert result['model_requests'] >= 2 and not result['failures'],result['failures']
    assert all(set(x) == TOOLS for x in result['tool_sets'])
    edit = next(x['result'] for x in result['events'] if x['tool']=='edit_photo')
    assert not edit['reused_existing_job']
    folder = Path(edit['job']); job = json.loads((folder/'job.json').read_text())
    assert job['runtime']['denoiser']=='DRUNet color'
    assert tifffile.imread(folder/'composite.tif').dtype.name == 'uint16'
    from tests.verify_expanded import check_psd
    psd = check_psd(folder)
    saved = Path(next(x['result']['saved'] for x in result['events'] if x['tool']=='save_note'))
    assert 'violet lantern' in saved.read_text(encoding='utf-8').lower()
    assert sha256(source)==original and sha256(fixture)==before
    json_write(ROOT/'outputs/latest-chat-verification.json',{'status':'passed', 'harness':'Oh My Pi v18.3.2', 'model':result['model'],
        'evidence':str(report),'tools':names,'psd':psd,'source_preserved':True,'selected_note_preserved':True,
        'boundary_tests':'passed','visual_review':'local human review required','lightroom':'separate unverified integration'})
    print('Passed local OMP, vault context/new note, DRUNet, PSD and boundary checks.')


if __name__ == '__main__':
    json_write(ROOT/'outputs/latest-chat-verification.json',{'status':'running'})
    try: verify()
    except BaseException as error:
        json_write(ROOT/'outputs/latest-chat-verification.json',{'status':'failed','error':repr(error)})
        raise
