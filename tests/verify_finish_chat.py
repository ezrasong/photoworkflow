"""Actual default launcher -> edits -> normal Adobe close -> local review UI."""
import json
from pathlib import Path
import subprocess
import time
import uuid

from photo_workflow.runtime import ROOT, json_write, local_runtime, sha256


def verify():
    local_runtime();uid=uuid.uuid4().hex[:8]
    record=ROOT/'outputs'/f'finish-chat-{uid}-verification.json'
    evidence=ROOT/'outputs'/f'finish-chat-{uid}.json'
    source=ROOT/'tests/fixtures/astronaut.png';digest=sha256(source)
    report={'status':'running','evidence':str(evidence),'source_sha256':digest}
    started=time.monotonic();json_write(record,report)
    try:
        prompt='Edit "tests/fixtures/astronaut.png". Raise global exposure by 0.15 stop in Lightroom, then denoise gently with blend strength 0.25. Keep natural texture and colors. Do not restore faces, remove objects or upscale. Save TIFF and layered Photoshop output.'
        with evidence.with_suffix('.log').open('w',encoding='utf-8') as log:
            run=subprocess.run([str(ROOT/'omp.cmd'),'--prompt',prompt,'--evidence',str(evidence)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=900,creationflags=subprocess.CREATE_NO_WINDOW)
        outer=json.loads(evidence.read_text());assert run.returncode==0 and not outer['failures']
        calls=[event for event in outer['events'] if event['tool']=='edit_photos'];assert len(calls)==1
        batch_path=Path(calls[0]['result']['report']);batch=json.loads(batch_path.read_text())
        assert batch['status']=='passed';item=batch['files'][0]
        inner=json.loads((Path(item['output'])/'model-evidence.json').read_text())
        names=[event['tool'] for event in inner['events']]
        assert names.count('lightroom_develop')==1 and names.count('edit_photo')==1
        final=Path(item['final_output']);job=json.loads((final/'job.json').read_text())
        assert job['settings']['recipe']['denoise']==.25
        assert not job['runtime']['restoration_invoked'] and not job['runtime']['inpainting_invoked']
        assert sha256(source)==digest
        assert Path(item['psd']).exists() and Path(item['tiff']).exists()
        for stage in item['stages']:
            adobe=json.loads((Path(stage)/'photoshop-verification.json').read_text())
            assert adobe['existing_document_state_preserved'] and adobe['assets_preserved']
        deadline=time.monotonic()+15;ui=batch_path.parent/'review-ui-status.json'
        while not ui.exists() and time.monotonic()<deadline:time.sleep(.2)
        assert ui.exists() and json.loads(ui.read_text())['status']=='ready'
        assert batch['finish']['review']=='launched'
        report.update(status='passed',batch_report=str(batch_path),finish=batch['finish'],ui=json.loads(ui.read_text()),
                      source_preserved=True,one_attempt_per_edit_stage=True,seconds=time.monotonic()-started,
                      shutdown_all_closed=all(v['status'] in ('closed','already closed') for v in batch['finish']['adobe'].values()))
    except BaseException as error:report.update(status='failed',error=repr(error));raise
    finally:
        json_write(record,report);json_write(ROOT/'outputs/latest-finish-chat-verification.json',report)
    print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':verify()
