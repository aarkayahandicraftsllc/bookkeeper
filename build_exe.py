"""Packages the desktop app into a single Windows executable.

    python build_exe.py

Produces dist/Bookkeeper.exe — copy it anywhere and double-click. Python does not
need to be installed on the machine that runs it.

The books themselves live in data/books.db next to the executable, so keep the
two together, or point BOOKS_DB somewhere else (OneDrive, a shared folder).

**The executable it replaces is kept.** This script wipes dist/ before
building, which used to destroy the only copy of the working app - so a bad
build left nothing to fall back to. The outgoing exe is now moved to
previous/Bookkeeper-<when it was built>.exe first, the newest KEEP_PREVIOUS are
retained, and if PyInstaller fails the last good one is put back in dist/ so
you are never left without a runnable app.
"""

import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
DIST = HERE / "dist"
PREVIOUS = HERE / "previous"
EXE_NAME = "Bookkeeper.exe"

# How many superseded builds to keep. Two rather than one: if you rebuild twice
# before noticing a problem, one would already have overwritten your only good
# copy. Each is ~144 MB, so this caps the cost at roughly 290 MB.
KEEP_PREVIOUS = 2


def archive_current() -> Path | None:
    """Move the exe that is about to be replaced into previous/.

    Named for when that build was MADE, not when it was archived, so the
    filenames line up with what you remember building. Returns the archive
    path, to put back if the new build fails.
    """
    current = DIST / EXE_NAME
    if not current.exists():
        return None

    PREVIOUS.mkdir(exist_ok=True)
    stamp = datetime.fromtimestamp(current.stat().st_mtime).strftime(
        "%Y%m%d-%H%M%S")
    kept = PREVIOUS / f"Bookkeeper-{stamp}.exe"
    if kept.exists():          # same build archived twice - leave the first
        current.unlink()
        print(f"Already kept {kept.name}")
        return kept
    shutil.move(str(current), str(kept))
    size = kept.stat().st_size / (1024 * 1024)
    print(f"Kept the previous build: {kept.relative_to(HERE)}  ({size:.0f} MB)")
    return kept


def prune_previous() -> None:
    """Keep the newest KEEP_PREVIOUS archives, drop the rest.

    The timestamp in the name sorts chronologically, so sorting by name is
    enough and does not depend on the files' own mtimes surviving a copy.
    """
    if not PREVIOUS.exists():
        return
    archives = sorted(PREVIOUS.glob("Bookkeeper-*.exe"))
    for stale in archives[:-KEEP_PREVIOUS] if KEEP_PREVIOUS else archives:
        stale.unlink()
        print(f"Dropped older build: {stale.name}")


def main() -> int:
    kept = archive_current()
    prune_previous()

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
        # Put the last good exe back, so a failed build does not leave you
        # without a runnable app. It stays in previous/ as well.
        if kept is not None and kept.exists():
            DIST.mkdir(exist_ok=True)
            shutil.copy2(str(kept), str(DIST / EXE_NAME))
            print(f"\nBuild failed - restored {kept.name} to "
                  f"{(DIST / EXE_NAME).relative_to(HERE)}")
        return result.returncode

    built = DIST / EXE_NAME
    if built.exists():
        size = built.stat().st_size / (1024 * 1024)
        print(f"\nBuilt {built}  ({size:.0f} MB)")
    archives = sorted(PREVIOUS.glob("Bookkeeper-*.exe")) if PREVIOUS.exists() else []
    if archives:
        print(f"Previous build{'s' if len(archives) > 1 else ''} kept in "
              f"previous/: {', '.join(a.name for a in archives)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
