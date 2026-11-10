"""Automated check that the preview really bakes the requested audio shift.

A click track at known times is muxed with a test video, the preview is built through the
real job, and the click positions are compared.  This is the regression net for the sign
and the ms/sec units in the filter graph: a flipped sign or a /1000 slip shows up as a
grossly wrong delta instead of passing silently.
"""
import os
import struct
import uuid
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import ffmpeg_tools, preview  # noqa: E402
from app.config import Config  # noqa: E402
from app.db import Database  # noqa: E402
from app.jobs import JobManager  # noqa: E402

RATE = 8000
CLICKS = [0.31, 0.93, 1.71, 2.62, 3.94, 5.13]
DUR = 6.0
fails = 0


def check(label, cond, detail=""):
    global fails
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else "  " + str(detail)))
    if not cond:
        fails += 1


def build_fixture(cfg):
    work = Path(cfg.data_dir) / "test"
    work.mkdir(parents=True, exist_ok=True)
    wav = work / "preview_clicks.wav"
    clip = work / "preview_clicks_v2.mp4"
    if clip.exists():
        return clip
    ff, _fp = ffmpeg_tools.ffmpeg_paths(cfg)
    samples = np.zeros(int(48000 * DUR), dtype=np.float32)
    for at in CLICKS:
        start = int(at * 48000)
        n = int(0.02 * 48000)
        samples[start:start + n] += 0.8 * np.sin(2 * np.pi * 1000 * np.arange(n) / 48000)
    pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16)
    with open(wav, "wb") as handle:
        handle.write(b"RIFF" + struct.pack("<I", 36 + pcm.nbytes) + b"WAVEfmt ")
        handle.write(struct.pack("<IHHIIHH", 16, 1, 1, 48000, 96000, 2, 16))
        handle.write(b"data" + struct.pack("<I", pcm.nbytes) + pcm.tobytes())
    subprocess.run([ff, "-hide_banner", "-nostdin", "-y", "-f", "lavfi", "-i",
                    "testsrc2=size=320x240:rate=30:duration=" + str(int(DUR)),
                    "-i", str(wav), "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart", str(clip)], capture_output=True, check=True)
    return clip


def pcm(path, ff):
    raw = subprocess.run([ff, "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1",
                          "-ar", str(RATE), "-f", "s16le", "-"], capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32)


def click_times(signal, threshold=3000):
    found = []
    last = -1
    for index, value in enumerate(np.abs(signal)):
        if value > threshold and (index - last) > RATE // 10:
            found.append(index / float(RATE))
            last = index
    return found


