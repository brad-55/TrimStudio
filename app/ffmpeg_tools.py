"""ffmpeg/ffprobe discovery, bootstrap, probing, and command helpers."""
import hashlib
import json
import os
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

MP4_VIDEO = {"h264", "hevc", "mpeg4", "av1", "vp9", "mjpeg"}
MP4_AUDIO = {"aac", "mp3", "ac3", "eac3", "alac", "opus"}
MOV_VIDEO = MP4_VIDEO | {"prores", "dnxhd", "rawvideo"}
MOV_AUDIO = MP4_AUDIO | {"pcm_s16le", "pcm_s24le", "pcm_s16be", "pcm_s24be", "pcm_s32le",
                           "pcm_s32be", "pcm_f32le", "pcm_f64le", "pcm_u8", "pcm_s8"}
MKV_VIDEO = MP4_VIDEO | MOV_VIDEO | {"theora", "mpeg2video", "vp8"}
MKV_AUDIO = MP4_AUDIO | MOV_AUDIO | {"vorbis", "flac", "dts", "truehd"}
WEBM_VIDEO = {"vp8", "vp9", "av1"}
WEBM_AUDIO = {"opus", "vorbis"}

AUDIO_CONTAINERS = {"mp3", "ipod", "adts", "wav", "flac", "ogg", "asf", "aiff"}
AUDIO_CONTAINER_CODECS = {
    "mp3": {"mp3"},
    "ipod": {"aac", "alac", "mp3"},
    "adts": {"aac"},
    "wav": {"pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_u8", "pcm_s8", "pcm_f32le", "pcm_f64le",
            "pcm_s16be", "pcm_s24be", "pcm_s32be", "pcm_alaw", "pcm_mulaw"},
    "flac": {"flac"},
    "ogg": {"vorbis", "opus", "flac"},
    "asf": {"wmav1", "wmav2", "wmapro", "wmalossless", "wmavoice", "pcm_s16le", "pcm_s24le"},
    "aiff": {"pcm_s16be", "pcm_s24be", "pcm_s32be", "pcm_s16le", "pcm_s24le", "pcm_s32le",
             "pcm_u8", "pcm_s8", "pcm_f32le", "pcm_alaw", "pcm_mulaw"},
}

MP4_SUB = {"mov_text"}
MKV_SUB = {"subrip", "ass", "ssa", "mov_text", "webvtt", "hdmv_pgs_subtitle"}


def _no_window_kwargs():
    if os.name == "nt":
        return {"creationflags": CREATE_NO_WINDOW}
    return {}


def _run(cmd, timeout=None):
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, **_no_window_kwargs())
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def format_seconds(us):
    return "%.9f" % (int(us) / 1000000.0)


def ffmpeg_paths(cfg):
    tools = Path(cfg.tools_dir) / "ffmpeg" / "bin"
    suffix = ".exe" if os.name == "nt" else ""
    ff = tools / ("ffmpeg" + suffix)
    fp = tools / ("ffprobe" + suffix)
    if ff.exists() and fp.exists():
        return str(ff), str(fp)
    wf = shutil.which("ffmpeg")
    wp = shutil.which("ffprobe")
    if wf and wp:
        return wf, wp
    return None, None


def ffmpeg_version(ff):
    if not ff:
        return None
    rc, out, err = _run([ff, "-version"], timeout=30)
    if rc != 0:
        return None
    first = (out or err).splitlines()
    return first[0] if first else None


def ensure_ffmpeg(cfg, log=print):
    ff, fp = ffmpeg_paths(cfg)
    if ff:
        return ff, fp
    info = cfg.get("ffmpeg") or {}
    url = info.get("url")
    sha = (info.get("sha256") or "").lower()
    if not url or not sha:
        raise RuntimeError("ffmpeg is not installed and no pinned download is configured")
    tools = Path(cfg.tools_dir) / "ffmpeg"
    tools.mkdir(parents=True, exist_ok=True)
    zip_path = tools / "download.zip"
    log("downloading ffmpeg " + str(info.get("version")) + " from " + url)
    with urllib.request.urlopen(url, timeout=180) as resp, open(zip_path, "wb") as fh:
        shutil.copyfileobj(resp, fh)
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest().lower()
    if digest != sha:
        zip_path.unlink(missing_ok=True)
        raise RuntimeError("ffmpeg checksum mismatch: expected " + sha + " got " + digest)
    bin_dir = tools / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    wanted = {"ffmpeg.exe", "ffprobe.exe"} if os.name == "nt" else {"ffmpeg", "ffprobe"}
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            base = Path(member).name.lower()
            if base in wanted:
                with zf.open(member) as src, open(bin_dir / base, "wb") as dst:
                    shutil.copyfileobj(src, dst)
    zip_path.unlink(missing_ok=True)
    ff, fp = ffmpeg_paths(cfg)
    if not ff:
        raise RuntimeError("ffmpeg bootstrap failed")
    log("ffmpeg installed at " + ff)
    return ff, fp


