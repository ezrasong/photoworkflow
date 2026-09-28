"""Integration proof for the installed plug-in, only in a workspace test catalog."""
import json
from pathlib import Path

import tifffile

from photo_workflow.lightroom import QUEUE, request
from photo_workflow.runtime import ROOT, json_write, sha256


def check_develop(initial, edited):
    assert edited['selection'] != initial['selection'] and edited['virtual_copy']
    assert edited['original_settings_preserved'] is True
    assert edited['settings']['Exposure2012'] == .5
    assert edited['settings']['Highlights2012'] == -20


def check_export(path):
    path = Path(path).resolve()
    assert path.is_relative_to(QUEUE.resolve()) and path.suffix.lower() in {'.tif', '.tiff'}
    pixels = tifffile.imread(path)
    assert pixels.dtype.name == 'uint16' and pixels.shape == (512, 512, 3)
    return list(pixels.shape)


def verify():
    source=ROOT/'tests/fixtures/astronaut.png'; before=sha256(source)
    # Plug-in enforces the catalog path before importing the one public fixture.
    initial=request('import_fixture')
    edited=request('develop',initial['selection'],{'Exposure2012':.5,'Highlights2012':-20})
    check_develop(initial, edited)
    rendered=request('export',edited['selection'])
    assert rendered['selection'] == edited['selection'] and rendered['bit_depth'] == 16
    shape = check_export(rendered['path'])
    original = request('import_fixture')
    assert original['settings'] == initial['settings'] and not original['virtual_copy']
    assert sha256(source)==before
    json_write(ROOT/'outputs/latest-lightroom-verification.json',{'status':'passed','native_settings':edited,
        'export':rendered,'shape':shape,'bit_depth':16,'source_preserved':True,
        'original_settings_readback': original['settings']})
    print('Passed actual Lightroom virtual copy, Develop readback, original preservation and 16-bit export.')


if __name__=='__main__':
    report = ROOT/'outputs/latest-lightroom-verification.json'
    json_write(report, {'status': 'running'})
    try:
        verify()
    except BaseException as error:
        json_write(report, {'status': 'failed', 'error': repr(error),
                           'native_acceptance': 'not passed; inspect any in-flight copy before retrying'})
        raise
