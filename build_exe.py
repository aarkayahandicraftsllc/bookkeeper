"""Packages the desktop app into a single Windows executable.

    python build_exe.py

Produces dist/Bookkeeper.exe — copy it anywhere and double-click. Python does not
need to be installed on the machine that runs it.

The books live in a data folder NEXT TO THE EXECUTABLE, so keep the two
together, or point BOOKS_DIR somewhere else (OneDrive, a shared folder).

That is why dist/ is no longer wiped before a build: dist/data holds real
books. Only build/ is cleared.

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

    Safe to do while the app is open: Windows permits renaming a running
    executable, and the open copy keeps running from its file handle. It
    cannot be DELETED until that process exits, which is why prune_previous()
    tolerates a refusal.
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

    A failure here must never stop the build. An archive the user is still
    RUNNING cannot be deleted on Windows - the app they launched from dist/ is
    this very file, moved - and an unhandled PermissionError here once wiped
    dist/ and left them with no executable at all. Skip it and say so; it will
    be prunable next time.
    """
    if not PREVIOUS.exists():
        return
    archives = sorted(PREVIOUS.glob("Bookkeeper-*.exe"))
    for stale in archives[:-KEEP_PREVIOUS] if KEEP_PREVIOUS else archives:
        try:
            stale.unlink()
            print(f"Dropped older build: {stale.name}")
        except OSError as error:
            print(f"Could not drop {stale.name} ({error.strerror or error}) - "
                  f"it is probably still running. Left in place.")


def main() -> int:
    # Keeping the old build is a convenience; failing to keep it must not cost
    # you the new one. Anything unexpected here is reported and stepped over.
    kept = None
    try:
        kept = archive_current()
        prune_previous()
    except OSError as error:
        print(f"Could not archive the previous build ({error}) - "
              f"continuing with the build.")

    # build/ only. dist/ is NOT wiped any more: the packaged app keeps its
    # books in dist/data, next to the executable, and wiping dist/ would delete
    # them on every rebuild. PyInstaller overwrites the exe by itself, and
    # archive_current() has already moved the old one aside.
    shutil.rmtree(HERE / "build", ignore_errors=True)

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
