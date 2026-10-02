"""Download verified releases and transactionally replace only app/."""
import base64
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import time
import urllib.request
import uuid
import zipfile

from .policy import CHANNEL_PATH, MAIN_EXE, MAX_DOWNLOAD, MAX_EXPANDED, REPOSITORY


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temp.replace(path)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def rename_retry(source, target):
    """Antivirus scanners may briefly hold freshly produced executables open."""
    for attempt in range(30):
        try:
            return source.rename(target)
        except PermissionError:
            if attempt == 29:
                raise
            time.sleep(.2)


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d+\.\d+\.\d+", value):
        raise ValueError("Invalid release version")
    return tuple(map(int, value.split(".")))


def request(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={
        "User-Agent": "MinecraftManager-Updater/1", "Cache-Control": "no-cache",
    }), timeout=30)


def channel():
    # The API returns current content; raw branch URLs can lag behind a publication.
    url = f"https://api.github.com/repos/{REPOSITORY}/contents/{CHANNEL_PATH}?ref=main&t={time.time_ns()}"
    try:
        with request(url) as response:
            data = json.loads(response.read(128 * 1024))
        manifest = json.loads(base64.b64decode(data["content"], validate=False))
    except Exception:
        with request(f"https://raw.githubusercontent.com/{REPOSITORY}/main/{CHANNEL_PATH}") as response:
            manifest = json.loads(response.read(65536))
    if manifest.get("schema") != 2 or manifest.get("protocol") != 1:
        raise ValueError("This release needs a newer updater. Download updater.exe from GitHub Releases.")
    version(manifest.get("version"))
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", manifest.get("state", "")):
        raise ValueError("Invalid update state")
    return manifest


def contained(root, path):
    root, path = Path(root).absolute(), Path(path).absolute()
    if not path.is_relative_to(root) or path == root:
        raise ValueError("Path is outside the installation")
    for item in [path, *path.parents]:
        if item.is_symlink() or item.is_junction():
            raise ValueError("Update paths must not contain junctions or symbolic links")
        if item == root:
            break
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Update path escaped its installation")
    return path


def download(asset, target, report):
    url = asset["url"]
    if not url.startswith(f"https://github.com/{REPOSITORY}/releases/download/"):
        raise ValueError("Release download is outside the configured GitHub repository")
    expected = asset["sha256"]
    if not re.fullmatch(r"[a-f0-9]{64}", expected):
        raise ValueError("Invalid download checksum")
    partial = target.with_suffix(target.suffix + ".part")
    digest, size = hashlib.sha256(), 0
    try:
        with request(url) as response, partial.open("wb") as output:
            total = int(response.headers.get("Content-Length", 0))
            while block := response.read(1024 * 1024):
                size += len(block)
                if size > MAX_DOWNLOAD:
                    raise ValueError("Download exceeds size limit")
                output.write(block)
                digest.update(block)
                report(f"Downloading: {size // (1024 * 1024)} MB" + (f" / {total // (1024 * 1024)} MB" if total else ""))
        if digest.hexdigest() != expected:
            raise ValueError("Download checksum mismatch; installed files were not changed")
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)


