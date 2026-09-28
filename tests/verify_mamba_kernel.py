"""Actual CUDA kernel compared numerically to pinned upstream PyTorch reference."""
import ast
import json
import torch
import torch.nn.functional as F
from einops import rearrange, repeat
from photo_workflow.runtime import ROOT, local_runtime, disable_network, json_write
from photo_workflow.mamba_scan import selective_scan_fn


def verify():
    local_runtime(); disable_network()
    source = ROOT/'apps/mamba-2.2.5/mamba_ssm/ops/selective_scan_interface.py'
    tree = ast.parse(source.read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name=='selective_scan_ref')
    namespace = dict(torch=torch, F=F, rearrange=rearrange, repeat=repeat)
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), namespace)
    reference = namespace['selective_scan_ref']
    results = []
    with torch.inference_mode():
        for length in (17, 256, 2049, 4096):
            torch.manual_seed(42)
            u = torch.randn(1, 12, length, device='cuda')
            delta = torch.randn_like(u)
            A = -torch.rand(12,16,device='cuda')
            B,C = [torch.randn(1,1,16,length,device='cuda') for _ in range(2)]
            D,bias = [torch.randn(12,device='cuda') for _ in range(2)]
            expected = reference(u,delta,A,B,C,D,delta_bias=bias,delta_softplus=True)
            actual = selective_scan_fn(u,delta,A,B,C,D,delta_bias=bias,delta_softplus=True)
            torch.testing.assert_close(actual, expected, rtol=3e-4, atol=3e-4)
            results.append({'sequence_length':length,'max_absolute_error':float((actual-expected).abs().max())})
    json_write(ROOT/'outputs/latest-mamba-kernel-verification.json', {'status':'passed','cases':results,
        'gpu':torch.cuda.get_device_name(0), 'reference':'Mamba v2.2.5 selective_scan_ref'})
    print(json.dumps(results), flush=True)


if __name__ == '__main__': verify()
