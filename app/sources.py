"""Source registration, uploads, metadata, and keyframe indexing."""
import json
import os
import shutil
import time
import uuid
from pathlib import Path

from . import ffmpeg_tools, security


def _record_from_info(source_id, path, name, origin, info):
    video = info.get("video") or {}
    audio = info.get("audio") or {}
    streams = info.get("streams") or []
    video_index = None
    for st in streams:
        if st.get("type") == "video" and not st.get("attached_pic"):
            video_index = st.get("index")
            break
    if video_index is not None:
        video_spec = str(video_index)
    elif audio and audio.get("index") is not None:
        video_spec = str(audio.get("index"))
    else:
        video_spec = "v:0"
    return {
        "id": source_id,
        "path": str(path),
        "name": name,
        "origin": origin,
        "container": info.get("container"),
        "duration_us": info.get("duration_us"),
        "size": info.get("size"),
        "width": video.get("width"),
        "height": video.get("height"),
        "fps": None,
        "video_codec": video.get("codec"),
        "audio_codec": audio.get("codec"),
        "pix_fmt": video.get("pix_fmt"),
        "index_state": "none",
        "streams": streams,
        "video_stream_index": video_index,
        "video_spec": video_spec,
        "meta": info.get("meta") or {},
        "created_at": time.time(),
        "last_access": time.time(),
    }


def _fps(info):
    video = info.get("video") or {}
    value = ffmpeg_tools.parse_fraction(video.get("avg_frame_rate")) or ffmpeg_tools.parse_fraction(video.get("r_frame_rate"))
    return value


def open_source(cfg, db, jobs, path):
    real = security.check_path(path, cfg)
    if not Path(real).is_file():
        raise FileNotFoundError(real)
    ff, fp = ffmpeg_tools.ffmpeg_paths(cfg)
    if not fp:
        raise RuntimeError("ffprobe is not available")
    info = ffmpeg_tools.summarize(ffmpeg_tools.probe(fp, real))
    if not info.get("video") and not info.get("audio"):
        raise RuntimeError("no audio or video stream found")
    existing = [s for s in db.list_sources() if os.path.normcase(s["path"]) == os.path.normcase(real)]
    if existing:
        source_id = existing[0]["id"]
        db.touch_source(source_id)
        if not existing[0].get("meta_json"):
            # Refresh metadata recorded before bit rate and detail fields existed.
            try:
                fresh = ffmpeg_tools.summarize(ffmpeg_tools.probe(fp, real))
                rec = _record_from_info(source_id, real, existing[0]["name"], existing[0]["origin"], fresh)
                rec["fps"] = _fps(fresh)
                rec["index_state"] = existing[0].get("index_state") or "none"
                rec["video_spec"] = existing[0].get("video_spec") or rec.get("video_spec")
                rec["created_at"] = existing[0].get("created_at") or time.time()
                db.upsert_source(rec)
            except Exception as exc:
                print("metadata refresh skipped: " + repr(exc))
        return db.get_source(source_id)
    source_id = uuid.uuid4().hex
    rec = _record_from_info(source_id, real, Path(real).name, "local", info)
    rec["fps"] = _fps(info)
    with db.lock:
        rec["name"] = unique_display_name(db, rec["name"])
        db.upsert_source(rec)
    if info.get("video"):
        start_index(cfg, db, jobs, source_id)
    else:
        db.set_index_state(source_id, "ready")
    return db.get_source(source_id)


SAFE_UPLOAD_EXTS = {".mp4", ".m4v", ".mov", ".mkv", ".webm", ".mp3", ".m4a", ".aac",
                    ".wav", ".flac", ".ogg", ".oga", ".opus", ".wma", ".aif", ".aiff",
                    ".avi", ".wmv", ".flv", ".ts", ".m2ts", ".mts", ".m2t", ".mpg", ".mpeg",
                    ".3gp", ".3g2", ".ogv", ".lrv", ".insv", ".insp", ".360", ".mxf",
                    ".dv", ".vob", ".rm", ".rmvb", ".f4v", ".mod", ".tod"}


def normalize_upload_ext(target, info):
    if target.suffix.lower() in SAFE_UPLOAD_EXTS:
        return target
    tokens = {tok.strip() for tok in (info.get("format_name") or "").lower().split(",")}
    name = (info.get("format_name") or "").lower()
    has_video = bool(info.get("video"))
    if "webm" in tokens:
        ext = ".webm"
    elif "matroska" in tokens:
        ext = ".mkv"
    elif "mp3" in tokens:
        ext = ".mp3"
    elif "flac" in tokens:
        ext = ".flac"
    elif "ogg" in tokens:
        ext = ".ogg"
    elif "wav" in tokens:
        ext = ".wav"
    elif "aiff" in tokens:
        ext = ".aiff"
    elif "asf" in tokens:
        ext = ".wmv" if has_video else ".wma"
    elif tokens & {"mov", "mp4", "3gp", "3g2", "mj2"}:
        ext = ".mp4"
    elif "m4a" in tokens and not has_video:
        ext = ".m4a"
    else:
        ext = ".mp4" if has_video else ".m4a"
    return target.with_suffix(ext)


