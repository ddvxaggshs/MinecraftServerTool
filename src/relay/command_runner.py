"""Bounded, windowless commands; timeouts terminate this command's descendants."""
import ctypes
from ctypes import wintypes
import os
import signal
import subprocess
import tempfile
import time
from .process_job import WindowsJob


def _resume_suspended(pid):
    # Popen closes CreateProcess's primary thread handle. Reopen that thread while
    # it is still suspended, after the process has been assigned to its job.
    class ThreadEntry(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("usage", wintypes.DWORD),
                    ("tid", wintypes.DWORD), ("pid", wintypes.DWORD),
                    ("priority", wintypes.LONG), ("delta", wintypes.LONG),
                    ("flags", wintypes.DWORD)]
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    for name in ("Thread32First", "Thread32Next"):
        method = getattr(k, name)
        method.argtypes = [wintypes.HANDLE, ctypes.POINTER(ThreadEntry)]
        method.restype = wintypes.BOOL
    k.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.OpenThread.restype = wintypes.HANDLE
    k.ResumeThread.argtypes = [wintypes.HANDLE]
    k.ResumeThread.restype = wintypes.DWORD
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.CloseHandle.restype = wintypes.BOOL
    snapshot = k.CreateToolhelp32Snapshot(0x00000004, 0)  # TH32CS_SNAPTHREAD
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = ThreadEntry()
        entry.size = ctypes.sizeof(entry)
        found = k.Thread32First(snapshot, ctypes.byref(entry))
        while found:
            if entry.pid == pid:
                thread = k.OpenThread(0x0002, False, entry.tid)  # THREAD_SUSPEND_RESUME
                if not thread:
                    raise ctypes.WinError(ctypes.get_last_error())
                try:
                    if k.ResumeThread(thread) == 0xFFFFFFFF:
                        raise ctypes.WinError(ctypes.get_last_error())
                    return
                finally:
                    k.CloseHandle(thread)
            found = k.Thread32Next(snapshot, ctypes.byref(entry))
        raise RuntimeError("Could not resume the command's primary thread")
    finally:
        k.CloseHandle(snapshot)


def run(cmd, cwd=None, timeout=60, input=None, progress=None):
    started = time.monotonic()
    job = WindowsJob()
    proc = None
    # Disk-backed output prevents descendants holding a PIPE open from turning a
    # TimeoutExpired into an unbounded communicate() wait on Windows.
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err, tempfile.TemporaryFile() as stdin:
        if input is not None:
            stdin.write(input.encode("utf-8"))
            stdin.seek(0)
        try:
            flags = (subprocess.CREATE_NO_WINDOW | 0x00000004) if os.name == "nt" else 0
            proc = subprocess.Popen(cmd, cwd=cwd, stdin=stdin, stdout=out, stderr=err,
                                    creationflags=flags, start_new_session=os.name != "nt")
            if os.name == "nt":
                job.assign(proc)
                _resume_suspended(proc.pid)
            while True:
                elapsed = time.monotonic() - started
                if timeout is not None and elapsed >= timeout:
                    raise subprocess.TimeoutExpired(cmd, timeout)
                try:
                    proc.wait(timeout=min(15, timeout - elapsed) if timeout is not None else 15)
                    break
                except subprocess.TimeoutExpired:
                    if progress:
                        progress(int(time.monotonic() - started))
        finally:
            # Also removes command-owned helpers after a successful root exit.
            # Never taskkill all git.exe processes: other applications may use Git.
            job.close()
            if proc is not None:
                if os.name != "nt":
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                if proc.poll() is None:
                    proc.kill()
                proc.wait(timeout=5)
        def read(stream):
            stream.seek(0)
            return stream.read().decode("utf-8", errors="replace").replace("\r\n", "\n")
        return subprocess.CompletedProcess(cmd, proc.returncode, read(out), read(err))
