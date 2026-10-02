import json
import shutil
from .paths import APP_DIR, DATA_DIR, CONFIG_PATH, RECOVERY_PATH, BACKUP_DIR

def load_recovery():
    try:return json.loads(RECOVERY_PATH.read_text(encoding="utf-8")) if RECOVERY_PATH.exists() else None
    except:return None
def save_recovery(d):
    temp=RECOVERY_PATH.with_suffix(".json.tmp")
    temp.write_text(json.dumps(d,indent=2),encoding="utf-8")
    temp.replace(RECOVERY_PATH)
def clear_recovery():
    try: RECOVERY_PATH.unlink(missing_ok=True)
    except: pass

DEFAULTS={
 "server_dir":r"D:\MinecraftServer","repo_url":"https://github.com/ddvxaggshs/Minecraft_server.git",
 "server_jar":"fabric-server-mc.1.21.11-loader.0.19.5-launcher.1.1.2.jar","java":"java",
 "min_ram":"2G","max_ram":"4G","git_remote":"origin","git_branch":"main","host_name":"Host-1",
 "public_address":"","playit_command":r"C:\Program Files\playit_gg\bin\playit.exe","setup_complete":False}


def migrate_legacy_data():
    """One-time migration from pre-3.5 files beside the executable."""
    DATA_DIR.mkdir(parents=True,exist_ok=True)
    pairs=[
        (APP_DIR/"config.json", DATA_DIR/"config.json"),
        (APP_DIR/"relay-recovery.json", DATA_DIR/"recovery.json"),
    ]
    for old,new in pairs:
        try:
            if old.exists() and not new.exists():
                shutil.copy2(old,new)
        except Exception:
            pass
    old_backups=APP_DIR/"recovery-backups"
    new_backups=DATA_DIR/"recovery-backups"
    try:
        if old_backups.exists():
            new_backups.mkdir(parents=True,exist_ok=True)
            for f in old_backups.iterdir():
                if f.is_file() and not (new_backups/f.name).exists():
                    shutil.copy2(f,new_backups/f.name)
    except Exception:
        pass

migrate_legacy_data()

def load_config():
    c=DEFAULTS.copy()
    if CONFIG_PATH.exists():
        try:c.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except:pass
    return c
def save_config(c): CONFIG_PATH.write_text(json.dumps(c,indent=2),encoding="utf-8")
