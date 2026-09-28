"""Camera routing boundaries and real public A7CR acceptance; pixels stay local."""
import json
from contextlib import nullcontext
from pathlib import Path
import tempfile
import time
import uuid
from unittest.mock import patch

import numpy as np
import tifffile

from photo_workflow import lightroom
from photo_workflow.prompt_chat import PromptWorkspace
from photo_workflow.runtime import ROOT, json_write, local_runtime, sha256


DETAIL = {'LuminanceNoiseReductionDetail': 60, 'LuminanceNoiseReductionContrast': 10,
          'ColorNoiseReductionDetail': 60, 'ColorNoiseReductionSmoothness': 55}


def boundaries():
    from photo_workflow.native_batch import inputs
    from photo_workflow.chat import Workspace, pick
    from photo_workflow.review_panel import change_summary
    from photo_workflow.photoshop import PhotoshopSession
    import pywintypes
    with patch('win32com.client.GetActiveObject', side_effect=pywintypes.com_error(-2147221021, 'Unavailable', None, None)), \
         patch('win32com.client.Dispatch') as dispatch:
        session = PhotoshopSession(defer_start=True)
        dispatch.assert_not_called()
        dispatch.return_value.DoJavaScript.return_value = ''
        session.verify(); dispatch.assert_called_once()
        dispatch.return_value.DoJavaScript.side_effect = RuntimeError('Simulated disconnect')
        try: session.verify()
        except RuntimeError: pass
        else: raise AssertionError('Disconnected session accepted')
        dispatch.assert_called_once()
    with patch('win32com.client.GetActiveObject') as active, patch('win32com.client.Dispatch') as dispatch:
        active.return_value.DoJavaScript.return_value = '1:true:2:3:16:16'
        session = PhotoshopSession(defer_start=True)
        active.return_value.DoJavaScript.return_value = ''
        try: session.verify()
        except RuntimeError: pass
        else: raise AssertionError('Lost pre-existing Photoshop document accepted')
        dispatch.assert_not_called()
    with tempfile.TemporaryDirectory(dir=ROOT/'.cache') as directory:
        folder = Path(directory)
        # Synthetic format tags test layout handling, never camera-specific quality.
        for value, expected in ((32803, 'mosaic_dng'), (34892, 'linear_dng'), (1, 'unknown_dng')):
            source = folder/f'{value}.dng'
            shape = (16, 16, 3) if value == 34892 else (16, 16)
            tifffile.imwrite(source, np.zeros(shape, np.uint16), photometric=value)
            assert lightroom.source_encoding(source) == expected
        nested = folder/'nested.dng'
        with tifffile.TiffWriter(nested) as writer:
            writer.write(np.zeros((8, 8, 3), np.uint8), photometric='rgb', subifds=1)
            writer.write(np.zeros((16, 16), np.uint16), photometric=32803)
        assert lightroom.source_encoding(nested) == 'mosaic_dng'
        broken = folder/'broken.dng'; broken.write_bytes(b'invalid DNG')
        assert lightroom.source_encoding(broken) == 'unknown_dng'
        for ext in ('.arw', '.dng', '.heic', '.heif', '.jpg'):
            source = folder/('route'+ext); source.touch()
            assert inputs(source)[0] == [source]
            workspace = PromptWorkspace(); workspace.select_source(source)
            assert workspace.selected_input == source and workspace.job is None
            assert workspace._call('photo_status', {})['selected']
            assert (workspace.source is not None) == (ext == '.jpg')
            workspace.accept_prompt(uuid.uuid4().hex, f'Select "{source}"')
            workspace._call('select_context', {'kind':'photo', 'paths':[str(source)]})
            assert workspace.selected_input == source
        assert lightroom.source_encoding(folder/'route.heic') == 'rendered'
        # RAW inspection renders with Lightroom while preserving original selection for editing.
        workspace.select_source(folder/'route.arw')
        preview = lightroom.QUEUE/'test-preview.tif'
        with patch('photo_workflow.native_batch.connect_lightroom', return_value={'catalog':'test'}), \
             patch('photo_workflow.pipeline.job_lock', return_value=nullcontext()), \
             patch.object(lightroom, 'request', side_effect=[{'selection':'token'}, {'path':str(preview)}]), \
             patch.object(Workspace, '_call', return_value={'inspected':True}) as inspection:
            assert workspace._call('inspect_photo', {'path':'', 'view':'source'})['inspected']
            assert workspace.source == preview and workspace.selected_input.suffix == '.arw'
            inspection.assert_called_once()
        # The actual picker advertises native formats and keeps masks raster-only.
        with patch('tkinter.Tk'), patch('tkinter.filedialog.askopenfilename', return_value='') as chooser:
            pick('native_photo', folder/'choice.json')
            patterns = chooser.call_args.kwargs['filetypes'][0][1]
            assert all('*'+ext in patterns for ext in ('.arw', '.dng', '.heic', '.heif'))
            pick('photo', folder/'legacy-choice.json')
            assert '*.arw' not in chooser.call_args.kwargs['filetypes'][0][1]
            pick('mask', folder/'mask.json')
            assert '*.arw' not in chooser.call_args.kwargs['filetypes'][0][1]
        json_write(folder/'job.json', {'settings':{'before':{'settings':dict.fromkeys(DETAIL, 50),
                   'camera_model':'ILCE-7CR', 'iso':'125', 'source_encoding':'camera_raw'},
                   'after':{'settings':DETAIL}}})
        summary = change_summary({'output':str(folder)})
        assert 'Luminance detail preservation: 50 → 60' in summary and 'ILCE-7CR' in summary
    for key in DETAIL:
        lightroom.validate_settings({key:0});lightroom.validate_settings({key:100})
        for value in (-1, 101, True, float('nan')):
            try: lightroom.validate_settings({key:value})
            except ValueError: pass
            else: raise AssertionError(f'Accepted invalid {key}')
    print('Camera routing, DNG layout, picker, inspection and detail boundaries passed.', flush=True)


