"""Host integration with simulated keyboard events; never touches device services."""

import contextlib
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

from frontend import capture, deep_escape, host_menu, main, menu_session, show_intro
from keymap import DEEP_ESCAPE, MENU
from preferences import Preferences
from profiles import Profile


class Connection:
    def __init__(self, events):
        self.reader, self.writer = socket.socketpair()
        self.events = iter(events)
        self.writer.sendall(b"x" * len(events))
        self.acks = 0
        self.reads = 0
        self.closed = False

    def fileno(self):
        return self.reader.fileno()

    def read_key(self):
        self.reader.recv(1)
        self.reads += 1
        return next(self.events)

    def ack_consume(self):
        self.acks += 1

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True
        self.reader.close()
        self.writer.close()


def keyboard(events):
    conn = Connection(events)
    kb = ModuleType("kb_client")
    kb.BTB_DOT1 = 497
    kb.BTB_SPACE = 57
    kb.BTB_R3 = 261
    kb.BTB_R2 = 260
    kb.BTB_L2 = 257
    kb.BTB_L3 = 258
    kb.FLAG_EXCLUSIVE = 1
    kb.FLAG_WANT_RAW = 2
    kb.connect = lambda flags: conn
    kb.server_available = lambda: True
    return kb, conn


def chord_events(bits):
    keys = [497 + dot for dot in range(8) if bits & (1 << dot)]
    if bits & 256:
        keys.append(57)
    return [SimpleNamespace(key=key, state=pressed) for pressed in (True, False) for key in keys]


