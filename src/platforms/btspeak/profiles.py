"""Read the same native firmware catalog used by the desktop and terminal shells."""

import json
import subprocess
from dataclasses import dataclass
from gettext import gettext as _
from pathlib import Path

from worker import WorkerError


@dataclass(frozen=True)
class Profile:
    key: str
    label: str
    firmware: Path
    factory: Path | None
    saved: str
    kind: str = "bl"
    codepage: int = 850
    release: bool = False               # a language release (bl_languages.txt's): the Firmware choice's More languages

    def paths(self, firmware_dir: Path, state_dir: Path) -> tuple[Path, Path | None, Path]:
        return self.firmware, self.factory, state_dir / self.saved

    def available(self, firmware_dir: Path, state_dir: Path) -> bool:
        return self.firmware.is_file() and (
            self.factory is None or self.factory.is_file() or (state_dir / self.saved).is_file()
        )


def discover(executable: Path, firmware_dir: Path) -> dict[str, Profile]:
    """Catalog inspection does not open audio, create states, or take the keyboard."""
    try:
        result = subprocess.run([str(executable.resolve()), "--catalog", str(firmware_dir.resolve())],
                                capture_output=True, text=True, check=True, timeout=30)
        profiles = {}
        for row in json.loads(result.stdout):
            profile = Profile(row["key"], _(row["label"]), Path(row["firmware"]),
                              Path(row["factory"]) if row["factory"] else None,
                              row["saved"], row["kind"], row["codepage"], bool(row.get("release", False)))
            if Path(profile.saved).name != profile.saved or profile.kind not in ("bl", "bns", "tns"):
                raise ValueError("Invalid catalog entry")
            profiles[profile.key] = profile
        return profiles
    except (subprocess.SubprocessError, ValueError, KeyError, TypeError) as exc:
        raise WorkerError(_("Could not read the firmware catalog. Rebuild the emulator and try again.")) from exc
