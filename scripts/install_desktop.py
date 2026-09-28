"""Installer-owned setup using the same verified downloads as in-app repair.

Launched by NSIS with bundled Python in isolated mode; no system Python or pip.
"""
import argparse
import json
import os
from pathlib import Path
import queue
import sys
import threading
import traceback
import uuid


def run_setup(emit, marker, log):
    from photo_workflow.installation import install
    def report(event):
        log.write(json.dumps(event) + '\n')
        log.flush()
        emit(event)
    try:
        install('all', report, marker)
        return 0
    except InterruptedError as error:
        report({'type': 'setup_error', 'text': str(error)})
        return 2
    except Exception as error:
        traceback.print_exc(file=log)
        report({'type': 'setup_error', 'text': str(error)})
        return 1
    finally:
        marker.unlink(missing_ok=True)


def progress_window(marker, log, log_path):
    import tkinter as tk
    from tkinter import ttk, messagebox
    from photo_workflow.installation import catalog

    root = tk.Tk()
    root.title('Photo Studio — Downloading components')
    root.minsize(560, 300)
    root.geometry('660x340')
    frame = ttk.Frame(root, padding=24)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='Installing Photo Studio', font=('Segoe UI', 16)).pack(anchor='w')
    total = sum(entry['bytes'] for entry in catalog().values())
    ttk.Label(frame, text=f'All models, runtimes and Obsidian • {total/1024**3:.1f} GiB total\n'
              'Verified downloads resume if interrupted. Keep this window open.').pack(anchor='w', pady=(12, 16))
    status = tk.StringVar(value='Checking files and available disk space…')
    ttk.Label(frame, textvariable=status, wraplength=500).pack(anchor='w')
    progress = ttk.Progressbar(frame, mode='indeterminate')
    progress.pack(fill='x', pady=12)
    progress.start()
    amounts = tk.StringVar(value='Preparing setup')
    ttk.Label(frame, textvariable=amounts).pack(anchor='w')
    events = queue.Queue()
    result = [1]
    def cancel():
        marker.touch()
        cancel_button.configure(state='disabled')
        status.set('Stopping safely… Partial downloads will be kept for the next install.')
    cancel_button = ttk.Button(frame, text='Cancel installation', command=cancel)
    cancel_button.pack(anchor='e', pady=(16, 0))
    root.protocol('WM_DELETE_WINDOW', cancel)

    def worker():
        code = run_setup(events.put, marker, log)
        events.put({'type': 'finished', 'code': code})
    last_error = ['']
    def poll():
        try:
            while True:
                event = events.get_nowait()
                if event['type'] == 'finished':
                    result[0] = event['code']
                    if result[0] == 1:
                        messagebox.showerror('Photo Studio installation incomplete',
                            last_error[0] + '\n\nRun the installer again to resume.\nLog: ' + str(log_path), parent=root)
                    root.destroy()
                    return
                if event['type'] == 'setup_error':
                    last_error[0] = event['text']
                if marker.exists():
                    continue
                if event['type'] == 'setup_progress':
                    progress.stop()
                    progress.configure(mode='determinate', maximum=max(1, event['total']), value=event['done'])
                    status.set('Downloading / verifying ' + Path(event['file']).name)
                    amounts.set(f"{event['done']/1024**3:.2f} / {event['total']/1024**3:.2f} GiB")
                elif event['type'] in ('setup_extract', 'setup_group_complete'):
                    progress.configure(mode='indeterminate')
                    progress.start()
                    status.set('Preparing ' + Path(event.get('file', event.get('group', 'components'))).name)
                    amounts.set('Extracting and checking components…')
        except queue.Empty:
            pass
        root.after(100, poll)

    # Non-daemon: closing the progress UI cannot strand a writer mid-extraction.
    thread = threading.Thread(target=worker)
    thread.start()
    root.after(100, poll)
    root.mainloop()
    thread.join()
    return result[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--silent', action='store_true')
    parser.add_argument('--workspace', type=Path)
    args = parser.parse_args()
    home = (args.workspace or Path(os.environ.get('PHOTOWORKFLOW_HOME') or
            str(Path(os.environ['APPDATA']) / 'photo-workflow/Workspace'))).resolve()
    os.environ['PHOTOWORKFLOW_HOME'] = str(home)
    # -I ignores inherited Python paths. Only this installation and its private
    # runtime can supply imports, including newly extracted torch for conversion.
    code = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(code), str(home / 'runtime/python-libs')]
    from photo_workflow.runtime import local_runtime
    local_runtime()
    control = home / '.cache/control'
    control.mkdir(parents=True, exist_ok=True)
    marker = control / ('installer-' + uuid.uuid4().hex + '.cancel')
    log_path = home / 'desktop/install-logs' / (uuid.uuid4().hex + '.log')
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open('w', encoding='utf-8', buffering=1) as log:
        # pythonw has no standard streams; numerical imports can require them.
        previous_streams = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = log
        try:
            return run_setup(lambda event: None, marker, log) if args.silent else progress_window(marker, log, log_path)
        except Exception:
            traceback.print_exc(file=log)
            return 1
        finally:
            sys.stdout, sys.stderr = previous_streams


if __name__ == '__main__':
    raise SystemExit(main())
