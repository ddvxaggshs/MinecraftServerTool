import subprocess
from pathlib import Path
from PySide6.QtWidgets import QApplication, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QMessageBox, QFileDialog, QWizard, QWizardPage, QFormLayout

from .config import save_config
from .processes import run_gui, which, java21, find_playit, winget_install

class GatePage(QWizardPage):
    def __init__(self, title, validator):
        super().__init__()
        self.setTitle(title)
        self.validator = validator
    def isComplete(self):
        try:
            return bool(self.validator())
        except:
            return False
    def refresh_gate(self):
        self.completeChanged.emit()


class SetupWizard(QWizard):
    def __init__(self,cfg):
        super().__init__(); self.cfg=cfg
        self.setWindowTitle("Minecraft Relay Setup"); self.resize(720,500)
        self.setWizardStyle(QWizard.ModernStyle)
        p=QWizardPage(); p.setTitle("Welcome")
        l=QVBoxLayout(p); l.addWidget(QLabel("Relay will check/install Git, Java 21 and Playit, connect GitHub,\nclone the shared server, and configure this computer."))
        self.addPage(p)

        p=GatePage("1. Dependencies", lambda: bool(which("git") and java21() and find_playit())); l=QVBoxLayout(p)
        self.dep_page=p
        self.dep=QLabel(); l.addWidget(self.dep)
        row=QHBoxLayout()
        for name,pkg in [("Install Git","Git.Git"),("Install Java 21","Microsoft.OpenJDK.21"),("Install Playit","DevelopedMethods.playit")]:
            b=QPushButton(name); b.clicked.connect(lambda _,x=pkg:self.install(x)); row.addWidget(b)
        l.addLayout(row); b=QPushButton("Check again"); b.clicked.connect(self.check); l.addWidget(b); self.addPage(p)

        self.github_verified=False
        p=QWizardPage(); p.setTitle("2. GitHub & Repository"); l=QVBoxLayout(p)
        l.addWidget(QLabel("Relay uses Git for Windows / Git Credential Manager. Relay never stores your GitHub password or token."))
        self.repo=QLineEdit(cfg.get("repo_url","")); l.addWidget(QLabel("Private repository URL")); l.addWidget(self.repo)
        self.dir=QLineEdit(cfg.get("server_dir","")); br=QPushButton("Browse"); br.clicked.connect(self.browse)
        r=QHBoxLayout(); r.addWidget(self.dir); r.addWidget(br); l.addWidget(QLabel("Local server folder")); l.addLayout(r)
        self.gitstat=QLabel(); l.addWidget(self.gitstat)
        self.addPage(p)

        p=GatePage("3. Playit", lambda: bool(find_playit() and self.addr.text().strip().lower().endswith(".ply.gg"))); l=QVBoxLayout(p)
        self.play_page=p
        self.playstat=QLabel(); l.addWidget(self.playstat)
        b=QPushButton("Open official Playit Claim"); b.clicked.connect(self.claim); l.addWidget(b)
        self.addr=QLineEdit(cfg.get("public_address","")); self.addr.setPlaceholderText("your-address.tun.ply.gg")
        self.addr.textChanged.connect(lambda: self.play_page.refresh_gate())
        l.addWidget(QLabel("Create a Minecraft Java tunnel → 127.0.0.1:25565, then paste its public address:")); l.addWidget(self.addr)
        self.addPage(p)

        p=QWizardPage(); p.setTitle("4. Computer"); f=QFormLayout(p)
        self.host=QLineEdit(cfg.get("host_name","Host-1")); f.addRow("Host name",self.host); self.addPage(p)
        self.currentIdChanged.connect(self.update_nav_button)
        self.check()
        self.update_nav_button(self.currentId())

    def install(self,pkg):
        try:winget_install(pkg); QMessageBox.information(self,"Installer","Installer opened. Finish it, then click Check again.")
        except Exception as e: QMessageBox.critical(self,"Installer",str(e))
    def check(self):
        self.dep.setText(f"Git       {'✓ Ready' if which('git') else '✕ Required'}\nJava 21   {'✓ Ready' if java21() else '✕ Required'}\nPlayit    {'✓ Ready' if find_playit() else '✕ Required'}")
        self.playstat.setText("✓ Playit installed" if find_playit() else "⚠ Playit missing")
        if hasattr(self,"dep_page"): self.dep_page.refresh_gate()
    def browse(self):
        x=QFileDialog.getExistingDirectory(self,"Server folder",self.dir.text())
        if x:self.dir.setText(x)
    def github(self):
        if not which("git"):
            QMessageBox.warning(self,"Git","Install Git first.")
            return False
        url=self.repo.text().strip(); dest=Path(self.dir.text().strip())
        try:
            if (dest/".git").exists():
                r=run_gui(["git","remote","set-url","origin",url],dest)
                r=run_gui(["git","ls-remote","origin"],dest,120)
            else:
                dest.parent.mkdir(parents=True,exist_ok=True)
                # For HTTPS private repos, Git Credential Manager will open official browser auth when needed.
                r=run_gui(["git","clone",url,str(dest)],dest.parent,300)
            if r.returncode:
                self.github_verified=False
                self.gitstat.setText("⚠ GitHub authentication/repository access required")
                QMessageBox.warning(self,"GitHub",(r.stderr or r.stdout)[-2500:])
                return False
            else:
                self.github_verified=True
                self.gitstat.setText("✓ GitHub identity authenticated\n✓ Repository connected and accessible")
                jars=sorted(dest.glob("fabric-server-*.jar"))
                if jars:self.cfg["server_jar"]=jars[-1].name
                return True
        except subprocess.TimeoutExpired:
            QMessageBox.information(self,"GitHub","Authentication may still be open in your browser. Finish it, then click Verify & Continue again.")
            return False
        except Exception as e:
            QMessageBox.critical(self,"GitHub",str(e))
            return False
    def update_nav_button(self, page_id):
        nxt=self.button(QWizard.NextButton)
        if not nxt:
            return
        # Pages: 0 Welcome, 1 Dependencies, 2 GitHub, 3 Playit, 4 Computer
        if page_id==2:
            nxt.setText("Verify & Continue >")
            nxt.setEnabled(True)
        elif page_id==1:
            nxt.setText("Continue >")
        elif page_id==3:
            nxt.setText("Verify & Continue >")
        else:
            nxt.setText("Next >")

    def validateCurrentPage(self):
        page_id=self.currentId()
        if page_id==1:
            self.check()
            if not (which("git") and java21() and find_playit()):
                QMessageBox.warning(self,"Dependencies required","Git, Java 21, and Playit must all be ready before continuing.")
                return False
        elif page_id==2:
            btn=self.button(QWizard.NextButton)
            old=btn.text()
            btn.setEnabled(False); btn.setText("Verifying…")
            QApplication.processEvents()
            ok=self.github()
            btn.setEnabled(True); btn.setText(old)
            return bool(ok)
        elif page_id==3:
            self.check()
            if not find_playit():
                QMessageBox.warning(self,"Playit","Playit must be installed before continuing.")
                return False
            if not self.addr.text().strip().lower().endswith(".ply.gg"):
                QMessageBox.warning(self,"Playit","Enter the public .ply.gg address for this computer before continuing.")
                return False
        return super().validateCurrentPage()

    def claim(self):
        p=find_playit()
        if not p:return QMessageBox.warning(self,"Playit","Install Playit first.")
        subprocess.Popen([p,"setup"],creationflags=subprocess.CREATE_NEW_CONSOLE)
    def accept(self):
        if not (which("git") and java21() and find_playit() and self.github_verified and self.addr.text().strip().lower().endswith(".ply.gg")):
            QMessageBox.warning(self,"Setup incomplete","Git, Java 21, GitHub repository access, and Playit must all be ready before setup can finish.")
            return
        self.cfg.update(server_dir=self.dir.text().strip(),repo_url=self.repo.text().strip(),
                        host_name=self.host.text().strip() or "Host",
                        public_address=self.addr.text().strip(),playit_command=find_playit() or self.cfg.get("playit_command"),
                        setup_complete=True)
        d=Path(self.cfg["server_dir"])
        jars=sorted(d.glob("fabric-server-*.jar")) if d.exists() else []
        if jars:self.cfg["server_jar"]=jars[-1].name
        save_config(self.cfg); super().accept()
