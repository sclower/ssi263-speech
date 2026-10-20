"""The unit's files to and from a FAT disk image, as the Windows and desktop apps' Firmware menu does.

Export writes every file the unit holds into an image (7-Zip opens it; Linux mounts it). Import makes the unit's
files what an image holds -- blazie_files import, the same transaction as the other emulators -- through the staged
copy the file import uses, so the worker keeps its lock and adopts the result only once it has checked it.
"""

import curses
import os
import re
import subprocess
from contextlib import ExitStack
from gettext import gettext as _
from pathlib import Path
from types import ModuleType

from file_import import staged
from profiles import Profile
from worker import Worker, WorkerError


def run_tool(executable: Path, command: str, state: Path, image: Path, codepage: int, *,
             dry_run: bool = False) -> subprocess.CompletedProcess:
    args = [str(executable), command, str(state), str(image.resolve()), "--codepage={value}".format(value=codepage)]
    if dry_run:
        args.append("--dry-run")
    return subprocess.run(args, capture_output=True, text=True, errors="replace", timeout=60)


def failure(result: subprocess.CompletedProcess, default: str) -> WorkerError:
    """The tool's reason, its last line ("import failed: not a FAT disk image"), without its own prefix."""
    lines = result.stdout.strip().splitlines() or result.stderr.strip().splitlines()
    reason = lines[-1] if lines else default
    return WorkerError(reason.removeprefix("import failed: ").removeprefix("export failed: "))


def image_name(profile: Profile) -> str:
    """The Windows app's suggested name: "Braille Lite 2000 (English) files.img"."""
    return "{label} files.img".format(label=profile.label.replace("/", "-"))


def export_image(worker: Worker, dialogs: ModuleType, profile: Profile, executable: Path, *,
                 stdscr: curses.window | None = None) -> None:
    """Every file the unit holds, as it holds them now, into an image in a folder the user chooses."""
    if not callable(getattr(dialogs, "request_directory", None)):
        dialogs.show_message(_("This version of BT software has no folder picker. Update it to export files."),
                             stdscr=stdscr)
        return
    if not executable.is_file():
        dialogs.show_message(_("The file tool is missing. Rebuild or reinstall the emulator."), stdscr=stdscr)
        return
    folder = dialogs.request_directory(Path("/"), initial_dir=Path.home(),
                                       prompt=_("Choose a folder for the disk image"), stdscr=stdscr)
    if folder is None:
        return
    target = Path(folder) / image_name(profile)
    if target.exists() and not dialogs.request_confirmation(
            _("{name} is there already. Replace it?").format(name=target.name), default=False, stdscr=stdscr):
        return
    partial = target.with_name(target.name + ".new")
    try:
        with dialogs.activity(_("Exporting files"), stdscr=stdscr):
            worker.request("SAVE", "SAVED")  # its memory as it is this moment; a paused worker writes no more
            partial.unlink(missing_ok=True)
            result = run_tool(executable, "export", worker.saved, partial, profile.codepage)
            if result.returncode:
                raise failure(result, _("The files could not be exported."))
            os.replace(partial, target)
        found = re.search(r"Exported (\d+) files", result.stdout)
        dialogs.show_message(_(
            "Exported {count} files to {path}.\n"
            "Each of the unit's folders is a folder in the image. Text files keep the unit's line ends."
        ).format(count=found.group(1) if found else 0, path=target), stdscr=stdscr)
    except (OSError, subprocess.SubprocessError, WorkerError) as exc:
        dialogs.show_message(_("Export failed: {error}").format(error=exc), stdscr=stdscr)
    finally:
        partial.unlink(missing_ok=True)


def import_image(worker: Worker, dialogs: ModuleType, profile: Profile, executable: Path, *,
                 stdscr: curses.window | None = None) -> None:
    """The unit's files made what an image holds; asks before deleting the files the image does not have."""
    if not callable(getattr(dialogs, "request_file", None)):
        dialogs.show_message(_("This version of BT software has no file picker. Update it to import files."),
                             stdscr=stdscr)
        return
    if not executable.is_file():
        dialogs.show_message(_("The file tool is missing. Rebuild or reinstall the emulator."), stdscr=stdscr)
        return
    image = dialogs.request_file(Path("/"), extensions=["img"], initial_dir=Path.home(),
                                 prompt=_("Choose a disk image to import"), stdscr=stdscr)
    if image is None:
        return
    image = Path(image)
    try:
        with ExitStack() as stack:
            with dialogs.activity(_("Checking the disk image"), stdscr=stdscr):
                stage = stack.enter_context(staged(worker))
                result = run_tool(executable, "import", stage, image, profile.codepage, dry_run=True)
                if result.returncode:
                    raise failure(result, _("The disk image could not be read."))
            deleted = [line[8:] for line in result.stdout.splitlines() if line.startswith("deleted ")]
            if deleted and not dialogs.request_confirmation(_(
                "The image does not have {count} of the unit's files. Importing it deletes them from the unit: "
                "{names}. Delete them and import?"
            ).format(count=len(deleted), names=", ".join(deleted)), default=False, stdscr=stdscr):
                dialogs.show_message(_("Nothing was imported. The unit's files are as they were."), stdscr=stdscr)
                return
            with dialogs.activity(_("Importing files"), stdscr=stdscr):
                result = run_tool(executable, "import", stage, image, profile.codepage)
                if result.returncode:
                    raise failure(result, _("The files could not be imported."))
                worker.request("IMPORT_COMMIT", "IMPORTED")
        lines = result.stdout.strip().splitlines()
        warnings = [line for line in lines if line.startswith(("kept ", "skipped "))]
        dialogs.show_message(_(
            "Imported from {name}: {summary}.\n{warnings}The unit has restarted; its previous memory is backed up."
        ).format(name=image.name, summary=lines[-1] if lines else "", warnings="".join(w + "\n" for w in warnings)),
            stdscr=stdscr)
    except (OSError, subprocess.SubprocessError, WorkerError) as exc:
        dialogs.show_message(_("Import failed: {error}").format(error=exc), stdscr=stdscr)
