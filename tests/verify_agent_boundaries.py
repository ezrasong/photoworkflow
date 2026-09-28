"""Protocol and real local refusal/endpoint checks; no photo inputs are sent."""
import json
import socket
from unittest.mock import patch

from photo_workflow.runtime import ROOT,local_runtime,json_write

def verify():
    local_runtime()
    from photo_workflow.agent import DEFAULTS,validate_call,server,propose,restrict_controller
    def message(args):return {'tool_calls':[{'type':'function','function':{'name':'edit_photo','arguments':json.dumps(dict(args,scope='whole_image'))}}]}
    assert validate_call(message(DEFAULTS))==DEFAULTS
    for args in (dict(DEFAULTS,shell='whoami'),dict(DEFAULTS,exposure=999),dict(DEFAULTS,denoise=True),
                 dict(DEFAULTS,exposure=float('nan')),dict(DEFAULTS,grade_mask='any path')):
        try:validate_call(message(args));raise AssertionError('Unsafe recipe accepted')
        except ValueError:pass
    import requests
    with server() as (session,url,process):
        anonymous=requests.Session();anonymous.trust_env=False
        assert anonymous.get(url+'/props',timeout=3).status_code==401
        assert session.get(url+'/cors-proxy',timeout=3).status_code==403
        props=session.get(url+'/props',timeout=3);props.raise_for_status()
        assert session.get(url+'/health',timeout=3).ok
        assert '127.0.0.1' in url
        anonymous.close()
    assert process.poll() is not None
    refusals=[]
    for request in ('Describe the person and identify them from the photograph.',
                    'Brighten only the performer, leave the background untouched.'):
        try:propose(request);raise AssertionError('Unsupported request was executed: '+request)
        except ValueError as error:refusals.append(str(error))
    restrict_controller()
    try:socket.create_connection(('1.1.1.1',443),timeout=.2);raise AssertionError('External Python socket allowed')
    except PermissionError:pass
    result={'status':'passed','checks':['invalid tool arguments rejected','unknown fields and paths rejected',
        'finite bounds enforced','loopback endpoint with authentication','MCP proxy disabled','owned server stopped',
        'real model refuses vision and subject edit without mask','controller rejects external Python sockets'],
        'refusal_messages':refusals,'native_isolation':'requires Windows Firewall verification'}
    json_write(ROOT/'outputs/agent-boundaries-verification.json',result);print(json.dumps(result,indent=2))

if __name__=='__main__':verify()
