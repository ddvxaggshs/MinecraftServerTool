"""Main-window integration for manual backups and nonblocking local metrics."""
import threading
import time
from PySide6.QtWidgets import QMessageBox
from .backup import create_snapshot, online_snapshot, ResumeSavingError
from .monitor import PlayerMonitor, memory_bytes
from .paths import DATA_DIR, IDLE, RUNNING, RECOVERY_REQUIRED


class LiveTools:
    def init_live_tools(self):
        self._backup_busy = False
        self._stop_after_backup = False
        self._resume_saving_required = False
        self._metrics_proc = None
        self._player_request_proc = None
        self._player_values = None
        self._player_updated = 0
        self._next_player_query = 0
        self._next_memory_query = 0
        self.console_session = None

    def render_tools(self):
        busy = self._backup_busy
        alive = bool(self.server_proc and self.server_proc.poll() is None)
        self.backup_button.setEnabled(not busy and not self._resume_saving_required and
            (self.state == RUNNING and alive or self.state in (IDLE, RECOVERY_REQUIRED) and not alive))
        if not busy:
            self.backup_button.setText("MANUAL BACKUP")
        if busy:
            for button in (self.hb, self.sb, self.resolve_button, self.sendb, self.cmd, self.settings_button):
                button.setEnabled(False)
        else:
            self.settings_button.setEnabled(True)

    def manual_backup(self):
        if self._backup_busy or self._resume_saving_required or self.mods_blocked():
            return
        proc = self.server_proc
        session = self.console_session
        alive = bool(proc and proc.poll() is None)
        if self.state == RUNNING:
            if not alive or session is None or session.proc is not proc:
                return
        elif self.state not in (IDLE, RECOVERY_REQUIRED) or alive:
            return
        self._backup_busy = True
        self.render_state()
        self.backup_button.setText("BACKING UP...")
        self.log("[Backup] Preparing a local world backup...")
        directory = self.cwd
        def work():
            result = {"path": None, "error": None, "resume_error": False}
            try:
                with self.git_mutex:
                    last_percent = -1
                    def progress(done, total):
                        nonlocal last_percent
                        percent = done * 100 // total
                        if percent != last_percent:
                            last_percent = percent
                            self.backupProgressS.emit(percent)
                    target = DATA_DIR / "manual-backups"
                    result["path"] = str(online_snapshot(session, directory, target, progress) if alive
                                         else create_snapshot(directory, target, progress))
            except Exception as error:
                result["error"] = str(error)
                result["resume_error"] = isinstance(error, ResumeSavingError)
            self.backupDoneS.emit(result)
        threading.Thread(target=work, daemon=True).start()

    def backup_finished(self, result):
        self._backup_busy = False
        self._resume_saving_required = result["resume_error"]
        if result["error"]:
            self.log("[Backup] " + result["error"])
            QMessageBox.warning(self, "Backup", result["error"])
        else:
            self.log("[Backup] Saved: " + result["path"])
        self.render_state()
        if self._stop_after_backup:
            self._stop_after_backup = False
            self.stop_sync()

    def poll_metrics(self):
        proc = self.server_proc
        alive = bool(proc and proc.poll() is None)
        now = time.monotonic()
        if proc is not self._metrics_proc:
            self._metrics_proc = proc
            self._player_values = None
            self._player_updated = 0
            self._next_player_query = 0
            self._next_memory_query = 0
            self._player_monitor = PlayerMonitor(self.cwd)
        if not alive:
            self.online_label.setText("Online: --")
            self.bots_label.setText("Remote host" if self.remote_lock and self.state == IDLE else "Server offline")
            self.memory_label.setText("Java RAM: --")
            return
        if now >= self._next_memory_query:
            self._next_memory_query = now + 2
            try:
                value = memory_bytes(proc)
            except (OSError, AttributeError):
                value = None
            self.memory_label.setText("Java RAM: " + (f"{value / (1024**3):.2f} GiB" if value is not None else "--"))
        if self.state != RUNNING:
            self.online_label.setText("Online: --")
            self.bots_label.setText("Waiting for server")
            return
        values = self._player_values if now - self._player_updated <= 15 else None
        self.online_label.setText(f"Online: {values['total']}" if values else "Online: --")
        if values and values["fake"] is not None:
            self.bots_label.setText(f"Real: {values['real']}  |  Carpet bots: {values['fake']}")
        else:
            self.bots_label.setText("Carpet bots: unknown" if values else "Querying players...")
        if self._backup_busy or now < self._next_player_query or self._player_request_proc is proc:
            return
        session = self.console_session
        if session is None or session.proc is not proc:
            return
        self._player_request_proc = proc
        self._next_player_query = now + 5
        monitor = self._player_monitor
        def work():
            try:
                values = monitor.read(session)
            except (RuntimeError, OSError, TimeoutError, ValueError):
                values = None
            self.playerStatsS.emit(proc, values)
        threading.Thread(target=work, daemon=True).start()

    def player_stats_received(self, proc, values):
        if self._player_request_proc is proc:
            self._player_request_proc = None
        if proc is self.server_proc:
            self._player_values = values
            self._player_updated = time.monotonic() if values else 0
            self.poll_metrics()
