"""Build a main EXE and a separate updater, with a shared runtime under dist/."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from relay.update_policy import REPOSITORY, protected


def remove_build_tree(path):
    resolved = path.resolve()
    if not resolved.is_relative_to((ROOT / "build").resolve()) or resolved == (ROOT / "build").resolve():
        raise RuntimeError("Refusing to delete outside the generated build directory")
    if path.exists():
        shutil.rmtree(path)


def build(state=None):
    tree = ast.parse((ROOT / "relay/paths.py").read_text(encoding="utf-8"))
    version = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "VERSION" for t in n.targets))
    stamp = json.loads((ROOT / "release-state.json").read_text(encoding="utf-8"))
    if stamp["version"] != version or (state and state != stamp["state"]):
        raise ValueError("Source version and release-state.json must agree")
    state = stamp["state"]
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", state) or state in (".", ".."):
        raise ValueError("Invalid release state")
    output = ROOT / "dist"
    work = ROOT / "build" / state
    staging = work / ("package-" + uuid.uuid4().hex)
    work.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    common = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--windowed", "--onedir",
              "--distpath", str(staging), "--workpath", str(work / "cache"),
              "--specpath", str(work), "--paths", str(ROOT)]
    subprocess.run(common + ["--name", "MinecraftRelay", str(ROOT / "MinecraftRelay.py")], cwd=ROOT, check=True)
    subprocess.run(common + ["--name", "MinecraftRelayUpdater", "--contents-directory", ".",
                             str(ROOT / "tools/updater_entry.py")], cwd=ROOT, check=True)
    app = staging / "MinecraftRelay"
    # The main application already carries the updater's imports. Preserve its
    # broader base_library.zip; only add dependencies not present there yet.
    for path in (staging / "MinecraftRelayUpdater").rglob("*"):
        if path.is_file():
            target = app / "_internal" / path.relative_to(staging / "MinecraftRelayUpdater")
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
    for name in ("apply-update.ps1", "release-state.json", "README.md"):
        shutil.copy2(ROOT / name, app / name)
    assets = {}
    source_files = [ROOT / n for n in ("MinecraftRelay.py", "Run-Source.vbs", "Run-Source.bat",
                    "Build-Windows.bat", "apply-update.ps1", "release-state.json", "README.md")]
    for folder in ("relay", "tools"):
        source_files.extend((ROOT / folder).rglob("*.py"))
    for kind in ("source", "windows"):
        archive = output / f"MinecraftRelay-{kind}.zip"
        files = source_files if kind == "source" else [p for p in app.rglob("*") if p.is_file()]
        relative_to = ROOT if kind == "source" else app
        with ZipFile(archive, "w", ZIP_DEFLATED) as z:
            for path in sorted(files):
                name = path.relative_to(relative_to).as_posix()
                if protected(name):
                    raise RuntimeError("Protected file found in package: " + name)
                z.write(path, name)
        with ZipFile(archive) as z:
            if z.testzip():
                raise RuntimeError("Archive integrity check failed")
        assets[kind] = {"url": f"https://github.com/{REPOSITORY}/releases/download/v{state}/{archive.name}",
                        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}
    # Preserve personal files in an existing dist installation, but never zip them.
    destination = output / "MinecraftRelay"
    if destination.exists():
        for path in destination.iterdir():
            if protected(path.name):
                target = app / path.name
                if path.is_dir():
                    shutil.copytree(path, target)
                else:
                    shutil.copy2(path, target)
    previous = work / ("previous-" + uuid.uuid4().hex)
    if destination.exists():
        destination.rename(previous)
    try:
        app.rename(destination)
    except Exception:
        if previous.exists():
            previous.rename(destination)
        raise
    remove_build_tree(previous)
    remove_build_tree(staging)
    manifest = {"schema": 1, "state": state, "version": version, "assets": assets}
    (output / "update.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Built {state}: {destination}\nRelease assets: {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--state")
    build(parser.parse_args().state)
