import re, threading, queue
from pathlib import Path
from PySide6.QtCore import Signal, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QPlainTextEdit, QLineEdit, QFrame, QMessageBox

from .paths import VERSION, LOCK_REF, REMOTE_LOCK_REF, BACKUP_DIR, IDLE, STARTING, RUNNING, STOPPING, RECOVERY_REQUIRED, RECOVERING, ERROR
from .config import load_config, load_recovery
from .processes import WindowsJob, run, find_playit
from .settings import Settings
from .lifecycle import Lifecycle
from .world_git import WorldGit

class Main(Lifecycle, QMainWindow):
    logS=Signal(str)
    infoS=Signal(object)
    stateS=Signal(str,str)

    def __init__(self):
        super().__init__()
        self.cfg=load_config()
        self.server_proc=None
        self.playit_proc=None
        self.lock_sha=None
        self.job=WindowsJob()
        self.recovery=load_recovery()
        self.autosave_stop=threading.Event()
        self.git_mutex=threading.RLock()
        self._refresh_running=False
        self._refresh_pending=False
        self._refresh_generation=0
        self._closing_after_sync=False
        self.console_queue=queue.Queue()
        self.server_ready_event=threading.Event()

        same_recovery=bool(self.recovery and self.recovery.get("server_dir")==self.cfg.get("server_dir"))
        if same_recovery:
            self.lock_sha=self.recovery.get("lock_sha")
            self.state=RECOVERY_REQUIRED
        else:
            self.state=IDLE

        self.setWindowTitle(f"Minecraft Relay V{VERSION}")
        self.resize(1020,700)
        self.ui()
        self.logS.connect(self.log)
        self.infoS.connect(self.apply_info)
        self.stateS.connect(self.set_state)
        self.console_timer=QTimer(self)
        self.console_timer.setInterval(50)
        self.console_timer.timeout.connect(self.flush_console_queue)
        self.console_timer.start()
        self.render_state()
        self.refresh()

    @property
    def cwd(self): return self.cfg["server_dir"]

    def git(self,*a,t=60):
        # All Git access, including read-only refreshes, is serialized.
        with self.git_mutex:
            return run(["git",*a],self.cwd,t)

    def ui(self):
        w=QWidget(); self.setCentralWidget(w)
        o=QVBoxLayout(w); o.setContentsMargins(28,24,28,24); o.setSpacing(14)
        title=QLabel(f"Minecraft Relay  V{VERSION}"); title.setObjectName("title"); o.addWidget(title)
        self.update_status=QLabel("Application updates will be checked in the background.")
        self.update_status.setWordWrap(True)
        o.addWidget(self.update_status)

        c=QFrame(); c.setObjectName("card"); v=QVBoxLayout(c)
        self.world=QLabel(); self.host=QLabel(); self.playst=QLabel(); self.srv=QLabel(); self.address=QLabel()
        for x in [self.world,self.host,self.playst,self.srv,self.address]: v.addWidget(x)
        o.addWidget(c)

        r=QHBoxLayout()
        self.hb=QPushButton("▶  HOST SERVER"); self.hb.setObjectName("primary"); self.hb.clicked.connect(self.host_server)
        self.sb=QPushButton("■  STOP & SYNC"); self.sb.clicked.connect(self.stop_sync)
        self.rf=QPushButton("Refresh"); self.rf.clicked.connect(self.refresh)
        self.resolve_button=QPushButton("Resolve World"); self.resolve_button.clicked.connect(self.resolve_world)
        st=QPushButton("⚙ Settings"); st.clicked.connect(self.settings)
        for b in [self.hb,self.sb,self.rf,self.resolve_button,st]: r.addWidget(b)
        r.addStretch(); o.addLayout(r)

        o.addWidget(QLabel("Server Console"))
        self.con=QPlainTextEdit(); self.con.setReadOnly(True); self.con.setFont(QFont("Consolas",10))
        self.con.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.con.document().setMaximumBlockCount(3000); o.addWidget(self.con,1)

        rr=QHBoxLayout()
        self.cmd=QLineEdit(); self.cmd.setPlaceholderText("Server command…"); self.cmd.returnPressed.connect(self.send)
        self.sendb=QPushButton("Send"); self.sendb.clicked.connect(self.send)
        rr.addWidget(self.cmd); rr.addWidget(self.sendb); o.addLayout(rr)

        self.setStyleSheet("""QMainWindow,QWidget{background:#f5f6f8;color:#202124;font-family:"Segoe UI";font-size:14px} QLabel#title{font-size:30px;font-weight:700}
        QFrame#card{background:white;border:1px solid #dfe3e8;border-radius:10px;padding:14px}
        QPushButton{background:#ffffff;border:1px solid #c9ced6;border-radius:7px;padding:8px 14px}
        QPushButton:hover:enabled{background:#e8ebef;border-color:#9ca3ad}
        QPushButton:pressed:enabled{background:#cfd4da;border-color:#737b86;padding-top:10px;padding-bottom:6px}
        QPushButton:disabled{background:#eef0f2;color:#9aa0a6;border-color:#d9dde2}
        QPushButton#primary{background:#202124;color:white;border:1px solid #202124;font-weight:700;padding:10px 18px}
        QPushButton#primary:hover:enabled{background:#34373b;border-color:#34373b}
        QPushButton#primary:pressed:enabled{background:#050505;border-color:#050505;padding-top:12px;padding-bottom:8px}
        QPlainTextEdit{background:#1e1e1e;color:#d4d4d4;border-radius:8px;padding:8px}
        QLineEdit{background:white;border:1px solid #c9ced6;border-radius:6px;padding:8px}""")

    def log(self,msg):
        self.console_queue.put(msg.rstrip())

    def flush_console_queue(self):
        lines=[]
        # Bound each UI tick so a pathological log flood cannot monopolize Qt.
        for _ in range(250):
            try:
                lines.append(self.console_queue.get_nowait())
            except queue.Empty:
                break
        if lines:
            self.con.appendPlainText("\n".join(lines))

    def set_state(self,new_state,reason=""):
        # This slot runs on the Qt thread and is the ONLY authority allowed to change lifecycle state.
        self.state=new_state
        self._refresh_generation+=1
        if reason:
            self.log(reason)
        self.render_state()
        self.refresh()
        if new_state==IDLE and self._closing_after_sync:
            self._closing_after_sync=False
            QTimer.singleShot(0,self.close)

    def render_state(self):
        st=self.state
        self.resolve_button.setEnabled(st in (IDLE,RECOVERY_REQUIRED) and not (self.server_proc and self.server_proc.poll() is None))
        self.hb.setVisible(st==IDLE)
        self.sb.setVisible(st in (STARTING,RUNNING,STOPPING,RECOVERY_REQUIRED,RECOVERING,ERROR))

        self.hb.setEnabled(st==IDLE)
        if st==STARTING:
            self.sb.setText("◐  STARTING…"); self.sb.setEnabled(False)
        elif st==RUNNING:
            self.sb.setText("■  STOP & SYNC"); self.sb.setEnabled(True)
        elif st==STOPPING:
            self.sb.setText("◐  STOPPING & SYNCING…"); self.sb.setEnabled(False)
        elif st==RECOVERY_REQUIRED:
            self.sb.setText("⚠  RECOVER & SYNC"); self.sb.setEnabled(True)
        elif st==RECOVERING:
            self.sb.setText("◐  RECOVERING & SYNCING…"); self.sb.setEnabled(False)
        elif st==ERROR:
            self.sb.setText("⚠  RECOVER & SYNC"); self.sb.setEnabled(bool(self.recovery))
        else:
            self.sb.setEnabled(False)

        alive=bool(self.server_proc and self.server_proc.poll() is None)
        can_command=(st==RUNNING and alive)
        self.cmd.setEnabled(can_command)
        self.sendb.setEnabled(can_command)

        # Lifecycle owns local process display. Refresh cannot overwrite this.
        if st==STARTING: self.srv.setText("Server      ◐ Starting")
        elif st==RUNNING: self.srv.setText("Server      ● Online")
        elif st==STOPPING: self.srv.setText("Server      ◐ Stopping")
        elif st in (RECOVERY_REQUIRED,RECOVERING): self.srv.setText("Server      ⚠ Recovery required")
        else: self.srv.setText("Server      ○ Offline")

    def resolve_world(self):
        if self.state not in (IDLE,RECOVERY_REQUIRED):return
        if self.server_proc and self.server_proc.poll() is None:return
        box=QMessageBox(self)
        box.setWindowTitle("Choose the world to keep")
        box.setIcon(QMessageBox.Warning)
        box.setText("Which complete world version should everyone continue playing?")
        box.setInformativeText("All hosts must be stopped. A local world ZIP and Git history backup will be saved first. Keep GitHub replaces this computer's files. Keep Local publishes this computer's files while preserving both histories. Another host's lock will never be removed.")
        remote=box.addButton("Keep GitHub",QMessageBox.AcceptRole)
        local=box.addButton("Keep Local",QMessageBox.DestructiveRole)
        cancel=box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(cancel)
        box.exec()
        if box.clickedButton() not in (remote,local):return
        choice="remote" if box.clickedButton() is remote else "local"
        self.set_state(RECOVERING)
        threading.Thread(target=self._resolve_transaction,args=(choice,),daemon=True).start()

    def settings(self):
        if self.state not in (IDLE,RECOVERY_REQUIRED):
            QMessageBox.warning(self,"Server active","Settings cannot be changed while hosting or synchronizing.")
            return
        d=Settings(self.cfg,self)
        if d.exec():
            self.cfg=load_config()
            self._refresh_generation+=1
            self.refresh()

    # ---------- informational refresh: observation only ----------
    def refresh(self):
        if self._refresh_running:
            self._refresh_pending=True
            return
        self._refresh_running=True
        self._refresh_generation+=1
        generation=self._refresh_generation
        threading.Thread(target=self._refresh_worker,args=(generation,),daemon=True).start()

    def _refresh_worker(self,generation):
        info={"generation":generation}
        try:
            d=Path(self.cwd)
            info["repo_ok"]=(d/".git").exists()
            if info["repo_ok"]:
                # Do not wait behind a lifecycle Git transaction merely to repaint UI.
                if not self.git_mutex.acquire(blocking=False):
                    info["git_busy"]=True
                    info["dirty"]=None; info["sha"]=None; info["msg"]=""
                else:
                    try:
                        info["git_busy"]=False
                        rem=self.cfg["git_remote"]
                        g=WorldGit(self.cwd,rem,self.cfg["git_branch"])
                        info.update(g.relation())
                        _,sha=g.remote_refs()
                        if not sha:
                            info["sha"]=None; info["msg"]=""
                        else:
                            info["sha"]=sha
                            info["msg"]=run(["git","show","-s","--format=%B",info["sha"]],self.cwd,20).stdout.strip()
                    finally:
                        self.git_mutex.release()
            else:
                info.update(git_busy=False,dirty=False,sha=None,msg="")
            info["playit_ready"]=bool(find_playit() or Path(self.cfg.get("playit_command","")).exists())
            info["address_default"]=self.cfg.get("public_address","")
            info["error"]=None
        except Exception as e:
            info["error"]=str(e)
        self.infoS.emit(info)

    def apply_info(self,info):
        self._refresh_running=False
        if info.get("generation") != self._refresh_generation:
            self._refresh_pending=False
            self.refresh()
            return  # stale observation; re-read the current state
        if self._refresh_pending:
            self._refresh_pending=False
            QTimer.singleShot(0,self.refresh)
        if info.get("error"):
            self.log("[Relay] Status: "+info["error"])
            self.world.setText("World       ⚠ Unable to verify synchronization")
            if self.state==IDLE:self.host.setText("Host        ⚠ Remote status unavailable")
            return

        if not info["repo_ok"]:
            self.world.setText("World       ⚠ Repository not configured")
        elif info.get("git_busy"):
            self.world.setText("World       ◐ Sync operation in progress")
        elif info.get("dirty") is None:
            pass
        else:
            ahead,behind=info.get("ahead",0),info.get("behind",0)
            if ahead and behind:message=f"⚠ Diverged: {ahead} local / {behind} remote commits — Resolve World"
            elif ahead:message=f"⚠ {ahead} local commits not uploaded — Resolve World"
            elif behind:message=f"↓ {behind} remote commits to download before hosting"
            else:message="● Synced with GitHub"
            if info["dirty"]:
                message="⚠ Uncommitted local changes"+("; "+message if ahead or behind else "")
            self.world.setText("World       "+message)

        sha,msg=info.get("sha"),info.get("msg","")
        active=info.get("address_default","")
        if self.state in (STARTING,RUNNING,STOPPING):
            # Local lifecycle is authoritative while this computer owns/uses the session.
            self.host.setText("Host        ● Hosted by "+self.cfg.get("host_name","this computer"))
            active=self.cfg.get("public_address","") or active
        elif self.state in (RECOVERY_REQUIRED,RECOVERING,ERROR) and self.recovery:
            self.host.setText("Host        ⚠ Recovery owned by "+self.recovery.get("host_name",self.cfg.get("host_name","this computer")))
        elif sha:
            h=re.search(r"host=([^|]+)",msg); a=re.search(r"address=([^|]+)",msg)
            self.host.setText("Host        ● Hosted by "+(h.group(1).strip() if h else "another host"))
            active=a.group(1).strip() if a else active
        else:
            self.host.setText("Host        ● Available")

        self.playst.setText("Playit      "+("● Ready" if info["playit_ready"] else "⚠ Missing"))
        self.address.setText("Active address    "+(active or "Not configured"))
        self.render_state()

    # ---------- lifecycle transactions ----------


    def closeEvent(self,e):
        if self.state in (STARTING,STOPPING,RECOVERING):
            QMessageBox.warning(self,"Operation in progress","Wait for the current operation to finish before closing.")
            e.ignore(); return

        if self.state in (RUNNING,RECOVERY_REQUIRED,ERROR):
            box=QMessageBox(self)
            box.setWindowTitle("Session still active")
            box.setIcon(QMessageBox.Warning)
            if self.state==RUNNING:
                box.setText("Minecraft Relay is still hosting this world.")
                box.setInformativeText("Use Stop & Sync before closing so the world is saved and uploaded safely.")
                go=box.addButton("Stop & Sync",QMessageBox.AcceptRole)
            else:
                box.setText("This computer has an unsynchronized recovery session.")
                box.setInformativeText("Recover & Sync before closing if you want to finish synchronization now.")
                go=box.addButton("Recover & Sync",QMessageBox.AcceptRole)
            box.addButton("Cancel",QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is go:
                self._closing_after_sync=True
                self.stop_sync()
            e.ignore(); return

        self.autosave_stop.set()
        try:self.job.close()
        except:pass
        e.accept()