def main():
    cfg = Config()
    ff, fp = ffmpeg_tools.ffmpeg_paths(cfg)
    if not ff:
        print("RESULT: SKIP (ffmpeg unavailable)")
        return 0
    clip = build_fixture(cfg)
    info = ffmpeg_tools.probe(fp, str(clip))
    streams = []
    for stream in info.get("streams") or []:
        row = dict(stream)
        row["type"] = row.get("codec_type")
        row["codec"] = row.get("codec_name")
        streams.append(row)
    source = {"id": "preview-sync-fixture", "name": clip.name, "path": str(clip),
              "container": "mp4", "duration_us": int(DUR * 1e6),
              "streams_json": __import__("json").dumps(streams)}
    db = Database(cfg.db_path)
    jobs = JobManager(db, 2)
    reference = click_times(pcm(clip, ff))
    check("fixture has the expected clicks", len(reference) >= 5, reference)

    for shift in (0, 500, -500, 120):
        job, variant, key, cached = preview.start_preview(
            cfg, db, jobs, source,
            {"audioMode": "original", "audioShiftMs": shift, "variant": "original"})
        if job is not None:
            deadline = time.time() + 120
            while time.time() < deadline:
                state = jobs.get(job.id)
                status = state.get("status") if isinstance(state, dict) else getattr(state, "status", None)
                if status in ("done", "error", "cancelled"):
                    if status != "done":
                        check("build for shift %d" % shift, False, status)
                    break
                time.sleep(0.25)
        out = preview.paths(cfg, key)["mp4"]
        got = click_times(pcm(out, ff))
        if shift >= 0:
            expected = [c + shift / 1000.0 for c in reference if c + shift / 1000.0 < DUR - 0.05]
        else:
            expected = [c + shift / 1000.0 for c in reference if c + shift / 1000.0 > 0.02]
        check("shift %+dms detects the same number of clicks" % shift,
              len(expected) == len(got), "expected %d got %d" % (len(expected), len(got)))
        delta = max((abs(a - b) for a, b in zip(expected, got)), default=999)
        check("shift %+dms lands within 2ms" % shift, delta <= 0.002, "max delta %.4fs" % delta)
        length = subprocess.run([fp, "-v", "error", "-show_entries", "format=duration",
                                 "-of", "default=nw=1:nk=1", str(out)],
                                capture_output=True, text=True).stdout.strip()
        try:
            check("shift %+dms keeps the video length" % shift, abs(float(length) - DUR) < 0.05, length)
        except ValueError:
            check("shift %+dms keeps the video length" % shift, False, length)

    # The video is copied, not re-encoded: pin that with frame hashes so a future change
    # to the video pipeline cannot silently degrade the "pretend it is the same file" claim.
    built = preview.paths(cfg, key)["mp4"]

    def framemd5(path):
        raw = subprocess.run([ff, "-v", "error", "-i", str(path), "-map", "0:v:0",
                              "-f", "framemd5", "-"], capture_output=True, text=True).stdout
        return [line.split(",")[-1].strip() for line in raw.splitlines()
                if line and not line.startswith("#")]

    source_frames = framemd5(clip)
    built_frames = framemd5(built)
    check("the preview copies every video frame bit for bit",
          built_frames == source_frames,
          "%d vs %d frames" % (len(built_frames), len(source_frames)))

    # A build that fails must not leave its temporary file behind.
    before = set(os.listdir(preview.preview_dir(cfg)))
    broken = dict(source)
    broken["path"] = str(clip.parent / "does_not_exist.mp4")
    broken["id"] = "preview-sync-broken"
    try:
        job, _variant, _key, _cached = preview.start_preview(
            cfg, db, jobs, broken, {"audioMode": "original", "audioShiftMs": 0, "variant": "original"})
    except ValueError:
        # Fail fast on an unreadable source: that is the intended behaviour.
        job = None
        check("an unreadable source is rejected before building", True)
    if job is not None:
        deadline = time.time() + 60
        while time.time() < deadline:
            state = jobs.get(job.id)
            status = state.get("status") if isinstance(state, dict) else getattr(state, "status", None)
            if status in ("done", "error", "cancelled"):
                break
            time.sleep(0.25)
        check("a build with a missing source fails", status == "error", status)
        leftover = [n for n in os.listdir(preview.preview_dir(cfg)) if ".part" in n and n not in before]
        check("a failed build leaves no .part file", not leftover, leftover)

    # A build that dies AFTER ffmpeg started must not leave its temporary file behind.
    # Forcing this with a real encoder is not reliable on Windows (ffmpeg often exits 0 on
    # a truncated tail), so the ffmpeg runner is replaced with one that writes a partial
    # output and then raises - exactly the state the cleanup has to survive.
    real_run = preview.run_ffmpeg_job
    seen = {"part": None, "called": False}

    def failing_run(job, ff_path, args, total_us=0, **kwargs):
        seen["called"] = True
        target = Path(args[-1])
        target.write_bytes(b"partial")
        seen["part"] = target
        raise RuntimeError("simulated ffmpeg failure")

    broken_mid = dict(source)
    broken_mid["id"] = "preview-sync-midfail"
    # A fresh shift every run: a cached answer would skip the build (and the failure path).
    unique_shift = 100000 + uuid.uuid4().int % 400000
    preview.run_ffmpeg_job = failing_run
    try:
        job, _variant, _key, _cached = preview.start_preview(
            cfg, db, jobs, broken_mid,
            {"audioMode": "original", "audioShiftMs": unique_shift, "variant": "original"})
        if job is None:
            check("a build that dies after ffmpeg started fails", False, "the request was cached")
        else:
            deadline = time.time() + 60
            status_mid = None
            while time.time() < deadline:
                state = jobs.get(job.id)
                status_mid = state.get("status") if isinstance(state, dict) else getattr(state, "status", None)
                if status_mid in ("done", "error", "cancelled"):
                    break
                time.sleep(0.1)
            check("a build that dies after ffmpeg started fails", status_mid == "error", status_mid)
            check("the mid-build failure path was exercised", seen["called"] and seen["part"] is not None)
            # The runner deletes the part in a finally block before the job publishes
            # "error", so this normally holds immediately; the poll only absorbs a
            # scheduling gap instead of racing the worker thread.
            gone_by = time.time() + 5
            while seen["part"] is not None and seen["part"].exists() and time.time() < gone_by:
                time.sleep(0.05)
            check("the temporary file is removed when the build fails",
                  seen["part"] is not None and not seen["part"].exists(), seen["part"])
    finally:
        preview.run_ffmpeg_job = real_run

    print("RESULT: " + ("FAIL(%d)" % fails if fails else "OK"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
