#!/bin/sh
# Remove what install.sh put in PREFIX (~/.local by default) and its lines in ~/BTSpeak/user.menu (the Blazie menu's,
# and any unit copied from it).  The units' memory
# and settings (~/.config/ssi263-speech/blazie-emu) are kept: delete that folder too to forget them.
set -e
PREFIX="${PREFIX:-$HOME/.local}"
rm -f "$PREFIX/bin/blazie_emu" "$PREFIX/bin/blazie_files" "$PREFIX/bin/blazie_emu_bt" "$PREFIX/bin/blazie_bt"
rm -rf "$PREFIX/share/ssi263-speech" "$PREFIX/lib/blazie-emu"
UM="$HOME/BTSpeak/user.menu"
RUN="run $PREFIX/bin/blazie_emu --unit "
OPEN=": menu $PREFIX/lib/blazie-emu/blazie"
if [ -f "$UM" ] && grep -q -F -e "$RUN" -e "$OPEN" "$UM"; then
    grep -v -F -e "$RUN" -e "$OPEN" "$UM" > "$UM.new" && mv "$UM.new" "$UM"
    echo "user menu: the emulator's lines removed"
fi
echo "removed the Blazie emulator from $PREFIX"
