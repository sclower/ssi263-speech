"""The SSI-263's latch race (bl_board.h BL_LATCH_RACE_US): at double speed the BASIC runtime writes a note's
registers 1.46 and 2.12 us apart, and the chip's R4 catches R0's 37 -- the rumble of BASIC's tones on Tomi's double-
speed Braille Lite (2026-10-16).  The English Braille Lite 2000 from its warm state:

    python test_latch_race.py [--firmware DIR] [--lib PATH] [--files PATH]

  speech    with double speed on, the firmware's own speech (letters typed, a line read) writes exactly the same with
            the race on and off
  params    the speech parameters at double speed (on the 640 too, when bns640/june2003/ has its BSPENG.BNS and
            bspeng_fresh.state): no key's answer left holding a phoneme, nothing caught.  Every utterance ends PA
            into R0, then R1, 1.953 us apart; caught, R0 kept R1's value and the chip held it as a vowel until a key
            (issue #25)
  tones     a BASIC program (below, run with Blazie's run.bns) playing 80 notes at double speed: writes caught, and
            some notes' R4 holding 37
  base      the same program at the base clock: nothing caught, no R4 of 37
The tone checks need run.bns (Blazie's BASIC runtime, from its 1995 BASIC disk) in the firmware folder's games/
(never in the repo; absent, they are skipped) and blazie_files (the emulator's file tool) to put it and the program
into a state.

Controls: SSI263_LATCH_RACE_BREAK=1, the latch time 1 us, below the closest writes -- nothing is caught, and "tones"
must fail; SSI263_LATCH_RACE_BREAK=wide, the 2.15 us latch before issue #25 -- "params" must fail.
"""
import argparse
import ctypes
import os
import shutil
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
WINDOWS = sys.platform == "win32"
BREAK = os.environ.get("SSI263_LATCH_RACE_BREAK") == "1"
WIDE = os.environ.get("SSI263_LATCH_RACE_BREAK") == "wide"
RATE = 22050
SPACE = 0x40
STATUS, PLUS, YES, EXIT = 0x0C | SPACE, 0x2C, 0x3D, 0x11 | SPACE
LETTERS = (0x13, 0x11, 0x07, 0x07, 0x15)            # h e l l o
READ_LINE = 0x09 | SPACE
# the speech parameters (345-chord), dots 1 / 4 (softer, louder) and 3 / 6 (lower, higher), e-chord to leave
PARAMS_WALK = [0x1C | SPACE] + [0x01, 0x08, 0x04, 0x20] * 3 + [0x11 | SPACE]
PARAMS_STARTS = (0.0, 0.37)                         # two phases of the board's clock against the latch's
WIDE_NS = 2150                                      # the latch time before issue #25 (dbf590b)
# td.bas, compiled from this source with Blazie's COMPILE.BNS (on the emulated unit):
#   10 print "d" / 20 for i = 1 to 20 / 30 for n = 1 to 4 / 40 sound 300 + 100 * n, 1 / 50 next n / 70 next i /
#   80 print "done" / 90 end
TD_BAS = bytes.fromhex(
    "000a00090101032264220014000c0b016901310c023230001e000b0b016e01310c0134002800112b02093330302b3130302a6e013100"
    "3200070e01016e004600070e0101690050000c01010622646f6e6522005a000415")
# o-chord x, run.bns, e-chord; then td.bas, e-chord (computer braille)
RUN_TD = [0x55, 2.0, 0x2D, 0x17, 0x25, 0x1D, 0x28, 0x03, 0x1D, 0x0E, 0x51, 9.0,
          0x1E, 0x19, 0x28, 0x03, 0x01, 0x0E, 0x51]


class W(ctypes.Structure):
    _fields_ = [("t", ctypes.c_double), ("reg", ctypes.c_int), ("val", ctypes.c_int)]


def load(path):
    lib = ctypes.CDLL(path)
    lib.ssi263_new.restype = ctypes.c_void_p
    lib.ssi263_new.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_double]
    lib.ssi263_default_rom.restype = ctypes.c_void_p
    lib.ssi263_free.argtypes = [ctypes.c_void_p]
    lib.bh_create.restype = ctypes.c_void_p
    lib.bh_create.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_double, ctypes.c_double,
                              ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_ulonglong, ctypes.c_int,
                              ctypes.c_char_p, ctypes.c_int]
    lib.bh_destroy.argtypes = [ctypes.c_void_p]
    lib.bh_run.argtypes = [ctypes.c_void_p, ctypes.c_double, ctypes.c_double,
                           ctypes.POINTER(ctypes.POINTER(ctypes.c_double))]
    lib.bh_get_int.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    lib.bh_set_int.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    lib.bh_key.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.bh_writes.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.POINTER(W))]
    lib.bh_clear_writes.argtypes = [ctypes.c_void_p]
    lib.ssi263_reg.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.ssi263_time.restype = ctypes.c_double
    lib.ssi263_time.argtypes = [ctypes.c_void_p]
    return lib


