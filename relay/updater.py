"""Small GitHub manifest check, verified staging, and deferred Windows install."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile

from PySide6.QtCore import QObject, Signal
from .paths import APP_DIR, DATA_DIR, VERSION

REPOSITORY = "ddvxaggshs/MinecraftServerTool"
MANIFEST_URL = f"https://raw.githubusercontent.com/{REPOSITORY}/main/update.json"
MAX_DOWNLOAD = 512 * 1024 * 1024
MAX_EXPANDED = 2 * 1024 * 1024 * 1024
ROOT_FILES = {"MinecraftRelay.py", "Run-Source.vbs", "Run-Source.bat", "Build-Windows.bat",
              "README.md", "README.txt", "apply-update.ps1", "release-state.json"}


def atomic_json(path, value):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temp.replace(path)


def safe_member(name, kind):
    """Only program files may be replaced; config, data and worlds are excluded."""
    if "\\" in name or ":" in name or name.startswith("/"):
        return False
    parts = name.split("/")
    if any(p in ("", ".", "..") or p.rstrip(" .") != p for p in parts):
        return False
    if any(re.fullmatch(r"(?i)(con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\..*)?", p) for p in parts):
        return False
    if kind == "windows":
        return name in {"MinecraftRelay.exe", "apply-update.ps1", "release-state.json", "README.md", "README.txt"} or parts[0] == "_internal" and len(parts) > 1
    return name in ROOT_FILES or (parts[0] in {"relay", "tools"} and len(parts) > 1 and name.endswith(".py"))


def unpack_verified(archive, destination, kind):
    with zipfile.ZipFile(archive) as z:
        entries = [item for item in z.infolist() if not item.is_dir()]
        if len(entries) > 5000 or sum(item.file_size for item in entries) > MAX_EXPANDED:
            raise ValueError("Update archive is too large")
        seen = set()
        for item in entries:
            name = item.filename
            if not safe_member(name, kind) or name.lower() in seen:
                raise ValueError(f"Unsafe or duplicate update path: {name}")
            if (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Update archives cannot contain symbolic links")
            seen.add(name.lower())
        required = {"release-state.json", "apply-update.ps1"}
        required.add("MinecraftRelay.exe" if kind == "windows" else "MinecraftRelay.py")
        if kind == "source":
            required.add("relay/app.py")
        elif not any(name.startswith("_internal/") for name in seen):
            raise ValueError("Windows runtime files are missing")
        if not {s.lower() for s in required}.issubset(seen):
            raise ValueError("Incomplete update package")
        destination.mkdir(parents=True, exist_ok=False)
        files = []
        for item in entries:
            target = destination.joinpath(*PurePosixPath(item.filename).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(item) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            files.append({"path": item.filename, "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
        return files


class UpdateManager(QObject):
    status = Signal(str)

    def __init__(self, parent=None, app_dir=APP_DIR, data_dir=DATA_DIR):
        super().__init__(parent)
        self.app_dir = Path(app_dir).resolve()
        self.folder = Path(data_dir).resolve() / "updates"
        self.kind = "windows" if getattr(sys, "frozen", False) else "source"
        self._started = False
        self.ready = False

    def start(self):
        if self._started:
            return
        self._started = True
        threading.Thread(target=self._check, daemon=True).start()

    def local_state(self):
        try:
            return json.loads((self.app_dir / "release-state.json").read_text(encoding="utf-8"))["state"]
        except (OSError, ValueError, KeyError):
            return VERSION

    def _request(self, url):
        request = urllib.request.Request(url, headers={"User-Agent": f"MinecraftRelay/{VERSION}", "Cache-Control": "no-cache"})
        return urllib.request.urlopen(request, timeout=20)

    def _check(self):
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            pending = self.folder / "pending.json"
            if pending.exists():
                plan = json.loads(pending.read_text(encoding="utf-8"))
                if plan.get("state") != self.local_state() and plan.get("kind") == self.kind:
                    self.ready = True
                    self.status.emit("Update downloaded; will install after normal exit.")
                    return
            self.status.emit("Checking for application updates…")
            with self._request(MANIFEST_URL) as response:
                raw = response.read(65537)
            if len(raw) > 65536:
                raise ValueError("Update manifest is too large")
            manifest = json.loads(raw)
            if manifest.get("schema") != 1:
                raise ValueError("Unsupported update manifest")
            state = manifest.get("state")
            if not isinstance(state, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", state):
                raise ValueError("Invalid release state")
            if state == self.local_state():
                self.status.emit("Application is up to date.")
                return
            asset = manifest.get("assets", {}).get(self.kind)
            if not asset:
                self.status.emit("A new version is listed; its package has not been published yet.")
                return
            url = asset["url"]
            parsed = urllib.parse.urlsplit(url)
            if parsed.scheme != "https" or parsed.netloc != "github.com" or not parsed.path.startswith(f"/{REPOSITORY}/releases/download/"):
                raise ValueError("Update package must come from this application's GitHub Releases")
            digest = asset["sha256"].lower()
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("Invalid package checksum")
            self.status.emit(f"Downloading application update {manifest.get('version', state)}…")
            download = self.folder / (uuid.uuid4().hex + ".zip.part")
            try:
                hash_ = hashlib.sha256()
                size = 0
                with self._request(url) as response, download.open("wb") as output:
                    while chunk := response.read(1024 * 1024):
                        size += len(chunk)
                        if size > MAX_DOWNLOAD:
                            raise ValueError("Update download exceeds the size limit")
                        hash_.update(chunk)
                        output.write(chunk)
                if hash_.hexdigest() != digest:
                    raise ValueError("Update checksum mismatch; keeping the current version")
                stage = self.folder / ("stage-" + uuid.uuid4().hex)
                files = unpack_verified(download, stage, self.kind)
                stamp = json.loads((stage / "release-state.json").read_text(encoding="utf-8"))
                if stamp.get("state") != state:
                    raise ValueError("Package state does not match the manifest")
                atomic_json(pending, {"schema": 1, "state": state, "kind": self.kind,
                                     "app_dir": str(self.app_dir), "stage": str(stage), "files": files})
            finally:
                download.unlink(missing_ok=True)
            self.ready = True
            self.status.emit("Update downloaded; will install after normal exit. Your data is preserved.")
        except urllib.error.HTTPError as error:
            if error.code == 404:
                self.status.emit("No update has been published yet.")
            else:
                self.status.emit(f"Update check unavailable ({error.code}); using current version.")
        except Exception as error:
            self.status.emit(f"Update check failed; using current version. {error}")

    def install_after_exit(self):
        if not self.ready or os.name != "nt":
            return
        # Run a copy: the package may replace the original installer itself.
        helper = self.folder / "apply-update.ps1"
        shutil.copy2(self.app_dir / "apply-update.ps1", helper)
        powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        subprocess.Popen([str(powershell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                          "-File", str(helper), "-PlanPath", str(self.folder / "pending.json"),
                          "-ParentProcessId", str(os.getpid())],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True)
