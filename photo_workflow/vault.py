"""Explicit local person mappings and a dedicated, unsynced Obsidian vault."""
import hashlib
import json
import re
import time
from pathlib import Path

from .runtime import ROOT, json_write

VAULT = ROOT / 'Photo Vault'
CONFIG = ROOT / 'config.json'

def open_obsidian():
    import subprocess
    initialize()
    app = ROOT / 'apps/Obsidian/Obsidian.exe'
    if not app.is_file():
        raise RuntimeError('Install Obsidian from desktop Setup first. Existing vault notes are preserved.')
    return subprocess.Popen([str(app), '--user-data-dir=' + str(ROOT / 'apps/ObsidianData'),
                             '--disable-background-networking'], cwd=ROOT)

def initialize():
    for folder in (VAULT / '.obsidian', VAULT / 'People', VAULT / 'References', VAULT / 'Templates'):
        folder.mkdir(parents=True, exist_ok=True)
    files = {
        VAULT / 'Start here.md': '''# Photo restoration\n\nUse **Launch Luma Atelier.cmd** in the project folder to restore photos.\n\n1. Click **Add person** in the control panel to make a note and reference folder.\n2. Add reference photos only to that person's folder under References.\n3. Select that person when processing a photo. This is your explicit mapping, not recognition.\n4. Review comparison images locally and export the job to Photoshop.\n\nThe pipeline reads person-note frontmatter and links notes/references for human comparison. The separate chat reads only notes explicitly selected with /notes into the local Qwen model; see [[Chat with the local assistant]]. No Sync, Publish, community plugin, automatic web search or account is configured.\n\n[[Models and workflow]]\n''',
        VAULT / 'Models and workflow.md': '''# Models and workflow\n\n- GFPGAN v1.4: face restoration.\n- Real-ESRGAN x4plus: optional 2×/4× background upscale.\n- RetinaFace ResNet50: face detection and alignment.\n- ParseNet: editable semantic face masks.\n\nAll four weights are installed and checksummed in ../models. These are all the models needed by the selected workflow. The research report's CodeFormer, RestoreFormer, GPEN, ComfyUI and cloud agents are alternatives, not prerequisites.\n\nOutputs default to 16-bit sRGB TIFF and layered 16-bit PSD. Models use float32 inference; they were not trained to guarantee 16-bit photographic truth. Detection uses an 8-bit view. Original bytes are always retained.\n\nThe Python pipeline is the local orchestration harness. Its desktop control panel starts jobs, selects subject mappings, cancels work and exports Photoshop layers. Web reference retrieval is separate and disabled by default.\n''',
        VAULT / 'Templates/Person.md': '''---\nname: Replace with the person's name\nallow_web_search: false\n---\n\n# Person\n\nAdd human observations here. Use Add person in the control panel to register a mapping and reference folder. Do not assume this note conditions the restoration model.\n''',
    }
    for path, content in files.items():
        if not path.exists():
            path.write_text(content, encoding='utf-8')
    defaults = {VAULT / '.obsidian/app.json': {'alwaysUpdateLinks': True, 'attachmentFolderPath': 'References'},
        VAULT / '.obsidian/core-plugins.json': ['file-explorer', 'global-search', 'backlink', 'outgoing-link', 'tag-pane', 'page-preview', 'templates', 'properties'],
        VAULT / '.obsidian/community-plugins.json': [],
        VAULT / '.obsidian/templates.json': {'folder': 'Templates'}}
    for path, data in defaults.items():
        if not path.exists():
            json_write(path, data)
    if not CONFIG.exists():
        json_write(CONFIG, {'subjects': {}})
    profile = ROOT / 'apps/ObsidianData'; profile.mkdir(parents=True, exist_ok=True)
    settings = profile / 'obsidian.json'
    if not settings.exists():
        vault_id = hashlib.sha256(str(VAULT).encode()).hexdigest()[:16]
        json_write(settings, {'updateDisabled': True, 'vaults': {vault_id: {'path': str(VAULT), 'ts': int(time.time()*1000), 'open': True}}})
    else:
        current = json.loads(settings.read_text(encoding='utf-8'))
        if 'updateDisabled' not in current:
            current['updateDisabled'] = True
            json_write(settings, current)
    return VAULT