class FrontendTests(unittest.TestCase):
    def setUp(self):
        def catalog(executable, root):
            return {key: Profile(key, label, root / firmware, root / factory, saved)
                    for key, label, firmware, factory, saved in (
                        ("bl-en", "English", "BL2ENG.BNS", "bl2_2003_warm.state", "english.state"),
                        ("bl-es", "Spanish", "BL2SPA.BNS", "bl2spa_fresh.state", "spanish.state"))}
        self.catalog_patch = patch("frontend.discover", side_effect=catalog)
        self.catalog_patch.start()
        self.addCleanup(self.catalog_patch.stop)
        # Braille Settings' table, never the device's own: both sides pan, L2 and R2 back, L3 and R3 forward
        tables = tempfile.TemporaryDirectory()
        self.addCleanup(tables.cleanup)
        table = Path(tables.name) / "btbraille-nav-keys.kti"
        table.write_text("bind L2 FWINLT\nbind L3 FWINRT\nbind R2 FWINLT\nbind R3 FWINRT\n")
        tables_patch = patch("panning.TABLES", (table,))
        tables_patch.start()
        self.addCleanup(tables_patch.stop)

    def test_intro_is_shown_once_across_launches_and_preserved_by_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "preferences.json"
            path.write_text('{"quick_keys": true, "unit": "bl-es"}')
            prefs = Preferences.load(path)
            dialogs = SimpleNamespace(show_message=Mock())
            show_intro(dialogs, prefs)
            loaded = Preferences.load(path)
            self.assertTrue(loaded.intro_shown)
            self.assertTrue(loaded.quick_keys)
            self.assertEqual(loaded.unit, "bl-es")
            loaded.store(False, unit="tns-en")
            show_intro(dialogs, Preferences.load(path))
            dialogs.show_message.assert_called_once()

    def test_failed_intro_or_save_is_not_remembered(self):
        with tempfile.TemporaryDirectory() as tmp:
            prefs = Preferences(Path(tmp) / "preferences.json")
            dialogs = SimpleNamespace(show_message=Mock(side_effect=OSError("display failed")))
            with self.assertRaises(OSError):
                show_intro(dialogs, prefs)
            self.assertFalse(prefs.path.exists())
            dialogs.show_message.side_effect = None
            with patch.object(prefs, "store", side_effect=OSError("disk full")), self.assertRaises(OSError):
                show_intro(dialogs, prefs)
            self.assertFalse(prefs.intro_shown)

    def test_submenus_share_screen_and_return_to_previous_row(self):
        window = object()
        steps = iter(["o", "b", None, "x", "f", None, "r"])
        calls = []

        def choice(choices, *, prompt, default, stdscr):
            self.assertIs(stdscr, window)
            self.assertNotIn("a", choices)
            calls.append((prompt, default))
            key = next(steps)
            return None if key is None else SimpleNamespace(key=key)

        def wrapper(fn):
            self.assertEqual(worker.request.call_count, 0)
            return fn(window)

        dialogs = SimpleNamespace(request_choice=choice, curses_wrapper_low_level2=Mock(side_effect=wrapper))
        worker = Mock()
        prefs = Preferences(Path("unused"))
        self.assertEqual(menu_session(worker, dialogs, prefs, {"bl-en": "English"}), "resume")
        dialogs.curses_wrapper_low_level2.assert_called_once()
        worker.request.assert_not_called()
        self.assertEqual(calls, [("Blazie emulator", "r"), ("Audio settings", "b"), ("Sound buffer", "auto"),
                                ("Audio settings", "b"), ("Blazie emulator", "o"), ("Choose firmware", "bl-en"),
                                ("Blazie emulator", "f")])

    def test_menu_failure_propagates_after_terminal_restored(self):
        events = []

        def wrapper(fn):
            fn(object())
            events.append("restored")

        dialogs = SimpleNamespace(curses_wrapper_low_level2=wrapper)
        with patch("frontend.host_menu", side_effect=OSError("save failed")), self.assertRaises(OSError):
            menu_session(Mock(), dialogs, Preferences(Path("unused")), {})
        self.assertEqual(events, ["restored"])

    def test_type_n_speak_uses_qwerty_adapter_without_leaking_menu_chord(self):
        kb, conn = keyboard(chord_events(0x3D) + chord_events(256 | 0x11) + chord_events(MENU))
        output, peer = socket.socketpair()
        self.addCleanup(output.close)
        self.addCleanup(peer.close)
        commands = []
        capture(SimpleNamespace(output=output, send=commands.append), kb, tns=True)
        self.assertEqual(commands, ["TNS y", "TNS enter"])
        self.assertEqual(conn.reads, conn.acks)

    def test_panel_pairs_are_independent_of_chords_and_keep_overlapping_holds(self):
        presses = [(258, True), (261, True), (258, False), (261, False),
                   (257, True), (260, True), (257, False), (260, False),
                   (258, True), (260, True), (258, False), (260, False)]
        events = [SimpleNamespace(key=key, state=state) for key, state in presses]
        kb, conn = keyboard(events + chord_events(MENU))
        output, peer = socket.socketpair()
        self.addCleanup(output.close)
        self.addCleanup(peer.close)
        commands = []

        def send(command):
            self.assertEqual(conn.reads, conn.acks)
            commands.append(command)

        capture(SimpleNamespace(output=output, send=send), kb)
        self.assertEqual([c for c in commands if c.startswith("BARS")],
                         ["BARS " + str(n) for n in (1, 1, 1, 0, 2, 2, 2, 0, 1, 3, 2, 0)])
        self.assertFalse(any(c.startswith("KEY") and c.split()[-1] != "0" for c in commands))

    def test_bars_follow_the_layout_set_in_braille_settings(self):
        # left-right navigation and panning: L3 back, R3 forward; L2 and R2 are line up and down, not the unit's
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        table = Path(tmp.name) / "btbraille-nav-keys.kti"
        table.write_text("bind L1 CHRLT\nbind L2 LNUP\nbind L3 FWINLT\nbind R1 CHRRT\nbind R2 LNDN\nbind R3 FWINRT\n")
        presses = [(258, True), (258, False), (261, True), (261, False), (257, True), (257, False),
                   (260, True), (260, False), (258, True), (261, True), (261, False), (258, False)]
        kb, conn = keyboard([SimpleNamespace(key=key, state=state) for key, state in presses] + chord_events(MENU))
        output, peer = socket.socketpair()
        self.addCleanup(output.close)
        self.addCleanup(peer.close)
        commands = []
        with patch("panning.TABLES", (table,)):
            capture(SimpleNamespace(output=output, send=commands.append), kb)
            help_shown = Mock()
            host_menu(Mock(), SimpleNamespace(request_choice=Mock(side_effect=[SimpleNamespace(key="h"), None]),
                                              show_message=help_shown), SimpleNamespace(quick_keys=False, double_speed=False))
        self.assertEqual([c for c in commands if c.startswith("BARS")],
                         ["BARS " + str(n) for n in (2, 0, 1, 0, 2, 3, 2, 0)])
        self.assertFalse(any(c.startswith("KEY") and c.split()[-1] != "0" for c in commands))
        self.assertIn("R3 advances braille; L3 moves it back", help_shown.call_args.args[0])
        # a key the keyboard does not report is not named: the older keypad's bridge has no L1
        table.write_text("bind L1 FWINRT\nbind R2 FWINLT\n")
        legacy = ModuleType("legacy_keyboard")
        legacy.BTB_L2, legacy.BTB_L3, legacy.BTB_R2, legacy.BTB_R3 = 257, 258, 260, 261
        with patch("panning.TABLES", (table,)):
            host_menu(Mock(), SimpleNamespace(request_choice=Mock(side_effect=[SimpleNamespace(key="h"), None]),
                                              show_message=help_shown), SimpleNamespace(quick_keys=False, double_speed=False),
                      kb_client=legacy)
        self.assertIn("R2 moves braille back", help_shown.call_args.args[0])
        self.assertNotIn("L1", help_shown.call_args.args[0])

    def test_menu_is_in_groups_unit_files_restarts_settings_then_help_and_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "factory.state").touch()
            shown = {}
            for kind in ("bl", "tns"):
                profile = Profile("bl-en", "English", root / "fw", root / "factory.state", "english.state", kind)
                dialogs = SimpleNamespace(request_file=Mock(), request_directory=Mock(),
                                          request_choice=lambda choices, **k: shown.setdefault(kind, list(choices)) and None)
                host_menu(Mock(), dialogs, SimpleNamespace(quick_keys=False, double_speed=False, unit="bl-en"),
                          {"bl-en": "English"}, profile=profile, files_tool=root / "blazie_files",
                          serial=SimpleNamespace(label=lambda: "not connected"))
            self.assertEqual(shown["bl"], ["r", "f", "s", "p", "c", "x", "i", "e", "n", "w", "b", "k", "d", "o", "l", "h", "q"])
            self.assertEqual(shown["tns"], ["r", "f", "t", "s", "p", "c", "x", "i", "e", "b", "k", "d", "o", "l", "h", "q"])

    def test_files_factory_and_serial_are_offered_when_they_can_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "factory.state").touch()
            offered = []

            def choice(choices, **kwargs):
                offered.append(set(choices))
                return None

            prefs = SimpleNamespace(quick_keys=False, double_speed=False)
            bl = Profile("bl-en", "English", root / "BL2ENG.BNS", root / "factory.state", "english.state")
            missing = Profile("bl-es", "Spanish", root / "BL2SPA.BNS", root / "gone.state", "spanish.state")
            release = Profile("bl2_hu_1999_07", "Hungarian", root / "HU.BNS", None, "bl2_hu_1999_07.state")
            pickers = dict(request_choice=choice, request_file=Mock(), request_directory=Mock())
            host_menu(Mock(), SimpleNamespace(**pickers), prefs, profile=bl, files_tool=root / "blazie_files",
                      serial=SimpleNamespace(label=lambda: "not connected"))
            host_menu(Mock(), SimpleNamespace(request_choice=choice, request_file=Mock()), prefs, profile=missing,
                      files_tool=root / "blazie_files")
            host_menu(Mock(), SimpleNamespace(request_choice=choice), prefs, profile=release)
            items = {"p", "c", "x", "i", "b", "l"}
            self.assertTrue(items <= offered[0])
            self.assertEqual({"p", "i"}, offered[1] & items)    # no folder picker; no factory state
            self.assertEqual({"b"}, offered[2] & items)         # made by its recipe

            confirm = Mock(side_effect=[False, True])
            dialogs = SimpleNamespace(request_choice=Mock(return_value=SimpleNamespace(key="b")),
                                      request_confirmation=confirm)
            self.assertEqual(host_menu(Mock(), dialogs, prefs, profile=bl), "factory")
            self.assertEqual(confirm.call_count, 2)                                 # declined once: the menu again
            self.assertFalse(confirm.call_args.kwargs["default"])

    def run_main(self, root, workers, actions, preferences=None):
        said = []
        runtime = ModuleType("BTSpeak")
        runtime.kb_client = SimpleNamespace(server_available=lambda: True)
        runtime.brl = SimpleNamespace(has_display=lambda: False, write=lambda text: None)
        runtime.host = SimpleNamespace(push_self_voice=lambda value: None, pop_self_voice=lambda: None,
                                       say=lambda text, **kwargs: said.append(text))
        runtime.dialogs = SimpleNamespace(activity=lambda text, **kwargs: contextlib.nullcontext(), show_message=Mock(),
                                          curses_wrapper_low_level2=lambda fn: fn(object()))
        runtime.script = SimpleNamespace(start_log=lambda: Mock())
        (preferences or Preferences(root / "preferences.json")).store(False, intro_shown=True)
        with (patch.dict(sys.modules, {"BTSpeak": runtime}),
              patch("frontend.Worker", side_effect=workers) as start,
              patch("frontend.capture", return_value="menu"),
              patch("frontend.host_menu", side_effect=actions),
              patch.object(sys, "argv", ["blazie", "--backend", str(root / "backend"),
                                        "--firmware", str(root), "--state-dir", str(root)])):
            self.assertEqual(main(), 0)
        return start, said, runtime.dialogs.show_message

    def test_back_to_the_factory_state_deletes_the_saved_unit_and_its_update_before_starting_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("backend", "BL2ENG.BNS", "bl2_2003_warm.state"):
                (root / name).touch()
            saved = root / "english.state"
            events = []

            def unit(name):
                return SimpleNamespace(braille=bytes(18), saved=saved,
                    request=lambda cmd, reply: events.append((name, cmd)),
                    close=lambda: events.append((name, "close")),
                    abort=lambda: events.append((name, "abort")))

            def start(*args, **kwargs):
                if events:   # the second unit: what it finds on disk
                    events.append(("gone", not saved.exists() and not Path(str(saved) + ".program").exists()))
                saved.write_bytes(b"memory")
                Path(str(saved) + ".program").write_bytes(b"update")
                return unit("first" if not events else "second")

            start, said, _shown = self.run_main(root, start, ["factory", "quit"])
            self.assertEqual(start.call_args_list[1].args[1:4], (root / "BL2ENG.BNS", root / "bl2_2003_warm.state", saved))
            self.assertLess(events.index(("first", "close")), events.index(("gone", True)))
            self.assertIn("Unit back to its factory state", said)

    def test_the_serial_port_is_plugged_in_whenever_a_unit_starts_and_a_missing_one_is_said(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("backend", "BL2ENG.BNS", "bl2_2003_warm.state", "BL2SPA.BNS", "bl2spa_fresh.state"):
                (root / name).touch()
            events = []

            def unit(name, reply):
                return SimpleNamespace(braille=bytes(18), saved=root / "english.state", request=lambda cmd, r: None,
                                       answer=lambda cmd, *replies: events.append((name, cmd)) or reply,
                                       close=lambda: events.append((name, "close")), abort=lambda: None)

            preferences = Preferences(root / "preferences.json")
            preferences.store(False, serial="/dev/ttyUSB0")
            _start, _said, shown = self.run_main(root, [unit("first", ("SERIAL_FAILED", "No such file or directory")),
                                                        unit("second", ("SERIAL", "/dev/ttyUSB0"))],
                                                 ["unit:bl-es", "quit"], preferences)
            # a firmware switch: the new unit takes the port once the old one has closed (a port is one unit's)
            self.assertEqual(events, [("first", "SERIAL /dev/ttyUSB0"), ("first", "close"),
                                      ("second", "SERIAL /dev/ttyUSB0"), ("second", "close")])
            self.assertIn("/dev/ttyUSB0 is not connected: No such file or directory", shown.call_args_list[0].args[0])
            self.assertEqual(shown.call_count, 1)
            self.assertEqual(Preferences.load(root / "preferences.json").serial, "/dev/ttyUSB0")   # kept for next time

    def test_firmware_menu_returns_selection_without_changing_running_unit(self):
        prefs = Preferences(Path("unused"))
        worker = Mock()
        dialogs = SimpleNamespace(request_choice=Mock(side_effect=[SimpleNamespace(key="f"),
                                                                   SimpleNamespace(key="bl-es")]))
        units = {"bl-en": "English", "bl-es": "Spanish"}
        self.assertEqual(host_menu(worker, dialogs, prefs, units), "unit:bl-es")
        self.assertEqual(prefs.unit, "bl-en")
        worker.assert_not_called()

    def test_switch_saves_old_unit_before_resuming_new_and_remembers_selection(self):
        for fail in (False, True):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                for name in ("backend", "BL2ENG.BNS", "bl2_2003_warm.state", "BL2SPA.BNS", "bl2spa_fresh.state"):
                    (root / name).touch()
                events = []

                def unit(name):
                    return SimpleNamespace(braille=bytes(18),
                        request=lambda cmd, reply: events.append((name, cmd)),
                        close=lambda: events.append((name, "close")),
                        abort=lambda: events.append((name, "abort")))

                english, spanish = unit("en"), unit("es")
                runtime = ModuleType("BTSpeak")
                runtime.kb_client = SimpleNamespace(server_available=lambda: True)
                runtime.brl = SimpleNamespace(has_display=lambda: False, write=lambda text: None)
                runtime.host = SimpleNamespace(push_self_voice=lambda value: None, pop_self_voice=lambda: None)
                runtime.dialogs = SimpleNamespace(activity=lambda text, **kwargs: contextlib.nullcontext(), show_message=Mock(),
                                                 curses_wrapper_low_level2=lambda fn: fn(object()))
                runtime.script = SimpleNamespace(start_log=lambda: Mock())
                outcomes = [english, OSError("bad firmware") if fail else spanish]
                with (patch.dict(sys.modules, {"BTSpeak": runtime}), patch("frontend.Worker", side_effect=outcomes) as start,
                      patch("frontend.capture", return_value="menu"),
                      patch("frontend.host_menu", side_effect=["unit:bl-es", "quit"]),
                      patch.object(sys, "argv", ["blazie", "--backend", str(root / "backend"),
                                                "--firmware", tmp, "--state-dir", tmp])):
                    self.assertEqual(main(), 0)
                self.assertEqual(start.call_args_list[0].args[3], root / "english.state")
                self.assertEqual(start.call_args_list[1].args[3], root / "spanish.state")
                self.assertEqual(Preferences.load(root / "preferences.json").unit, "bl-en" if fail else "bl-es")
                if fail:
                    self.assertEqual(events.count(("en", "RESUME")), 2)
                    runtime.dialogs.show_message.assert_any_call("Could not switch firmware: bad firmware")
                else:
                    self.assertLess(events.index(("en", "close")), events.index(("es", "RESUME")))
                    self.assertIn(("es", "close"), events)

    def test_ack_before_forward_and_menu_does_not_leak(self):
        kb, conn = keyboard(chord_events(256 | 0x11) + chord_events(MENU))
        output, peer = socket.socketpair()
        self.addCleanup(output.close)
        self.addCleanup(peer.close)
        commands = []

        def send(command):
            self.assertEqual(conn.reads, conn.acks)
            commands.append(command)

        worker = SimpleNamespace(output=output, send=send)
        capture(worker, kb)
        self.assertTrue(conn.closed)
        self.assertEqual([c for c in commands if c.split()[-1] != "0"], ["KEY 0 81"])
        self.assertEqual(commands[-1], "KEY 0 0")

    def test_capture_releases_keyboard_on_worker_failure(self):
        kb, conn = keyboard(chord_events(1))
        output, peer = socket.socketpair()
        self.addCleanup(output.close)
        self.addCleanup(peer.close)

        def send(command):
            raise OSError("broken pipe")

        with self.assertRaises(OSError):
            capture(SimpleNamespace(output=output, send=send), kb)
        self.assertTrue(conn.closed)
        self.assertEqual(conn.reads, conn.acks)

    def test_main_pauses_and_releases_before_dialog_and_restores_on_exit(self):
        self.run_exit(MENU)

    def test_deep_escape_saves_and_restores_before_leaving_terminal(self):
        self.run_exit(DEEP_ESCAPE)

    def test_deep_escape_save_failure_does_not_close_terminal(self):
        self.run_exit(DEEP_ESCAPE, save_failure=True)

    def run_exit(self, chord, save_failure=False):
        kb, conn = keyboard(chord_events(chord))
        output, peer = socket.socketpair()
        self.addCleanup(output.close)
        self.addCleanup(peer.close)
        actions = []
        def close():
            actions.append("close")
            if save_failure:
                raise OSError("save failed")

        worker = SimpleNamespace(
            braille=bytes(range(18)),
            output=output, send=lambda command: actions.append(command),
            request=lambda command, response: actions.append(command),
            close=close,
            abort=lambda: actions.append("abort"),
        )

        def choice(*args, **kwargs):
            self.assertNotEqual(chord, DEEP_ESCAPE)
            self.assertTrue(conn.closed)
            self.assertEqual(actions[-1], "PAUSE")
            return SimpleNamespace(key="q")

        runtime = ModuleType("BTSpeak")
        runtime.kb_client = kb
        runtime.brl = SimpleNamespace(write=lambda text: actions.append(("braille", text)), get_display_width=lambda: 40,
                                      has_display=lambda: True, write_dots=lambda cells: actions.append(("dots", cells)))
        runtime.host = SimpleNamespace(push_self_voice=lambda value: actions.append("push"),
                                       pop_self_voice=lambda: actions.append("pop"))
        runtime.dialogs = SimpleNamespace(activity=lambda text, **kwargs: contextlib.nullcontext(),
                                          show_message=lambda text: None, request_choice=choice,
                                          curses_wrapper_low_level2=lambda fn: fn(object()))
        runtime.script = SimpleNamespace(start_log=lambda: Mock())

        def leave(host):
            self.assertTrue(conn.closed)
            self.assertEqual(actions[-4:], ["close", "abort", ("braille", ""), "pop"])
            actions.append("deep_escape")

        with tempfile.TemporaryDirectory() as tmp:
            backend = Path(tmp) / "backend"
            backend.touch()
            for name in ("BL2ENG.BNS", "bl2_2003_warm.state"):
                (Path(tmp) / name).touch()
            with (patch.dict(sys.modules, {"BTSpeak": runtime}), patch("frontend.Worker", return_value=worker),
                  patch("frontend.deep_escape", side_effect=leave) as escape):
                with patch.object(sys, "argv", ["blazie", "--backend", str(backend), "--state-dir", tmp, "--firmware", tmp]):
                    self.assertEqual(main(), int(save_failure))
                self.assertEqual(escape.call_count, int(chord == DEEP_ESCAPE and not save_failure))
        self.assertEqual(actions[0], "push")
        self.assertIn("QUICK 0", actions)
        self.assertIn(("dots", bytes(range(18)) + bytes(22)), actions)

    def test_deep_escape_uses_detached_platform_helper(self):
        host = SimpleNamespace(repository_path=Path("/platform"))
        with patch("frontend.os.geteuid", return_value=1000), patch("frontend.subprocess.run") as run:
            deep_escape(host)
        self.assertEqual(run.call_args.args[0], ["sudo", "-n", "/platform/Tools/deep-escape"])
        self.assertTrue(run.call_args.kwargs["start_new_session"])

    def test_quick_menu_toggles_and_remembers_preference(self):
        with tempfile.TemporaryDirectory() as tmp:
            prefs = Preferences.load(Path(tmp) / "preferences.json")
            worker = Mock()
            labels = []
            def choice(choices, **kwargs):
                labels.append(choices["k"])
                return SimpleNamespace(key="k" if len(labels) == 1 else "r")
            self.assertEqual(host_menu(worker, SimpleNamespace(request_choice=choice), prefs), "resume")
            worker.request.assert_called_once_with("QUICK 1", "OK")
            self.assertTrue(Preferences.load(prefs.path).quick_keys)
            self.assertEqual(labels, ["Quick key response: off", "Quick key response: on"])
            # The same menu switches back off and persists that choice too.
            labels.clear()
            host_menu(worker, SimpleNamespace(request_choice=choice), prefs)
            worker.request.assert_called_with("QUICK 0", "OK")
            self.assertFalse(Preferences.load(prefs.path).quick_keys)

    def test_double_speed_menu_toggles_and_remembers_preference(self):
        with tempfile.TemporaryDirectory() as tmp:
            prefs = Preferences.load(Path(tmp) / "preferences.json")
            worker = Mock()
            labels = []
            def choice(choices, **kwargs):
                labels.append(choices["d"])
                return SimpleNamespace(key="d" if len(labels) == 1 else "r")
            told = Mock()
            dialogs = SimpleNamespace(request_choice=choice, show_message=told)
            self.assertEqual(host_menu(worker, dialogs, prefs), "resume")
            worker.request.assert_called_once_with("DOUBLE 1", "OK")
            loaded = Preferences.load(prefs.path)
            self.assertTrue(loaded.double_speed)
            self.assertFalse(loaded.quick_keys)
            self.assertEqual(labels, ["Double-speed upgrade installed: off", "Double-speed upgrade installed: on"])
            self.assertIn("status menu", told.call_args.args[0])       # how to switch it on in the unit
            labels.clear()
            told.reset_mock()
            host_menu(worker, dialogs, prefs)
            worker.request.assert_called_with("DOUBLE 0", "OK")
            self.assertFalse(Preferences.load(prefs.path).double_speed)
            told.assert_not_called()

    def test_double_speed_preference_round_trips_and_old_files_load_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "preferences.json"
            path.write_text('{"quick_keys": true, "unit": "bl-es"}')
            old = Preferences.load(path)
            self.assertFalse(old.double_speed)
            old.store(old.quick_keys, double_speed=True)
            again = Preferences.load(path)
            self.assertTrue(again.double_speed and again.quick_keys)
            self.assertEqual(again.unit, "bl-es")
            again.store(again.quick_keys, unit="bl-en")                 # other changes keep it
            self.assertTrue(Preferences.load(path).double_speed)
            path.write_text('{"double_speed": "yes"}')
            with self.assertRaises(ValueError):
                Preferences.load(path)

    def test_restart_saves_the_unit_and_starts_it_again_from_its_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("backend", "BL2ENG.BNS", "bl2_2003_warm.state"):
                (root / name).touch()
            events = []

            def unit(name):
                return SimpleNamespace(braille=bytes(18),
                    request=lambda cmd, reply: events.append((name, cmd)),
                    close=lambda: events.append((name, "close")),
                    abort=lambda: events.append((name, "abort")))

            first, second = unit("first"), unit("second")
            said = []
            runtime = ModuleType("BTSpeak")
            runtime.kb_client = SimpleNamespace(server_available=lambda: True)
            runtime.brl = SimpleNamespace(has_display=lambda: False, write=lambda text: None)
            runtime.host = SimpleNamespace(push_self_voice=lambda value: None, pop_self_voice=lambda: None,
                                           say=lambda text, **kwargs: said.append(text))
            runtime.dialogs = SimpleNamespace(activity=lambda text, **kwargs: contextlib.nullcontext(), show_message=Mock(),
                                              curses_wrapper_low_level2=lambda fn: fn(object()))
            runtime.script = SimpleNamespace(start_log=lambda: Mock())
            Preferences(root / "preferences.json").store(False, double_speed=True)
            with (patch.dict(sys.modules, {"BTSpeak": runtime}),
                  patch("frontend.Worker", side_effect=[first, second]) as start,
                  patch("frontend.capture", return_value="menu"),
                  patch("frontend.host_menu", side_effect=["restart", "quit"]),
                  patch.object(sys, "argv", ["blazie", "--backend", str(root / "backend"),
                                            "--firmware", tmp, "--state-dir", tmp])):
                self.assertEqual(main(), 0)
            # the same unit's memory both times: the first closed (saved) before the second runs
            self.assertEqual(start.call_args_list[0].args[3], root / "english.state")
            self.assertEqual(start.call_args_list[1].args[3], root / "english.state")
            self.assertLess(events.index(("first", "close")), events.index(("second", "RESUME")))
            self.assertIn(("first", "DOUBLE 1"), events)
            self.assertIn(("second", "DOUBLE 1"), events)               # the upgrade carried into the restarted unit
            self.assertIn(("second", "close"), events)
            self.assertIn("Unit restarted", said)

    def test_one_handed_restart_holds_dot_6_from_the_new_units_first_instant(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("backend", "BL2ENG.BNS", "bl2_2003_warm.state"):
                (root / name).touch()
            events = []

            def unit(name):
                return SimpleNamespace(braille=bytes(18),
                    request=lambda cmd, reply: events.append((name, cmd)),
                    close=lambda: events.append((name, "close")),
                    abort=lambda: events.append((name, "abort")))

            runtime = ModuleType("BTSpeak")
            runtime.kb_client = SimpleNamespace(server_available=lambda: True)
            runtime.brl = SimpleNamespace(has_display=lambda: False, write=lambda text: None)
            runtime.host = SimpleNamespace(push_self_voice=Mock(), pop_self_voice=Mock(), say=Mock())
            runtime.dialogs = SimpleNamespace(activity=lambda text, **kwargs: contextlib.nullcontext(), show_message=Mock(),
                                              curses_wrapper_low_level2=lambda fn: fn(object()))
            runtime.script = SimpleNamespace(start_log=lambda: Mock())
            with (patch.dict(sys.modules, {"BTSpeak": runtime}),
                  patch("frontend.Worker", side_effect=[unit("first"), unit("second"), unit("third")]),
                  patch("frontend.capture", return_value="menu"),
                  patch("frontend.host_menu", side_effect=["restart:one-hand", "restart:two-hand", "quit"]),
                  patch.object(sys, "argv", ["blazie", "--backend", str(root / "backend"),
                                            "--firmware", tmp, "--state-dir", tmp])):
                self.assertEqual(main(), 0)
            # held while the new worker is still paused: before it ever runs
            self.assertLess(events.index(("second", "HOLDSTART 32")), events.index(("second", "RESUME")))
            self.assertLess(events.index(("third", "HOLDSTART 4")), events.index(("third", "RESUME")))
            self.assertLess(events.index(("first", "close")), events.index(("second", "HOLDSTART 32")))
            self.assertNotIn(("first", "HOLDSTART 32"), events)

    def test_one_handed_mode_is_offered_for_braille_keyboards_only(self):
        offered = {}

        def choice(choices, **kwargs):
            offered.setdefault(kind, set(choices))
            return SimpleNamespace(key="n") if kind != "tns" else None

        prefs = SimpleNamespace(quick_keys=False, double_speed=False)
        for kind in ("bl", "bns", "tns"):
            result = host_menu(Mock(), SimpleNamespace(request_choice=choice), prefs, profile=SimpleNamespace(kind=kind, factory=None))
            self.assertEqual(result, "restart:one-hand" if kind != "tns" else "resume")
        self.assertTrue({"n", "w"} <= offered["bl"] & offered["bns"])
        self.assertFalse({"n", "w"} & offered["tns"])

    def test_restart_after_failed_switch_keeps_the_active_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("backend", "BL2ENG.BNS", "bl2_2003_warm.state", "BL2SPA.BNS", "bl2spa_fresh.state"):
                (root / name).touch()
            runtime = ModuleType("BTSpeak")
            runtime.kb_client = SimpleNamespace(server_available=lambda: True)
            runtime.brl = SimpleNamespace(has_display=lambda: False, write=Mock())
            runtime.host = SimpleNamespace(push_self_voice=Mock(), pop_self_voice=Mock(), say=Mock())
            runtime.dialogs = SimpleNamespace(activity=lambda *a, **k: contextlib.nullcontext(), show_message=Mock(),
                                              curses_wrapper_low_level2=lambda fn: fn(object()))
            runtime.script = SimpleNamespace(start_log=lambda: Mock())
            def unit():
                return SimpleNamespace(braille=bytes(18), request=Mock(), close=Mock(), abort=Mock())
            with (patch.dict(sys.modules, {"BTSpeak": runtime}),
                  patch("frontend.Worker", side_effect=[unit(), OSError("bad firmware"), unit()]) as start,
                  patch("frontend.capture", return_value="menu"),
                  patch("frontend.host_menu", side_effect=["unit:bl-es", "restart", "quit"]),
                  patch.object(sys, "argv", ["blazie", "--backend", str(root / "backend"),
                                            "--firmware", tmp, "--state-dir", tmp])):
                self.assertEqual(main(), 0)
            self.assertEqual([call.args[3].name for call in start.call_args_list],
                             ["english.state", "spanish.state", "english.state"])
            self.assertEqual(Preferences.load(root / "preferences.json").unit, "bl-en")

    def test_preference_save_failure_rolls_back_quick_response(self):
        prefs = Preferences(Path("unused"))
        worker = Mock()
        with patch.object(prefs, "store", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                host_menu(worker, SimpleNamespace(request_choice=lambda *a, **k: SimpleNamespace(key="k")), prefs)
        self.assertEqual([call.args for call in worker.request.call_args_list], [("QUICK 1", "OK"), ("QUICK 0", "OK")])


if __name__ == "__main__":
    unittest.main()
