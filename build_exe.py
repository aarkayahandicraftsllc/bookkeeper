"""Packages the desktop app into a single Windows executable.

    python build_exe.py

Produces dist/Bookkeeper.exe — copy it anywhere and double-click. Python does not
need to be installed on the machine that runs it.

The books themselves live in data/books.db next to the executable, so keep the
two together, or point BOOKS_DB somewhere else (OneDrive, a shared folder).
"""

import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> int:
    for stale in ("build", "dist"):
        shutil.rmtree(HERE / stale, ignore_errors=True)

    command = [
        sys.executable, "-m", "PyInstaller",
        "--name", "Bookkeeper",
        "--onefile",
        "--windowed",                 # no console window
        "--noconfirm",
        "--clean",
        # the data layer and reports are plain modules, pulled in explicitly
        "--hidden-import", "db",
        "--hidden-import", "accounting",
        "--paths", str(HERE),
        str(HERE / "desktop.py"),
    ]
    print(" ".join(command), "\n")
    result = subprocess.run(command, cwd=HERE)
    if result.returncode:
        return result.returncode

    built = HERE / "dist" / "Bookkeeper.exe"
    if built.exists():
        size = built.stat().st_size / (1024 * 1024)
        print(f"\nBuilt {built}  ({size:.0f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
