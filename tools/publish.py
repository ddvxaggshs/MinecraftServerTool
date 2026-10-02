"""One-click local build -> source push -> compiled Release -> update state."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.request
import hashlib

from build_release import build, ROOT
from github_release import GitHubRelease, REPO


def git(*args):
    result = subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Git command failed")
    return result.stdout.strip()


def version_number(value):
    if not re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", value):
        raise ValueError("Use major.minor.patch, for example 3.9.1 (no v prefix).")
    return tuple(map(int, value.split(".")))


def choose_version(api, current):
    minimum = version_number(current)
    channel_path = ROOT / "channel.json"
    published = None
    if channel_path.exists():
        published = version_number(json.loads(channel_path.read_text(encoding="utf-8"))["version"])

    def used(state):
        return bool(api.exists(state) or git("tag", "--list", "v" + state) or
                    git("ls-remote", "origin", "refs/tags/v" + state))

    suggested = current
    while (published is not None and version_number(suggested) <= published) or used(suggested):
        major, minor, patch = version_number(suggested)
        suggested = f"{major}.{minor}.{patch + 1}"
    print(f"\nCurrent source version: {current}\nSuggested release: {suggested}")
    while True:
        answer = input(f"Release version [{suggested}] (Enter to accept, q to cancel): ").strip()
        if answer.lower() in {"q", "quit", "cancel"}:
            return None
        state = answer or suggested
        try:
            number = version_number(state)
        except ValueError as error:
            print(error)
            continue
        if number < minimum or (published is not None and number <= published):
            print("Choose a version newer than the published version and not older than the source.")
            continue
        if used(state):
            print("This release or tag already exists. Choose another version.")
            continue
        while True:
            confirm = input(f"Build and publish v{state} to {REPO}? [y/N]: ").strip().lower()
            if confirm in {"y", "yes"}:
                return state
            if confirm in {"", "n", "no", "q", "quit", "cancel"}:
                return None
            print("Enter y to publish or n to cancel.")


def main():
    remote = git("remote", "get-url", "origin")
    if remote.rstrip("/").removesuffix(".git") not in ("https://github.com/" + REPO, "git@github.com:" + REPO):
        raise RuntimeError("origin does not point to the program repository. Refusing to publish.")
    if git("branch", "--show-current") != "main":
        raise RuntimeError("Switch the program repository to main before publishing.")
    api = GitHubRelease(ROOT)
    stamp = json.loads((ROOT / "release-state.json").read_text(encoding="utf-8"))
    state = choose_version(api, stamp["state"])
    if state is None:
        print("Publish cancelled. Version files and releases were not changed.")
        return 2
    stamp = {"state": state, "version": state}
    (ROOT / "release-state.json").write_text(json.dumps(stamp, indent=2) + "\n", encoding="utf-8")
    paths = ROOT / "src/relay/paths.py"
    paths.write_text(re.sub(r'^VERSION="[^"]+"', f'VERSION="{state}"', paths.read_text(encoding="utf-8"), flags=re.M), encoding="utf-8")
    print("Building", state, flush=True)
    build(state)
    # Explicit allowlist; never stage private configuration or compiled output.
    roots = {".gitignore", "build.bat", "Publish-Git.bat",
             "Run-Source.vbs", "requirements.txt", "config.example.json",
             "README.md", "release-state.json"}
    for name in sorted(roots | {"src", "tools", "resources"}):
        git("add", "--", name)
    for deleted in git("diff", "--name-only", "--diff-filter=D").splitlines():
        if deleted in {"MinecraftRelay.py", "apply-update.ps1", "Build-Windows.bat", "Run-Source.bat"} or deleted.startswith("relay/"):
            git("add", "-u", "--", deleted)
    for name in git("diff", "--cached", "--name-only").splitlines():
        if name not in roots | {"MinecraftRelay.py", "apply-update.ps1", "channel.json", "Build-Windows.bat", "Run-Source.bat"} and not name.startswith(("src/", "tools/", "resources/", "relay/")):
            raise RuntimeError("Unexpected staged file; review before publishing: " + name)
    if git("diff", "--cached", "--name-only"):
        git("commit", "-m", "Release " + state)
    git("push", "origin", "main")
    commit = git("rev-parse", "HEAD")
    git("tag", "v" + state)
    git("push", "origin", "v" + state)
    print("Uploading built EXE, dependencies and source package…", flush=True)
    url = api.publish(state, commit, ROOT / "dist")
    manifest = json.loads((ROOT / "dist/channel.json").read_text(encoding="utf-8"))
    for asset in manifest["assets"].values():
        digest = hashlib.sha256()
        with urllib.request.urlopen(asset["url"], timeout=60) as response:
            while chunk := response.read(1024 * 1024):
                digest.update(chunk)
        if digest.hexdigest() != asset["sha256"]:
            raise RuntimeError("Published download verification failed; update state was not advanced.")
    # Last operation: clients only see the version after its downloads are verified.
    shutil.copy2(ROOT / "dist/channel.json", ROOT / "channel.json")
    git("add", "--", "channel.json")
    git("commit", "-m", "Publish update state " + state)
    git("push", "origin", "main")
    print("Published:", url, flush=True)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        print("\nPublish cancelled.")
        sys.exit(2)
    except Exception as error:
        print("Publish stopped:", error, file=sys.stderr)
        sys.exit(1)
