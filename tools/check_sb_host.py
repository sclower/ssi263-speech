"""The C Sounding Board host (src/csrc/soundingboard/sb_host.c) against its reference, src/hosts/soundingboard.py: the
same drivers, boot and sentences, every chip write the same -- register, value and chip time (the Python logs it
round()ed to 6 places, and so is the C's here).  The C test
program (test_sb_host.c) is built here with w64devkit, the chip's flags as build_am.py's.

    python tools/check_sb_host.py            exit 1 on any failure

Control (SB_HOST_BREAK=1): the Python reference's chip runs 1 % fast (xck 1.01 MHz) -- every frame then comes at
another time, and the writes must differ.  Control (SSI263_SB_PACE_BREAK=1, both hosts): the long text printed at once, as
before this fix -- both hosts must fault.  (The instruction coupling alone does not show: the drivers send a frame
when the chip asks, so their writes follow the chip, not the CPU's speed.)
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
CSRC = os.path.join(ROOT, "src", "csrc")
SB_DIR = os.path.join(ROOT, "firmware", "gw-micro-sounding-board")
OUT = os.path.join(ROOT, "build", "sb_host", str(os.getpid()))   # its own: the suite runs the check and its control at once
# the last, about 70 s of speech: SB.COM's frame ring holds 40 s, so its text is printed as the ring empties (say()) --
# printed at once, the call waited past 30 s and the host faulted, the whole text lost (a listener's report, 0.8.5)
TEXTS = ["Hello, this is the Sounding Board.", "The quick brown fox jumps over the lazy dog, 1234 times.",
         "The quick brown fox jumps over the lazy dog. " * 24]
BREAK = os.environ.get("SB_HOST_BREAK") == "1"
sys.path.insert(0, ROOT)
from tools import repo_paths  # noqa: E402
GCC = repo_paths.bin_dir("W64DEVKIT")


def build():
    env = dict(os.environ, PATH=GCC + os.pathsep + os.environ.get("PATH", ""))
    os.makedirs(OUT, exist_ok=True)
    cc = ["-O2", "-std=gnu99", "-ffp-contract=off", "-Wall"]
    chip = ["-O2", "-std=c99", "-ffp-contract=off", "-Wall", "-Wextra", "-Wno-unused-parameter"]
    cxx = ["-O2", "-std=c++17", "-fno-exceptions", "-fno-rtti", "-ffp-contract=off", "-Wall", "-Wno-sign-compare"]
    inc = ["-I" + os.path.join(CSRC, "cpu"), "-I" + os.path.join(CSRC, "pc86"), "-I" + os.path.join(CSRC, "soundingboard"),
           "-I" + CSRC]
    objs = []
    for src, tool, flags in ((os.path.join(CSRC, "cpu", "i86_mame.cpp"), "g++", cxx),
                             (os.path.join(CSRC, "pc86", "pc86.c"), "gcc", cc),
                             (os.path.join(CSRC, "soundingboard", "sb_host.c"), "gcc", cc),
                             (os.path.join(CSRC, "soundingboard", "test_sb_host.c"), "gcc", cc),
                             (os.path.join(CSRC, "numwords.c"), "gcc", cc),
                             (os.path.join(CSRC, "ssi263.c"), "gcc", chip),
                             (os.path.join(CSRC, "ssi263dsp.c"), "gcc", chip)):
        obj = os.path.join(OUT, os.path.basename(src) + ".o")
        subprocess.run([os.path.join(GCC, tool)] + flags + inc + ["-c", src, "-o", obj], check=True, env=env)
        objs.append(obj)
    exe = os.path.join(OUT, "test_sb_host.exe")
    subprocess.run([os.path.join(GCC, "g++"), "-static", "-o", exe] + objs, check=True, env=env)
    return exe


def reference():
    from hosts.soundingboard import SoundingBoard
    chip = None
    if BREAK:                                    # the control: the reference's chip clock 1 % fast
        from ssi263 import SSI263
        chip = SSI263({"xck_hz": 1_010_000.0}, out_rate=44100)
    sb = SoundingBoard(os.path.join(SB_DIR, "SBLOAD.COM"), os.path.join(SB_DIR, "SB.COM"), chip=chip)
    n0 = len(sb.writes)                  # the C test logs from after loading (log_writes is set then)
    sb.boot()
    lines = []
    try:
        for text in TEXTS:
            sb.say(text + "\r")
            sb.run(0.05)
            k = 0
            while k < 2400 and sb.busy():
                sb.run(0.05)
                k += 1
            lines.append(len(sb.writes) - n0)
    except RuntimeError as e:                    # the host stopped: what it wrote, and why
        return sb.writes[n0:], lines, str(e)
    return sb.writes[n0:], lines, None


def main():
    paths = [os.path.join(SB_DIR, "SBLOAD.COM"), os.path.join(SB_DIR, "SB.COM")]
    if not all(os.path.isfile(p) for p in paths):
        print("skip  the Sounding Board host check: its drivers are not in firmware/gw-micro-sounding-board")
        return 0
    try:
        exe = build()
        r = subprocess.run([exe] + paths + TEXTS, capture_output=True, text=True, timeout=600)
    finally:
        import shutil
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
    py_writes, py_ends, py_fault = reference()
    failures = 0
    print("%-5s the Python reference ran: %s" % ("ok" if py_fault is None else "FAIL", py_fault or "%d writes" % len(py_writes)))
    failures += py_fault is not None
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
    print("%-5s each sentence's end: C %s, Python %s" % ("ok" if c_ends == py_ends else "FAIL", c_ends, py_ends))
    failures += c_ends != py_ends
    print("sb host: %s" % ("all passed" if not failures else "%d FAILED" % failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
