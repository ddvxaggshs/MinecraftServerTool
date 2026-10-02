"""The GUI only wakes the standalone updater and authorizes a safe handoff."""
import json
import os
import sys
import uuid
from PySide6.QtCore import QObject, QTimer, Signal
from bootstrap.engine import write_json
from bootstrap.platform import spawn
from .paths import APP_DIR, DATA_DIR


class UpdateClient(QObject):
    status = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = None
        self.session = uuid.uuid4().hex
        self.ready = False
        self.last_message = None
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.poll)

    def start(self):
        if self.process is not None:
            return
        if getattr(sys, "frozen", False):
            command = [str(APP_DIR / "updater.exe")]
        else:
            command = [sys.executable, str(APP_DIR / "src/updater_main.py"), "--check-only"]
        try:
            self.process = spawn(command + ["--background", "--parent", str(os.getpid()),
                                          "--session", self.session, "--root", str(APP_DIR)], APP_DIR)
            self.timer.start()
            self.status.emit("Checking for updates...")
        except Exception as error:
            self.status.emit("Updater could not start: " + str(error))

    def poll(self):
        try:
            info = json.loads((DATA_DIR / f"updates/check-{self.session}.json").read_text(encoding="utf-8"))
            if info.get("session") == self.session:
                self.ready = bool(info.get("ready"))
                if info["message"] != self.last_message:
                    self.last_message = info["message"]
                    self.status.emit(self.last_message)
        except (OSError, ValueError, KeyError):
            pass
        if self.process and self.process.poll() is not None:
            self.timer.stop()
            if not self.last_message:
                self.status.emit("Updater exited without a result; using the current version.")

    def install_after_exit(self):
        self.poll()
        if self.ready and self.process and self.process.poll() is None:
            write_json(DATA_DIR / f"updates/approve-{self.session}.json", {"session": self.session})

    def close(self):
        # The updater must outlive this process. No kill-on-close job or termination.
        self.timer.stop()
