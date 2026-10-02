"""Self-contained bootstrap EXE: first install, background check, safe replacement."""
import argparse
import json
from pathlib import Path
import queue
import threading
import time

from bootstrap.engine import Installer, channel, write_json, contained
from bootstrap.platform import installation_root, Mutex, ParentProcess, spawn
from bootstrap.policy import MAIN_EXE


def run(args, report):
    root = Path(args.root).resolve() if args.root else installation_root()
    parent = ParentProcess(args.parent) if args.parent else None
    try:
        with Mutex(root, role="MinecraftManager-Updater"):
            installer = Installer(root, report)
            status_file = contained(root, installer.folder / ("check-" + args.session + ".json"))
            approval = contained(root, installer.folder / ("approve-" + args.session + ".json"))

            def status(message, ready=False, done=False):
                report(message)
                write_json(status_file, {"session": args.session, "message": message, "ready": ready, "done": done})

            try:
                status("Checking GitHub for application updates...")
                manifest = channel()
                if args.check_only:
                    status("Published version: " + manifest["version"] + ". Source checkout is managed with Git.", done=True)
                    return
                if not installer.needs_update(manifest):
                    status("Application is up to date.", done=True)
                    if not parent:
                        with Mutex(root):
                            spawn([str(installer.app / MAIN_EXE)], root)
                    return
                stage = installer.prepare(manifest)
                if parent:
                    status("Update ready. Waiting for a safe application exit...", ready=True)
                    while not parent.exited():
                        time.sleep(.2)
                    if not approval.exists():
                        status("Application did not authorize installation; update deferred.", done=True)
                        return
                    authorization = json.loads(approval.read_text(encoding="utf-8"))
                    approval.unlink()
                    if authorization.get("session") != args.session:
                        raise RuntimeError("Invalid update handoff")
                # A second main instance cannot start during the rename transaction.
                with Mutex(root, timeout=5000):
                    installer.install(stage)
                    status("Update installed. Restarting application...", done=True)
                    spawn([str(installer.app / MAIN_EXE)], root)
            except Exception as error:
                status("Update failed: " + str(error), done=True)
                raise
    finally:
        if parent:
            parent.close()


def main():
    import uuid
    parser = argparse.ArgumentParser()
    parser.add_argument("--root")
    parser.add_argument("--parent", type=int)
    parser.add_argument("--session", default=uuid.uuid4().hex)
    parser.add_argument("--background", action="store_true")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    if not args.session.isalnum() or len(args.session) > 64:
        parser.error("Invalid update session")
    if args.background:
        try:
            run(args, lambda text: None)
        except Exception:
            # Main GUI reads the error status. Never open a background error dialog.
            return 1
        return 0

    import tkinter as tk
    from tkinter import ttk
    window = tk.Tk()
    window.title("Minecraft Manager - Install / Update")
    window.geometry("570x175")
    window.resizable(False, False)
    label = ttk.Label(window, text="Preparing installation...", wraplength=530)
    label.pack(padx=20, pady=20, anchor="w")
    progress = ttk.Progressbar(window, mode="indeterminate")
    progress.pack(fill="x", padx=20)
    progress.start()
    events = queue.Queue()
    window.protocol("WM_DELETE_WINDOW", lambda: None)

    def worker():
        try:
            run(args, lambda text: events.put(("status", text)))
            events.put(("done", ""))
        except Exception as error:
            events.put(("error", str(error)))

    def poll():
        while not events.empty():
            kind, text = events.get()
            if kind == "done":
                window.destroy()
                return
            label.configure(text=text)
            if kind == "error":
                progress.stop()
                ttk.Button(window, text="Close", command=window.destroy).pack(pady=8)
                window.protocol("WM_DELETE_WINDOW", window.destroy)
                return
        window.after(100, poll)

    threading.Thread(target=worker, daemon=True).start()
    window.after(100, poll)
    window.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
