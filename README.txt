Minecraft Relay 3.8.0
Current usage, updates and publishing instructions: README.md

Minecraft Relay V3.7.2

SOURCE STARTUP WITHOUT A CONSOLE WINDOW
- Double-click Run-Source.vbs (requires Windows Script Host).
- The launcher uses pythonw/pyw so no console stays attached to the application.
- Run-Source.bat is a compatibility shortcut; Windows may briefly show its console.
- Packaged users should launch MinecraftRelay.exe directly.

V3.7.2 UI responsiveness:
- Background Git and Java probes no longer open console windows on Windows.
- Git setup, authentication, and force-release commands run in a worker while a modal progress dialog keeps Qt responsive.
- Java version probes run once and cache their result for 15 seconds.
- Console output uses a plain-text widget and batched updates without line wrapping.
- Interactive dependency installers and Playit setup still open their required windows.
- This update does not change the world synchronization or host-lock protocol.

WHAT'S NEW
- Qt/PySide6 interface.
- First-run dependency setup for Git, Microsoft OpenJDK 21, and Playit.
- GitHub private repository connect/clone flow through Git for Windows / Git Credential Manager.
- Settings page can manually change/re-authenticate GitHub, change repo/branch/remote,
  select playit.exe, rerun Playit claim, edit public tunnel address, server folder/jar, and host name.
- Playit TUI/ANSI output is suppressed during normal hosting.
- Active host lock carries the active host's Playit address.

BUILD AN EXE ON WINDOWS
1. Extract this ZIP.
2. Double-click Build-Windows.bat.
3. It installs PySide6 + PyInstaller for the build machine.
4. Output is dist\MinecraftRelay\MinecraftRelay.exe.
5. Send the WHOLE dist\MinecraftRelay folder to your friend.

WHY A FOLDER INSTEAD OF ONEFILE?
PySide6/Qt is large. --onedir starts faster, is easier to troubleshoot, and does not unpack Qt
to a temporary directory every launch. Your friend does NOT need Python or PySide6.

FRIEND'S FIRST RUN
- Run MinecraftRelay.exe.
- Install missing Git / Java 21 / Playit from Setup.
- Enter the private GitHub repository URL and choose a local server folder.
- Connect/Clone/Verify. Git Credential Manager should handle official GitHub browser authentication.
- Run Playit setup/claim, create Minecraft Java tunnel -> 127.0.0.1:25565, paste .ply.gg address.
- Set a host name and Finish.

IMPORTANT
- Friend must have access to the private GitHub repository.
- Offline-mode Minecraft does not authenticate player identities.
- Never run two world hosts at once; the remote mc-relay-lock is the safety mechanism.

V3.2: Host button is atomically disabled/replaced by Stop & Sync after first click. Git settings are read-only until the safety acknowledgement checkbox is checked.

V3.3 safety changes:
- Setup Next is hard-locked until Git + Java 21 + Playit are installed.
- GitHub page is hard-locked until repository authentication/access succeeds.
- Playit page is hard-locked until Playit exists and a .ply.gg address is configured.
- Setup Finish performs the same checks again.
- Closing the manager while hosting no longer silently exits: it offers Stop & Sync or Cancel.
- Closing is blocked while a start/stop/sync operation is in progress.

V3.4 recovery/safety:
- Windows Job Object: Java server + Playit are killed by Windows if Relay is terminated/crashes.
- Persistent relay-recovery.json remembers the exact owned remote lock across app restarts.
- Interrupted sessions show RECOVER & SYNC instead of allowing another local Host.
- Remote host lock is intentionally retained after an abnormal exit.
- Recovery creates a local ZIP snapshot of world/ before Git synchronization.
- While hosting, Relay sends `save-all flush` every 5 minutes.
- world/session.lock is ignored/untracked automatically during sync.
- Settings > Git contains a Danger Zone force-release control with acknowledgement + second confirmation.
- Force Release deletes only the remote mc-relay-lock; it does not reset/delete local world or recovery files.

Note: Job Object protects against app crash/task-manager termination. A hard power loss cannot run cleanup,
but the persistent remote lock/recovery record remains for the next launch.


