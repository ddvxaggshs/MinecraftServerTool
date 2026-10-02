"""Stable entry: do not replace this binary during routine application updates."""
from bootstrap.platform import installation_root, Mutex, spawn, show_error
from bootstrap.policy import MAIN_EXE


def main():
    root = installation_root()
    try:
        # Serialize against directory replacement. The app takes the same mutex.
        with Mutex(root):
            exe = root / "app" / MAIN_EXE
            if not exe.exists():
                spawn([str(root / "updater.exe")], root)
                return
            spawn([str(exe)], root)
    except Exception as error:
        show_error(error)


if __name__ == "__main__":
    main()
