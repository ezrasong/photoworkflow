"""Private stdio desktop bridge. Python retains all photo validation and locks."""
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

from .runtime import CODE_ROOT, ROOT, PYTHON, local_runtime, json_write, sha256, workspace_path

_stdout = sys.stdout
_write_lock = threading.Lock()

def emit(value):
    with _write_lock:
        _stdout.write(json.dumps(value, ensure_ascii=False, default=str) + '\n')
        _stdout.flush()


class Desktop:
    def __init__(self):
        from .installation import seed_workspace, setup_lock
        with setup_lock():
            seed_workspace()
        local_runtime()
        from .vault import initialize
        initialize()
        for name in ('outputs', 'inputs', '.cache/control', 'desktop/sessions'):
            (ROOT/name).mkdir(parents=True, exist_ok=True)
        self.guard = threading.Lock()
        self.worker = None
        self.cancel_file = None
        self.omp = None
        self.broker = None
        self.broker_context = None
        self.session_lock = None
        self.workspace = None
        self.busy = False
        self.session = None
        self.children = []
        self.readers = []
        from .creative_mcp import write_config
        self.mcp_config = write_config()

    def status(self):
        from .installation import inventory
        from .creative_mcp import inventory as mcp_inventory
        import shutil
        gpu = {'available': False, 'reason': 'CUDA inspection failed'}
        try:
            import torch
            gpu = {'available': torch.cuda.is_available(), 'torch': torch.__version__}
            if gpu['available']:
                prop = torch.cuda.get_device_properties(0)
                gpu.update(name=prop.name, memory=prop.total_memory, capability=list(torch.cuda.get_device_capability(0)))
            else: gpu['reason'] = 'A supported NVIDIA GPU and driver are required for model inference; CPU fallback is not configured.'
        except ImportError: gpu['reason'] = 'Install the PyTorch CUDA runtime in Setup, then restart Photo Studio to detect supported hardware.'
        except Exception as error: gpu['reason'] = str(error)
        adobe = {}
        for product, exe in [('Photoshop', 'Photoshop.exe'), ('Lightroom', 'Lightroom.exe')]:
            base = Path(os.environ.get('ProgramFiles', 'C:/Program Files'))/'Adobe'
            adobe[product] = [str(p) for p in base.glob('*/'+exe)] if base.exists() else []
        return dict(home=str(ROOT), gpu=gpu, adobe=adobe, dependencies=inventory(),
                    creativeMcp=mcp_inventory(), mcpConfig=self.mcp_config,
                    mcpPlugin=str(ROOT/'apps/LightroomMCP.lrplugin'),
                    free=shutil.disk_usage(ROOT).free, busy=self.busy,
                    plugin=str(ROOT/'apps/PhotoWorkflow.lrplugin'), sessions=self.sessions(), results=self.results())

    def sessions(self):
        items = []
        for path in (ROOT/'desktop/sessions').glob('*/session.json'):
            try: items.append(json.loads(path.read_text(encoding='utf-8')))
            except (OSError, ValueError): pass
        return sorted(items, key=lambda x:x.get('updated', 0), reverse=True)

    def session_path(self, identity):
        if not isinstance(identity, str) or len(identity) != 32 or any(c not in '0123456789abcdef' for c in identity):
            raise ValueError('Invalid session identifier')
        return ROOT/'desktop/sessions'/identity

    def record(self, event):
        if self.session:
            with (self.session_path(self.session)/'events.jsonl').open('a', encoding='utf-8') as f:
                f.write(json.dumps(event, ensure_ascii=False, default=str)+'\n')
        emit({'event': event})

    def save_workspace(self):
        if not self.session or not self.workspace:return
        w=self.workspace
        def paths(values):return [str(p) for p in values]
        json_write(self.session_path(self.session)/'context.json', {
            'selected_input':str(w.selected_input) if w.selected_input else None,
            'source':str(w.source) if w.source else None, 'mask':str(w.mask) if w.mask else None,
            'job':str(w.job) if w.job else None,'notes':paths(w.notes),'references':paths(w.references),
            'completed_sources':paths(w.completed_sources),'result':w.result,'progress':w.progress})

    def restore_workspace(self):
        path=self.session_path(self.session)/'context.json'
        if not path.exists():return
        from .references import local_path
        data=json.loads(path.read_text(encoding='utf-8'));w=self.workspace
        if data.get('selected_input'):w.select_source(local_path(data['selected_input']))
        w.select_notes(data.get('notes',[]));w.select_references(data.get('references',[]))
        if data.get('source'):w.source=local_path(data['source'])
        if data.get('mask'):w.mask=local_path(data['mask'])
        if data.get('job'):
            job=workspace_path(data['job'])
            if not job.is_relative_to(ROOT/'outputs') or not (job/'job.json').is_file():raise ValueError('Saved result is missing; inspect the workspace before continuing')
            w.job=job
        w.completed_sources=[workspace_path(p) for p in data.get('completed_sources',[])]
        w.result=data.get('result');w.progress=data.get('progress','Ready')

    def stop_chat(self):
        if self.omp:
            self.omp.stdin.close()
            # RPC EOF drains accepted work. Never kill an Adobe save.
            self.omp.wait()
            for reader in self.readers:reader.join()
            self.readers=[]
            self.omp = None
        self.save_workspace()
        if self.broker_context:
            self.broker_context.__exit__(None,None,None)
            self.broker_context = self.broker = None
        if self.session_lock:
            self.session_lock.__exit__(None,None,None)
            self.session_lock = None

    def start_chat(self, identity):
        if self.busy: raise ValueError('Wait for the current job or stop safely before changing sessions')
        self.stop_chat()
        from .chat import OMP, OMP_HASH, configure, running
        from .prompt_chat import PromptWorkspace, SYSTEM
        from .pipeline import job_lock
        if not OMP.exists() or sha256(OMP) != OMP_HASH:
            raise ValueError('Install or repair Oh My Pi in Setup before opening an assistant session')
        path = self.session_path(identity); path.mkdir(parents=True, exist_ok=True)
        self.session = identity
        self.workspace = PromptWorkspace()
        self.restore_workspace()
        # Outer prompt profile must not take the per-photo worker's chat.lock.
        lock=job_lock(ROOT/'.cache/prompt-chat.lock');lock.__enter__();self.session_lock=lock
        try:
            self.broker_context = running(self.workspace)
            self.broker = self.broker_context.__enter__()
            env, work = configure(self.broker, ROOT/'apps/OhMyPiDesktopData')
            args = [str(OMP), '--cwd', str(work), '--model', 'photo-local/qwen-photo',
                    '--system-prompt', SYSTEM, '--no-tools', '--no-extensions', '--no-skills', '--no-rules',
                    '--no-lsp', '--no-pty', '--no-title', '--thinking', 'off',
                    '-e', str(CODE_ROOT/'integrations/photo-chat.ts'), '--session-dir', str(path/'omp'),
                    '--continue', '--mode', 'rpc', '--no-ui']
            self.omp = subprocess.Popen(args, cwd=work, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True, encoding='utf-8', creationflags=subprocess.CREATE_NO_WINDOW)
            self.readers=[threading.Thread(target=self.read_omp,args=(self.omp,),daemon=True),
                          threading.Thread(target=self.read_errors,args=(self.omp,),daemon=True)]
            for reader in self.readers:reader.start()
        except BaseException:
            self.stop_chat(); raise

    def read_errors(self, process):
        for line in process.stderr:
            if line.strip(): self.record({'type':'diagnostic', 'text':line.strip()})

    def read_omp(self, process):
        for line in process.stdout:
            try: event=json.loads(line)
            except ValueError:
                self.record({'type':'diagnostic','text':line[:2000]}); continue
            if event.get('type') == 'prompt_result' or (event.get('type') == 'response' and event.get('command') == 'prompt' and (not event.get('success') or event.get('data',{}).get('agentInvoked') is False)):
                # An aborted RPC fetch can finish before its Adobe/model handler.
                # Keep the job busy until the owning Python operations drain.
                while self.broker and (self.broker.active_calls or self.broker.inference_lock.locked()):
                    time.sleep(.1)
                self.save_workspace()
                self.busy = False
            self.record(event)
        if self.busy:
            self.busy = False
            self.record({'type':'error', 'text':'Assistant exited unexpectedly. Inspect results before retrying an edit.'})

    def omp_send(self, value):
        if not self.omp or self.omp.poll() is not None: raise ValueError('Open an assistant session first')
        self.omp.stdin.write(json.dumps(value)+'\n'); self.omp.stdin.flush()

    def results(self):
        items=[]
        for path in (ROOT/'outputs').rglob('job.json'):
            if any(p.startswith('.partial') for p in path.parts): continue
            try:
                data=json.loads(path.read_text(encoding='utf-8'))
                items.append({'path':str(path.parent), 'name':path.parent.name, 'updated':path.stat().st_mtime,
                              'details':data})
            except (OSError, ValueError): pass
        return sorted(items,key=lambda x:x['updated'],reverse=True)[:200]

    def run_worker(self, args):
        with self.guard:
            if self.busy: raise ValueError('A job is already running')
            self.busy=True
            self.cancel_file=ROOT/'.cache/control'/(uuid.uuid4().hex+'.cancel')
        env=os.environ.copy(); env['PHOTOWORKFLOW_CANCEL_FILE']=str(self.cancel_file)
        try:
            self.worker=subprocess.Popen([str(PYTHON), '-u', '-m', 'photo_workflow', *args],cwd=ROOT,env=env,
                    stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',creationflags=subprocess.CREATE_NO_WINDOW)
            for line in self.worker.stdout: self.record({'type':'job_progress','text':line.strip()})
            code=self.worker.wait()
            self.record({'type':'job_end','code':code,'results':self.results()})
            if code not in (0,130): raise RuntimeError('Photo job failed. See job activity and the preserved error report.')
            return {'code':code}
        finally:
            with self.guard:
                self.worker=None;self.cancel_file.unlink(missing_ok=True);self.cancel_file=None;self.busy=False

    def cancel(self):
        with self.guard:
            if self.cancel_file: self.cancel_file.touch()
            if self.broker:
                for marker in list(self.broker.active_calls.values()): marker.touch()
            if self.omp and self.omp.poll() is None: self.omp_send({'type':'abort','id':uuid.uuid4().hex})
        return {'message':'Stop requested; waiting for a safe model/Adobe boundary.'}

    def dispatch(self, method, args):
        if not isinstance(args,dict): raise ValueError('Object arguments required')
        if method=='status': return self.status()
        if method=='mcp_check':
            from .creative_mcp import inspect
            if set(args) != {'server', 'probe'} or type(args['probe']) is not bool:
                raise ValueError('Choose a bundled server and check type')
            with self.guard:
                if self.busy: raise ValueError('Wait for the current job before checking MCP')
                self.busy=True
                self.cancel_file=ROOT/'.cache/control'/(uuid.uuid4().hex+'.cancel')
            try:
                return inspect(args['server'], probe=args['probe'], cancel_file=self.cancel_file)
            finally:
                with self.guard:
                    self.cancel_file.unlink(missing_ok=True);self.cancel_file=None;self.busy=False
        if method=='results': return self.results()
        if method=='preview':
            import base64
            import io
            from .imaging import decode_working, preview
            from .references import local_path
            path=local_path(args.get('path',''))
            if path.stat().st_size>512*1024*1024:raise ValueError('Preview source too large')
            pixels,_=decode_working(path.read_bytes());image=preview(pixels)
            if not args.get('full'): image.thumbnail((1800,1200))
            output=io.BytesIO();image.save(output,format='PNG')
            return 'data:image/png;base64,'+base64.b64encode(output.getvalue()).decode('ascii')
        if method=='review':
            path=workspace_path(args.get('path',''))
            if not path.is_relative_to(ROOT/'outputs'):raise ValueError('Select a result')
            if not (path/'job.json').is_file():raise ValueError('Completed job required')
            # Existing review handles native-batch reports; create a minimal view-only report.
            report=ROOT/'.cache/control'/('review-'+uuid.uuid4().hex)/'report.json'
            report.parent.mkdir()
            job=json.loads((path/'job.json').read_text(encoding='utf-8'))
            before=workspace_path(path/job.get('baseline_file','original.tif'))
            after=workspace_path(path/job.get('composite_file','composite.tif'))
            if before.parent!=path or after.parent!=path:raise ValueError('Invalid result artifact path')
            json_write(report,{'files':[{'output':str(path),'final_output':str(path),'source':str(before),'baseline':str(before),'tiff':str(after),'status':'passed'}]})
            process=subprocess.Popen([str(PYTHON),'-m','photo_workflow.review_panel',str(report)],cwd=ROOT,stdin=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
            self.children.append(process)
            status=report.parent/'review-ui-status.json'
            deadline=time.monotonic()+30
            while not status.exists() and process.poll() is None and time.monotonic()<deadline:time.sleep(.1)
            state=json.loads(status.read_text()) if status.exists() else {'status':'failed','error':'Review did not become ready within 30 seconds; inspect the backend log.'}
            if state['status']!='ready':raise RuntimeError(state.get('error','Review failed'))
            return {'opened':str(path),'pid':process.pid}
        if method=='obsidian':
            from .vault import open_obsidian
            open_obsidian();return {'opened':True}
        if method=='references':
            from .chat import choose_references
            with self.guard:
                if self.busy or not self.workspace:raise ValueError('Open an idle assistant session first')
                self.busy=True
            try:
                result=choose_references(self.workspace, '')
                self.save_workspace()
                return result
            finally:
                with self.guard:self.busy=False
        if method=='suggest':
            with self.guard:
                if self.busy or not self.broker:raise ValueError('Open an idle assistant session first')
                if not self.workspace.selected_input:raise ValueError('Choose a photo first')
                self.busy=True
                self.cancel_file=ROOT/'.cache/control'/(uuid.uuid4().hex+'.cancel')
            try:
                from .prompt_master import suggest
                result=suggest(self.workspace,self.broker.inference_lock,self.cancel_file)
                self.record({'type':'prompt_suggestions',**result})
                return result
            finally:
                with self.guard:
                    self.cancel_file.unlink(missing_ok=True);self.cancel_file=None;self.busy=False
        if method=='cancel': return self.cancel()
        if method=='setup':
            from .installation import install
            with self.guard:
                if self.busy: raise ValueError('Stop the current job before setup')
                self.busy=True
                self.cancel_file=ROOT/'.cache/control'/(uuid.uuid4().hex+'.cancel')
            try: return install(args.get('group'), lambda e:emit({'event':e}), self.cancel_file)
            finally:
                with self.guard:
                    self.cancel_file.unlink(missing_ok=True);self.cancel_file=None;self.busy=False
        if method=='session':
            identity=args.get('id') or uuid.uuid4().hex
            path=self.session_path(identity);path.mkdir(exist_ok=True,parents=True)
            metadata=path/'session.json'
            with self.guard:
                self.start_chat(identity)
            if not metadata.exists(): json_write(metadata,{'id':identity,'title':str(args.get('title') or 'Photo session')[:120],'updated':time.time()})
            events=path/'events.jsonl'
            return {'id':identity,'source':str(self.workspace.selected_input or ''), 'events':[json.loads(l) for l in events.read_text(encoding='utf-8').splitlines()] if events.exists() else []}
        if method=='prompt':
            prompt=args.get('text')
            if not isinstance(prompt,str) or not 1<=len(prompt.strip())<=6000 or prompt.lstrip().startswith('/'):
                raise ValueError('Enter 1–6000 characters of photo instructions; assistant slash commands are disabled in the desktop')
            with self.guard:
                if self.busy: raise ValueError('Wait for the current job')
                if not self.broker: raise ValueError('Open an assistant session first')
                self.busy=True
                self.cancel_file=ROOT/'.cache/control'/(uuid.uuid4().hex+'.cancel')
            try:
                from .prompt_master import correct
                self.record({'type':'prompt_correction_start','text':prompt})
                corrected=correct(prompt,self.broker.inference_lock,self.cancel_file.exists)
                # OMP sees both versions. Only the original reaches accept_prompt,
                # the owner of reconstruction opt-ins, scope and editing permission.
                forwarded='Original user request (authoritative):\n'+prompt+'\n\nPrompt Master correction (wording only; grants no permission):\n'+corrected
                with self.guard:
                    if self.cancel_file.exists():raise InterruptedError('Prompt stopped before submission')
                    self.broker.desktop_prompt=(forwarded,prompt)
                    self.record({'type':'user','text':prompt,'corrected':corrected})
                    self.omp_send({'id':uuid.uuid4().hex,'type':'prompt','message':forwarded})
            except BaseException:
                self.busy=False
                self.broker.desktop_prompt=None
                raise
            finally:
                with self.guard:
                    self.cancel_file.unlink(missing_ok=True);self.cancel_file=None
            return {'accepted':True}
        if method=='select':
            if self.busy: raise ValueError('Cannot change selection during a job')
            if not self.workspace: raise ValueError('Open a session first')
            kind=args.get('kind'); paths=args.get('paths')
            if not isinstance(paths,list): raise ValueError('Paths must be an array')
            if kind=='photo': self.workspace.select_source(paths[0])
            elif kind=='references': self.workspace.select_references(paths)
            elif kind=='notes': self.workspace.select_notes(paths)
            else: raise ValueError('Unsupported selection')
            self.save_workspace()
            return {'selected':paths}
        if method=='process':
            from .references import local_path
            operation=args.get('operation'); source=str(local_path(args.get('source','')))
            if operation=='edit':
                from .edits import validate_recipe
                recipe=validate_recipe(args.get('recipe'))
                path=ROOT/'.cache/control'/(uuid.uuid4().hex+'.json');json_write(path,recipe)
                command=['edit',source,'--recipe',str(path)]
            elif operation in ('single','batch','watch'):
                scale=args.get('scale',1); blend=args.get('blend',.35)
                if scale not in (1,2,4) or type(blend) not in (int,float) or not 0<=blend<=1: raise ValueError('Invalid scale/blend')
                command=[operation,source,'--scale',str(scale),'--blend',str(blend)]
            elif operation=='upscale':
                scale=args.get('scale',2);strength=args.get('strength',.2);model=args.get('model','mambairv2')
                if scale not in (2,4) or type(strength) not in (float,int) or not 0<=strength<=.5 or model not in ('mambairv2','realesrgan'): raise ValueError('Invalid upscale settings')
                command=['upscale',source,'--scale',str(scale),'--detail-strength',str(strength),'--model',model]
            else: raise ValueError('Unsupported photo operation')
            return self.run_worker(command)
        if method=='export':
            path=workspace_path(args.get('path',''))
            if not path.is_relative_to(ROOT/'outputs') or not (path/'job.json').is_file(): raise ValueError('Select a completed result')
            return self.run_worker(['photoshop',str(path)])
        if method=='panel':
            if self.busy: raise ValueError('Wait for the current job before opening advanced tools')
            name=args.get('name')
            modules={'advanced':'photo_workflow.harness','batch':'photo_workflow.batch_panel'}
            if name not in modules: raise ValueError('Unknown panel')
            log=(ROOT/'.cache/desktop-panels.log').open('a',encoding='utf-8')
            process=subprocess.Popen([str(PYTHON),'-m',modules[name]],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
            log.close();self.children.append(process)
            return {'opened':name}
        if method=='person':
            from .vault import add_person
            return {'id':add_person(args.get('name',''))}
        if method=='settings':
            path=ROOT/'desktop/settings.json'
            if 'value' in args:
                value=args['value']
                if not isinstance(value,dict) or set(value)-{'theme','reviewZoom'} or value.get('theme','dark') not in ('dark','light') or value.get('reviewZoom','fit') not in ('fit','100%'): raise ValueError('Invalid settings')
                json_write(path,value)
            return json.loads(path.read_text()) if path.exists() else {'theme':'dark','reviewZoom':'fit'}
        raise ValueError('Unsupported desktop command')


def main():
    # Windows native numerical modules inspect standard streams on import.
    # Load them before the main thread blocks reading the stdio command pipe.
    import numpy
    import cv2
    import imagecodecs
    try:
        import torch
    except ImportError:
        pass  # Repair remains available for unpacked or interrupted installations.
    desktop=Desktop()
    emit({'event':{'type':'backend_ready','home':str(ROOT)}})
    def handle(request):
        try: emit({'id':request['id'],'result':desktop.dispatch(request.get('method'),request.get('args',{}))})
        except Exception as error: emit({'id':request.get('id'),'error':str(error)})
    # Keep cancellation responsive while setup, workers and native applications run.
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        try:
            for line in sys.stdin:
                if len(line)>128000: continue
                try: request=json.loads(line)
                except ValueError: continue
                if isinstance(request,dict) and isinstance(request.get('id'),str): pool.submit(handle,request)
        finally:
            desktop.cancel()
    desktop.stop_chat()

if __name__=='__main__':
    # Backend libraries may print diagnostics; reserve stdout for the protocol.
    sys.stdout=sys.stderr
    main()
