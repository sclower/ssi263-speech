#!/bin/sh
# check_glibc_floor.sh MAX FILE... -- every ELF FILE needs no glibc symbol version above MAX, and no C++ runtime
# from the system (libstdc++ and libgcc are linked inside: build_linux.sh's -static-libstdc++).  The release's floor
# is 2.29 (exp and pow; built in Debian 11).  readelf's version needs, so any machine's binaries can be checked on any
# other (the Pi checks the x86-64 release).  A file that is not ELF (the BT frontend's zipapp) is named and skipped; a
# missing file fails.  Exit 1 on any failure.
#
#   sh tools/check_glibc_floor.sh 2.29 build/linux/libssi263speech.so build/linux/sd_ssi263 build/linux/blazie_*
max="${1:?usage: check_glibc_floor.sh MAX FILE...}"; shift
bad=0; n=0
for f in "$@"; do
    if [ ! -f "$f" ]; then echo "FAIL  $f: missing"; bad=1; continue; fi
    if [ "$(head -c 4 "$f" | tail -c 3)" != ELF ]; then echo "skip  $f: not ELF"; continue; fi
    needs="$(readelf -V -W "$f" | sed -n 's/.*Name: \([A-Z]*_[0-9][0-9.]*\).*/\1/p')"
    hi="$(echo "$needs" | sed -n 's/^GLIBC_//p' | sort -uV | tail -n 1)"
    cxx="$(echo "$needs" | grep -c -E '^(GLIBCXX|CXXABI)_')"
    n=$((n + 1))
    if [ -z "$hi" ]; then echo "FAIL  $f: no GLIBC version needs found (readelf -V)"; bad=1
    elif [ "$(printf '%s\n%s\n' "$hi" "$max" | sort -V | tail -n 1)" != "$max" ]; then
        echo "FAIL  $f: needs GLIBC_$hi, above $max"; bad=1
    elif [ "$cxx" -ne 0 ]; then echo "FAIL  $f: needs the system's C++ runtime ($cxx versions)"; bad=1
    else echo "ok    $f: GLIBC_$hi"; fi
done
[ $n -gt 0 ] || { echo "FAIL  no ELF file checked"; bad=1; }
[ $bad -eq 0 ] && echo "GLIBC floor: $n binaries, none above $max" || echo "GLIBC floor: FAILED"
exit $bad
