#!/bin/sh
# Install the Blazie emulator (blazie_emu) on a BT Speak or BT Braille -- from the unpacked Linux release package
# (where it is install-btspeak.sh, beside bin/ and share/), or from this source tree after ./build_linux.sh: the
# program and blazie_files into PREFIX/bin, the firmware into PREFIX/share/ssi263-speech (where blazie_emu looks
# beside itself), and -- with --menu -- the units in the BT Speak's user menu.  README-btspeak.md says the rest.
#
#   ./install-btspeak.sh [--menu] [FIRMWARE_DIR]                  (the package)
#   src/platforms/btspeak/install.sh [--menu] [FIRMWARE_DIR]      (the source tree)
#
#   PREFIX        where to install: ~/.local by default, which needs no root (the menu entries name the program by
#                 its full path, so it need not be on the PATH); PREFIX=/usr/local with sudo for every user
#   FIRMWARE_DIR  the Blazie firmware, laid out as the repository's firmware/blazie (BL2ENG.BNS and its state,
#                 spanish/, tns/, bns2000/) or all in one folder -- or a release's blazie-emu-*.tar.gz, as downloaded
#                 (its share/ssi263-speech is used); default: the package's share/ssi263-speech, or the source tree's
#                 firmware/blazie
#   --menu        ~/BTSpeak/user.menu lists each unit the installed firmware can start (blazie_emu --list-units), a
#                 line each: a unit listed already is left alone, and one of these lines whose firmware is not there
#                 any more goes (user-menu-units)
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
if [ -x "$HERE/bin/blazie_emu" ]; then         # the unpacked package
    BIN="$HERE/bin"; DEF_FW="$HERE/share/ssi263-speech"; DOCS="$HERE"
else                                           # the source tree
    ROOT="$(cd "$HERE/../../.." && pwd)"
    BIN="$ROOT/build/linux"; DEF_FW="$ROOT/firmware/blazie"; DOCS=""
fi
PREFIX="${PREFIX:-$HOME/.local}"
MENU=0
FW=""
for a in "$@"; do
    case "$a" in
        --menu) MENU=1 ;;
        -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
        *) FW="$a" ;;
    esac
done
FW="${FW:-$DEF_FW}"
case "$FW" in
    *.tar.gz|*.tgz)                            # a release download: its firmware, unpacked for the copy below
        TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
        tar -xzf "$FW" -C "$TMP" --wildcards '*/share/ssi263-speech/*' \
            || { echo "no firmware in $FW"; exit 1; }
        FW="$(dirname "$(find "$TMP" -name BL2ENG.BNS | head -n 1)")" ;;
esac

[ -x "$BIN/blazie_emu" ] || { echo "no $BIN/blazie_emu: build it first (./build_linux.sh)"; exit 1; }
[ -f "$FW/BL2ENG.BNS" ] || { echo "no Braille Lite firmware in $FW (BL2ENG.BNS: firmware/blazie/README.txt)"; exit 1; }
if [ ! -e /run/BTSpeak/keyboard-socket ] && [ ! -d /BTSpeak ]; then
    echo "note: this is not a BT Speak or BT Braille (no keyboard server); installing all the same"
fi

mkdir -p "$PREFIX/bin" "$PREFIX/share/ssi263-speech"
cp "$BIN/blazie_emu" "$PREFIX/bin/"
[ -x "$BIN/blazie_files" ] && cp "$BIN/blazie_files" "$PREFIX/bin/"
# the BT front end (#4: the device's own dialogs), which blazie_emu hands over to when it is beside it
if [ -x "$BIN/blazie_emu_bt" ] && [ -x "$BIN/blazie_bt" ]; then
    cp "$BIN/blazie_emu_bt" "$BIN/blazie_bt" "$PREFIX/bin/"
fi
# the firmware, as it is laid out (blazie_emu reads either layout); README.txt is the repository's own notes
(cd "$FW" && find . -type f \( -iname '*.BNS' -o -iname '*.TNS' -o -name '*.state' \)) | while read -r f; do
    mkdir -p "$PREFIX/share/ssi263-speech/$(dirname "$f")"
    cp "$FW/$f" "$PREFIX/share/ssi263-speech/$f"
done
if [ -n "$DOCS" ]; then
    cp "$DOCS/README-blazie-emu.md" "$DOCS/README-btspeak.md" "$PREFIX/share/ssi263-speech/"
else
    cp "$ROOT/src/apps/blazie/README-linux.md" "$PREFIX/share/ssi263-speech/README-blazie-emu.md"
    cp "$ROOT/src/platforms/btspeak/README-btspeak.md" "$PREFIX/share/ssi263-speech/README-btspeak.md"
fi
echo "installed $PREFIX/bin/blazie_emu, its firmware in $PREFIX/share/ssi263-speech"

if [ "$MENU" = 1 ]; then
    mkdir -p "$HOME/BTSpeak"
    "$PREFIX/bin/blazie_emu" --list-units --firmware "$PREFIX/share/ssi263-speech" \
        | "$HERE/user-menu-units" "$HOME/BTSpeak/user.menu" "run $PREFIX/bin/blazie_emu --unit" 2>&1
fi
