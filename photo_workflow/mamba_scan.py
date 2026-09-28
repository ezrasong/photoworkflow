"""Inference-only adapter to the locally compiled upstream Mamba CUDA kernel.

Avoids importing Mamba's unrelated training/Triton/causal-convolution packages.
No runtime compilation, download, CPU substitute, or alternate model fallback.
"""
import importlib.util
import sys

from .runtime import ROOT


def kernel():
    if 'selective_scan_cuda' not in sys.modules:
        path = ROOT / 'apps/mamba-scan-build/selective_scan_cuda.pyd'
        if not path.is_file():
            raise RuntimeError('MambaIRv2 CUDA kernel is missing. Repair the Luma Atelier installation; no runtime compiler is required.')
        spec = importlib.util.spec_from_file_location('selective_scan_cuda', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        sys.modules[spec.name] = module
    return sys.modules['selective_scan_cuda']


def selective_scan_fn(u, delta, A, B, C, D=None, z=None, delta_bias=None,
                      delta_softplus=False, return_last_state=False):
    import torch
    if torch.is_grad_enabled():
        raise RuntimeError('Mamba scan adapter is inference-only')
    if z is not None or return_last_state:
        raise ValueError('MambaIRv2 inference requires no z or last-state output')
    # This is the same forward call used by upstream SelectiveScanFn.forward.
    out, _ = kernel().fwd(u.contiguous(), delta.contiguous(), A,
        B.contiguous(), C.contiguous(), D, None, delta_bias, delta_softplus)
    return out
