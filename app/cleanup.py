"""Work-area housekeeping: orphan temp files and LRU cache enforcement."""
import shutil
import time
from pathlib import Path


def _size_of(path):
    try:
        if path.is_file():
            return path.stat().st_size
    except OSError:
        return 0
    total = 0
    try:
        for item in path.rglob("*"):
            if item.is_file():
                try:
                    total += item.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def clean_stale_parts(directory, max_age_seconds=3600):
    """Remove abandoned .part files this tool wrote into an output directory."""
    removed = 0
    try:
        entries = list(Path(directory).iterdir())
    except OSError:
        return 0
    now = time.time()
    for item in entries:
        try:
            if not item.is_file():
                continue
            name = item.name
            if ".part" not in name:
                continue
            # Our temporaries carry either the legacy ".trim-" or the readable "_切出" marker.
            if ".trim-" not in name and "_切出" not in name:
                continue
            if now - item.stat().st_mtime < max_age_seconds:
                continue
            item.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def remove_orphans(cfg, max_age_seconds=3600):
    removed = 0
    work = Path(cfg.work_dir)
    now = time.time()
    for item in work.rglob("*.part"):
        try:
            if now - item.stat().st_mtime > max_age_seconds:
                item.unlink()
                removed += 1
        except OSError:
            pass
    preview_dir = work / "preview"
    if preview_dir.exists():
        for item in list(preview_dir.glob("*.part*")):
            try:
                if now - item.stat().st_mtime > max_age_seconds:
                    item.unlink()
                    removed += 1
            except OSError:
                pass
        for mp4 in list(preview_dir.glob("*.mp4")):
            ok = preview_dir / (mp4.stem + ".ok")
            try:
                if not ok.exists() and now - mp4.stat().st_mtime > max_age_seconds:
                    for sibling in (mp4, preview_dir / (mp4.stem + ".json")):
                        try:
                            sibling.unlink(missing_ok=True)
                        except OSError:
                            pass
                    removed += 1
            except OSError:
                pass
    for item in work.glob("export-*"):
        try:
            if item.is_dir() and now - item.stat().st_mtime > max_age_seconds:
                shutil.rmtree(item, ignore_errors=True)
                removed += 1
        except OSError:
            pass
    return removed


def enforce(cfg, db, job_manager=None, log=print):
    cap = int(cfg.get("workCacheBytes", 0) or 0)
    if cap <= 0:
        return 0
    work = Path(cfg.work_dir)
    try:
        free = shutil.disk_usage(str(work)).free
        if free > 0:
            cap = min(cap, int(free * 0.1))
    except OSError:
        pass
    active_window = int(cfg.get("activeWindowSeconds", 600))
    now = time.time()
    active = set()
    for source in db.list_sources():
        if now - float(source.get("last_access") or 0) < active_window:
            active.add(source["id"])
    if job_manager is not None:
        try:
            for job in job_manager.list():
                if job.get("status") in ("queued", "running") and job.get("sourceId"):
                    active.add(job["sourceId"])
        except Exception:
            pass
    candidates = []
    for path in list((work / "proxy").glob("*.mp4")) + list((work / "sprite").glob("*.jpg")):
        if path.stem in active:
            continue
        try:
            candidates.append((path.stat().st_mtime, path, _size_of(path)))
        except OSError:
            pass
    # Preview proxies are a trio (.mp4 + .json + .ok) keyed by a content hash, so they are
    # evicted as a unit.  The media endpoint touches all three on every GET, which keeps a
    # preview that is actually being played at the recent end of the LRU.
    preview_dir = work / "preview"
    if preview_dir.exists():
        import json as _json
        for mp4 in list(preview_dir.glob("*.mp4")):
            key = mp4.stem
            trio = [mp4, preview_dir / (key + ".json"), preview_dir / (key + ".ok")]
            try:
                owner = ""
                meta_path = preview_dir / (key + ".json")
                if meta_path.exists():
                    owner = str(_json.loads(meta_path.read_text(encoding="utf-8")).get("sourceId") or "")
                if owner and owner in active:
                    continue
                candidates.append((mp4.stat().st_mtime, mp4, sum(_size_of(p) for p in trio)))
            except (OSError, ValueError):
                continue
    thumbs = Path(cfg.thumbs_dir)
    if thumbs.exists():
        for d in thumbs.iterdir():
            if d.is_dir() and d.name not in active:
                try:
                    candidates.append((d.stat().st_mtime, d, _size_of(d)))
                except OSError:
                    pass
    total = sum(c[2] for c in candidates)
    if total <= cap:
        return 0
    candidates.sort(key=lambda c: c[0])
    removed = 0
    for _, path, size in candidates:
        if total <= cap:
            break
        try:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            elif path.parent.name == "preview" and path.suffix == ".mp4":
                for sibling in (path, path.with_suffix(".json"), path.with_suffix(".ok")):
                    try:
                        sibling.unlink(missing_ok=True)
                    except OSError:
                        pass
            else:
                path.unlink(missing_ok=True)
            total -= size
            removed += 1
        except OSError:
            pass
    if removed and log:
        log("work cache enforced: removed " + str(removed) + " item(s)")
    return removed
