"""Conventional Adobe extensions: boundaries, real native pixels and real OMP."""
import json
from pathlib import Path
import shutil
import tempfile
import uuid
from unittest.mock import patch

import numpy as np
import tifffile

from photo_workflow import lightroom
from photo_workflow.native_batch import NativeWorkspace, run, save_job
from photo_workflow.photoshop_local import apply, validate_operations
from photo_workflow.runtime import ROOT, json_write, local_runtime, sha256
from tests.verify_expanded import check_psd


def boundaries():
    def reject(action):
        try: action()
        except ValueError: return
        raise AssertionError('Invalid edit accepted')
    assert lightroom.validate_settings({'Crop':[.1,.2,.8,.9]}) == {
        'CropLeft':.1,'CropTop':.2,'CropRight':.8,'CropBottom':.9}
    reject(lambda: lightroom.validate_settings({'Crop':[.1,.2,.8]}))
    reject(lambda: lightroom.validate_settings({'Crop':[.1,.2,.8,.9],'CropTop':.2}))
    for settings in ({'CropTop': .1}, {'CropTop': .8, 'CropBottom': .2, 'CropLeft': 0, 'CropRight': 1},
                     {'ToneCurvePV2012': [0, 0, 128, 200, 255, 100]},
                     {'ToneCurvePV2012': [0, 0, 0, 30, 255, 255]}, {'LensProfileEnable': .5},
                     {'CropAngle': float('nan')}, {'HasCrop': True}, {'MaskGroupBasedCorrections': []}):
        reject(lambda: lightroom.validate_settings(settings))
    clone = {'kind': 'clone', 'region': [.6, .6, .7, .7], 'feather': 0, 'donor_offset': [-.4, -.4]}
    validate_operations([clone])
    for op in (dict(clone, donor_offset=[1, 1]), dict(clone, donor_offset=[0, 0]),
               dict(clone, kind='generative_fill'), dict(clone, feather=float('inf')),
               dict(clone, path='C:/private'), dict(clone, region=[.7, .6, .6, .7])):
        reject(lambda: validate_operations([op]))
    with tempfile.TemporaryDirectory(dir=ROOT/'.cache') as directory:
        p = Path(directory); shutil.copyfile(ROOT/'tests/fixtures/astronaut.png', p/'source.png')
        w = NativeWorkspace(p/'source.png', p/'source.png', p/'test.lrcat', str(uuid.uuid4()))
        assert w.tools - {'photoshop_local'} == {'inspect_photo', 'photo_status', 'lightroom_status', 'lightroom_develop'}
        reject(lambda: w.call('photoshop_local', {'operations': [clone]}))
        w.read_status = True
        with patch('photo_workflow.vision.inspect', return_value={'observations':'Review the donor locally'}) as inspect, \
             patch('photo_workflow.native_batch.subprocess.run') as mutation:
            preview = w.call('photoshop_local', {'operations':[clone]})
            assert preview['operations_applied'] is False and w.inspected_current and not w.local_attempted
            inspect.assert_called_once(); mutation.assert_not_called()
        w.read_status = w.inspected_current = True
        with patch.object(w, 'current_render', return_value=p/'source.png'), patch('photo_workflow.native_batch.subprocess.run', side_effect=TimeoutError):
            try: w.call('photoshop_local', {'operations': [clone]})
            except TimeoutError: pass
            else: raise AssertionError('Expected simulated uncertain Photoshop mutation')
        reject(lambda: w.call('photoshop_local', {'operations': [clone]}))
        reject(lambda: w.call('lightroom_develop', {'scope':'whole_image', 'settings':{'Exposure2012':.2}}))
        # The unattended runner must stop the harness after a tool failure rather than
        # allowing further model turns to retry a mutation that may have completed.
        from contextlib import nullcontext
        from types import SimpleNamespace
        from unittest.mock import Mock
        from photo_workflow import chat
        broker = SimpleNamespace(failures=['native operation failed'], active_calls={}, requests=0,
                                 tool_sets=[], tool_schemas=None)
        process = Mock(); process.poll.return_value = None; process.returncode = 1
        with patch.object(chat, 'running', return_value=nullcontext(broker)), \
             patch.object(chat, 'configure', return_value=({},p)), \
             patch.object(chat, 'sha256', return_value=chat.OMP_HASH), \
             patch.object(chat.subprocess, 'Popen', return_value=process):
            try: chat.run_session(w, 'test failure')
            except RuntimeError as error: assert 'Folder tool failed' in str(error)
            else: raise AssertionError('Unattended runner continued after failure')
        process.terminate.assert_called_once(); process.wait.assert_called_once()
    print('PASS extended validation and mutation ordering', flush=True)