Minecraft Relay V3.7.1
====================
Persistent data layout:
  data/
    config.json
    recovery.json
    recovery-backups/

The data/ folder is the part intended to survive manual upgrades. Replace the EXE/_internal
for a newer build and keep data/. On first V3.5 launch, legacy config.json,
relay-recovery.json, and recovery-backups beside the EXE are copied into data/ automatically.

V3.5 changes:
- Main title/window title show V3.5.
- Git settings are placed near the bottom of Settings; Danger Zone / Force Release is last.
- Force Release now explicitly checks the remote lock, deletes mc-relay-lock, and verifies deletion.
- Local recovery state takes priority over "Host Available", even if the remote lock was manually deleted.
- Recover & Sync tolerates a remote lock that was already manually force-released, but refuses to delete a lock belonging to another session.
- Existing Windows Job Object crash protection remains.
- Existing 5-minute save-all flush and recovery ZIP snapshot remain.
- First-run dependency/GitHub/Playit setup gates remain hard requirements.

V3.5.1 fixes:
- Added visible hover/pressed/disabled feedback for QPushButton controls.
- Reworked main-screen Server Command Send: writes directly to the live Minecraft server stdin, flushes immediately, strips optional leading '/', logs the sent command, and supports Enter.
- Reworked Force Release end-to-end using the configured repository and exact refs/heads/mc-relay-lock refspec, with query/delete/verify stages and visible error reporting.

V3.5.2 UI/UX fixes:
- GitHub Setup page no longer has a duplicate in-page verify button. Bottom Next becomes Verify & Continue and advances only after successful verification.
- Settings layout is rebuilt: Minecraft -> Playit -> GitHub/Git -> Danger Zone.
- Danger Zone uses a Safe/ARMED slider; Force Release stays disabled until armed and still requires the final confirmation dialog.
- Explicit hover/pressed/disabled button states are defined for both light main UI and dark setup UI.
- Fixed DATA_DIR initialization order in the source package.

V3.6 performance/recovery refactor:
- Normal Stop & Sync no longer creates a recovery ZIP.
- Recovery ZIP is created only when recovery.json existed at Relay startup, meaning a previous session was interrupted.
- Git/network Refresh now runs in a background worker instead of blocking the Qt UI thread.
- Minecraft console output is batched before crossing into Qt, reducing repaint/event overhead.
- Console history is capped at 3000 blocks to avoid long-session slowdown.
- Command input/Send are disabled while the server is offline.
- Existing Job Object, persistent data/, recovery lock, and safety behavior remain.

V3.7 lifecycle/state-machine refactor
=====================================
Single authoritative lifecycle:
  IDLE -> STARTING -> RUNNING -> STOPPING -> IDLE
  interrupted/failed sync -> RECOVERY_REQUIRED -> RECOVERING -> IDLE

Rules:
- Only the Qt-thread state machine renders Host / Stop / Recover / command controls.
- Background Refresh is informational only; it cannot change lifecycle state or buttons.
- Refresh results carry a generation number; stale results are discarded.
- Host, Stop/Sync, and Recovery are strict serial transactions.
- All Git operations share one mutex. Informational refresh skips Git while a lifecycle transaction owns it.
- Remote lock is released only after the world push succeeds.
- Unexpected Java exit while RUNNING transitions to RECOVERY_REQUIRED.
- Normal Stop never creates a recovery ZIP; Recover does.
- Console reader/autosave remain independent background workers.

V3.7.1 startup/console fix
==========================
- STARTING no longer becomes RUNNING after an arbitrary 0.35 second delay.
- Relay waits for Minecraft's actual "Done (...)! For help, type \"help\"" ready line.
- Startup timeout is 120 seconds and immediate Java exit is detected.
- Server stdout now goes into a thread-safe queue.
- A Qt timer drains the queue every 50 ms, so the final line in a burst can never remain stuck in a reader-side buffer.
- Each UI tick drains at most 250 lines to keep the event loop responsive during log floods.
- V3.7 state-machine / Git lock behavior is otherwise unchanged.
