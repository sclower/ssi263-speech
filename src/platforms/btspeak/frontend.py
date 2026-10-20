"""Blazie Mode host menus and direct keyboard capture for the firmware emulator."""

import argparse
import curses
from contextlib import ExitStack
import os
import select
import signal
import subprocess
import time
from dataclasses import replace
from gettext import gettext as _
from pathlib import Path
from types import ModuleType

from keymap import SPACE, ChordKeyboard
from display import BrailleOutput
from preferences import Preferences
from profiles import Profile, discover
from file_import import import_files
from disk_image import copy_files, export_image, import_image
from panning import bar_codes, describe as describe_panning, panning_keys
from serial_port import SerialPort, serial_menu
from worker import Worker, WorkerError
from tns_keyboard import key_name as tns_key_name
from audio_menu import audio_menu
from audio_options import RATES
from runtime_paths import default_paths
from keyboard_backend import select_keyboard
from bt_runtime import Dialogs, say


# the unit switched on with these keys held (chords.h bits): the Braille Lite's and Braille 'n Speaks' one-handed mode
ONE_HAND = {"one-hand": 0x20, "two-hand": 0x04}


def capture(worker: Worker, kb_client: ModuleType, display: BrailleOutput | None = None, *, tns: bool = False) -> str:
    """Return a host action after its chord is released. ACK before doing any work."""
    keys = {kb_client.BTB_DOT1 + dot: 1 << dot for dot in range(8)}
    keys[kb_client.BTB_SPACE] = SPACE
    bars = bar_codes(kb_client, panning_keys())  # the keys that pan the display in Braille Settings
    bars_held: set[int] = set()
    keyboard = ChordKeyboard(keys)
    pending_display = False
    next_display = time.monotonic()
    with kb_client.connect(kb_client.FLAG_EXCLUSIVE | kb_client.FLAG_WANT_RAW) as conn:
        while True:
            ready, _writable, _failed = select.select([conn, worker.output], [], [], 0.02 if display else 0.1)
            if conn in ready:
                event = conn.read_key()
                conn.ack_consume()
                if event.key in bars:
                    if event.state:
                        bars_held.add(event.key)
                    else:
                        bars_held.discard(event.key)
                    bars_down = 0
                    for key in bars_held:
                        bars_down |= bars[key]
                    if not tns:
                        worker.send("BARS {down}".format(down=bars_down))
                    continue
                if event.key is not None:
                    action = keyboard.feed(event.key, event.state)
                    if action is not None:
                        if tns:
                            name = tns_key_name(action.chord)
                            if name:
                                worker.send("TNS " + name)
                        else:
                            worker.send("KEY {held} {chord}".format(held=action.held, chord=action.chord))
                        if action.menu:
                            return "menu"
                        if action.deep_escape:
                            return "deep_escape"
            if worker.output in ready:
                responses = worker.receive()  # Report failures; autosaves need no announcement.
                if "BRAILLE" in responses:
                    pending_display = False
                    if display is not None:
                        display.show(worker.braille)
            # One outstanding poll at most: neither a slow device nor a slow worker can build a frame backlog.
            if display is not None and not pending_display and time.monotonic() >= next_display:
                worker.send("BRAILLE")
                pending_display = True
                next_display = time.monotonic() + 0.05


