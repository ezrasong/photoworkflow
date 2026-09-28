"""Build the pinned upstream Mamba CUDA extension with existing Windows tools."""
import os
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ['TORCH_CUDA_ARCH_LIST'] = '12.0'
os.environ['MAX_JOBS'] = '2'
os.environ['PATH'] = str(ROOT / '.venv/Scripts') + os.pathsep + os.environ['PATH']
os.environ['TEMP'] = os.environ['TMP'] = str(ROOT / '.cache/temp')
from torch.utils.cpp_extension import load

build = ROOT / 'apps/mamba-scan-build'
build.mkdir(exist_ok=True)
source = build / 'cuda-source'
source.mkdir(exist_ok=True)
for original in (ROOT / 'apps/mamba-2.2.5/csrc/selective_scan').iterdir():
    if original.is_file():
        shutil.copyfile(original, source / original.name)
# MSVC cannot handle conditional directives nested inside BOOL_SWITCH macro
# arguments. Select the unchanged NVIDIA branch before compiling; retain upstream.
for name in ('selective_scan_fwd_kernel.cuh', 'selective_scan_bwd_kernel.cuh'):
    path = source / name
    code, count = re.subn(r'#ifndef USE_ROCM\s*\n(.*?)#else[^\n]*\n.*?#endif',
                          r'\1', path.read_text(), flags=re.S)
    assert count == 3, 'Pinned upstream CUDA branch layout changed'
    path.write_text(code.replace('constexpr int kNRows = 1;', 'static constexpr int kNRows = 1;'))
path = source / 'static_switch.h'
path.write_text(path.read_text().replace('constexpr bool CONST_NAME', 'static constexpr bool CONST_NAME'))
# This workflow only performs inference. Omit the backward binding/kernels.
path = source / 'selective_scan.cpp'
code = path.read_text().split('std::vector<at::Tensor>\nselective_scan_bwd(')[0]
path.write_text(code + '\nPYBIND11_MODULE(TORCH_EXTENSION_NAME, m) { m.def("fwd", &selective_scan_fwd); }\n')
module = load(name='selective_scan_cuda',
    sources=[str(source / 'selective_scan.cpp')] + [str(p) for p in sorted(source.glob('*_fwd_*.cu'))],
    extra_include_paths=[str(source)], extra_cflags=['/O2', '/std:c++17', '/Zc:preprocessor', '/D_USE_MATH_DEFINES'],
    extra_cuda_cflags=['-O3', '-std=c++17', '-D_USE_MATH_DEFINES', '-Xcompiler=/Zc:preprocessor', '--expt-relaxed-constexpr', '--expt-extended-lambda',
        '-U__CUDA_NO_HALF_OPERATORS__', '-U__CUDA_NO_HALF_CONVERSIONS__',
        '-U__CUDA_NO_BFLOAT16_OPERATORS__', '-U__CUDA_NO_BFLOAT16_CONVERSIONS__',
        '-U__CUDA_NO_BFLOAT162_OPERATORS__', '-U__CUDA_NO_BFLOAT162_CONVERSIONS__'],
    build_directory=str(build), verbose=True)
print(module.__file__)
