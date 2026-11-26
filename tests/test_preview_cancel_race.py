"""Real JobManager regression for preview cancellation while queued."""
import sys
import threading
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import preview
from app.jobs import JobManager

fails = 0


def check(label, cond, detail=""):
    global fails
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else "  " + str(detail)))
    if not cond:
        fails += 1


names = ("resolve_variant", "_resolve_added", "cache_key", "hit", "paths",
         "_probe_streams", "run_ffmpeg_job")
saved = {name: getattr(preview, name) for name in names}
saved_ffmpeg_paths = preview.ffmpeg_tools.ffmpeg_paths
preview._INFLIGHT.clear()
release = threading.Event()
started = threading.Event()
try:
    root = Path("data/test/tmp") / ("preview_cancel_" + uuid.uuid4().hex)
    root.mkdir(parents=True, exist_ok=True)
    files = {"mp4": root / "out.mp4", "json": root / "out.json", "ok": root / "out.ok"}
    info = {"streams": [
        {"type": "video", "start_time": "0", "duration": "1.0"},
        {"type": "audio", "start_time": "0", "duration": "1.0", "sample_rate": 48000},
    ], "format": {"duration": "1.0"}}
    preview.resolve_variant = lambda cfg, source, variant: "original"
    preview._resolve_added = lambda db, options: None
    preview.cache_key = lambda source, variant_path, options, variant: "cancel-race-key"
    preview.hit = lambda cfg, key: None
    preview.paths = lambda cfg, key: files
    preview._probe_streams = lambda cfg, path: info
    preview.ffmpeg_tools.ffmpeg_paths = lambda cfg: ("ffmpeg", "ffprobe")

    def fake_ffmpeg(job, ff, args, total_us=None):
        # The nested preview runner only needs a non-empty output to finish successfully.
        Path(args[-1]).write_bytes(b"fake-preview")

    preview.run_ffmpeg_job = fake_ffmpeg
    jobs = JobManager(None, concurrency=1)

    def blocker(job):
        started.set()
        release.wait(5)
        return {"blocked": True}

    held = jobs.create("other", None, blocker)
    check("the blocker occupies the only worker slot", started.wait(2))
    options = {"variant": "original", "audioMode": "original"}
    source = {"id": "s1", "path": "unused.mp4", "duration_us": 1000000}
    first, _variant, _key, _cached = preview.start_preview(None, None, jobs, source, options)
    check("the preview is queued behind the blocker", first.status == "queued", first.status)
    jobs.cancel(first.id)
    release.set()
    held.thread.join(3)
    first.thread.join(3)
    check("the queued preview is cancelled", first.status == "cancelled", first.status)
    check("cancelling before runner does not leave the key registered",
      "cancel-race-key" not in preview._INFLIGHT, list(preview._INFLIGHT))

    second, _variant, _key, _cached = preview.start_preview(None, None, jobs, source, options)
    second.thread.join(5)
    check("the same key starts a new job after cancellation", second.id != first.id, second.id)
    check("the replacement preview completes", second.status == "done", second.status)
    check("the replacement also cleans up its key",
      "cancel-race-key" not in preview._INFLIGHT, list(preview._INFLIGHT))
finally:
    release.set()
    for name, value in saved.items():
        setattr(preview, name, value)
    preview.ffmpeg_tools.ffmpeg_paths = saved_ffmpeg_paths
    preview._INFLIGHT.clear()

print("RESULT: " + ("FAIL(%d)" % fails if fails else "OK"))
sys.exit(1 if fails else 0)
