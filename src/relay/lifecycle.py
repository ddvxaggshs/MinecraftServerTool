import subprocess, threading, time, zipfile, json
from pathlib import Path
from datetime import datetime, timezone
from .paths import VERSION, LOCK_REF, REMOTE_LOCK_REF, BACKUP_DIR, IDLE, STARTING, RUNNING, STOPPING, RECOVERY_REQUIRED, RECOVERING, ERROR
from .config import save_recovery, clear_recovery
from .processes import run, java21, find_playit
from .world_git import WorldGit

class Lifecycle:
    def _resolve_transaction(self,choice):
        try:
            if choice not in ("remote","local"):
                raise RuntimeError("Invalid version selection.")
            if self.server_proc and self.server_proc.poll() is None:
                raise RuntimeError("Stop the local server before resolving world versions.")
            with self.git_mutex:
                g=self.world_git()
                g.check_branch()
                _,lock=g.remote_refs()
                owned=self.lock_sha or (self.recovery or {}).get("lock_sha")
                if lock and lock!=owned:
                    raise RuntimeError("Another host owns the lock. It must stop and synchronize first.")
                BACKUP_DIR.mkdir(parents=True,exist_ok=True)
                stamp=datetime.now().strftime("%Y%m%d-%H%M%S-%f")
                if self.recovery:
                    (BACKUP_DIR/f"session-{stamp}.json").write_text(json.dumps(self.recovery,indent=2),encoding="utf-8")
                if not lock:self.claim_lock(g)
                self.make_recovery_backup()
                g.command("rm","--cached","--ignore-unmatch","world/session.lock")
                ignore=Path(self.cwd)/".gitignore"
                text=ignore.read_text(encoding="utf-8") if ignore.exists() else ""
                if "world/session.lock" not in text:
                    ignore.write_text(text.rstrip()+"\nworld/session.lock\n",encoding="utf-8")
                g.command("add","-A")
                if g.command("diff","--cached","--name-only"):
                    g.command("commit","-m","Preserve local files before world resolution")
                branch="backup/relay-"+stamp
                g.command("branch",branch,"HEAD")
                remote=g.fetch()
                g.command("bundle","create",str(BACKUP_DIR/f"history-{stamp}.bundle"),"--all")
                self.logS.emit(f"[Safety] Local version preserved in {branch} and recovery-backups.")
                # Snapshot and lock are established before either version is selected.
                g.require_owner(self.lock_sha)
                if choice=="remote":
                    g.command("reset","--hard",remote)
                else:
                    local=g.command("rev-parse","HEAD")
                    parents=["-p",local]
                    if remote!=local:parents.extend(["-p",remote])
                    merge=g.command("commit-tree",g.command("rev-parse","HEAD^{tree}"),*parents,
                                    input="Resolve world versions: keep local files\n")
                    g.command("merge","--ff-only",merge)
                g.publish_and_unlock(self.lock_sha)
                self.clear_session()
            if self.playit_proc and self.playit_proc.poll() is None:self.playit_proc.terminate()
            self.server_proc=None; self.playit_proc=None
            self.stateS.emit(IDLE,"[Relay] World versions resolved and synchronized. You can host now.")
        except Exception as error:
            self.stateS.emit(RECOVERY_REQUIRED if self.recovery else IDLE,"[Relay] Resolve failed: "+str(error))

    def world_git(self):
        return WorldGit(self.cwd,self.cfg["git_remote"],self.cfg["git_branch"])

    def clear_session(self):
        clear_recovery()
        self.lock_sha=None
        self.recovery=None

    def claim_lock(self,g):
        _,existing=g.remote_refs()
        if existing:
            raise RuntimeError("Another host owns the lock. Stop that host before continuing.")
        tree=g.command("rev-parse","HEAD^{tree}")
        msg=f"MC Relay lock | host={self.cfg['host_name']} | address={self.cfg['public_address']} | time={datetime.now(timezone.utc).isoformat()}"
        sha=g.command("commit-tree",tree,"-p","HEAD",input=msg+"\n")
        # Write the intent before the network operation: an interrupted push is recoverable.
        self.lock_sha=sha
        self.recovery={"lock_sha":sha,"host_name":self.cfg["host_name"],"server_dir":self.cwd,
                       "repo_url":self.cfg.get("repo_url",""),"started_at":datetime.now(timezone.utc).isoformat()}
        save_recovery(self.recovery)
        try:
            g.command("push","--force-with-lease="+LOCK_REF+":",g.remote,sha+":"+LOCK_REF)
        except Exception:
            # If the request outcome cannot be checked, keep the recovery intent.
            _,actual=g.remote_refs()
            if actual!=sha:self.clear_session()
            raise

    def acquire(self):
        with self.git_mutex:
            g=self.world_git()
            g.check_branch()
            if g.meaningful_changes():
                raise RuntimeError("Local progress/settings changed: " + ", ".join(g.meaningful_changes()[:5]) + ". Use Resolve World or recover the previous session.")
            self.claim_lock(g)
            try:
                # The final world commit and lock release are atomic. Fetch after
                # claiming so a status observation can never miss that final save.
                remote=g.fetch()
                if g.sync_checkout(remote):
                    self.logS.emit("[Git] Latest world synchronized. Starting server...")
            except Exception:
                # Java has not started; leave genuine local progress untouched and
                # release only our own newly acquired lock, not a recovery session.
                g.delete_owned_lock(self.lock_sha)
                self.clear_session()
                raise

    def release(self):
        with self.git_mutex:
            owned=self.lock_sha or (self.recovery or {}).get("lock_sha")
            if owned:self.world_git().delete_owned_lock(owned)
            self.clear_session()

    def host_server(self):
        if self.state!=IDLE or not self.remote_status_known or self.remote_lock:
            return
        self._last_server_exit=None
        self._expected_stop_proc=None
        self.set_state(STARTING)
        threading.Thread(target=self._host_transaction,daemon=True).start()


    def _host_transaction(self):
        acquired=False
        try:
            self.logS.emit("[Relay] Preparing world and acquiring host lock…")
            self.acquire(); acquired=True
            self.logS.emit("[Relay] ✓ Host lock acquired.")

            p=self.cfg.get("playit_command") or find_playit()
            if not p or not Path(p).exists(): p=find_playit()
            if not p: raise RuntimeError("Playit missing. Open Settings.")
            self.playit_proc=subprocess.Popen([p],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                                               stdin=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
            self.job.assign(self.playit_proc)
            self.logS.emit("[Playit] ✓ Agent started.")

            j=java21() or self.cfg.get("java","java")
            cmd=[j,f"-Xms{self.cfg['min_ram']}",f"-Xmx{self.cfg['max_ram']}","-jar",self.cfg["server_jar"],"nogui"]
            self.server_proc=subprocess.Popen(cmd,cwd=self.cwd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                               stderr=subprocess.STDOUT,text=True,encoding="utf-8",errors="replace",
                                               creationflags=subprocess.CREATE_NO_WINDOW)
            self.job.assign(self.server_proc)

            self.server_ready_event.clear()
            self.autosave_stop.clear()
            threading.Thread(target=self.reader,args=(self.server_proc,),daemon=True).start()

            # RUNNING means Minecraft itself is ready, not merely that java.exe exists.
            deadline=time.monotonic()+120
            while time.monotonic()<deadline:
                if self.server_proc.poll() is not None:
                    raise RuntimeError(f"Minecraft server exited during startup ({self.server_proc.returncode}).")
                if self.server_ready_event.wait(0.10):
                    break
            else:
                raise RuntimeError("Minecraft did not report ready within 120 seconds.")

            threading.Thread(target=self.autosave_loop,daemon=True).start()
            self.stateS.emit(RUNNING,"[Relay] ✓ Minecraft reported ready; server running.")
        except Exception as e:
            self.logS.emit("[Relay] START ERROR: "+str(e))
            self.autosave_stop.set()
            server_started=self.server_proc is not None
            try:
                self.stop_server_process()
            except Exception as cleanup:
                self.logS.emit("[Relay] Server cleanup failed; lock retained: "+str(cleanup))
            if self.playit_proc and self.playit_proc.poll() is None:
                try:self.playit_proc.terminate()
                except:pass
            if server_started:
                # Even an unsuccessful startup can modify the world. Sync before unlocking.
                self.stateS.emit(RECOVERY_REQUIRED,"[Relay] Recovery required after failed startup; lock retained.")
            elif acquired:
                try:
                    self.release()
                    self.stateS.emit(IDLE,"[Relay] Startup rolled back safely.")
                except Exception as cleanup:
                    self.logS.emit("[Relay] Lock cleanup failed: "+str(cleanup))
                    self.stateS.emit(RECOVERY_REQUIRED,"[Relay] Recovery required after failed startup.")
            elif self.recovery:
                self.stateS.emit(RECOVERY_REQUIRED,"[Relay] Recovery required after incomplete lock acquisition.")
            else:
                self.stateS.emit(IDLE,"")


    def stop_server_process(self):
        proc=self.server_proc
        if proc is None or proc.poll() is not None:
            return proc is None or proc.returncode==0
        self._expected_stop_proc=proc
        graceful=True
        self.logS.emit("[Minecraft] Saving and stopping…")
        try:
            proc.stdin.write("save-all flush\nstop\n")
            proc.stdin.flush()
            proc.wait(120)
        except Exception as e:
            graceful=False
            self.logS.emit("[Relay] Graceful stop failed; terminating Java: "+str(e))
            if proc.poll() is None:
                proc.kill()
            proc.wait(15)
        if proc.poll() is None:
            raise RuntimeError("Java is still running. Refusing to synchronize or release the lock.")
        return graceful and proc.returncode==0


    def reader(self,proc):
        graceful=False
        code=None
        try:
            for raw in proc.stdout:
                line=raw.rstrip("\r\n")
                self.console_queue.put(line)
                if "[Server thread/INFO]: Stopping server" in line:
                    graceful=True
                # Vanilla/Fabric ready line: "Done (x.xxxs)! For help, type "help""
                if "Done (" in line and 'For help, type "help"' in line:
                    self.server_ready_event.set()
            code=proc.wait()
            self.console_queue.put(f"[Minecraft] Server exited ({code}).")
        finally:
            # Only the GUI thread decides whether this exit is expected. Carry the
            # process identity so delayed notifications cannot corrupt a new session.
            self.serverExitS.emit(proc,code,graceful)

    def server_exited(self,proc,code,graceful):
        if proc is not self.server_proc:
            return
        self._last_server_exit=(proc,code,graceful)
        if proc is self._expected_stop_proc or self.state in (STOPPING,RECOVERING,STARTING):
            return
        if self.state==RUNNING:
            self.autosave_stop.set()
            if code==0 and graceful:
                self.log("[Minecraft] Normal server shutdown detected; synchronizing automatically.")
                self.stop_sync()
            else:
                self.set_state(RECOVERY_REQUIRED,"[Relay] Minecraft stopped unexpectedly. Recover & Sync is required.")


    def autosave_loop(self):
        while not self.autosave_stop.wait(300):
            try:
                if self.state==RUNNING and self.server_proc and self.server_proc.poll() is None:
                    self.server_proc.stdin.write("save-all flush\n"); self.server_proc.stdin.flush()
                    self.logS.emit("[Safety] Periodic save-all flush completed.")
            except Exception:
                return


    def make_recovery_backup(self):
        world=Path(self.cwd)/"world"
        if not world.exists():return None
        BACKUP_DIR.mkdir(parents=True,exist_ok=True)
        stamp=datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        target=BACKUP_DIR/f"world-recovery-{stamp}.zip"
        self.logS.emit("[Safety] Creating local recovery snapshot…")
        with zipfile.ZipFile(target,"w",zipfile.ZIP_DEFLATED,allowZip64=True) as z:
            for f in world.rglob("*"):
                if f.is_file() and f.name!="session.lock":
                    z.write(f,f.relative_to(Path(self.cwd)))
        self.logS.emit(f"[Safety] Recovery snapshot: {target.name}")
        return target


    def send(self):
        if self.state!=RUNNING:
            return
        cmd=self.cmd.text().strip()
        if not cmd:return
        proc=self.server_proc
        if not proc or proc.poll() is not None:
            self.stateS.emit(RECOVERY_REQUIRED,"[Relay] Server process disappeared; recovery required.")
            return
        try:
            if cmd.startswith("/"):cmd=cmd[1:]
            self.logS.emit("> "+cmd)
            if cmd.lower()=="stop":
                self.cmd.clear()
                self.stop_sync()
                return
            proc.stdin.write(cmd+"\n"); proc.stdin.flush()
            self.cmd.clear()
        except Exception as e:
            self.logS.emit("[Relay] ERROR sending server command: "+str(e))


    def stop_sync(self):
        if self.state==RUNNING:
            self._expected_stop_proc=self.server_proc
            self.set_state(STOPPING)
            threading.Thread(target=self._stop_transaction,args=(False,),daemon=True).start()
        elif self.state in (RECOVERY_REQUIRED,ERROR):
            self._expected_stop_proc=self.server_proc
            self.set_state(RECOVERING)
            threading.Thread(target=self._stop_transaction,args=(True,),daemon=True).start()


    def _stop_transaction(self,is_recovery):
        try:
            self.autosave_stop.set()

            # Recovery must also stop a process left alive by an earlier failed cleanup.
            graceful=self.stop_server_process()

            # Check ownership BEFORE backups, commits or any world upload.
            with self.git_mutex:
                self.world_git().require_owner(self.lock_sha or (self.recovery or {}).get("lock_sha"))

            if is_recovery or not graceful:
                # Never ZIP a normal stop; only interrupted sessions get the extra snapshot.
                self.make_recovery_backup()

            gi=Path(self.cwd)/".gitignore"
            try:
                txt=gi.read_text(encoding="utf-8") if gi.exists() else ""
                if "world/session.lock" not in txt:
                    gi.write_text(txt.rstrip()+"\nworld/session.lock\n",encoding="utf-8")
            except Exception: pass

            with self.git_mutex:
                self.world_git().check_branch()
                self.world_git().require_owner(self.lock_sha or (self.recovery or {}).get("lock_sha"))
                self.logS.emit("[Git] Saving session…")
                self.world_git().stage_session()
                if run(["git","diff","--cached","--quiet"],self.cwd,30).returncode:
                    c=run(["git","commit","-m",f"Relay world save - {self.cfg['host_name']}"],self.cwd,60)
                    if c.returncode: raise RuntimeError(c.stderr or c.stdout)
                self.world_git().publish_and_unlock(self.lock_sha or (self.recovery or {}).get("lock_sha"))
                self.clear_session()
            self.logS.emit("[Relay] ✓ World synchronized.")

            if self.playit_proc and self.playit_proc.poll() is None:
                try:
                    self.playit_proc.terminate()
                    try:self.playit_proc.wait(8)
                    except subprocess.TimeoutExpired:
                        self.playit_proc.kill()
                        self.playit_proc.wait(8)
                except Exception as error:
                    # World publication already succeeded and its lock is gone.
                    # A tunnel cleanup error is not an unsynchronized world/crash.
                    self.logS.emit("[Playit] World is saved; tunnel cleanup warning: " + str(error))
            self.server_proc=None
            if self.playit_proc is None or self.playit_proc.poll() is not None:
                self.playit_proc=None
            self.stateS.emit(IDLE,"")
        except Exception as e:
            self.logS.emit("[Relay] SYNC ERROR: "+str(e))
            # Keep recovery/lock intact. Never pretend the session is safe.
            self.stateS.emit(RECOVERY_REQUIRED,"[Relay] ⚠ Synchronization incomplete; lock retained.")
