# Blazie firmware on BT Speak and BT Braille

This frontend runs the existing emulator's Braille Lite 2000, Braille 'n Speak 2000, and Type 'n Speak firmware
using the shared emulator core and SSI-263 voice.
The device's keyboard server supplies the original dot keys, before BRLTTY translates them. On older
speech-only BT Speak releases without that server, a temporary evdev/uinput bridge supplies the same raw keys. Host menus use
the installed `BTSpeak.dialogs` library. The firmware handles editing, commands, speech settings, and files.

Speech, keyboard access, and the firmware's own braille output are supported. The English Braille Lite 2000's
18 cells appear at the left of a BT Braille 20 or 40, with remaining cells blank. Routing keys are unused.

## Build and run

Run `blazie_emu`, the same command as on any other Linux machine; on a BT Speak or BT Braille it uses the device
automatically. From the repository root, with the English firmware and factory state in `firmware/blazie/`:

```sh
./build_linux.sh
./build/linux/blazie_emu
```

On the device, `blazie_emu` says "BT Speak or BT Braille detected: using its keyboard, speech and braille display."
and hands over to `blazie_emu_bt` beside it (`src/apps/blazie/bt_handover.c`), passing on `--unit`, `--firmware`,
`--config` (as `--state-dir`) and `--rate`; its terminal-only options have no equivalent here and are left behind.
The device is recognised when the system's `python3` imports the device's `BTSpeak` library and its keyboard service
answers (`kb_client.server_available()`), or the bundled frontend recognizes the older `4x3braille` keypad
and its BRLTTY services. This probe is read-only. An ordinary PC or Raspberry Pi
has no `BTSpeak` library, so `blazie_emu` stays in the terminal there. `blazie_emu --bt-probe` says what it finds.
`blazie_emu --no-bt`, or `bt = off` under `[input]` in its `blazie_emu.ini`, keeps the terminal emulator on the
device. `bt = native` keeps `blazie_emu` itself, using the device's keyboard and braille display without this
frontend or Python ([README-btspeak.md](README-btspeak.md)); it does so too when `blazie_emu_bt` is missing. If `blazie_emu_bt` or `blazie_bt` is missing beside it, `blazie_emu` says so in one line and runs in the
terminal. `./build/linux/blazie_emu_bt` can also be run directly, with the options below. The desktop app,
`blazie_emu_gtk`, never hands over: the BT devices have no desktop.

The BT frontend uses three runtime files:

- `build/linux/blazie_emu_bt`: the executable Python frontend, bundled as a zipapp by `tools/build_bt_frontend.py`.
- `build/linux/blazie_bt`: its native worker, sharing `emu_unit.c`, the firmware catalog, the MAME Z180 core, and Linux audio.
- `build/linux/blazie_files`: the upstream file tool used by the import menu.

Keep these files together. The launcher starts the worker; it does not compile it. The frontend requires Python 3.11+
and the device's installed `BTSpeak` Python package. Older dialog signatures are adapted at runtime;
menus use their own native curses wrappers where shared-screen dialogs are unavailable. The import menu is
shown only when the installed runtime supplies a native file picker.

Run from a Blazie Mode terminal on the device. Nothing is installed into or changed under `/BTSpeak` or
`/BTBraille`; no menu registration or driver configuration is needed. The native keyboard-server route
needs no service changes. The older-device fallback briefly restarts its BRLTTY instance at setup and exit.

The original `./src/platforms/btspeak/blazie` convenience launcher still works for source development,
using the same compiled worker in `build/linux`. Rebuild the normal launcher after Python edits with
`python3 tools/build_bt_frontend.py`; rerun `./build_linux.sh` after native-code changes.

The existing `tools/package_linux.sh firmware/blazie VERSION` includes both runtime files under `bin/`,
this guide as `README-blazie-bt.md`, and the packaged firmware under `share/ssi263-speech/`. The Braille 'n Speak
2000's firmware is never in that package (it ships with the emulator's own downloads only); its profiles appear
when you supply it. From an unpacked package run `./bin/blazie_emu`; after installation with the existing Linux
installer, run `blazie_emu`.
That installer also installs/configures speech-dispatcher and requires its existing system configuration;
it is not needed to run the unpacked BT application. No BT device library is bundled or replaced.
Firmware is located relative to the executable, so the build and unpacked package can run from any working
directory. `--firmware` and `--backend` override those defaults. These runtime files do not need the source tree
when distributed with the firmware folder. Objects and test programs elsewhere in `build/linux` are development
artifacts, not runtime dependencies. Saved user memory stays in the BT user directory, outside `build/`.

