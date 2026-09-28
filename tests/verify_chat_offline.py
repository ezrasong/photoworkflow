"""Native OMP controls and actual local chat under approved temporary firewall rules."""
import argparse
import json
import subprocess
import sys
import uuid

from photo_workflow.chat import OMP, PROFILE, SYSTEM, Workspace, configure, running
from photo_workflow.runtime import ROOT, json_write, local_runtime, sha256
from tests.verify_expanded_offline import native_controls


def control(path):
    result = native_controls()
    probe = ROOT / '.cache/offline-probes' / ('omp-'+uuid.uuid4().hex+'.json')
    with running(Workspace()) as broker:
        env, work = configure(broker)
        # Only this HEAD control removes application-level proxy restrictions.
        # No photo extension, photos, notes, credentials or model inference is loaded.
        env = {k:v for k,v in env.items() if 'PROXY' not in k.upper()}
        env['PHOTO_PROBE_OUTPUT'] = str(probe)
        run = subprocess.run([str(OMP),'--cwd',str(work),'--model','photo-local/qwen-photo',
               '--no-tools','--no-extensions','--no-skills','--no-rules','--no-lsp','--no-pty','--no-title',
               '-e',str(ROOT/'tests/omp-network-probe.ts'),'-p','Network control only'],
               cwd=work,env=env,capture_output=True,text=True,encoding='utf-8',timeout=40,
               creationflags=subprocess.CREATE_NO_WINDOW)
        if run.returncode or not probe.exists(): raise RuntimeError('OMP probe failed: '+run.stderr[-1000:])
    result['omp'] = json.loads(probe.read_text())
    json_write(path,result)


def verify():
    # Unique ancillary PNG metadata forces a fresh job on every verification.
    from PIL import Image, PngImagePlugin
    source=ROOT/'tests/fixtures'/('offline-chat-'+uuid.uuid4().hex+'.png')
    metadata=PngImagePlugin.PngInfo(); metadata.add_text('verification',uuid.uuid4().hex)
    with Image.open(ROOT/'tests/fixtures/astronaut.png') as image:
        image.save(source,pnginfo=metadata)
    digest=sha256(source)
    evidence=ROOT/'outputs/chat-offline-blocked.json'
    with (ROOT/'outputs/chat-offline-model.log').open('w',encoding='utf-8') as stream:
        reference=json.loads((ROOT/'outputs/latest-reference-verification.json').read_text())['selected']
        run=subprocess.run([sys.executable,'-m','photo_workflow.chat','--source',str(source),'--reference',reference,
             '--prompt','First inspect the source with the selected reference using inspect_photo. These are different scenes; do not transfer details. Then apply exactly 0.47 stops exposure and DRUNet denoise strength 0.2 to the whole selected raster. Leave all other controls neutral. Do not search online.',
             '--evidence',str(evidence)],cwd=ROOT,stdout=stream,stderr=stream,timeout=300,
             creationflags=subprocess.CREATE_NO_WINDOW)
    assert run.returncode==0
    report=json.loads(evidence.read_text())
    assert report['model_requests']>=2 and not report['failures']
    visual=[e['result'] for e in report['events'] if e['tool']=='inspect_photo'];assert visual and visual[0]['image_count']==2
    edits=[e['result'] for e in report['events'] if e['tool']=='edit_photo'];assert len(edits)==1
    assert not edits[0]['reused_existing_job']
    from pathlib import Path
    job=json.loads((Path(edits[0]['job'])/'job.json').read_text())
    assert job['runtime']['denoiser']=='DRUNet color' and sha256(source)==digest
    print('Passed real OMP, local multimodal source/reference inspection and DRUNet while external networking was blocked.')


if __name__=='__main__':
    local_runtime()
    parser=argparse.ArgumentParser();parser.add_argument('--control');parser.add_argument('--python-only');args=parser.parse_args()
    if args.control: control(args.control)
    elif args.python_only:
        from photo_workflow.native_network import probe, executable
        json_write(args.python_only,dict(probe(),executable=executable()))
    else: verify()
