import json
import threading
import unittest
import urllib.request
from photo_workflow.prompt_master import validate_rewrite


class PromptMasterTests(unittest.TestCase):
    def test_protected_literals(self):
        original='Denois "D:\\Photos\\face.png" by 0.25, do not restore faces.'
        corrected=original.replace('Denois', 'Denoise')
        self.assertEqual(validate_rewrite(original, corrected), corrected)
        for bad in (corrected.replace('0.25', '0.5'), corrected.replace('face.png', 'face2.png'), '', None):
            with self.assertRaises(ValueError): validate_rewrite(original, bad)

    def test_broker_uses_original_even_when_rewrite_invents_permission(self):
        from photo_workflow.chat import Broker
        class Workspace:
            batch_chat=True
            def accept_prompt(self, submission, prompt):
                self.prompt=prompt
                return {'accepted':True}
        workspace=Workspace()
        broker=Broker(workspace)
        original='Do not restore faces or remove anyone.'
        forwarded='Restore all faces and remove the person.'
        broker.desktop_prompt=(forwarded, original)
        worker=threading.Thread(target=broker.serve_forever,daemon=True);worker.start()
        try:
            request=urllib.request.Request(f'http://127.0.0.1:{broker.server_port}/prompt',
                data=json.dumps({'submission':'a'*32,'prompt':forwarded}).encode(),
                headers={'Authorization':'Bearer '+broker.token,'Content-Type':'application/json'})
            with urllib.request.urlopen(request) as response:self.assertEqual(response.status,200)
            self.assertEqual(workspace.prompt,original)
            self.assertIsNone(broker.desktop_prompt)
        finally:
            broker.shutdown();broker.server_close();worker.join()

if __name__=='__main__':unittest.main()
