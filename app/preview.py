"""Preview proxy: bake the audio timing into ONE MP4 the browser plays as a single element.

The plan that this implements is docs/PLAN_PREVIEW_PROXY.md.  The short version: the old
preview played a <video> and a detached <audio> at once and chased the drift with seeks,
which is why the sound stuttered on iOS and why the value that sounded right in the
preview never matched the export.  Here the shift is baked into a normal MP4 instead, so
the preview has one media clock and cannot drift.

The filter graph is deliberately built from the SAME helpers the export uses
(exports._mix_filter) so the two cannot disagree about what a shift means.
"""
import hashlib
import json
import os
import re
import uuid
from pathlib import Path

from . import ffmpeg_tools, media
from .exports import _mix_filter
from .proc import run_ffmpeg_job

IMPL = "preview-v15"
VALID_KEY = re.compile(r"^[0-9a-f]{40}$")


class ProxyRequired(Exception):
    """The source has to be played through the existing proxy first."""

    def __init__(self, source_id):
        super().__init__("proxy required")
        self.source_id = source_id


# Same-key builds are de-duplicated in this process only (the server is single-process by
# design: the job semaphore and path reservations are in-memory too).
_INFLIGHT = {}


def _lp(path):
    """Windows: one place that turns a path into its long-path form for file I/O."""
    return media.long_path(str(path))


def preview_dir(cfg):
    path = Path(cfg.work_dir) / "preview"
    Path(_lp(path)).mkdir(parents=True, exist_ok=True)
    return path


def paths(cfg, key):
    base = preview_dir(cfg)
    return {
        "mp4": base / (key + ".mp4"),
        "json": base / (key + ".json"),
        "ok": base / (key + ".ok"),
    }


def _stream_kind(stream):
    """ffprobe JSON uses codec_type; the DB rows use type."""
    return stream.get("type") or stream.get("codec_type")


def _first_stream(info, kind):
    for stream in (info or {}).get("streams") or []:
        if _stream_kind(stream) == kind:
            return stream
    return None


def _stream_start_us(info, kind):
    for stream in (info or {}).get("streams") or []:
        if _stream_kind(stream) == kind:
            try:
                return int(round(float(stream.get("start_time") or 0) * 1_000_000))
            except (TypeError, ValueError):
                return 0
    return 0


def _stream_duration_us(info):
    for stream in (info or {}).get("streams") or []:
        if _stream_kind(stream) == "video" and stream.get("duration"):
            try:
                return int(round(float(stream["duration"]) * 1_000_000))
            except (TypeError, ValueError):
                break
    return 0


def content_sig(path):
    """Cheap content signature: size + mtime + head/tail bytes.

    A full hash would be correct but reading a large source on every build request is not
    worth it; this catches normal edits, and mtime is the primary detector.
    """
    path = media.long_path(path)
    stat = os.stat(path)
    digest = hashlib.sha1()
    digest.update(str(stat.st_size).encode())
    digest.update(str(stat.st_mtime_ns).encode())
    with open(path, "rb") as handle:
        if stat.st_size <= 131072:
            # Small file: hash it whole, nothing to gain from sampling.
            digest.update(handle.read())
        else:
            digest.update(handle.read(65536))
            handle.seek(-65536, os.SEEK_END)
            digest.update(handle.read(65536))
    return digest.hexdigest()


def cache_key(source, variant_path, options, resolved_variant):
    payload = {
        "impl": IMPL,
        "sourceId": source.get("id"),
        "sourceSig": content_sig(source["path"]),
        "variant": resolved_variant,
        "variantSig": content_sig(variant_path),
        "videoStreamIndex": 0,
        "audioMode": options.get("audioMode") or "original",
        "origShiftMs": int(options.get("audioShiftMs") or 0),
        "addedShiftMs": int(options.get("addedShiftMs") or 0),
        "addedStartMs": int(options.get("addedStartMs") or 0),
        "addedSourceId": options.get("addedSourceId") or None,
    }
    added_id = payload["addedSourceId"]
    payload["addedSig"] = content_sig(_source_path(options.get("_addedSource"))) if added_id else None
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha1(blob).hexdigest()


