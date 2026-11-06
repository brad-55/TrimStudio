"""Export planning and execution: lossless copy and optional re-encode."""
import ctypes
import json
import os
import shutil
import uuid
from pathlib import Path

from . import cleanup, ffmpeg_tools, security
from .media import is_hdr, streams_to_info
from .proc import run_ffmpeg_job

EXT_CONTAINER = {".mp4": "mp4", ".m4v": "mp4", ".mov": "mov", ".mkv": "matroska",
                 ".webm": "webm", ".ts": "matroska", ".m2ts": "matroska",
                 ".m4a": "ipod", ".mp3": "mp3", ".aac": "adts", ".wav": "wav",
                 ".flac": "flac", ".ogg": "ogg", ".oga": "ogg", ".opus": "ogg",
                 ".wma": "asf", ".aif": "aiff", ".aiff": "aiff", ".wmv": "asf",
                 ".avi": "avi", ".flv": "flv", ".mpg": "mpeg", ".mpeg": "mpeg", ".3gp": "mp4",
                 ".lrv": "mp4", ".insv": "mp4", ".insp": "mp4", ".360": "mp4", ".3g2": "mp4",
                 ".mxf": "mxf", ".dv": "avi", ".vob": "mpeg", ".rm": "matroska", ".rmvb": "matroska",
                 ".f4v": "flv", ".m2t": "matroska", ".mod": "mpeg", ".tod": "mpeg"}
OUTPUT_EXT = {"mp4": "mp4", "mov": "mov", "matroska": "mkv", "webm": "webm", "mp3": "mp3",
              "ipod": "m4a", "adts": "aac", "wav": "wav", "flac": "flac", "ogg": "ogg",
              "asf": "wmv", "aiff": "aiff", "avi": "avi", "flv": "flv", "mpeg": "mpg",
              "mxf": "mxf"}
LUT_EXTS = {".cube", ".3dl", ".dat"}
CHAPTER_CONTAINERS = ("mp4", "mov", "matroska")


def known_videos_dir():
    if os.name == "nt":
        try:
            import uuid as _uuid
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                            ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

                def __init__(self, value):
                    super().__init__()
                    self.Data1 = value.time_low
                    self.Data2 = value.time_mid
                    self.Data3 = value.time_hi_version
                    for i, byte in enumerate(value.bytes[8:]):
                        self.Data4[i] = byte

            folder = GUID(_uuid.UUID("{18989B1D-99B5-455B-841C-AB7C74E4DDFC}"))
            ptr = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(folder), 0, None, ctypes.byref(ptr)) == 0:
                value = ptr.value
                ctypes.windll.ole32.CoTaskMemFree(ptr)
                if value:
                    return value
        except Exception:
            pass
    return str(Path.home() / "Videos")


def long_path(path):
    text = str(path)
    if os.name == "nt" and len(text) > 255 and not text.startswith("\\\\?\\"):
        absolute = os.path.abspath(text)
        if absolute.startswith("\\\\"):
            return "\\\\?\\UNC\\" + absolute[2:]
        return "\\\\?\\" + absolute
    return text


def sanitize_name(name):
    reserved = {"CON", "PRN", "AUX", "NUL"}
    reserved |= {"COM" + str(i) for i in range(1, 10)}
    reserved |= {"LPT" + str(i) for i in range(1, 10)}
    out = []
    for ch in name:
        if ch in '<>:"/\\|?*' or ord(ch) < 32:
            out.append("_")
        else:
            out.append(ch)
    base = "".join(out).strip(" .")
    stem = Path(base).stem[:80] or "video"
    if stem.upper() in reserved:
        stem = "_" + stem
    return stem


ENCODER_LABEL = {
    "libx264": "H264", "libx265": "H265",
    "h264_nvenc": "H264-NVENC", "hevc_nvenc": "H265-NVENC",
}


