"""Local public-fixture SR comparison; does not transmit or display pixels."""
import gc
import json
import time
import uuid

import cv2
import numpy as np
import torch
from PIL import Image
from skimage.metrics import peak_signal_noise_ratio, structural_similarity

from photo_workflow.runtime import ROOT, local_runtime, disable_network, json_write, sha256


def metrics(actual, target, scale):
    a = actual[scale:-scale, scale:-scale].astype(np.float64)/65535
    b = target[scale:-scale, scale:-scale].astype(np.float64)/65535
    return {'rgb_psnr_db':float(peak_signal_noise_ratio(b,a,data_range=1)),
            'rgb_ssim':float(structural_similarity(b,a,data_range=1,channel_axis=2))}


def verify():
    local_runtime(); disable_network()
    from photo_workflow.mambair import MambaUpscaler
    from photo_workflow.models import Models
    from photo_workflow.imaging import save_rgb
    source = ROOT/'tests/fixtures/astronaut.png'
    source_hash = sha256(source)
    rgb = np.array(Image.open(source).convert('RGB'))
    folder = ROOT/'outputs'/('mambair-benchmark-'+uuid.uuid4().hex[:8]);folder.mkdir()
    report = {'status':'running','folder':str(folder),'source_sha256':source_hash,
        'scope':'One public photograph, bicubic downsample; not a real-camera benchmark or universal quality ranking',
        'results':[]}
    model = MambaUpscaler()
    for scale in (2,4):
        # Full 512px fixture gives 256/128px LR and exercises tiling at 2x.
        low8 = np.array(Image.fromarray(rgb).resize((512//scale,512//scale),Image.Resampling.BICUBIC))
        low = low8.astype(np.uint16)*257
        target = rgb.astype(np.uint16)*257
        save_rgb(folder/f'input-{scale}x.tif',low)
        baseline = cv2.resize(low,(512,512),interpolation=cv2.INTER_LANCZOS4)
        torch.cuda.reset_peak_memory_stats()
        start=time.monotonic(); actual=model.upscale(low,scale); torch.cuda.synchronize()
        row={'scale':scale,'seconds':time.monotonic()-start,
            'peak_allocated_gib':torch.cuda.max_memory_allocated()/1024**3,
            'lanczos':metrics(baseline,target,scale),'mambairv2':metrics(actual,target,scale)}
        save_rgb(folder/f'mambairv2-{scale}x.tif',actual)
        repeat=model.upscale(low,scale)
        assert np.array_equal(actual,repeat),'Fixed-seed inference was not repeatable'
        row['repeat_exact']=True
        row['output_dtype']=str(actual.dtype)
        # Isolate the impact of tiles from the model itself at the largest LR size.
        if scale==2:
            model.tile=512
            torch.cuda.reset_peak_memory_stats()
            whole=model.upscale(low,scale)
            model.tile=192
            save_rgb(folder/'mambairv2-2x-untiled.tif',whole)
            diff=np.abs(actual.astype(np.float32)-whole.astype(np.float32))/65535
            row['tiled_vs_whole']={'mean_absolute_8bit_levels':float(diff.mean()*255),
                'max_absolute_8bit_levels':float(diff.max()*255),
                'untiled_metrics':metrics(whole,target,scale),
                'seam_band_mean_8bit_levels':float(diff[:,380:388].mean()*255)}
        report['results'].append(row)
        print('Mamba completed '+json.dumps(row),flush=True)
    report['runtime']=model.info()
    del model;gc.collect();torch.cuda.empty_cache()
    esr=Models(restoration=False)
    for row in report['results']:
        scale=row['scale']
        low=np.array(Image.fromarray(rgb).resize((512//scale,512//scale),Image.Resampling.BICUBIC)).astype(np.uint16)*257
        start=time.monotonic();actual=esr.upscale(low,scale);torch.cuda.synchronize()
        row['realesrgan']=metrics(actual,rgb.astype(np.uint16)*257,scale)
        row['realesrgan_seconds']=time.monotonic()-start
        save_rgb(folder/f'realesrgan-{scale}x.tif',actual)
    assert sha256(source)==source_hash
    report.update(status='passed',source_preserved=True,images_remained_local=True,
                  subjective_review='Local human review still required')
    json_write(folder/'benchmark.json',report)
    json_write(ROOT/'outputs/latest-mambair-verification.json',report)
    print(json.dumps(report['results'],indent=2),flush=True)


if __name__=='__main__':verify()
