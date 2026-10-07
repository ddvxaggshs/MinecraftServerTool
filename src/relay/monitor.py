"""Local server metrics. Counts come from commands, never name heuristics."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import re
import time
import uuid


def memory_bytes(proc):
    if os.name != "nt" or proc.poll() is not None:
        return None
    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize",
            "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
            "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage", "PrivateUsage")]
    api = ctypes.WinDLL("psapi", use_last_error=True)
    api.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    api.GetProcessMemoryInfo.restype = wintypes.BOOL
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    # Use Popen's original process handle, not a PID that might have been reused.
    if not api.GetProcessMemoryInfo(wintypes.HANDLE(int(proc._handle)), ctypes.byref(counters), counters.cb):
        return None
    return counters.WorkingSetSize


LIST_PATTERN = re.compile(r"^There are (\d+) of a max of (\d+) players online:")


class PlayerMonitor:
    def __init__(self, directory):
        self.carpet = any("carpet" in p.name.lower() for p in (Path(directory) / "mods").glob("*.jar"))
        self.retry_carpet_at = 0

    def read(self, session):
        if self.carpet and time.monotonic() >= self.retry_carpet_at:
            token = "RELAY_STATS_" + uuid.uuid4().hex
            # Both normal fakes and shadow replacements are Carpet fake players.
            expression = ("'" + token + "|'+length(player('all'))+'|'+"
                          "length(filter(player('all'),query(_,'player_type')=='fake'||"
                          "query(_,'player_type')=='shadow'))")
            pattern = re.compile(re.escape(token) + r"\|(\d+)\|(\d+)(?![\d|])")
            try:
                def valid(message):
                    # Carpet returns '= value' (some versions append evaluation time).
                    return message.lstrip().startswith(("= ", token)) and pattern.search(message) is not None
                result = session.request("script run " + expression, valid, timeout=6, quiet=True)
                total, fake = map(int, pattern.search(result).groups())
                if not 0 <= fake <= total <= 100000:
                    raise ValueError("Invalid player counts")
                return {"total": total, "fake": fake, "real": total - fake, "source": "Carpet"}
            except (TimeoutError, ValueError):
                # Disabled/incompatible Scarpet is not evidence that zero bots exist.
                self.retry_carpet_at = time.monotonic() + 60
        result = session.request("list", lambda msg: LIST_PATTERN.match(msg) is not None, timeout=6, quiet=True)
        total, maximum = map(int, LIST_PATTERN.match(result).groups())
        return {"total": total, "fake": None, "real": None, "maximum": maximum, "source": "list"}