def local_native():
    import win32com.client
    app = win32com.client.Dispatch('Photoshop.Application')
    docs = [(d.Name, d.Saved) for d in app.Documents]
    p = ROOT/'outputs'/('extended-local-'+uuid.uuid4().hex[:8]); p.mkdir()
    source = ROOT/'outputs/native-batches/20260926-105806-e308ca0a/0001/original.tif'
    digest = sha256(source)
    shutil.copyfile(source, p/'original.tif'); shutil.copyfile(source, p/'lightroom.tif')
    ops = [{'kind':'curve','region':[.1,.1,.4,.4],'feather':.01,'curve':[0,0,128,170,255,255]},
           {'kind':'clone','region':[.6,.6,.7,.7],'feather':0,'donor_offset':[-.4,-.4]}]
    result = apply(p/'lightroom.tif', p/'local', ops)
    a, b = tifffile.imread(source), tifffile.imread(p/'local/composite.tif')
    m1, m2 = (tifffile.imread(p/'local'/f'local-{i:02}-mask.tif') for i in (1, 2))
    outside = (m1 == 0) & (m2 == 0)
    assert outside.sum() > a.shape[0]*a.shape[1]*.7
    outside_error = int(np.abs(a.astype(int)-b.astype(int))[outside].max())
    assert outside_error <= 1
    curve, clone = (tifffile.imread(p/'local'/f'local-{i:02}.tif') for i in (1, 2))
    assert np.mean(curve[70:180,70:180].astype(float)-a[70:180,70:180]) > 1000
    assert np.array_equal(clone[320:340,320:340],curve[115:135,115:135])
    shutil.copyfile(p/'local/composite.tif', p/'composite.tif')
    save_job(p,source,digest,a,b,{}, {},'Prescribed local curve and clone acceptance',True,
             native_file='lightroom.tif',local_result=result)
    psd = check_psd(p)
    from psd_tools import PSDImage
    merged = np.rint(PSDImage.open(p/'review.psd').numpy('color')*65535).astype(int)
    merged_error = int(np.abs(merged-b.astype(int)).max())
    assert merged_error <= 3, merged_error
    assert sha256(source) == digest and [(d.Name,d.Saved) for d in app.Documents] == docs
    report = {'status':'passed','folder':str(p),'psd':psd,'outside_mask_max_error':outside_error,
              'psd_composite_max_error':merged_error,'donor_samples_exact':True,'source_and_documents_preserved':True}
    json_write(ROOT/'outputs/latest-extended-local-verification.json',report)
    print('PASS native Photoshop local corrections and layered PSD',flush=True)
    return report


def conversational():
    source = ROOT/'tests/fixtures/astronaut.png'; digest = sha256(source)
    catalog = lightroom.request('catalog')
    assert catalog['bridge_version'] >= 3 and '/tests/lightroom/' in catalog['catalog'].replace('\\','/').lower()
    initial = lightroom.request('import_fixture')
    prompt = ('For this technical editing test, crop to the central 75 percent on both axes '
              '(absolute edges left/top .125 and right/bottom .875), set the RGB point curve '
              'to [0,0,64,55,128,140,255,255], parametric shadows to +5, manual lens distortion '
              'to +5 and chromatic aberration correction on (AutoLateralCA=1). Leave other settings alone. '
              'Then inspect the cropped render locally. Apply a local Photoshop curve '
              '[0,0,128,160,255,255] in rectangle [.1,.1,.3,.3] with feather .01. '
              'Also clone rectangle [.6,.6,.7,.7] using donor offset [-.4,-.4] with zero feather. '
              'These explicitly prescribed coordinates are for verifying the editing tools. '
              'Use one Photoshop operation list and do not use generative editing.')
    report_path = run(source,prompt)
    batch = json.loads(report_path.read_text()); assert batch['status'] == 'passed'
    p = Path(batch['files'][0]['output'])
    evidence = json.loads((p/'model-evidence.json').read_text())
    assert not evidence['failures'] and all(set(names) == NativeWorkspace.tools for names in evidence['tool_sets'])
    names = [e['tool'] for e in evidence['events']]
    assert names.index('lightroom_develop') < names.index('photoshop_local')
    local_events = [e for e in evidence['events'] if e['tool']=='photoshop_local']
    assert ('inspect_photo' in names[names.index('lightroom_develop')+1:names.index('photoshop_local')]
            or local_events[0]['result'].get('operations_applied') is False)
    native = next(e['result'] for e in evidence['events'] if e['tool']=='lightroom_develop')
    for k,v in {'CropLeft':.125,'CropTop':.125,'CropRight':.875,'CropBottom':.875,
                'ParametricShadows':5,'LensManualDistortionAmount':5,'AutoLateralCA':1,
                'ToneCurvePV2012':[0,0,64,55,128,140,255,255]}.items(): assert native['settings'][k]==v,(k,native['settings'])
    assert tifffile.imread(p/'composite.tif').shape == (384,384,3)
    assert tifffile.imread(p/'geometry-baseline.tif').shape == (384,384,3)
    assert tifffile.imread(p/'original.tif').shape == (512,512,3)
    assert lightroom.request('import_fixture')['settings'] == initial['settings'] and sha256(source)==digest
    psd = check_psd(p);assert psd['layers']==4
    result = {'status':'passed','report':str(report_path),'tool_calls':names,'psd':psd,
              'source_and_native_original_preserved':True,'generative_tools':False,
              'limitations':'Public PNG and prescribed regions only; subjective quality, rotated RAW and lens profile matching not established.'}
    json_write(ROOT/'outputs/latest-extended-native-chat-verification.json',result)
    print('PASS actual OMP -> crop/curves/lens -> local inspection -> Photoshop region/clone -> PSD',flush=True)
    return result


if __name__ == '__main__':
    import sys
    local_runtime();boundaries()
    if '--local' in sys.argv: local_native()
    else: conversational()
