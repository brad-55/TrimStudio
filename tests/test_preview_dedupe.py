"""Targeted tests for preview's same-key job de-duplication (no ffmpeg required)."""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import preview

fails = 0


def check(label, cond, detail=""):
    global fails
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else "  " + str(detail)))
    if not cond:
        fails += 1


class FakeJobs:
    def __init__(self, status):
        self.status = status
        self.created = []

    def create(self, kind, source_id, runner, on_finish=None):
        job = SimpleNamespace(id="j%d" % (len(self.created) + 1),
                              status=self.status, runner=runner, on_finish=on_finish)
        job.is_cancelled = lambda: job.status == "cancelled"
        self.created.append(job)
        return job


def exercise(status):
    saved = {name: getattr(preview, name) for name in
             ("resolve_variant", "_resolve_added", "cache_key", "hit", "paths")}
    preview._INFLIGHT.clear()
    try:
        preview.resolve_variant = lambda cfg, source, variant: "original"
        preview._resolve_added = lambda db, options: None
        preview.cache_key = lambda source, variant_path, options, variant: "same-key"
        preview.hit = lambda cfg, key: None
        preview.paths = lambda cfg, key: {}
        jobs = FakeJobs(status)
        options = {"variant": "original", "audioMode": "original"}
        source = {"id": "s1", "path": "unused.mp4"}
        first = preview.start_preview(None, None, jobs, source, options)
        second = preview.start_preview(None, None, jobs, source, options)
        return jobs, first[0], second[0]
    finally:
        for name, value in saved.items():
            setattr(preview, name, value)
        preview._INFLIGHT.clear()


jobs, first, second = exercise("running")
check("a runner that starts before create() returns is still registered",
      first is second and len(jobs.created) == 1,
      [job.id for job in jobs.created])

jobs, first, second = exercise("cancelled")
check("a cancelled job is not retained as the in-flight answer",
      first is not second and len(jobs.created) == 2,
      [job.id for job in jobs.created])

jobs, first, second = exercise("done")
check("a synchronously completed job is not re-registered",
      first is not second and len(jobs.created) == 2,
      [job.id for job in jobs.created])

# Direct preview callers must ignore addedSourceId in original/mute too, not only via main.py.
check("original mode never resolves an unused added source",
      preview._resolve_added(None, {"audioMode": "original", "addedSourceId": "unused"}) is None)
check("mute never resolves an unused added source",
      preview._resolve_added(None, {"audioMode": "mute", "addedSourceId": "unused"}) is None)
saved_sig = preview.content_sig
try:
    preview.content_sig = lambda path: str(path)
    source = {"id": "s1", "path": "video.mp4"}
    base = {"audioMode": "original", "audioShiftMs": 0, "addedShiftMs": 0, "addedStartMs": 0}
    with_unused = dict(base, addedSourceId="unused")
    check("original mode keeps one cache key with or without an unused added source",
          preview.cache_key(source, "video.mp4", base, "original")
          == preview.cache_key(source, "video.mp4", with_unused, "original"))
    mute = dict(base, audioMode="mute")
    mute_unused = dict(mute, addedSourceId="unused")
    check("mute keeps one cache key with or without an unused added source",
          preview.cache_key(source, "video.mp4", mute, "original")
          == preview.cache_key(source, "video.mp4", mute_unused, "original"))
finally:
    preview.content_sig = saved_sig

print("RESULT: " + ("FAIL(%d)" % fails if fails else "OK"))
sys.exit(1 if fails else 0)
