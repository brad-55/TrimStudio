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
    check(not security.host_allowed("pc.tailnet.ts.net:8003", {"127.0.0.1"}, names, True, set(), set(), False),
          "ts.net host rejected from a lan client")
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

    check(sources.security_path_sanitize("CON.mp3").startswith("_"), "reserved upload name")

    print("unit checks: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
