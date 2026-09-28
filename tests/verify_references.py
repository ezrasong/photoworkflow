"""Public-only retrieval plus destination and private-address boundaries."""
import json
import socket
import tkinter as tk
from unittest.mock import patch

from photo_workflow.public_references import fetch,search,download
from photo_workflow.runtime import ROOT,json_write,sha256


def rejects(fn):
    try:fn()
    except ValueError:return
    raise AssertionError('Unsafe input accepted')


def verify():
    rejects(lambda:fetch('http://commons.wikimedia.org/',{'commons.wikimedia.org'},as_json=True))
    rejects(lambda:fetch('https://127.0.0.1/',{'commons.wikimedia.org'},as_json=True))
    rejects(lambda:fetch('https://user:password@commons.wikimedia.org/',{'commons.wikimedia.org'},as_json=True))
    with patch.object(socket,'getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]):
        rejects(lambda:fetch('https://commons.wikimedia.org/',{'commons.wikimedia.org'},as_json=True))
    rejects(lambda:search('x'*201));rejects(lambda:search(''))
    items=search('snowy mountain landscape photograph');assert items
    path=download(items[0],'snowy mountain landscape photograph')
    provenance=json.loads((path.parent/'provenance.json').read_text())
    assert sha256(path)==provenance['sha256'] and provenance['source_page'] and provenance['license']
    from photo_workflow.reference_browser import Browser
    # Prove an LLM-suggested query does not automatically submit when the UI opens.
    root=tk.Tk();root.withdraw();target=ROOT/'.cache/control/reference-ui-test.json'
    with patch('photo_workflow.reference_browser.search',side_effect=AssertionError('Automatic query submission')):
        ui=Browser(root,target,'private example that must not be sent');root.withdraw();root.update()
        ui.selected=[str(path)];ui.done()
    assert json.loads(target.read_text())==[str(path)];target.unlink()
    json_write(ROOT/'outputs/latest-reference-verification.json',{'status':'passed','provider':'Wikimedia Commons',
        'explicit_query':'snowy mountain landscape photograph','selected':str(path),'provenance':provenance,
        'no_automatic_submission':True,'private_address_rejection':True,'local_photo_or_note_uploaded':False})
    print('Passed live public search/download/provenance and query/privacy boundaries.')


if __name__=='__main__':verify()
