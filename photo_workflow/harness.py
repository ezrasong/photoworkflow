"""Local desktop orchestration for restoration, editing and bounded agent tools."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import uuid

from .runtime import PYTHON, PYTHONW, ROOT, local_runtime
from .vault import CONFIG, VAULT, add_person, initialize

class App:
    def __init__(self, window):
        local_runtime(); initialize()
        self.window = window
        window.title('Local Photo Workflow'); window.geometry('960x700')
        self.events = queue.Queue(); self.process = None; self.busy = False; self.cancel_file = None
        self.path = tk.StringVar(); self.mode = tk.StringVar(value='single')
        self.scale = tk.StringVar(value='1'); self.depth = tk.StringVar(value='16'); self.blend = tk.DoubleVar(value=.35)
        self.subject = tk.StringVar(value='No person mapping'); self.jobs = []
        root = ttk.Frame(window, padding=16); root.pack(fill='both', expand=True)
        ttk.Label(root, text='Local Photo Workflow', font=('Segoe UI', 18)).pack(anchor='w')
        ttk.Button(root, text='Edit file / folder with a prompt (native Adobe)', command=self.native_batch).pack(anchor='w', pady=8)
        ttk.Button(root, text='Open editor / local assistant', command=self.editor).pack(anchor='w', pady=8)
        ttk.Button(root, text='Oh My Pi chat: path + editing prompt', command=self.chat).pack(anchor='w', pady=4)
        ttk.Button(root, text='Natural upscale (no face reconstruction)', command=self.natural_upscale).pack(anchor='w', pady=4)
        ttk.Label(root, text='Restoration below is opt-in. Use the editor for grading, DRUNet denoising and masked clone.').pack(anchor='w', pady=(0, 12))
        row = ttk.Frame(root); row.pack(fill='x')
        ttk.Combobox(row, textvariable=self.mode, values=['single', 'batch', 'watch'], state='readonly', width=9).pack(side='left')
        ttk.Entry(row, textvariable=self.path).pack(side='left', fill='x', expand=True, padx=8)
        ttk.Button(row, text='Choose input', command=self.choose).pack(side='left')
        row = ttk.Frame(root); row.pack(fill='x', pady=12)
        for label, variable, values in [('Scale', self.scale, ['1','2','4']), ('Output bits', self.depth, ['16','8'])]:
            ttk.Label(row, text=label).pack(side='left', padx=(0,5))
            ttk.Combobox(row, textvariable=variable, values=values, state='readonly', width=5).pack(side='left', padx=(0,20))
        ttk.Label(row, text='Face blend').pack(side='left')
        ttk.Scale(row, from_=0, to=1, variable=self.blend).pack(side='left', fill='x', expand=True, padx=8)
        self.blend_label = ttk.Label(row, text='35%', width=5); self.blend_label.pack(side='left')
        self.blend.trace_add('write', lambda *_: self.blend_label.configure(text=f'{self.blend.get():.0%}'))
        row = ttk.Frame(root); row.pack(fill='x')
        ttk.Label(row, text='Person (your mapping)').pack(side='left')
        self.people = ttk.Combobox(row, textvariable=self.subject, state='readonly', width=34)
        self.people.pack(side='left', padx=8)
        ttk.Button(row, text='Add person', command=self.person).pack(side='left')
        ttk.Button(row, text='Open Obsidian', command=self.obsidian).pack(side='left', padx=8)
        self.refresh_people()
        row = ttk.Frame(root); row.pack(fill='x', pady=12)
        self.start_button = ttk.Button(row, text='Start face restoration', command=self.start); self.start_button.pack(side='left')
        self.stop_button = ttk.Button(row, text='Stop safely', command=self.stop, state='disabled'); self.stop_button.pack(side='left', padx=8)
        ttk.Button(row, text='Open input folder', command=lambda: os.startfile(ROOT / 'inputs')).pack(side='left')
        ttk.Label(root, text='Completed jobs — select a row to review or export').pack(anchor='w')
        self.listbox = tk.Listbox(root, height=8, exportselection=False); self.listbox.pack(fill='x', pady=6)
        row = ttk.Frame(root); row.pack(fill='x')
        ttk.Button(row, text='Refresh jobs', command=self.refresh_jobs).pack(side='left')
        ttk.Button(row, text='Open result folder', command=self.open_result).pack(side='left', padx=8)
        self.export_button = ttk.Button(row, text='Export layered PSD', command=self.export); self.export_button.pack(side='left')
        ttk.Button(row, text='Open local comparison', command=self.review).pack(side='left', padx=8)
        self.status = ttk.Label(root, text='Ready. Outputs default to 16-bit sRGB; visual review is required.')
        self.status.pack(anchor='w', pady=(12,4))
        self.log = tk.Text(root, height=8, state='disabled', wrap='word'); self.log.pack(fill='both', expand=True)
        self.refresh_jobs(); window.after(150, self.poll); window.protocol('WM_DELETE_WINDOW', self.close)

    def editor(self):
        from .edit_panel import Editor
        Editor(self)

    def native_batch(self):
        subprocess.Popen([str(PYTHONW), '-m', 'photo_workflow.batch_panel'],
                         cwd=ROOT, creationflags=subprocess.CREATE_NO_WINDOW)

    def chat(self):
        args = [str(PYTHON), '-m', 'photo_workflow.chat']
        subprocess.Popen(args, cwd=ROOT, creationflags=subprocess.CREATE_NEW_CONSOLE)

    def natural_upscale(self):
        if self.busy:return
        path=filedialog.askopenfilename(parent=self.window,title='Choose photo for natural upscale',initialdir=ROOT/'inputs',
                                       filetypes=[('Photographs','*.jpg *.jpeg *.png *.tif *.tiff')])
        if not path:return
        window=tk.Toplevel(self.window);window.title('Natural upscale');window.geometry('420x220')
        scale=tk.StringVar(value='2');strength=tk.DoubleVar(value=.2)
        ttk.Label(window,text='Face reconstruction stays off. Review texture locally.',wraplength=380).pack(padx=14,pady=12)
        ttk.Combobox(window,textvariable=scale,values=['2','4'],state='readonly',width=6).pack()
        ttk.Label(window,text='AI detail strength: 0 = normal resize; start at 0.2').pack(pady=8)
        ttk.Spinbox(window,from_=0,to=.5,increment=.05,textvariable=strength,width=8).pack()
        def run():
            try:value=strength.get()
            except tk.TclError:return messagebox.showerror('Invalid strength','Use 0 to 0.5.',parent=window)
            if not 0<=value<=.5:return messagebox.showerror('Invalid strength','Use 0 to 0.5.',parent=window)
            window.destroy()
            self.launch(['upscale',path,'--scale',scale.get(),'--detail-strength',str(value)],True)
        ttk.Button(window,text='Create separate 16-bit result',command=run).pack(pady=12)

    def choose(self):
        path = (filedialog.askopenfilename(filetypes=[('Photographs', '*.jpg *.jpeg *.png *.tif *.tiff')])
                if self.mode.get() == 'single' else filedialog.askdirectory(initialdir=ROOT / 'inputs'))
        if path: self.path.set(path)

    def refresh_people(self):
        entries = json.loads(CONFIG.read_text(encoding='utf-8'))['subjects']
        self.subjects = {'No person mapping': None}
        for key, entry in entries.items():
            self.subjects[entry.get('name', key) + ' [' + key + ']'] = key
        self.people['values'] = list(self.subjects)

    def person(self):
        name = simpledialog.askstring('Add person', 'Name for your local note and reference folder:', parent=self.window)
        if not name: return
        try:
            key = add_person(name); self.refresh_people()
            self.subject.set(next(label for label, value in self.subjects.items() if value == key))
            entry = json.loads(CONFIG.read_text(encoding='utf-8'))['subjects'][key]
            os.startfile(entry['reference_folder'])
        except Exception as error: messagebox.showerror('Cannot add person', str(error))

    def obsidian(self):
        try:
            from .vault import open_obsidian
            open_obsidian()
        except Exception as error: messagebox.showerror('Cannot open Obsidian', str(error))

    def refresh_jobs(self):
        self.jobs = []
        self.listbox.delete(0, 'end')
        for path in sorted((ROOT/'outputs').rglob('job.json'), key=lambda p: p.stat().st_mtime, reverse=True):
            if any(part.startswith('.partial-') for part in path.parts): continue
            try:
                job = json.loads(path.read_text(encoding='utf-8'))
                self.jobs.append(path.parent)
                self.listbox.insert('end', f"{job['source_name']} — {job.get('bit_depth',8)} bit, {job['faces']} faces — {path.parent.name}")
            except (ValueError, OSError): pass
        if self.jobs: self.listbox.selection_set(0)

    def selected(self):
        selection = self.listbox.curselection()
        return self.jobs[selection[0]] if selection else None

    def open_result(self):
        folder = self.selected()
        if folder: os.startfile(folder)

    def review(self):
        folder = self.selected()
        if folder: os.startfile(folder/'comparison.jpg')

    def start(self):
        if not self.path.get(): return messagebox.showinfo('Choose input', 'Choose a photograph or input folder first.')
        args = [self.mode.get(), self.path.get(), '--scale', self.scale.get(), '--bit-depth', self.depth.get(), '--blend', str(round(self.blend.get(),3))]
        if self.depth.get() == '8':
            if not messagebox.askyesno('8-bit output', 'This explicitly permits reducing high-bit-depth inputs to 8-bit derivatives. Continue?'): return
            args.append('--allow-8bit')
        subject = self.subjects.get(self.subject.get())
        if subject: args += ['--config', str(CONFIG), '--subject', subject]
        self.launch(args, cancellable=True)

    def export(self):
        folder = self.selected()
        if not folder: return
        from .photoshop import review_path
        if review_path(folder).exists(): return os.startfile(review_path(folder))
        self.launch(['photoshop', str(folder)], cancellable=False)

    def launch(self, args, cancellable):
        if self.busy: return
        self.busy = True
        self.start_button['state'] = self.export_button['state'] = 'disabled'
        self.stop_button['state'] = 'normal' if cancellable else 'disabled'
        self.status['text'] = 'Working locally…' if cancellable else 'Exporting in Photoshop; finish any Adobe dialog if prompted.'
        self.cancel_file = ROOT/'.cache/control'/(uuid.uuid4().hex+'.cancel')
        self.cancel_file.parent.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, PHOTOWORKFLOW_CANCEL_FILE=str(self.cancel_file), PYTHONUNBUFFERED='1', PYTHONIOENCODING='utf-8')
        def worker():
            try:
                self.process = subprocess.Popen([str(PYTHON), '-m', 'photo_workflow', *args], cwd=ROOT,
                    env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', creationflags=subprocess.CREATE_NO_WINDOW)
                with (ROOT/'.cache/harness.log').open('a', encoding='utf-8') as log:
                    for line in self.process.stdout:
                        log.write(line); log.flush(); self.events.put(('line', line))
                self.events.put(('done', self.process.wait()))
            except Exception as error: self.events.put(('line',str(error)+'\n')); self.events.put(('done',1))
        threading.Thread(target=worker, daemon=True).start()

    def stop(self):
        if self.busy and self.cancel_file:
            self.cancel_file.touch(); self.status['text'] = 'Stopping at the next safe model/job boundary…'

    def poll(self):
        while not self.events.empty():
            kind, value = self.events.get()
            if kind == 'line':
                if value.startswith('EXPORTING PHOTOSHOP'):
                    self.stop_button['state']='disabled'
                    self.status['text']='Saving layered PSD in Photoshop; finish any Adobe dialog if prompted.'
                self.log['state']='normal'; self.log.insert('end', value); self.log.see('end'); self.log['state']='disabled'
            else:
                self.busy=False; self.process=None
                if self.cancel_file: self.cancel_file.unlink(missing_ok=True)
                self.start_button['state']=self.export_button['state']='normal'; self.stop_button['state']='disabled'
                self.status['text'] = 'Completed.' if value == 0 else ('Cancelled safely.' if value == 130 else 'Job failed — see the local log.')
                self.refresh_jobs()
        self.window.after(150,self.poll)

    def close(self):
        if self.busy:
            self.stop(); messagebox.showinfo('Stopping', 'Wait for the active job to finish or cancel, then close the window.'); return
        self.window.destroy()

def main():
    root=tk.Tk(); App(root); root.mainloop()

if __name__ == '__main__': main()
