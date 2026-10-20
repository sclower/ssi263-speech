"""Real native worker, isolated saved states and silent pacing. Never takes the device keyboard."""

import signal
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from worker import Worker, WorkerError

ROOT = Path(__file__).resolve().parents[3]
EXE = ROOT / "build/linux/blazie_bt"
FIRMWARE_DIR = Path(os.environ.get("BLAZIE_TEST_FIRMWARE", str(ROOT / "firmware/blazie"))).resolve()
FIRMWARE = FIRMWARE_DIR / "BL2ENG.BNS"
FACTORY = FIRMWARE_DIR / "bl2_2003_warm.state"

# A stand-in backend with the real worker's replies: its queue-full warnings for KEY and BARS, its Type 'n Speak
# queue-full answer to TNS, and a failed save. Needs no build and no firmware.
STUB = """import sys
print("READY", flush=True)
for line in sys.stdin:
    word = line.split()[0]
    if word == "KEY":
        print("ERROR Keyboard queue full; the last chord was not entered.", flush=True)
    elif word == "BARS":
        print("ERROR Braille bar queue full.", flush=True)
    elif word == "TNS":
        print("ERROR Type 'n Speak keyboard queue full.", flush=True)
    elif word == "SAVE":
        print("ERROR Could not save the unit's memory.", flush=True)
    elif word == "QUIT":
        print("BYE", flush=True)
        break
    else:
        print("OK", flush=True)
"""


class TransientWarningTests(unittest.TestCase):
    def test_queue_full_warnings_do_not_end_the_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            stub = Path(tmp) / "blazie_bt"
            stub.write_text("#!" + sys.executable + "\n" + STUB)
            stub.chmod(0o755)
            worker = Worker(stub, Path(tmp) / "fw", None, Path(tmp) / "saved")
            self.addCleanup(worker.abort)
            with self.assertLogs("worker", "WARNING") as logged:
                worker.send("KEY 0 1")
                worker.send("BARS 1")
                worker.request("QUICK 1", "OK")  # Both warnings arrive before this OK; the session goes on.
            self.assertEqual(len(logged.records), 2)
            self.assertIn("Keyboard queue full", logged.output[0])
            self.assertIn("Braille bar queue full", logged.output[1])
            # Every other error still ends it: the Type 'n Speak's answer to its request, and a failed save.
            with self.assertRaisesRegex(WorkerError, "Type 'n Speak keyboard queue full"):
                worker.request("TNS a", "OK")
            with self.assertRaisesRegex(WorkerError, "save"):
                worker.request("SAVE", "SAVED")
            worker.close()