def time_tag_short(us):
    """Readable, compact timecode for file names: 0s / 12s / 1m05s / 1h02m03s."""
    total_us = max(0, int(us))
    total = total_us // 1000000
    ms = (total_us // 1000) % 1000
    hours, minutes, seconds = total // 3600, (total // 60) % 60, total % 60
    parts = []
    if hours:
        parts.append("%dh" % hours)
    if hours or minutes:
        parts.append("%dm" % minutes)
    parts.append(("%d.%03ds" % (seconds, ms)) if ms else ("%ds" % seconds))
    return "".join(parts)


def export_tags(options, start_us, end_us, has_video=True):
    """Human readable summary of what the export was asked to do."""
    options = options or {}
    tags = ["切出" + time_tag_short(start_us) + "-" + time_tag_short(end_us)]
    if options.get("mode") == "reencode":
        tags.append("再エンコード" if has_video else "音声再エンコード")
        label = ENCODER_LABEL.get(str(options.get("encoder") or ""))
        if label and has_video:
            tags.append(label)
        try:
            vbr = int(options.get("videoBitrate") or 0)
        except (TypeError, ValueError):
            vbr = 0
        if vbr > 0 and has_video:
            tags.append("%dkbps" % vbr)
        try:
            abr = int(options.get("audioBitrate") or 0)
        except (TypeError, ValueError):
            abr = 0
        if abr > 0:
            tags.append("音声%dkbps" % abr)
        if options.get("audioReencode") and has_video:
            tags.append("音声再圧縮")
        if options.get("lut"):
            tags.append("LUT")
        if options.get("stabilize"):
            tags.append("手ブレ補正")
        crop = options.get("crop")
        if crop:
            try:
                tags.append("切抜%dx%d" % (int(crop["w"]), int(crop["h"])))
            except (KeyError, TypeError, ValueError):
                tags.append("切抜")
    else:
        tags.append("無変換")
    return "_".join(tags)


def time_tag(us):
    total = int(max(0, us) // 1000)
    ms = total % 1000
    seconds = total // 1000
    return "%02dh%02dm%02ds%03d" % (seconds // 3600, (seconds // 60) % 60, seconds % 60, ms)


def video_streams(streams):
    result = []
    for st in streams:
        if st.get("type") == "video" and not st.get("attached_pic"):
            result.append(st)
    return result


def source_container(source):
    ext = Path(source["path"]).suffix.lower()
    return EXT_CONTAINER.get(ext, "matroska")


ALLOWED_CONTAINERS = {"mp4", "mov", "matroska", "webm", "ipod", "mp3", "adts", "wav", "flac",
                     "ogg", "asf", "aiff", "mxf", "mpeg", "avi", "flv"}
SINGLE_AUDIO_CONTAINERS = {"mp3", "adts", "wav", "flac", "aiff"}


def sanitize_dir_name(name):
    """Sanitize a single directory component without dropping any extension-like suffix."""
    cleaned = []
    for ch in str(name or ""):
        if ch.isalnum() or ch in "._- ()[]":
            cleaned.append(ch)
        else:
            cleaned.append("_")
    result = "".join(cleaned).strip(" .")
    if not result:
        return None
    head = result.split(".")[0].upper()
    reserved = {"CON", "PRN", "AUX", "NUL"}
    reserved |= {"COM" + str(i) for i in range(1, 10)}
    reserved |= {"LPT" + str(i) for i in range(1, 10)}
    if head in reserved:
        result = "_" + result
    return result[:120]


def decide_streams(source, streams, preferred=None):
    chosen = video_streams(streams)
    include = list(chosen[:1])
    for st in streams:
        if st in include:
            continue
        if st.get("type") in ("audio", "subtitle"):
            include.append(st)
    if preferred:
        if preferred not in ALLOWED_CONTAINERS:
            raise ValueError("未知のコンテナです: " + str(preferred))
        if preferred in SINGLE_AUDIO_CONTAINERS:
            audio_only = len(include) == 1 and include and include[0].get("type") == "audio"
            if not audio_only:
                raise ValueError("このコンテナは音声ストリーム1本のみ格納できます: " + str(preferred))
        if all(ffmpeg_tools.copy_compatibility(st, preferred) for st in include):
            return preferred, include, []
        raise ValueError("選択したコンテナには格納できないストリームがあります: " + str(preferred))
    candidates = [source_container(source), "matroska", "mp4", "mov", "webm"]
    if not chosen:
        candidates = [source_container(source), "ipod", "ogg", "mp3", "flac", "wav", "adts", "matroska"]
    for container in candidates:
        if all(ffmpeg_tools.copy_compatibility(st, container) for st in include):
            return container, include, []
    container = source_container(source)
    selected = [st for st in include if ffmpeg_tools.copy_compatibility(st, container)]
    excluded = [st for st in streams if st not in selected]
    return container, selected, excluded


def actual_range(db, source, start_us, end_us, in_snap, out_mode):
    keyframes = db.get_keyframes(source["id"], 0)
    if not keyframes:
        raise ValueError("keyframe index is not ready yet")
    fallback = False
    if in_snap == "next":
        later = [k for k in keyframes if k >= start_us]
        if not later or later[0] >= end_us:
            fallback = True
            earlier = [k for k in keyframes if k <= start_us]
            actual_start = earlier[-1] if earlier else keyframes[0]
        else:
            actual_start = later[0]
    else:
        earlier = [k for k in keyframes if k <= start_us]
        actual_start = earlier[-1] if earlier else keyframes[0]
    if out_mode == "keyframeBefore":
        earlier = [k for k in keyframes if k <= end_us]
        actual_end = earlier[-1] if earlier else end_us
    elif out_mode == "keyframeAfter":
        later = [k for k in keyframes if k >= end_us]
        actual_end = later[0] if later else end_us
    else:
        actual_end = end_us
    if actual_end <= actual_start:
        raise ValueError("end must be after start")
    return actual_start, actual_end, fallback


def output_path_for(source, start_us, end_us, container, explicit=None, has_video=True, options=None):
    ext = OUTPUT_EXT.get(container, "mkv")
    if container == "asf":
        # ASF holds both WMV and WMA; name the output for what it actually carries.
        ext = "wmv" if has_video else "wma"
    stem = sanitize_name(Path(source["path"]).name)
    if options is None:
        tail = "trim-" + time_tag(start_us) + "-" + time_tag(end_us)
    else:
        tail = export_tags(options, start_us, end_us, has_video)
    # sanitize_name already caps the original name at 80 chars and the tags stay short,
    # so the readable settings always survive; _fit_length below is the final guard.
    name = stem + "_" + tail + "." + ext
    if explicit:
        target = Path(explicit)
        if target.is_dir() or str(explicit).endswith(("/", chr(92))):
            target = target / name
    else:
        if source.get("origin") == "upload":
            out_dir = Path(known_videos_dir())
        else:
            out_dir = Path(source["path"]).parent
        target = out_dir / name
    if target.suffix.lower() != "." + ext:
        target = target.with_suffix("." + ext)
    target = _fit_length(target, 240)
    return _avoid_collision(target)


def _avoid_collision(target):
    candidate = target
    index = 1
    while candidate.exists():
        candidate = target.with_name(target.stem + "-" + str(index) + target.suffix)
        index += 1
    return candidate


def _fit_length(path, max_len=240):
    text = str(path)
    if len(text) <= max_len:
        return path
    suffix = path.suffix
    parent = str(path.parent)
    keep = max(8, max_len - len(parent) - len(suffix) - 2)
    return path.with_name(path.stem[:keep] + suffix)


def plan(cfg, db, source, start_us, end_us, options):
    streams = json.loads(source.get("streams_json") or "[]")
    container, selected, excluded = decide_streams(source, streams, options.get("container"))
    kind = "video" if video_streams(streams) else (
        "audio" if any(st.get("type") == "audio" for st in streams) else "other")
    mode = options.get("mode", "lossless")
    fallback = False
    seek_us = start_us
    if mode == "reencode":
        actual_start, actual_end = start_us, end_us
    elif kind == "audio":
        if end_us <= start_us:
            raise ValueError("end must be after start")
        actual_start, actual_end, fallback = start_us, end_us, False
        seek_us = start_us
    else:
        actual_start, actual_end, fallback = actual_range(
            db, source, start_us, end_us, options.get("inSnap", "prev"), options.get("outMode", "exact"))
        keyframes = db.get_keyframes(source["id"], 0)
        earlier = [k for k in keyframes if k < actual_start]
        if earlier:
            seek_us = (earlier[-1] + actual_start) // 2
        else:
            # No preceding keyframe. The first keyframe can carry a negative DTS
            # because of B-frame reordering, so seeking exactly at it would drop it;
            # seek one second earlier so ffmpeg clamps to zero and keeps it intact.
            seek_us = actual_start - 1000000
    has_video = any(st.get("type") == "video" for st in selected)
    out = output_path_for(source, actual_start, actual_end, container, options.get("outputPath"), has_video, options)
    warnings = []
    for st in excluded:
        warnings.append("stream " + str(st.get("index")) + " (" + str(st.get("type")) + "/" + str(st.get("codec")) + ") was excluded as incompatible")
    if fallback:
        warnings.append("inSnap=next had no room before endUs; fell back to prev keyframe")
    return {"selected": selected, "excluded": excluded, "container": container, "kind": kind,
            "actualStartUs": actual_start, "actualEndUs": actual_end, "seekUs": seek_us,
            "outputPath": str(out), "warnings": warnings, "fallback": fallback}


def build_audio_copy_args(source, out, selected, start_us, end_us, container=""):
    args = ["-i", long_path(source["path"]), "-ss", ffmpeg_tools.format_seconds(start_us),
            "-t", ffmpeg_tools.format_seconds(max(0, end_us - start_us))]
    for st in selected:
        args += ["-map", "0:" + str(st["index"])]
    if container == "flac":
        # Stream copy leaves the source STREAMINFO total-sample count in place, so the
        # header would still claim the full source length. FLAC re-encoding is bit exact.
        args += ["-c:a", "flac"]
    else:
        args += ["-c", "copy"]
    if container in ("ipod", "mp4", "mov"):
        args += ["-movflags", "+faststart"]
    args += ["-map_metadata", "0", "-avoid_negative_ts", "make_zero", long_path(out)]
    return args


def _video_cut_args(source, out, video_selected, seek_us, end_us):
    # Output-side seek starts at the first keyframe strictly after the value, so the
    # video pass seeks from the midpoint between the previous keyframe and the start
    # keyframe to land exactly on the requested start.
    args = ["-i", long_path(source["path"]), "-ss", ffmpeg_tools.format_seconds(seek_us),
            "-t", ffmpeg_tools.format_seconds(max(0, end_us - seek_us))]
    for st in video_selected:
        args += ["-map", "0:" + str(st["index"])]
    args += ["-c", "copy", "-map_metadata", "0", "-avoid_negative_ts", "make_zero", long_path(out)]
    return args


def _av_cut_args(source, out, other_selected, start_us, end_us):
    # Audio/subtitle packets are independently decodable, so a plain output seek at
    # the true start time cuts them correctly in one pass.
    args = ["-i", long_path(source["path"]), "-ss", ffmpeg_tools.format_seconds(start_us),
            "-t", ffmpeg_tools.format_seconds(max(0, end_us - start_us))]
    for st in other_selected:
        args += ["-map", "0:" + str(st["index"])]
    args += ["-c", "copy", "-avoid_negative_ts", "make_zero", long_path(out)]
    return args


def _mux_args(video_tmp, av_tmp, out, container, start_us):
    # Shift every input by -startUs so the first retained packet lands at zero; this
    # keeps video and audio aligned without touching their codec payloads.
    offset = ffmpeg_tools.format_seconds(-start_us)
    args = ["-itsoffset", offset, "-i", long_path(video_tmp)]
    if av_tmp:
        args += ["-itsoffset", offset, "-i", long_path(av_tmp), "-map", "0", "-map", "1"]
    else:
        args += ["-map", "0"]
    args += ["-c", "copy", "-map_metadata", "0", "-avoid_negative_ts", "make_zero"]
    if container in CHAPTER_CONTAINERS:
        args += ["-map_chapters", "0"]
    if container in ("mp4", "mov"):
        args += ["-movflags", "+faststart"]
    args += [long_path(out)]
    return args


REENCODE_AUDIO_CODECS = {"mp4": "aac", "mov": "aac", "matroska": "aac", "webm": "libopus",
                         "ogg": "libopus", "asf": "wmav2", "ipod": "aac", "adts": "aac",
                         "mp3": "libmp3lame", "wav": "pcm_s16le", "flac": "flac", "aiff": "pcm_s16le",
                         "avi": "libmp3lame", "flv": "libmp3lame", "mpeg": "mp2"}
LOSSLESS_AUDIO_CODECS = {"flac", "pcm_s16le"}


def audio_reencode_args(container, kbps):
    codec = REENCODE_AUDIO_CODECS.get(container, "aac")
    if codec in LOSSLESS_AUDIO_CODECS:
        return ["-c:a", codec]
    return ["-c:a", codec, "-b:a", "%dk" % kbps]


def build_audio_reencode_args(source, out, selected, container, start_us, end_us, options):
    args = ["-i", long_path(source["path"]), "-ss", ffmpeg_tools.format_seconds(start_us),
            "-t", ffmpeg_tools.format_seconds(max(0, end_us - start_us))]
    for st in selected:
        args += ["-map", "0:" + str(st["index"])]
    audio = None
    for st in selected:
        if st.get("type") == "audio":
            audio = st
            break
    args += audio_reencode_args(container, _audio_bitrate(options, audio))
    args += ["-map_metadata", "0", long_path(out)]
    return args


def _bitrate_option(options, key):
    value = options.get(key)
    if value in (None, "", 0, "0"):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def video_rotation(cfg, source, video):
    """Display rotation in degrees for the crop maths.

    Records created before the rotation field existed have no stored value, so
    fall back to a fresh ffprobe of the source file.
    """
    if isinstance(video, dict) and "rotation" in video:
        return int(video.get("rotation") or 0)
    try:
        _ff, fp = ffmpeg_tools.ffmpeg_paths(cfg)
        data = ffmpeg_tools.probe(fp, source["path"])
        info = ffmpeg_tools.summarize(data)
        st = next((x for x in info.get("streams", [])
                   if x.get("type") == "video" and not x.get("attached_pic")), None)
        return int((st or {}).get("rotation") or 0)
    except Exception:
        return 0


def encoder_plan(options, source):
    info = streams_to_info(source)
    video = info.get("video") or {}
    encoder = options.get("encoder", "libx264")
    ten_bit = is_hdr(video) or "10" in (video.get("pix_fmt") or "")
    kbps = _bitrate_option(options, "videoBitrate")
    rate = ["-b:v", "%dk" % kbps, "-maxrate", "%dk" % kbps, "-bufsize", "%dk" % (kbps * 2)] if kbps else None
    if encoder == "libx264":
        args = ["-c:v", "libx264", "-preset", "slow", "-pix_fmt", "yuv420p",
                "-tune", "film", "-profile:v", "high"] + (rate or ["-crf", "16"])
        return args, "yuv420p"
    if encoder == "libx265":
        pix = "yuv420p10le" if ten_bit else "yuv420p"
        args = ["-c:v", "libx265", "-preset", "medium", "-pix_fmt", pix, "-tag:v", "hvc1"] + (rate or ["-crf", "18"])
        return args, pix
    if encoder == "h264_nvenc":
        args = ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-pix_fmt", "yuv420p"] + (rate or ["-cq", "19"])
        return args, "yuv420p"
    if encoder == "hevc_nvenc":
        # p010le only for 10-bit/HDR sources: an 8-bit source must stay 8-bit
        # (10-bit output doubles the cost, breaks browser preview and adds nothing).
        pix = "p010le" if ten_bit else "yuv420p"
        args = ["-c:v", "hevc_nvenc", "-preset", "p5", "-rc", "vbr", "-pix_fmt", pix] + (rate or ["-cq", "21"])
        return args, pix
    args = ["-c:v", "libx264", "-pix_fmt", "yuv420p"] + (rate or ["-crf", "18"])
    return args, "yuv420p"


def _audio_bitrate(options, audio):
    kbps = _bitrate_option(options, "audioBitrate")
    if kbps:
        return kbps
    source_rate = (audio or {}).get("bit_rate")
    try:
        if source_rate:
            return max(32, int(round(int(source_rate) / 1000.0)))
    except (TypeError, ValueError):
        pass
    return 192


def build_reencode_args(cfg, source, out, container, selected, start_us, end_us, options):
    work = Path(cfg.work_dir) / ("export-" + uuid.uuid4().hex)
    work.mkdir(parents=True, exist_ok=True)
    info = streams_to_info(source)
    video = info.get("video") or {}
    encoder_args, final_pix = encoder_plan(options, source)
    lut_name = None
    if options.get("lut"):
        lut_path = Path(options["lut"])
        if not lut_path.is_file():
            raise FileNotFoundError(str(lut_path))
        if not security.is_within(lut_path, cfg.luts_dir):
            raise PermissionError("LUT must be inside " + str(cfg.luts_dir))
        if lut_path.suffix.lower() not in LUT_EXTS:
            raise ValueError("unsupported LUT extension: " + lut_path.suffix)
        lut_name = "lut" + lut_path.suffix.lower()
        shutil.copyfile(lut_path, work / lut_name)
    crop_filter = None
    if options.get("crop"):
        crop = options["crop"]
        width = max(2, int(crop["w"]) & ~1)
        height = max(2, int(crop["h"]) & ~1)
        src_w = int(video.get("width") or width)
        src_h = int(video.get("height") or height)
        # The UI frames the crop on the rotated (display) picture and ffmpeg
        # autorotates before the filters, so clamp/offset in display orientation.
        if video_rotation(cfg, source, video) % 180 == 90:
            disp_w, disp_h = src_h, src_w
        else:
            disp_w, disp_h = src_w, src_h
        width = min(width, disp_w & ~1)
        height = min(height, disp_h & ~1)
        x = max(0, min(int(crop["x"]) & ~1, disp_w - width))
        y = max(0, min(int(crop["y"]) & ~1, disp_h - height))
        crop_filter = "crop=%d:%d:%d:%d" % (width, height, x, y)
    lut_filter = None
    if lut_name:
        lut_filter = "format=gbrp16le,lut3d=file=" + lut_name + ",format=" + final_pix
    order = options.get("order") or ["stabilize", "crop", "lut"]
    filters = []
    detect_pre = []
    seen_stabilize = False
    for key in order:
        value = None
        if key == "stabilize" and options.get("stabilize"):
            value = "vidstabtransform=input=transforms.trf:optzoom=2:smoothing=15"
        elif key == "crop" and crop_filter:
            value = crop_filter
        elif key == "lut" and lut_filter:
            value = lut_filter
        if not value:
            continue
        filters.append(value)
        if key == "stabilize":
            seen_stabilize = True
        elif not seen_stabilize:
            detect_pre.append(value)
    args = ["-ss", ffmpeg_tools.format_seconds(start_us), "-i", long_path(source["path"]),
            "-t", ffmpeg_tools.format_seconds(end_us - start_us)]
    for st in selected:
        if st.get("type") != "subtitle":
            args += ["-map", "0:" + str(st["index"])]
    if filters:
        args += ["-vf", ",".join(filters)]
    args += encoder_args
    audio = None
    for st in selected:
        if st.get("type") == "audio":
            audio = st
            break
    audio_copy_ok = bool(audio) and ffmpeg_tools.copy_compatibility(audio, container)
    if options.get("audioReencode") or (audio and not audio_copy_ok):
        args += audio_reencode_args(container, _audio_bitrate(options, audio))
    else:
        args += ["-c:a", "copy"]
    if lut_name and not options.get("keepColorTags"):
        args += ["-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", "-color_range", "tv"]
    if container in ("mp4", "mov"):
        args += ["-movflags", "+faststart"]
    args += [long_path(out)]
    detect = None
    if options.get("stabilize"):
        detect = ["-ss", ffmpeg_tools.format_seconds(start_us), "-i", long_path(source["path"]),
                  "-t", ffmpeg_tools.format_seconds(end_us - start_us)]
        detect_filters = list(detect_pre) + ["vidstabdetect=result=transforms.trf:shakiness=5"]
        detect += ["-vf", ",".join(detect_filters), "-an", "-f", "null", "-"]
    return args, detect, work


def start_export(cfg, db, jobs, source, start_us, end_us, options):
    def runner(job):
        built = plan(cfg, db, source, start_us, end_us, options)
        explicit = bool(options.get("outputPath"))
        out = Path(built["outputPath"])
        out_dir = out.parent
        try:
            cleanup.clean_stale_parts(out_dir)
        except Exception:
            pass
        can_write, why = writable_probe(out_dir)
        if not can_write and not explicit:
            # The default location (source folder) is not writable here (e.g. the server
            # runs under a sandbox that only allows the workspace). Fall back to a writable
            # default and report it as a warning instead of failing the export.
            for fallback in (Path(known_videos_dir()), Path(cfg.data_dir) / "exports"):
                try:
                    fallback.mkdir(parents=True, exist_ok=True)
                except OSError:
                    continue
                except Exception:
                    continue
                ok2, _why2 = writable_probe(fallback)
                if ok2:
                    out = _avoid_collision(fallback / out.name)
                    built = dict(built)
                    built["outputPath"] = str(out)
                    built["warnings"] = list(built.get("warnings") or []) + [
                        "既定の出力先が書き込めないため " + str(fallback) + " に変更しました"]
                    out_dir = out.parent
                    can_write = True
                    break
        if not can_write:
            raise RuntimeError(
                "出力先に書き込めません: " + str(out_dir) + " (" + why + ")。"
                "フォルダの書き込み権限を確認するか、別の出力先を指定してください。")
        out.parent.mkdir(parents=True, exist_ok=True)
        temp = out.with_name(out.stem + ".part" + out.suffix)
        ff, fp = ffmpeg_tools.ffmpeg_paths(cfg)
        reencode = options.get("mode") == "reencode"
        work = None
        total = built["actualEndUs"] - built["actualStartUs"]
        try:
            if reencode and built["kind"] == "audio":
                args = build_audio_reencode_args(source, temp, built["selected"], built["container"],
                                                 built["actualStartUs"], built["actualEndUs"], options)
                job.update(message="re-encoding audio")
                run_ffmpeg_job(job, ff, args, total_us=total)
            elif reencode:
                args, detect, work = build_reencode_args(cfg, source, temp, built["container"], built["selected"],
                                                         built["actualStartUs"], built["actualEndUs"], options)
                if detect is not None:
                    job.update(message="stabilizer analysis pass")
                    run_ffmpeg_job(job, ff, detect, total_us=total, cwd=str(work))
                job.update(message="re-encoding")
                run_ffmpeg_job(job, ff, args, total_us=total, cwd=str(work))
            elif built["kind"] == "audio":
                args = build_audio_copy_args(source, temp, built["selected"],
                                             built["actualStartUs"], built["actualEndUs"],
                                             built["container"])
                job.update(message="lossless audio copy")
                run_ffmpeg_job(job, ff, args, total_us=total)
            elif not [st for st in built["selected"] if st.get("type") == "video"]:
                # Nothing but audio/subtitles can be stored: cut them in one pass so the
                # mux never falls back to ffmpeg default stream selection (which would
                # silently re-add the excluded video).
                if not built["selected"]:
                    raise RuntimeError("no stream can be copied into the chosen container")
                args = build_audio_copy_args(source, temp, built["selected"],
                                             built["actualStartUs"], built["actualEndUs"],
                                             built["container"])
                job.update(message="lossless copy")
                run_ffmpeg_job(job, ff, args, total_us=total)
            else:
                video_sel = [st for st in built["selected"] if st.get("type") == "video"]
                other_sel = [st for st in built["selected"] if st.get("type") != "video"]
                vtemp = temp.with_name(temp.stem + ".v" + temp.suffix)
                atemp = temp.with_name(temp.stem + ".a" + temp.suffix) if other_sel else None
                job.update(message="lossless video copy")
                run_ffmpeg_job(job, ff, _video_cut_args(source, vtemp, video_sel,
                                                       built["seekUs"], built["actualEndUs"]), total_us=total)
                if atemp is not None:
                    job.update(message="lossless audio copy")
                    run_ffmpeg_job(job, ff, _av_cut_args(source, atemp, other_sel,
                                                         built["actualStartUs"], built["actualEndUs"]), total_us=total)
                job.update(message="muxing")
                run_ffmpeg_job(job, ff, _mux_args(vtemp, atemp, temp, built["container"],
                                                  built["actualStartUs"]), total_us=total)
                for leftover in (vtemp, atemp):
                    if leftover is not None:
                        try:
                            leftover.unlink()
                        except OSError:
                            pass
                vtemp = None
                atemp = None
            if job.is_cancelled():
                raise RuntimeError("cancelled")
            data = ffmpeg_tools.summarize(ffmpeg_tools.probe(fp, str(temp)))
            wants_video = any(st.get("type") == "video" for st in built["selected"])
            if wants_video:
                if not data.get("video"):
                    raise RuntimeError("output verification failed")
            elif data.get("audio"):
                pass
            elif data.get("video"):
                # Only subtitles were retained: a video track here is unexpected.
                raise RuntimeError("output verification failed")
            elif not any(st.get("type") == "subtitle" for st in built["selected"]):
                raise RuntimeError("output verification failed")
            os.replace(str(temp), str(out))
            try:
                cleanup.enforce(cfg, db, jobs)
            except Exception:
                pass
            note = "FLAC は可逆再エンコード（STREAMINFO 補正）" if built["container"] == "flac" else ""
            result = {"outputPath": str(out), "bytes": out.stat().st_size,
                      "actualStartUs": built["actualStartUs"], "actualEndUs": built["actualEndUs"],
                      "container": built["container"], "note": note,
                      "excluded": [st.get("index") for st in built["excluded"]],
                      "lossless": not reencode, "warnings": built["warnings"], "fallback": built["fallback"]}
            job.update(progress=1.0, message="done")
            return result
        except Exception:
            raise
        finally:
            for leftover in (temp, locals().get("vtemp"), locals().get("atemp")):
                try:
                    if leftover is not None and leftover.exists():
                        leftover.unlink()
                except OSError:
                    pass
            if work is not None:
                shutil.rmtree(work, ignore_errors=True)
    return jobs.create("export", source["id"], runner)


def writable_probe(directory):
    probe = Path(directory) / (".trim_write_probe_" + uuid.uuid4().hex[:8] + ".tmp")
    try:
        with open(str(probe), "wb") as fh:
            fh.write(b"0")
    except OSError as exc:
        return False, str(exc)
    try:
        probe.unlink()
    except OSError:
        pass
    return True, ""


def validate_output(cfg, db, source, path, start_us=None, end_us=None):
    target = Path(path)
    parent = target if target.is_dir() else target.parent
    result = {"writable": False, "reason": "", "freeBytes": 0, "estimatedNeedBytes": 0,
              "pathLength": len(str(target)), "path": str(target)}
    try:
        parent_exists = parent.exists()
    except OSError:
        parent_exists = False
    if not parent_exists:
        result["reason"] = "target directory does not exist"
        return result
    try:
        usage = shutil.disk_usage(str(parent))
        result["freeBytes"] = usage.free
    except OSError as exc:
        result["reason"] = str(exc)
        return result
    if source:
        duration = source.get("duration_us") or 0
        size = source.get("size") or 0
        if duration and size and start_us is not None and end_us is not None:
            result["estimatedNeedBytes"] = int(size * max(0, end_us - start_us) / duration)
        elif size:
            result["estimatedNeedBytes"] = int(size)
    result["writable"], why = writable_probe(parent)
    if not result["writable"]:
        result["reason"] = "directory is not writable: " + why
    return result