class Unit:
    def __init__(self, lib, fw, st, double, latch_ns=None):
        self.lib = lib
        params = ctypes.create_string_buffer(lib.ssi263_params_size())
        lib.ssi263_default_params(params)
        self.chip = lib.ssi263_new(params, lib.ssi263_default_rom(), float(RATE))
        err = ctypes.create_string_buffer(300)
        self.h = lib.bh_create(fw.encode(), st.encode(), self.chip, float(RATE), 5000.0, None, None, 0, 0, 1, err, 300)
        if not self.h:
            sys.exit("host: " + err.value.decode(errors="replace"))
        lib.bh_set_int(self.h, b"double_speed", double)
        if latch_ns is not None:
            lib.bh_set_int(self.h, b"latch_race_ns", latch_ns)
        self.y = ctypes.POINTER(ctypes.c_double)()
        self.writes = []

    def listen(self, s):
        self.lib.bh_run(self.h, s, 0.0005, ctypes.byref(self.y))
        wp = ctypes.POINTER(W)()
        n = self.lib.bh_writes(self.h, ctypes.byref(wp))
        self.writes += [(round(wp[i].t, 9), wp[i].reg, wp[i].val) for i in range(n)]
        self.lib.bh_clear_writes(self.h)

    def keys(self, seq, gap=0.25):
        for k in seq:
            if isinstance(k, float):
                self.listen(k)
            else:
                self.lib.bh_key(self.h, k)
                self.listen(gap)

    def double_on(self):
        for key, secs in ((STATUS, 3.5), (PLUS, 3.0), (YES, 2.5), (EXIT, 1.5)):
            self.lib.bh_key(self.h, key)
            self.listen(secs)

    def close(self):
        catches = self.lib.bh_get_int(self.h, b"latch_catches")
        self.lib.bh_destroy(self.h)
        self.lib.ssi263_free(self.chip)
        return catches


def speech_writes(lib, fw, st, latch_ns):
    u = Unit(lib, fw, st, 1, latch_ns)
    u.listen(12.0)
    u.double_on()
    u.writes.clear()
    u.keys(LETTERS, 1.2)
    u.keys([READ_LINE], 3.0)
    return u.writes, u.close()


def params_walk(lib, fw, st, start, latch_ns):
    """the speech-parameter keys at double speed: (keys whose answer was left holding a phoneme, writes caught).  Held:
    the chip on (R3 bit 7 clear) with a phoneme, not PA, in R0 and nothing written for 0.8 s -- what issue #25 heard:
    every utterance ends PA into R0, then R1, 1.95 us apart, and a caught R0 keeps R1's value as a vowel"""
    u = Unit(lib, fw, st, 1, latch_ns)
    u.listen(12.0 + start)
    u.double_on()
    c0 = lib.bh_get_int(u.h, b"latch_catches")
    held = 0
    for k in PARAMS_WALK:
        lib.bh_key(u.h, k)
        u.listen(1.5)
        quiet = not u.writes or lib.ssi263_time(u.chip) - u.writes[-1][0] > 0.8
        held += bool(quiet and lib.ssi263_reg(u.chip, 0) & 0x3F and not lib.ssi263_reg(u.chip, 3) & 0x80)
    caught = lib.bh_get_int(u.h, b"latch_catches") - c0
    u.close()
    return held, caught


def td_state(files, fw_dir, st, run_bns, tmp):
    """the warm state with run.bns and td.bas in its RAM startup folder (blazie_files extract, pack, import)"""
    folder, img, out = os.path.join(tmp, "unit"), os.path.join(tmp, "td.img"), os.path.join(tmp, "td_unit.state")
    shutil.copy(st, out)
    for cmd in (["extract", st, folder], None, ["pack", folder, img], ["import", out, img]):
        if cmd is None:
            ram = next(os.path.join(folder, d) for d in os.listdir(folder) if d.lower().startswith("ram"))
            shutil.copy(run_bns, os.path.join(ram, "run.bns"))
            open(os.path.join(ram, "td.bas"), "wb").write(TD_BAS)
            continue
        r = subprocess.run([files] + cmd, capture_output=True, text=True)
        if r.returncode:
            sys.exit("blazie_files %s: %s" % (cmd[0], (r.stdout + r.stderr)[-300:]))
    return out


