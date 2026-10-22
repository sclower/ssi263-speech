"""Native BT file selection and the upstream file tool's transactional batch import."""

import curses
import shutil
import subprocess
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from gettext import gettext as _
from pathlib import Path
from types import ModuleType

from profiles import Profile
from worker import Worker, WorkerError


MAX_FILES = 64


def select_files(dialogs: ModuleType, *, stdscr: curses.window | None = None) -> list[Path]:
    selected: list[Path] = []
    directory = Path.home()
    browse = True
    while True:
        if browse:
            # Start at home, but allow going up to /media and /mnt for removable storage.
            path = dialogs.request_file(Path("/"), initial_dir=directory, prompt=_("Choose a program or file to import"),
                                        stdscr=stdscr)
            if path is not None:
                path = Path(path).resolve()
                directory = path.parent
                if path not in selected:
                    selected.append(path)
            elif not selected:
                return []
        choices = {"i": _("Import {count} selected files").format(count=len(selected)),
                   "a": _("Add another file"), "r": _("Remove a selected file"), "x": _("Cancel import")}
        if len(selected) >= MAX_FILES:
            del choices["a"]
        choice = dialogs.request_choice(choices, prompt=_("Selected: {names}").format(
            names=", ".join(path.name for path in selected)), default="i", stdscr=stdscr)
        if choice is None or choice.key == "x":
            return []
        if choice.key == "i":
            return selected
        browse = choice.key == "a"
        if choice.key == "r":
            remove = dialogs.request_choice({str(i): str(path) for i, path in enumerate(selected, 1)},
                                             prompt=_("Remove which file"), stdscr=stdscr)
            if remove:
                selected.pop(int(remove.key) - 1)
            browse = not selected


@contextmanager
def staged(worker: Worker) -> Iterator[Path]:
    """A copy of the paused unit's memory, and its updated firmware bank, for blazie_files to edit while the worker
    keeps its lock; IMPORT_COMMIT adopts it. Removed afterwards, whether it was adopted or not."""
    stage = Path(str(worker.saved) + ".import")
    try:
        worker.request("IMPORT_CHECK", "SAVED")
        shutil.copyfile(worker.saved, stage)
        program = Path(str(worker.saved) + ".program")
        staged_program = Path(str(stage) + ".program")
        staged_program.unlink(missing_ok=True)
        if program.exists():
            shutil.copyfile(program, staged_program)
        yield stage
    finally:
        for suffix in ("", ".program", ".before-import", ".tmp"):
            Path(str(stage) + suffix).unlink(missing_ok=True)


def run_tool(executable: Path, stage: Path, paths: list[Path], codepage: int, *,
             dry_run: bool = False, replace: bool = False) -> subprocess.CompletedProcess:
    args = [str(executable), "add", str(stage), "--codepage={value}".format(value=codepage)]
    if dry_run:
        args.append("--dry-run")
    if replace:
        args.append("--replace")
    # Absolute paths cannot be mistaken for the file tool's options. No shell is involved.
    args.extend(str(path.resolve()) for path in paths)
    return subprocess.run(args, capture_output=True, text=True, errors="replace", timeout=60)


def import_files(worker: Worker, dialogs: ModuleType, profile: Profile, executable: Path, *,
                 stdscr: curses.window | None = None) -> None:
    """Keep the worker paused and locked throughout; only commit a fully validated staged state."""
    if not callable(getattr(dialogs, "request_file", None)):
        dialogs.show_message(_("This version of BT software has no file picker. Update it to use file importing."), stdscr=stdscr)
        return
    if not executable.is_file():
        dialogs.show_message(_("The file import tool is missing. Rebuild or reinstall the emulator."), stdscr=stdscr)
        return
    paths = select_files(dialogs, stdscr=stdscr)
    if not paths:
        return
    try:
        with ExitStack() as stack:
            with dialogs.activity(_("Checking the selected files"), stdscr=stdscr):
                stage = stack.enter_context(staged(worker))
                result = run_tool(executable, stage, paths, profile.codepage, dry_run=True)
            replace = False
            if result.returncode:
                existing = [line[7:] for line in result.stdout.splitlines() if line.startswith("exists ")]
                if not existing:
                    raise WorkerError(result.stdout.strip() or result.stderr.strip() or _("The files could not be imported."))
                replace = dialogs.request_confirmation(_("Replace existing files: {names}").format(names=", ".join(existing)),
                                                       default=False, stdscr=stdscr)
                if not replace:
                    return
            with dialogs.activity(_("Importing files"), stdscr=stdscr):
                result = run_tool(executable, stage, paths, profile.codepage, replace=replace)
                if result.returncode:
                    raise WorkerError(result.stdout.strip() or result.stderr.strip() or _("The files could not be imported."))
                worker.request("IMPORT_COMMIT", "IMPORTED")
        dialogs.show_message(_("Imported {count} files. The unit has restarted; its previous memory is backed up.").format(
            count=len(paths)), wait=False, wait_for_speech=True, stdscr=stdscr)
    except (OSError, subprocess.SubprocessError, WorkerError) as exc:
        dialogs.show_message(_("Import failed: {error}").format(error=exc), stdscr=stdscr)
