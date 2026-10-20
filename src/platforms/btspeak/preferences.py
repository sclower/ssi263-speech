"""Host preferences, written atomically beside the units' saved memories."""

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from gettext import gettext as _
from pathlib import Path

from audio_options import AudioOptions


@dataclass
class Preferences:
    path: Path
    quick_keys: bool = False
    unit: str = "bl-en"
    audio: AudioOptions = field(default_factory=AudioOptions)
    intro_shown: bool = False
    double_speed: bool = False          # the double-speed upgrade installed (emu_set_double_speed), off as most units
    serial: str = "none"                # the unit's serial port: "none", "pty" or a /dev path (serial_port.py)

    @classmethod
    def load(cls, path: Path) -> "Preferences":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls(path)
        if not isinstance(data, dict) or not isinstance(data.get("quick_keys", False), bool):
            raise ValueError(_("Invalid emulator preferences."))
        if not isinstance(data.get("intro_shown", False), bool) or not isinstance(data.get("double_speed", False), bool):
            raise ValueError(_("Invalid emulator preferences."))
        unit = data.get("unit", "bl-en")
        if not isinstance(unit, str) or not unit or len(unit) > 80 or any(
            not (char.isascii() and (char.isalnum() or char in "_-")) for char in unit
        ):
            raise ValueError(_("Invalid emulator firmware preference."))
        serial = data.get("serial", "none")
        if not isinstance(serial, str) or not (serial in ("none", "pty") or (
            serial.startswith("/dev/") and len(serial) < 100 and serial.isascii() and not any(c.isspace() for c in serial)
        )):
            raise ValueError(_("Invalid emulator serial port preference."))
        return cls(path, data.get("quick_keys", False), unit, AudioOptions.load(data.get("audio", {})),
                   data.get("intro_shown", False), data.get("double_speed", False), serial)

    def store(self, quick_keys: bool, *, unit: str | None = None, audio: AudioOptions | None = None,
              intro_shown: bool | None = None, double_speed: bool | None = None, serial: str | None = None) -> None:
        selected = self.unit if unit is None else unit
        sound = self.audio if audio is None else audio
        introduced = self.intro_shown if intro_shown is None else intro_shown
        doubled = self.double_speed if double_speed is None else double_speed
        port = self.serial if serial is None else serial
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                         prefix=self.path.name + ".", delete=False) as stream:
            tmp = Path(stream.name)
            try:
                json.dump({"quick_keys": quick_keys, "unit": selected, "audio": asdict(sound),
                           "intro_shown": introduced, "double_speed": doubled, "serial": port}, stream)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
                os.replace(tmp, self.path)
            finally:
                tmp.unlink(missing_ok=True)
        self.quick_keys = quick_keys
        self.unit = selected
        self.audio = sound
        self.intro_shown = introduced
        self.double_speed = doubled
        self.serial = port
