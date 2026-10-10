"""Dropdown mod inventory and asynchronous mod-only synchronization."""
import threading
from PySide6.QtWidgets import QFileDialog, QMenu
from .mod_files import scan_mods
from .mod_sync import ModSync
from .paths import IDLE


class ModTools:
    def init_mod_tools(self):
        self._mods_busy = False
        self._mods_pending = ModSync(self.cfg).pending
        self._mods = []
        self._mods_scanning = False
        self._mods_error = None

    def mods_blocked(self):
        return self._mods_busy or self._mods_pending

    def can_edit_mods(self):
        return (self.state == IDLE and not self.recovery and not self._backup_busy
                and not self._mods_busy and not self._mods_pending
                and self.remote_status_known and not self.remote_lock
                and not (self.server_proc and self.server_proc.poll() is None))

    def render_mod_tools(self):
        if self.mods_blocked():
            for control in (self.hb, self.sb, self.resolve_button, self.settings_button, self.backup_button):
                control.setEnabled(False)
        self.mods_button.setEnabled(not self._backup_busy and not self._mods_busy)
        self.mod_status.setVisible(self._mods_busy or self._mods_pending)
        if self._mods_busy:
            self.mod_status.setText('Mods: applying changes and synchronizing only selected mod files...')
        elif self._mods_pending:
            self.mod_status.setText('Mods: synchronization unfinished. Open Mods to Retry sync or Cancel pending change.')

    def refresh_mods(self):
        if self._mods_scanning or self._mods_busy:
            return
        self._mods_scanning = True
        directory = self.cwd
        def work():
            try:
                result = {'directory': directory, 'mods': scan_mods(directory), 'error': None}
            except Exception as error:
                result = {'directory': directory, 'mods': [], 'error': str(error)}
            self.modsListedS.emit(result)
        threading.Thread(target=work, daemon=True).start()

    def mods_listed(self, result):
        self._mods_scanning = False
        if result['directory'] == self.cwd:
            self._mods, self._mods_error = result['mods'], result['error']
            self.mods_button.setText(f'Mods ({len(self._mods)})')
            # Never rebuild an open submenu under the user's cursor.
            if not self.mods_menu.isVisible():
                self.fill_mod_menu()
        else:
            self.refresh_mods()

    def fill_mod_menu(self):
        menu = self.mods_menu
        menu.clear()
        def action(text, handler, enabled=True):
            item = menu.addAction(text)
            item.setEnabled(enabled)
            item.triggered.connect(handler)
        action('Add JAR...', self.add_mod, self.can_edit_mods())
        can_retry = (self.state == IDLE and not self.recovery and not self._backup_busy and not self._mods_busy
                     and not (self.server_proc and self.server_proc.poll() is None))
        if self._mods_pending:
            action('Retry sync (mods only)', lambda: self.run_mod_action('retry'), can_retry)
            action('Cancel pending change', lambda: self.run_mod_action('cancel'), can_retry)
        action('Refresh list', self.refresh_mods)
        menu.addSeparator()
        if self._mods_error:
            action('Cannot read mods: ' + self._mods_error[:100], lambda: None, False)
        elif not self._mods:
            action('Reading mods...' if self._mods_scanning else 'No mod files found', lambda: None, False)
        for mod in self._mods:
            label = f"{'[ON]' if mod['enabled'] else '[OFF]'} {mod['name']}  {mod['version']}"
            # QMenu uses ampersands as keyboard mnemonics.
            submenu = QMenu(label.replace('&', '&&'), menu)
            menu.addMenu(submenu)
            for detail in (mod['filename'], f"{mod['loader']} | ID: {mod['mod_id'] or 'unknown'}",
                           'Metadata error: ' + mod['error'] if mod['error'] else None):
                if detail:
                    submenu.addAction(detail.replace('&', '&&')).setEnabled(False)
            submenu.addSeparator()
            toggle = 'disable' if mod['enabled'] else 'enable'
            item = submenu.addAction(toggle.capitalize() + ' & sync')
            item.setEnabled(self.can_edit_mods())
            item.triggered.connect(lambda checked=False, op=toggle, name=mod['filename']: self.run_mod_action(op, name))
            item = submenu.addAction('Remove & sync')
            item.setEnabled(self.can_edit_mods())
            item.triggered.connect(lambda checked=False, name=mod['filename']: self.run_mod_action('remove', name))
        if not self.can_edit_mods() and not self._mods_pending:
            menu.addSeparator()
            action('Stop all hosts and finish synchronization before editing mods', lambda: None, False)

    def add_mod(self):
        if not self.can_edit_mods():
            return
        source, _ = QFileDialog.getOpenFileName(self, 'Add a Fabric server mod', '', 'Java mod (*.jar)')
        if source:
            self.run_mod_action('add', source=source)

    def run_mod_action(self, action, filename=None, source=None):
        if self.state != IDLE or self.recovery or self._backup_busy or self._mods_busy:
            return
        if self.server_proc and self.server_proc.poll() is None:
            return
        if action not in ('retry', 'cancel') and not self.can_edit_mods():
            return
        self._mods_busy = True
        self._refresh_generation += 1
        self.render_state()
        cfg = dict(self.cfg)
        self.log('[Mods] ' + action.capitalize() + ': preparing mod-only synchronization...')
        def work():
            sync = ModSync(cfg)
            try:
                with self.git_mutex:
                    message = (sync.retry() if action == 'retry' else sync.cancel() if action == 'cancel'
                               else sync.prepare(action, filename, source))
                result = dict(message=message, error=False, pending=sync.pending)
            except Exception as error:
                result = dict(message=str(error), error=True, pending=sync.pending)
            self.modsDoneS.emit(result)
        threading.Thread(target=work, daemon=True).start()

    def mods_finished(self, result):
        self._mods_busy = False
        self._mods_pending = result['pending']
        self.log('[Mods] ' + ('ERROR: ' if result['error'] else '') + result['message'])
        self.remote_status_known = False
        self._refresh_generation += 1
        self.render_state()
        self.refresh_mods()
        self.refresh()