def probe(fp, path, timeout=180):
    rc, out, err = _run([fp, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                        timeout=timeout)
    if rc != 0:
        raise RuntimeError("ffprobe failed: " + err.strip()[:500])
    return json.loads(out)


def parse_fraction(value):
    if not value or value == "0/0":
        return None
    if "/" in value:
        num, den = value.split("/", 1)
        try:
            den_f = float(den)
            return (float(num) / den_f) if den_f else None
        except ValueError:
            return None
    try:
        return float(value)
    except ValueError:
        return None


def summarize(data):
    fmt = data.get("format") or {}
    streams = []
    for st in data.get("streams") or []:
        disp = st.get("disposition") or {}
        streams.append({
            "index": st.get("index"),
            "type": st.get("codec_type"),
            "codec": st.get("codec_name"),
            "profile": st.get("profile"),
            "width": st.get("width"),
            "height": st.get("height"),
            "pix_fmt": st.get("pix_fmt"),
            "color_transfer": st.get("color_transfer"),
            "color_primaries": st.get("color_primaries"),
            "color_space": st.get("color_space"),
            "bits_per_raw_sample": st.get("bits_per_raw_sample"),
            "avg_frame_rate": st.get("avg_frame_rate"),
            "r_frame_rate": st.get("r_frame_rate"),
            "time_base": st.get("time_base"),
            "channels": st.get("channels"),
            "channel_layout": st.get("channel_layout"),
            "sample_rate": st.get("sample_rate"),
            "codec_long_name": st.get("codec_long_name"),
            "level": st.get("level"),
            "field_order": st.get("field_order"),
            "bit_rate": int(st["bit_rate"]) if str(st.get("bit_rate", "")).isdigit() else None,
            "nb_frames": int(st["nb_frames"]) if str(st.get("nb_frames", "")).isdigit() else None,
            "duration_us": int(round(float(st["duration"]) * 1e6)) if str(st.get("duration", "")).replace(".", "", 1).isdigit() else None,
            "start_time": st.get("start_time"),
            "attached_pic": bool(disp.get("attached_pic")),
            "default": bool(disp.get("default")),
            "forced": bool(disp.get("forced")),
            "tags": st.get("tags") or {},
        })
    video = None
    for st in streams:
        if st["type"] == "video" and not st["attached_pic"]:
            video = st
            break
    audio = None
    for st in streams:
        if st["type"] == "audio":
            audio = st
            break
    duration = None
    try:
        duration = float(fmt.get("duration"))
    except (TypeError, ValueError):
        duration = None
    fps = parse_fraction(video.get("avg_frame_rate")) if video else None
    if not fps and video:
        fps = parse_fraction(video.get("r_frame_rate"))
    sample_rate = None
    if audio and audio.get("sample_rate"):
        try:
            sample_rate = int(audio["sample_rate"])
        except ValueError:
            sample_rate = None
    kind = "video" if video else ("audio" if audio else "other")
    fmt_bit_rate = int(fmt["bit_rate"]) if str(fmt.get("bit_rate", "")).isdigit() else None
    if fmt_bit_rate is None and duration:
        try:
            fmt_bit_rate = int(round(int(fmt.get("size")) * 8 / duration))
        except (TypeError, ValueError, ZeroDivisionError):
            fmt_bit_rate = None
    meta = {
        "format_name": fmt.get("format_name"),
        "format_long_name": fmt.get("format_long_name"),
        "nb_streams": fmt.get("nb_streams"),
        "bit_rate": fmt_bit_rate,
        "start_time": fmt.get("start_time"),
        "probe_score": fmt.get("probe_score"),
        "tags": fmt.get("tags") or {},
    }
    return {
        "kind": kind,
        "meta": meta,
        "bit_rate": fmt_bit_rate,
        "video_bit_rate": video.get("bit_rate") if video else None,
        "audio_bit_rate": audio.get("bit_rate") if audio else None,
        "container": (fmt.get("format_name") or "").split(",")[0],
        "format_name": fmt.get("format_name"),
        "duration_us": int(round(duration * 1e6)) if duration is not None else None,
        "size": int(fmt.get("size")) if fmt.get("size") else None,
        "paths": [video["index"]] if video else [],
        "video": video,
        "audio": audio,
        "sample_rate": sample_rate,
        "streams": streams,
    }


def keyframes(fp, path, stream_spec, timeout=900):
    cmd = [fp, "-v", "error", "-select_streams", stream_spec, "-show_packets",
           "-show_entries", "packet=pts,pts_time,dts_time,flags", "-of", "json", str(path)]
    rc, out, err = _run(cmd, timeout=timeout)
    if rc != 0:
        raise RuntimeError("ffprobe keyframes failed: " + err.strip()[:500])
    packets = json.loads(out).get("packets") or []
    values = []
    for pkt in packets:
        if "K" not in (pkt.get("flags") or ""):
            continue
        t = pkt.get("pts_time")
        if t is None:
            continue
        try:
            pts = int(round(float(t) * 1e6))
        except (TypeError, ValueError):
            continue
        try:
            dts = float(pkt.get("dts_time"))
        except (TypeError, ValueError):
            dts = float(t)
        values.append((dts, pts))
    values.sort(key=lambda item: item[0])
    return [pts for _dts, pts in values]


def frame_times(fp, path, stream_spec, start_us, duration_us, max_count, timeout=180):
    start_sec = max(0.0, start_us / 1e6)
    duration_sec = max(0.05, duration_us / 1e6)
    interval = "%.6f%%+%.6f" % (start_sec, duration_sec)
    cmd = [fp, "-v", "error", "-select_streams", stream_spec, "-read_intervals", interval,
           "-show_frames", "-show_entries", "frame=pts_time", "-of", "json", str(path)]
    rc, out, err = _run(cmd, timeout=timeout)
    if rc != 0:
        raise RuntimeError("ffprobe frames failed: " + err.strip()[:500])
    frames = json.loads(out).get("frames") or []
    values = []
    for fr in frames:
        t = fr.get("pts_time")
        if t is None:
            continue
        try:
            values.append(int(round(float(t) * 1e6)))
        except (TypeError, ValueError):
            continue
    values.sort()
    return values[:max_count]


def copy_compatibility(stream, container):
    ctype = stream.get("type")
    codec = stream.get("codec")
    if container in ("mp4", "m4v", "mov"):
        if ctype == "video":
            return codec in (MOV_VIDEO if container == "mov" else MP4_VIDEO)
        if ctype == "audio":
            return codec in (MOV_AUDIO if container == "mov" else MP4_AUDIO)
        if ctype == "subtitle":
            return codec in MP4_SUB
        return False
    if container == "matroska" or container == "webm":
        if container == "webm":
            if ctype == "video":
                return codec in WEBM_VIDEO
            if ctype == "audio":
                return codec in WEBM_AUDIO
            return False
        # Matroska accepts virtually every video and audio codec, so it is the safe
        # fallback container for sources that no plain container can hold.
        if ctype in ("video", "audio"):
            return True
        if ctype == "subtitle":
            return codec in MKV_SUB
        if ctype == "attachment":
            return True
        return False
    if container == "mxf":
        # The MXF muxer in this ffmpeg build only accepts these codecs (and 48kHz PCM);
        # anything else (e.g. XAVC H.264+AAC, MJPEG) must fall back to Matroska.
        if ctype == "video":
            return codec in {"mpeg2video", "h264", "dvvideo"}
        if ctype == "audio":
            if codec not in {"pcm_s16le", "pcm_s24le", "pcm_s16be", "pcm_s24be"}:
                return False
            return str(stream.get("sample_rate")) in ("48000", "48000.0", None)
        return False
    if container in AUDIO_CONTAINERS:
        if ctype != "audio":
            return False
        allowed = AUDIO_CONTAINER_CODECS.get(container)
        return not allowed or codec in allowed
    return ctype in ("video", "audio")


def direct_playable(info):
    container = (info.get("container") or "").lower()
    video = info.get("video")
    audio = info.get("audio")
    if not video:
        if not audio:
            return False
        if container in ("mp3", "wav", "flac", "ogg"):
            return True
        if container in ("mov", "mp4", "m4a", "ipod", "adts") and audio.get("codec") in ("aac", "mp3", "alac", "flac"):
            return True
        return audio.get("codec") in ("mp3", "aac", "flac", "vorbis", "opus", "alac")
    if not video and not audio:
        return False
    if container in ("mp4", "m4v", "mov"):
        if video.get("codec") != "h264":
            return False
        if video.get("pix_fmt") not in ("yuv420p", "yuvj420p"):
            return False
        if audio and audio.get("codec") not in ("aac", "mp3"):
            return False
        return True
    if container == "webm":
        if video.get("codec") not in WEBM_VIDEO:
            return False
        if audio and audio.get("codec") not in WEBM_AUDIO:
            return False
        return True
    return False


def spawn(args, **kwargs):
    return subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace", **_no_window_kwargs(), **kwargs)