def unpack(archive, target, expected):
    with zipfile.ZipFile(archive) as package:
        files = [item for item in package.infolist() if not item.is_dir()]
        if len(files) > 5000 or sum(p.file_size for p in files) > MAX_EXPANDED:
            raise ValueError("Update archive is too large")
        seen = set()
        for item in files:
            name = item.filename
            parts = name.split("/")
            if ("\\" in name or ":" in name or
                any(p in ("", ".", "..") or p.rstrip(" .") != p for p in parts) or
                any(re.fullmatch(r"(?i)(con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\..*)?", p) for p in parts) or
                name.lower() in seen or (item.external_attr >> 16) & 0o170000 == 0o120000):
                raise ValueError("Unsafe archive path: " + name)
            if name not in (MAIN_EXE, "release-state.json") and not (parts[0] in ("_internal", "resources") and len(parts) > 1):
                raise ValueError("Archive contains a non-application file: " + name)
            seen.add(name.lower())
        if not {MAIN_EXE.lower(), "release-state.json"}.issubset(seen) or not any(n.startswith("_internal/") for n in seen):
            raise ValueError("Application package is incomplete")
        target.mkdir()
        for item in files:
            path = target.joinpath(*PurePosixPath(item.filename).parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            with package.open(item) as source, path.open("wb") as output:
                shutil.copyfileobj(source, output)
    stamp = read_json(target / "release-state.json")
    if stamp.get("state") != expected["state"] or stamp.get("version") != expected["version"]:
        raise ValueError("Package version does not match the update manifest")


class Installer:
    def __init__(self, root, report=lambda message: None):
        self.root = Path(root).resolve()
        self.app = contained(self.root, self.root / "app")
        self.folder = contained(self.root, self.root / "data/updates")
        self.folder.mkdir(parents=True, exist_ok=True)
        self.report = report
        self.journal = self.folder / "install-transaction.json"

    def current(self):
        try:
            return read_json(self.app / "release-state.json") if (self.app / MAIN_EXE).exists() else {}
        except (OSError, ValueError):
            return {}

    def needs_update(self, manifest):
        current = self.current()
        if current.get("version") and version(current["version"]) > version(manifest["version"]):
            return False
        return current.get("state") != manifest["state"]

    def prepare(self, manifest):
        stage = self.folder / ("download-" + uuid.uuid4().hex)
        stage.mkdir()
        archive = stage / "app.zip"
        download(manifest["assets"]["app"], archive, self.report)
        unpack(archive, stage / "app", manifest)
        archive.unlink()
        if not (self.root / "launcher.exe").exists():
            download(manifest["assets"]["launcher"], stage / "launcher.exe", self.report)
        return stage

    def recover_transaction(self):
        """Called under the application mutex. Never remove an unrecognized tree."""
        if not self.journal.exists():
            return
        transaction = read_json(self.journal)
        backup = contained(self.folder, Path(transaction["backup"]))
        if not self.app.exists() and backup.exists():
            rename_retry(backup, self.app)
        self.journal.replace(self.folder / "previous-transaction.json")

    def install(self, stage):
        contained(self.folder, stage)
        contained(self.root, self.app)
        if (self.root / "data/recovery.json").exists() or (self.root / "relay-recovery.json").exists():
            raise RuntimeError("An unfinished hosting session exists. Recover & Sync in the current application first.")
        self.recover_transaction()
        backup = self.folder / ("rollback-" + uuid.uuid4().hex)
        write_json(self.journal, {"backup": str(backup)})
        if self.app.exists():
            rename_retry(self.app, backup)
        try:
            rename_retry(stage / "app", self.app)
            launcher = contained(self.root, self.root / "launcher.exe")
            if not launcher.exists():
                rename_retry(stage / "launcher.exe", launcher)
            for name in ("data/server", "data/logs", "playit"):
                contained(self.root, self.root / name).mkdir(parents=True, exist_ok=True)
        except Exception:
            if self.app.exists():
                rename_retry(self.app, stage / "failed-app")
            if backup.exists():
                rename_retry(backup, self.app)
            raise
        self.journal.unlink()
        write_json(self.folder / "last-install.json", {"ok": True, **self.current()})
        cleanup = self.cleanup_legacy()
        self.report("Update installed. Starting Minecraft Manager...")
        return cleanup

    def cleanup_legacy(self):
        from .migration import archive_legacy
        try:
            return archive_legacy(self.root)
        except Exception as error:
            # A cleanup failure must not roll back a successfully installed app.
            message = "Legacy cleanup deferred: " + str(error)
            self.report(message)
            try:
                write_json(self.folder / "legacy-cleanup-error.json", {"error": str(error)})
            except OSError:
                pass
            return message