@unittest.skipUnless(EXE.exists() and FIRMWARE.exists() and FACTORY.exists(), "Build the worker and supply firmware")
class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.saved = Path(self.tmp.name) / "english.state"

    def start(self):
        worker = Worker(EXE, FIRMWARE, FACTORY, self.saved, "-")
        self.addCleanup(worker.abort)
        return worker

    def test_import_commits_staged_files_keeps_backup_and_lock(self):
        import shutil
        worker = self.start()
        worker.request("IMPORT_CHECK", "SAVED")
        before = self.saved.read_bytes()
        stage = Path(str(self.saved) + ".import")
        shutil.copyfile(self.saved, stage)
        program = Path(self.tmp.name) / "sample.bns"
        document = Path(self.tmp.name) / "story.txt"
        program.write_bytes(b"program\x00\x01\x02\xff")
        document.write_bytes(b"first line\nsecond line\n")
        tool = EXE.with_name("blazie_files")
        subprocess.run([str(tool), "add", str(stage), str(program), str(document)], check=True, capture_output=True)
        with self.assertRaisesRegex(WorkerError, "busy"):
            self.start()
        worker.request("IMPORT_COMMIT", "IMPORTED")
        self.assertEqual(Path(str(self.saved) + ".before-import").read_bytes(), before)
        self.assertNotEqual(self.saved.read_bytes(), before)
        listing = subprocess.run([str(tool), "list", str(self.saved)], check=True, capture_output=True, text=True).stdout
        self.assertIn("sample.bns", listing)
        self.assertIn("story.txt", listing)
        extracted = Path(self.tmp.name) / "extracted"
        subprocess.run([str(tool), "extract", str(self.saved), str(extracted)], check=True, capture_output=True)
        self.assertEqual(next(extracted.rglob("sample.bns")).read_bytes(), program.read_bytes())
        worker.close()
        worker = self.start()
        worker.request("BRAILLE", "BRAILLE")
        listing = subprocess.run([str(tool), "list", str(self.saved)], check=True, capture_output=True, text=True).stdout
        self.assertIn("sample.bns", listing)
        worker.close()

    def test_import_rejects_running_unit_and_bad_stage_without_losing_memory(self):
        worker = self.start()
        worker.request("RESUME", "RUNNING")
        with self.assertRaisesRegex(WorkerError, "flash"):
            worker.request("IMPORT_CHECK", "SAVED")
        worker.request("PAUSE", "PAUSED")
        worker.request("IMPORT_CHECK", "SAVED")
        original = self.saved.read_bytes()
        Path(str(self.saved) + ".import").write_bytes(b"bad state")
        with self.assertRaises(WorkerError):
            worker.request("IMPORT_COMMIT", "IMPORTED")
        self.assertEqual(self.saved.read_bytes(), original)
        self.assertFalse(Path(str(self.saved) + ".before-import").exists())
        worker.request("RESUME", "RUNNING")
        worker.close()

    def test_import_backup_failure_retains_old_unit(self):
        import shutil
        worker = self.start()
        worker.request("IMPORT_CHECK", "SAVED")
        original = self.saved.read_bytes()
        shutil.copyfile(self.saved, Path(str(self.saved) + ".import"))
        Path(str(self.saved) + ".before-import").mkdir()
        with self.assertRaisesRegex(WorkerError, "back up"):
            worker.request("IMPORT_COMMIT", "IMPORTED")
        self.assertEqual(self.saved.read_bytes(), original)
        worker.request("RESUME", "RUNNING")
        worker.close()

    def test_new_language_discovery_setup_and_reload(self):
        from profiles import discover
        profiles = discover(EXE, FIRMWARE_DIR)
        profile = profiles.get("bl2_hu_1999_07")
        if profile is None:
            self.skipTest("Supply Hungarian firmware to exercise first-start recipe")
        self.assertIsNone(profile.factory)
        saved = Path(self.tmp.name) / profile.saved
        worker = Worker(EXE, profile.firmware, None, saved, "-")
        self.addCleanup(worker.abort)
        self.assertTrue(saved.exists())
        worker.request("RESUME", "RUNNING")
        deadline = time.monotonic() + 10
        while worker.braille is None and time.monotonic() < deadline:
            worker.request("BRAILLE", "BRAILLE")
            time.sleep(0.1)
        self.assertIsNotNone(worker.braille)
        self.assertEqual(len(worker.braille), 18)
        worker.close()
        # An existing state must win even when its factory recipe is no longer supplied.
        worker = Worker(EXE, profile.firmware, Path(self.tmp.name) / "missing-factory", saved, "-")
        self.addCleanup(worker.abort)
        worker.close()

    def test_pause_save_resume_reload_and_lock(self):
        worker = self.start()
        with self.assertRaisesRegex(WorkerError, "busy"):
            self.start()
        worker.request("RESUME", "RUNNING")
        time.sleep(0.2)
        worker.send("KEY 1 0")
        worker.send("KEY 0 1")
        worker.request("PAUSE", "PAUSED")
        worker.request("SAVE", "SAVED")
        self.assertGreater(self.saved.stat().st_size, 786432)
        self.assertFalse(self.saved.with_suffix(".state.new").exists())
        worker.request("RESUME", "RUNNING")
        worker.close()
        restored = self.start()
        restored.close()

    def test_bad_saved_state_is_not_replaced_by_factory(self):
        original = b"damaged state"
        self.saved.write_bytes(original)
        with self.assertRaises(WorkerError):
            self.start()
        self.assertEqual(self.saved.read_bytes(), original)

    def test_signal_and_parent_eof_save(self):
        for reason in ("signal", "eof"):
            with self.subTest(reason=reason):
                worker = self.start()
                worker.request("RESUME", "RUNNING")
                if reason == "signal":
                    worker.process.send_signal(signal.SIGTERM)
                else:
                    worker.input.close()
                worker.wait_for("BYE")
                self.assertEqual(worker.process.wait(timeout=5), 0)
                self.assertGreater(self.saved.stat().st_size, 786432)
                worker.abort()

    def test_save_failure_is_reported(self):
        worker = self.start()
        self.saved.mkdir()  # Atomic replacement must fail, preserving the old destination.
        with self.assertRaisesRegex(WorkerError, "save"):
            worker.request("SAVE", "SAVED")
        self.assertTrue(self.saved.is_dir())
        self.saved.rmdir()
        worker.close()

    def test_audio_failure_leaves_worker_responsive(self):
        worker = Worker(EXE, FIRMWARE, FACTORY, self.saved, "blazie_nonexistent_audio_device")
        self.addCleanup(worker.abort)
        with self.assertRaises(WorkerError):
            worker.request("RESUME", "RUNNING")
        worker.request("PAUSE", "PAUSED")
        worker.close()

    def test_real_firmware_sees_keys_held_through_restart(self):
        worker = self.start()
        worker.request("QUICK 1", "OK")  # Fast keys must still allow the original reset hold timing.
        worker.request("RESUME", "RUNNING")
        time.sleep(8)
        worker.send("KEY 0 79")  # p-chord
        time.sleep(2)
        worker.send("KEY 0 7")  # l
        time.sleep(0.25)
        worker.send("KEY 74 0")  # hold i-chord through the restart
        time.sleep(2)
        worker.send("KEY 0 74")
        time.sleep(2)
        worker.close()
        result = subprocess.run([
            str(ROOT / "build/linux/blazie_emu"), "--null", "--firmware", str(FIRMWARE.parent),
            "--state", str(self.saved), "--seconds", "0.1", "--ram-has", "initialize file system",
        ], capture_output=True, text=True, timeout=30, check=True)
        self.assertIn('ram has "initialize file system": yes', result.stdout)

    def test_quick_response_can_be_changed_while_paused_or_running(self):
        worker = self.start()
        worker.request("QUICK 1", "OK")
        worker.request("RESUME", "RUNNING")
        worker.send("KEY 0 1")
        worker.request("QUICK 0", "OK")
        worker.request("PAUSE", "PAUSED")
        with self.assertRaisesRegex(WorkerError, "Invalid"):
            worker.request("QUICK 2", "OK")
        worker.close()

    def test_double_speed_can_be_changed_while_paused_or_running_and_kept_by_a_reload(self):
        worker = self.start()
        worker.request("DOUBLE 1", "OK")
        worker.request("RESUME", "RUNNING")
        worker.send("KEY 0 1")
        worker.request("DOUBLE 0", "OK")
        worker.request("DOUBLE 1", "OK")
        worker.request("PAUSE", "PAUSED")
        worker.request("AUDIO 16000 auto 3 1 1 1", "OK")    # a new rate: the unit restarted from its memory
        with self.assertRaisesRegex(WorkerError, "Invalid"):
            worker.request("DOUBLE 2", "OK")
        worker.close()

    def serial_bytes(self, worker, ser, until, seconds):
        import select
        got, end = bytearray(), time.monotonic() + seconds
        while until not in got and time.monotonic() < end:
            worker.receive()
            if select.select([ser], [], [], 0.02)[0]:
                got.extend(os.read(ser, 256))
        return bytes(got)

    def test_serial_port_on_a_pseudo_terminal_carries_the_units_bytes_and_survives_a_new_rate(self):
        import termios
        import tty
        worker = self.start()
        self.assertEqual(worker.answer("SERIAL /etc/passwd", "SERIAL", "SERIAL_FAILED")[0], "SERIAL_FAILED")
        self.assertEqual(worker.answer("SERIAL /dev/ttyNOPE", "SERIAL", "SERIAL_FAILED"),
                         ("SERIAL_FAILED", "could not open /dev/ttyNOPE: No such file or directory"))
        worker.request("QUICK 0", "OK")                     # a port that would not open ends nothing
        reply, other = worker.answer("SERIAL pty", "SERIAL", "SERIAL_FAILED")
        self.assertEqual(reply, "SERIAL")
        self.assertTrue(other.startswith("pty /dev/pts/"), other)
        ser = os.open(other[4:], os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        self.addCleanup(os.close, ser)
        tty.setraw(ser)
        worker.request("AUDIO 16000 auto 3 1 1 1", "OK")    # a new rate: the new unit is on the line too
        worker.request("RESUME", "RUNNING")
        self.serial_bytes(worker, ser, b"\x05", 6)          # its greeting over (4 s on a Pi 5)
        worker.send("KEY 0 78")                             # s-chord (space, dots 2 3 4): storage, XON ENQ
        sent = self.serial_bytes(worker, ser, b"\x05", 5)
        self.assertTrue(sent.endswith(b"\x11\x05"), sent)
        self.assertEqual(termios.tcgetattr(ser)[4], termios.B19200)
        self.assertEqual(worker.answer("SERIAL none", "SERIAL", "SERIAL_FAILED"), ("SERIAL", "none"))
        worker.close()

    def test_audio_controls_all_rates_and_buffers_keep_memory(self):
        from audio_options import AudioOptions, RATES
        from dataclasses import replace
        worker = self.start()
        worker.request("RESUME", "RUNNING")
        time.sleep(0.2)
        worker.request("PAUSE", "PAUSED")
        worker.request("SAVE", "SAVED")
        flash = self.saved.read_bytes()[262144:-64]
        options = AudioOptions()
        worker.request("AUDIO", options.command())
        worker.request("QUICK 1", "OK")
        for rate in RATES:
            options = replace(options, rate=rate)
            worker.request(options.command(), "OK")
            worker.request("AUDIO", options.command())
            worker.request("RESUME", "RUNNING")
            time.sleep(0.03)
            worker.request("PAUSE", "PAUSED")
        for mode in ("auto", "medium", "long"):
            for idle in range(4):
                options = replace(options, buffer=mode, idle=idle, keep_open=idle % 3, pop_click=bool(idle % 2), tick=False)
                worker.request(options.command(), "OK")
                worker.request("AUDIO", options.command())
        worker.request("SAVE", "SAVED")
        self.assertEqual(self.saved.read_bytes()[262144:-64], flash)
        for invalid in ("AUDIO 123 long 3 1 1 1", "AUDIO 22050 short 3 1 1 1", "AUDIO 22050 auto 4 1 1 1",
                        "AUDIO 22050 auto 3 3 1 1", "AUDIO 22050 auto 3 1 2 1", "AUDIO 22050 auto 3 1 1 2"):
            with self.assertRaises(WorkerError):
                worker.request(invalid, "OK")
            worker.request("AUDIO", options.command())
        worker.request("RESUME", "RUNNING")
        with self.assertRaisesRegex(WorkerError, "not paused"):
            worker.request(options.command(), "OK")
        worker.close()

    def test_sample_rate_save_failure_keeps_running_unit(self):
        worker = self.start()
        self.saved.mkdir()
        with self.assertRaisesRegex(WorkerError, "save"):
            worker.request("AUDIO 48000 auto 0 0 0 0", "OK")
        worker.request("AUDIO", "AUDIO 22050 auto 3 1 1 1")
        worker.request("RESUME", "RUNNING")
        worker.request("PAUSE", "PAUSED")
        self.saved.rmdir()
        worker.close()

    def test_sample_rate_device_failure_keeps_old_settings(self):
        worker = Worker(EXE, FIRMWARE, FACTORY, self.saved, "blazie_nonexistent_audio_device")
        self.addCleanup(worker.abort)
        with self.assertRaises(WorkerError):
            worker.request("AUDIO 48000 auto 0 0 0 0", "OK")
        worker.request("AUDIO", "AUDIO 22050 auto 3 1 1 1")
        worker.close()

    def test_sample_rate_reload_failure_keeps_old_unit(self):
        firmware = Path(self.tmp.name) / "copy.BNS"
        firmware.write_bytes(FIRMWARE.read_bytes())
        worker = Worker(EXE, firmware, FACTORY, self.saved, "-")
        self.addCleanup(worker.abort)
        firmware.unlink()  # The current unit has it in memory; recreating it must fail safely.
        with self.assertRaises(WorkerError):
            worker.request("AUDIO 48000 auto 0 0 0 0", "OK")
        worker.request("AUDIO", "AUDIO 22050 auto 3 1 1 1")
        worker.request("RESUME", "RUNNING")
        worker.request("PAUSE", "PAUSED")
        worker.close()

    def test_firmware_braille_directory_and_help_file(self):
        worker = self.start()
        worker.request("BRAILLE", "BRAILLE")
        self.assertIsNone(worker.braille)  # No invented text before the firmware's first display latch.
        worker.request("RESUME", "RUNNING")
        time.sleep(3)
        worker.request("BRAILLE", "BRAILLE")
        self.assertEqual(len(worker.braille), 18)
        # The supplied factory state starts at file 0, help: number-sign, j (zero), space, h e l p.
        self.assertEqual(worker.braille[:7], bytes.fromhex("3c1a001311070f"))
        for chord in (0x55, 0x75, 0x51):  # Options, cancel, E-chord to open help.
            worker.send("KEY 0 {chord}".format(chord=chord))
            time.sleep(0.7)
        worker.request("BRAILLE", "BRAILLE")
        # The actual help text starts with 'braille lite', in the firmware's dot patterns.
        self.assertEqual(worker.braille[:12], bytes.fromhex("0317010a07071100070a1e11"))
        first = worker.braille
        # Short physical taps: press and release can arrive in the same pipe read.
        # The firmware must see its port B contacts, not a synthetic keyboard chord.
        for bars in (1, 2, 1, 2):
            worker.send("BARS {bars}".format(bars=bars))
            worker.send("BARS 0")
            time.sleep(0.7)
            worker.request("BRAILLE", "BRAILLE")
            if bars == 1:
                self.assertNotEqual(worker.braille, first)
            else:
                self.assertEqual(worker.braille, first)
        # Pausing releases a held bar and drops pending input before entering host menus.
        worker.send("BARS 1")
        time.sleep(0.7)
        worker.request("PAUSE", "PAUSED")
        worker.request("RESUME", "RUNNING")
        worker.send("BARS 2")
        worker.send("BARS 0")
        time.sleep(0.7)
        worker.request("BRAILLE", "BRAILLE")
        self.assertEqual(worker.braille, first)
        worker.send("BARS 1\nPAUSE")
        worker.wait_for("PAUSED")
        worker.request("RESUME", "RUNNING")
        time.sleep(0.7)
        worker.request("BRAILLE", "BRAILLE")
        self.assertEqual(worker.braille, first)
        worker.request("PAUSE", "PAUSED")
        frame = worker.braille
        time.sleep(0.1)
        worker.request("BRAILLE", "BRAILLE")
        self.assertEqual(worker.braille, frame)
        worker.close()

    def test_spanish_firmware_has_its_own_display_and_saved_memory(self):
        from profiles import discover
        BY_KEY = discover(EXE, FIRMWARE.parent)
        paths = BY_KEY["bl-es"].paths(FIRMWARE.parent, Path(self.tmp.name))
        if not paths[0].exists() or not paths[1].exists():
            self.skipTest("Spanish firmware not supplied")
        english = self.start()
        english.request("SAVE", "SAVED")
        before = self.saved.read_bytes()
        spanish = Worker(EXE, *paths, "-")
        self.addCleanup(spanish.abort)
        spanish.request("RESUME", "RUNNING")
        time.sleep(3)
        spanish.request("BRAILLE", "BRAILLE")
        self.assertEqual(len(spanish.braille), 18)
        spanish.close()
        self.assertTrue(paths[2].is_file())
        self.assertEqual(self.saved.read_bytes(), before)
        english.close()

    def test_type_n_speak_cold_start_keyboard_and_save(self):
        from profiles import discover
        BY_KEY = discover(EXE, FIRMWARE.parent)
        for key, yes in (("tns-en", "y"), ("tns-es", "s")):
            with self.subTest(key=key):
                paths = BY_KEY[key].paths(FIRMWARE.parent, Path(self.tmp.name))
                if not paths[0].exists():
                    self.skipTest("Type 'n Speak firmware not supplied")
                worker = Worker(EXE, *paths, "-", kind="tns")
                self.addCleanup(worker.abort)
                worker.request("RESUME", "RUNNING")
                time.sleep(1)
                worker.request("BRAILLE", "BRAILLE")
                self.assertIsNone(worker.braille)
                worker.request("TNS " + yes, "OK")
                time.sleep(1)
                worker.request("PAUSE", "PAUSED")
                with self.assertRaisesRegex(WorkerError, "Unknown"):
                    worker.request("TNS nonexistent", "OK")
                worker.close()
                self.assertTrue(paths[2].is_file())
                if key == "tns-en":
                    # The yes key reached the real firmware: it advanced to the confirmation question.
                    result = subprocess.run([
                        str(ROOT / "build/linux/blazie_emu"), "--null", "--unit", key,
                        "--firmware", str(FIRMWARE.parent), "--state", str(paths[2]),
                        "--seconds", "0.1", "--ram-has", "are you sure",
                    ], capture_output=True, text=True, timeout=30, check=True)
                    self.assertIn('ram has "are you sure": yes', result.stdout)


if __name__ == "__main__":
    unittest.main()
