"""A native Windows HEAD probe. Never reads or sends local files or notes."""
import ctypes
from ctypes import wintypes as w

def probe():
    api = ctypes.WinDLL('winhttp', use_last_error=True)
    signatures = {
        'WinHttpOpen': ([w.LPCWSTR,w.DWORD,w.LPCWSTR,w.LPCWSTR,w.DWORD],w.HANDLE),
        'WinHttpConnect': ([w.HANDLE,w.LPCWSTR,w.WORD,w.DWORD],w.HANDLE),
        'WinHttpOpenRequest': ([w.HANDLE,w.LPCWSTR,w.LPCWSTR,w.LPCWSTR,w.LPCWSTR,ctypes.c_void_p,w.DWORD],w.HANDLE),
        'WinHttpSetTimeouts': ([w.HANDLE,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int],w.BOOL),
        'WinHttpSendRequest': ([w.HANDLE,w.LPCWSTR,w.DWORD,ctypes.c_void_p,w.DWORD,w.DWORD,ctypes.c_size_t],w.BOOL),
        'WinHttpReceiveResponse': ([w.HANDLE,ctypes.c_void_p],w.BOOL),
        'WinHttpCloseHandle': ([w.HANDLE],w.BOOL),
    }
    for name,(args,result) in signatures.items():
        function=getattr(api,name); function.argtypes=args; function.restype=result
    handles=[]
    result={'api':'native WinHTTP', 'method':'HEAD', 'url':'https://www.microsoft.com/', 'connected':False}
    try:
        session=api.WinHttpOpen('PhotoWorkflow-OfflineVerification/1.0',1,None,None,0)
        if not session: raise ctypes.WinError(ctypes.get_last_error())
        handles.append(session); api.WinHttpSetTimeouts(session,3000,3000,3000,3000)
        connection=api.WinHttpConnect(session,'www.microsoft.com',443,0)
        if not connection: raise ctypes.WinError(ctypes.get_last_error())
        handles.append(connection)
        request=api.WinHttpOpenRequest(connection,'HEAD','/',None,None,None,0x800000)
        if not request: raise ctypes.WinError(ctypes.get_last_error())
        handles.append(request)
        if not api.WinHttpSendRequest(request,None,0,None,0,0,0):
            result.update(stage='send',winerror=ctypes.get_last_error()); return result
        if not api.WinHttpReceiveResponse(request,None):
            result.update(stage='receive',winerror=ctypes.get_last_error()); return result
        result.update(connected=True,stage='response',winerror=0); return result
    finally:
        for handle in reversed(handles): api.WinHttpCloseHandle(handle)

def executable():
    buffer=ctypes.create_unicode_buffer(32768)
    ctypes.windll.kernel32.GetModuleFileNameW(None,buffer,len(buffer))
    return buffer.value
