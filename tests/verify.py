"""Real offline CUDA acceptance checks. Run from workspace: python -m tests.verify."""
import io
import json
from pathlib import Path
import socket
import threading
import time
import uuid

import numpy as np
from PIL import Image

from photo_workflow.runtime import ROOT, disable_network, json_write, local_runtime, sha256

def verify():
    local_runtime()
    disable_network()
    from photo_workflow.imaging import decode, stable_read
    from photo_workflow.pipeline import Pipeline, job_lock
    try:
        socket.create_connection(('1.1.1.1', 443), timeout=.1)
        raise AssertionError('Network should be denied')
    except PermissionError:
        pass
    fixtures = ROOT / 'tests/fixtures'
    astronaut = fixtures / 'astronaut.png'
    if not astronaut.exists():
        raise RuntimeError('First run scripts/download_fixture.py during installation')
    original = Image.open(astronaut).convert('RGB')
    multiple = Image.new('RGB', (1024, 512)); multiple.paste(original); multiple.paste(original, (512, 0))
    multiple.save(fixtures / 'multiple.jpg', quality=95)
    Image.new('RGB', (128, 96), (60, 90, 120)).save(fixtures / 'no-face.tiff')
    (fixtures / 'corrupt.jpg').write_bytes(b'not an image')
    paths = [astronaut, fixtures / 'multiple.jpg', fixtures / 'no-face.tiff', fixtures / 'corrupt.jpg']
    hashes = {p.name: sha256(p) for p in paths}
    run_id = time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6]
    output = ROOT / 'outputs' / ('acceptance-' + run_id)
    pipeline = Pipeline(output)
    results = []
    for path, scale, expected_faces in [(astronaut, 2, 1), (paths[1], 1, 2), (paths[2], 1, 0)]:
        folder, skipped = pipeline.process(path, scale=scale, settle=.05, bit_depth=8)
        assert not skipped
        job = json.loads((folder / 'job.json').read_text())
        assert job['faces'] == expected_faces, job['faces']
        size = Image.open(path).size
        assert Image.open(folder / 'composite.png').size == (size[0]*scale, size[1]*scale)
        assert sha256(folder / ('source' + path.suffix)) == hashes[path.name]
        assert Image.open(folder / 'composite.png').info.get('icc_profile')
        if expected_faces == 0:
            assert sha256(folder / 'original.png') == sha256(folder / 'composite.png')
        else:
            mask = np.array(Image.open(folder / 'face-01-mask.png'))
            assert mask.max() > 128 and mask.min() == 0
            assert np.any(np.array(Image.open(folder / 'original.png')) != np.array(Image.open(folder / 'composite.png')))
        before = {p.name: (sha256(p), p.stat().st_mtime_ns) for p in folder.iterdir()}
        again, skipped = pipeline.process(path, scale=scale, settle=.05, bit_depth=8)
        assert skipped and again == folder
        assert before == {p.name: (sha256(p), p.stat().st_mtime_ns) for p in folder.iterdir()}
        results.append({'input': path.name, 'job': str(folder), 'faces': job['faces'],
                        'dimensions': job['output_size'], 'seconds': job['inference_seconds']})
        print('PASS real CUDA:', path.name, expected_faces, 'faces', flush=True)
    try:
        pipeline.process(paths[3], settle=.05)
        raise AssertionError('Corrupt file accepted')
    except (ValueError, OSError):
        pass
    # Orientation / ICC / bit-depth decoding checks use locally generated test data.
    oriented = Image.new('RGB', (20, 10), (10, 20, 30)); exif = Image.Exif(); exif[274] = 6
    stream = io.BytesIO(); oriented.save(stream, format='JPEG', exif=exif)
    assert decode(stream.getvalue())[0].size == (10, 20)
    stream = io.BytesIO(); Image.fromarray(np.full((16, 16), 32768, np.uint16)).save(stream, format='TIFF')
    try:
        decode(stream.getvalue())
        raise AssertionError('16-bit silently accepted')
    except ValueError:
        pass
    reduced, conversions = decode(stream.getvalue(), True)
    assert np.array(reduced)[0, 0, 0] == 128 and any('16-bit' in c for c in conversions)
    # Demonstrate waiting for an active writer, and lock contention.
    slow = fixtures / 'writing.png'; payload = astronaut.read_bytes()
    def writer():
        with slow.open('wb') as file:
            file.write(payload[:100]); file.flush(); time.sleep(.5); file.write(payload[100:])
    thread = threading.Thread(target=writer); thread.start(); time.sleep(.05)
    assert stable_read(slow, settle=.2) == payload
    thread.join()
    with job_lock(output / 'test.lock'):
        try:
            with job_lock(output / 'test.lock'):
                raise AssertionError('Concurrent job lock failed')
        except RuntimeError:
            pass
    # Fault injection tests transaction rollback only; these are NOT model-execution proof.
    from unittest.mock import patch
    from photo_workflow.models import Models
    import torch
    for error in (torch.cuda.OutOfMemoryError('injected OOM'), KeyboardInterrupt()):
        with patch.object(Models, 'faces', side_effect=error):
            try:
                pipeline.process(astronaut, blend=.123, settle=.05, bit_depth=8)
                raise AssertionError('Injected failure swallowed')
            except type(error):
                pass
        assert not list(output.glob('.partial-*'))
    assert hashes == {p.name: sha256(p) for p in paths}
    report = {'status': 'passed', 'run_id': run_id, 'network_attempt': 'denied before connection',
              'actual_gpu_inference': results, 'gpu': job['runtime'],
              'checks': ['multiple faces', 'no face unchanged', 'corrupt input rejected', 'rerun unchanged',
                         'source hashes unchanged', 'output dimensions', 'ICC output', 'EXIF orientation',
                         '16-bit explicit opt-in', 'active writer waited for', 'duplicate lock',
                         'injected OOM rollback', 'injected cancellation rollback'],
              'visual_quality': 'Awaiting human review in local applications'}
    json_write(output / 'verification.json', report)
    json_write(ROOT / 'outputs/latest-verification.json', report)
    print(output, flush=True)

if __name__ == '__main__':
    verify()
