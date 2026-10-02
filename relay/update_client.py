"""Qt bridge to the independent updater; performs no network operations."""
import json
import os
import subprocess
import sys
import uuid
from PySide6.QtCore import QObject, QTimer, Signal
from .paths import APP_DIR, DATA_DIR
from .processes import WindowsJob
from .updater import UpdateManager


class UpdateClient(QObject):
    status = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = None
        self.session = uuid.uuid4().hex
        self.ready = False
        self.job = WindowsJob()
        self.last_message = None
        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.poll)

    def start(self):
        if self.process is not None:
            return
        if getattr(sys, "frozen", False):
            command = [str(APP_DIR / "_internal/MinecraftRelayUpdater.exe")]
        else:
            command = [sys.executable, "-m", "relay.update_component"]
        try:
            self.process = subprocess.Popen(command + ["--session", self.session], cwd=APP_DIR,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            self.job.assign(self.process)
            self.timer.start()
            self.status.emit("Checking updates with the upgrade component…")
        except Exception as error:
            self.status.emit("Updater could not start; using current version. " + str(error))

    def poll(self):
        try:
            info = json.loads((DATA_DIR / "updates/check-status.json").read_text(encoding="utf-8"))
            if info.get("session") == self.session:
                self.ready = bool(info.get("ready")) and bool(info.get("done"))
                if info["message"] != self.last_message:
                    self.last_message = info["message"]
                    self.status.emit(self.last_message)
        except (OSError, ValueError, KeyError):
            pass
        if self.process and self.process.poll() is not None:
            self.timer.stop()
            if not self.last_message:
                self.status.emit("Updater exited without a result; using current version.")

    def install_after_exit(self):
        self.poll()
        if self.ready:
            manager = UpdateManager()
            manager.ready = True
            manager.install_after_exit()

    def close(self):
        self.timer.stop()
        self.job.close()
        if self.process:
            try:
                self.process.wait(3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(3)
