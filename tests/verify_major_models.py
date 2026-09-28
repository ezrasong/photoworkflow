"""Real CUDA inference and labeled public-fixture metrics; pixels remain local."""
import json
import time
import uuid

import cv2
import numpy as np

from photo_workflow.runtime import ROOT, local_runtime, disable_network, json_write
from photo_workflow.imaging import decode_working, save_rgb, save_mask
from photo_workflow.pipeline import job_lock
from photo_workflow.selection import automatic_mask, pixel_hash, assert_binding
from photo_workflow.inpainting import inpaint


def metrics(mask, truth):
    a, b = mask > 0, truth > 0
    kernel = np.ones((3,3), np.uint8)
    ea = a.astype(np.uint8)-cv2.erode(a.astype(np.uint8), kernel)
    eb = b.astype(np.uint8)-cv2.erode(b.astype(np.uint8), kernel)
    precision = np.sum(ea*(cv2.dilate(eb,np.ones((5,5),np.uint8)) > 0))/max(1,ea.sum())
    recall = np.sum(eb*(cv2.dilate(ea,np.ones((5,5),np.uint8)) > 0))/max(1,eb.sum())
    return dict(iou=float(np.sum(a&b)/np.sum(a|b)), boundary_f1_2px=float(2*precision*recall/max(1e-9,precision+recall)))


def verify():
    local_runtime(); disable_network()
    folder = ROOT/'outputs'/('major-models-'+uuid.uuid4().hex[:8]); folder.mkdir()
    report = dict(status='running', folder=str(folder), images_remained_local=True)
    try:
        with job_lock(ROOT/'.cache/gpu.lock'):
            for id, category, position in [(252219,'person','leftmost'),(252219,'person','rightmost')]:
                source = ROOT/f'tests/fixtures/COCO/{id:012}.jpg'
                rgb, _ = decode_working(source.read_bytes(),16,False)
                mask, record = automatic_mask(rgb,dict(category=category,position=position))
                anns = json.loads((source.parent/f'{id}.json').read_text())
                cid = next(x['id'] for x in anns['categories'] if x['name']==category)
                targets = [x for x in anns['annotations'] if x['category_id']==cid and not x['iscrowd']]
                target = (min if position=='leftmost' else max)(targets,key=lambda x:x['bbox'][0]+x['bbox'][2]/2)
                truth = np.zeros(mask.shape,np.uint8)
                for poly in target['segmentation']:
                    cv2.fillPoly(truth,[np.rint(np.array(poly).reshape(-1,2)).astype(np.int32)],1)
                report[str(id)+'-'+position] = dict(record, **metrics(mask,truth), label_rasterization='COCO polygons rounded to nearest pixels with OpenCV')
                save_mask(folder/f'{id}-{position}-mask.tif',mask)
                save_mask(folder/f'{id}-{position}-label.tif',truth.astype(np.uint16)*65535)
                assert_binding(record,rgb)
                try: assert_binding(record,np.flip(rgb,axis=1))
                except ValueError: pass
                else: raise AssertionError('Stale mask accepted')
                if position=='rightmost':
                    effective=cv2.dilate(mask,np.ones((9,9),np.uint8))
                    result, info=inpaint(rgb,effective)
                    composite=rgb.copy();composite[effective>0]=result[effective>0]
                    assert np.array_equal(composite[effective==0],rgb[effective==0])
                    save_rgb(folder/'removal.tif',composite)
                    report['inpaint']=dict(info,outside_exact=True,changed_pixels=int(np.count_nonzero(np.any(composite!=rgb,axis=2))))
            # A known synthetic hole is a numerical diagnostic, not proof of photographic plausibility.
            yy,xx=np.mgrid[:256,:256]
            synthetic=np.stack((.2+xx/1024,.3+yy/1024,np.full(xx.shape,.4)),axis=2)
            image=np.rint(synthetic*65535).astype(np.uint16)
            hole=np.zeros((256,256),np.uint16);hole[100:140,105:150]=65535
            result,info=inpaint(image,hole)
            error=(result[hole>0].astype(float)-image[hole>0])/65535
            report['synthetic_hole']=dict(info,psnr=float(-10*np.log10(np.mean(error**2))))
        report['status']='passed'
    except BaseException as e:
        report.update(status='failed',error=repr(e));raise
    finally:
        json_write(folder/'verification.json',report)
        json_write(ROOT/'outputs/latest-major-models-verification.json',report)
    print(json.dumps(report,indent=2))


if __name__=='__main__':verify()
