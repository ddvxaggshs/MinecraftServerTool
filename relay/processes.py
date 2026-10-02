import os, re, shutil, subprocess, threading, time, ctypes, queue
from pathlib import Path
from ctypes import wintypes
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QProgressDialog

class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_=[
        ("PerProcessUserTimeLimit",ctypes.c_longlong),
        ("PerJobUserTimeLimit",ctypes.c_longlong),
        ("LimitFlags",wintypes.DWORD),
        ("MinimumWorkingSetSize",ctypes.c_size_t),
        ("MaximumWorkingSetSize",ctypes.c_size_t),
        ("ActiveProcessLimit",wintypes.DWORD),
        ("Affinity",ctypes.c_size_t),
        ("PriorityClass",wintypes.DWORD),
        ("SchedulingClass",wintypes.DWORD)
    ]


class IO_COUNTERS(ctypes.Structure):
    _fields_=[
        ("ReadOperationCount",ctypes.c_ulonglong),
        ("WriteOperationCount",ctypes.c_ulonglong),
        ("OtherOperationCount",ctypes.c_ulonglong),
        ("ReadTransferCount",ctypes.c_ulonglong),
        ("WriteTransferCount",ctypes.c_ulonglong),
        ("OtherTransferCount",ctypes.c_ulonglong)
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_=[
        ("BasicLimitInformation",JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo",IO_COUNTERS),
        ("ProcessMemoryLimit",ctypes.c_size_t),
        ("JobMemoryLimit",ctypes.c_size_t),
        ("PeakProcessMemoryUsed",ctypes.c_size_t),
        ("PeakJobMemoryUsed",ctypes.c_size_t)
    ]


class WindowsJob:
    """Kill assigned child processes automatically when Relay dies/closes its job handle."""
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE=0x00002000
    JobObjectExtendedLimitInformation=9

    def __init__(self):
        self.handle=None
        if os.name!="nt": return
        self.k=ctypes.WinDLL("kernel32",use_last_error=True)

        # Explicit signatures are important on 64-bit Windows: HANDLE is pointer-sized.
        self.k.CreateJobObjectW.argtypes=[ctypes.c_void_p,wintypes.LPCWSTR]
        self.k.CreateJobObjectW.restype=wintypes.HANDLE
        self.k.SetInformationJobObject.argtypes=[
            wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD
        ]
        self.k.SetInformationJobObject.restype=wintypes.BOOL
        self.k.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        self.k.OpenProcess.restype=wintypes.HANDLE
        self.k.AssignProcessToJobObject.argtypes=[wintypes.HANDLE,wintypes.HANDLE]
        self.k.AssignProcessToJobObject.restype=wintypes.BOOL
        self.k.CloseHandle.argtypes=[wintypes.HANDLE]
        self.k.CloseHandle.restype=wintypes.BOOL

        self.handle=self.k.CreateJobObjectW(None,None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())

        info=JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags=self.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.k.SetInformationJobObject(
            self.handle,self.JobObjectExtendedLimitInformation,
            ctypes.byref(info),ctypes.sizeof(info)
        ):
            err=ctypes.get_last_error()
            self.k.CloseHandle(self.handle); self.handle=None
            raise ctypes.WinError(err)

    def assign(self,proc):
        if not self.handle:return
        PROCESS_SET_QUOTA=0x0100
        PROCESS_TERMINATE=0x0001
        h=self.k.OpenProcess(PROCESS_SET_QUOTA|PROCESS_TERMINATE,False,proc.pid)
        if not h:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not self.k.AssignProcessToJobObject(self.handle,h):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            self.k.CloseHandle(h)

    def close(self):
        if self.handle:
            self.k.CloseHandle(self.handle)
            self.handle=None


def run(cmd,cwd=None,timeout=60,input=None):
    return subprocess.run(cmd,cwd=cwd,text=True,encoding="utf-8",errors="replace",
                          capture_output=True,timeout=timeout,input=input,
                          creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)

def run_gui(cmd,cwd=None,timeout=60):
    """Keep Qt painting while a modal Git operation runs on a worker thread."""
    result=queue.Queue()
    def work():
        try:result.put((run(cmd,cwd,timeout),None))
        except Exception as e:result.put((None,e))
    dialog=QProgressDialog("Waiting for Git… Complete browser authentication if prompted.",
                           "",0,0,QApplication.activeWindow())
    dialog.setCancelButton(None)
    dialog.setWindowTitle("Git operation")
    dialog.setWindowModality(Qt.ApplicationModal)
    dialog.setWindowFlag(Qt.WindowCloseButtonHint,False)
    # Prevent Escape/close from abandoning an operation that may still write files.
    dialog.reject=lambda: None
    outcome=[]
    def poll():
        try:value=result.get_nowait()
        except queue.Empty:return
        outcome.append(value)
        timer.stop()
        dialog.accept()
    timer=QTimer(dialog)
    timer.timeout.connect(poll)
    timer.start(25)
    threading.Thread(target=work,daemon=True).start()
    dialog.exec()
    value,error=outcome[0]
    if error:raise error
    return value
def which(name): return shutil.which(name)
def find_playit():
    for p in [r"C:\Program Files\playit_gg\bin\playit.exe",
              r"C:\Program Files\playit\playit.exe", which("playit")]:
        if p and Path(p).exists(): return str(p)
    return None
_java_cache={"path":None,"result":None,"expires":0}
def java21():
    p=which("java")
    if not p:return None
    if p==_java_cache["path"] and time.monotonic()<_java_cache["expires"]:
        return _java_cache["result"]
    try:
        r=run([p,"-version"],timeout=10)
        s=r.stderr+r.stdout
        m=re.search(r'version "(\d+)',s)
        result=p if r.returncode==0 and m and int(m.group(1))>=21 else None
        _java_cache.update(path=p,result=result,expires=time.monotonic()+15)
        return result
    except:return None
def winget_install(pkg):
    return subprocess.Popen(["winget","install","--id",pkg,"-e",
        "--accept-source-agreements","--accept-package-agreements"],
        creationflags=subprocess.CREATE_NEW_CONSOLE)
