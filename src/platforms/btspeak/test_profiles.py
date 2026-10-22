"""Model discovery and preferences without external firmware or device access."""

import json
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from pathlib import Path

from preferences import Preferences
from profiles import discover

ROOT = Path(__file__).resolve().parents[3]
EXE = ROOT / "build/linux/blazie_bt"
from tns_keyboard import CELLS, key_name


class ProfileTests(unittest.TestCase):
    def test_all_existing_models_and_isolated_states(self):
        if not EXE.exists():
            self.skipTest("Build the worker")
        BY_KEY = discover(EXE, Path("/nonexistent-blazie-firmware"))
        PROFILES = tuple(BY_KEY.values())
        self.assertEqual(set(BY_KEY), {"bl-en", "bl-es", "tns-en", "tns-es", "bns-en", "bns-sk", "bl-de", "bl-it"})
        self.assertEqual(len({p.saved for p in PROFILES}), 8)
        self.assertFalse(any(p.release for p in PROFILES))      # the catalog's own: never under More languages
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            PROFILES = tuple(discover(EXE, root).values())
            for profile in PROFILES:
                self.assertFalse(profile.available(root, root))
                firmware = profile.firmware
                firmware.parent.mkdir(parents=True, exist_ok=True)
                firmware.touch()
                if profile.factory:
                    self.assertFalse(profile.available(root, root))
                    factory = profile.factory
                    factory.parent.mkdir(parents=True, exist_ok=True)
                    factory.touch()
                self.assertTrue(profile.available(root, root))
                self.assertEqual(profile.paths(root, root)[0], firmware)

    @unittest.skipUnless(EXE.exists(), "Build the worker")
    def test_flat_layout_and_existing_state_without_factory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "BL2SPA.BNS").touch()
            (root / "spanish.state").touch()
            BY_KEY = discover(EXE, root)
            self.assertTrue(BY_KEY["bl-es"].available(root, root))
            self.assertEqual(BY_KEY["bl-es"].paths(root, root)[0], root / "BL2SPA.BNS")

    def test_old_preferences_and_unit_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "preferences.json"
            path.write_text('{"quick_keys": true}')
            prefs = Preferences.load(path)
            self.assertEqual(prefs.unit, "bl-en")
            prefs.store(True, unit="tns-es")
            self.assertEqual(Preferences.load(path).unit, "tns-es")
            prefs.store(False)
            self.assertEqual(Preferences.load(path).unit, "tns-es")
            for invalid in ("yes", 1, None, []):
                path.write_text(json.dumps({"intro_shown": invalid}))
                with self.assertRaises(ValueError):
                    Preferences.load(path)
            path.write_text('{"unit": []}')
            with self.assertRaises(ValueError):
                Preferences.load(path)

    def test_new_catalog_release_and_preference_survive_relaunch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / 'renamed firmware.BNS'
            image.touch()
            row = dict(key='bl2_hu_1999_07', label='Braille Lite 2000 (Hungarian)', firmware=str(image),
                       factory='', saved='bl2_hu_1999_07.state', kind='bl', codepage=850, release=True)
            with patch('profiles.subprocess.run', return_value=SimpleNamespace(stdout=json.dumps([row]))):
                profiles = discover(EXE, root)
            profile = profiles[row['key']]
            self.assertTrue(profile.available(root, root))
            self.assertIsNone(profile.factory)
            self.assertTrue(profile.release)
            prefs = Preferences(root / 'preferences.json')
            prefs.store(True, unit=profile.key)
            self.assertEqual(Preferences.load(prefs.path).unit, profile.key)
            self.assertEqual(profile.paths(root, root)[2], root / row['saved'])

    def test_tns_adapter_letters_and_controls(self):
        self.assertEqual(len(CELLS), 64)
        for char in "abcdefghijklmnopqrstuvwxyz":
            self.assertEqual(key_name(CELLS.index(char.upper())), char)
        for chord, expected in ((0x51, "enter"), (0x43, "backspace"), (0x4A, "tab"),
                                (0x64, "esc"), (0x40, "space"), (0x55, "ctrl-o"), (0x41, "up")):
            self.assertEqual(key_name(chord), expected)
        self.assertIsNone(key_name(0))


if __name__ == "__main__":
    unittest.main()
