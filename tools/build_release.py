"""Build the self-contained bootstrap tools and the replaceable application."""
import ast
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from bootstrap.policy import REPOSITORY, MAIN_EXE
from bootstrap.engine import rename_retry


def archive_files(archive, files, base):
    with ZipFile(archive, "w", ZIP_DEFLATED) as package:
        for path in sorted(files):
            if path.is_file():
                package.write(path, path.relative_to(base).as_posix())
    with ZipFile(archive) as package:
        if package.testzip():
            raise RuntimeError("Archive integrity check failed")


def build(state=None):
    stamp = json.loads((ROOT / "release-state.json").read_text(encoding="utf-8"))
    tree = ast.parse((ROOT / "src/relay/paths.py").read_text(encoding="utf-8"))
    version = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "VERSION" for t in n.targets))
    if stamp["version"] != version or (state and state != stamp["state"]):
        raise ValueError("Source and release versions must agree")
    state = stamp["state"]
    from bootstrap.engine import version as validate_version
    validate_version(state)
    work = ROOT / "build" / state
    staging = work / ("package-" + uuid.uuid4().hex)
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    common = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--windowed",
              "--distpath", str(staging), "--workpath", str(work / "cache"),
              "--specpath", str(work), "--paths", str(ROOT / "src")]
    subprocess.run(common + ["--onedir", "--name", "MinecraftManager", str(ROOT / "src/main.py")], cwd=ROOT, check=True)
    for name in ("updater", "launcher"):
        subprocess.run(common + ["--onefile", "--name", name, str(ROOT / f"src/{name}_main.py")], cwd=ROOT, check=True)
    bundle = staging / "bundle"
    bundle.mkdir()
    app = bundle / "app"
    rename_retry(staging / "MinecraftManager", app)
    shutil.copy2(ROOT / "release-state.json", app / "release-state.json")
    shutil.copytree(ROOT / "resources", app / "resources")
    for name in ("updater", "launcher"):
        shutil.copy2(staging / (name + ".exe"), bundle / (name + ".exe"))
        shutil.copy2(staging / (name + ".exe"), output / (name + ".exe"))
    for name in ("data/server", "data/logs", "playit"):
        (bundle / name).mkdir(parents=True, exist_ok=True)
    archive_files(output / "MinecraftManager-app.zip", app.rglob("*"), app)
    # Empty data/playit folders are intentional, not the developer's personal settings.
    archive_files(output / "MinecraftManager-windows.zip", bundle.rglob("*"), bundle)
    with ZipFile(output / "MinecraftManager-windows.zip", "a") as package:
        for directory in ("data/", "data/server/", "data/logs/", "playit/"):
            package.writestr(directory, "")
    source_files = [ROOT / name for name in ("build.bat", "Publish-Git.bat",
                    "Run-Source.vbs", "requirements.txt", "config.example.json",
                    "release-state.json", "README.md", ".gitignore")]
    for name in ("src", "tools", "resources"):
        source_files.extend(p for p in (ROOT / name).rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")
    archive_files(output / "MinecraftManager-source.zip", source_files, ROOT)
    assets = {}
    for kind, name in {"app":"MinecraftManager-app.zip", "launcher":"launcher.exe",
                       "updater":"updater.exe", "windows":"MinecraftManager-windows.zip",
                       "source":"MinecraftManager-source.zip"}.items():
        path = output / name
        assets[kind] = {"url": f"https://github.com/{REPOSITORY}/releases/download/v{state}/{name}",
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    (output / "channel.json").write_text(json.dumps({"schema":2,"protocol":1,**stamp,"assets":assets}, indent=2)+"\n", encoding="utf-8")
    destination = output / "MinecraftManager"
    # Keep all developer/user data in previous output outside the replaceable app.
    if destination.exists():
        for path in destination.iterdir():
            if path.name in ("app", "launcher.exe", "updater.exe"):
                continue
            target = bundle / path.name
            if path.is_dir():
                shutil.copytree(path, target, dirs_exist_ok=True)
            else:
                shutil.copy2(path, target)
        previous = work / ("previous-" + uuid.uuid4().hex)
        rename_retry(destination, previous)
    else:
        previous = None
    try:
        rename_retry(bundle, destination)
    except Exception:
        if previous:
            rename_retry(previous, destination)
        raise
    print(f"Built {state}: {destination}; standalone bootstrap: {output / 'updater.exe'}", flush=True)


if __name__ == "__main__":
    build()
