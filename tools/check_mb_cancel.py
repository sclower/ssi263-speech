"""The Mockingboard voices after a cancel: the next text starts as a text said again after its end does -- no pop,
none of the cut phoneme at its head (Tomi: "slight pops and phoneme spitback at the start of utterances ... quickly
tabbing").

For each version, "Warning, the quick brown fox ..." is cut at 0.12, 0.2, 0.33 and 0.5 s (mbv_cancel, as NVDA does
when a new utterance comes), then "Hello there." is said.  Its start against "Hello there." said again after it ended
(the state every text but a new voice's first starts from): its onset (the first sample past 300) within 40 ms, and
its first 40 ms like that start's (the normalized correlation of the two envelopes, aligned on each one's own onset,
the best within 10 ms: at least 0.65).  As it was, a cut's last phoneme came back at once (onset 0-1 ms, likeness
-0.5: nothing like "Hello"), and even a text said again after its end came 90-110 ms late; with the tract brought to
rest before each text, every start reads 0.66-0.81, onsets 9-20 ms.

    python tools/check_mb_cancel.py [library]     (default build/win/x64/ssi263speech.dll)

Control (MB_CANCEL_REST_BREAK=1): the tract not brought to rest before a text (mb_voice.c rest), as it was -- every
cut must fail.
"""
import ctypes
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FW = os.path.join(ROOT, "firmware", "sweet-micro-mockingboard")
OLD = b"Warning, the quick brown fox jumps over the lazy dog, again and again and again."
NEW = b"Hello there."
CUTS = (0.12, 0.2, 0.33, 0.5)
R = 22050
ONSET_MAX = 0.040               # seconds: a start later than this was held back
LIKE_MIN = 0.65                 # its first 40 ms against the fresh start's


def load(path):
    lib = ctypes.CDLL(path)
    p = ctypes.c_void_p
    lib.mbv_create.restype = p
    lib.mbv_create.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_double, ctypes.c_char_p, ctypes.c_int]
    lib.mbv_speak.argtypes = [p, ctypes.c_char_p, ctypes.c_int]
    lib.mbv_render.argtypes = [p, ctypes.POINTER(ctypes.POINTER(ctypes.c_short)), ctypes.POINTER(ctypes.c_int)]
    lib.mbv_cancel.argtypes = [p]
    lib.mbv_destroy.argtypes = [p]
    return lib


def render(lib, v, seconds):
    pcm, done, out = ctypes.POINTER(ctypes.c_short)(), ctypes.c_int(0), []
    while len(out) < seconds * R:
        k = lib.mbv_render(v, ctypes.byref(pcm), ctypes.byref(done))
        if k > 0:
            out.extend(pcm[:k])
        if done.value or k < 0:
            break
    return out[:int(seconds * R)]


def onset(y):
    return next((i for i, x in enumerate(y) if abs(x) > 300), len(y))


def envelope(y, start, n, w=22):
    """the mean absolute sample over 1 ms windows, from start, n samples"""
    return [sum(abs(x) for x in y[i:i + w]) / w for i in range(start, start + n, w)]


def corr(p, q):
    n = min(len(p), len(q))
    if n < 2:
        return 0.0
    p, q = p[:n], q[:n]
    mp, mq = sum(p) / n, sum(q) / n
    num = sum((x - mp) * (y - mq) for x, y in zip(p, q))
    den = (sum((x - mp) ** 2 for x in p) * sum((y - mq) ** 2 for y in q)) ** 0.5
    return num / den if den else 0.0


def likeness(y, fresh_env):
    """the first 40 ms from its own onset against the fresh start's, the best alignment within 10 ms"""
    o, n = onset(y), int(0.040 * R)
    return max(corr(envelope(y, max(0, o + d), n), fresh_env) for d in range(-220, 221, 22))


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "build", "win", "x64", "ssi263speech.dll")
    names = ("mockingboard-tts-1.1.bin", "mockingboard-tts-early.bin")
    if not all(os.path.isfile(os.path.join(FW, n)) for n in names):
        print("skip  the Mockingboard cancel check: its files are not in firmware/sweet-micro-mockingboard")
        return 0
    lib = load(path)
    err = ctypes.create_string_buffer(300)
    failures = 0
    for name in names:
        img = open(os.path.join(FW, name), "rb").read()
        v = lib.mbv_create(img, len(img), float(R), err, 300)
        if not v:
            print("FAIL  %s: %s" % (name, err.value.decode()))
            failures += 1
            continue
        # the start to match: the text said again after it has ended (every text but a new voice's first starts so;
        # the first comes from the chip's power-on, never sample for sample the same)
        lib.mbv_speak(v, NEW, 0)
        render(lib, v, 5.0)
        lib.mbv_speak(v, NEW, 0)
        fresh = render(lib, v, 0.4)
        render(lib, v, 5.0)
        f_onset = onset(fresh)
        fresh_env = envelope(fresh, f_onset, int(0.040 * R))
        print("      %s said again after its end: onset %.1f ms" % (name, 1000.0 * f_onset / R))
        for cut in CUTS:
            lib.mbv_speak(v, OLD, 0)
            render(lib, v, cut)
            lib.mbv_cancel(v)
            lib.mbv_speak(v, NEW, 0)
            y = render(lib, v, 0.4)
            o, like = onset(y) / float(R), likeness(y, fresh_env)
            good = o <= ONSET_MAX and like >= LIKE_MIN
            print("%-5s %s cut at %.2f s: onset %.1f ms, its start like a usual one's %.2f" % (
                "ok" if good else "FAIL", name, cut, 1000.0 * o, like))
            failures += not good
        lib.mbv_destroy(v)
    print("mb cancel: %s" % ("all passed" if not failures else "%d FAILED" % failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
