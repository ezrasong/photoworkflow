import json
import sys
from pathlib import Path
from photo_workflow.native_network import probe,executable
from photo_workflow.runtime import ROOT,json_write

def main():
    connection=probe()
    connection['executable']=executable()
    if '--probe-only' in sys.argv:
        print(json.dumps(connection)); return 0 if connection['connected'] else 1
    if connection['connected']:
        raise RuntimeError('Native network still works: OS isolation has NOT been verified')
    from tests.verify_precision import verify
    report=verify()
    # Repeat native call after Python restrictions and actual inference to ensure
    # the result is not just the Python audit hook or a pre-start condition.
    after=probe()
    if after['connected']: raise RuntimeError('Native network became reachable during inference')
    report['network']={'status':'native egress blocked during actual CUDA run', 'before':connection,'after':after,
                       'requires_control_and_rule_evidence':'outputs/latest-offline-os-verification.json'}
    json_write(ROOT/'outputs/latest-precision-verification.json',report)
    json_write(Path(report['actual_gpu_inference'][0]['job']).parent/'verification.json',report)
    return 0

if __name__=='__main__': sys.exit(main())
