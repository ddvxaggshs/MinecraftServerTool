"""All updater exclusion rules live here. Paths are relative to the installation."""

REPOSITORY = "ddvxaggshs/MinecraftServerTool"
MANIFEST_URL = f"https://raw.githubusercontent.com/{REPOSITORY}/main/update.json"

# Never replace, remove, or include these in a release package.
PRESERVE_DIRECTORIES = frozenset({
    "data", ".git", ".venv", "world", "world_nether", "world_the_end",
    "logs", "mods", "config", "plugins", "libraries", "versions",
    "incident-backups", "recovery-backups", "build", "dist",
})
PRESERVE_FILES = frozenset({
    "config.json", "relay-recovery.json", "server.properties", "eula.txt",
    "ops.json", "whitelist.json", "banned-ips.json", "banned-players.json",
})
SOURCE_ROOT_FILES = frozenset({
    "MinecraftRelay.py", "Run-Source.vbs", "Run-Source.bat", "Build-Windows.bat",
    "README.md", "apply-update.ps1", "release-state.json",
})
WINDOWS_ROOT_FILES = frozenset({"MinecraftRelay.exe", "apply-update.ps1", "release-state.json", "README.md"})


def protected(name):
    parts = name.replace("\\", "/").lower().split("/")
    return parts[0] in PRESERVE_DIRECTORIES or "/".join(parts) in PRESERVE_FILES
