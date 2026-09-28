"""Offline setup boundary tests; network responses are deterministic fixtures."""
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from photo_workflow.installation import download

class Response(io.BytesIO):
    status=200
    url='https://fixture.invalid/file'
    headers={}

class SetupTests(unittest.TestCase):
    def test_complete_setup_order_completion_and_failure(self):
        from photo_workflow import installation as setup
        entries={name+'/asset':{'group':name,'bytes':1,'url':'https://fixture.invalid/file','sha256':'0'*64}
                 for name in ('runtime','assistant','photo','legacy','obsidian')}
        events=[];order=[]
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);marker=root/'cancel'
            # All orchestration is real; network, archive and platform boundaries are fixtures.
            (root/'apps/Obsidian').mkdir(parents=True)
            (root/'apps/Obsidian/Obsidian.exe').touch()
            def downloaded(url,target,*args):order.append(target.parent.name)
            with patch.object(setup,'ROOT',root), patch.object(setup,'catalog',return_value=entries), \
                 patch.object(setup.shutil,'disk_usage',return_value=SimpleNamespace(free=10**12)), \
                 patch.object(setup,'download',side_effect=downloaded), patch.object(setup,'extract_llama'), \
                 patch('subprocess.run',return_value=SimpleNamespace(returncode=0)), \
                 patch('subprocess.CREATE_NO_WINDOW',0,create=True), patch('photo_workflow.vault.initialize') as vault:
                result=setup.install('all',events.append,marker)
                self.assertEqual(order,list(setup.COMPLETE_GROUPS))
                self.assertTrue(result['restartRecommended'])
                self.assertEqual([e['group'] for e in events if e['type']=='setup_complete'],['all'])
                self.assertEqual(len([e for e in events if e['type']=='setup_group_complete']),5)
                vault.assert_called()
                events.clear();order.clear()
                def fail(url,target,*args):
                    order.append(target.parent.name)
                    if target.parent.name=='photo':raise ValueError('fixture failure')
                with patch.object(setup,'download',side_effect=fail):
                    with self.assertRaisesRegex(ValueError,'fixture failure'):setup.install('all',events.append,marker)
                self.assertEqual(order,['runtime','assistant','photo'])
                self.assertFalse(any(e['type']=='setup_complete' for e in events))
                events.clear();marker.touch()
                with self.assertRaises(InterruptedError):setup.install('all',events.append,marker)
                self.assertEqual(events,[])

    def test_interruption_resumes_and_preserves_existing(self):
        data=b'original fixture';digest=hashlib.sha256(data).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'model'
            target.write_bytes(b'existing invalid model')
            partial=target.with_name('model.partial');partial.write_bytes(data[:5])
            response=Response(data[5:]);response.status=206;response.headers={'Content-Range':f'bytes 5-{len(data)-1}/{len(data)}'}
            with patch('urllib.request.urlopen',return_value=response) as request:
                download('https://fixture.invalid/file',target,len(data),digest)
                self.assertEqual(request.call_args.args[0].get_header('Range'),'bytes=5-')
            self.assertEqual(target.read_bytes(),data);self.assertFalse(partial.exists())

    def test_hash_failure_does_not_replace_existing(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'model';target.write_bytes(b'existing')
            with patch('urllib.request.urlopen',return_value=Response(b'bad')):
                with self.assertRaisesRegex(ValueError,'integrity'):download('https://fixture.invalid/file',target,3,'0'*64)
            self.assertEqual(target.read_bytes(),b'existing')
            self.assertFalse(target.with_name('model.partial').exists())

    def test_pause_and_ignored_range(self):
        data=b'restart';digest=hashlib.sha256(data).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'model';partial=target.with_name('model.partial');partial.write_bytes(b're')
            with patch('urllib.request.urlopen',return_value=Response(data)):
                download('https://fixture.invalid/file',target,len(data),digest)
            self.assertEqual(target.read_bytes(),data)
            with patch('urllib.request.urlopen',return_value=Response(data)):
                with self.assertRaises(InterruptedError):download('https://fixture.invalid/file',target,len(data),'1'*64,cancelled=lambda:True)
            self.assertEqual(target.read_bytes(),data)

    def test_insecure_url_rejected(self):
        with self.assertRaises(ValueError):download('http://fixture.invalid',Path('unused'),0,'0'*64)

if __name__=='__main__':unittest.main()
