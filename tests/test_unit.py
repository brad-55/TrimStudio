"""Unit checks for security, time parsing, and naming (no server required)."""
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import security, sources  # noqa: E402
from app.config import Config  # noqa: E402
from app.cleanup import clean_stale_parts  # noqa: E402
from app.exports import (build_audio_copy_args, build_audio_reencode_args,  # noqa: E402
                         export_tags, output_path_for, sanitize_name, time_tag, time_tag_short)
from app.ffmpeg_tools import copy_compatibility, format_seconds, parse_fraction  # noqa: E402


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    check(security.is_private_ip("192.168.1.10"), "192.168/16 must be private")
    check(security.is_private_ip("10.0.0.5"), "10/8 must be private")
    check(security.is_private_ip("::ffff:192.168.0.7"), "IPv4-mapped must normalize")
    check(security.is_private_ip("fd00::1"), "ULA must be private")
    check(not security.is_private_ip("8.8.8.8"), "public must be rejected")
    check(not security.is_private_ip("2001:4860:4860::8888"), "public v6 must be rejected")

    cfg = Config()
    ctx = "L:/dev/Trim/data/test"
    check(security.is_within(ctx, "L:/dev/Trim"), "workspace containment")
    check(not security.is_within("C:/Windows", "L:/dev/Trim"), "outside workspace")
    cfg.data["allowedRoots"] = ["L:/dev/Trim"]
    cfg.data["denyRoots"] = ["L:/dev/Trim/secret"]
    check(security.check_path("L:/dev/Trim/data/test", cfg).lower().startswith("l:"), "allowed path resolves")
    try:
        security.check_path("C:/Windows/System32/drivers/etc/hosts", cfg)
        raise AssertionError("outside path must be rejected")
    except PermissionError:
        pass
    try:
        security.check_path("L:/dev/Trim/secret/x.mp4", cfg)
        raise AssertionError("denied path must be rejected")
    except PermissionError:
        pass

    check(format_seconds(2500000) == "2.500000000", "us to seconds")
    check(parse_fraction("30000/1001") > 29.97 and parse_fraction("30000/1001") < 29.98, "fraction parse")
    check(parse_fraction("0/0") is None, "zero fraction")
    check(time_tag(3723456000) == "01h02m03s456", "time tag: " + time_tag(3723456000))
    check(sanitize_name('a<b>c:d"e/f.mp4') == "a_b_c_d_e_f", "sanitize: " + sanitize_name('a<b>c:d"e/f.mp4'))
    check(sanitize_name("CON.mp4") == "_CON", "reserved name")

    check(time_tag_short(0) == "0s", "short tag 0s")
    check(time_tag_short(2000000) == "2s", "short tag 2s")
    check(time_tag_short(65000000) == "1m5s", "short tag 1m5s: " + time_tag_short(65000000))
    check(time_tag_short(3723500000) == "1h2m3.500s", "short tag hours: " + time_tag_short(3723500000))
    check(export_tags({"mode": "lossless"}, 0, 2000000) == "切出0s-2s_無変換", "lossless tags")
    tags = export_tags({"mode": "reencode", "encoder": "libx265", "videoBitrate": 1500,
                        "stabilize": True, "crop": {"w": 320, "h": 180, "x": 0, "y": 0}}, 10000000, 20000000)
    check(tags.startswith("切出10s-20s_再エンコード") and "H265" in tags and "1500kbps" in tags
          and "手ブレ補正" in tags and "切抜320x180" in tags, "reencode tags: " + tags)

    long_src = {"path": "L:/dev/Trim/data/test/" + ("あ" * 160) + ".mp4", "origin": "local"}
    long_out = output_path_for(long_src, 0, 2000000, "mp4", None, True, {"mode": "lossless"})
    check(len(str(long_out)) <= 240, "long output stays within 240 chars")
    check(len(long_out.name.split("_切出")[0]) <= 80, "original name is capped by sanitize_name")
    check("切出0s-2s_無変換" in long_out.name, "settings survive the cap: " + long_out.name)

    tmp = Path("L:/dev/Trim/data/test/_stale_check")
    tmp.mkdir(parents=True, exist_ok=True)
    old_part = tmp / "x.trim-00h00m00s000-00h00m01s000.part.mp4"
    new_part = tmp / "IMG_1234_切出0s-2s_無変換.part.mp4"
    keep_part = tmp / "someone_else.part.mp4"
    for item in (old_part, new_part, keep_part):
        item.write_bytes(b"0")
        stamp = time.time() - 7200
        os.utime(item, (stamp, stamp))
    clean_stale_parts(str(tmp))
    check(not old_part.exists(), "legacy stale .part removed")
    check(not new_part.exists(), "readable stale .part removed")
    check(keep_part.exists(), "unrelated .part is kept")
    shutil.rmtree(tmp, ignore_errors=True)

    check(copy_compatibility({"type": "audio", "codec": "aac"}, "mp4"), "aac in mp4")
    check(not copy_compatibility({"type": "audio", "codec": "pcm_s16le"}, "mp4"), "pcm not in mp4")
    check(copy_compatibility({"type": "audio", "codec": "pcm_s16le"}, "matroska"), "pcm in mkv")
    check(not copy_compatibility({"type": "data", "codec": "none"}, "mp4"), "data not copied")
    check(copy_compatibility({"type": "subtitle", "codec": "ass"}, "matroska"), "ass in mkv")
    check(copy_compatibility({"type": "audio", "codec": "mp3"}, "mp3"), "mp3 in mp3")
    check(copy_compatibility({"type": "audio", "codec": "flac"}, "flac"), "flac in flac")
    check(not copy_compatibility({"type": "audio", "codec": "pcm_s16le"}, "ogg"), "pcm not in ogg")
    check(not copy_compatibility({"type": "audio", "codec": "aac"}, "flac"), "aac not in flac")
    check(not copy_compatibility({"type": "video", "codec": "h264"}, "mp3"), "video not in mp3")

    copy_args = build_audio_copy_args({"path": r"C:\x\a.mp3"}, r"C:\x\out.mp3",
                                      [{"index": 0, "type": "audio"}], 2000000, 7000000, "mp3")
    check(copy_args[copy_args.index("-ss") + 1] == "2.000000000", "audio copy start")
    check(copy_args[copy_args.index("-t") + 1] == "5.000000000", "audio copy duration")
    check(copy_args[copy_args.index("-c") + 1] == "copy", "audio copy is a packet copy")
    flac_args = build_audio_copy_args({"path": r"C:\x\a.flac"}, r"C:\x\out.flac",
                                      [{"index": 0, "type": "audio"}], 0, 3000000, "flac")
    check(flac_args[flac_args.index("-c:a") + 1] == "flac", "flac uses bit exact re-encode")
    m4a_args = build_audio_copy_args({"path": r"C:\x\a.m4a"}, r"C:\x\out.m4a",
                                     [{"index": 0, "type": "audio"}], 0, 3000000, "ipod")
    check("+faststart" in m4a_args, "m4a faststart")
    enc1 = build_audio_reencode_args({"path": r"C:\x\a.mp3"}, r"C:\x\out.mp3",
                                     [{"index": 0, "type": "audio"}], "mp3", 0, 3000000, {})
    check("libmp3lame" in enc1, "mp3 encoder")
    enc2 = build_audio_reencode_args({"path": r"C:\x\a.m4a"}, r"C:\x\out.m4a",
                                     [{"index": 0, "type": "audio"}], "ipod", 0, 3000000, {})
    check("aac" in enc2, "aac encoder")

    names = {"localhost", "selfhost"}
    check(security.host_allowed("localhost:8003", {"127.0.0.1"}, names), "localhost allowed")
    check(security.host_allowed("selfhost:8003", {"127.0.0.1"}, names), "self name allowed")
    check(not security.host_allowed("evil.example.com:8003", {"127.0.0.1"}, names), "foreign name rejected")
    check(not security.host_allowed("192.168.0.200:8003", {"127.0.0.1"}, names), "unlisted ip rejected")
    check(security.host_allowed("192.168.0.200:8003", {"192.168.0.200"}, names), "listed ip allowed")
    check(security.is_tailnet_ip("100.70.95.77"), "tailnet ip allowed")
    check(security.is_tailnet_ip("100.64.0.1"), "tailnet range start allowed")
    check(security.is_tailnet_ip("100.127.255.254"), "tailnet range end allowed")
    check(not security.is_tailnet_ip("100.128.0.1"), "outside tailnet range rejected")
    check(not security.is_tailnet_ip("192.168.0.5"), "lan ip is not tailnet")
    check(not security.is_tailnet_ip("fd00::1"), "v6 ula is not a tailnet ipv4")
    check(security.is_allowed_source("100.70.95.77", True), "tailnet source allowed when enabled")
    check(not security.is_allowed_source("100.70.95.77", False), "tailnet source rejected when disabled")
    check(not security.is_allowed_source("8.8.8.8", True), "public source rejected")
    check(security.is_allowed_source("192.168.1.10", True), "lan source still allowed")
    check(security.is_allowed_source("fd00::1", True), "v6 ula source still allowed")
    check(security.host_allowed("pc.tailnet.ts.net:8003", {"127.0.0.1"}, names, True, set(), set(), True),
          "ts.net host allowed from the tailnet")
    check(security.host_allowed("pc.tailnet.ts.net:8003", {"127.0.0.1"}, names, True, set(), set(), False),
          "ts.net host allowed from a lan client (ts.net cannot be attacker-registered)")
    check(not security.host_allowed("pc.tailnet.ts.net:8003", {"127.0.0.1"}, names, False),
          "ts.net host rejected when tailnet disabled")
    check(security.host_allowed("100.70.95.77:8003", set(), names, True, set(), {"100.70.95.77"}),
          "own tailnet ip allowed as host")
    check(not security.host_allowed("100.70.95.77:8003", set(), names, True, set(), set()),
          "unknown tailnet ip rejected as host")
    check(not security.host_allowed("evil.example.com:8003", {"127.0.0.1"}, names, True),
          "foreign name still rejected")
    check(security.host_allowed("DESKTOP-515R9UE.Tail0340.TS.NET.:8003", {"127.0.0.1"}, names, True, set(), set(), True),
          "ts.net host is case and trailing-dot insensitive")
    check(not security.host_allowed("evil.ts.net.attacker.com:8003", {"127.0.0.1"}, names, True, set(), set(), True),
          "ts.net suffix must be terminal")
    check(not security.host_allowed("evilts.net:8003", {"127.0.0.1"}, names, True, set(), set(), True),
          "evilts.net is not a ts.net name")
    check(security.host_allowed("desktop-515r9ue.tail0340.ts.net:8003", {"127.0.0.1"}, names, True,
                                {"desktop-515r9ue.tail0340.ts.net"}, set(), False),
          "enumerated tailnet name works even without a tailnet client")
    check(security.host_allowed("100.70.95.77:8003", {"100.70.95.77"}, names, True, set(), set(), False),
          "tailnet ip allowed when it is a local address (CLI fallback)")
    check(security.is_allowed_source("fd7a:115c:a1e0::1", True), "v6 tailnet (ULA) source allowed")
    check(not security.host_allowed(".ts.net:8003", {"127.0.0.1"}, names, True, set(), set(), True),
          "bare .ts.net host rejected")
    tn_names, tn_ips = security.tailnet_info(0)
    if tn_names or tn_ips:
        check(all(n.endswith(".ts.net") for n in tn_names), "tailnet names look like ts.net: " + str(sorted(tn_names)))
        check(all(security.is_tailnet_ip(i) or ":" in i for i in tn_ips),
              "tailnet ips are tailnet addresses: " + str(sorted(tn_ips)))
    print("tailnet self:", sorted(tn_names), sorted(tn_ips))

    from app.exports import audio_offsets, added_head_skip_us, clamp_added_start
    off = audio_offsets("original", 0, 0, False)
    check(off["audio"] == 0 and off["video"] == 0 and off["audioStreams"] == 1, "no shift is a no-op: " + str(off))
    off = audio_offsets("original", 120000, 0, False)
    check(off["audio"] == 120000 and off["video"] == 0, "+shift moves the audio later")
    off = audio_offsets("original", -120000, 0, False)
    check(off["video"] == 0 and off["audio"] == 0 and off["audioSkipUs"] == 120000,
      "-shift advances the audio content instead of moving the video")
    off = audio_offsets("bothTracks", 0, 90000, True)
    check(off["added"] == 90000 and off["audioStreams"] == 2, "added shift and 2 tracks: " + str(off))
    off = audio_offsets("bothTracks", 0, -90000, True)
    check(off["added"] == 0 and added_head_skip_us(-90000) == 90000, "negative added shift skips the head")
    off = audio_offsets("mute", 500000, 500000, True)
    check(off["audioStreams"] == 0 and off["audio"] == 0 and off["video"] == 0, "mute drops every audio stream")
    check(audio_offsets("added", 0, 0, True)["audioStreams"] == 1, "added-only keeps one stream")
    check(clamp_added_start(40000000, 0, 30000000) == 30000000, "added start is clamped to the file length")
    check(clamp_added_start(1000000, -2000000, 30000000) == 1000000, "head skip keeps the start valid")
    from app.exports import _shifted_mux_args, _added_cut_args
    zero = {"video": 0, "audio": 0, "added": 0}
    base_args = _shifted_mux_args(r"C:\t\v.mp4", r"C:\t\a.mp4", None, r"C:\t\o.mp4", "mp4", 2000000, zero)
    check("-avoid_negative_ts" in base_args and base_args[base_args.index("-avoid_negative_ts") + 1] == "make_zero",
          "unshifted mux keeps make_zero (existing behaviour)")
    check("-map_chapters" in base_args and "-use_editlist" not in base_args, "unshifted mux keeps chapters")
    plus = _shifted_mux_args(r"C:\t\v.mp4", r"C:\t\a.mp4", None, r"C:\t\o.mp4", "mp4", 0,
                             {"video": 0, "audio": 120000, "added": 0})
    check(plus.index("-itsoffset") < plus.index("-map"), "video input carries the first offset")
    audio_i = plus.index("-itsoffset", plus.index("-itsoffset") + 1)
    check(plus[audio_i + 1] == "0.120000000", "audio itsoffset carries the shift: " + plus[audio_i + 1])
    check(plus[plus.index("-avoid_negative_ts") + 1] == "disabled", "shifted mux disables make_zero")
    check("-use_editlist" in plus and plus[plus.index("-use_editlist") + 1] == "1", "MP4 gets an edit list")
    check("-map_chapters" in plus and plus[plus.index("-map_chapters") + 1] == "-1",
          "chapters are dropped when the original shift moves the timeline")
    addonly = _shifted_mux_args(r"C:\\t\\v.mp4", r"C:\\t\\a.mp4", r"C:\\t\\x.mka", r"C:\\t\\o.mp4", "mp4", 0,
                                {"video": 0, "audio": 0, "added": 120000}, length_us=5000000)
    check(addonly[addonly.index("-map_chapters") + 1] == "0", "an added-only shift keeps chapters")
    check(addonly[addonly.index("-t") + 1] == "5.120000000",
          "the -t cap reaches past the delayed stream: " + addonly[addonly.index("-t") + 1])
    check(addonly.count("-i") == 3, "the added track is a third input")
    solo = _shifted_mux_args(None, r"C:\\t\\a.m4a", None, r"C:\\t\\o.m4a", "mp4", 0,
                             {"video": 0, "audio": -2500000, "added": 0})
    check(solo.count("-i") == 1, "an audio-only export has a single input")
    check(solo[solo.index("-itsoffset") + 1] == "-2.500000000", "the audio-only route keeps the signed shift")
    check("-map_chapters" in solo and solo[solo.index("-map_chapters") + 1] == "-1",
          "an audio-only shift drops chapters too")
    minus = _shifted_mux_args(r"C:\t\v.mp4", r"C:\t\a.mp4", None, r"C:\t\o.mp4", "mp4", 0,
                              {"video": 120000, "audio": 0, "added": 0})
    check(minus[minus.index("-itsoffset") + 1] == "0.120000000", "negative shift moves the video instead")
    track = _shifted_mux_args(r"C:\t\v.mp4", r"C:\t\a.mp4", r"C:\t\x.m4a", r"C:\t\o.mp4", "mp4", 0,
                              {"video": 0, "audio": 0, "added": 60000})
    check(track.count("-i") == 3 and "-map" in track and "2" in track, "added input is mapped")
    add_cut = _added_cut_args({"path": r"C:\t\x.m4a"}, r"C:\t\a.acut.m4a",
                              [{"index": 0, "type": "audio"}], 2000000, 7000000, 500000)
    check(add_cut[add_cut.index("-ss") + 1] == "2.500000000", "added cut skips the shifted head")
    check(add_cut[add_cut.index("-t") + 1] == "4.500000000", "added cut keeps the export length")
    from app.audio_sync import SAMPLE_RATE, estimate_offset, estimate_consistent
    import numpy as _np
    rng = _np.random.default_rng(7)
    base = rng.standard_normal(SAMPLE_RATE * 6).astype("float32")
    delay = int(0.137 * SAMPLE_RATE)
    # tgt is the base signal advanced by 137ms: it must be delayed by +137ms to line up.
    tgt = _np.concatenate([base[delay:], _np.zeros(delay, dtype="float32")])
    lag, ratio, peak = estimate_offset(base, tgt, SAMPLE_RATE, 5.0)
    got_ms = lag / float(SAMPLE_RATE) * 1000.0
    check(abs(got_ms - 137.0) <= 2.0, "auto sync finds a 137ms advance: " + ("%.1f" % got_ms))
    check(ratio >= 1.5 and peak >= 0.15, "auto sync reports confidence: ratio=%.2f peak=%.2f" % (ratio, peak))
    lag0, _r0, _p0 = estimate_offset(base, base.copy(), SAMPLE_RATE, 5.0)
    check(abs(lag0) <= 2, "identical tracks give zero offset: " + str(lag0))
    silent = _np.zeros(SAMPLE_RATE * 3, dtype="float32")
    _l, r2, p2v = estimate_offset(base, silent, SAMPLE_RATE, 5.0)
    check(r2 == 0.0 and p2v == 0.0, "silence is not trusted")
    ok = estimate_consistent([(100, 2.0, 0.4), (110, 2.2, 0.5), (95, 1.9, 0.45)], SAMPLE_RATE)
    check(ok[3] >= 0.4 and ok[2] is True, "consistent windows agree: " + str(ok))
    bad = estimate_consistent([(100, 2.0, 0.4), (4000, 2.2, 0.5), (8000, 1.9, 0.45)], SAMPLE_RATE)
    check(bad[2] is False, "drifting windows are reported as inconsistent")
    low = estimate_consistent([(100, 1.0, 0.05)], SAMPLE_RATE)
    check(low[0] == 0 and low[3] == 0.0, "low confidence windows are rejected")
    check(sources.security_path_sanitize("CON.mp3").startswith("_"), "reserved upload name")

    # --- added-track offset must also carry the video term (plan-review finding) ---
    off = audio_offsets("bothTracks", -5_000_000, 2_000_000, True)
    check(off["video"] == 0 and off["audio"] == 0 and off["audioSkipUs"] == 5_000_000,
      "a negative original shift advances the audio content instead")
    check(off["added"] == 2_000_000,
          "the added track follows the video, which no longer moves: " + str(off))
    off2 = audio_offsets("added", -5_000_000, 2_000_000, True)
    check(off2["video"] == 0 and off2["added"] == 2_000_000,
          "case 2 (no original audio) must not add the video term: " + str(off2))
    off3 = audio_offsets("bothTracks", 1_000_000, -2_000_000, True)
    check(off3["audio"] == 1_000_000 and off3["added"] == 0,
          "negative added shift is absorbed by head_skip, not by a negative offset: " + str(off3))

    # --- output path reservations keep concurrent exports apart ---
    from app import jobs as _jobs_mod

    class _DB:
        def upsert_job(self, row):
            pass

    jm = _jobs_mod.JobManager(_DB(), concurrency=1)
    check(jm.reserve_output(r"L:\x\a.mp4", "j1") is True, "first reservation wins")
    check(jm.reserve_output(r"L:\x\a.mp4", "j2") is False, "a second job cannot take the same path")
    check(jm.is_output_reserved(r"L:\X\A.MP4") is True, "reservation lookup is case-insensitive")
    jm.release_output(r"L:\x\a.mp4")
    check(jm.is_output_reserved(r"L:\x\a.mp4") is False, "released paths become free again")
    check(jm.reserve_output(r"L:\x\b.mp4", "j3", alias=r"L:\y\c.mp4") is True, "alias reserves the raw path")
    check(jm.is_output_reserved(r"L:\y\c.mp4") is True, "the alias is reserved as well")
    jm.release_output(r"L:\x\b.mp4", alias=r"L:\y\c.mp4")
    check(jm.is_output_reserved(r"L:\y\c.mp4") is False, "alias is released too")


    from app import exports  # noqa: E402


    # the debug helpers are only useful if they actually run (a NameError here is
    # invisible in production because the caller swallows exceptions)
    from app import proc  # noqa: E402
    _log = proc._log_path("selftest.log")
    _log.parent.mkdir(parents=True, exist_ok=True)
    with open(_log, "w", encoding="utf-8") as fh:
        fh.write("2026-01-01 00:00:00 ancient\n")
        fh.write("00:00:00 undated-legacy\n")
        fh.write('{"t": "2999-01-01 00:00:00", "label": "json-future"}\n')
        fh.write("2999-01-01 00:00:00 future\n")
    proc.prune_logs()
    _body = open(_log, encoding="utf-8").read()
    check("future" in _body and "json-future" in _body
          and "ancient" not in _body and "legacy" not in _body,
          "prune_logs keeps only the recent window (incl. JSON lines): " + _body.replace(chr(10), "|")[:120])
    _log.unlink()
    _missing = proc.probe_media(r"tools/ffmpeg/bin/ffprobe.exe", "data/does-not-exist.mp4")
    check(isinstance(_missing, dict) and not _missing.get("codec"),
          "probe_media returns cleanly for a missing file (never raises)")
    # NOTE: prune_logs scans the real data/logs dir, so this test uses a unique
    # selftest.log name and removes it; production logs are only pruned, never written.
    if os.path.exists(r"tools/ffmpeg/bin/ffprobe.exe"):
        check("probe_error" not in _missing,
              "probe_media really spawned ffprobe (no swallowed NameError): "
              + str(_missing.get("probe_error")))
    _real = None
    for _cand in ("data/test/aux", "data/test"):
        import glob as _glob
        _hits = _glob.glob(_cand + "/*.mp4")
        if _hits:
            _real = _hits[0]
            break
    if _real:
        _d = proc.probe_media(r"tools/ffmpeg/bin/ffprobe.exe", _real)
        check(_d.get("codec") and _d.get("start"),
              "probe_media reads the real stream start times: " + str(_d.get("start"))[:80])

    # --- the added re-encode checkbox really re-encodes the added track (plan 0.5) ---
    import json as _json  # noqa: E402
    from app.exports import _audio_plan  # noqa: E402


    class _FakeDB:
        def __init__(self, row):
            self.row = row

        def get_source(self, sid):
            return self.row if sid == "add" else None


    _sel = [{"index": 0, "type": "video", "codec": "h264"},
            {"index": 1, "type": "audio", "codec": "aac", "channels": 2, "sample_rate": 48000, "start_time": "0.000000"}]
    _aac = [{"index": 0, "type": "audio", "codec": "aac", "channels": 2, "sample_rate": 48000}]
    _flac = [{"index": 0, "type": "audio", "codec": "flac", "channels": 2, "sample_rate": 48000}]
    _row_aac = {"id": "add", "streams_json": _json.dumps(_aac), "duration_us": 9_000_000}
    _row_flac = {"id": "add", "streams_json": _json.dumps(_flac), "duration_us": 9_000_000}
    _opt = {"audioMode": "added", "addedSourceId": "add"}

    # an empty plan must NOT be returned when only the content skip carries the shift
    _w = []
    _p = exports._audio_plan(_FakeDB(_row_aac), _sel, "mp4", {"audioShiftMs": -1}, 0, 4_000_000, _w)
    check(_p is not None and _p["offsets"]["audioSkipUs"] == 1000,
          "a plan survives when only audioSkipUs is non-zero: " + str(_p))
    _w = []
    _p = exports._audio_plan(_FakeDB(_row_aac), _sel, "mp4", {}, 0, 4_000_000, _w)
    check(_p is None, "a plain cut still uses the legacy route (no plan)")

    # the API speaks milliseconds and the internal time base is microseconds: the
    # conversion is a pure function, so it belongs in the unit layer (not only in E2E)
    check(exports._ms_us(1500) == 1_500_000, "1500ms converts to 1.5s of microseconds")
    check(exports._ms_us(-1) == -1000, "a negative shift keeps its sign")
    check(exports._ms_us(None) == 0 and exports._ms_us("junk") == 0, "junk converts to zero")
    _w = []
    _p = exports._audio_plan(_FakeDB(_row_aac), _sel, "mp4", {"audioShiftMs": 1500}, 0, 4_000_000, _w)
    check(_p["offsets"]["audio"] == 0 and _p["offsets"].get("audioPreUs") == 0
          and _p["offsets"].get("audioDelayUs") == 1_500_000
          and any("音声のみ再エンコード" in x for x in _w),
          "a positive shift without earlier audio bakes the delay into the audio: " + str((_p["offsets"], _w)))
    _late = [{"index": 0, "type": "video", "codec": "h264"},
             {"index": 1, "type": "audio", "codec": "aac", "channels": 2, "sample_rate": 48000, "start_time": "3.000000"}]
    _w = []
    _p = exports._audio_plan(_FakeDB(_row_aac), _late, "mp4", {"audioShiftMs": 1500}, 4_000_000, 8_000_000, _w)
    check(_p["offsets"]["audio"] == 0 and _p["offsets"].get("audioPreUs") == 0
          and _p["offsets"].get("audioDelayUs") == 1_500_000
          and any("音声のみ再エンコード" in x for x in _w),
          "a shift reaching before the first audio packet bakes the delay (no silent no-op): " + str((_p["offsets"], _w)))
    _w = []
    _p = exports._audio_plan(_FakeDB(_row_aac), _sel, "mp4", {"audioShiftMs": -1500}, 0, 4_000_000, _w)
    check(_p["offsets"]["video"] == 0 and _p["offsets"]["audio"] == 0
          and _p["offsets"]["audioSkipUs"] == 1_500_000,
          "a negative shift advances the audio: " + str(_p["offsets"]))
    _w = []
    _p = exports._audio_plan(_FakeDB(_row_aac), _sel, "mp4", {"audioShiftMs": 1500}, 4_000_000, 8_000_000, _w)
    check(_p is not None and _p["offsets"]["audio"] == 0
          and _p["offsets"]["audioPreUs"] == 1_500_000,
          "a positive shift with room is carried in the content: " + str(_p["offsets"]))
    _w = []
    _p = exports._audio_plan(_FakeDB(_row_aac), _sel, "mp4", {"audioShiftMs": 1500}, 0, 4_000_000, _w)
    check(_p["offsets"]["audio"] == 0 and _p["offsets"].get("audioPreUs") == 0
          and _p["offsets"].get("audioDelayUs") == 1_500_000
          and any("音声のみ再エンコード" in x for x in _w),
          "a positive shift without room bakes the delay into the audio: " + str((_p["offsets"], _w)))

    # --- delayNoReencode: opt-in timestamp delay instead of re-encoding the audio ---
    _w = []
    _p = exports._audio_plan(_FakeDB(_row_aac), _sel, "mp4",
                             {"audioShiftMs": 500, "delayNoReencode": True}, 0, 4_000_000, _w)
    check(_p["offsets"]["audio"] == 500_000 and not _p["offsets"].get("audioDelayUs")
          and _p.get("delayMode") == "timestamp"
          and any("無変換のままタイムスタンプ" in x for x in _w),
          "delayNoReencode copies the packets and uses the container timestamp: "
          + str((_p["offsets"], _p.get("delayMode"), _w)))
    _w = []
    _p = exports._audio_plan(_FakeDB(_row_aac), _sel, "webm",
                             {"audioShiftMs": 500, "delayNoReencode": True}, 0, 4_000_000, _w)
    check(_p["offsets"].get("audioDelayUs") == 500_000 and _p["offsets"]["audio"] == 0
          and _p.get("delayMode") == "reencode"
          and any("無変換の遅延に対応しない" in x for x in _w),
          "an edit-list-less container falls back to the exact re-encode: " + str((_p["offsets"], _w)))
    _w = []
    _p = exports._audio_plan(_FakeDB(_row_aac), _sel, "mp4",
                             {"audioShiftMs": 1500, "delayNoReencode": True}, 4_000_000, 8_000_000, _w)
    check(_p["offsets"].get("audioPreUs") == 1_500_000 and not _p["offsets"].get("audioDelayUs")
          and _p.get("delayMode") == "content",
          "delayNoReencode leaves the existing content-delay path untouched")
    _w = []
    _p = exports._audio_plan(_FakeDB(_row_aac), _sel, "mp4",
                             {"audioShiftMs": -1500, "delayNoReencode": True}, 0, 4_000_000, _w)
    check(_p["offsets"]["audioSkipUs"] == 1_500_000 and _p["offsets"]["audio"] == 0
          and _p.get("delayMode") == "none",
          "delayNoReencode does not affect a negative shift")
    _w = []
    _p = exports._audio_plan(_FakeDB(_row_aac), _sel, "mp4", {"audioShiftMs": 500}, 0, 4_000_000, _w)
    check(_p.get("delayMode") == "reencode",
          "without the option the default stays the exact re-encode")
    _w = []
    _p = exports._audio_plan(_FakeDB(_row_aac), _sel, "matroska",
                             {"audioShiftMs": 500, "delayNoReencode": True}, 0, 4_000_000, _w)
    check(_p["offsets"]["audio"] == 500_000 and _p.get("delayMode") == "timestamp",
          "matroska supports the timestamp delay (block timestamps)")
    _w = []
    _p = exports._audio_plan(_FakeDB(_row_aac), _sel, "mp4",
                             {"audioMode": "bothTracks", "addedSourceId": "add",
                              "audioShiftMs": 500, "delayNoReencode": True}, 0, 4_000_000, _w)
    check(_p["offsets"]["audio"] == 500_000 and not _p["offsets"].get("audioDelayUs")
          and _p.get("delayMode") == "timestamp" and _p.get("added") is not None,
          "bothTracks uses the timestamp delay as well: " + str(_p["offsets"]))
    _no_start = [{"index": 0, "type": "video", "codec": "h264"},
                 {"index": 1, "type": "audio", "codec": "aac", "channels": 2, "sample_rate": 48000}]
    _w = []
    _p = exports._audio_plan(_FakeDB(_row_aac), _no_start, "mp4",
                             {"audioShiftMs": 500, "delayNoReencode": True}, 0, 4_000_000, _w)
    check(_p["offsets"]["audio"] == 500_000 and _p.get("delayMode") == "timestamp",
          "a missing audio start_time still uses the timestamp delay when requested")
    check(not _p["offsets"].get("audioPreUs") and not _p["offsets"].get("audioSkipUs"),
          "the timestamp route does not move the cut (no reach-back)")
    # audio-only exports already ride the container start (not the new option)
    _audio_only = [{"index": 0, "type": "audio", "codec": "aac", "channels": 1, "sample_rate": 48000}]
    _w = []
    _p = exports._audio_plan(_FakeDB(_row_aac), _audio_only, "mp4", {"audioShiftMs": 500}, 0, 4_000_000, _w)
    check(_p.get("delayMode") == "timestamp" and _p["offsets"]["audio"] == 500_000,
          "audio-only positive shifts report the timestamp delay: " + str(_p.get("delayMode")))
    # bothTracks: the added track keeps its own zero placement
    _w = []
    _p = exports._audio_plan(_FakeDB(_row_aac), _sel, "mp4",
                             {"audioMode": "bothTracks", "addedSourceId": "add",
                              "audioShiftMs": 500, "delayNoReencode": True}, 0, 4_000_000, _w)
    _add = _p.get("added") or {}
    check(_add.get("startUs") == 0 and _add.get("headSkipUs") == 0 and _add.get("reencode") is False,
          "bothTracks keeps the added track placement unchanged: " + str(_add))
    _w = []
    _p = _audio_plan(_FakeDB(_row_aac), _sel, "mp4", dict(_opt), 0, 4_000_000, _w)
    check(_p["added"]["reencode"] is False, "a compatible added codec is copied while the checkbox is off")
    _w = []
    _p = _audio_plan(_FakeDB(_row_aac), _sel, "mp4", dict(_opt, addedReencode=True), 0, 4_000_000, _w)
    check(_p["added"]["reencode"] is True, "the checkbox forces the added track to be re-encoded")
    check(any("再エンコード" in x for x in _w), "the forced re-encode is reported as a warning")
    _w = []
    _p = _audio_plan(_FakeDB(_row_flac), _sel, "mp4", dict(_opt, addedReencode=True), 0, 4_000_000, _w)
    check(_p["added"]["reencode"] is True and _p["added"]["codec"] == "aac",
          "an incompatible codec is re-encoded to the container codec")
    try:
        _audio_plan(_FakeDB(_row_flac), _sel, "mp4", dict(_opt), 0, 4_000_000, [])
        check(False, "an incompatible codec without the checkbox is refused")
    except ValueError:
        check(True, "an incompatible codec without the checkbox is refused")

    # --- db migration columns and job pruning (audit #10, #8) ---
    import tempfile as _tf  # noqa: E402
    from app.db import Database  # noqa: E402
    _tmpdir = _tf.mkdtemp(prefix="trimdb")
    try:
        _db = Database(os.path.join(_tmpdir, "t.db"))
        check("meta_json" in {x["name"] for x in _db.query("PRAGMA table_info(sources)")},
              "sources migration adds meta_json")
        check("error" in {x["name"] for x in _db.query("PRAGMA table_info(jobs)")},
              "jobs migration adds error")
        for i in range(5):
            _db.execute("INSERT INTO jobs (id, created_at, updated_at) VALUES (?,?,?)",
                        ("j%d" % i, float(i), float(i)))
        _db.prune_jobs(keep=3)
        check({x["id"] for x in _db.query("SELECT id FROM jobs")} == {"j2", "j3", "j4"},
              "prune_jobs keeps the newest rows")
    finally:
        shutil.rmtree(_tmpdir, ignore_errors=True)

    # --- host allowlist (audit #10) ---
    check(security.host_allowed("localhost", set()) is True, "localhost is allowed")
    check(security.host_allowed("", set()) is False, "empty host is rejected")
    check(security.host_allowed("unknown.example.com", set(), set()) is False,
          "unknown names are rejected without DNS resolution")
    check(security.host_allowed("notebook.ts.net", set(), set()) is True,
          "tailnet MagicDNS names are allowed")
    check(security.host_allowed("192.168.1.5", {"192.168.1.5"}) is True,
          "listed LAN IPs are allowed")
    check(security.host_allowed("8.8.8.8", set(), set()) is False,
          "public IPs are rejected")
    print("unit checks: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
