import sys
from pathlib import Path

APP_DIR=(Path(sys.executable).resolve().parent.parent if getattr(sys,"frozen",False)
         else Path(__file__).resolve().parents[2])
VERSION="3.9.0"
DATA_DIR=APP_DIR/"data"
DATA_DIR.mkdir(parents=True,exist_ok=True)
CONFIG_PATH=DATA_DIR/"config.json"
LOCK_REF="refs/heads/mc-relay-lock"
REMOTE_LOCK_REF="refs/remotes/origin/mc-relay-lock"

IDLE="IDLE"
STARTING="STARTING"
RUNNING="RUNNING"
STOPPING="STOPPING"
RECOVERY_REQUIRED="RECOVERY_REQUIRED"
RECOVERING="RECOVERING"
ERROR="ERROR"

RECOVERY_PATH=DATA_DIR/"recovery.json"
BACKUP_DIR=DATA_DIR/"recovery-backups"
