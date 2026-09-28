"""Local decoded-pixel, color, orientation and native editing acceptance."""
import json
from pathlib import Path
import uuid

import numpy as np
import pillow_heif
from PIL import Image
import tifffile

from photo_workflow.heif import prepare, color_profile
from photo_workflow.imaging import SRGB
from photo_workflow.runtime import ROOT, local_runtime, json_write, sha256


def verify():
    local_runtime()
    folder = ROOT/'outputs'/('heif-verification-'+uuid.uuid4().hex[:8]);folder.mkdir()
    report = {'status':'running', 'folder':str(folder), 'checks':[], 'pixels_remained_local':True}
    try:
        y,x = np.mgrid[:64,:96]
        pixels = np.stack((x*650,y*1000,(x+y)*400),axis=2).astype(np.uint16)
        for depth in (8,10,12):
            data = (pixels//257).astype(np.uint8) if depth == 8 else pixels
            image = pillow_heif.from_bytes('RGB' if depth==8 else 'RGB;16',(96,64),data.tobytes())
            exif=Image.Exif();exif[271]='Apple';exif[272]='iPhone 14 Pro Max';exif[274]=6
            source=folder/f'synthetic-{depth}.heic'
            image.save(source,quality=-1,chroma=444,bit_depth=depth,icc_profile=SRGB,exif=exif.tobytes())
            digest=sha256(source)
            decoded=pillow_heif.open_heif(source,convert_hdr_to_8bit=False,hdr_to_16bit=True)
            expected=np.asarray(decoded)
            if expected.dtype==np.uint8:expected=expected.astype(np.uint16)*257
            converted,record=prepare(source,folder/f'converted-{depth}')
            assert record['source_bit_depth']==depth
            with tifffile.TiffFile(converted) as tif:
                assert tif.pages[0].dtype==np.uint16 and np.array_equal(tif.asarray(),expected)
                assert tif.pages[0].tags[34675].value==SRGB and tif.pages[0].tags[274].value==1
            assert sha256(source)==digest
            assert expected.shape[:2]==(96,64),expected.shape
            assert np.unique(expected).size > 256 if depth>8 else True
            assert record['camera']['camera_model']=='iPhone 14 Pro Max'
            assert (converted.parent/'source.exif').read_bytes()==decoded.info['exif']
            report['checks'].append({'depth':depth,'dimensions':record['dimensions'],
                'exact_decoded_pixels':True,'profile_exact':True,'orientation_applied_once':True,'source_preserved':True})
        # NCLX sRGB and Display P3 produce an ICC without converting RGB samples.
        for primaries in (1,12):
            source=folder/f'nclx-{primaries}.heif'
            image=pillow_heif.from_bytes('RGB',(96,64),(pixels//257).astype(np.uint8).tobytes())
            image.save(source,quality=-1,chroma=444,save_nclx_profile=True,
                       color_primaries=primaries,transfer_characteristics=13,matrix_coefficients=0)
            converted,record=prepare(source,folder/f'nclx-converted-{primaries}')
            assert record['exact_decoded_pixel_readback']
        for info in ({'bit_depth':10,'nclx_profile':{'transfer_characteristics':16}},
                     {'bit_depth':10,'nclx_profile':{'transfer_characteristics':18}},
                     {'bit_depth':8,'icc_profile':SRGB,'aux':{'gainmap':[1]}},
                     {'bit_depth':8,'icc_profile':SRGB,'xmp':b'<hdrgm:Version>1.0</hdrgm:Version>'},
                     {'bit_depth':8}):
            try:color_profile(info)
            except ValueError:pass
            else:raise AssertionError('Unsupported quality condition accepted')
        # The untagged upstream example must not acquire a guessed sRGB profile.
        try:prepare(ROOT/'tests/fixtures/cameras/libheif-example.heic',folder/'untagged')
        except ValueError as error:assert 'color metadata' in str(error)
        else:raise AssertionError('Untagged color silently assumed')
        assert not (folder/'untagged/converted.tif').exists()
        # Actual PQ-tagged file must stop before a TIFF is published.
        hdr=folder/'synthetic-pq.heic'
        image.save(hdr,quality=-1,chroma=444,save_nclx_profile=True,
                   color_primaries=9,transfer_characteristics=16,matrix_coefficients=9)
        try:prepare(hdr,folder/'hdr-rejected')
        except ValueError as error:assert 'HDR' in str(error)
        else:raise AssertionError('Actual PQ file accepted')
        assert not (folder/'hdr-rejected/converted.tif').exists()
        # Primary item selection must never substitute another image or thumbnail.
        first=pillow_heif.from_bytes('RGB',(96,64),np.zeros((64,96,3),np.uint8).tobytes())
        second=pillow_heif.from_bytes('RGB',(96,64),np.full((64,96,3),180,np.uint8).tobytes())
        multi=folder/'multiple.heic'
        first.save(multi,append_images=[second[0]],primary_index=1,quality=-1,chroma=444,icc_profile=SRGB)
        output,record=prepare(multi,folder/'multiple-converted')
        assert record['top_level_images']==2 and record['primary_index']==1
        expected=np.asarray(pillow_heif.open_heif(multi)).astype(np.uint16)*257
        assert np.array_equal(tifffile.imread(output),expected)
        try:prepare(folder/'synthetic-8.heic',folder/'converted-8')
        except FileExistsError:pass
        else:raise AssertionError('Existing conversion overwritten')
        report.update(status='passed',hdr_auxiliary_unknown_color_rejected=True,nclx_profiles='sRGB and Display P3 passed',
                      source_for_integration=str(folder/'synthetic-10.heic'))
    except BaseException as error:
        report.update(status='failed',error=repr(error));raise
    finally:
        json_write(folder/'verification.json',report);json_write(ROOT/'outputs/latest-heif-verification.json',report)
    print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':verify()
