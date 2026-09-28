"""Real unified harness acceptance; public fixture, local processing only."""
import json
from pathlib import Path
import tempfile
import uuid
from unittest.mock import patch

from photo_workflow.runtime import ROOT, json_write, local_runtime, sha256
from photo_workflow.prompt_chat import PromptWorkspace, SYSTEM
from photo_workflow.unified_batch import UnifiedWorkspace
from photo_workflow.chat import run_session
from photo_workflow.pipeline import job_lock


def rejects(action):
    try: action()
    except (ValueError, RuntimeError): return
    raise AssertionError('Expected rejection')


def boundaries():
    from tests.verify_prompt_chat import boundaries as base_boundaries
    base_boundaries()
    with tempfile.TemporaryDirectory(dir=ROOT/'.cache') as name:
        work = Path(name)
        source = ROOT/'tests/fixtures/astronaut.png'
        w = UnifiedWorkspace(source, source, work/'catalog.lrcat', 'selection')
        from photo_workflow import lightroom
        with patch.object(lightroom, 'request', return_value={'source':str(source), 'selection':'current', 'settings':{'Exposure2012':0}}):
            status = w.call('photo_status', {})
        assert w.read_status and status['native']['selection']=='current'
        w.raster_attempted.add('upscale_photo')
        rejects(lambda: w.call('lightroom_develop', {'scope':'whole_image','settings':{'Exposure2012':.1}}))
        rejects(lambda: w.call('photoshop_local', {'operations':[]}))
        rejects(lambda: w.call('edit_photo', {'scope':'whole_image','denoise':.2}))
        rejects(lambda: w.call('upscale_photo', {'input':'latest_result','scale':2,'detail_strength':.2}))
        outer = PromptWorkspace()
        outer.accept_prompt(uuid.uuid4().hex, f'Review "{source}"')
        outer.call('select_context', {'kind':'photo','paths':[str(source)]})
        assert outer.selected_input == source
        with patch('photo_workflow.vision.inspect', return_value={'observations':'local fixture'}) as inspect:
            result = outer.call('inspect_photo', {'path':str(source),'focus':'review','view':'source','include_references':False})
            assert result['observations']=='local fixture' and inspect.call_args.args[0][0][1]==source
        rejects(lambda: outer.call('read_notes', {'paths':[str(ROOT/'Photo Vault/Start here.md')]}))
        rejects(lambda: outer.call('select_context', {'kind':'references','paths':[str(source.parent)]}))
        outer.result = {'status':'failed'}
        outer.accept_prompt(uuid.uuid4().hex, 'Now upscale it')
        rejects(lambda: outer.call('edit_photos', {'path':''}))
    print('Unified order, retry, context and failed-followup boundaries passed.', flush=True)


