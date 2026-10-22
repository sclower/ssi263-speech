"""The BT Braille keys that pan its display, as the user set them in Braille Settings, as the advance bars.

BT Speak's Navigation Key Setup (BTSpeak/nav_keys.py) writes Blazie mode's assignments for L1-L3 and R1-R3 into a
key table for BRLTTY; whichever keys pan the display there (FWINLT, FWINRT) are the Braille Lite's back and advance
bars here, so the emulator pans as everything else on the device does. The same tables, in the same order, as the
native route reads them (btkb_linux.c btkb_panning_keys): the user's, then the shipped default; with neither, R2 and
R3, the right-handed layout every BT Braille starts with.
"""

from gettext import gettext as _
from pathlib import Path
from types import ModuleType

ADVANCE = 1  # the worker's BARS bits
BACK = 2

TABLES = (
    Path("/var/lib/BTSpeak/btbraille-nav-keys.kti"),  # the user's (Braille Settings, Navigation Key Setup)
    Path("/etc/xdg/brltty/btbraille-nav-keys.kti"),  # the shipped default
)
NAV_KEYS = ("L1", "L2", "L3", "R1", "R2", "R3")
DEFAULT = {"R2": BACK, "R3": ADVANCE}
COMMANDS = {"FWINLT": BACK, "FWINRT": ADVANCE}


def panning_keys(tables: tuple[Path, ...] | None = None) -> dict[str, int]:
    """Each navigation key that pans, by name ("R3"), and its bar. The first table there is the one BRLTTY reads."""
    for table in TABLES if tables is None else tables:
        try:
            lines = table.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        keys: dict[str, int] = {}
        for line in lines:
            # "bind R2 FWINLT": one key alone, as navigation-key-setup writes; a combination (L1+R1) is not a bar
            words = line.split()
            if len(words) >= 3 and words[0] == "bind" and words[1].upper() in NAV_KEYS:
                bar = COMMANDS.get(words[2].upper())
                if bar:
                    keys[words[1].upper()] = bar
        return keys
    return dict(DEFAULT)


def usable(kb_client: ModuleType, keys: dict[str, int]) -> dict[str, int]:
    """Those of the keys this keyboard reports: the older keypad's bridge (legacy_keyboard.py) has L2, L3, R2, R3 only."""
    return {name: bar for name, bar in keys.items() if hasattr(kb_client, "BTB_" + name)}


def bar_codes(kb_client: ModuleType, keys: dict[str, int]) -> dict[int, int]:
    """The keyboard server's codes for those keys (kb_client.BTB_R3, ...), each with its bar."""
    return {getattr(kb_client, "BTB_" + name): bar for name, bar in usable(kb_client, keys).items()}


def describe(keys: dict[str, int]) -> str:
    """The keyboard help's line for the bars."""
    advance = " or ".join(name for name in NAV_KEYS if keys.get(name) == ADVANCE)
    back = " or ".join(name for name in NAV_KEYS if keys.get(name) == BACK)
    if advance and back:
        return _("On BT Braille, {advance} advances braille; {back} moves it back, as set in Braille Settings.\n").format(
            advance=advance, back=back)
    if advance:
        return _("On BT Braille, {advance} advances braille, as set in Braille Settings. No key moves it back.\n").format(
            advance=advance)
    if back:
        return _("On BT Braille, {back} moves braille back, as set in Braille Settings. No key advances it.\n").format(
            back=back)
    return _("On BT Braille, no navigation key pans the display in Braille Settings, so the advance bars are unused.\n")
