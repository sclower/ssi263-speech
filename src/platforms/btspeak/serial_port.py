"""The unit's serial port: a serial device on the BT Speak, or a pseudo-terminal for a program on it.

As blazie_emu's own menu and the Windows app's Serial port (serial_linux.h): the worker plugs the unit into the
port and follows the line settings its firmware programs. The choice is kept in preferences.json and used again
whenever a unit starts. A pseudo-terminal's other end changes with each start, so it is also linked as `serial`
beside the saved memory, for a terminal program (picocom, minicom) to open by one name.
"""

import curses
import os
from gettext import gettext as _
from pathlib import Path
from types import ModuleType

from preferences import Preferences
from worker import Worker

PATTERNS = ("/dev/ttyUSB{n}", "/dev/ttyACM{n}", "/dev/ttyS{n}", "/dev/ttyAMA{n}")


def ports() -> list[str]:
    """The serial devices present, as blazie_emu's menu lists them."""
    return [pattern.format(n=n) for pattern in PATTERNS for n in range(8) if os.path.exists(pattern.format(n=n))]


class SerialPort:
    def __init__(self, link: Path) -> None:
        self.link = link
        self.port = "none"  # where the running unit is plugged in: "none", "pty" or a device
        self.other = ""  # a pseudo-terminal's other end

    def label(self) -> str:
        if self.port == "pty":
            return _("pseudo-terminal {path}").format(path=self.other)
        return _("not connected") if self.port == "none" else self.port

    def plug(self, worker: Worker, port: str) -> str | None:
        """Plug a worker's unit into port; None when it is there, else why not (the unit then unplugged)."""
        self.port, self.other = "none", ""
        self.link.unlink(missing_ok=True)
        reply, rest = worker.answer("SERIAL " + port, "SERIAL", "SERIAL_FAILED")
        if reply == "SERIAL_FAILED":
            return rest
        if rest.startswith("pty "):
            self.port, self.other = "pty", rest[4:]
            try:
                self.link.symlink_to(self.other)
            except OSError:
                pass  # the other end's name is still said
        else:
            self.port = rest
        return None


def serial_menu(worker: Worker, dialogs: ModuleType, preferences: Preferences, serial: SerialPort, *,
                stdscr: curses.window | None = None) -> None:
    choices = {"none": _("Not connected"),
               "pty": _("Pseudo-terminal, for a program on this device")}
    choices.update({path: path for path in ports()})
    current = serial.port if serial.port in choices else "none"
    selected = dialogs.request_choice(choices, prompt=_("Serial port"), default=current, stdscr=stdscr)
    if selected is None or (selected.key == serial.port and selected.key != "pty"):
        return
    error = serial.plug(worker, selected.key)
    preferences.store(preferences.quick_keys, serial=serial.port)
    if error:
        dialogs.show_message(_("The serial port is not connected: {error}").format(error=error), stdscr=stdscr)
    elif serial.port == "pty":
        dialogs.show_message(_(
            "The serial port is on a pseudo-terminal. A program on this device, such as picocom,\n"
            "opens its other end: {path}, also {link}. It changes each time the unit starts."
        ).format(path=serial.other, link=serial.link), stdscr=stdscr)
    else:
        dialogs.show_message(_("The serial port is on {port}.").format(port=serial.port), wait=False,
                             wait_for_speech=True, stdscr=stdscr)
