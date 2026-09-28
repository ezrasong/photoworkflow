import json
import threading
import unittest
import urllib.request
from pathlib import Path
import tempfile
from unittest.mock import Mock
from photo_workflow.prompt_master import validate_rewrite, suggest


class PromptMasterTests(unittest.TestCase):
    def test_suggestions_inspect_only_and_validate_model_output(self):
        workspace=Mock(selected_input=Path('photo.png'))
        valid={'summary':'Slight shadow noise; texture is visible.', 'prompts':['Reduce shadow noise gently; preserve texture.']}
        with tempfile.TemporaryDirectory() as directory:
            marker=Path(directory)/'cancel'
            workspace.call.return_value={'observations':json.dumps(valid),'backend':'local-fixture'}
            result=suggest(workspace,threading.Lock(),marker)
            self.assertEqual(result['prompts'],valid['prompts'])
            workspace.call.assert_called_once()
            self.assertEqual(workspace.call.call_args.args[0],'inspect_photo')
            self.assertEqual(workspace.call.call_args.args[1]['view'],'source')
            self.assertEqual(workspace.call.call_args.args[1]['path'],'')
            for body in ('not json', '[]', json.dumps({**valid,'prompts':['/edit']}), json.dumps({**valid,'prompts':[]})):
                workspace.call.return_value={'observations':body,'backend':'local-fixture'}
                with self.assertRaisesRegex(ValueError,'invalid suggestions'):suggest(workspace,threading.Lock(),marker)
            marker.touch()
            with self.assertRaises(InterruptedError):suggest(workspace,threading.Lock(),marker)

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
