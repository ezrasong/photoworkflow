"""Normal Adobe shutdown followed by local review, only after a successful batch."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import time

from .runtime import PYTHON, PYTHONW, ROOT, json_write, workspace_path


def launch_review(report_path):
    report_path=workspace_path(report_path)
    json_write(report_path.parent/'review-ui-status.json',{'status':'launching'})
    with (report_path.parent/'review-ui.log').open('a',encoding='utf-8') as log:
        return subprocess.Popen([str(PYTHONW),'-m','photo_workflow.review_panel',str(report_path)],
                                cwd=ROOT,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)


def adobe_windows():
    import win32gui
    import win32process
    api=ctypes.WinDLL('kernel32',use_last_error=True)
    api.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];api.OpenProcess.restype=wintypes.HANDLE
    api.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
    api.CloseHandle.argtypes=[wintypes.HANDLE]
    found={}
    def visit(hwnd,_):
        if not win32gui.IsWindowVisible(hwnd) or win32gui.GetWindow(hwnd,4) or win32gui.GetClassName(hwnd)=='#32770':return
        _,pid=win32process.GetWindowThreadProcessId(hwnd)
        handle=api.OpenProcess(0x1000,False,pid)
        if not handle:return
        try:
            buffer=ctypes.create_unicode_buffer(32768);size=wintypes.DWORD(len(buffer))
            if api.QueryFullProcessImageNameW(handle,0,buffer,ctypes.byref(size)):
                name=Path(buffer.value).name.lower()
                if name in ('photoshop.exe','lightroom.exe'):found.setdefault(name,[]).append((hwnd,pid))
        finally:api.CloseHandle(handle)
    win32gui.EnumWindows(visit,None)
    return found


def close_adobe(catalog, photoshop_session=None):
    import win32gui
    import win32api
    import win32event
    from . import lightroom
    result={};waiting={}
    windows=adobe_windows()
    for app,exe in [('Photoshop','photoshop.exe'),('Lightroom','lightroom.exe')]:
        targets=windows.get(exe,[])
        if not targets:
            result[app]={'status':'already closed'};continue
        if len(targets)!=1:
            result[app]={'status':'left open','reason':'Multiple application windows need local review'};continue
        try:
            if app=='Photoshop':
                import win32com.client
                # GetActiveObject never starts a replacement after a crash.
                adobe=photoshop_session.app if photoshop_session else win32com.client.GetActiveObject('Photoshop.Application')
                if photoshop_session:photoshop_session.verify()
                if any(not doc.Saved for doc in adobe.Documents):
                    result[app]={'status':'left open','reason':'Unsaved documents; no changes discarded'};continue
            else:
                current=lightroom.request('catalog',timeout=5)
                if Path(current['catalog']).resolve()!=Path(catalog).resolve():
                    result[app]={'status':'left open','reason':'Active catalog changed'};continue
            hwnd,pid=targets[0]
            process=win32api.OpenProcess(0x100000,False,pid)
            win32gui.PostMessage(hwnd,0x0010,0,0)  # WM_CLOSE: normal app close, never kill.
            waiting[app]=process
            result[app]={'status':'close requested','method':'normal window close; dialogs preserved'}
        except Exception as error:result[app]={'status':'left open','reason':str(error)}
    deadline=time.monotonic()+12
    while waiting and time.monotonic()<deadline:
        for app,process in list(waiting.items()):
            if win32event.WaitForSingleObject(process,0)==0:
                result[app]['status']='closed';waiting.pop(app);process.Close()
        if waiting:time.sleep(.25)
    for app,process in waiting.items():
        process.Close()
        result[app].update(status='needs attention',reason='Application is still open; finish its normal close/backup dialog locally')
    return result


def finish_batch(report_path, report, photoshop_session=None):
    if report.get('status')!='passed' or any(item.get('status')!='passed' for item in report['files']):
        return {'status':'skipped','reason':'Edits did not all succeed'}
    from .pipeline import job_lock
    result={'status':'completed','review_report':str(report_path)}
    try:
        with job_lock(ROOT/'.cache/photoshop.lock'):
            result['adobe']=close_adobe(report['catalog'],photoshop_session)
    except Exception as error:result['adobe']={'shutdown':{'status':'left open','reason':str(error)}}
    report['finish']=result;json_write(report_path,report)
    try:
        process=launch_review(report_path)
        result.update(review='launched',review_process_id=process.pid)
    except Exception as error:result.update(review='failed to open',review_error=str(error))
    json_write(report_path,report)
    return result
