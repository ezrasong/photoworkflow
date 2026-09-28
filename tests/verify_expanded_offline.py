"""Native control probes plus actual loopback model/worker operation under OS rules.

Firewall policy is managed only by scripts/verify_expanded_offline.ps1 with approval.
The llama native downloader requests a public license text, never any photo data.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

from photo_workflow.runtime import ROOT,json_write,local_runtime,sha256
from photo_workflow.native_network import probe,executable

URL='https://raw.githubusercontent.com/ggml-org/llama.cpp/b11193/LICENSE'
PYTHON=ROOT/'.venv/Scripts/python.exe'

def native_controls():
    folder=ROOT/'.cache/offline-probes'/uuid.uuid4().hex;folder.mkdir(parents=True)
    target=folder/'license.gguf'
    # Deliberately turn off application-level offline mode only for this public-file
    # native probe. Successful download must then fail GGUF parsing.
    env={k:v for k,v in os.environ.items() if not k.startswith(('LLAMA_','GGML_','HF_'))}
    cmd=[str(ROOT/'apps/llama/llama-server.exe'),'--model-url',URL,'-m',str(target),
         '--host','127.0.0.1','--port','0','--no-webui','--no-agent']
    try:
        run=subprocess.run(cmd,cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',
                           timeout=25,creationflags=subprocess.CREATE_NO_WINDOW)
        log=run.stdout+run.stderr;code=run.returncode
    except subprocess.TimeoutExpired as e:
        log=str(e);code='timeout'
    (folder/'llama-probe.log').write_text(log,encoding='utf-8')
    license_hash=sha256(ROOT/'docs/assistant-sources/llama-license.txt')
    downloaded=target.exists() and sha256(target)==license_hash
    native=probe();native['executable']=executable()
    return {'python':native,'llama':{'api':'llama.cpp native HTTP downloader','url':URL,
            'connected':downloaded,'exit':code,'log':str(folder/'llama-probe.log')}}

def verify_blocked():
    before=native_controls()
    assert not before['python']['connected'] and not before['llama']['connected'],before
    report=json.loads((ROOT/'outputs/latest-edits-verification.json').read_text())
    from photo_workflow.agent import run
    out=ROOT/'outputs'/('offline-expanded-'+uuid.uuid4().hex[:10])
    # Request differs from the normal test and uses a fresh output directory, so
    # passing requires new local LLM and DRUNet inference rather than cached output.
    folder,evidence=run('Reduce noise moderately and lift exposure by 0.4 stops across the whole image while preserving purple stage lighting.',
                        report['source'],out)
    job=json.loads((folder/'job.json').read_text())
    assert job['runtime']['denoiser']=='DRUNet color' and len(job['layers'])>=2
    # Separate expanded worker verification proves grading, clone and failure handling.
    child=subprocess.run([str(PYTHON),'-m','tests.verify_edits'],cwd=ROOT,capture_output=True,
                         text=True,encoding='utf-8',creationflags=subprocess.CREATE_NO_WINDOW)
    (out/'worker-verification.log').write_text(child.stdout+child.stderr,encoding='utf-8')
    assert child.returncode==0,child.stderr
    worker=json.loads((ROOT/'outputs/latest-edits-verification.json').read_text())
    after=native_controls()
    assert not after['python']['connected'] and not after['llama']['connected'],after
    result={'status':'passed','before':before,'after':after,'loopback_tool_inference':'passed',
            'agent_evidence':str(evidence),'job':str(folder),'actual_worker_checks':worker,
            'requires_rule_scope_and_controls':'latest-expanded-offline-os-verification.json'}
    json_write(ROOT/'outputs/expanded-offline-blocked.json',result)
    print(json.dumps(result,indent=2))

if __name__=='__main__':
    local_runtime()
    parser=argparse.ArgumentParser();parser.add_argument('--control',type=Path);parser.add_argument('--python-only',type=Path);args=parser.parse_args()
    if args.python_only:json_write(args.python_only,dict(probe(),executable=executable()))
    elif args.control:json_write(args.control,native_controls())
    else:verify_blocked()