def upload(cfg, db, jobs, filename, fileobj):
    safe = security_path_sanitize(filename)
    upload_dir = cfg.upload_dir / uuid.uuid4().hex
    upload_dir.mkdir(parents=True, exist_ok=True)
    target = upload_dir / safe
    free = shutil.disk_usage(str(cfg.upload_dir)).free
    if free < 1073741824:
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise ValueError("not enough free disk space to accept an upload")
    size = 0
    try:
        out = open(target, "wb")
    except OSError as exc:
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise ValueError("could not store the upload: " + str(exc))
    with out:
        while True:
            chunk = fileobj.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > int(cfg.get("maxUploadBytes", 68719476736)):
                out.close()
                shutil.rmtree(upload_dir, ignore_errors=True)
                raise ValueError("upload exceeds maxUploadBytes")
            if size > free:
                out.close()
                shutil.rmtree(upload_dir, ignore_errors=True)
                raise ValueError("upload exceeds free disk space")
            out.write(chunk)
    ff, fp = ffmpeg_tools.ffmpeg_paths(cfg)
    if not fp:
        raise RuntimeError("ffprobe is not available")
    info = ffmpeg_tools.summarize(ffmpeg_tools.probe(fp, str(target)))
    if not info.get("video") and not info.get("audio"):
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise ValueError("uploaded file is not a supported media file")
    normalized = normalize_upload_ext(target, info)
    if normalized != target:
        os.replace(str(target), str(normalized))
        target = normalized
        safe = normalized.name
    source_id = uuid.uuid4().hex
    rec = _record_from_info(source_id, target, safe, "upload", info)
    rec["fps"] = _fps(info)
    with db.lock:
        rec["name"] = unique_display_name(db, rec["name"])
        db.upsert_source(rec)
    if info.get("video"):
        start_index(cfg, db, jobs, source_id)
    else:
        db.set_index_state(source_id, "ready")
    return db.get_source(source_id)


def unique_display_name(db, name):
    """Append -2, -3, ... when another registered source already uses this display name."""
    try:
        existing = {row["name"] for row in db.list_sources()}
    except Exception:
        return name
    if name not in existing:
        return name
    if "." in name:
        stem, ext = name.rsplit(".", 1)
        ext = "." + ext
    else:
        stem, ext = name, ""
    index = 2
    while "%s-%d%s" % (stem, index, ext) in existing:
        index += 1
    return "%s-%d%s" % (stem, index, ext)


def security_path_sanitize(name):
    base = Path(name or "upload.bin").name
    cleaned = []
    for ch in base:
        if ch.isalnum() or ch in "._- ()[]":
            cleaned.append(ch)
        else:
            cleaned.append("_")
    result = "".join(cleaned).strip(" .")
    if not result:
        result = "upload.bin"
    stem = result.split(".")[0].upper()
    reserved = {"CON", "PRN", "AUX", "NUL"}
    reserved |= {"COM" + str(i) for i in range(1, 10)}
    reserved |= {"LPT" + str(i) for i in range(1, 10)}
    if stem in reserved:
        result = "_" + result
    return result[:120]


def start_index(cfg, db, jobs, source_id):
    def runner(job):
        source = db.get_source(source_id)
        if not source:
            raise RuntimeError("source not found")
        ff, fp = ffmpeg_tools.ffmpeg_paths(cfg)
        db.set_index_state(source_id, "building")
        job.update(progress=0.05, message="scanning keyframes")
        try:
            spec = source.get("video_spec") or "v:0"
            pts = ffmpeg_tools.keyframes(fp, source["path"], spec, timeout=1800)
            db.replace_keyframes(source_id, 0, pts)
            db.set_index_state(source_id, "ready")
            job.update(progress=1.0, message="keyframes ready: " + str(len(pts)))
            return {"keyframes": len(pts)}
        except Exception:
            db.set_index_state(source_id, "error")
            raise
    return jobs.create("index", source_id, runner)


def list_sources(db):
    return db.list_sources()


def delete_source(cfg, db, source_id, keep_upload=False):
    source = db.get_source(source_id)
    if not source:
        return False
    if source.get("origin") == "upload" and not keep_upload:
        parent = Path(source["path"]).parent
        shutil.rmtree(parent, ignore_errors=True)
    proxy = Path(cfg.work_dir) / "proxy" / (source_id + ".mp4")
    sprite = Path(cfg.work_dir) / "sprite" / (source_id + ".jpg")
    frames = Path(cfg.thumbs_dir) / source_id
    preview_dir = Path(cfg.work_dir) / "preview"
    if preview_dir.exists():
        import json as _json
        for meta_path in list(preview_dir.glob("*.json")):
            try:
                if str(_json.loads(meta_path.read_text(encoding="utf-8")).get("sourceId") or "") != source_id:
                    continue
            except (OSError, ValueError):
                continue
            base = meta_path.with_suffix("")
            for sibling in (meta_path, Path(str(base) + ".mp4"), Path(str(base) + ".ok")):
                try:
                    sibling.unlink(missing_ok=True)
                except OSError:
                    pass
    proxy.unlink(missing_ok=True)
    sprite.unlink(missing_ok=True)
    if frames.exists():
        shutil.rmtree(frames, ignore_errors=True)
    db.delete_source(source_id)
    return True
