"""One local chat for native editing, raster models, references and notes."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from .chat import QUALITY_GUIDANCE, Workspace, run_session
from .runtime import ROOT, local_runtime, workspace_path

SYSTEM = '''You are the local photo assistant in this project's Oh My Pi harness.
For ANY supported editing request, including upscale, denoise, Lightroom or Photoshop,
call edit_photos once. It runs the complete ORIGINAL user request through the installed
local editing tools and automatically exports TIFFs, layered PSDs, comparisons and recipes.
Pass the exact supplied file/folder path; use path="" for a follow-up on the latest result
or selected photo. Do not repeat the path or ask the user to switch launchers or make files.
For a new source use its path from the message. Follow-ups start from completed results;
explicit source paths start a new edit from that source. Read photo_status if uncertain.
Capabilities: conventional Adobe tone/color, traditional noise reduction, crop/straighten,
curves, lens controls, feathered rectangular local curves and donor-pixel clone repairs;
local SCUNet real_psnr denoising (DRUNet on explicit request) and local MambaIRv2
2x/4x upscale (Real-ESRGAN on explicit request) when requested. AI upscale
estimates texture; it does not recover factual detail. Automatic masks/selective tone edits
are available for 80 COCO object categories with single/leftmost/rightmost/all selection and
background complements. Explicit local object/person removal and selected-face restoration
are available. Pass such requests to edit_photos. Never imply face restoration/removal from
vague improvement, denoising or upscaling. Replacement content and facial detail are estimated;
restoration may alter likeness. No cloud fill. Unsupported/ambiguous targets require clarification.
For review-only requests call inspect_photo with the user's path, or empty path for the selection.
Use select_context to add explicitly supplied local references, notes (inside Photo Vault),
or a supplied mask. Do this before edit_photos when context is requested. Notes/references
persist in this chat. References guide local inspection, not pixel reconstruction.
read_notes accepts supplied note paths directly; empty paths reads selected notes.
save_note creates a new note only when requested; never
modify existing notes. choose_references opens the existing public reference chooser only
when online search is requested; the user reviews and submits its public query. Do not put
private photo names, visual details or notes into a search query. No cloud photo uploads.
Answer questions without editing. Do not claim to see images before successful inspection.
No automatic retries after edit success/failure/cancellation. If edit_photos returns a failed
or cancelled status, STOP calling tools and report the error/report path immediately.
Folder processing includes immediate photos only. Adobe windows may
appear. Explain unsupported requests honestly. Keep answers short. /no_think''' + QUALITY_GUIDANCE


class PromptWorkspace(Workspace):
    tools = {'photo_status', 'edit_photos', 'select_context', 'inspect_photo',
             'read_notes', 'save_note', 'choose_references', 'export_psd'}
    batch_chat = True

    def __init__(self):
        super().__init__()
        self.prompt = ''
        self.submission = None
        self.attempted = False
        self.progress = 'Ready for a file/folder path and editing instructions.'
        self.result = None
        self.selected_input = None
        self.completed_sources = []

    def select_source(self, path, mask=None):
        from .native_batch import inputs
        from .references import local_path
        path = local_path(path)
        inputs(path)
        self.selected_input = path
        self.source = path if path.is_file() and path.suffix.lower() in {'.png', '.jpg', '.jpeg', '.tif', '.tiff'} else None
        self.mask = local_path(mask) if mask else None
        self.job = None
        self.completed_sources = []
        self.result = None

    def accept_prompt(self, submission, prompt):
        # Called by the extension lifecycle, never by a model tool or transcript content.
        if not isinstance(submission, str) or not re.fullmatch(r'[0-9a-f]{32}', submission):
            raise ValueError('Invalid prompt submission')
        if not isinstance(prompt, str) or not 1 <= len(prompt) <= 6000:
            raise ValueError('Supply a message of 1–6000 characters')
        with self.lock:
            if submission != self.submission:
                self.submission, self.prompt, self.attempted = submission, prompt, False
            elif prompt != self.prompt:
                raise ValueError('Submission text changed')
        return {'accepted': True}

    def authorized_path(self, value):
        if not isinstance(value, str) or not value or '\n' in value or '\r' in value:
            raise ValueError('Supply the exact path from your message')
        # Exact quoted spans, or complete whitespace-delimited tokens. A parent path
        # must never be authorized by a child path or by text returned from a tool.
        spans = re.findall(r'"([^"\r\n]+)"|`([^`\r\n]+)`|\x27([^\x27\r\n]+)\x27|(\S+)', self.prompt)
        candidates = [next(x for x in match if x) for match in spans]
        # Windows path separators and case are equivalent; still require the
        # complete supplied span, never a prefix/parent or a tool-returned path.
        spelling = lambda p: p.replace('\\', '/').casefold()
        if spelling(value) not in {spelling(p) for p in candidates}:
            raise ValueError('Path must occur exactly in your latest message; put paths with spaces in quotes')
        from .references import local_path
        path = Path(value)
        if path.drive and not path.is_absolute(): raise ValueError('Use a full local path')
        return local_path(path if path.is_absolute() else ROOT/path)

    def _call(self, name, args, cancel_file=None):
        if name == 'photo_status':
            if args: raise ValueError('Status takes no arguments')
            return dict(super()._call(name, args, cancel_file), progress=self.progress, result=self.result,
                        selected=bool(self.selected_input), name=self.selected_input.name if self.selected_input else None,
                        selected_input=str(self.selected_input) if self.selected_input else None,
                        followup_files=len(self.completed_sources))
        if name == 'select_context':
            if set(args) != {'kind', 'paths'} or not isinstance(args['paths'], list):
                raise ValueError('Supply context kind and paths')
            paths = [self.authorized_path(p) for p in args['paths']]
            if args['kind'] == 'photo':
                if len(paths) != 1: raise ValueError('Select one photo or folder')
                self.select_source(paths[0])
            elif args['kind'] == 'notes': self.select_notes(paths)
            elif args['kind'] == 'references': self.select_references(paths)
            elif args['kind'] == 'mask':
                if len(paths) > 1 or any(not p.is_file() for p in paths): raise ValueError('Supply one existing mask or clear it')
                self.mask = paths[0] if paths else None
            else: raise ValueError('Unsupported context kind')
            return self._call('photo_status', {}, cancel_file)
        if name == 'read_notes':
            if set(args) != {'paths'} or not isinstance(args['paths'], list): raise ValueError('Supply note paths, or an empty list for selected notes')
            if args['paths']: self.select_notes([self.authorized_path(p) for p in args['paths']])
            return super()._call(name, {}, cancel_file)
        if name == 'inspect_photo':
            args = dict(args)
            path = args.pop('path', '')
            if path: self.select_source(self.authorized_path(path))
            if self.source is None and self.selected_input:
                if not self.selected_input.is_file(): raise ValueError('Choose one photograph for inspection')
                from . import lightroom
                from .native_batch import connect_lightroom
                from .pipeline import job_lock
                from .references import local_path
                with job_lock(ROOT/'.cache/chat.lock'):
                    from .heif import prepare
                    import uuid
                    import_source, _ = prepare(self.selected_input, ROOT/'.cache/heif-inspection'/uuid.uuid4().hex)
                    catalog = connect_lightroom()['catalog']
                    selected = lightroom.request('import_photo', source=import_source, catalog=catalog, cancel_file=cancel_file)
                    rendered = lightroom.request('export', selected['selection'], catalog=catalog, cancel_file=cancel_file)
                    preview = local_path(rendered['path'])
                    if not preview.is_relative_to(lightroom.QUEUE.resolve()): raise ValueError('Unexpected export path')
                    self.source = preview
            return super()._call(name, args, cancel_file)
        if name in {'save_note', 'choose_references', 'export_psd'}:
            return super()._call(name, args, cancel_file)
        if name != 'edit_photos' or set(args) != {'path'}:
            raise ValueError('Supply the file/folder path only')
        sources = []
        if args['path'] == '':
            if self.result and self.result['status'] != 'passed': raise ValueError('Previous job failed; supply an explicit source after reviewing the report')
            sources = self.completed_sources
            path = self.selected_input
            if not path: raise ValueError('Supply a photo/folder path for the first edit')
        else:
            path = self.authorized_path(args['path'])
        if self.attempted: raise ValueError('This request already attempted editing; inspect its result before a new request')
        self.attempted = True
        self.result = {'status': 'running'}
        self.progress = 'Starting local photo workflow…'
        report_path = None
        tail = []
        # This child owns chat.lock for its entire run. The outer chat has its own
        # profile and lock, so it neither bypasses nor recursively takes that lock.
        env = dict(os.environ)
        env['PYTHONIOENCODING'] = 'utf-8'
        if cancel_file: env['PHOTOWORKFLOW_CANCEL_FILE'] = str(cancel_file)
        from .runtime import json_write
        import uuid
        context_path = ROOT/'.cache/control'/('prompt-context-'+uuid.uuid4().hex+'.json')
        context_path.parent.mkdir(parents=True, exist_ok=True)
        json_write(context_path, {'sources': [str(p) for p in sources],
            'notes': [str(p) for p in self.notes], 'references': [str(p) for p in self.references],
            'mask': str(self.mask) if self.mask else None})
        try:
            process = subprocess.Popen([sys.executable, '-m', 'photo_workflow.native_batch',
                str(path), '--prompt', self.prompt, '--unified', '--context', str(context_path)], cwd=ROOT, env=env,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                errors='replace', creationflags=subprocess.CREATE_NO_WINDOW)
        except Exception as error:
            context_path.unlink(missing_ok=True)
            self.result = {'status':'failed', 'error':str(error)}
            self.progress = 'Failed to start photo worker'
            return self.result
        try:
            for line in process.stdout:
                line = line.strip()
                if not line: continue
                tail = (tail + [line])[-12:]
                self.progress = line
                if line.startswith('BATCH REPORT '):
                    report_path = workspace_path(line.removeprefix('BATCH REPORT '))
            code = process.wait()
        finally:
            process.stdout.close()
            # Never abandon an Adobe worker or release the controlling chat while
            # it still owns a catalog operation. Cancellation uses the marker.
            if process.poll() is None:
                if cancel_file: cancel_file.touch()
                process.wait()
            context_path.unlink(missing_ok=True)
        report = json.loads(report_path.read_text(encoding='utf-8')) if report_path else {}
        self.result = {'status': report.get('status', 'failed'),
                       'report': str(report_path) if report_path else None,
                       'file_count': len(report.get('files', [])),
                       'completed': sum(x['status'] == 'passed' for x in report.get('files', [])),
                       'files': [{'source': x['source'], 'status': x['status'],
                                  'output': x.get('final_output', x.get('output')), 'tiff': x.get('tiff'), 'psd': x.get('psd'),
                                  'stages': x.get('stages'), 'error': x.get('error'),
                                  'edits': x.get('assistant_message')} for x in report.get('files', [])[:5]],
                       'skipped_count': len(report.get('skipped', [])),
                       'finish': report.get('finish'),
                       'all_files_in_report': True}
        if code or self.result['status'] != 'passed':
            self.result['error'] = report.get('error') or '\n'.join(tail)
            self.result['instruction'] = 'Stopped without retrying. Inspect the report and in-flight Adobe work before a new request.'
        if self.result['status'] == 'passed':
            self.selected_input = path
            self.completed_sources = [Path(x['tiff']) for x in report['files']]
            first = report['files'][0]
            self.source = Path(first['output'])/'original.tif'
            self.job = Path(first.get('final_output', first['output']))
            # A supplied mask belongs to its current source. Follow-ups must
            # recompute an automatic mask or explicitly select a corrected one.
            self.mask = None
        self.progress = 'Finished: ' + self.result['status']
        return self.result


def launch(prompt=None, evidence=None, log=None):
    from .pipeline import job_lock
    local_runtime()
    from .vault import initialize
    initialize()
    with job_lock(ROOT/'.cache/prompt-chat.lock'):
        return run_session(PromptWorkspace(), prompt, evidence, SYSTEM, log,
                           profile=ROOT/'apps/OhMyPiPromptData')


if __name__ == '__main__':
    sys.exit(launch())
