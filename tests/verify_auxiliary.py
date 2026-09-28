"""Local metadata and disabled web-retrieval boundary checks; no HTTP requests."""
import importlib.util
import json
from pathlib import Path
import tempfile

from photo_workflow.references import subject_context, write_review
from photo_workflow.runtime import ROOT

def verify():
    with tempfile.TemporaryDirectory(dir=ROOT / '.cache') as directory:
        folder = Path(directory)
        (folder / 'person.md').write_text('---\nname: Explicit person\nage: 40\n---\nPrivate local note', encoding='utf-8')
        (folder / 'reference.jpg').write_bytes(b'Only a link; not passed to inference')
        config = {'subjects': {'person': {'reference_folder': str(folder), 'note': str(folder / 'person.md')}}}
        (folder / 'config.json').write_text(json.dumps(config), encoding='utf-8')
        context = subject_context(folder / 'config.json', 'person')
        assert context['metadata']['name'] == 'Explicit person'
        assert len(context['references']) == 1
        write_review(folder, context)
        html = (folder / 'review.html').read_text(encoding='utf-8')
        assert 'file:///' in html and 'https://' not in html
        try:
            subject_context(folder / 'config.json', 'unmapped')
            raise AssertionError('Unknown subject accepted')
        except ValueError:
            pass
    spec = importlib.util.spec_from_file_location('fetch_references', ROOT / 'scripts/fetch_references.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    for url, domains in [('http://example.com/photo.png', {'example.com'}),
                         ('https://example.com/photo.png', set()),
                         ('https://127.0.0.1/photo.png', {'127.0.0.1'}),
                         ('https://user:pass@example.com/photo.png', {'example.com'})]:
        try:
            module.fetch(url, domains)
            raise AssertionError('Unsafe URL accepted')
        except ValueError:
            pass
    print('PASS explicit subject mapping, local note/link review, HTTP/domain/credential/private-IP rejection')

if __name__ == '__main__':
    verify()
