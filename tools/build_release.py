"""Build both update assets and their small manifest; never delete user data."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parent.parent


def build(state=None):
    tree = ast.parse((ROOT / "relay/paths.py").read_text(encoding="utf-8"))
    version = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "VERSION" for t in n.targets))
    stamp = json.loads((ROOT / "release-state.json").read_text(encoding="utf-8"))
    if stamp["version"] != version:
        raise ValueError("relay/paths.py VERSION and release-state.json version must agree")
    if state and state != stamp["state"]:
        raise ValueError("Tag version must match release-state.json state")
    state = stamp["state"]
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", state) or state in (".", ".."):
        raise ValueError("Invalid release state")
    output = ROOT / "dist" / state
    work = ROOT / "build" / state
    if (output / "MinecraftRelay/data").exists():
        raise RuntimeError("Build output contains user data. Move it to a separate installation before rebuilding.")
    work.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--windowed", "--onedir",
                    "--name", "MinecraftRelay", "--distpath", str(output), "--workpath", str(work),
                    "--specpath", str(work), str(ROOT / "MinecraftRelay.py")], cwd=ROOT, check=True)
    app = output / "MinecraftRelay"
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
                z.write(path, path.relative_to(relative_to))
        with ZipFile(archive) as z:
            if z.testzip():
                raise RuntimeError("Archive integrity check failed")
        assets[kind] = {"url": f"https://github.com/ddvxaggshs/MinecraftServerTool/releases/download/v{state}/{archive.name}",
                        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}
    manifest = {"schema": 1, "state": state, "version": version, "assets": assets}
    (output / "update.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Release built: {output}\nPublish both ZIPs before updating main/update.json.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--state")
    build(parser.parse_args().state)
