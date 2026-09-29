import json
import threading
import unittest
import urllib.request
from pathlib import Path
import tempfile
from contextlib import ExitStack, nullcontext
from unittest.mock import Mock, patch
from photo_workflow.prompt_master import validate_rewrite, suggest


class PromptMasterTests(unittest.TestCase):
    def test_selected_photo_inspection_and_retry(self):
        from photo_workflow.prompt_chat import PromptWorkspace
        from photo_workflow import lightroom
        from photo_workflow.desktop import Desktop
        valid={'summary':'Visible shadow noise.', 'prompts':['Reduce shadow noise gently.']}
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root=Path(directory).resolve()
            source=root/'intended.arw'; source.write_bytes(b'original fixture')
            raster=root/'intended.png'; raster.write_bytes(b'raster fixture')
            queue=root/'queue'; queue.mkdir()
            preview=queue/'render.tif'; preview.touch()
            workspace=PromptWorkspace()
            stack.enter_context(patch.object(lightroom,'QUEUE',queue))
            stack.enter_context(patch('photo_workflow.desktop.ROOT',root))
            stack.enter_context(patch('photo_workflow.prompt_chat.ROOT',root))
            stack.enter_context(patch('photo_workflow.native_batch.connect_lightroom',return_value={'catalog':'fixture-catalog'}))
            stack.enter_context(patch('photo_workflow.pipeline.job_lock',return_value=nullcontext()))
            inspection=stack.enter_context(patch('photo_workflow.vision.inspect',return_value={
                'observations':json.dumps(valid),'backend':'fixture'}))
            bridge=stack.enter_context(patch.object(lightroom,'request'))
            desktop=Desktop.__new__(Desktop)
            desktop.guard=threading.Lock(); desktop.busy=False; desktop.cancel_file=None
            desktop.workspace=workspace; desktop.broker=Mock(inference_lock=threading.Lock())
            desktop.record=Mock()

            with self.assertRaisesRegex(ValueError,'Choose a photo'):
                desktop.dispatch('suggest',{})
            source_folder=root/'photos'; source_folder.mkdir()
            (source_folder/'one.png').touch(); (source_folder/'two.png').touch()
            workspace.select_source(source_folder)
            with self.assertRaisesRegex(ValueError,'Choose one existing photo'):
                desktop.dispatch('suggest',{})
            self.assertFalse(desktop.busy); self.assertIsNone(desktop.cancel_file)
            bridge.assert_not_called(); inspection.assert_not_called()

            # Raster selection never consults unrelated Lightroom targets.
            workspace.select_source(raster)
            self.assertEqual(desktop.dispatch('suggest',{})['source'],str(raster))
            self.assertEqual(inspection.call_args.args[0],[('SOURCE photograph',raster)])
            bridge.assert_not_called()
            raster.unlink()
            with self.assertRaisesRegex(ValueError,'Choose one existing photo'):
                desktop.dispatch('suggest',{})

            workspace.select_source(source)
            for error in ('No photo selected in Lightroom. Select the intended photo, then retry.',
                          'Select exactly one photo in Lightroom, then retry.',
                          'Selection or catalog changed; read selection again'):
                bridge.side_effect=[{'selection':'fixture-token'},RuntimeError(error)]
                count=inspection.call_count
                with self.assertRaisesRegex(RuntimeError,error):
                    desktop.dispatch('suggest',{})
                self.assertEqual(inspection.call_count,count)
                self.assertIsNone(workspace.source)
                self.assertFalse(desktop.busy); self.assertIsNone(desktop.cancel_file)
            # Explicit retry reimports the intended app source and uses the fresh token/catalog.
            bridge.reset_mock()
            bridge.side_effect=[{'selection':'fresh-token'},{'path':str(preview)}]
            result=desktop.dispatch('suggest',{})
            self.assertEqual(result['prompts'],valid['prompts'])
            self.assertEqual(result['source'],str(source))
            self.assertEqual([call.args[0] for call in bridge.call_args_list],['import_photo','export'])
            self.assertEqual(bridge.call_args_list[0].kwargs['source'],source)
            self.assertEqual(bridge.call_args_list[1].args,('export','fresh-token'))
            self.assertTrue(all(call.kwargs['catalog']=='fixture-catalog' for call in bridge.call_args_list))
            self.assertEqual(inspection.call_args.args[0],[('SOURCE photograph',preview)])
            self.assertFalse(desktop.busy); self.assertIsNone(desktop.cancel_file)
            self.assertEqual(source.read_bytes(),b'original fixture')
            self.assertIsNone(workspace.job)
            self.assertEqual(desktop.record.call_args.args[0]['type'],'prompt_suggestions')

    def test_suggestions_inspect_only_and_validate_model_output(self):
        valid={'summary':'Slight shadow noise; texture is visible.', 'prompts':['Reduce shadow noise gently; preserve texture.']}
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'photo.png'; source.touch()
            workspace=Mock(selected_input=source)
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
