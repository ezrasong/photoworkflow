"""Actual OMP -> native Lightroom -> TIFF -> DRUNet -> layered Photoshop PSD.

Only fixture setup uses the queue directly. Every accepted editing/export step
must come from successful tools called by the real local conversational model.
"""
import json
from pathlib import Path
import subprocess
import sys
import uuid

from photo_workflow.chat import TOOLS
from photo_workflow.edits import DEFAULTS
from photo_workflow.lightroom import request
from photo_workflow.runtime import ROOT, json_write, local_runtime, sha256
from tests.verify_lightroom import check_develop, check_export


def verify():
    local_runtime()
    source = ROOT/'tests/fixtures/astronaut.png'
    digest = sha256(source)
    # The plug-in rejects this operation outside the workspace test catalog.
    initial = request('import_fixture')
    assert not initial['virtual_copy']
    evidence = ROOT/'outputs'/('lightroom-chat-' + uuid.uuid4().hex + '.json')
    prompt = (
        'Read the current Lightroom selection with lightroom_status. '
        'Use lightroom_develop once to create a new virtual copy with absolute '
        'Exposure2012=0.5 and Highlights2012=-20, scope whole_image. '
        'Then use lightroom_export to select the rendered 16-bit TIFF. '
        'On that exported raster use edit_photo with scope whole_image, '
        'exposure=0.2 and denoise=0.25; leave other raster controls neutral. '
        'Finally call export_psd for a layered 16-bit PSD. '
        'Do not search online, read or write notes, or retry a failed edit. '
        'Report only what the tools actually completed.'
    )
    with evidence.with_suffix('.log').open('w', encoding='utf-8') as log:
        run = subprocess.run(
            [sys.executable, '-m', 'photo_workflow.chat', '--prompt', prompt,
             '--evidence', str(evidence)], cwd=ROOT, stdout=log, stderr=log,
            timeout=900, creationflags=subprocess.CREATE_NO_WINDOW)
    assert run.returncode == 0, str(evidence.with_suffix('.log'))
    record = json.loads(evidence.read_text(encoding='utf-8'))
    assert record['exit_code'] == 0 and record['model_requests'] >= 2
    assert not record['failures'], record['failures']
    assert record['tool_sets'] and all(set(x) == TOOLS for x in record['tool_sets'])
    events = record['events']
    names = [x['tool'] for x in events]
    required = ['lightroom_status', 'lightroom_develop', 'lightroom_export', 'edit_photo', 'export_psd']
    assert all(names.count(name) == 1 for name in required), names
    assert [name for name in names if name in required] == required, names
    assert not set(names) - set(required) - {'photo_status'}, names
    assert all(event['ok'] is True for event in events)
    results = {event['tool']: event['result'] for event in events}
    status = results['lightroom_status']
    assert status['settings'] == initial['settings'] and not status['virtual_copy']
    edited = results['lightroom_develop']
    check_develop(status, edited)
    rendered = results['lightroom_export']
    raster = Path(rendered['selected_raster']).resolve()
    shape = check_export(raster)
    assert rendered['bit_depth'] == 16
    edit = results['edit_photo']
    assert not edit['reused_existing_job']
    assert edit['recipe'] == dict(DEFAULTS, exposure=.2, denoise=.25)
    folder = Path(edit['job']).resolve()
    assert folder.is_relative_to(ROOT/'outputs/chat-edits')
    job = json.loads((folder/'job.json').read_text(encoding='utf-8'))
    assert job['source_sha256'] == sha256(raster)
    assert job['source_name'] == raster.name and job['output_size'] == [512, 512]
    assert job['runtime']['denoiser'] == 'DRUNet color'
    assert job['runtime']['restoration_invoked'] is False
    assert job['runtime']['upscale_invoked'] is False
    # Do not let the PSD checker create the artifact on behalf of the model.
    psd_path = Path(results['export_psd']['psd']).resolve()
    assert psd_path == folder/'review.psd' and psd_path.is_file()
    from tests.verify_expanded import check_psd
    psd = check_psd(folder)
    assert psd['layers'] >= 3
    original = request('import_fixture')
    assert original['settings'] == initial['settings'] and not original['virtual_copy']
    assert sha256(source) == digest
    json_write(ROOT/'outputs/latest-lightroom-chat-verification.json', {
        'status': 'passed', 'harness': record['harness'], 'model': record['model'],
        'evidence': str(evidence), 'tools': names, 'native_settings': edited,
        'export': str(raster), 'shape': shape, 'psd': psd,
        'source_preserved': True, 'exported_tiff_preserved': True,
        'original_settings_readback': original['settings'],
        'visual_review': 'local human review required',
    })
    print('Passed real local OMP -> Lightroom -> TIFF -> DRUNet -> layered 16-bit PSD.')


if __name__ == '__main__':
    report = ROOT/'outputs/latest-lightroom-chat-verification.json'
    json_write(report, {'status': 'running'})
    try:
        verify()
    except BaseException as error:
        json_write(report, {'status': 'failed', 'error': repr(error),
                           'conversational_acceptance': 'not passed; inspect any in-flight copy before retrying'})
        raise
