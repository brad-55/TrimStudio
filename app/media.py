"""Preview media: range streaming, proxy generation, frame extraction, sprites."""
import json
import os
from pathlib import Path

from . import ffmpeg_tools
from .proc import run_ffmpeg_job

TONEMAP = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
           "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p")


def is_hdr(video):
    if not video:
        return False
    transfer = (video.get("color_transfer") or "").lower()
    if transfer in ("smpte2084", "arib-std-b67"):
        return True
    pix = (video.get("pix_fmt") or "")
    return "10" in pix or "12" in pix


def proxy_path(cfg, source_id):
    p = Path(cfg.work_dir) / "proxy"
    p.mkdir(parents=True, exist_ok=True)
    return p / (source_id + ".mp4")


def variant_for(cfg, source):
    mode = cfg.get("previewMode", "auto")
    if mode == "original":
        return "original"
    if mode == "proxy":
        return "proxy"
    streams = source.get("streams") or []
    info = streams_to_info(source)
    return "original" if ffmpeg_tools.direct_playable(info) else "proxy"


def streams_to_info(source, streams=None):
    if streams is None:
        streams = source.get("streams")
        if streams is None and source.get("streams_json"):
            try:
                streams = json.loads(source["streams_json"])
            except (TypeError, ValueError):
                streams = []
    data = streams or []
    video = None
    audio = None
    for st in data:
        if st.get("type") == "video" and not st.get("attached_pic") and video is None:
            video = st
        if st.get("type") == "audio" and audio is None:
            audio = st
    return {"container": source.get("container"), "video": video, "audio": audio, "streams": data}


def start_proxy(cfg, db, jobs, source_id):
    def runner(job):
        source = db.get_source(source_id)
        if not source:
            raise RuntimeError("source not found")
        ff, fp = ffmpeg_tools.ffmpeg_paths(cfg)
        out = proxy_path(cfg, source_id)
        info = streams_to_info(source)
        video = info.get("video") or {}
        duration = source.get("duration_us") or 0
        scale = "scale=w='if(gt(iw,ih),min(1280,iw),-2)':h='if(gt(iw,ih),-2,min(1280,ih))'"
        chain = scale
        if is_hdr(video):
            chain = TONEMAP + "," + scale
        common = ["-i", long_path(source["path"]), "-map", "0:v:0", "-map", "0:a:0?",
                  "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p"]
        if chain:
            common += ["-vf", chain]
        common += ["-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out)]
        job.update(message="building proxy")
        run_ffmpeg_job(job, ff, common, total_us=duration)
        return {"proxy": str(out), "bytes": out.stat().st_size if out.exists() else 0}
    return jobs.create("proxy", source_id, runner)


def frame_path(cfg, source_id, t_us):
    d = Path(cfg.thumbs_dir) / source_id
    d.mkdir(parents=True, exist_ok=True)
    return d / (str(int(t_us)) + ".jpg")


def long_path(path):
    text = str(path)
    if os.name == "nt" and len(text) > 240 and not text.startswith("\\\\?\\"):
        return "\\\\?\\" + text
    return text


def extract_frame(cfg, source, t_us, width=1280):
    ff, fp = ffmpeg_tools.ffmpeg_paths(cfg)
    if not streams_to_info(source).get("video"):
        raise RuntimeError("source has no video stream")
    out = frame_path(cfg, source["id"], t_us)
    if out.exists() and out.stat().st_size > 0:
        return out
    info = streams_to_info(source)
    video = info.get("video") or {}
    chain = "scale='min(" + str(width) + ",iw)':-2"
    if is_hdr(video):
        chain = TONEMAP + "," + chain
    args = ["-ss", ffmpeg_tools.format_seconds(t_us), "-i", long_path(source["path"]), "-frames:v", "1",
            "-vf", chain, "-q:v", "3", str(out)]
    rc, sout, serr = ffmpeg_tools._run([ff, "-hide_banner", "-nostdin", "-y"] + args, timeout=180)
    if rc != 0 or not out.exists():
        raise RuntimeError("frame extraction failed: " + serr.strip()[:400])
    return out


def _sample_times(source, count):
    duration = source.get("duration_us") or 0
    if duration <= 0:
        return [0]
    return [int(duration * (i + 0.5) / count) for i in range(count)]


def start_sprite(cfg, db, jobs, source_id, count=100, tile=10):
    def runner(job):
        source = db.get_source(source_id)
        if not source:
            raise RuntimeError("source not found")
        ff, fp = ffmpeg_tools.ffmpeg_paths(cfg)
        out = Path(cfg.work_dir) / "sprite" / (source_id + ".jpg")
        out.parent.mkdir(parents=True, exist_ok=True)
        duration = source.get("duration_us") or 0
        step = max(1.0, (duration / 1e6) / max(1, count))
        rows = (count + tile - 1) // tile
        chain = "fps=1/%.4f,scale=160:-2,tile=%dx%d" % (step, tile, rows)
        info = streams_to_info(source)
        if is_hdr(info.get("video")):
            chain = TONEMAP + "," + chain
        args = ["-i", long_path(source["path"]), "-vf", chain, "-frames:v", "1", "-q:v", "4", str(out)]
        run_ffmpeg_job(job, ff, args, total_us=duration)
        return {"sprite": str(out), "step": step, "tile": tile, "count": count}
    return jobs.create("sprite", source_id, runner)


def read_range(path, start, end):
    with open(path, "rb") as fh:
        fh.seek(start)
        remaining = end - start
        while remaining > 0:
            chunk = fh.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
