import html
import json
from pathlib import Path

from .imaging import EXTENSIONS

def local_path(value):
    path = Path(value).resolve()
    if str(path).startswith('\\\\'):
        raise ValueError('Network paths are not supported; use local files')
    return path

def subject_context(config, subject):
    if not subject:
        return None
    if not config:
        raise ValueError('--subject requires --config with an explicit subject mapping')
    settings = json.loads(local_path(config).read_text(encoding='utf-8-sig'))
    entry = settings.get('subjects', {}).get(subject)
    if not entry:
        raise ValueError('Subject is absent from explicit configuration mapping')
    result = {'subject': subject, 'references': []}
    if entry.get('reference_folder'):
        folder = local_path(entry['reference_folder'])
        if not folder.is_dir():
            raise ValueError('Reference folder does not exist')
        result['references'] = [str(x.resolve()) for x in sorted(folder.iterdir())
                                if x.is_file() and x.suffix.lower() in EXTENSIONS]
    if entry.get('note'):
        import yaml
        note = local_path(entry['note'])
        text = note.read_text(encoding='utf-8-sig')
        metadata = {}
        if text.startswith('---\n'):
            parts = text.split('---', 2)
            if len(parts) == 3:
                metadata = yaml.safe_load(parts[1]) or {}
        if not isinstance(metadata, dict):
            raise ValueError('Person-note frontmatter must be a mapping')
        result['note'] = str(note)
        result['metadata'] = metadata
    # Ensure only JSON-safe YAML values; notes remain local and never enter inference.
    return json.loads(json.dumps(result, default=str))

def write_review(folder, context):
    text = '<!doctype html><meta charset="utf-8"><title>Local photo review</title>'
    text += '<h1>Local photo review</h1><p>Left: original baseline. Right: composite. '
    text += 'Generated detail is an estimate; identity preservation is not guaranteed.</p>'
    if (folder / 'recipe.json').exists():
        text += '<p>Color/tone and denoise are separate masked raster layers, with settings in recipe.json. '
        text += 'Later raster layers include earlier visible edits; change the recipe and rerun to recompute the stack. '
        text += 'Clone removal copies a user-selected donor area. It does not recover hidden content.</p>'
    text += '<img style="max-width:100%" src="comparison.jpg"><h2>Human reference comparison</h2>'
    text += '<p>References and notes are never used by GFPGAN or Real-ESRGAN.</p>'
    if context:
        text += '<pre>' + html.escape(json.dumps(context.get('metadata', {}), indent=2)) + '</pre>'
        if context.get('note'):
            text += '<p><a href="' + html.escape(Path(context['note']).as_uri(), quote=True) + '">Person note</a></p>'
        for ref in context['references']:
            text += '<p><a href="' + html.escape(Path(ref).as_uri(), quote=True) + '">' + html.escape(Path(ref).name) + '</a></p>'
    (folder / 'review.html').write_text(text, encoding='utf-8')
