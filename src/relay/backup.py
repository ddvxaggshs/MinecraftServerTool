"""Local world snapshots; online snapshots require save-off/flush acknowledgements."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import uuid
import zipfile


def world_directories(directory):
    root = Path(directory).resolve()
    name = "world"
    properties = root / "server.properties"
    if properties.exists():
        for line in properties.read_text(encoding="utf-8", errors="replace").splitlines():
            match = re.match(r"^\s*level-name\s*[=:]\s*(.*?)\s*$", line)
            if match:
                name = match.group(1)
                break
    # Common Java-properties escapes, including names containing Unicode.
    name = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), name)
    name = re.sub(r"\\([ :=#!\\])", r"\1", name)
    if not name or Path(name).is_absolute() or ".." in Path(name).parts:
        raise ValueError("World folder must be inside the configured server directory")
    worlds = []
    for value in (name, name + "_nether", name + "_the_end"):
        path = root / value
        if path.is_symlink() or path.is_junction() or not path.resolve().is_relative_to(root) or path.resolve() == root:
            raise ValueError("World folder must not point outside the server directory")
        if path.is_dir():
            worlds.append(path)
    if not worlds or worlds[0] != root / name:
        raise RuntimeError("Configured world folder does not exist yet")
    return root, worlds


def inventory(root, worlds):
    files = {}
    for world in worlds:
        for path in world.rglob("*"):
            if path.is_symlink() or path.is_junction():
                raise RuntimeError("Backup does not follow linked world files: " + str(path))
            if path.is_file() and path.name != "session.lock":
                if not path.resolve().is_relative_to(root):
                    raise RuntimeError("World file escapes the server directory")
                stat = path.stat()
                files[path] = (stat.st_size, stat.st_mtime_ns)
    if not files:
        raise RuntimeError("World contains no files to back up")
    return files


def create_snapshot(directory, destination, progress=lambda done, total: None, check=lambda: None):
    root, worlds = world_directories(directory)
    destination = Path(destination).resolve()
    if any(destination.is_relative_to(world.resolve()) for world in worlds):
        raise RuntimeError("Backup destination cannot be inside the world")
    destination.mkdir(parents=True, exist_ok=True)
    stem = "world-manual-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    target, partial = destination / (stem + ".zip"), destination / (stem + ".zip.part")
    files = inventory(root, worlds)
    try:
        with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as archive:
            for count, (path, signature) in enumerate(files.items(), 1):
                check()
                stat = path.stat()
                if signature != (stat.st_size, stat.st_mtime_ns):
                    raise RuntimeError("World changed during backup; retry after stopping the server")
                archive.write(path, path.relative_to(root).as_posix())
                progress(count, len(files))
            check()
            if files != inventory(root, worlds):
                raise RuntimeError("World changed during backup; incomplete snapshot discarded")
            archive.writestr("_relay-backup.json", json.dumps({"created_at": datetime.now(timezone.utc).isoformat(),
                "worlds": [p.relative_to(root).as_posix() for p in worlds], "kind": "manual"}, indent=2))
        partial.replace(target)
        return target
    finally:
        partial.unlink(missing_ok=True)


class ResumeSavingError(RuntimeError):
    pass


def online_snapshot(session, directory, destination, progress=lambda done, total: None):
    result = None
    try:
        session.request("save-off", lambda m: m in ("Automatic saving is now disabled", "Saving is already turned off"), timeout=15)
        session.request("save-all flush", lambda m: m == "Saved the game", timeout=120)
        def check():
            if session.closed or session.proc.poll() is not None:
                raise RuntimeError("Server exited during backup; snapshot cancelled")
        result = create_snapshot(directory, destination, progress, check)
        return result
    finally:
        # Even a timeout or disk-full error must not leave autosaving disabled.
        if session.proc.poll() is None:
            try:
                session.request("save-on", lambda m: m in ("Automatic saving is now enabled", "Saving is already turned on"), timeout=15)
            except Exception as error:
                raise ResumeSavingError("Could not confirm save-on. Use STOP & SYNC before closing. " +
                    ("Snapshot: " + str(result) if result else "Backup did not finish.")) from error
