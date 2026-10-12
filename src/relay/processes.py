import os, re, shutil, subprocess, threading, time, queue
from pathlib import Path
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QProgressDialog

from .process_job import WindowsJob
from .command_runner import run

def run_gui(cmd,cwd=None,timeout=60):
    """Keep Qt painting while a modal Git operation runs on a worker thread."""
    result=queue.Queue()
    def work():
        try:result.put((run(cmd,cwd,timeout),None))
        except Exception as e:result.put((None,e))
    dialog=QProgressDialog("Waiting for Git… Complete browser authentication if prompted.",
                           "",0,0,QApplication.activeWindow())
    dialog.setCancelButton(None)
    dialog.setWindowTitle("Git operation")
    dialog.setWindowModality(Qt.ApplicationModal)
    dialog.setWindowFlag(Qt.WindowCloseButtonHint,False)
    # Prevent Escape/close from abandoning an operation that may still write files.
    dialog.reject=lambda: None
    outcome=[]
    def poll():
        try:value=result.get_nowait()
        except queue.Empty:return
        outcome.append(value)
        timer.stop()
        dialog.accept()
    timer=QTimer(dialog)
    timer.timeout.connect(poll)
    timer.start(25)
    threading.Thread(target=work,daemon=True).start()
    dialog.exec()
    value,error=outcome[0]
    if error:raise error
    return value
def which(name): return shutil.which(name)
def find_playit():
    from .paths import APP_DIR
    for p in [str(APP_DIR/"playit/playit.exe"),r"C:\Program Files\playit_gg\bin\playit.exe",
              r"C:\Program Files\playit\playit.exe", which("playit")]:
        if p and Path(p).exists(): return str(p)
    return None
_java_cache={"path":None,"result":None,"expires":0}
def java21():
    p=which("java")
    if not p:return None
    if p==_java_cache["path"] and time.monotonic()<_java_cache["expires"]:
        return _java_cache["result"]
    try:
        r=run([p,"-version"],timeout=10)
        s=r.stderr+r.stdout
        m=re.search(r'version "(\d+)',s)
        result=p if r.returncode==0 and m and int(m.group(1))>=21 else None
        _java_cache.update(path=p,result=result,expires=time.monotonic()+15)
        return result
    except:return None
def winget_install(pkg):
    return subprocess.Popen(["winget","install","--id",pkg,"-e",
        "--accept-source-agreements","--accept-package-agreements"],
        creationflags=subprocess.CREATE_NEW_CONSOLE)
