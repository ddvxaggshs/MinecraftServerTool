import subprocess
from pathlib import Path
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QMessageBox, QFileDialog, QFormLayout, QDialog, QDialogButtonBox, QGroupBox, QCheckBox, QSlider

from .config import save_config
from .processes import run_gui, which, java21, find_playit, winget_install

class Settings(QDialog):
    def __init__(self,cfg,parent=None):
        super().__init__(parent)
        self.cfg=cfg.copy()
        self.setWindowTitle("Relay Settings")
        self.resize(700,650)
        l=QVBoxLayout(self)

        # Normal settings first.
        mc=QGroupBox("Minecraft"); f=QFormLayout(mc)
        self.sd=QLineEdit(cfg.get("server_dir",""))
        self.jar=QLineEdit(cfg.get("server_jar",""))
        self.host=QLineEdit(cfg.get("host_name","Host"))
        f.addRow("Server folder",self.sd)
        f.addRow("Server jar",self.jar)
        f.addRow("Host name",self.host)
        l.addWidget(mc)

        play=QGroupBox("Playit"); f=QFormLayout(play)
        self.play=QLineEdit(cfg.get("playit_command",""))
        pb=QPushButton("Browse"); pb.clicked.connect(self.pick_playit)
        rr=QHBoxLayout(); rr.addWidget(self.play); rr.addWidget(pb); f.addRow("Executable",rr)
        self.addr=QLineEdit(cfg.get("public_address","")); f.addRow("Public address",self.addr)
        rr=QHBoxLayout()
        claim=QPushButton("Run Playit setup / claim"); claim.clicked.connect(self.claim)
        web=QPushButton("Open Playit"); web.clicked.connect(lambda:QDesktopServices.openUrl(QUrl("https://playit.gg/")))
        rr.addWidget(claim); rr.addWidget(web); f.addRow(rr)
        l.addWidget(play)

        # Advanced Git settings near the bottom.
        git=QGroupBox("GitHub / Git"); f=QFormLayout(git)
        self.repo=QLineEdit(cfg.get("repo_url",""))
        self.remote=QLineEdit(cfg.get("git_remote","origin"))
        self.branch=QLineEdit(cfg.get("git_branch","main"))
        f.addRow("Repository URL",self.repo); f.addRow("Remote",self.remote); f.addRow("Branch",self.branch)
        self.git_ack=QCheckBox("I know what I'm doing — allow Git repository settings to be edited")
        self.git_ack.setChecked(False); f.addRow(self.git_ack)
        row=QHBoxLayout()
        self.git_verify_btn=QPushButton("Verify / Re-authenticate"); self.git_verify_btn.clicked.connect(self.git_verify)
        openrepo=QPushButton("Open repository"); openrepo.clicked.connect(lambda:QDesktopServices.openUrl(QUrl(self.repo.text())))
        row.addWidget(self.git_verify_btn); row.addWidget(openrepo); f.addRow(row)
        for x in (self.repo,self.remote,self.branch): x.setReadOnly(True)
        self.git_ack.toggled.connect(self.toggle_git_edit)
        l.addWidget(git)

        # Danger Zone is always the final settings section.
        danger=QGroupBox("Danger Zone — Host Lock")
        df=QVBoxLayout(danger)
        warn=QLabel("⚠ Only use this when you are certain the other computer is no longer hosting.\n"
                    "Force releasing an active lock can cause conflicting worlds or lost progress.")
        warn.setWordWrap(True); df.addWidget(warn)
        sr=QHBoxLayout()
        sr.addWidget(QLabel("Safe"))
        self.force_slider=QSlider(Qt.Horizontal)
        self.force_slider.setRange(0,1); self.force_slider.setValue(0)
        self.force_slider.setPageStep(1); self.force_slider.setTickInterval(1)
        sr.addWidget(self.force_slider,1)
        self.arm_label=QLabel("Locked")
        sr.addWidget(self.arm_label)
        df.addLayout(sr)
        self.force_btn=QPushButton("⚠ Force Release Host Lock")
        self.force_btn.setObjectName("danger")
        self.force_btn.setEnabled(False)
        self.force_slider.valueChanged.connect(self.toggle_force_arm)
        self.force_btn.clicked.connect(self.force_unlock)
        df.addWidget(self.force_btn)
        l.addWidget(danger)

        bb=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel)
        bb.accepted.connect(self.save); bb.rejected.connect(self.reject)
        l.addWidget(bb)

    def toggle_git_edit(self, enabled):
        for x in (self.repo,self.remote,self.branch):
            x.setReadOnly(not enabled)
    def toggle_force_arm(self, value):
        armed=bool(value)
        self.force_btn.setEnabled(armed)
        self.arm_label.setText("ARMED" if armed else "Locked")
    def force_unlock(self):
        if self.force_slider.value()!=1:
            return
        d=Path(self.sd.text().strip() or self.cfg.get("server_dir",""))
        if not (d/".git").exists():
            QMessageBox.warning(self,"Force Release","Configured server folder is not a Git repository.")
            return

        remote=(self.remote.text().strip() if hasattr(self,"remote") else "") or self.cfg.get("git_remote","origin")
        box=QMessageBox(self)
        box.setWindowTitle("Force release host lock?")
        box.setIcon(QMessageBox.Critical)
        box.setText("This can cause world data loss if another host is still running.")
        box.setInformativeText("Only refs/heads/mc-relay-lock on the remote will be deleted. Local world and recovery data will be kept.")
        yes=box.addButton("Force Release",QMessageBox.DestructiveRole)
        box.addButton("Cancel",QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not yes:
            return

        self.force_btn.setEnabled(False)
        QApplication.processEvents()
        try:
            chk=run_gui(["git","ls-remote","--heads",remote,"refs/heads/mc-relay-lock"],d,60)
            if chk.returncode!=0:
                raise RuntimeError((chk.stderr or chk.stdout or "Unable to query remote lock.")[-1800:])
            if not chk.stdout.strip():
                QMessageBox.information(self,"Force Release","No remote host lock exists. Nothing was deleted.")
                return

            expected=chk.stdout.split()[0]
            deletion=run_gui(["git","push","--force-with-lease=refs/heads/mc-relay-lock:"+expected,remote,":refs/heads/mc-relay-lock"],d,60)
            if deletion.returncode!=0:
                raise RuntimeError((deletion.stderr or deletion.stdout or "Git rejected lock deletion.")[-1800:])

            verify=run_gui(["git","ls-remote","--heads",remote,"refs/heads/mc-relay-lock"],d,60)
            if verify.returncode!=0:
                raise RuntimeError((verify.stderr or verify.stdout or "Unable to verify deletion.")[-1800:])
            if verify.stdout.strip():
                raise RuntimeError("Remote lock still exists after Git reported a successful deletion.")

            QMessageBox.information(self,"Force Release",
                "Remote mc-relay-lock was deleted successfully.\n\n"
                "Local world and recovery data were not changed.")
            self.force_slider.setValue(0)
        except Exception as e:
            QMessageBox.warning(self,"Force Release Failed",str(e))
        finally:
            self.force_btn.setEnabled(self.force_slider.value()==1)

    def git_verify(self):
        d=Path(self.sd.text())
        if not (d/".git").exists(): return QMessageBox.warning(self,"GitHub","Server folder is not a Git repository.")
        run_gui(["git","remote","set-url",self.remote.text().strip() or "origin",self.repo.text().strip()],d)
        # Using an ordinary authenticated remote operation intentionally lets GCM invoke browser OAuth.
        try:r=run_gui(["git","fetch",self.remote.text().strip() or "origin"],d,180)
        except subprocess.TimeoutExpired:return QMessageBox.information(self,"GitHub","Finish browser authentication, then retry.")
        QMessageBox.information(self,"GitHub","Repository access verified." if r.returncode==0 else (r.stderr or r.stdout)[-1800:])
    def pick_playit(self):
        x,_=QFileDialog.getOpenFileName(self,"Select playit.exe",self.play.text(),"Executable (*.exe)")
        if x:self.play.setText(x)
    def claim(self):
        p=self.play.text().strip() or find_playit()
        if not p or not Path(p).exists():return QMessageBox.warning(self,"Playit","Select/install playit.exe first.")
        subprocess.Popen([p,"setup"],creationflags=subprocess.CREATE_NEW_CONSOLE)
    def save(self):
        git_values = {}
        if self.git_ack.isChecked():
            git_values = dict(repo_url=self.repo.text().strip(),git_remote=self.remote.text().strip() or "origin",
                              git_branch=self.branch.text().strip() or "main")
        self.cfg.update(**git_values,playit_command=self.play.text().strip(),
            public_address=self.addr.text().strip(),server_dir=self.sd.text().strip(),
            server_jar=self.jar.text().strip(),host_name=self.host.text().strip() or "Host")
        save_config(self.cfg); self.accept()
