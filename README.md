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

Idle clients check the remote host lock every 10 seconds. HOST is disabled while
another host owns the lock or its status cannot be verified. Pending commits show
SYNC & START: the application acquires the host lock, fetches again, synchronizes,
then launches Minecraft. Runtime session locks and the player lookup cache do not
count as world progress; genuine unpublished progress still requires Resolve World.
Normal STOP & SYNC does not create a recovery snapshot. Delayed Java exit events are
bound to their original process and cannot mark a subsequent session as crashed.

## Manual backups and live statistics

Click **MANUAL BACKUP** to save a ZIP in `data/manual-backups/`. This is a local
snapshot, not a Git upload. It includes the configured world and its dimensions,
including separate `_nether` / `_the_end` folders, and excludes `session.lock`.
While hosting, Relay waits for `save-off` and `save-all flush` acknowledgements
before copying, then restores `save-on` even if the backup fails. Conflicting
actions and application exit are disabled until backup finishes. If a mod changes
world files during copying, the incomplete archive is discarded; retry offline.
Keep the resulting ZIP somewhere safe before restoring it with the server stopped.

The upper-right panel shows local Java working-set RAM (every 2 seconds) and online
players (approximately every 5 seconds). RAM includes heap and native memory; it
is not the configured maximum heap. Carpet servers with Scarpet commands enabled
also show real players and fake/shadow players, using Carpet's `player_type` query.
Without a compatible query, Relay displays total players and marks bot count as
unknown. Statistics are unavailable when another computer is hosting.

Carpet query reference: [Entities API](https://github.com/gnembon/fabric-carpet/blob/master/docs/scarpet/api/Entities.md).

## Mod management

Open **Mods** to see the names, versions and enabled state of JAR files directly
inside the server's `mods/` folder. Names are read locally from `fabric.mod.json`
(with Quilt/Forge metadata recognized for display); no account, internet lookup or
execution of the JAR is needed. Unknown files retain their filenames.

With all hosts stopped and the local branch at the published GitHub commit:

- **Add JAR...** imports a local Fabric server mod, rejecting duplicate IDs and
  client-only mods. Dependency/version compatibility is still checked by Fabric
  when the server starts; this is not an automatic dependency installer.
- **Disable / Enable & sync** renames `.jar` to `.jar.disabled` or back.
- **Remove & sync** removes the selected file after retaining a local copy.

Each action automatically publishes only its selected mod paths to the configured
server Git repository. An isolated Git index prevents unrelated staged or dirty
world/configuration files from entering the commit. Existing unpublished commits
must be resolved first, since pushing them would also publish their world changes.
The ordinary **STOP & SYNC** operation still saves and uploads world progress.

Mod operations use the same exclusive remote host lock and atomic publication as
hosting. A failed/interrupted operation keeps a journal and copies under
`data/mod-transactions/`. Open **Mods > Retry sync (mods only)** to finish, or
**Cancel pending change** to restore the original mod files. Hosting and other
mutations remain disabled until the transaction finishes. A lost response after
a successful push is detected on retry instead of creating a duplicate commit.

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
    manual-backups/         # local ZIP snapshots made with MANUAL BACKUP
    mod-transactions/       # pending mod operations and retained JAR copies
    updates/               # staged files, status, transaction journal and rollback
  playit/                  # optional portable playit.exe; installed Playit also works
```

Only `app/` is replaced during normal updates. After a successful legacy migration,
known old program files are moved to `expired/legacy-...`; other files are preserved. Exact update boundaries
and protected names are documented in `src/bootstrap/policy.py`. The main program
never overwrites launcher.exe or updater.exe. To update the bootstrap itself, close
the application and replace updater.exe with the separately published new file.

### Existing 3.8.x installations

Close the old application normally, copy the new `updater.exe` beside its `data/`
folder, then run it once. Existing root data/config.json and external server paths
are retained. Launch `launcher.exe` afterwards; the old MinecraftRelay.exe is no
longer the entry point. After installation succeeds, the updater automatically archives known old files
(such as MinecraftRelay.exe, _internal, relay and the old update script) into
expired/legacy-... . It never sweeps unknown EXEs/DLLs or user files. Root config.json,
data/, worlds, backups and Playit remain in place. Files in use, directories containing
user data, and configured server/Playit paths are retained. Cleanup problems are
recorded in data/updates/legacy-cleanup.json or legacy-cleanup-error.json; they do not
undo the installation. Re-run updater.exe manually to retry leftover cleanup even
when the application is already current. Development checkouts are never cleaned. Resolve pending recovery sessions
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
    migration.py           # archive old program files after successful installation
    platform.py            # Windows process handles and installation mutexes
    policy.py              # repository, protocol paths and preservation rules
  relay/
    app.py, window.py       # startup / main UI
    setup.py, settings.py  # setup / settings dialogs
    lifecycle.py           # Java / Playit process lifecycle and recovery
    live_tools.py          # backup controls and live statistics integration
    backup.py              # acknowledged online saves and local world snapshots
    monitor.py             # player / Carpet counts and Java working-set RAM
    server_io.py           # process-bound console commands and acknowledgements
    mod_files.py           # local JAR metadata and file validation
    mod_ui.py              # Mods dropdown and background actions
    mod_sync.py            # isolated mod-only commits, retry and cancellation
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
channel state. Before changing version files or building, the publisher suggests an
unused patch version. Press Enter to select it or type another major.minor.patch
version, then explicitly type `y` to confirm publication. Existing tags/releases and
older versions are rejected. Enter `q`, decline confirmation, or press Ctrl+C to cancel.
GitHub credentials are read from Git Credential Manager only into memory. No worlds,
local settings, credentials, build/, dist/, or expired/ are committed. Binary packages
live in GitHub Releases rather than source history.
