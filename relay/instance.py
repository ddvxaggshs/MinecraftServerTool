"""One application/updater per installation directory."""
import ctypes
from ctypes import wintypes
import hashlib
import os

from .paths import APP_DIR


class InstanceGuard:
    def __init__(self):
        self.handle = None
        if os.name != "nt":
            return
        key = hashlib.sha256(str(APP_DIR.resolve()).rstrip("\\").lower().encode("utf-8")).hexdigest()
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel.CreateMutexW.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.handle = self.kernel.CreateMutexW(None, True, "Local\\MinecraftRelay-" + key)
        error = ctypes.get_last_error()
        if not self.handle:
            raise ctypes.WinError(error)
        if error == 183:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
            raise RuntimeError("Minecraft Relay is already running or installing an update in this folder.")

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
