"""Separate updater process, invoked once per main application startup."""
import argparse
import traceback
from .paths import DATA_DIR
from .updater import UpdateManager, atomic_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", required=True)
    args = parser.parse_args()
    manager = UpdateManager()
    manager.folder.mkdir(parents=True, exist_ok=True)
    status_file = manager.folder / "check-status.json"
    def report(message, done=False):
        atomic_json(status_file, {"session": args.session, "message": message,
                                 "done": done, "ready": manager.ready})
    manager.status.connect(report)
    try:
        manager._check()
        previous = __import__("json").loads(status_file.read_text(encoding="utf-8"))
        report(previous["message"], True)
    except Exception:
        (DATA_DIR / "update-component-error.log").write_text(traceback.format_exc(), encoding="utf-8")
        report("Updater could not finish. The current version can still be used.", True)


if __name__ == "__main__":
    main()
