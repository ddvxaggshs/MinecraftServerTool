# Minecraft Server Manager

Windows Minecraft hosting and Git world handoff, with a standalone bootstrap updater.

## Give a friend one file

Download `updater.exe` from this repository's latest GitHub Release. Put it in a new,
permanent folder and double-click it. No Python, Git or main-app DLLs are required
for the updater itself. It downloads and verifies the application and installs the
stable launcher. The main app's setup wizard handles Minecraft's Git/Java/Playit prerequisites.

Use `launcher.exe` for subsequent launches. Main also works from `app/MinecraftManager.exe`.
Every main-app launch invokes root `updater.exe` once. It checks `channel.json`,
downloads only when the release state changes, verifies SHA-256, and stages the
whole app directory. An older numeric version is never automatically installed.

When the GUI is idle it exits for the ready update. While hosting, syncing, or
recovering, it waits until safe to exit. The updater holds an OS process handle,
waits for the main process to exit, and requires that process's per-session safe-exit
approval before swapping directories. A forced process termination never approves
an update. It keeps a rollback copy, replaces `app/`, restarts the GUI, and exits.
Network/download/checksum failures leave the installed application usable.

## Installed / Release ZIP layout

```text
MinecraftManager/
  launcher.exe             # stable entry, installed once; never routinely replaced
  updater.exe              # standalone one-file bootstrap; independent of app DLLs
  app/
    MinecraftManager.exe
    _internal/             # Python / Qt / DLL runtime dependencies
    resources/
    release-state.json
  data/
    config.json            # created by setup, not shipped with personal settings
    server/                # new installations' default; existing paths retained
    logs/
    updates/               # staged files, status, transaction journal and rollback
  playit/                  # optional portable playit.exe; installed Playit also works
```

Only `app/` is replaced. Everything outside it is preserved. Exact update boundaries
and protected names are documented in `src/bootstrap/policy.py`. The main program
never overwrites launcher.exe or updater.exe. To update the bootstrap itself, close
the application and replace updater.exe with the separately published new file.

### Existing 3.8.x installations

Close the old application normally, copy the new `updater.exe` beside its `data/`
folder, then run it once. Existing root data/config.json and external server paths
are retained. Launch `launcher.exe` afterwards; the old MinecraftRelay.exe is no
longer the entry point. Keep old files until migration succeeds, then move old
MinecraftRelay.exe and _internal into expired/. Resolve pending recovery sessions
with the old app before migrating. Do not mix app/_internal with the old root runtime.

The old `update.json` remains on 3.8.2 for compatibility; it deliberately does not
send an incompatible layout to old clients. New clients use `channel.json` (schema 2,
protocol 1). Thus existing 3.8.x users need the new standalone updater once.

## Development layout

```text
src/
  main.py                  # Qt application entry
  launcher_main.py         # stable launcher
  updater_main.py          # standalone installer/updater entry and progress UI
  bootstrap/
    engine.py              # download, verification, staged install and rollback
    platform.py            # Windows process handles and installation mutexes
    policy.py              # repository, protocol paths and preservation rules
  relay/
    app.py, window.py       # startup / main UI
    setup.py, settings.py  # setup / settings dialogs
    lifecycle.py           # Java / Playit process lifecycle and recovery
    world_git.py           # world Git transactions and host lock
    config.py, paths.py     # data locations and configuration
    processes.py           # subprocess and dependency helpers
    update_client.py        # wake updater, show state, authorize safe exit
resources/                 # bundled static resources
build/                     # PyInstaller temporary output; ignored by Git
dist/                      # current binaries / release assets; ignored by Git
expired/                   # old versions/tools; ignored by Git
config.example.json        # reference template, not an actual user's configuration
requirements.txt
build.bat
Publish-Git.bat
Run-Source.vbs
```

Run source with `Run-Source.vbs` or `py src/main.py`. Source startup also invokes
the updater in check-only mode; it never overwrites a development checkout.
Double-click `build.bat` to generate:

- `dist/updater.exe`: the single file to send a friend.
- `dist/MinecraftManager/`: complete installation layout.
- `dist/MinecraftManager-windows.zip`: complete distributable package.
- `dist/MinecraftManager-app.zip`: replaceable app only, used by the updater.
- `dist/launcher.exe`, `dist/MinecraftManager-source.zip`, `dist/channel.json`.

Double-click `Publish-Git.bat` to build, commit/push the allowlisted source, publish
a draft Release with all five assets, verify public downloads, then commit the new
channel state. Previously used release versions automatically increment the patch.
GitHub credentials are read from Git Credential Manager only into memory. No worlds,
local settings, credentials, build/, dist/, or expired/ are committed. Binary packages
live in GitHub Releases rather than source history.