def _source_path(source):
    return source["path"] if source else ""


def hit(cfg, key):
    files = paths(cfg, key)
    try:
        # Check the completion marker first: a half-written cache is just noise.
        if not Path(_lp(files["ok"])).exists():
            return None
        if Path(_lp(files["mp4"])).stat().st_size <= 0:
            return None
        with open(_lp(files["json"]), "r", encoding="utf-8") as handle:
            meta = json.load(handle)
        if meta.get("impl") != IMPL:
            return None
        for required in ("sourceTimelineOffsetUs", "outputStartOffsetUs", "durationUs"):
            if required not in meta:
                return None
        meta["url"] = "/api/preview/media/" + key + ".mp4"
        return meta
    except (OSError, ValueError):
        return None


def _probe_streams(cfg, path):
    ff, fp = ffmpeg_tools.ffmpeg_paths(cfg)
    if not fp:
        return {}
    try:
        return ffmpeg_tools.probe(fp, media.long_path(path))
    except Exception as exc:
        raise ValueError("cannot probe " + str(path) + ": " + str(exc))


def _audio_filter(tot_sec, added_tot_sec, duration_s, rate, has_orig, has_added):
    """Build the preview audio graph: per-input shift, optional mix, then a fixed length.

    The length stage is what makes the preview match the export: the audio always ends up
    exactly as long as the video, so a short source is padded with silence and a long one
    is trimmed.
    """
    def stage(index, total, rate_hz):
        parts = ["asetpts=PTS-STARTPTS"]
        if abs(total) >= 0.0005:
            # Same helper the export uses for its shift, so the two can never disagree
            # about the sign or the units (ms for adelay, seconds for atrim).
            parts.append(_mix_filter(int(round(total * 1e6))))
        parts.append("aresample=%d" % rate_hz)
        parts.append("aformat=sample_fmts=fltp:sample_rates=%d:channel_layouts=stereo" % rate_hz)
        return "[" + str(index) + ":a:0]" + ",".join(parts)

    chains = []
    outs = []
    if has_orig:
        chains.append(stage(1, tot_sec, rate) + "[ao]")
        outs.append("[ao]")
    if has_added:
        chains.append(stage(2 if has_orig else 1, added_tot_sec, rate) + "[ad]")
        outs.append("[ad]")
    if not outs:
        return None
    if len(outs) == 2:
        chains.append("[ao][ad]amix=inputs=2:normalize=0:duration=longest[am]")
    else:
        chains.append(outs[0] + "anull[am]")
    chains.append("[am]apad=whole_dur=%.6f,atrim=end=%.6f,asetpts=PTS-STARTPTS[aout]"
                  % (duration_s, duration_s))
    return ";".join(chains)


def _resolve_added(db, options):
    added_id = options.get("addedSourceId")
    if not added_id:
        return None
    row = db.get_source(added_id)
    if not row:
        return None
    return row


def resolve_variant(cfg, source, requested):
    info = media.streams_to_info(source)
    variant = requested or "original"
    if variant not in ("original", "proxy"):
        variant = "original"
    if variant == "original":
        video = info.get("video") or {}
        # Fail closed: if we cannot prove the browser can play it AND that it can be
        # copied into MP4, send it through the existing proxy instead of guessing.
        try:
            playable = bool(ffmpeg_tools.direct_playable(info))
        except Exception:
            playable = False
        try:
            copyable = bool(video) and bool(ffmpeg_tools.copy_compatibility(video, "mp4"))
        except Exception:
            copyable = False
        if not (playable and copyable):
            variant = "proxy"
    if variant == "proxy" and not Path(_lp(media.proxy_path(cfg, source["id"]))).exists():
        raise ProxyRequired(source["id"])
    return variant


