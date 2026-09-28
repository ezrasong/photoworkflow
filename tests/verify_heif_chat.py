"""Actual HEIC preparation -> local chat -> Adobe -> normal close and review."""
import json
from pathlib import Path
import time
import uuid

import tifffile

from photo_workflow.prompt_chat import PromptWorkspace
from photo_workflow.runtime import ROOT, json_write, local_runtime, sha256


def verify():
    from photo_workflow.native_batch import connect_lightroom
    from photo_workflow.review_panel import change_summary
    local_runtime()
    converted = json.loads((ROOT/'outputs/latest-heif-verification.json').read_text())
    assert converted['status'] == 'passed'
    source = Path(converted['source_for_integration']); digest = sha256(source)
    evidence = ROOT/'outputs'/('heif-chat-'+uuid.uuid4().hex[:8]+'.json')
    report = {'status':'running','source':str(source),'source_sha256':digest,
              'fixture':'Synthetic 10-bit SDR HEIC with sRGB ICC and camera EXIF; no phone quality claim'}
    try:
        catalog = connect_lightroom()
        assert Path(catalog['catalog']).is_relative_to(ROOT/'tests/lightroom')
        workspace = PromptWorkspace()
        prompt = f'Edit "{source}". Raise exposure by 0.10 stop in Lightroom. Leave all other settings unchanged. No denoise or upscale. Save TIFF and layered Photoshop output.'
        workspace.accept_prompt(uuid.uuid4().hex,prompt)
        result = workspace.call('edit_photos',{'path':str(source)})
        report['result'] = result
        assert result['status']=='passed',result
        batch_path = Path(result['report']);batch=json.loads(batch_path.read_text());item=batch['files'][0]
        assert item['conversion']['exact_decoded_pixel_readback'] and item['conversion']['source_bit_depth']==10
        assert sha256(source)==digest and item['source_preserved'] and item['original_settings_preserved']
        job=json.loads((Path(item['output'])/'job.json').read_text())
        assert job['settings']['before']['source_encoding']=='rendered_heif'
        assert job['settings']['before']['camera_model']=='iPhone 14 Pro Max'
        assert abs(job['settings']['after']['settings']['Exposure2012']-job['settings']['before']['settings']['Exposure2012']-.1)<1e-6
        with tifffile.TiffFile(item['tiff']) as tif:
            assert tif.pages[0].dtype.name=='uint16' and tif.pages[0].shape==(96,64,3)
        adobe=json.loads((Path(item['output'])/'photoshop-verification.json').read_text())
        assert adobe['bit_depth']==16 and adobe['assets_preserved'] and adobe['existing_document_state_preserved']
        summary=change_summary(item);assert 'HEIC/HEIF preparation' in summary and 'Exposure (stops)' in summary
        ui=batch_path.parent/'review-ui-status.json';deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            if ui.exists() and json.loads(ui.read_text())['status']=='ready':break
            time.sleep(.2)
        assert json.loads(ui.read_text())['status']=='ready'
        report.update(status='passed',batch=str(batch_path),changes=summary,finish=batch['finish'],
                      bit_depth=16,dimensions=[64,96],source_preserved=True)
    except BaseException as error:
        report.update(status='failed',error=repr(error));raise
    finally:
        json_write(evidence,report);json_write(ROOT/'outputs/latest-heif-chat-verification.json',report)
    print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':verify()
