import sys
from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMessageBox
from .config import load_config
from .paths import IDLE, RECOVERY_REQUIRED
from .setup import SetupWizard
from .window import Main
from .instance import InstanceGuard
from .update_client import UpdateClient

def main():
    app=QApplication(sys.argv)
    try:
        instance=InstanceGuard()
    except RuntimeError as error:
        QMessageBox.information(None,"Minecraft Relay",str(error))
        return
    app.setStyleSheet("""QPushButton { padding:7px 12px; border:1px solid #666; border-radius:6px; }
QPushButton:hover:enabled { background:#505050; border-color:#8a8a8a; }
QPushButton:pressed:enabled { background:#1f1f1f; border-color:#aaa; padding-top:9px; padding-bottom:5px; }
QPushButton:disabled { color:#777; background:#303030; border-color:#444; }
QPushButton#danger { color:#ffb3b3; border-color:#b85b5b; }
QPushButton#danger:hover:enabled { background:#6b3030; }
QPushButton#danger:pressed:enabled { background:#3b1515; }
QSlider::groove:horizontal { height:6px; background:#777; border-radius:3px; }
QSlider::handle:horizontal { width:22px; margin:-8px 0; border-radius:11px; background:#ddd; border:1px solid #555; }
QSlider::handle:horizontal:hover { background:#fff; }""");app.setFont(QFont("Segoe UI",10));c=load_config()
    updater=UpdateClient(app)
    updater.start()
    if not c.get("setup_complete"):
        w=SetupWizard(c)
        if not w.exec():return
    m=Main();m.show()
    updater.status.connect(m.update_status.setText)
    if updater.last_message:
        m.update_status.setText(updater.last_message)
    # Download in the background; never interrupt hosting or an unsynced session.
    def apply_when_idle():
        if updater.ready and m.state==IDLE and not m.recovery and not m._backup_busy and not m.mods_blocked() and not app.activeModalWidget():
            m.close()
    update_exit_timer=QTimer(m)
    update_exit_timer.setInterval(1000)
    update_exit_timer.timeout.connect(apply_when_idle)
    update_exit_timer.start()
    if m.state==RECOVERY_REQUIRED:
        QMessageBox.warning(m,"Interrupted session detected",
            "A previous hosting session did not finish normally.\n\n"
            "The remote host lock has been retained to protect unsynchronized world progress. "
            "Use RECOVER & SYNC before another computer hosts.")
    code=app.exec()
    try:
        if code==0 and m.state==IDLE and not m.recovery and not m.mods_blocked():
            updater.install_after_exit()
    except Exception as error:
        from .paths import DATA_DIR
        (DATA_DIR/"update-launch-error.txt").write_text(str(error),encoding="utf-8")
    updater.close()
    instance.close()
    sys.exit(code)
