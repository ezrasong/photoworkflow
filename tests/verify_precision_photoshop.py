import json
from pathlib import Path
import numpy as np
from psd_tools import PSDImage
import tifffile
from photo_workflow.photoshop import export
from photo_workflow.runtime import ROOT,json_write

def verify():
    report=json.loads((ROOT/'outputs/latest-precision-verification.json').read_text())
    results=[]
    # Include no-face genuine 16-bit gradient and the restored/upscaled photograph.
    for entry in (report['actual_gpu_inference'][0],report['actual_gpu_inference'][-1]):
        folder=Path(entry['job'])
        if not (folder/'review.psd').exists(): result=export(folder)
        else: result=json.loads((folder/'photoshop-verification.json').read_text())
        psd=PSDImage.open(folder/'review.psd')
        job=json.loads((folder/'job.json').read_text())
        assert psd.depth==16
        saved=np.rint(list(psd)[0].numpy('color')*65535).astype(np.int32)
        baseline=tifffile.imread(folder/job['baseline_file']).astype(np.int32)
        baseline_error=int(np.abs(saved-baseline).max())
        # Photoshop's native 16-bit editing uses 0..32768 internally; allow 1 LSB.
        assert baseline_error<=2, baseline_error
        masks=[]
        for layer,spec in zip(list(psd)[1:],job['layers']):
            assert layer.has_mask() and not layer.mask.disabled
            assert abs(layer.opacity/255*100-spec['opacity'])<.5
            stored=layer.numpy('mask')
            full=np.full((psd.height,psd.width),layer.mask.background_color/255,dtype=np.float32)
            left,top,right,bottom=layer.mask.bbox
            if stored is not None:
                full[top:bottom,left:right]=stored.squeeze()
            expected=tifffile.imread(folder/spec['mask']).astype(np.int32)
            error=int(np.abs(np.rint(full*65535).astype(np.int32)-expected).max())
            assert error<=2,error
            levels=int(len(np.unique(full)))
            if spec['name'].startswith('GFPGAN'):
                assert levels>256, 'Saved mask was quantized to 8 bits'
            masks.append({'name':layer.name,'max_16bit_error':error,'distinct_levels':levels})
        result.update(baseline_max_16bit_error=baseline_error,mask_precision=masks,
                      note='Photoshop 16-bit internal rounding may differ by 1–2 of 65535 levels')
        json_write(folder/'photoshop-verification.json',result)
        results.append({'job':str(folder),**result})
    report['photoshop']=results
    json_write(ROOT/'outputs/latest-precision-verification.json',report)
    json_write(Path(report['actual_gpu_inference'][0]['job']).parent/'verification.json',report)
    print(json.dumps(results,indent=2))

if __name__=='__main__': verify()