def add_person(name):
    import yaml
    name = name.strip()
    if not name or len(name) > 120 or any(ord(c) < 32 for c in name):
        raise ValueError('Enter a name of 1–120 printable characters')
    initialize()
    key = re.sub(r'[^a-z0-9-]', '-', name.lower()).strip('-')[:60] or 'person'
    key += '-' + hashlib.sha256(name.encode()).hexdigest()[:6]
    note = VAULT / 'People' / (key + '.md')
    references = VAULT / 'References' / key
    settings = json.loads(CONFIG.read_text(encoding='utf-8'))
    if key not in settings['subjects']:
        references.mkdir(exist_ok=True)
        if not note.exists():
            note.write_text('---\n' + yaml.safe_dump({'name': name, 'allow_web_search': False}, allow_unicode=True) +
                '---\n\n# ' + name + '\n\nAdd notes for human review here.\n', encoding='utf-8')
        settings['subjects'][key] = {'name': name, 'reference_folder': str(references), 'note': str(note)}
        json_write(CONFIG, settings)
    return key


def save_reference(source):
    """Archive an explicitly chosen reference, with an immutable new note/attachment."""
    import shutil
    import uuid
    from urllib.parse import urlsplit
    from .references import local_path
    from .imaging import stable_read, decode_working
    source = local_path(source)
    if not source.is_file() or source.suffix.lower() not in {'.jpg', '.jpeg', '.png', '.tif', '.tiff'}:
        raise ValueError('Select an existing reference photo')
    if source.stat().st_size > 20 * 1024**2:
        raise ValueError('Vault references must be at most 20 MiB')
    data = stable_read(source, settle=0)
    if len(data) > 20 * 1024**2:raise ValueError('Vault reference grew beyond 20 MiB')
    decode_working(data)  # Same bounded decoder used for photo inspection.
    digest = hashlib.sha256(data).hexdigest()
    metadata = {'sha256':digest, 'local_source':str(source), 'bytes':len(data)}
    provenance = source.parent/'provenance.json'
    if source.is_relative_to((ROOT/'references/web').resolve()) and provenance.is_file():
        if provenance.stat().st_size > 64000:raise ValueError('Reference provenance is too large')
        metadata = json.loads(provenance.read_text(encoding='utf-8'))
        if not isinstance(metadata, dict) or metadata.get('sha256') != digest or metadata.get('file') != source.name:
            raise ValueError('Reference no longer matches its downloaded provenance')
    initialize()
    folder = VAULT/'References'/'Collected'
    if not folder.resolve().is_relative_to(VAULT.resolve()):raise ValueError('Invalid vault reference folder')
    folder.mkdir(parents=True, exist_ok=True)
    identity = uuid.uuid4().hex
    temporary, destination = folder/('.partial-'+identity), folder/identity
    temporary.mkdir()
    def text(value):
        # Provider metadata is inert text, never an Obsidian embed, HTML or instruction.
        return re.sub(r'([\\`*_{}\[\]()<>!#|])', r'\\\1', str(value).replace('\r',' ').replace('\n',' '))[:2000]
    try:
        filename = 'reference'+source.suffix.lower()
        (temporary/filename).write_bytes(data)
        json_write(temporary/'provenance.json', metadata)
        lines = ['# Saved photo reference', '', '![[References/Collected/'+identity+'/'+filename+']]', '',
                 'For visual comparison and planning. This is not evidence of missing detail in another photo.', '',
                 'SHA-256: `'+digest+'`', '', '## Source details', '']
        for key in ('title', 'artist', 'credit', 'license', 'query', 'retrieved_utc', 'local_source'):
            if metadata.get(key):lines.append('- '+key.replace('_',' ')+': '+text(metadata[key]))
        for key in ('source_page', 'original_url', 'license_url'):
            value = metadata.get(key)
            if not isinstance(value, str):continue
            try:
                url = urlsplit(value)
                valid = url.scheme == 'https' and url.hostname in {'commons.wikimedia.org','upload.wikimedia.org','creativecommons.org'} and not url.username and not url.password and url.port in (None,443)
            except ValueError:valid = False
            if valid and not any(c in value for c in '<>\r\n'):
                lines.append('- '+key.replace('_',' ')+': <'+value+'>')
        if not metadata.get('license'):lines.append('- License: unknown; verify before reuse.')
        (temporary/'Reference.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
        temporary.rename(destination)
        return destination/'Reference.md'
    finally:
        if temporary.exists():shutil.rmtree(temporary)