def td_run(lib, fw, st, double, latch_ns):
    u = Unit(lib, fw, st, double, latch_ns)
    u.listen(12.0)
    if double:
        u.double_on()
    u.keys(RUN_TD)
    u.writes.clear()
    u.listen(15.0 if double else 30.0)              # the 80 notes take ~7 s at double speed, ~14 s at the base clock
    notes = sum(1 for t, r, v in u.writes if r == 0 and v == 0x37)
    r4_37 = sum(1 for t, r, v in u.writes if r == 4 and v == 0x37)
    return notes, r4_37, u.close()


def main():
    arch = "x64" if struct.calcsize("P") == 8 else "x86"
    ap = argparse.ArgumentParser()
    ap.add_argument("--firmware", default=os.environ.get("SSI263_FIRMWARE") or os.path.join(REPO, "firmware", "blazie"))
    ap.add_argument("--lib", default=os.path.join(REPO, "build", "win", arch, "ssi263speech.dll") if WINDOWS
                    else os.path.join(REPO, "build", "linux", "libssi263speech.so"))
    ap.add_argument("--files", default=os.path.join(REPO, "nvda", "dist", "blazie-emu", "blazie_files.exe") if WINDOWS
                    else os.path.join(REPO, "build", "linux", "blazie_files"))
    a = ap.parse_args()
    fw, st = os.path.join(a.firmware, "BL2ENG.BNS"), os.path.join(a.firmware, "bl2_2003_warm.state")
    if not (os.path.isfile(fw) and os.path.isfile(st)):
        print("skip: BL2ENG.BNS and bl2_2003_warm.state are not in %s" % a.firmware)
        return
    lib = load(a.lib)
    bad = 0

    def report(ok, what):
        nonlocal bad
        print("%-4s %s" % ("ok" if ok else "FAIL", what))
        bad += not ok

    on, caught_on = speech_writes(lib, fw, st, None)
    off, caught_off = speech_writes(lib, fw, st, 0)
    report(on == off and len(on) > 100 and caught_on == 0,
           "speech   at double speed: %d writes with the race, %d without, %s; %d caught (want the same, 0)"
           % (len(on), len(off), "the same" if on == off else "DIFFERENT", caught_on))
    units = [("Braille Lite 2000", fw, st)]
    fw640 = os.path.join(a.firmware, "bns640", "june2003")
    if os.path.isfile(os.path.join(fw640, "BSPENG.BNS")) and os.path.isfile(os.path.join(fw640, "bspeng_fresh.state")):
        units.append(("Braille 'n Speak 640", os.path.join(fw640, "BSPENG.BNS"), os.path.join(fw640, "bspeng_fresh.state")))
    else:
        print("skip params on the 640: no bns640/june2003/BSPENG.BNS and bspeng_fresh.state in %s" % a.firmware)
    for name, ufw, ust in units:
        runs = [params_walk(lib, ufw, ust, s, WIDE_NS if WIDE else None) for s in PARAMS_STARTS]
        held, caught = sum(h for h, c in runs), sum(c for h, c in runs)
        report(held == 0 and caught == 0,
               "params   %s at double speed, %d speech-parameter keys: %d left holding a phoneme, %d writes caught "
               "(want none: the real units never hold one)" % (name, len(PARAMS_WALK) * len(runs), held, caught))
    games =os.path.join(a.firmware, "games")
    run_bns = next((os.path.join(games, n) for n in (os.listdir(games) if os.path.isdir(games) else [])
                    if n.lower() == "run.bns"), None)
    if not run_bns or not os.path.isfile(a.files):
        print("skip tones/base: %s" % ("no run.bns in %s" % games if not run_bns else "no %s" % a.files))
    else:
        tmp = tempfile.mkdtemp(prefix="latch_race_")
        try:
            tst = td_state(a.files, a.firmware, st, run_bns, tmp)
            notes, r4, caught = td_run(lib, fw, tst, 1, 1000 if BREAK else None)
            report(caught > 0 and r4 >= 10 and notes >= 60,
                   "tones    80 notes at double speed: %d played, %d writes caught, %d R4s of 37 (want some of each)"
                   % (notes, caught, r4))
            notes, r4, caught = td_run(lib, fw, tst, 0, None)
            report(caught == 0 and r4 == 0 and notes >= 60,
                   "base     at the base clock: %d played, %d caught, %d R4s of 37 (want none)" % (notes, caught, r4))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print("latch race: every check passed" if not bad else "latch race: %d FAILED" % bad)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
