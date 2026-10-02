"""Release endpoint and the complete update boundary.

Only app/ is swapped. launcher.exe is installed once and never replaced.
updater.exe is distributed independently and never replaced by the main app.
Known legacy program files can be archived to expired/ after a successful install.
All other files under the installation root are preserved, including these paths.
"""
REPOSITORY = "ddvxaggshs/MinecraftServerTool"
CHANNEL_PATH = "channel.json"
PRESERVE_DIRECTORIES = frozenset({
    "data", "playit", ".git", ".venv", "world", "world_nether", "world_the_end",
    "mods", "config", "plugins", "logs", "libraries", "versions", "build", "dist",
    "incident-backups", "recovery-backups", "src", "resources", "tools", "expired",
})
PRESERVE_FILES = frozenset({
    "config.json", "server.properties", "eula.txt", "relay-recovery.json",
    "ops.json", "whitelist.json", "banned-players.json", "banned-ips.json",
    "launcher.exe", "updater.exe",
})
MAIN_EXE = "MinecraftManager.exe"
MAX_DOWNLOAD = 512 * 1024 * 1024
MAX_EXPANDED = 2 * 1024 * 1024 * 1024

# Exact names only. Never glob EXEs, DLLs, JSON files, or arbitrary directories.
# A source/development checkout is excluded from automatic legacy cleanup.
LEGACY_PROGRAM_FILES = frozenset({
    "MinecraftRelay.exe", "MinecraftRelay.py", "MinecraftRelay.spec",
    "apply-update.ps1", "release-state.json", "update.json",
    "Run-Source.vbs", "Run-Source.bat", "Build-Windows.bat",
})
LEGACY_PROGRAM_DIRECTORIES = frozenset({"_internal", "relay"})
