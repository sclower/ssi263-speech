"""The C SmarTalk host (src/csrc/smartalk/st_host.c) against its reference, src/hosts/smartalk.py: the same TSR,
boot and sentences -- with SmarTalk's own commands and the Accent's, and a cancel mid-sentence -- every chip write
the same: register, value and chip time (the Python logs it round()ed to 6 places, and so is the C's here).  The C
test program (test_st_host.c) is built here with w64devkit, the chip's flags as check_sb_host.py's.

    python tools/check_st_host.py            exit 1 on any failure

Control (ST_HOST_BREAK=1): the Python reference's chip runs 1 % fast (xck 1.01 MHz) -- every phoneme then comes at
another time, and the writes must differ.  (The instruction coupling alone does not show: the TSR sends a phoneme
when the chip asks, so its writes follow the chip, not the CPU's speed.)
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
CSRC = os.path.join(ROOT, "src", "csrc")
EXE = os.path.join(ROOT, "firmware", "automated-functions-smartalk", "S_TALK.EXE")
OUT = os.path.join(ROOT, "build", "st_host", str(os.getpid()))   # its own: the suite may run the check and its control at once
E = "\x1b"
TEXTS = ["Hello, this is SmarTalk.",
         "The quick brown fox jumps over the lazy dog, 1234 times.",
         E + ">9" + E + "P8" + E + "{M Faster, higher and another tone." + E + ">5" + E + "P5" + E + "{I",
         E + "m1 Monotone, then " + E + "m0 the regular inflection.",
         E + "R0" + E + "V7 The Accent's rate and voice commands." + E + "R5" + E + "V5",
         "This sentence is cut off by a control X before it ends, and the next one is said whole.", "^X",
         "Said after the cancel."]
BREAK = os.environ.get("ST_HOST_BREAK") == "1"
sys.path.insert(0, ROOT)
from tools import repo_paths  # noqa: E402
GCC = repo_paths.bin_dir("W64DEVKIT")


def build():
    env = dict(os.environ, PATH=GCC + os.pathsep + os.environ.get("PATH", ""))
    os.makedirs(OUT, exist_ok=True)
    cc = ["-O2", "-std=gnu99", "-ffp-contract=off", "-Wall"]
    chip = ["-O2", "-std=c99", "-ffp-contract=off", "-Wall", "-Wextra", "-Wno-unused-parameter"]
    cxx = ["-O2", "-std=c++17", "-fno-exceptions", "-fno-rtti", "-ffp-contract=off", "-Wall", "-Wno-sign-compare"]
    inc = ["-I" + os.path.join(CSRC, "cpu"), "-I" + os.path.join(CSRC, "pc86"), "-I" + os.path.join(CSRC, "smartalk"),
           "-I" + CSRC]
    objs = []
    for src, tool, flags in ((os.path.join(CSRC, "cpu", "i86_mame.cpp"), "g++", cxx),
                             (os.path.join(CSRC, "pc86", "pc86.c"), "gcc", cc),
                             (os.path.join(CSRC, "smartalk", "st_host.c"), "gcc", cc),
                             (os.path.join(CSRC, "smartalk", "test_st_host.c"), "gcc", cc),
                             (os.path.join(CSRC, "numwords.c"), "gcc", cc),
                             (os.path.join(CSRC, "ssi263.c"), "gcc", chip),
                             (os.path.join(CSRC, "ssi263dsp.c"), "gcc", chip)):
        obj = os.path.join(OUT, os.path.basename(src) + ".o")
        subprocess.run([os.path.join(GCC, tool)] + flags + inc + ["-c", src, "-o", obj], check=True, env=env)
        objs.append(obj)
    exe = os.path.join(OUT, "test_st_host.exe")
    subprocess.run([os.path.join(GCC, "g++"), "-static", "-o", exe] + objs, check=True, env=env)
    return exe


def reference():
    from hosts.smartalk import SmarTalk
    chip = None
    if BREAK:                                    # the control: the reference's chip clock 1 % fast
        from ssi263 import SSI263
        chip = SSI263({"xck_hz": 1_010_000.0}, out_rate=44100)
    st = SmarTalk(EXE, chip=chip)
    n0 = len(st.writes)                  # the C test logs from after loading (log_writes is set then)
    st.boot()
    lines = []
    for i, text in enumerate(TEXTS):
        if text == "^X":
            st.cancel()
        else:
            st.say(text + "\r")
            if i + 1 < len(TEXTS) and TEXTS[i + 1] == "^X":
                st.run(0.4)
            else:
                st.run(0.05)
                k = 0
                while k < 400 and st.busy():
                    st.run(0.05)
                    k += 1
        lines.append(len(st.writes) - n0)
    return st.writes[n0:], lines


def main():
    if not os.path.isfile(EXE):
        print("skip  the SmarTalk host check: S_TALK.EXE is not in firmware/automated-functions-smartalk")
        return 0
    try:
        exe = build()
        r = subprocess.run([exe, EXE] + TEXTS, capture_output=True, text=True, timeout=600)
    finally:
        shutil.rmtree(OUT, ignore_errors=True)
    c_writes, c_ends, fault = [], [], None
    for ln in r.stdout.splitlines():
        p = ln.split()
        if p[0] == "W":
            c_writes.append((float(p[1]), int(p[2]), int(p[3], 16)))
        elif p[0] == "E":
            c_ends.append(int(p[1]))
        elif p[0] == "FAULT":
            fault = ln
    py_writes, py_ends = reference()
    failures = 0
    ok = fault is None and r.returncode == 0
    print("%-5s the C host ran: %s" % ("ok" if ok else "FAIL", fault or "exit %d, %d writes" % (r.returncode,
                                                                                            len(c_writes))))
    failures += not ok
    same = len(c_writes) == len(py_writes) and all(
        a[1:] == b[1:] and round(a[0], 6) == b[0] for a, b in zip(c_writes, py_writes))
    where = next((i for i, (a, b) in enumerate(zip(c_writes, py_writes))
                  if a[1:] != b[1:] or round(a[0], 6) != b[0]), min(len(c_writes), len(py_writes)))
    print("%-5s every chip write: C %d, Python %d%s" % ("ok" if same else "FAIL", len(c_writes), len(py_writes),
                                                        "" if same else ", first difference at write %d" % where))
    failures += not same
    print("%-5s each line's end: C %s, Python %s" % ("ok" if c_ends == py_ends else "FAIL", c_ends, py_ends))
    failures += c_ends != py_ends
    print("st host: %s" % ("all passed" if not failures else "%d FAILED" % failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
