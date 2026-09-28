"""Real Adobe format decoding; synthetic metadata is not phone quality evidence."""
import json
from pathlib import Path
import shutil
import uuid

from PIL import Image

from photo_workflow import lightroom
from photo_workflow.finish import close_adobe
from photo_workflow.native_batch import connect_lightroom, copy_render
from photo_workflow.pipeline import job_lock
from photo_workflow.runtime import ROOT, json_write, local_runtime, sha256


def verify():
    local_runtime()
    folder = ROOT/'outputs'/('phone-formats-'+uuid.uuid4().hex[:8]); folder.mkdir()
    report = {'status':'running', 'checks':[], 'failures':[], 'pixels_remained_local':True,
              'limits':'Format and metadata tests only; no actual Vivo X300 Ultra or iPhone 14 Pro Max quality samples.'}
    try:
        fixtures = ROOT/'tests/fixtures/cameras'
        dng = folder/'public-iphone12pro-linear.DNG'
        shutil.copyfile(fixtures/'iphone12pro-linear.DNG', dng)
        cases = [(dng, 'linear_dng', 'iPhone 12 Pro'),
                 (fixtures/'libheif-example.heic', 'rendered', None)]
        heif = folder/'public-example.heif'; shutil.copyfile(cases[-1][0], heif)
        cases.append((heif, 'rendered', None))
        for make, model in [('vivo', 'vivo X300 Ultra'), ('Apple', 'iPhone 14 Pro Max')]:
            source = folder/('synthetic-'+model.replace(' ', '-')+'.jpg')
            exif = Image.Exif(); exif[271] = make; exif[272] = model
            with Image.open(ROOT/'tests/fixtures/astronaut.png') as image:
                image.convert('RGB').save(source, exif=exif)
            cases.append((source, 'rendered', model))
        with job_lock(ROOT/'.cache/chat.lock'):
            catalog = connect_lightroom()
            assert Path(catalog['catalog']).is_relative_to(ROOT/'tests/lightroom')
            assert catalog['bridge_version'] >= 4
            for index, (source, encoding, model) in enumerate(cases):
                digest = sha256(source)
                try:
                    initial = lightroom.request('import_photo', source=source, catalog=catalog['catalog'])
                    assert initial['source_encoding'] == encoding
                    if model: assert initial['camera_model'] == model, initial.get('camera_model')
                    rendered = lightroom.request('export', initial['selection'], catalog=catalog['catalog'])
                    pixels = copy_render(rendered, folder/f'{index}-render.tif')
                    assert pixels.dtype.name == 'uint16' and pixels.shape[2] == 3
                    original = lightroom.request('status', initial['selection'], catalog=catalog['catalog'])
                    assert all(original['settings'].get(k) == v for k,v in initial['settings'].items())
                    assert sha256(source) == digest
                    report['checks'].append({'source':str(source), 'source_sha256':digest,
                        'camera_model':initial.get('camera_model'), 'source_encoding':encoding,
                        'render_shape':list(pixels.shape), 'bit_depth':16, 'original_preserved':True,
                        'initialized_native_settings':sorted(original['settings'].keys()-initial['settings'].keys())})
                except Exception as error:
                    assert sha256(source) == digest
                    report['failures'].append({'source':str(source), 'error':str(error), 'source_preserved':True})
                    print('Format check failed without retry: '+source.name, flush=True)
                    continue
                json_write(folder/'verification.json', report)
                print('Passed native decode and preservation: '+source.name, flush=True)
            report['shutdown'] = close_adobe(catalog['catalog'])
        report['status'] = 'partial' if report['failures'] else 'passed'
    except BaseException as error:
        report.update(status='failed', error=repr(error)); raise
    finally:
        json_write(folder/'verification.json', report)
        json_write(ROOT/'outputs/latest-phone-format-verification.json', report)
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__': verify()
