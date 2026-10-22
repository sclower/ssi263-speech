"""The host menu's Firmware choice, as the desktop apps' Firmware menu: the catalog's units, then the language releases
(bl_languages.txt's) under More languages.  Ctrl+C on a unit puts it in the User Menu, as the BT Speak's own menus do
(BTSpeak/user_menu.py: a name asked for, then "name: run ... --unit id"); without that library, Ctrl+C is the dialog's
own."""

import os
from gettext import gettext as _
from pathlib import Path
from types import ModuleType

from bt_runtime import optional_keywords

MORE = "+more"                          # More languages' key: never a unit's (an id has no "+")


def launcher(backend: Path) -> str | None:
    """What a User Menu line runs to start a unit: the .deb's launcher (it says so, in BLAZIE_EMU_LAUNCHER: it finds the
    firmware a user fetched), else the blazie_emu beside this frontend.  None when there is none, or its path has a
    space (a menu's run action splits there)."""
    # absolute, links not followed: the path the installers wrote, which uninstall.sh looks for
    program = os.environ.get("BLAZIE_EMU_LAUNCHER") or os.path.join(os.path.dirname(os.path.abspath(backend)), "blazie_emu")
    if not os.access(program, os.X_OK) or any(char.isspace() for char in program):
        return None
    return program


def _request(dialogs: ModuleType, choices: dict[str, str], prompt: str, default: str, run: str | None,
             stdscr: object) -> str | None:
    native = getattr(dialogs, "native", dialogs)
    try:
        from BTSpeak import user_menu
    except ImportError:
        user_menu = None
    if run is None or user_menu is None or not hasattr(native, "ChoiceDialog") or not hasattr(native, "Choice"):
        selected = dialogs.request_choice(choices, prompt=prompt, default=default, stdscr=stdscr)
        return None if selected is None else selected.key

    class UnitChoice(native.ChoiceDialog):
        def on_Copy(self) -> bool:
            key, label = self.menu_items[self.selection]
            if key == MORE:
                return bool(super().on_Copy())
            user_menu.prompt_and_add(label, "run {program} --unit {key}".format(program=run, key=key),
                                     stdscr=self.window)
            return True

    # an older runtime's dialog takes no stdscr (bt_runtime.Dialogs' own adapting)
    selected = optional_keywords(UnitChoice, "stdscr")(choices, prompt, default, stdscr=stdscr).run()
    return selected.key if isinstance(selected, native.Choice) else None


def choose_unit(dialogs: ModuleType, units: dict[str, str], releases: frozenset[str], current: str, *,
                run: str | None = None, stdscr: object = None) -> str | None:
    """The unit chosen, or None for none (Escape out of the firmware list)."""
    more = {key: label for key, label in units.items() if key in releases}
    choices = {key: label for key, label in units.items() if key not in releases}
    if more:
        choices[MORE] = _("More languages")
    default = MORE if current in more else current
    while True:
        key = _request(dialogs, choices, _("Choose firmware"), default, run, stdscr)
        if key != MORE:
            return key
        key = _request(dialogs, more, _("More languages"), current, run, stdscr)
        if key is not None:
            return key
        default = MORE                  # Escape out of More languages: back to the firmware list, on it
