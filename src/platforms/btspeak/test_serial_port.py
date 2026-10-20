"""The serial port's menu, its link to a pseudo-terminal and its preference, with a stand-in worker; the worker's own
port is test_worker's."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from preferences import Preferences
from serial_port import SerialPort, serial_menu


class SerialPortTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.serial = SerialPort(self.root / "serial")
        self.preferences = Preferences(self.root / "preferences.json")
        self.dialogs = SimpleNamespace(request_choice=Mock(), show_message=Mock())

    def worker(self, *replies):
        return SimpleNamespace(answer=Mock(side_effect=list(replies)))

    def test_a_pseudo_terminal_is_linked_beside_the_memory_and_the_link_follows_the_port(self):
        self.assertEqual(self.serial.plug(self.worker(("SERIAL", "pty /dev/pts/7")), "pty"), None)
        self.assertEqual((self.serial.port, self.serial.other), ("pty", "/dev/pts/7"))
        self.assertEqual(Path(self.serial.link).readlink(), Path("/dev/pts/7"))
        self.assertIn("/dev/pts/7", self.serial.label())
        self.assertIsNone(self.serial.plug(self.worker(("SERIAL", "/dev/ttyUSB0")), "/dev/ttyUSB0"))
        self.assertEqual(self.serial.label(), "/dev/ttyUSB0")
        self.assertFalse(self.serial.link.is_symlink())
        self.assertEqual(self.serial.plug(self.worker(("SERIAL_FAILED", "could not open /dev/ttyUSB0")), "/dev/ttyUSB0"),
                         "could not open /dev/ttyUSB0")
        self.assertEqual(self.serial.label(), "not connected")

    def test_menu_lists_the_ports_present_and_keeps_the_choice(self):
        self.dialogs.request_choice.return_value = SimpleNamespace(key="/dev/ttyUSB0")
        worker = self.worker(("SERIAL", "/dev/ttyUSB0"))
        with patch("serial_port.ports", return_value=["/dev/ttyUSB0", "/dev/ttyACM0"]):
            serial_menu(worker, self.dialogs, self.preferences, self.serial)
        offered = self.dialogs.request_choice.call_args.args[0]
        self.assertEqual(list(offered), ["none", "pty", "/dev/ttyUSB0", "/dev/ttyACM0"])
        self.assertEqual(self.dialogs.request_choice.call_args.kwargs["default"], "none")
        worker.answer.assert_called_once_with("SERIAL /dev/ttyUSB0", "SERIAL", "SERIAL_FAILED")
        self.assertEqual(Preferences.load(self.preferences.path).serial, "/dev/ttyUSB0")

    def test_a_port_that_will_not_open_is_said_and_not_kept(self):
        self.preferences.store(False, serial="pty")
        self.dialogs.request_choice.return_value = SimpleNamespace(key="/dev/ttyUSB0")
        with patch("serial_port.ports", return_value=["/dev/ttyUSB0"]):
            serial_menu(self.worker(("SERIAL_FAILED", "Permission denied")), self.dialogs, self.preferences, self.serial)
        self.assertIn("Permission denied", self.dialogs.show_message.call_args.args[0])
        self.assertEqual(Preferences.load(self.preferences.path).serial, "none")

    def test_cancelling_changes_nothing(self):
        self.dialogs.request_choice.return_value = None
        worker = self.worker()
        serial_menu(worker, self.dialogs, self.preferences, self.serial)
        worker.answer.assert_not_called()
        self.assertFalse(self.preferences.path.exists())

    def test_preference_round_trips_and_old_files_are_unplugged(self):
        path = self.preferences.path
        path.write_text('{"quick_keys": true}')
        self.assertEqual(Preferences.load(path).serial, "none")
        for port in ("pty", "/dev/ttyACM0"):
            Preferences.load(path).store(True, serial=port)
            self.assertEqual(Preferences.load(path).serial, port)
            Preferences.load(path).store(False, unit="bl-es")             # other changes keep it
            self.assertEqual(Preferences.load(path).serial, port)
        for bad in ('"COM1"', '"/dev/tty USB0"', '7', '"../etc/passwd"'):
            path.write_text('{"serial": %s}' % bad)
            with self.assertRaises(ValueError):
                Preferences.load(path)


if __name__ == "__main__":
    unittest.main()
