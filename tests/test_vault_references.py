import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from photo_workflow import vault


class VaultReferenceTests(unittest.TestCase):
    def test_archive_provenance_and_preserve_existing_notes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            source=root/'references/web/fixture/reference.png'
            source.parent.mkdir(parents=True)
            Image.new('RGB',(12,12),(100,120,140)).save(source)
            original=source.read_bytes()
            metadata={'file':source.name,'sha256':hashlib.sha256(original).hexdigest(),
                      'title':'<script>bad</script> ![[private]]', 'license':'CC BY-SA 4.0',
                      'source_page':'https://commons.wikimedia.org/wiki/File:Fixture.png',
                      'license_url':'javascript:alert(1)', 'query':'public landscape'}
            sidecar=source.parent/'provenance.json'
            sidecar.write_text(json.dumps(metadata))
            with patch.object(vault,'ROOT',root),patch.object(vault,'VAULT',root/'Photo Vault'),patch.object(vault,'CONFIG',root/'config.json'):
                vault.initialize()
                existing=root/'Photo Vault/Start here.md';existing.write_text('User notes')
                note=vault.save_reference(source)
                content=note.read_text(encoding='utf-8')
                self.assertIn(metadata['source_page'],content)
                self.assertIn('CC BY-SA 4.0',content)
                self.assertNotIn('<script>',content)
                self.assertNotIn('![[private]]',content)
                self.assertNotIn('javascript:',content)
                self.assertEqual((note.parent/'reference.png').read_bytes(),original)
                self.assertEqual(json.loads((note.parent/'provenance.json').read_text()),metadata)
                second=vault.save_reference(source)
                self.assertNotEqual(note,second)
                self.assertEqual(note.read_text(encoding='utf-8'),content)
                self.assertEqual(existing.read_text(),'User notes')
                self.assertEqual(source.read_bytes(),original)
                metadata['sha256']='0'*64;sidecar.write_text(json.dumps(metadata))
                with self.assertRaisesRegex(ValueError,'provenance'):vault.save_reference(source)
                self.assertFalse(list(note.parent.parent.glob('.partial-*')))

    def test_local_reference_without_license(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'photo.png'
            Image.new('RGB',(8,8)).save(source)
            with patch.object(vault,'ROOT',root),patch.object(vault,'VAULT',root/'Photo Vault'),patch.object(vault,'CONFIG',root/'config.json'):
                note=vault.save_reference(source)
                self.assertIn('License: unknown',note.read_text(encoding='utf-8'))


if __name__=='__main__':unittest.main()
