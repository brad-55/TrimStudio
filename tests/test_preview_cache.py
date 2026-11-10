"""Security / cache-integrity tests for the preview endpoint.

The media route resolves a file from a key, so the key validation is the only thing
between a URL and the filesystem.  These cases pin it down, and the cache tests make sure
a half-written preview can never be served as if it were complete.
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import cleanup, preview  # noqa: E402

fails = 0


def check(label, cond, detail=""):
    global fails
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else "  " + str(detail)))
    if not cond:
        fails += 1


good = "a" * 40
check("a 40-hex key is accepted", bool(preview.VALID_KEY.match(good)))
for bad in ["..", "../" + good, good + "/../x", good.upper(), "a" * 39, "a" * 41,
            "g" * 40, "a" * 40 + ".mp4", "\\server\\share", "C:/windows/win.ini",
            "a" * 20 + "/" + "b" * 19, ""]:
    check("rejected: " + repr(bad)[:40], not preview.VALID_KEY.match(bad))

root = Path(__file__).resolve().parent.parent / "data" / "test" / "preview_cache_case"
shutil.rmtree(root, ignore_errors=True)
root.mkdir(parents=True, exist_ok=True)
try:
    class Cfg:
        work_dir = root / "work"
        thumbs_dir = root / "thumbs"
        data_dir = root
        def get(self, key, default=None):
            return default
    cfg = Cfg()
    key = "b" * 40
    files = preview.paths(cfg, key)
    Path(files["mp4"].parent).mkdir(parents=True, exist_ok=True)
    files["mp4"].write_bytes(b"x")
    check("an mp4 without the sidecars is not a hit", preview.hit(cfg, key) is None)
    files["json"].write_text(json.dumps({"impl": preview.IMPL, "sourceTimelineOffsetUs": 0,
                                        "outputStartOffsetUs": 0, "durationUs": 1}), encoding="utf-8")
    check("an mp4 with json but no marker is not a hit", preview.hit(cfg, key) is None)
    files["ok"].write_text("ok", encoding="utf-8")
    meta = preview.hit(cfg, key)
    check("the full trio is a hit", meta is not None and meta.get("url", "").endswith(".mp4"))
    files["json"].write_text(json.dumps({"impl": "old-impl", "durationUs": 1}), encoding="utf-8")
    check("a cache from another impl is not a hit", preview.hit(cfg, key) is None)
finally:
    shutil.rmtree(root, ignore_errors=True)

# --- cleanup: a preview in use must survive the LRU, an idle one must not -------------
class Db:
    def __init__(self, sources):
        self.sources = sources

    def list_sources(self):
        return self.sources


root2 = Path(__file__).resolve().parent.parent / "data" / "test" / "preview_lru_case"
shutil.rmtree(root2, ignore_errors=True)
root2.mkdir(parents=True, exist_ok=True)
try:
    class Cfg2:
        work_dir = root2 / "work"
        thumbs_dir = root2 / "thumbs"
        data_dir = root2
        overrides = {"workCacheBytes": 1, "activeWindowSeconds": 600}
        def get(self, key, default=None):
            return self.overrides.get(key, default)
    cfg2 = Cfg2()
    key2 = "c" * 40
    trio = preview.paths(cfg2, key2)
    trio["mp4"].write_bytes(b"0123456789")
    trio["json"].write_text(json.dumps({"impl": preview.IMPL, "sourceId": "s1"}), encoding="utf-8")
    trio["ok"].write_text("ok", encoding="utf-8")
    removed = cleanup.enforce(cfg2, Db([{"id": "s1", "last_access": __import__("time").time()}]))
    check("a preview whose source is active is not evicted", removed == 0 and trio["mp4"].exists(), removed)
    removed = cleanup.enforce(cfg2, Db([]))
    check("an idle preview is evicted as a trio",
          removed >= 1 and not trio["mp4"].exists() and not trio["json"].exists() and not trio["ok"].exists(),
          (removed, trio["mp4"].exists(), trio["json"].exists(), trio["ok"].exists()))
    # A preview that a running build is producing must not be evicted, and it must fall
    # back into the LRU once the job is gone.
    class Jobs:
        def __init__(self, rows):
            self.rows = rows

        def list(self):
            return self.rows

    key3 = "e" * 40
    trio3 = preview.paths(cfg2, key3)
    trio3["mp4"].write_bytes(b"0123456789")
    trio3["json"].write_text(json.dumps({"impl": preview.IMPL, "sourceId": "s2"}), encoding="utf-8")
    trio3["ok"].write_text("ok", encoding="utf-8")
    running = Jobs([{"status": "running", "sourceId": "s2"}])
    removed = cleanup.enforce(cfg2, Db([]), job_manager=running)
    check("a preview being built is not evicted", removed == 0 and trio3["mp4"].exists(), removed)
    finished = Jobs([{"status": "done", "sourceId": "s2"}])
    removed = cleanup.enforce(cfg2, Db([]), job_manager=finished)
    check("the same preview is evicted after the job ends", removed >= 1 and not trio3["mp4"].exists(), removed)

    # only old temporaries are swept; a fresh one belongs to a build in progress
    fresh = root2 / "work" / "preview" / ("f" * 40 + ".abc.part.mp4")
    fresh.write_bytes(b"x")
    cleanup.remove_orphans(cfg2, max_age_seconds=3600)
    check("a fresh .part is kept (a build may be using it)", fresh.exists())
    fresh.unlink()

    # abandoned build output is swept by the startup orphan pass
    orphan = root2 / "work" / "preview" / ("d" * 40 + ".abc123.part.mp4")
    orphan.write_bytes(b"x")
    cleanup.remove_orphans(cfg2, max_age_seconds=0)
    check("an abandoned .part is swept", not orphan.exists())
finally:
    shutil.rmtree(root2, ignore_errors=True)

print("RESULT: " + ("FAIL(%d)" % fails if fails else "OK"))
sys.exit(1 if fails else 0)