def host_menu(worker: Worker, dialogs: ModuleType, preferences: Preferences,
              units: dict[str, str] | None = None, *, stdscr: curses.window | None = None,
              profile: Profile | None = None, files_tool: Path | None = None,
              serial: SerialPort | None = None) -> str:
    """The worker is paused and the keyboard is back with BRLTTY."""
    selected_key = "r"
    kind = profile.kind if profile else "bl"
    while True:
        choices = {
            "r": _("Resume emulator"),
            "s": _("Save memory"),
            "k": _("Quick key response: {state}").format(state=_("on") if preferences.quick_keys else _("off")),
            "d": _("Double-speed upgrade installed: {state}").format(
                state=_("on") if preferences.double_speed else _("off")),
            "e": _("Restart the unit (keeps its files)"),
            "o": _("Audio settings"),
        }
        if serial is not None:
            choices["l"] = _("Serial port: {port}").format(port=serial.label())
        choices["h"] = _("Keyboard help")
        choices["q"] = _("Save and exit")
        if profile is not None and files_tool is not None and callable(getattr(dialogs, "request_file", None)):
            choices["p"] = _("Import programs and files")
            if callable(getattr(dialogs, "request_directory", None)):
                choices["c"] = _("Copy files to a folder")
                choices["x"] = _("Export files to disk image")
            choices["i"] = _("Import files from disk image")
        if units:
            choices["f"] = _("Firmware: {name}").format(name=units[preferences.unit])
        if kind == "tns":
            choices["t"] = _("Send Type 'n Speak key")
        else:
            # one-handed mode, the braille keyboard's: the unit switched on with dot 6 held (dot 3 leaves it)
            choices["n"] = _("Restart in one-handed mode (dot 6 held as it starts)")
            choices["w"] = _("Restart in two-handed mode (dot 3 held as it starts)")
        if profile is not None and (profile.kind == "tns" or profile.factory is None or profile.factory.is_file()):
            choices["b"] = _("Back to the factory state (erases this unit's files)")
        choice = dialogs.request_choice(choices, prompt=_("Blazie emulator"), default=selected_key, stdscr=stdscr)
        if choice is None or choice.key == "r":
            return "resume"
        selected_key = choice.key
        if choice.key == "q":
            return "quit"
        if choice.key == "o":
            audio_menu(worker, dialogs, preferences, stdscr=stdscr, kind=kind)
            continue
        if choice.key == "p" and profile is not None and files_tool is not None:
            import_files(worker, dialogs, profile, files_tool, stdscr=stdscr)
            continue
        if choice.key == "c" and profile is not None and files_tool is not None:
            copy_files(worker, dialogs, profile, files_tool, stdscr=stdscr)
            continue
        if choice.key == "x" and profile is not None and files_tool is not None:
            export_image(worker, dialogs, profile, files_tool, stdscr=stdscr)
            continue
        if choice.key == "i" and profile is not None and files_tool is not None:
            import_image(worker, dialogs, profile, files_tool, stdscr=stdscr)
            continue
        if choice.key == "l" and serial is not None:
            serial_menu(worker, dialogs, preferences, serial, stdscr=stdscr)
            continue
        if choice.key == "b":
            if dialogs.request_confirmation(_(
                "Put this unit back as it left the factory? Its files and settings are erased, "
                "and any firmware update it was given."
            ), default=False, stdscr=stdscr):
                return "factory"
            continue
        if choice.key == "t":
            name = dialogs.request_input(_("Key name, for example ctrl-o, alt-x, or f1"), stdscr=stdscr)
            if name:
                try:
                    if not name.isascii() or any(char.isspace() for char in name):
                        raise ValueError(_("Use a single key name, with hyphens for modifiers."))
                    worker.request("TNS " + name, "OK")
                except (ValueError, WorkerError) as exc:
                    dialogs.show_message(str(exc), stdscr=stdscr)
                    continue
                return "resume"
            continue
        if choice.key == "f" and units:
            selected = dialogs.request_choice(units, prompt=_("Choose firmware"), default=preferences.unit, stdscr=stdscr)
            if selected is not None and selected.key != preferences.unit:
                return "unit:" + selected.key
            continue
        if choice.key == "k":
            quick = not preferences.quick_keys
            worker.request("QUICK {value}".format(value=int(quick)), "OK")
            try:
                preferences.store(quick)
            except OSError:
                worker.request("QUICK {value}".format(value=int(preferences.quick_keys)), "OK")
                raise
            continue
        if choice.key == "d":
            doubled = not preferences.double_speed
            worker.request("DOUBLE {value}".format(value=int(doubled)), "OK")
            try:
                preferences.store(preferences.quick_keys, double_speed=doubled)
            except OSError:
                worker.request("DOUBLE {value}".format(value=int(preferences.double_speed)), "OK")
                raise
            if doubled:
                dialogs.show_message(_(
                    "The double-speed upgrade is installed. To use it, switch it on in the unit: the status menu,\n"
                    "then + (dots 3-4-6), answered y.\n"
                    "As on a real unit, programs that play sounds can misbehave with it on: their tones can come out\n"
                    "as a low rumble, and a game can stop the unit. Blazie's advice was to switch double speed off\n"
                    "for them. Restart the unit, in this menu, starts a stopped unit again."
                ), stdscr=stdscr)
            continue
        if choice.key == "e":
            return "restart"
        if choice.key in ("n", "w") and kind != "tns":
            return "restart:" + ("one-hand" if choice.key == "n" else "two-hand")
        if choice.key == "s":
            with dialogs.activity(_("Saving memory"), stdscr=stdscr):
                worker.request("SAVE", "SAVED")
            dialogs.show_message(_("Memory saved."), wait=False, wait_for_speech=True, stdscr=stdscr)
        elif choice.key == "h":
            if kind == "tns":
                dialogs.show_message(_(
                    "Type 'n Speak has a QWERTY keyboard and no braille display.\n"
                    "Use six-dot computer braille to type. E-chord is Enter, B-chord is Backspace,\n"
                    "dots 3-6 chord is Escape, I-chord is Tab, dots 1/4 chords are Up/Down,\n"
                    "dots 2/5 chords are Left/Right. Other space chords send Control plus the character.\n"
                    "Use Send Type 'n Speak key for function keys, Shift, Alt, and other combinations.\n"
                    "M-chord with Dot 7 opens this menu; Z-chord with Dot 7 saves and closes the terminal."
                ), stdscr=stdscr)
                continue
            display_help = (describe_panning(panning_keys()) + _("Routing keys are unused.\n")
                            if kind == "bl" else
                            _("Braille 'n Speak has no braille display or advance bars.\n"))
            dialogs.show_message(_(
                "The original firmware handles dots 1 through 6 and Space.\n"
                "Use E-chord for Enter and B-chord for Backspace.\n"
                "M-chord with Dot 7 opens this host menu: Space plus dots 1, 3, 4, and 7.\n"
                "Z-chord with Dot 7 saves and exits to the host editor, closing the terminal too.\n"
                "Other combinations with dots 7 or 8 do nothing in the emulator.\n"
                "{display_help}"
                "Memory is saved every minute and on exit.\n"
                "Quick key response reduces the delay before speech by speeding up firmware processing.\n"
                "It is optional, remembered between runs, and off by default for original timing.\n"
                "Restart the unit switches it off and on, its files kept, for a unit that has stopped answering.\n"
                "Restart in one-handed mode does the same with dot 6 held, as the unit's own manual says;\n"
                "two-handed mode, with dot 3, leaves it. The unit remembers it until then.\n"
                "Back to the factory state erases this unit's files and settings, as a new unit has.\n"
                "Choose Firmware to switch units; each keeps its own saved memory.\n"
                "Braille follows the selected firmware; unused cells are blank."
            ).format(display_help=display_help), stdscr=stdscr)


