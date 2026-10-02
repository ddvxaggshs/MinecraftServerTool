"""Windows handles shared by launcher, updater and main application."""
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import subprocess
import sys


def installation_root():
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]


def kernel32():
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    k.CreateMutexW.restype = wintypes.HANDLE
    k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k.WaitForSingleObject.restype = wintypes.DWORD
    k.ReleaseMutex.argtypes = [wintypes.HANDLE]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.OpenProcess.restype = wintypes.HANDLE
    return k


class Mutex:
    def __init__(self, root, role="MinecraftRelay", timeout=0):
        self.handle = None
        self.k = kernel32()
        key = hashlib.sha256(str(Path(root).resolve()).rstrip("\\").lower().encode()).hexdigest()
        handle = self.k.CreateMutexW(None, False, "Local\\" + role + "-" + key)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        result = self.k.WaitForSingleObject(handle, timeout)
        if result not in (0, 0x80):
            self.k.CloseHandle(handle)
            raise RuntimeError("Another application or updater is using this installation. Close it and try again.")
        self.handle = handle

    def close(self):
        if self.handle:
            self.k.ReleaseMutex(self.handle)
            self.k.CloseHandle(self.handle)
            self.handle = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class ParentProcess:
    """Capture a process handle once; cannot confuse an exited process with PID reuse."""
    def __init__(self, pid):
        self.k = kernel32()
        self.handle = self.k.OpenProcess(0x100000, False, pid)
        if not self.handle:
            raise RuntimeError("The main process is no longer available; update cancelled.")

    def exited(self):
        return self.k.WaitForSingleObject(self.handle, 0) == 0

    def close(self):
        if self.handle:
            self.k.CloseHandle(self.handle)
            self.handle = None


def spawn(command, root):
    return subprocess.Popen(command, cwd=root, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)


def show_error(message):
    ctypes.windll.user32.MessageBoxW(None, str(message), "Minecraft Manager", 0x10)