Optional arguments:

```sh
./build/linux/blazie_emu_bt --rate 44100
./build/linux/blazie_emu_bt --firmware /path/to/firmware --state-dir /path/to/emulator-memory
./build/linux/blazie_emu_bt --device default
```

The initial default is 22050 Hz with the automatic audio buffer (starting at 60 ms). Audio choices are remembered;
`--rate` overrides and saves the sample rate for this and later runs. Sound-device
failure is reported; it does not silently continue without a voice. Braille Lite and Braille 'n Speak require a factory state on the
first start; Type 'n Speak uses its own cold setup. An existing saved state takes precedence; a damaged state is reported instead of reset.

## Older BT Speak keyboards

The frontend prefers the existing keyboard server. If it is absent, it checks for exactly one `4x3braille`
keypad, `/dev/uinput`, and the supported active BRLTTY path, instance, and external-speech services. A server
that is installed but unavailable, a busy native connection, or an unrecognized setup does not trigger the
fallback. Setup failures are reported without silently changing input methods.

The fallback starts `blazie-bt-keyboard.service` as a temporary systemd service through passwordless `sudo`.
It briefly stops the BRLTTY instance, exclusively grabs the physical keypad, creates a virtual keypad,
and restarts BRLTTY against it. Firmware input goes to the emulator; host-menu input goes to BRLTTY.
Both directions switch only after the complete chord and its final input frame have been released.
The helper accepts only its owning frontend as a capture client. A stalled or disconnected client cannot
silently lose individual key events or block the helper's event loop.

Normal exit stops the helper. A pidfd also watches the frontend, so a frontend crash releases the keyboard.
The independent systemd `ExecStopPost` restores BRLTTY against the physical device after helper failure as
well. External speech stays running. Nothing is installed as a boot service, and sessions have no time limit.
Keep keys released during the brief handoff. If setup fails, the service journal contains the helper's error:
`journalctl -u blazie-bt-keyboard.service`. For recovery from another terminal, use
`sudo systemctl stop blazie-bt-keyboard.service`.
If recovery itself fails and the keyboard remains unavailable, restart the BT Speak using its normal
power controls. The temporary bridge does not persist across a restart, so the normal keyboard setup returns;
you do not need a working keyboard to type a recovery command.

The original six-dot firmware mapping, saved-memory paths, launcher name, language catalog, and audio
settings are shared with the native route. Linux with Python's pidfd support, systemd, uinput, and
noninteractive sudo is required for the fallback.

## Keyboard

| Physical keys | Effect |
| --- | --- |
| Dots 1–6, Space, and their chords | Sent unchanged to the original firmware |
| E-chord | Firmware Enter |
| B-chord | Firmware Backspace |
| M-chord with Dot 7: Space plus dots 1, 3, 4, and 7 | Open the host menu after all keys are released |
| Z-chord with Dot 7: Space plus dots 1, 3, 5, 6, and 7 | Save, close the emulator and terminal, and return to the host editor |
| Other combinations containing Dot 7 or Dot 8 | Ignored as a whole; never converted to a firmware command |
| The key set to pan right in Braille Settings (R3 by default) | Original Braille Lite forward bar |
| The key set to pan left in Braille Settings (R2 by default) | Original Braille Lite back bar |
| Other panel keys and all routing keys | Unassigned |

The bars follow **Braille Settings → Navigation Key Setup** for Blazie mode, so the display pans with the same keys
as everywhere else on the device: right handed, R2 back and R3 forward; left handed, L2 and L3; navigation on both
sides, L3 back and R3 forward (or the reverse); a custom layout's keys, more than one each way if it has them. The
frontend reads the key table that setup writes (`/var/lib/BTSpeak/btbraille-nav-keys.kti`, else the shipped
`/etc/xdg/brltty/btbraille-nav-keys.kti`), as `blazie_emu`'s own `bt = native` route does; a key bound to a
combination is not a bar. A device with neither table uses R2 and R3. The choice is read each time the unit resumes,
and Keyboard help names the keys.

