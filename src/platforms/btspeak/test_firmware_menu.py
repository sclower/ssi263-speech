"""The host menu's Firmware choice: the desktop apps' split (More languages) and Ctrl+C to the User Menu."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

from firmware_menu import MORE, choose_unit, launcher
from frontend import host_menu
from preferences import Preferences

UNITS = {"bl-en": "Braille Lite 2000 (English)", "tns-en": "Type 'n Speak (English)",
         "bl2_cs_1999_07": "Braille Lite 2000 (Czech)", "bl2_ko": "Braille Lite 2000 (Korean)"}
RELEASES = frozenset({"bl2_cs_1999_07", "bl2_ko"})


def answers(*keys):
    """A request_choice giving these keys in turn (None: Escape), and the menus it was shown."""
    shown = []

    def choice(choices, prompt, default, stdscr=None):
        shown.append((prompt, dict(choices), default))
        key = keys[len(shown) - 1]
        return None if key is None else SimpleNamespace(key=key)
    return choice, shown


class FirmwareMenuTests(unittest.TestCase):
    def test_catalog_units_then_more_languages_with_the_releases(self):
        choice, shown = answers(MORE, "bl2_ko")
        self.assertEqual(choose_unit(SimpleNamespace(request_choice=choice), UNITS, RELEASES, "bl-en"), "bl2_ko")
        self.assertEqual(shown[0], ("Choose firmware", {"bl-en": UNITS["bl-en"], "tns-en": UNITS["tns-en"],
                                                        MORE: "More languages"}, "bl-en"))
        self.assertEqual(shown[1], ("More languages", {"bl2_cs_1999_07": UNITS["bl2_cs_1999_07"],
                                                       "bl2_ko": UNITS["bl2_ko"]}, "bl-en"))

    def test_escape_from_more_languages_returns_to_the_list_on_it(self):
        choice, shown = answers(MORE, None, None)
        self.assertIsNone(choose_unit(SimpleNamespace(request_choice=choice), UNITS, RELEASES, "bl-en"))
        self.assertEqual([(prompt, default) for prompt, _choices, default in shown],
                         [("Choose firmware", "bl-en"), ("More languages", "bl-en"), ("Choose firmware", MORE)])

    def test_a_release_running_opens_on_more_languages_and_no_releases_no_more(self):
        choice, shown = answers(None)
        choose_unit(SimpleNamespace(request_choice=choice), UNITS, RELEASES, "bl2_cs_1999_07")
        self.assertEqual(shown[0][2], MORE)
        choice, shown = answers("tns-en")
        catalog = {key: UNITS[key] for key in ("bl-en", "tns-en")}
        self.assertEqual(choose_unit(SimpleNamespace(request_choice=choice), catalog, frozenset(), "bl-en"), "tns-en")
        self.assertNotIn(MORE, shown[0][1])

    def test_host_menu_firmware_switches_to_a_release(self):
        choice, _shown = answers("f", MORE, "bl2_ko")
        prefs = Preferences(Path("unused"))
        self.assertEqual(host_menu(Mock(), SimpleNamespace(request_choice=choice), prefs, UNITS, releases=RELEASES),
                         "unit:bl2_ko")

    def test_ctrl_c_copies_a_unit_to_the_user_menu_and_more_languages_keeps_its_own(self):
        copied = []
        user_menu = ModuleType("BTSpeak.user_menu")
        user_menu.prompt_and_add = lambda label, action, stdscr=None: copied.append((label, action))
        package = ModuleType("BTSpeak")
        package.user_menu = user_menu

        class Choice(SimpleNamespace):
            pass

        class ChoiceDialog:
            clipboard = 0

            def __init__(self, choices, label, default, stdscr=None):
                self.menu_items = list(choices.items())
                self.selection = [key for key, _label in self.menu_items].index(default)
                self.window = stdscr

            def on_Copy(self):
                ChoiceDialog.clipboard += 1
                return True

            def run(self):
                self.on_Copy()                      # Ctrl+C on the row it opened on, then Enter there
                key, label = self.menu_items[self.selection]
                return Choice(key=key, label=label)

        native = SimpleNamespace(ChoiceDialog=ChoiceDialog, Choice=Choice)
        dialogs = SimpleNamespace(native=native, request_choice=Mock())
        with patch.dict(sys.modules, {"BTSpeak": package, "BTSpeak.user_menu": user_menu}):
            self.assertEqual(choose_unit(dialogs, UNITS, RELEASES, "tns-en", run="/x/blazie_emu"), "tns-en")
            self.assertEqual(copied, [("Type 'n Speak (English)", "run /x/blazie_emu --unit tns-en")])
            # a release running: the list opens on More languages, whose Ctrl+C is the dialog's own; then the release
            self.assertEqual(choose_unit(dialogs, UNITS, RELEASES, "bl2_ko", run="/x/blazie_emu"), "bl2_ko")
            self.assertEqual(ChoiceDialog.clipboard, 1)
            self.assertEqual(copied[1], ("Braille Lite 2000 (Korean)", "run /x/blazie_emu --unit bl2_ko"))
            # nothing to run: no copying, the platform's own request_choice
            dialogs.request_choice.return_value = SimpleNamespace(key="bl-en")
            self.assertEqual(choose_unit(dialogs, UNITS, RELEASES, "tns-en"), "bl-en")
            self.assertEqual(len(copied), 2)
        dialogs.request_choice.reset_mock()
        with patch.dict(sys.modules, {"BTSpeak": None}):     # no User Menu library: the platform's own
            choose_unit(dialogs, UNITS, RELEASES, "tns-en", run="/x/blazie_emu")
            dialogs.request_choice.assert_called_once()

    def test_an_older_runtime_whose_dialog_takes_no_screen_still_copies(self):
        copied = []
        user_menu = ModuleType("BTSpeak.user_menu")
        user_menu.prompt_and_add = lambda label, action, stdscr=None: copied.append(action)
        package = ModuleType("BTSpeak")
        package.user_menu = user_menu

        class ChoiceDialog:
            def __init__(self, choices, label, default):        # no stdscr: an older runtime's
                self.menu_items = list(choices.items())
                self.selection = 0
                self.window = None

            def run(self):
                self.on_Copy()
                return SimpleNamespace(key=self.menu_items[0][0])

        native = SimpleNamespace(ChoiceDialog=ChoiceDialog, Choice=SimpleNamespace)
        with patch.dict(sys.modules, {"BTSpeak": package, "BTSpeak.user_menu": user_menu}):
            key = choose_unit(SimpleNamespace(native=native), UNITS, RELEASES, "bl-en", run="/x/blazie_emu",
                              stdscr=object())
        self.assertEqual((key, copied), ("bl-en", ["run /x/blazie_emu --unit bl-en"]))

    def test_launcher_is_the_debs_else_blazie_emu_beside_and_never_one_with_a_space(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "blazie_bt").touch()
            with patch.dict(os.environ, {"BLAZIE_EMU_LAUNCHER": ""}):
                self.assertIsNone(launcher(root / "blazie_bt"))
                (root / "blazie_emu").touch(mode=0o755)
                self.assertEqual(launcher(root / "blazie_bt"), str(root / "blazie_emu"))
                # by its own path, never a link's target: what install.sh wrote and uninstall.sh looks for
                (root / "linked").symlink_to(root)
                self.assertEqual(launcher(root / "linked" / "blazie_bt"), str(root / "linked" / "blazie_emu"))
            with patch.dict(os.environ, {"BLAZIE_EMU_LAUNCHER": str(root / "blazie_emu")}):
                self.assertEqual(launcher(root / "elsewhere"), str(root / "blazie_emu"))
            spaced = root / "a b"
            spaced.mkdir()
            (spaced / "blazie_emu").touch(mode=0o755)
            with patch.dict(os.environ, {"BLAZIE_EMU_LAUNCHER": ""}):
                self.assertIsNone(launcher(spaced / "blazie_bt"))


if __name__ == "__main__":
    unittest.main()