def verify_context_and_failure():
    """Real harness routing for notes and terminal failure; no Adobe mutation."""
    uid = uuid.uuid4().hex[:8]
    note = ROOT/'Photo Vault/Templates'/('Unified test '+uid+'.md')
    note.write_text('Public integration fixture. Preserve purple lighting. Test code: violet-42.\n', encoding='utf-8')
    digest = sha256(note)
    evidence = ROOT/'outputs'/('unified-context-'+uid+'.json')
    w = PromptWorkspace()
    prompt = f'Read the Photo Vault note "{note}" and save a NEW note titled "Unified test summary" containing its test code and lighting instruction. Do not edit photos.'
    with job_lock(ROOT/'.cache/prompt-chat.lock'), evidence.with_suffix('.log').open('w', encoding='utf-8') as log:
        code = run_session(w, prompt, evidence, SYSTEM, log, profile=ROOT/'apps/OhMyPiPromptData')
    record = json.loads(evidence.read_text())
    assert code==0 and not record['failures'], record
    assert not any(e['tool']=='edit_photos' for e in w.events)
    saved = [e['result']['saved'] for e in w.events if e['tool']=='save_note']
    assert len(saved)==1 and sha256(note)==digest
    content = Path(saved[0]).read_text(encoding='utf-8').lower()
    assert 'violet-42' in content and 'purple' in content
    class FailedWorkspace(PromptWorkspace):
        def _call(self, name, args, cancel_file=None):
            if name != 'edit_photos': return super()._call(name,args,cancel_file)
            self.authorized_path(args['path'])
            self.attempted=True
            self.result={'status':'failed','error':'Test fixture: Adobe is unavailable. Stop and explain.'}
            return self.result
    failed = FailedWorkspace()
    failure_evidence = ROOT/'outputs'/('unified-failure-'+uid+'.json')
    with job_lock(ROOT/'.cache/prompt-chat.lock'), failure_evidence.with_suffix('.log').open('w', encoding='utf-8') as log:
        code=run_session(failed, 'Upscale "tests/fixtures/astronaut.png" 2x.', failure_evidence, SYSTEM, log,
                         profile=ROOT/'apps/OhMyPiPromptData')
    record=json.loads(failure_evidence.read_text())
    assert code==0 and not record['failures'],record
    names = [e['tool'] for e in failed.events]
    assert names[-1]=='edit_photos' and names.count('edit_photos')==1 and record['model_requests']<=5
    json_write(ROOT/'outputs/latest-unified-context-verification.json', {'status':'passed',
        'notes_evidence':str(evidence),'failure_evidence':str(failure_evidence),'saved_note':saved[0],
        'source_note_preserved':True,'failure_test':'simulated Adobe error, actual OMP inference; one edit attempt and no subsequent tools'})
    print('Passed same-chat note selection/read/save and terminal-failure model reply.',flush=True)