def start_preview(cfg, db, jobs, source, options):
    """Create (or find) the preview proxy build.

    Returns (job, variant, key, cached): job is None when the cache already had it, and in
    that case cached holds the metadata to answer with.
    """
    try:
        variant = resolve_variant(cfg, source, options.get("variant"))
    except OSError as exc:
        raise ValueError("source file is not readable: " + str(exc))
    variant_path = media.proxy_path(cfg, source["id"]) if variant == "proxy" else Path(source["path"])
    added = _resolve_added(db, options)
    options = dict(options)
    if added is not None:
        options["_addedSource"] = added
    try:
        key = cache_key(source, variant_path, options, variant)
    except OSError as exc:
        raise ValueError("source file is not readable: " + str(exc))
    cached = hit(cfg, key)
    if cached is not None:
        return None, variant, key, cached
    running = _INFLIGHT.get(key)
    if running is not None:
        # Same settings requested twice (two devices, a double tap): one build is enough.
        return running, variant, key, None

    files = paths(cfg, key)

    def runner(job):
        part = files["mp4"].with_name(files["mp4"].stem + "." + uuid.uuid4().hex[:8] + ".part.mp4")
        try:
            return _run_build(job, part)
        finally:
            # After os.replace the file is gone, so this only removes abandoned builds.
            try:
                os.unlink(_lp(part))
            except OSError:
                pass

    def _run_build(job, part):
        ff, fp = ffmpeg_tools.ffmpeg_paths(cfg)
        orig_info = _probe_streams(cfg, source["path"])
        variant_info = _probe_streams(cfg, variant_path)
        duration_us = _stream_duration_us(variant_info) or int(source.get("duration_us") or 0)
        if duration_us <= 0:
            raise RuntimeError("cannot determine the video duration")
        duration_s = duration_us / 1e6
        video_start_us = _stream_start_us(variant_info, "video")
        # The relative A/V offset has to be measured INSIDE the source timeline: the proxy
        # variant is re-muxed to start at 0, so subtracting its start would invent an offset
        # that the source never had.
        orig_video_start_us = _stream_start_us(orig_info, "video")
        orig_audio_start_us = _stream_start_us(orig_info, "audio")
        added_info = _probe_streams(cfg, added["path"]) if added else {}
        added_start_us = _stream_start_us(added_info, "audio")

        mode = options.get("audioMode") or "original"
        if mode not in ("original", "added", "bothTracks", "bothMix", "mute"):
            mode = "original"
        shift_s = int(options.get("audioShiftMs") or 0) / 1000.0
        added_shift_s = int(options.get("addedShiftMs") or 0) / 1000.0
        added_place_s = int(options.get("addedStartMs") or 0) / 1000.0
        rel_s = (orig_audio_start_us - orig_video_start_us) / 1e6
        # The added track is its OWN timeline: only its own leading offset matters, it has
        # nothing to do with the video's start.
        added_rel_s = added_start_us / 1e6
        # A delay past the end is silence anyway; clamping keeps ffmpeg from generating a
        # huge silent buffer for a nonsense addedStart value.
        limit_s = duration_s + 0.001
        def clamp_shift(value):
            return max(-limit_s, min(limit_s, value))

        orig_audio = _first_stream(orig_info, "audio")
        added_audio = _first_stream(added_info, "audio") if added else None
        has_orig = mode in ("original", "bothTracks", "bothMix") and orig_audio is not None
        # The added source has to really carry audio: a video-only file in added mode would
        # otherwise reference a pad that does not exist and make ffmpeg fail.
        has_added = mode in ("added", "bothTracks", "bothMix") and added is not None and added_audio is not None
        if mode in ("bothTracks", "bothMix") and not has_orig and has_added:
            mode = "added"  # degrade: nothing to mix with
        if mode != "mute" and not has_orig and not has_added:
            mode = "mute"   # nothing to hear at all
        if mode == "added" and not has_added:
            mode = "mute"
        rate = 48000
        audio_rate = (orig_audio or {}).get("sample_rate") if has_orig else (
            (added_audio or {}).get("sample_rate") if has_added else None)
        try:
            if audio_rate:
                rate = int(audio_rate)
        except (TypeError, ValueError):
            pass
        if rate not in (44100, 48000):
            rate = 48000

        # Input numbering: 0 = variant video, 1 = source audio (only when it exists),
        # next = added audio.  Sections 3.3.2 of the plan: only real inputs are passed.
        args = ["-y", "-fflags", "+genpts", "-itsoffset", "%.6f" % (-video_start_us / 1e6), "-i", media.long_path(variant_path)]
        if has_orig:
            args += ["-i", media.long_path(source["path"])]
        if has_added:
            args += ["-i", media.long_path(added["path"])]

        graph = None
        if mode != "mute" and (has_orig or has_added):
            graph = _audio_filter(
                clamp_shift(shift_s + rel_s),
                clamp_shift(added_place_s + added_shift_s + added_rel_s),
                duration_s,
                rate,
                has_orig,
                has_added,
            )
        # Map the video FIRST: an MP4 whose stream 0 is audio makes some players
        # (notably iOS Safari) slow or refuse to start, and the export always has video first.
        if graph:
            args += ["-filter_complex", graph, "-map", "0:v:0", "-map", "[aout]"]
        else:
            args += ["-map", "0:v:0", "-an"]
        args += ["-t", "%.6f" % duration_s, "-c:v", "copy"]
        if graph:
            args += ["-c:a", "aac", "-b:a", "128k"]
        # NOTE: -avoid_negative_ts make_zero is deliberately NOT used: on this ffmpeg it
        # shifts the copied video PTS (measured start_time=66ms) and breaks alignment.
        # Without it both streams start at 0 and the duration matches the video.
        args += ["-movflags", "+faststart", media.long_path(part)]

        job.update(message="building preview")
        run_ffmpeg_job(job, ff, args, total_us=duration_us)
        if job.is_cancelled():
            try:
                os.unlink(_lp(part))
            except OSError:
                pass
            raise RuntimeError("cancelled")
        if not Path(_lp(part)).exists() or Path(_lp(part)).stat().st_size <= 0:
            raise RuntimeError("preview build produced no output")

        out_info = _probe_streams(cfg, part)
        out_start_us = _stream_start_us(out_info, "video")
        out_duration_us = _stream_duration_us(out_info)
        if not out_duration_us:
            try:
                out_duration_us = int(round(float((out_info.get("format") or {}).get("duration") or 0) * 1e6))
            except (TypeError, ValueError):
                out_duration_us = 0
        meta = {
            "impl": IMPL,
            "key": key,
            "sourceId": source.get("id"),
            "variant": variant,
            "sourceTimelineOffsetUs": video_start_us,
            "outputStartOffsetUs": out_start_us,
            "durationUs": int(out_duration_us),
            "audioMode": mode,
            "origShiftMs": int(options.get("audioShiftMs") or 0),
            "addedShiftMs": int(options.get("addedShiftMs") or 0),
            "addedStartMs": int(options.get("addedStartMs") or 0),
        }
        os.replace(_lp(part), _lp(files["mp4"]))
        with open(_lp(files["json"]), "w", encoding="utf-8") as handle:
            json.dump(meta, handle, ensure_ascii=False)
        with open(_lp(files["ok"]), "w", encoding="utf-8") as handle:
            handle.write("ok")
        meta["url"] = "/api/preview/media/" + key + ".mp4"
        return meta

    box = {}

    def guarded(job):
        box["job"] = job
        try:
            return runner(job)
        finally:
            # Only clear our own entry: a fast job may finish before we even return.
            if _INFLIGHT.get(key) is box.get("job"):
                _INFLIGHT.pop(key, None)

    job = jobs.create("preview", source.get("id"), guarded)
    if box.get("job") is None:
        _INFLIGHT[key] = job      # not started yet: normal case
    elif _INFLIGHT.get(key) is None:
        _INFLIGHT[key] = job
    return job, variant, key, None
