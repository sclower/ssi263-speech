#!/bin/sh
# A .deb of the Blazie emulator for the BT Speak and BT Braille: installed with apt, it fetches the firmware from the
# project's own release and adds the units to the User Menu; removing it takes both away again.  No firmware is
# inside the .deb (the project's releases are the only place it is published from): fetch-firmware takes it from the
# pinned release, else from the latest one by its SHA256SUMS.txt.
#
#   ./build_linux.sh && src/platforms/btspeak/deb/build_deb.sh [version]
#   Output: build/blazie-emu-btspeak_<version>_arm64.deb
#
# A preview hosted elsewhere (Tomi's eurpod.com/synths for 0.8's): BTE_PIN_URL and BTE_PIN_SHA, both or neither, are
# the pinned download and its SHA-256 written into this package's fetch-firmware in place of the release's; the
# latest-release fallback stays the project's.
#   BTE_PIN_URL=https://eurpod.com/synths/blazie-emu-0.8.0-preview1-linux-aarch64.tar.gz BTE_PIN_SHA=<sha256> \
#       src/platforms/btspeak/deb/build_deb.sh 0.8.0~preview1
set -e
ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
HERE="$ROOT/src/platforms/btspeak/deb"
VERSION="${1:-0.7.0+btspeak1}"
ARCH="$(dpkg --print-architecture)"
STAGE="$ROOT/build/deb/blazie-emu-btspeak"
[ -x "$ROOT/build/linux/blazie_emu" ] || { echo "build it first: ./build_linux.sh"; exit 1; }
rm -rf "$STAGE"
LIB="$STAGE/usr/lib/blazie-emu-btspeak"
DOC="$STAGE/usr/share/doc/blazie-emu-btspeak"
mkdir -p "$LIB/bin" "$STAGE/usr/bin" "$DOC" "$STAGE/DEBIAN"
install -m 755 "$ROOT/build/linux/blazie_emu" "$ROOT/build/linux/blazie_files" "$LIB/bin/"
# the BT front end (#4: the device's own dialogs), which blazie_emu hands over to; without it, blazie_emu's own route
[ -x "$ROOT/build/linux/blazie_emu_bt" ] && [ -x "$ROOT/build/linux/blazie_bt" ] \
    || { echo "no build/linux/blazie_emu_bt and blazie_bt: build them first (./build_linux.sh)"; exit 1; }
install -m 755 "$ROOT/build/linux/blazie_emu_bt" "$ROOT/build/linux/blazie_bt" "$LIB/bin/"
install -m 755 "$HERE/fetch-firmware" "$ROOT/src/platforms/btspeak/user-menu-units" "$LIB/"
if [ -n "${BTE_PIN_URL:-}${BTE_PIN_SHA:-}" ]; then
    case "${BTE_PIN_URL:-}" in https://*) ;; *) echo "BTE_PIN_URL must be an https:// URL"; exit 1 ;; esac
    echo "${BTE_PIN_SHA:-}" | grep -q -x -E '[0-9a-f]{64}' || { echo "BTE_PIN_SHA must be a SHA-256 (64 hex digits)"; exit 1; }
    sed -i -e "s|^URL=https://.*\$|URL=$BTE_PIN_URL|" -e "s|^SHA=[0-9a-f]*\$|SHA=$BTE_PIN_SHA|" "$LIB/fetch-firmware"
    grep -q -x "URL=$BTE_PIN_URL" "$LIB/fetch-firmware" && grep -q -x "SHA=$BTE_PIN_SHA" "$LIB/fetch-firmware" \
        || { echo "the pin was not written into fetch-firmware"; exit 1; }
    echo "pinned download: $BTE_PIN_URL ($BTE_PIN_SHA)"
fi
install -m 755 "$HERE/blazie-emu-btspeak" "$STAGE/usr/bin/"
ln -s ../lib/blazie-emu-btspeak/bin/blazie_files "$STAGE/usr/bin/blazie_files"
install -m 644 "$ROOT/src/platforms/btspeak/README-btspeak.md" "$DOC/README-btspeak.md"
install -m 644 "$ROOT/src/apps/blazie/README-linux.md" "$DOC/README-blazie-emu.md"
install -m 644 "$ROOT/src/platforms/btspeak/README.md" "$DOC/README-blazie-bt.md"
install -m 644 "$ROOT/LICENSE" "$DOC/LICENSE"
install -m 644 "$ROOT/src/csrc/cpu/mame_z180/LICENSE-BSD-3-Clause.txt" "$DOC/MAME-Z180-core-BSD-3-Clause.txt"
install -m 644 "$ROOT/third_party/casso/LICENSE" "$DOC/Casso-MIT.txt"
install -m 755 "$HERE/postinst" "$HERE/prerm" "$HERE/postrm" "$STAGE/DEBIAN/"
cat > "$STAGE/DEBIAN/control" <<EOF
Package: blazie-emu-btspeak
Version: $VERSION
Architecture: $ARCH
Maintainer: Stephen Clower <steve@steve-audio.net>
Depends: libc6 (>= 2.34), libasound2, python3 (>= 3.11), curl, ca-certificates
Recommends: libbrlapi0.8
Section: misc
Priority: optional
Installed-Size: $(du -sk "$STAGE/usr" | cut -f1)
Description: Blazie Braille Lite 2000, Braille 'n Speak 2000 and Type 'n Speak emulator for the BT Speak
 The original Blazie firmware on an emulated SSI-263 voice, played with the BT Speak's own
 braille keys, with the device's own dialogs for its menu; on a BT Braille the Braille Lite's
 display appears on the BT Braille's display and its L2/R2 and L3/R3 keys are the advance bars.  Installing fetches the firmware from
 the ssi263-speech project's release and adds the units to the User Menu; removing takes
 both away.  M-chord with dot 7 opens the emulator's menu; Z-chord with dot 7 saves and
 quits.
EOF
if find "$STAGE" -iname '*.BNS' -o -iname '*.TNS' -o -name '*.state' | grep -q .; then
    echo "firmware found in the package: not made"; exit 1
fi
mkdir -p "$ROOT/build"
dpkg-deb --root-owner-group --build "$STAGE" "$ROOT/build/blazie-emu-btspeak_${VERSION}_${ARCH}.deb"