def verify(existing_evidence=None):
    import cv2
    from photo_workflow.imaging import decode_working, save_rgb
    import win32com.client
    import tifffile
    from tests.verify_expanded import check_psd
    local_runtime(); boundaries()
    app = win32com.client.Dispatch('Photoshop.Application')
    before = [(d.Name, d.Saved) for d in app.Documents]
    if existing_evidence:
        evidence = Path(existing_evidence)
        outer = json.loads(evidence.read_text())
        assert outer['exit_code']==0 and not outer['failures']
        results=[e['result'] for e in outer['events'] if e['tool']=='edit_photos']
        assert len(results)==1 and results[0]['status']=='passed'
        report=json.loads(Path(results[0]['report']).read_text())
        source=Path(report['files'][0]['source'])
        digest=report['files'][0]['source_sha256']
        uid=uuid.uuid4().hex[:8]
        w=PromptWorkspace()
        w.result=results[0]
        w.selected_input=Path(report['input'])
        w.completed_sources=[Path(x['tiff']) for x in report['files']]
        w.source=Path(report['files'][0]['output'])/'original.tif'
        w.job=Path(report['files'][0]['final_output'])
    else:
        uid = uuid.uuid4().hex[:8]
        source = ROOT/'tests/fixtures'/('unified-'+uid+'.tif')
        pixels, _ = decode_working((ROOT/'tests/fixtures/astronaut.png').read_bytes())
        save_rgb(source, cv2.resize(pixels, (128,128), interpolation=cv2.INTER_AREA))
        digest = sha256(source)
        app = win32com.client.Dispatch('Photoshop.Application')
        before = [(d.Name, d.Saved) for d in app.Documents]
        w = PromptWorkspace()
        evidence = ROOT/'outputs'/('unified-chat-'+uid+'.json')
        prompt = (f'Edit "{source}". Set native Lightroom exposure to exactly +0.2 stops. '
                  'Then use local DRUNet denoising at strength 0.25 with noise_sigma 15. '
                  'Then upscale 2x with the local Real-ESRGAN model, detail strength 0.2. '
                  'Keep face reconstruction off. Save the results automatically.')
        with job_lock(ROOT/'.cache/prompt-chat.lock'), evidence.with_suffix('.log').open('w',encoding='utf-8') as log:
            code = run_session(w, prompt, evidence, SYSTEM, log, profile=ROOT/'apps/OhMyPiPromptData')
        outer = json.loads(evidence.read_text())
        assert code == 0 and not outer['failures'], outer
        assert len([e for e in w.events if e['tool']=='edit_photos']) == 1
        assert w.result['status'] == 'passed', w.result
        report = json.loads(Path(w.result['report']).read_text())
    item = report['files'][0]
    native = Path(item['output'])
    record = json.loads((native/'model-evidence.json').read_text())
    assert not record['failures']
    names = [e['tool'] for e in record['events']]
    assert names.index('lightroom_develop') < names.index('edit_photo') < names.index('upscale_photo')
    edit = next(e['result'] for e in record['events'] if e['tool']=='lightroom_develop')
    assert edit['settings']['Exposure2012']==.2 and edit['original_settings_preserved']
    stages = [Path(p) for p in item['stages']]
    assert len(stages)==3
    denoise = json.loads((stages[1]/'job.json').read_text())
    upscale = json.loads((stages[2]/'job.json').read_text())
    assert upscale['runtime']['upscale_invoked'] and not upscale['runtime']['restoration_invoked']
    assert denoise['runtime']['denoiser'] == 'DRUNet color'
    assert upscale['settings']['upscale_strength']==.2
    assert upscale['source_sha256'] == sha256(stages[1]/'composite.tif')
    assert denoise['source_sha256'] == sha256(native/'lightroom.tif')
    assert tifffile.imread(item['tiff']).shape == (256,256,3)
    psds = [check_psd(p) for p in stages]
    assert sha256(source)==digest
    if not existing_evidence: assert [(d.Name,d.Saved) for d in app.Documents]==before
    # Fresh model prompt, same trusted chat state; no repeated source path.
    followup = ROOT/'outputs'/('unified-followup-'+uid+'.json')
    with job_lock(ROOT/'.cache/prompt-chat.lock'), followup.with_suffix('.log').open('w',encoding='utf-8') as log:
        code = run_session(w, 'Now brighten the completed result by exactly +0.1 stops in Lightroom. Do not upscale again.',
            followup, SYSTEM, log, profile=ROOT/'apps/OhMyPiPromptData')
    assert code==0 and w.result['status']=='passed', w.result
    follow = json.loads(Path(w.result['report']).read_text())
    assert Path(follow['files'][0]['source']) == Path(item['tiff'])
    final = Path(follow['files'][0]['output'])
    final_record = json.loads((final/'model-evidence.json').read_text())
    assert not any(e['tool']=='upscale_photo' for e in final_record['events'])
    assert tifffile.imread(follow['files'][0]['tiff']).shape == (256,256,3)
    assert sha256(source)==digest and [(d.Name,d.Saved) for d in app.Documents]==before
    json_write(ROOT/'outputs/latest-unified-chat-verification.json', {'status':'passed',
        'evidence':str(evidence), 'batch_report':str(Path(item['output']).parent/'batch.json'),
        'followup_evidence':str(followup), 'followup_report':w.result['report'],
        'psds':psds, 'source_preserved':True, 'prior_stages_preserved':True,
        'preexisting_photoshop_documents_preserved':None if existing_evidence else True,
        'followup_preexisting_documents_preserved':True,
        'photoshop_warning':'Crashed/restarted during initial combined run; saved PSDs verified; original document continuity could not be verified.' if existing_evidence else None,
        'local_real_esrgan':True,
        'local_drunet':True, 'face_restoration':False, 'followup_without_path':'passed'})
    print('Passed unified local OMP -> Lightroom -> DRUNet -> Real-ESRGAN -> PSD, and follow-up on latest result.', flush=True)


if __name__=='__main__': verify()
