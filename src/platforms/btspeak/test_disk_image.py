"""Export to and import from disk images with the real file tool on a real factory state; the worker is a stand-in
(the staged commit itself is test_worker's). No device services."""

import contextlib
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from disk_image import export_image, image_name, import_image
from profiles import Profile

ROOT = Path(__file__).resolve().parents[3]
TOOL = ROOT / "build/linux/blazie_files"
FIRMWARE_DIR = Path(os.environ.get("BLAZIE_TEST_FIRMWARE", str(ROOT / "firmware/blazie"))).resolve()
FACTORY = FIRMWARE_DIR / "bl2_2003_warm.state"


def files_of(state: Path) -> str:
    return subprocess.run([str(TOOL), "list", str(state)], capture_output=True, text=True, check=True).stdout


@unittest.skipUnless(TOOL.exists() and FACTORY.exists(), "Build blazie_files and supply the English factory state")
class DiskImageTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.saved = self.root / "english.state"
        shutil.copyfile(FACTORY, self.saved)
        self.profile = Profile("bl-en", "Braille Lite 2000 (English)", self.root / "fw", FACTORY, self.saved.name)
        self.commits = []

        def request(command, reply):
            if command == "IMPORT_COMMIT":  # what the worker adopts: the staged copy, as the tool left it
                self.commits.append(files_of(Path(str(self.saved) + ".import")))
        self.worker = SimpleNamespace(saved=self.saved, request=Mock(side_effect=request))
        self.dialogs = SimpleNamespace(request_directory=Mock(return_value=self.root), request_file=Mock(),
                                       request_confirmation=Mock(return_value=False), show_message=Mock(),
                                       activity=lambda *a, **k: contextlib.nullcontext())
        self.image = self.root / image_name(self.profile)

    def export(self):
        self.dialogs.show_message.reset_mock()
        export_image(self.worker, self.dialogs, self.profile, TOOL)
        return self.dialogs.show_message.call_args.args[0] if self.dialogs.show_message.called else None

    def image_without(self, name: str) -> Path:
        """The exported image, one of its files taken out and a new one put in."""
        self.export()
        unpacked = self.root / "unpacked"
        subprocess.run([str(TOOL), "unpack", str(self.image), str(unpacked)], capture_output=True, check=True)
        (unpacked / "ram startup" / name).unlink()
        (unpacked / "ram startup" / "letter.txt").write_text("Dear Blazie,\n")
        changed = self.root / "changed.img"
        subprocess.run([str(TOOL), "pack", str(unpacked), str(changed)], capture_output=True, check=True)
        return changed

    def test_export_saves_the_unit_then_writes_every_file_into_the_image(self):
        message = self.export()
        self.assertIn("Exported 3 files to " + str(self.image), message)
        self.worker.request.assert_called_once_with("SAVE", "SAVED")
        self.assertEqual(self.dialogs.request_directory.call_args.args[0], Path("/"))
        listed = subprocess.run([str(TOOL), "unpack", str(self.image), str(self.root / "out")], capture_output=True)
        self.assertEqual(listed.returncode, 0)
        self.assertTrue((self.root / "out" / "ram startup" / "datebook.brl").exists())
        self.assertFalse(Path(str(self.image) + ".new").exists())

    def test_an_image_there_already_is_kept_unless_the_user_says_replace(self):
        self.image.write_bytes(b"someone's image")
        self.assertIsNone(self.export())
        self.assertEqual(self.image.read_bytes(), b"someone's image")
        self.assertFalse(self.dialogs.request_confirmation.call_args.kwargs["default"])
        self.worker.request.assert_not_called()
        self.dialogs.request_confirmation.return_value = True
        self.assertIn("Exported 3 files", self.export())
        self.assertNotEqual(self.image.read_bytes(), b"someone's image")

    def test_no_folder_picker_or_cancelled_changes_nothing(self):
        del self.dialogs.request_directory
        export_image(self.worker, self.dialogs, self.profile, TOOL)
        self.assertIn("no folder picker", self.dialogs.show_message.call_args.args[0])
        self.dialogs.request_directory = Mock(return_value=None)
        export_image(self.worker, self.dialogs, self.profile, TOOL)
        self.worker.request.assert_not_called()
        self.assertEqual(list(self.root.glob("*.img*")), [])

    def test_import_asks_before_deleting_and_declining_imports_nothing(self):
        before = self.saved.read_bytes()
        self.dialogs.request_file.return_value = self.image_without("a")
        self.worker.request.reset_mock()
        import_image(self.worker, self.dialogs, self.profile, TOOL)
        question = self.dialogs.request_confirmation.call_args
        self.assertIn("does not have 1 of the unit's files", question.args[0])
        self.assertIn(": a.", question.args[0])
        self.assertFalse(question.kwargs["default"])
        self.assertEqual([c.args[0] for c in self.worker.request.call_args_list], ["IMPORT_CHECK"])
        self.assertIn("Nothing was imported", self.dialogs.show_message.call_args.args[0])
        self.assertEqual(self.saved.read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.root.glob("english.state*")), ["english.state"])

    def test_import_accepted_commits_the_images_files(self):
        self.dialogs.request_file.return_value = self.image_without("a")
        self.dialogs.request_confirmation.return_value = True
        import_image(self.worker, self.dialogs, self.profile, TOOL)
        self.assertEqual(len(self.commits), 1)
        self.assertIn("letter.txt", self.commits[0])
        self.assertNotIn("startup: a,", self.commits[0])
        message = self.dialogs.show_message.call_args.args[0]
        self.assertIn("1 added", message)
        self.assertIn("1 deleted", message)
        self.assertEqual(sorted(p.name for p in self.root.glob("english.state*")), ["english.state"])

    def test_a_file_that_is_not_an_image_is_refused_before_anything_changes(self):
        not_image = self.root / "notes.img"
        not_image.write_bytes(b"not a disk image" * 64)
        self.dialogs.request_file.return_value = not_image
        import_image(self.worker, self.dialogs, self.profile, TOOL)
        self.assertIn("Import failed: not a FAT disk image", self.dialogs.show_message.call_args.args[0])
        self.assertEqual(self.commits, [])
        self.dialogs.request_confirmation.assert_not_called()
        self.assertEqual(self.dialogs.request_file.call_args.kwargs["extensions"], ["img"])


if __name__ == "__main__":
    unittest.main()