def menu_session(worker: Worker, dialogs: ModuleType, preferences: Preferences, units: dict[str, str], *,
                 profile: Profile | None = None, files_tool: Path | None = None,
                 serial: SerialPort | None = None) -> str:
    """Keep one terminal screen across host menus; return it before capturing firmware keys."""
    if not getattr(dialogs, "shared_screen", True):
        return host_menu(worker, dialogs, preferences, units, profile=profile, files_tool=files_tool, serial=serial)
    result = "resume"
    error: Exception | None = None

    def run(window: curses.window) -> None:
        nonlocal result, error
        try:
            result = host_menu(worker, dialogs, preferences, units, stdscr=window, profile=profile, files_tool=files_tool,
                               serial=serial)
        except Exception as exc:
            # The platform wrapper reports and swallows exceptions. Let main report worker/save
            # failures after the wrapper has restored the terminal instead.
            error = exc

    dialogs.curses_wrapper_low_level2(run)
    if error is not None:
        raise error
    return result


def show_intro(dialogs: ModuleType, preferences: Preferences) -> None:
    """Remember the keyboard introduction only after it has been shown successfully."""
    if not preferences.intro_shown:
        dialogs.show_message(_(
            "Use the original six-dot chords. M-chord with Dot 7 opens the emulator menu."
        ))
        preferences.store(preferences.quick_keys, intro_shown=True)


def deep_escape(host: ModuleType) -> None:
    """Use the platform's normal deep escape, after saving and releasing all app resources.

    Detached from this terminal so the helper survives its own terminal cleanup. No inherited
    pipes: the platform may terminate this frontend before its helper finishes switching VTs.
    """
    command = [str(host.repository_path / "Tools" / "deep-escape")]
    if os.geteuid() != 0:
        command = ["sudo", "-n", *command]
    subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   start_new_session=True, check=True, timeout=15)