The host menu offers, in groups: Resume and Firmware (and Send Type 'n Speak key, for that model); Save memory,
Import programs and files, Copy files to a folder, Export files to disk image and Import files from disk image; Restart
the unit, Restart in one-handed mode and Restart in two-handed mode (not for the Type 'n Speak), and Back to the
factory state; Quick key response, Double-speed upgrade installed, Audio settings and Serial port; then Keyboard help
and Save and exit -- the Windows app's Firmware and Settings menus, item for item, but for the braille display in the
window.
The normal BT dialog controls apply while in the host menu. Menus and submenus share one terminal screen,
and returning from a submenu keeps the previously selected row. Audio settings opens on Sound buffer.
Leaving the host menu with Z-chord (Escape) or Resume announces "Menu closed" before the firmware resumes.
Save memory announces "Memory saved" and returns to the menu without requiring Enter.

The keyboard introduction is shown once per saved-memory directory, with the acknowledgement stored in
`preferences.json`. Existing preferences without that flag show it once after updating. Keyboard help
remains available from the host menu.

Z-chord with Dot 7 uses the platform's existing `Tools/deep-escape`, after the emulator has saved and restored
its host context. The helper runs detached from the terminal it closes, using noninteractive sudo when needed,
just as the normal BRLTTY binding runs it as root. If the final save fails, this handoff is not performed.
The host menu's Save and exit still returns to the shell, so both ways of leaving remain available.

## Quick key response

Open the host menu with M-chord with Dot 7 and select **Quick key response: off** to turn it on; select it again
to turn it off. The choice is kept in `preferences.json` beside the unit's saved memory and restored at launch.
The default is off, preserving original timing.

This uses the existing `emu_set_quick` option from the desktop and terminal emulators. After a key, it briefly
runs the firmware CPU at eight times its usual speed until the first spoken phoneme or a bounded timeout.
Speech synthesis retains its normal timing. Quick response ends during firmware restart so held-key reset
gestures still work. The separate experimental `run_ahead` machinery is for speech rendering and is not enabled
by this menu item. The audio buffer still contributes to the delay heard at the speaker.

## Double speed and Restart the unit

**Double-speed upgrade installed: off** (in the host menu) installs the Braille Lite's double-speed chip, a $99
upgrade on the real units, so it is off by default. With it on, the firmware's own switch (the status menu, then
+ (dots 3-4-6), answered y) runs the CPU twice as fast (`emu_set_double_speed`, as on the desktop emulators). As on a
real unit, BASIC programs' tones then come out as a low rumble and a game can stop the unit; Blazie advised switching
double speed off for programs that play sounds. The choice is kept in `preferences.json`.

**Restart the unit (keeps its files)** does what switching a unit off and on does: the worker saves its memory as it
closes -- it answers even when the emulated unit has stopped -- and a new one starts from what it saved. It announces
"Unit restarted".

**Restart in one-handed mode (dot 6 held as it starts)** and **Restart in two-handed mode (dot 3)** (Leo's idea) are
the same restart with that key held from the new unit's first instant: the new worker, still paused, is sent
`HOLDSTART 32` or `HOLDSTART 4` before it runs (`emu_hold_at_start`). The firmware does the rest, as the manuals say:
it says "One-hand mode on" and keeps the mode in its memory until a two-handed restart. The BT Speak's own one-handed
setting cannot reach it: the emulator takes the raw dot keys. Not offered for the Type 'n Speak (its manual has none).

Six-dot keyboard chords accumulate until the last key is released. Keys physically held are also passed to the firmware,
so restart gestures such as holding I-chord after P-chord, L work. Automatic key-repeat does not produce
extra chords. There is no translated text input, capital-letter shortcut, or substitute for Enter or Backspace.

## Audio settings

Open **M-chord with Dot 7 → Audio settings**. Choices are kept in `preferences.json` and apply across
firmware switches and launches. Saved audio choices are preserved; preferences without a buffer setting use Automatic.
Buffer labels include their timing: Automatic starts at 60 ms and increases if needed, Medium is 100 ms, and Long is 250 ms.

| Control | Choices | Initial default |
| --- | --- | --- |
| Sound buffer | Automatic (starts at 60 ms and grows up to 250 ms if playback runs dry), Medium (100 ms), Long (250 ms) | Automatic |
| Sample rate | 11025, 16000, 22050, 32000, 44100, 48000 Hz | 22050 Hz |
| Idle sound | Silent, hiss, whine, original unit behavior | Original unit behavior |
| Keep channel open | During speech only, until firmware switches off, always | Until firmware switches off |
| Startup pop and shutdown click | On/off | On |
| 10 Hz channel tick | On/off | On |

The sample rate and buffer apply to every model. Idle sound, channel behavior, pops, and ticks are hidden for
Type 'n Speak because the shared emulator does not model those effects for it. Original idle behavior means
hiss at even firmware volume settings and whine at odd settings. Firmware speech speed, pitch, inflection,
and volume still use the firmware's own commands. Quick key response remains a separate host-menu setting.

A smaller buffer reduces additional speech latency; choose a larger one if playback breaks up. Automatic
uses the existing shared audio pacing code, starting fresh when the output device reopens. The unsupported
40 ms "short" test mode is not offered. Actual latency also depends on the sound device and system mixer.

Buffer and sound-effect choices do not restart the unit. Changing sample rate saves memory and recreates
the unit from that saved memory, as the original emulator does. The worker checks audio-device support first
without playing samples and retains the old unit if saving or creating the replacement fails. A failed
preference write restores the previous audio settings. Use **Back** or cancel to return to the host menu.

## Firmware selection

Open M-chord with Dot 7, then **Firmware**. The menu reads the same native `emu_catalog` as the desktop and terminal emulators. It lists installed, supported
firmware with a factory state, an existing saved memory, or a supported first-start recipe. A failed switch leaves the previous unit available; a successful switch
saves it before running the new unit. The choice is remembered, or override it with `--unit bl-en` etc.
As in the desktop apps' Firmware menu, the catalog's own units (the eight below) are listed first and the language
releases are under **More languages**; Escape there returns to the list. Ctrl+C on a unit, in either list, copies it to
the User Menu as the BT Speak's own menus do: it asks for the item's name (the unit's, to start with), and the new line
starts that unit (`run .../blazie_emu --unit bl-en`; with the .deb, `/usr/bin/blazie-emu-btspeak`, which finds a
user's own fetched firmware).
The switch announcement names the selected model and language.
The same nested and flat firmware-folder layouts as the original terminal emulator are accepted. Additional releases
are discovered by their image content, not their filenames, in the firmware folder or one directory below it.
Each additional release gets its own `<release-id>.state`; its first start uses the shared catalog recipe to initialize
and verify that memory. Setup runs under an activity indicator and may take longer than a normal start.
Firmware language changes the emulated unit's speech and braille, not the host menu language.

| Unit ID | Firmware | Saved memory | Braille |
| --- | --- | --- | --- |
| `bl-en` | `BL2ENG.BNS` | `english.state` | 18 cells |
| `bl-es` | `spanish/BL2SPA.BNS` | `spanish.state` | 18 cells |
| `tns-en` | `tns/TNSENG.TNS` | `tns_english.state` | None |
| `tns-es` | `tns/TNSSPA.TNS` | `tns_spanish.state` | None |
| `bns-en` | `bns2000/BS03ENG.BNS` | `bns_english.state` | None |
| `bns-sk` | `bns2000/BS2SLL.BNS` | `bns_slovak.state` | None |
| `bl-de` | `german/Lite2000.BNS` | `german.state` | 18 cells |
| `bl-it` | `italian/Lite2000.BNS` | `italian.state` | 18 cells |
| Release ID, e.g. `bl2_hu_1999_07` | Recognized language image | `<release-id>.state` | Firmware-controlled |

The original eight profiles retain their catalog filenames and saved-memory names.
Type 'n Speak starts cold if there is no saved memory. Only firmware supplied locally or in a release package appears in the menu.
The firmware controls display length: speech-only models clear the cells. The older Braille Lite 18 and
40 ROMs are rejected by the existing core; a 40-cell display decoder alone does not make those ROMs runnable.

Type 'n Speak has a QWERTY keyboard. Only for that model, six-dot computer braille is converted to QWERTY
keystrokes using the original emulator's `keys.c` and `tns_term.c`. E-chord sends Enter, B-chord Backspace,
dots 3-6 chord Escape, I-chord Tab, dots 1/4 chords Up/Down, dots 2/5 chords Left/Right. Other space chords
send Control plus the character. **Send Type 'n Speak key** in the host menu accepts names such as `ctrl-e`,
`shift-a`, `alt-x`, `f1`, and `ctrl-alt-delete`, covering combinations without a direct braille shortcut.
The panel bars are unused for this model. Host menu and deep-escape chords remain available.
This adapter never changes Braille Lite or Braille 'n Speak keyboard input.

On a new Type 'n Speak, answer each setup question with `y` (English) or `s` (Spanish), seven answers in all:
initialize files, confirm, initialize flash, confirm, initialize folders, delete file area, confirm.
Wait for the next prompt: flash initialization takes about 45 seconds of clicks; the final clear takes
about 35 seconds of silence. This is the original firmware's setup of its own fresh memory.

## Import programs and files

Open **M-chord with Dot 7 → Import programs and files**. The native BT `dialogs.request_file` picker starts in
Home. Navigate folders with the normal BT dialog keys, Enter to select a file, Backspace to go up, and Z-chord
(Escape) to cancel. You can navigate up to `/media` or `/mnt` for mounted USB storage. All file types are visible:
programs (`.bns`), BASIC (`.bas`), text (`.txt`), and braille documents (`.brl`, `.brf`), including extensionless files.

After selecting a file, choose **Import selected files**, **Add another file**, **Remove a selected file**, or
**Cancel import**. A batch can contain up to 64 files. The menu asks before replacing existing names, with No as
the default. Canceling the picker or declining replacement leaves the unit's files unchanged.

The import uses the same `blazie_files add` implementation as the other emulators: one batch, all or nothing,
with filename normalization, text line-ending conversion, protected/open-file checks, and flash-capacity checks.
The catalog supplies the filename code page. The worker must be paused and not writing flash; if it is busy,
resume the unit and try again after it finishes. A staged copy is checked and edited while the worker retains its
exclusive memory lock. The worker validates the replacement before adopting it, backs up the previous memory as
`<memory>.before-import`, and restarts the emulated unit with its audio/quick-response/double-speed settings kept.
An updated firmware bank (`.program`) is carried through the staged import too.

Use the firmware's own commands afterward: on Braille Lite, o-chord x, the program name, e-chord runs a program;
o-chord f o, the name, e-chord opens a document. No path typing or disk-image preparation is needed in the host menu.
Older BT software without `dialogs.request_file` reports that the file picker needs an update; it is not replaced
or modified by this application.

## Disk images

**Export files to disk image** and **Import files from disk image** are the Windows and desktop apps' items of the
same names, through the same `blazie_files export` and `blazie_files import` (`src/apps/blazie/blazie_files.c`).

Export saves the unit's memory, asks for a folder with the native `dialogs.request_directory` picker (starting in
Home; `/media` and `/mnt` are reachable for USB storage), and writes `<unit> files.img` there, for instance
`Braille Lite 2000 (English) files.img`: each of the unit's folders is a folder in the image (7-Zip opens it; Linux
mounts it with `mount -o loop`). An image of that name there already is replaced only when you answer yes (No is the
default). The image is written beside it first and renamed into place, so a failed export leaves no partial image.
Shown only when the installed runtime has the folder picker.

Import asks for an `.img` with the file picker, then makes the unit's files what the image holds: new files added,
changed ones rewritten, moved ones moved. Files the unit has that the image does not are deleted, so the menu first
names them and asks (No is the default; no imports nothing). It uses the same staged copy as Import programs and
files: the worker keeps its lock, checks the result before adopting it, keeps `<memory>.before-import`, and restarts
the unit. Files the unit has open or calls its own are kept and named in the report.

**Copy files to a folder** takes the unit's files out for the device itself: it saves the unit's memory, asks for a
folder with the same picker, and writes every file into `<unit> files` there (`Braille Lite 2000 (English) files`),
each of the unit's folders a folder, through `blazie_files extract --lf`. Text and braille files (`.txt`, `.doc`,
`.brl`, ...) get Linux line ends in place of the unit's lone carriage returns, so the device's editor opens them as
they read on the unit; `.brl` files stay the unit's contracted braille in braille ASCII. A compiled BASIC program,
and any other file with a NUL byte, is binary and copied exactly (`.src` files are the readable sources). A folder of
that name there already is copied into, replacing files of the same names, only when you answer yes (No is the
default). Import programs and files takes such a file back: its line ends are made the unit's again.

## Back to the factory state

**Back to the factory state (erases this unit's files)** asks first (No is the default), then does what the Windows
app does: the worker saves and closes, the unit's saved memory and any firmware update it was given
(`<memory>.program`) are deleted, and the unit starts again from its factory state -- a release's from its recipe,
a Type 'n Speak's from its cold start with the usual setup notice. It announces "Unit back to its factory state". Not
offered for a unit whose factory state is missing (one that runs only from a saved memory), since nothing could
start it again. The other units' memories are not touched.

## Serial port

**Serial port** plugs the unit's serial port into a USB serial adapter on the BT Speak (the menu lists the
`/dev/ttyUSB*` and `/dev/ttyACM*` present -- not the board's own UARTs, `ttyS*` and `ttyAMA*`, which are the device's;
the user needs the `dialout` group), into a
pseudo-terminal for a program on the device, or into nothing (the default). It is `blazie_emu`'s serial port
(`src/apps/blazie/serial_linux.c`, README-linux.md "The serial port"): the line follows what the firmware programs
-- rate, data bits, parity, DTR, RTS -- and its XON and XOFF pass through as bytes. A terminal program (`picocom`,
`minicom`) or a disk tool under DOSBox then talks to the unit.

A pseudo-terminal's other end is named when it is chosen, and linked as `serial` beside the saved memory; it is a new
one each time a unit starts (a restart, a firmware switch, a sample-rate change keep the port, but a pseudo-terminal
program must open the link again after a restart or switch). The choice is kept in `preferences.json` and used
whenever a unit starts; a device missing then leaves the unit unplugged, says so once, and keeps the setting for next
time; choosing Not connected then forgets it. One that will not open from the menu is said and the choice set back to
Not connected.

## Memory and cleanup

Memory is kept under `script.getUserSubdirectory("blazie-emulator")`, separate from the desktop
and terminal emulator's settings. Each firmware profile has its own state file; the original English
Braille Lite memory remains `english.state`. A lock prevents two instances from writing the same unit. Memory is saved
every minute while running, on an explicit save, and on exit, SIGINT, SIGTERM, SIGHUP, or loss of the frontend.
Saves use a flushed temporary file followed by replacement of the previous state, and the folder is flushed after
the replacement so it survives a power loss. As with other processes,
SIGKILL or loss of power can lose changes since the most recent save.

The worker pauses and closes audio for a host menu. Keyboard capture is released before any host dialog or
activity indicator runs. On exit the frontend restores the previous self-voice state. Killing or disconnecting
the frontend releases its keyboard socket; the worker sees pipe EOF and saves. A worker stuck in an audio
driver is terminated with a bounded timeout; this exceptional case cannot guarantee a final save.

The native worker starts paused and uses a small private stdin/stdout protocol. Commands are `RESUME`,
`PAUSE`, `KEY held chord` (decimal firmware bitmasks), `BARS down` (1 forward, 2 back, 3 both, 0 released),
`BRAILLE`, `TNS key-name`, `QUICK 0` / `QUICK 1`, `DOUBLE 0` / `DOUBLE 1`, `HOLDSTART held` (keys held as a
paused, not yet run unit starts), `SERIAL none|pty|/dev/...`, `AUDIO`,
`AUDIO rate buffer idle keep-open pop-click tick`, `SAVE`, `IMPORT_CHECK`, `IMPORT_COMMIT`, and `QUIT`.
`blazie_bt --catalog FIRMWARE_DIR` emits the shared catalog as JSON without starting a unit. A Braille Lite worker
with `-` for its factory state creates its first memory from the firmware's recognized release recipe, under the
same memory lock.

`IMPORT_CHECK` requires a paused unit with no flash write pending, then saves it (`SAVED`). The frontend uses
`<memory>.import` as a staging copy; `IMPORT_COMMIT` validates and adopts it, replying `SAVED` then `IMPORTED`.
A resume invalidates import preparation. Failed preparation or commit leaves the previous unit available.

Responses are `READY`, `RUNNING`, `PAUSED`, `OK` (for `QUICK`, `DOUBLE`, `TNS`, and audio changes), `SAVED`, `BYE`, or
`ERROR reason`. `SERIAL` answers `SERIAL none`, `SERIAL /dev/...`, or `SERIAL pty OTHER-END`, or `SERIAL_FAILED reason`
with the unit unplugged; neither ends the session. The port stays with the units an import or a sample-rate change
puts in place.
`KEY` and `BARS` have no success response. A zero chord updates only held keys. Their "Keyboard queue full" and
"Braille bar queue full" errors (keys typed faster than the unit reads them) are logged and the session continues;
every other `ERROR` ends it.
`AUDIO` queries the current options; the six-argument form changes them only while paused. Buffer is
`auto`, `medium`, or `long`; idle is 0–3; keep-open is 0–2; pop-click and tick are 0/1. A sample-rate change
can also emit `SAVED` before `OK`. The initial CLI rate accepts the same six rates as the menu.
The worker performs all unit operations on one thread, keeping its rendering independent of Python's UI.
The keyboard loop acknowledges server events before writing to the worker, using a nonblocking pipe.

## Braille display

The emulator decodes the physical display bus, rather than reading firmware RAM or translating its speech.
This preserves the firmware's own braille translation, cursor dots, and display messages. The keys that pan the
display in Braille Settings press the forward and back contacts (R3 and R2 by default; see Keyboard). The firmware still controls an 18-cell line on a BT Braille 40; extra physical cells
do not change the firmware's navigation or wrapping. BT Speak continues to work with speech alone.

The frontend polls `BRAILLE` at up to 20 Hz, with only one outstanding request. The reply is `BRAILLE ` plus
hexadecimal cell bytes (empty before the first complete latch). A complete frame is cached even when it arrives
alongside a menu command reply. Only changed frames are sent through `brl.write_dots`, padded to exactly the
device width; resuming after a host menu forces a redraw. Cursor flashing comes from the firmware's updates.

The display bus uses PPI port C bits 0, 1, and 2 for data, clock, and latch. Each byte is shifted
least-significant bit first; the clock and latch use rising edges. Cells arrive right-to-left.
The 18-cell board sends six padding bytes as three pairs. Wire bits 0 through 7 represent dots
7, 3, 2, 1, 8, 6, 5, and 4. Cursor indicators are already part of those bytes.

The bars are separate from the chord keyboard: active-low PPI port B (81h) bits 6 (forward) and
7 (back). The firmware handles messages, scrolling, direction reversal, and presses of both bars.
The native worker preserves quick taps with a 120 ms minimum contact/release interval in emulated time;
holding a button retains its contact. Both physical buttons for a direction share one contact,
so releasing one does not release the other. Pausing releases contacts and discards queued bar input.

`bl_display.h` publishes only complete, latched frames, discards partial or overlong transfers,
and ignores clock-controller activity on other PPI bits. It also decodes the 40-cell bus layout;
the supported English firmware uses the 18-cell layout, verified against its actual port traffic.

## Verification

```sh
python3 -m unittest discover -s src/platforms/btspeak -p 'test_*.py' -v
./build/linux/test_display
```

Tests cover every original dot/space/advance combination, menu press/release orders, suppression of extra dots,
keyboard acknowledgement and release, host-menu lifecycle, native save/reload, concurrent-instance exclusion,
bad states, save and audio failures, shutdown, remembered quick response, and a real firmware reset with I-chord held
while quick response is enabled. Deep-escape tests mock the platform helper and check that saving and keyboard/context
cleanup finish before it is invoked; they do not close the actual device terminal. Native tests use
temporary state directories and silent pacing; they do not capture the device keyboard. They require a built
worker and the English firmware. Actual speaker quality, physical typing, and new UI behavior need hands-on verification on each device. Display tests cover bus edges, bit order, padding, complete-frame latching, reset,
malformed transfers, raw output sizing, partial pipe reads, menu restoration, and the real firmware's file list
and help text. New language profiles still need a user's tactile check on the physical cells.

Navigation tests press and release the real emulated port contacts, verify forward/back help text,
and check overlapping left/right holds. Profile tests cover the shared catalog, legacy and release profiles, separate memories,
remembered selection, successful switching, and recovery from a failed switch. Type 'n Speak tests
exercise both installed languages, keyboard input, absent braille output, and saving.

Audio tests cover old-preference migration, every menu control, all six native sample rates, all buffer
modes, memory preservation, cancellation, device/save failures, and rollback after a preference-write failure.
Hardware listening is still needed to choose the shortest buffer that plays smoothly on a particular device.
Import tests cover picker cancellation and batch editing, replacement confirmation, failures that leave memory
unchanged, native staged commit and backup, and continued exclusion of a second worker. A new-language test
creates and reloads Hungarian memory when that firmware is supplied. Restart is also checked after a failed switch.

Disk image tests run the real `blazie_files` on the English factory state: a copy to a folder with Linux line ends
and a binary file byte for byte, a folder there already used only when allowed, export after a save, an image there
already kept unless replaced, a missing folder picker, an import that deletes asked first (declined: nothing changes),
accepted and committed, and a file that is not an image refused before anything is staged. Serial tests drive the
real worker: devices that will not open answered without ending the session, and a pseudo-terminal carrying s-chord's
XON ENQ at 19200 bit/s from a unit put in place by a sample-rate change. Frontend tests cover the bars on every
Navigation Key Setup layout (never the device's own table), the menu items offered only where they can work, the
factory reset deleting the memory and its update between the old unit closing and the new one starting, and a saved
serial port plugged in at every start. Firmware tests cover the catalog's units before More languages, Escape there
returning to the list on it, and Ctrl+C copying a unit (never More languages) to the User Menu, with the platform's
own chooser where its User Menu library is missing. `tools/btspeak_deb_test.sh` checks the User Menu from the .deb
and `install.sh`: one Blazie Emulator line, never doubled (renamed or not), the older packages' lines a unit gone,
renamed and copied ones kept until removal; and the Blazie menu itself: the catalog's units, More languages with the
releases, none without them, an item saying so when nothing is listed, and the .deb's launcher listing the Braille
Lite before any firmware is fetched.

Legacy keyboard tests cover backend selection, complete-chord handoff, exclusive capture, slow and disconnected
consumers, bounded release, concurrent-launch ownership, supervised recovery, and older dialog signatures.
These tests simulate device operations and do not restart the machine's keyboard services.

`blazie_emu`'s hand-over is tested by `src/apps/blazie/test_bt_handover.py` (in `tools/linux_tests.sh`): the
detection against a stand-in `BTSpeak` library and keyboard service, either one missing, and the test machine
itself; the options passed to a stand-in `blazie_emu_bt`; `--no-bt`, `bt = off`, no device and a missing frontend
keeping the terminal emulator. Its control (`BLAZIE_BT_BREAK=1`) must fail. On a BT device itself, run the gate
with `BLAZIE_TEST_ON_BT_DEVICE=1`, so the test machine's own detection is expected to say yes.

## Files

| File | What it does |
| --- | --- |
| `frontend.py` | The frontend: arguments, start-up checks, the capture loop (keyboard service events to the worker, braille polling), the host menu, firmware switching, deep escape, and the final save. |
| `keyboard_backend.py`, `bt_runtime.py` | Native-first keyboard selection and compatibility with older installed dialog APIs. |
| `legacy_keyboard.py` | Client connection and lifetime of the temporary keyboard service. |
| `legacy_bridge.py`, `legacy_protocol.py` | Supervised physical/virtual keypad handoff, recovery, and raw event routing. |
| `entrypoint.py` | Shared entry point for the frontend and its private supervised helper. |
| `worker.py` | The native worker's pipe protocol: start, bounded requests and replies, `BRAILLE` frames, logged queue-full warnings, close and abort. No BT UI imports. |
| `backend.c` | The native worker (`build/linux/blazie_bt`): one unit from `src/apps/blazie/emu_unit.c` with the Linux audio code, its commands on stdin, saves to a flushed temporary file renamed over the state. |
| `keymap.py` | Six-dot chords from the device's key events: held keys, the menu and deep-escape chords, dots 7 and 8 ignored. |
| `tns_keyboard.py` | Six-dot computer braille to the Type 'n Speak's key names (Type 'n Speak only). |
| `display.py` | Firmware braille frames to the device's cells, padded to its width, sent only when changed. |
| `profiles.py` | Read the native shared catalog, including discovered language releases and their saved-memory names. |
| `file_import.py` | Native file picker, batch selection, replacement confirmation, and staged imports through `blazie_files`. |
| `disk_image.py` | Copy files to a folder, Export files to disk image and Import files from disk image, through `blazie_files` (the import through the same staged copy). |
| `serial_port.py` | The Serial port menu, the worker's `SERIAL`, the pseudo-terminal's link. |
| `panning.py` | The keys that pan the display in Braille Settings, as the advance bars. |
| `firmware_menu.py` | The host menu's Firmware choice: the catalog's units, More languages, and Ctrl+C to the User Menu. |
| `blazie.menu` | The Blazie menu, a BT Speak menu made each time it opens: the units `blazie_emu --list-units` lists, the releases under More languages (the same program as `blazie-languages.menu`). |
| `user-menu-entry` | The User Menu's line opening the Blazie menu, under the menu's own lock (`install.sh`, the .deb). |
| `preferences.py` | `preferences.json` beside the saved memory: the unit, quick key response, the audio settings, the serial port. |
| `audio_options.py`, `audio_menu.py` | The audio settings and their host menu. |
| `runtime_paths.py` | The worker and firmware beside the launcher: the source tree, `build/linux`, or the package's `bin/`. |
| `blazie` | The source-tree launcher (`./src/platforms/btspeak/blazie`). |
| `test_*.py` | The unit tests (Verification above); `test_worker.py` also drives the real worker and firmware, and `test_launch.py` builds and runs the bundle. |

The bundle is made by `tools/build_bt_frontend.py`; `blazie_emu`'s hand-over to it is `src/apps/blazie/bt_handover.c`.

## Contributing

This frontend lives under `src/platforms/btspeak`, while shared firmware peripherals stay under
`src/csrc/blazie` and the shared emulator interfaces under `src/apps/blazie`. The existing Linux build,
release packager, installer/uninstaller, and test runner include the BT variant alongside the other shells.
`tools/linux_tests.sh DATA` supplies its firmware folder to the BT native tests through
`BLAZIE_TEST_FIRMWARE`; keyboard/menu/packaging tests also work without a BT runtime.

Commit source, tests, build/packaging changes, and documentation. Do not commit `build/`, firmware images,
or saved states; these are ignored.
