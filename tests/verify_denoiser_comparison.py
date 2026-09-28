"""Local numeric evaluation; never displays or transmits fixture pixels."""
import gc
import json
import time
import uuid

import cv2
import numpy as np
import torch
from scipy.io import loadmat
from skimage.metrics import peak_signal_noise_ratio, structural_similarity

from photo_workflow.runtime import ROOT, local_runtime, disable_network, json_write, sha256
from photo_workflow.imaging import decode_working, save_rgb
from photo_workflow.pipeline import job_lock
from photo_workflow.edits import quantize
from tests.denoiser_candidates import verify_pins, load_model, infer


def metrics(actual, target):
    a, b = actual.astype(np.float64)/65535, target.astype(np.float64)/65535
    return dict(psnr_db=float(peak_signal_noise_ratio(b,a,data_range=1)),
                ssim=float(structural_similarity(b,a,data_range=1,channel_axis=2,
                                                gaussian_weights=True,sigma=1.5,use_sample_covariance=False)),
                mean_rgb_bias_8bit=((a-b).mean(axis=(0,1))*255).tolist())


def verify():
    local_runtime(); disable_network()
    folder = ROOT/'outputs'/('denoiser-comparison-'+uuid.uuid4().hex[:8]); folder.mkdir()
    report = dict(status='running',folder=str(folder),results=[],
                  scope='80 preselected SIDD validation RGB blocks (indices 0 and 16 from each of 40 images); synthetic controls on one NASA photo. Not full SIDD benchmark or A7CR evidence.',
                  precision='float32 CUDA, autocast off, TF32 disabled; quantized directly to uint16',
                  metrics='RGB full extent, no border crop; PSNR data_range=1; SSIM Gaussian 11px sigma1.5 population covariance. Not necessarily identical to publisher MATLAB protocol.',
                  drunet_sigma='Fixed 5,15,25,50 sweeps on SIDD; no oracle-selected setting used as deployable result',
                  synthetic_seed=20260927,images_remained_local=True)
    latest = ROOT/'outputs/latest-denoiser-verification.json'
    def publish():
        json_write(folder/'benchmark.json',report); json_write(latest,report)
    publish()
    try:
        pins = verify_pins()
        report['manifest_sha256'] = sha256(ROOT/'models/denoiser-evaluation-manifest.json')
        paths = [ROOT/'tests/fixtures/SIDD'/f'{name}.mat' for name in ('ValidationNoisyBlocksSrgb','ValidationGtBlocksSrgb')]
        source = ROOT/'tests/fixtures/astronaut.png'
        hashes = {str(p):sha256(p) for p in paths+[source]}
        noisy = loadmat(paths[0])['ValidationNoisyBlocksSrgb']
        gt = loadmat(paths[1])['ValidationGtBlocksSrgb']
        assert noisy.shape == gt.shape == (40,32,256,256,3)
        fixtures=[]
        for scene in range(40):
            for block in (0,16):
                fixtures.append((f'sidd-{scene:02}-{block:02}', 'real_phone_srgb',
                                 noisy[scene,block].astype(np.uint16)*257,
                                 gt[scene,block].astype(np.uint16)*257, 15))
        del noisy,gt;gc.collect()
        clean,_ = decode_working(source.read_bytes())
        rng = np.random.default_rng(20260927)
        for sigma in (15,25):
            n = quantize(clean.astype(np.float32)/65535+rng.normal(0,sigma/255,clean.shape))
            fixtures.append((f'gaussian-{sigma}','synthetic_gaussian',n,clean,sigma))
        f = clean.astype(np.float32)/65535
        mixed = quantize(rng.poisson(f*100)/100+rng.normal(0,3/255,f.shape))
        encoded = cv2.imencode('.jpg',cv2.cvtColor(np.rint(mixed/257).astype(np.uint8),cv2.COLOR_RGB2BGR),[cv2.IMWRITE_JPEG_QUALITY,85])[1]
        mixed = cv2.cvtColor(cv2.imdecode(encoded,cv2.IMREAD_COLOR),cv2.COLOR_BGR2RGB).astype(np.uint16)*257
        fixtures.append(('poisson-jpeg','synthetic_poisson_gaussian_jpeg',mixed,clean,15))
        fixtures.append(('clean-control','clean_control',clean,clean,15))
        for key,kind,n,g,sigma in fixtures:
            save_rgb(folder/(key+'-input.tif'),n);save_rgb(folder/(key+'-gt.tif'),g)
        report['input_metrics'] = {key:metrics(n,g) for key,kind,n,g,sigma in fixtures if key!='clean-control'}
        with job_lock(ROOT/'.cache/gpu.lock'):
            torch.backends.cuda.matmul.allow_tf32=False
            torch.backends.cudnn.allow_tf32=False
            report['runtime'] = dict(torch=torch.__version__,cuda=torch.version.cuda,gpu=torch.cuda.get_device_name(0))
            for name in ('drunet','nafnet','scunet'):
                start=time.monotonic();model=load_model(name);torch.cuda.synchronize()
                report.setdefault('load_seconds',{})[name]=time.monotonic()-start
                assert next(model.parameters()).is_cuda
                # Warm up once, then record synchronized per-input latency excluding weight loading and disk writes.
                infer(model,name,fixtures[0][2])
                for key,kind,n,g,sigma in fixtures:
                    sigmas = (5,15,25,50) if name=='drunet' and kind=='real_phone_srgb' else (sigma,)
                    for level in sigmas:
                        torch.cuda.reset_peak_memory_stats();start=time.monotonic()
                        out=infer(model,name,n,level)
                        row=dict(model=name,fixture=key,kind=kind,sigma=level if name=='drunet' else None,
                                 seconds=time.monotonic()-start,peak_allocated_gib=torch.cuda.max_memory_allocated()/1024**3,
                                 peak_reserved_gib=torch.cuda.max_memory_reserved()/1024**3,
                                 metrics=metrics(out,g),output_dtype=str(out.dtype),shape=list(out.shape))
                        report['results'].append(row)
                        if name!='drunet' or level==sigma:
                            save_rgb(folder/f'{key}-{name}.tif',out)
                        if key=='sidd-00-00' and level==sigma:
                            row['repeat_exact']=bool(np.array_equal(out,infer(model,name,n,level)))
                            assert row['repeat_exact']
                            row['unique_output_values']=int(np.unique(out).size)
                            assert row['unique_output_values']>256
                        if key=='gaussian-15':
                            whole=infer(model,name,n,level,tile=1024)
                            diff=np.abs(out.astype(np.float64)-whole)/257
                            row['tiled_vs_whole']=dict(mean_8bit=float(diff.mean()),max_8bit=float(diff.max()),
                                                      seam_mean_8bit=float(diff[:,380:388].mean()),whole_metrics=metrics(whole,g))
                    if key.endswith('-16') and int(key.split('-')[1])%10==9:
                        print(name+' completed '+key,flush=True);publish()
                # A photographic crop tests high-bit precision. Uniform random RGB is
                # separately an out-of-distribution stress test, not a photograph.
                odd=quantize(clean[:131,:129].astype(np.float64)/65535*.731+.013)
                check=infer(model,name,odd)
                assert check.shape==odd.shape and check.dtype==np.uint16 and np.unique(check).size>256
                report.setdefault('odd_uint16_check',{})[name]=dict(passed=True,unique_values=int(np.unique(check).size))
                stress=quantize(np.random.default_rng(9).uniform(.15,.65,(131,129,3)))
                check=infer(model,name,stress)
                assert check.shape==stress.shape and check.dtype==np.uint16
                report.setdefault('uniform_random_stress',{})[name]=dict(
                    unique_values=int(np.unique(check).size),minimum=int(check.min()),maximum=int(check.max()),
                    clipped_fraction=float(np.mean((check==0)|(check==65535))))
                del model;gc.collect();torch.cuda.empty_cache()
                publish()
        assert all(sha256(p)==digest for p,digest in hashes.items())
        report.update(status='passed',source_preserved=True,source_hashes=hashes,
                      subjective_review='Not performed; human review must remain local')
    except BaseException as error:
        report.update(status='failed',error=repr(error));raise
    finally:
        publish()
    summary=[]
    for name in ('drunet','nafnet','scunet'):
        for sigma in ((5,15,25,50) if name=='drunet' else (None,)):
            rows=[r for r in report['results'] if r['model']==name and r['kind']=='real_phone_srgb' and r['sigma']==sigma]
            summary.append(dict(model=name,sigma=sigma,count=len(rows),psnr_db=float(np.mean([r['metrics']['psnr_db'] for r in rows])),
                                ssim=float(np.mean([r['metrics']['ssim'] for r in rows])),median_seconds=float(np.median([r['seconds'] for r in rows])),
                                max_peak_gib=max(r['peak_allocated_gib'] for r in rows)))
    report['sidd_summary']=summary;publish()
    print(json.dumps(summary,indent=2),flush=True)


if __name__=='__main__':verify()