def main() -> int:
    backend_path, firmware_path = default_paths()
    parser = argparse.ArgumentParser(description=_("Original Blazie firmware in Blazie Mode."))
    parser.add_argument("--firmware", type=Path, default=firmware_path,
                        help=_("Folder containing firmware and factory states"))
    parser.add_argument("--unit", help=_("Firmware to run; defaults to the last selected unit"))
    parser.add_argument("--state-dir", type=Path, help=_("Separate folder for the emulated unit's memory"))
    parser.add_argument("--backend", type=Path, default=backend_path)
    parser.add_argument("--device", default="default", help=_("ALSA output device"))
    parser.add_argument("--rate", type=int, choices=RATES, help=_("Sample rate; defaults to the saved audio setting"))
    args = parser.parse_args()

    # Deferred so --help works even on a development machine without the BT runtime.
    import BTSpeak
    from BTSpeak import brl, dialogs, host, script
    dialogs = Dialogs(dialogs, host)

    log = script.start_log()
    worker = None
    keyboard_session = ExitStack()
    result = 0
    exit_to_editor = False

    def interrupted(signum: int, frame: object) -> None:
        raise KeyboardInterrupt

    old_handlers = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGTERM, signal.SIGHUP)}
    host.push_self_voice(True)
    try:
        if not args.backend.is_file():
            raise WorkerError(_("Build the emulator first by running ./build_linux.sh in the repository."))
        kb_client = keyboard_session.enter_context(select_keyboard(BTSpeak))
        state_dir = args.state_dir or Path(script.getUserSubdirectory("blazie-emulator"))
        state_dir.mkdir(parents=True, exist_ok=True)
        preferences = Preferences.load(state_dir / "preferences.json")
        if args.rate is not None:
            preferences.audio = replace(preferences.audio, rate=args.rate)
        with dialogs.activity(_("Finding installed firmware")):
            profiles = discover(args.backend, args.firmware)
        selected = args.unit or preferences.unit
        units = {profile.key: profile.label for profile in profiles.values() if profile.available(args.firmware, state_dir)}
        if selected not in units:
            name = profiles[selected].label if selected in profiles else selected
            raise WorkerError(_("Firmware or factory state is missing for {name}.").format(name=name))

        serial = SerialPort(state_dir / "serial")

        def start_unit(key: str) -> Worker:
            profile = profiles[key]
            paths = profile.paths(args.firmware, state_dir)
            candidate = Worker(args.backend.resolve(), *paths, args.device, preferences.audio.rate, kind=profile.kind)
            try:
                candidate.request("QUICK {value}".format(value=int(preferences.quick_keys)), "OK")
                candidate.request("DOUBLE {value}".format(value=int(preferences.double_speed)), "OK")
                candidate.request(preferences.audio.command(), "OK")
            except BaseException:
                candidate.abort()
                raise
            return candidate

        def plug_serial(current: Worker) -> None:
            """The port chosen last time, into the unit now running (the one before it closed: a port is one unit's).
            One not there now leaves the unit unplugged and is said; the setting is kept for next time."""
            if preferences.serial != "none":
                problem = serial.plug(current, preferences.serial)
                if problem:
                    dialogs.show_message(_("The serial port {port} is not connected: {error}").format(
                        port=preferences.serial, error=problem))

        def first_start_notice(key: str) -> None:
            profile = profiles[key]
            if profile.kind == "tns" and not (state_dir / profile.saved).exists():
                dialogs.show_message(_(
                    "New Type 'n Speak. Answer y to each setup question, or s for Spanish, seven times in all.\n"
                    "Initialize file system, are you sure, initialize flash, are you sure; then about 45 seconds\n"
                    "of clicks. Initialize folders, delete all data in file area, are you sure; then about\n"
                    "35 seconds of silence. Wait for each question. This initializes this new unit's memory."
                ))

        initial_profile = profiles[selected]
        if initial_profile.factory is None and initial_profile.kind != "tns" and not (state_dir / initial_profile.saved).exists():
            dialogs.show_message(_("Setting up this firmware for its first start. This may take a little while."), wait=False)
        with dialogs.activity(_("Starting Blazie emulator")):
            worker = start_unit(selected)
            preferences.store(preferences.quick_keys, unit=selected)
        first_start_notice(selected)
        plug_serial(worker)
        show_intro(dialogs, preferences)
        display = BrailleOutput(brl)
        while True:
            worker.request("RESUME", "RUNNING")
            worker.request("BRAILLE", "BRAILLE")
            display.show(worker.braille, force=True)
            try:
                action = capture(worker, kb_client, display, tns=profiles[preferences.unit].kind == "tns")
            finally:
                # capture has already closed its exclusive connection; dialogs may now acquire it.
                worker.request("PAUSE", "PAUSED")
            if action == "deep_escape":
                exit_to_editor = True
                break
            action = menu_session(worker, dialogs, preferences, units, profile=profiles[preferences.unit],
                                  files_tool=args.backend.resolve().with_name("blazie_files"), serial=serial)
            if action == "resume":
                say(host, _("Menu closed"))
            if action == "quit":
                break
            if action == "restart" or action.startswith("restart:"):
                # As switching the unit off and on: the worker saves its memory as it closes (the emulated unit may
                # have stopped answering, the worker never does), and a new one starts from what it saved -- with
                # dot 6 (one-handed) or dot 3 (two-handed) held from its first instant, while it is still paused.
                with dialogs.activity(_("Restarting the unit")):
                    worker.close()
                    worker = None
                    worker = start_unit(preferences.unit)
                    if action != "restart":
                        worker.request("HOLDSTART {keys}".format(keys=ONE_HAND[action[8:]]), "OK")
                plug_serial(worker)
                say(host, _("Unit restarted"))
                continue
            if action == "factory":
                # As the Windows app's: the unit switched off (its memory saved, as always), that memory and any
                # firmware update it was given deleted, and the unit switched on from its factory state
                profile = profiles[preferences.unit]
                if profile.factory is None and profile.kind != "tns":
                    dialogs.show_message(_("Setting up this firmware for its first start. This may take a little while."),
                                         wait=False)
                with dialogs.activity(_("Returning the unit to its factory state")):
                    saved = worker.saved
                    worker.close()
                    worker = None
                    saved.unlink(missing_ok=True)
                    Path(str(saved) + ".program").unlink(missing_ok=True)
                    worker = start_unit(preferences.unit)
                first_start_notice(preferences.unit)
                plug_serial(worker)
                say(host, _("Unit back to its factory state"))
                continue
            if action.startswith("unit:"):
                requested = action[5:]
                try:
                    with dialogs.activity(_("Switching to {name}").format(name=profiles[requested].label)):
                        candidate = start_unit(requested)
                except (OSError, WorkerError) as exc:
                    dialogs.show_message(_("Could not switch firmware: {error}").format(error=exc))
                    continue  # The previous unit is still paused, with its memory intact.
                try:
                    worker.close()
                except BaseException:
                    candidate.abort()
                    raise
                worker = candidate
                selected = requested
                preferences.store(preferences.quick_keys, unit=selected)
                first_start_notice(selected)
                plug_serial(worker)
    except KeyboardInterrupt:
        pass
    except (OSError, EOFError, ValueError, WorkerError, subprocess.SubprocessError) as exc:
        log.exception("Blazie emulator failed")
        dialogs.show_message(_("Emulator error: {error}").format(error=exc))
        result = 1
    finally:
        try:
            if worker is not None:
                try:
                    with dialogs.activity(_("Saving emulator memory")):
                        worker.close()
                except (OSError, WorkerError) as exc:
                    log.exception("Blazie emulator could not close cleanly")
                    dialogs.show_message(_("Could not finish saving: {error}").format(error=exc))
                    result = 1
                finally:
                    worker.abort()
        finally:
            try:
                try:
                    keyboard_session.close()
                except (OSError, subprocess.SubprocessError) as exc:
                    log.exception("Legacy keyboard cleanup failed")
                    dialogs.show_message(_("Could not restore keyboard access: {error}").format(error=exc))
                    result = 1
                brl.write("")
            finally:
                try:
                    host.pop_self_voice()
                finally:
                    for sig, handler in old_handlers.items():
                        signal.signal(sig, handler)
    if exit_to_editor and result == 0:
        try:
            deep_escape(host)
        except (OSError, subprocess.SubprocessError) as exc:
            log.exception("Host deep escape failed")
            dialogs.show_message(_("Emulator saved, but could not return to the editor: {error}").format(error=exc))
            result = 1
    return result
