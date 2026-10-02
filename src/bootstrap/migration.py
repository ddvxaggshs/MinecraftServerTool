"""Archive known old application files, never user data or arbitrary root files."""
import json
from pathlib import Path
import time
import uuid

from .engine import contained, read_json, rename_retry, write_json
from .policy import LEGACY_PROGRAM_FILES, LEGACY_PROGRAM_DIRECTORIES


def archive_legacy(root):
    """Run only after installation succeeds, while holding the installation mutex.

    Moves are reversible. Persist the legacy marker before moving its EXE so that
    an interrupted/partially locked cleanup can safely retry on the next manual run.
    """
    root = Path(root).resolve()
    report_path = contained(root, root / "data/updates/legacy-cleanup.json")
    if any((root / name).exists() for name in (".git", "src", "tools")):
        return "Development checkout: legacy cleanup skipped."
    marker = root / "MinecraftRelay.exe"
    source_marker = root / "MinecraftRelay.py"
    previous = {}
    if report_path.exists():
        previous = read_json(report_path)
    legacy_found = marker.is_file() or (source_marker.is_file() and (root / "relay/app.py").is_file())
    if not legacy_found and not previous.get("detected"):
        return ""
    if (root / "data/recovery.json").exists() or (root / "relay-recovery.json").exists():
        return "Legacy cleanup deferred: unfinished recovery session."

    protected_paths = []
    # Preserve configured server and Playit locations even if someone put them
    # inside a legacy runtime directory. Both config generations remain untouched.
    for config in (root / "config.json", root / "data/config.json"):
        if config.exists():
            values = read_json(config)
            if not isinstance(values, dict):
                raise ValueError("Cannot verify legacy user-data locations: invalid config.json")
            for key in ("server_dir", "playit_command"):
                value = values.get(key)
                if value:
                    path = Path(value)
                    protected_paths.append((path if path.is_absolute() else root / path).resolve())

    report = {"detected": True, "moved": [], "skipped": [], "errors": [],
              "previous_archives": previous.get("previous_archives", [])}
    if previous.get("archive"):
        report["previous_archives"].append(previous["archive"])
    # Crash-safe marker; candidate names never come from the report itself.
    write_json(report_path, report)
    archive = None
    names = sorted(LEGACY_PROGRAM_FILES | LEGACY_PROGRAM_DIRECTORIES)
    for name in names:
        source = root / name
        if not source.exists() and not source.is_symlink():
            continue
        try:
            contained(root, source)
            if name in LEGACY_PROGRAM_FILES and not source.is_file():
                report["skipped"].append(name)
                continue
            if name in LEGACY_PROGRAM_DIRECTORIES:
                if not source.is_dir():
                    report["skipped"].append(name)
                    continue
                # An unexpected data folder or junction inside the runtime is
                # retained in place, rather than moving it along with code.
                unsafe = any(p.is_symlink() or p.is_junction() or
                             p.name.lower() in {"data", "world", "world_nether", "world_the_end",
                                                "playit", "server", "recovery-backups"}
                             for p in source.rglob("*"))
                if unsafe:
                    report["skipped"].append(name)
                    continue
            resolved = source.resolve()
            if any(p == resolved or p.is_relative_to(resolved) for p in protected_paths):
                report["skipped"].append(name)
                continue
            if archive is None:
                archive = contained(root, root / "expired" / ("legacy-" + time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]))
                archive.mkdir(parents=True)
                report["archive"] = str(archive.relative_to(root))
                write_json(report_path, report)
            rename_retry(source, archive / name)
            report["moved"].append(name)
        except (OSError, ValueError) as error:
            report["errors"].append({"file": name, "error": str(error)})
        write_json(report_path, report)
    if report["errors"] or report["skipped"]:
        return "Some legacy files were retained; see data/updates/legacy-cleanup.json."
    return "Legacy program files archived to expired/." if report["moved"] else ""
