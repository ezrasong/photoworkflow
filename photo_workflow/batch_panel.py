"""Small unattended Adobe job launcher; editing runs in a separate process."""
import os
import queue
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import uuid

from .runtime import PYTHON, PYTHONW, ROOT, local_runtime


def main():
    local_runtime()
    window = tk.Tk(); window.title('Edit photos with a prompt'); window.geometry('760x580')
    body = ttk.Frame(window, padding=16); body.pack(fill='both', expand=True)
    ttk.Label(body, text='Edit a file or folder with Lightroom', font=('Segoe UI', 17)).pack(anchor='w')
    ttk.Label(body, text='Keep Lightroom open with the destination catalog. Originals stay unchanged.\n'
              'Lightroom edits use virtual copies. Results include 16-bit TIFF and optional layered PSD.').pack(anchor='w', pady=8)
    path = tk.StringVar(); psd = tk.BooleanVar(value=True)
    row = ttk.Frame(body); row.pack(fill='x')
    ttk.Entry(row, textvariable=path).pack(side='left', fill='x', expand=True)
    def choose(folder):
        value = filedialog.askdirectory(parent=window) if folder else filedialog.askopenfilename(parent=window)
        if value: path.set(value)
    ttk.Button(row, text='Folder', command=lambda: choose(True)).pack(side='left', padx=5)
    ttk.Button(row, text='File', command=lambda: choose(False)).pack(side='left')
    ttk.Label(body, text='What should change? (Applied separately to each photo)').pack(anchor='w', pady=(12, 4))
    prompt = tk.Text(body, height=5, wrap='word'); prompt.pack(fill='x')
    ttk.Label(body, text='Tone/color, crop, curves, lens corrections and local Photoshop curve/clone edits.\n'
              'Subfolders are skipped. Unsupported requests stop with an explanation in the report.').pack(anchor='w', pady=6)
    ttk.Checkbutton(body, text='Also save layered PSD (local repairs use Photoshop even without PSD)', variable=psd).pack(anchor='w')
    row = ttk.Frame(body); row.pack(fill='x', pady=8)
    messages = queue.Queue(); state = {'busy': False, 'marker': None, 'report': None}
    log = tk.Text(body, height=12, state='disabled', wrap='word')
    status = ttk.Label(body, text='Ready')
    def start():
        if state['busy']: return
        request = prompt.get('1.0', 'end').strip()
        if not path.get().strip() or not request:
            return messagebox.showerror('Missing input', 'Choose a file/folder and enter your editing prompt.', parent=window)
        state.update(busy=True, report=None)
        marker = ROOT/'.cache/control'/('batch-'+uuid.uuid4().hex+'.cancel')
        marker.parent.mkdir(parents=True, exist_ok=True); state['marker'] = marker
        args = [str(PYTHON), '-m', 'photo_workflow.native_batch',
                path.get().strip().strip('"'), '--prompt', request]
        if not psd.get(): args.append('--tiff-only')
        run_button['state'] = 'disabled'; stop_button['state'] = 'normal'; status['text'] = 'Working locally…'
        def worker():
            code = 1
            try:
                process = subprocess.Popen(args, cwd=ROOT,
                    env=dict(os.environ, PHOTOWORKFLOW_CANCEL_FILE=str(marker), PYTHONIOENCODING='utf-8'),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace',
                    creationflags=subprocess.CREATE_NO_WINDOW)
                for line in process.stdout: messages.put(('line', line))
                code = process.wait()
            except Exception as error: messages.put(('line', str(error)+'\n'))
            finally: messages.put(('done', code))
        threading.Thread(target=worker, daemon=True).start()
    def stop():
        if state['busy']:
            state['marker'].touch(); status['text'] = 'Stopping at the next safe boundary; Adobe may finish its current operation.'
    def results():
        if state['report']:
            from pathlib import Path
            os.startfile(Path(state['report']).parent)
    def poll():
        while not messages.empty():
            kind, value = messages.get()
            if kind == 'line':
                if value.startswith('BATCH REPORT '): state['report'] = value[len('BATCH REPORT '):].strip()
                log['state'] = 'normal'; log.insert('end', value); log.see('end'); log['state'] = 'disabled'
            else:
                state['busy'] = False; state['marker'].unlink(missing_ok=True)
                run_button['state'] = 'normal'; stop_button['state'] = 'disabled'
                status['text'] = 'Completed — open results for TIFF, PSD and report.' if value == 0 else (
                    'Cancelled — inspect results before retrying.' if value == 130 else 'Stopped — see the report and log.')
        window.after(200, poll)
    def close():
        if state['busy']:
            stop(); messagebox.showinfo('Stopping', 'Wait for the active Adobe operation to finish, then close.', parent=window)
        else: window.destroy()
    run_button = ttk.Button(row, text='Run editing prompt', command=start); run_button.pack(side='left')
    stop_button = ttk.Button(row, text='Stop safely', command=stop, state='disabled'); stop_button.pack(side='left', padx=6)
    ttk.Button(row, text='Open results', command=results).pack(side='left')
    log.pack(fill='both', expand=True); status.pack(anchor='w', pady=6)
    window.protocol('WM_DELETE_WINDOW', close); window.after(200, poll); window.mainloop()
    return 0


if __name__ == '__main__': main()
