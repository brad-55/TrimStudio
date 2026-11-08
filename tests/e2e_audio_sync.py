"""E2E: automatic audio sync finds a known delay (needs ffmpeg, skipped otherwise)."""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import audio_sync, ffmpeg_tools  # noqa: E402
from app.config import Config  # noqa: E402

WORK = Path(r"L:/dev/Trim/data/test/audio_sync")
DELAY_MS = 137
fails = 0


def check(label, cond, detail=""):
    global fails
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else "  " + str(detail)))
    if not cond:
        fails += 1


def run(args):
    return subprocess.run(args, capture_output=True, text=True)


def main():
    cfg = Config()
    ff, _ = ffmpeg_tools.ffmpeg_paths(cfg)
    if not ff:
        print("SKIP audio sync e2e: ffmpeg not available")
        return 0
    WORK.mkdir(parents=True, exist_ok=True)
    src = WORK / "src.mp4"
    added = WORK / "added.m4a"
    duration = 30
    r = run([ff, "-y", "-f", "lavfi", "-i", "anoisesrc=d=%d:c=pink:r=48000" % duration,
             "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=10:duration=%d" % duration,
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(src)])
    if r.returncode != 0:
        print("SKIP audio sync e2e: cannot build the source (" + r.stderr[-200:] + ")")
        return 0
    # The added track is the same audio delayed by DELAY_MS -> it must be advanced by that.
    r = run([ff, "-y", "-i", str(src), "-vn", "-af", "adelay=%d|%d" % (DELAY_MS, DELAY_MS),
             "-c:a", "aac", str(added)])
    check("added track built", r.returncode == 0, r.stderr[-200:])
    if r.returncode != 0:
        return 1

    one = audio_sync.analyze(cfg, ff, str(src), str(added), window_us=10_000_000,
                             range_us=2_000_000, windows=1)
    check("single window analysis succeeds", one.get("ok") is True, one)
    if one.get("ok"):
        check("offset is about -%dms" % DELAY_MS, abs(one["offsetMs"] + DELAY_MS) <= 25, one)

    three = audio_sync.analyze(cfg, ff, str(src), str(added), window_us=6_000_000,
                               range_us=1_000_000, windows=3, span_us=duration * 1_000_000)
    check("multi window analysis succeeds", three.get("ok") is True, three)
    if three.get("ok"):
        check("multi window offset is about -%dms" % DELAY_MS, abs(three["offsetMs"] + DELAY_MS) <= 25, three)
        check("multi window estimates agree", three.get("consistent") is True, three)

    silent = WORK / "silent.m4a"
    run([ff, "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", "10", str(silent)])
    bad = audio_sync.analyze(cfg, ff, str(src), str(silent), window_us=6_000_000,
                             range_us=1_000_000, windows=1)
    check("silent target is rejected", bad.get("ok") is False, bad)

    print("RESULT:", "OK" if fails == 0 else "FAIL(%d)" % fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