def verify(native_evidence=None):
    from photo_workflow.native_batch import connect_lightroom
    from photo_workflow.review_panel import change_summary
    local_runtime(); boundaries()
    source = ROOT/'tests/fixtures/cameras/sony-a7cr-7031.ARW'
    provenance = json.loads(source.with_name('a7cr-provenance.json').read_text())
    digest = sha256(source); assert digest == provenance['sha256']
    uid = uuid.uuid4().hex[:8]; evidence = ROOT/'outputs'/f'a7cr-chat-{uid}.json'
    record = ROOT/'outputs'/f'a7cr-{uid}-verification.json'
    report = {'status':'running', 'evidence':str(evidence), 'source_sha256':digest,
              'fixture':'Actual Sony ILCE-7CR CC0 ARW, ISO125; not a high-ISO quality benchmark',
              'pixels_remained_local':True, 'boundaries':'passed'}
    started = time.monotonic(); json_write(record, report)
    try:
        if native_evidence:
            prior = json.loads(Path(native_evidence).read_text())
            assert prior['source_sha256'] == digest and prior['native_detail_readback'] == dict(DETAIL, LuminanceSmoothing=20, ColorNoiseReduction=25)
            report.update(native_detail_readback=prior['native_detail_readback'], camera=prior['camera'],
                          native_control_evidence=str(native_evidence))
        else:
            catalog = connect_lightroom()
            assert Path(catalog['catalog']).is_relative_to(ROOT/'tests/lightroom')
            assert catalog['bridge_version'] >= 4
            initial = lightroom.request('import_photo', source=source, catalog=catalog['catalog'])
            assert initial['camera_model'] == 'ILCE-7CR' and initial['source_encoding'] == 'camera_raw'
            assert all(k in initial['settings'] for k in ('Sharpness', *DETAIL))
            controls = dict(DETAIL, LuminanceSmoothing=20, ColorNoiseReduction=25)
            edited = lightroom.request('develop', initial['selection'], controls, catalog=catalog['catalog'])
            assert edited['virtual_copy'] and edited['original_settings_preserved']
            assert all(edited['settings'][k] == v for k,v in controls.items())
            original = lightroom.request('import_photo', source=source, catalog=catalog['catalog'])
            assert original['settings'] == initial['settings']
            report['native_detail_readback'] = controls; report['camera'] = {k:initial[k] for k in ('camera_make','camera_model','iso','source_encoding')}
            json_write(record, report)
            print('Real A7CR native detail controls and original settings preservation passed.', flush=True)
        prompt = ('Denoise "tests/fixtures/cameras/sony-a7cr-7031.ARW" with SCUNet blend strength 0.25. '
                  'Keep natural texture and colors at full native resolution. Apply only rendered RGB denoising; '
                  'leave existing Lightroom settings unchanged. Do not restore faces, remove objects or upscale. '
                  'Save TIFF and layered Photoshop output.')
        workspace = PromptWorkspace()
        workspace.accept_prompt(uuid.uuid4().hex, prompt)
        result = workspace.call('edit_photos', {'path':'tests/fixtures/cameras/sony-a7cr-7031.ARW'})
        outer = {'events':workspace.events, 'entry':'Actual default edit_photos handler; existing interactive outer chat preserved'}
        json_write(evidence, outer)
        assert result['status'] == 'passed', result
        calls = [e for e in outer['events'] if e['tool'] == 'edit_photos']; assert len(calls) == 1
        batch_path = Path(calls[0]['result']['report']); batch = json.loads(batch_path.read_text())
        assert batch['status'] == 'passed'; item = batch['files'][0]
        inner = json.loads((Path(item['output'])/'model-evidence.json').read_text())
        names = [e['tool'] for e in inner['events']]
        assert names.count('edit_photo') == 1 and 'lightroom_develop' not in names
        assert 'lightroom_status' in names or 'photo_status' in names
        final = Path(item['final_output']); job = json.loads((final/'job.json').read_text())
        assert job['settings']['recipe']['denoise'] == .25 and job['settings']['recipe']['denoise_model'] == 'scunet'
        assert not job['runtime']['restoration_invoked'] and not job['runtime']['inpainting_invoked']
        with tifffile.TiffFile(item['tiff']) as tif:
            assert tif.pages[0].shape == (6336, 9504, 3) and tif.pages[0].dtype == np.uint16
        from photo_workflow.photoshop import review_name
        assert sha256(source) == digest and Path(item['psd']).name == review_name(
            *job['output_size'], len(job['layers']), job['bit_depth'])
        assert Path(item['psd']).is_file()
        for stage in item['stages']:
            adobe = json.loads((Path(stage)/'photoshop-verification.json').read_text())
            assert adobe['existing_document_state_preserved'] and adobe['assets_preserved']
        summary = change_summary(item)
        assert 'ILCE-7CR' in summary and 'SCUNET, rendered RGB' in summary
        ui = batch_path.parent/'review-ui-status.json'; deadline = time.monotonic()+30
        while time.monotonic() < deadline:
            if ui.exists() and json.loads(ui.read_text())['status'] == 'ready': break
            time.sleep(.2)
        assert json.loads(ui.read_text())['status'] == 'ready'
        report.update(status='passed', batch_report=str(batch_path), finish=batch['finish'],
                      review_summary=summary, source_preserved=True, native_resolution=[9504,6336],
                      original_settings_preserved=True, one_raster_attempt=True, seconds=time.monotonic()-started)
    except BaseException as error:
        report.update(status='failed', error=repr(error)); raise
    finally:
        json_write(record, report); json_write(ROOT/'outputs/latest-camera-pipeline-verification.json', report)
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__': verify()
