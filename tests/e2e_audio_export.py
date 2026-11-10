"""E2E for the audio timing export wiring (docs/PLAN_AUDIO_EXPORT.md section 6.2)."""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8003"
D = os.path.join("data", "test", "aux")
FF = os.path.join("tools", "ffmpeg", "bin", "ffmpeg.exe")
FP = os.path.join("tools", "ffmpeg", "bin", "ffprobe.exe")

fails = 0


def check(cond, label):
    global fails
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        fails += 1


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"X-Trim-Token": TOKEN}
    if data:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8", "replace"))


def wait_job(jid, timeout=300):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st, r = call("GET", "/api/jobs/" + jid)
        j = (r or {}).get("job") or {}
        if j.get("status") in ("done", "error", "cancelled"):
            return j
        time.sleep(1.0)
    return {"status": "timeout"}


def export(src_id, a, b, options, mode="lossless"):
    # the source may still be indexing: the range only lands on the keyframes once the
    # index exists, so retry until the requested start is honoured
    j = {}
    for _ in range(30):
        st, r = call("POST", "/api/exports", {"sourceId": src_id, "startUs": a, "endUs": b,
                                              "mode": mode, "options": options})
        if st != 200:
            return st, r
        j = wait_job(r.get("jobId"))
        res = j.get("result") or {}
        if j.get("status") != "done" or abs((res.get("actualStartUs") or 0) - a) <= 1000:
            return st, j
        time.sleep(2.0)
    return st, j


def run(args):
    p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        print("   ffmpeg:", (p.stderr or "")[-260:].replace("\n", " "))
    return p


def streams_of(path):
    p = run([FP, "-v", "error", "-print_format", "json", "-show_streams", path])
    try:
        return json.loads(p.stdout)["streams"]
    except Exception:
        return []


def subtitle_texts(path, start=None, dur=None):
    """Decoded cue texts of the first subtitle track (timings stripped)."""
    import re as _re
    pre = ["-ss", str(start), "-t", str(dur)] if start is not None else []
    p = subprocess.run([FF, "-v", "error", "-i", path] + pre + ["-map", "0:s", "-f", "srt", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        return None
    lines = []
    for ln in (p.stdout or "").splitlines():
        s = ln.strip()
        if not s or s.isdigit() or "-->" in s:
            continue
        lines.append(s)
    return lines


def flash_time(path):
    """When the picture actually turns white: the content-level video reference."""
    import re as _re
    p = subprocess.run([FF, "-hide_banner", "-i", path, "-vf", "select='gt(scene,0.2)',showinfo",
                        "-f", "null", "-"], capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    m = _re.search(r"pts_time:([0-9.]+)", p.stderr or "")
    return float(m.group(1)) if m else None


def beep_time(path):
    """When the tone actually starts: the content-level audio reference."""
    import re as _re
    p = subprocess.run([FF, "-hide_banner", "-i", path, "-af", "silencedetect=noise=-40dB:d=0.02",
                        "-f", "null", "-"], capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    m = _re.search(r"silence_end:\s*([0-9.]+)", p.stderr or "")
    return float(m.group(1)) if m else None


def packet_md5(path, stream_spec, start=None, dur=None):
    """Packet-level bit identity (plan E2E 1): reframe the copied AAC packets to ADTS
    and hash the bytes.  Decoded-sample hashes are sensitive to edit lists and priming
    and would false-alarm on a perfectly lossless copy."""
    # output-side seek mirrors the pipeline's cut exactly (first packet >= start), so
    # the reference carries the same packet sequence as the export
    pre = []
    if start is not None:
        pre = ["-ss", str(start), "-t", str(dur)]
    p = subprocess.run([FF, "-v", "error", "-i", path] + pre + ["-map", stream_spec, "-c", "copy",
                       "-f", "adts", "-"], capture_output=True)
    import hashlib
    if p.returncode != 0:
        return "ERR:" + (p.stderr or b"")[:80].decode("utf-8", "replace")
    return hashlib.md5(p.stdout).hexdigest()


def elst_media_times(path):
    """Minimal MP4 box walk: moov>trak>edts>elst entries as (duration, media_time)."""
    with open(path, "rb") as fh:
        data = fh.read()

    def boxes(buf, off, end, depth, path_names, out):
        while off + 8 <= end and depth < 8:
            size = int.from_bytes(buf[off:off + 4], "big")
            kind = buf[off + 4:off + 8]
            if size < 8:
                return
            name = ".".join(path_names + [kind.decode("latin1")])
            body_off = off + 8
            if kind == b"elst":
                out.append(name)
                body = buf[body_off:off + size]
                ver = body[0]
                n = int.from_bytes(body[4:8], "big")
                pos = 8
                for _ in range(n):
                    if ver == 1:
                        seg = int.from_bytes(body[pos:pos + 8], "big")
                        mt = int.from_bytes(body[pos + 8:pos + 16], "big", signed=True)
                        pos += 20
                    else:
                        seg = int.from_bytes(body[pos:pos + 4], "big")
                        mt = int.from_bytes(body[pos + 4:pos + 8], "big", signed=True)
                        pos += 12
                    out.append((seg, mt))
            boxes(buf, body_off, off + size, depth + 1, path_names + [kind.decode("latin1")], out)
            off += size

    out = []
    boxes(data, 0, len(data), 0, [], out)
    return [x for x in out if isinstance(x, tuple)]


def main():
    # the server must be running this working tree and the decoding ffmpeg must be the
    # app's own binary, otherwise the whole suite validates the wrong code
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _harness import packet_times, require_current, require_ffmpeg
    require_current(BASE, TOKEN)
    print("ffmpeg:", require_ffmpeg(BASE, FF, TOKEN))
    os.makedirs(D, exist_ok=True)
    # controlled fixtures: 12s h264+aac and a 9s aac side file
    # a unique name per run: /api/sources/open dedupes by path and the old record
    # would carry the keyframe index of a previous file
    stamp = str(int(time.time()))
    vpath = os.path.abspath(os.path.join(D, "src_e2e_" + stamp + ".mp4"))
    apath = os.path.abspath(os.path.join(D, "add_e2e_" + stamp + ".m4a"))
    run([FF, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30:duration=12",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=12",
         "-c:v", "libx264", "-g", "30", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", vpath])
    run([FF, "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=880:duration=9",
         "-c:a", "aac", apath])
    fpath = os.path.abspath(os.path.join(D, "add_e2e_" + stamp + ".flac"))
    run([FF, "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=660:duration=9",
         "-c:a", "flac", fpath])
    for p in (vpath, apath, fpath):
        st, r = call("POST", "/api/sources/open", {"path": p})
        if st != 200:
            print("open failed:", st, r); return 1
    mpath = os.path.abspath(os.path.join(D, "marker_e2e_" + stamp + ".mp4"))
    run([FF, "-y", "-v", "error", "-f", "lavfi", "-i", "color=black:s=320x240:r=30:d=1",
         "-f", "lavfi", "-i", "color=white:s=320x240:r=30:d=11",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=11",
         "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]",
         "-map", "[v]", "-map", "2:a", "-af", "adelay=1000",
         "-c:v", "libx264", "-g", "15", "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", "12", mpath])
    st, r5 = call("POST", "/api/sources/open", {"path": mpath})
    marker = (r5 or {}).get("source") or {}
    if not marker.get("id"):
        print("marker source open failed"); return 1
    st, r2 = call("POST", "/api/sources/open", {"path": vpath})
    vid = (r2 or {}).get("source") or {}
    st, r3 = call("POST", "/api/sources/open", {"path": apath})
    aud = (r3 or {}).get("source") or {}
    st, r4 = call("POST", "/api/sources/open", {"path": fpath})
    flac = (r4 or {}).get("source") or {}
    if not (vid.get("id") and aud.get("id") and flac.get("id")):
        print("open failed"); return 1
    print("video source:", vid.get("name"), "| added source:", aud.get("name"),
          "| incompatible:", flac.get("name"))
    L = 4.0

    # --- 1/2: original +/-2s keeps the packets bit exact (plan E2E 1) ---
    st, j = export(vid["id"], 2_000_000, 6_000_000, {"audioShiftMs": 2000})
    out1 = (j.get("result") or {}).get("outputPath") if j.get("status") == "done" else None
    check(j.get("status") == "done" and out1, "export +2000ms succeeds: " + str(j.get("error"))[:400])
    _au1 = (j.get("result") or {}).get("audio") or {}
    check(_au1.get("contentMs", {}).get("reachBack") == 2000.0 and not _au1.get("ignored"),
          "the job result reports the content delay for +2000ms: " + str(_au1)[:200])
    if out1:
        # Independent oracle: the source's own packet grid is measured straight from the
        # file (no seek), never by re-running the pipeline's cut.  A positive delay is
        # carried in the CONTENT (cut from [start-shift, end-shift)) so every player
        # hears it -- not in container timestamps, which some players ignore.
        # Boundary spec (see docs/TEST_DESIGN.md): the export starts at the frame that
        # *contains* the in point, so it may carry one priming packet at the head, and
        # no packet at or after the out point.
        src = packet_times(vpath, "0:a")
        exact = [t0 for t0 in src if 0.0 - 1e-6 <= t0 < 4.0 - 1e-6]
        got = packet_times(out1, "0:a")
        check(len(exact) <= len(got) <= len(exact) + 1,
              "boundary: packet count matches the reached-back interval (+1 priming max): %d vs %d"
              % (len(got), len(exact)))
        steps = sorted({round(got[i + 1] - got[i], 6) for i in range(len(got) - 1)})
        check(len(steps) <= 2 and (max(steps) - min(steps) < 5e-6),  # 5us: float rounding only
              # any real re-timing would move a packet by a whole frame (~21-23ms)
              "boundary: the packet grid stays uniform (no re-timing): " + str(steps[:3]))
        check(abs(got[0]) < 0.2,
              "boundary: the content-delayed audio still starts at zero: " + str(got[0]))
    if out1:
        ast = [s for s in streams_of(out1) if s.get("codec_type") == "audio"]
        vst = [s for s in streams_of(out1) if s.get("codec_type") == "video"]
        check(packet_md5(out1, "0:a") == packet_md5(vpath, "0:a", 0.0, 4.0),
              "+2000ms keeps the audio packets bit exact (content from [0s,4s))")
        check(abs(float(ast[0].get("duration")) - L) < 0.15, "+2000ms keeps the interval length: " + str(ast[0].get("duration")))
        check(abs(float(ast[0].get("start_time") or 0)) < 0.25,
              "+2000ms keeps the audio at zero (the delay rides in the content): start="
              + str(ast[0].get("start_time")))
        # No edit list is needed anymore: both tracks start at zero, so there is
        # nothing for a player to normalise away.  The content-level oracle below
        # proves the sound itself moved.
        print("   starts:", {s["codec_type"]: s.get("start_time") for s in ast + vst})
    # No room to reach back (the interval starts at zero): the delay falls back
    # to container timestamps, and the export says so instead of silently
    # producing an unshifted file.
    st, j = export(vid["id"], 0, 4_000_000, {"audioShiftMs": 2000})
    out1b = (j.get("result") or {}).get("outputPath") if j.get("status") == "done" else None
    check(j.get("status") == "done" and out1b, "export +2000ms at file head succeeds: " + str(j.get("error"))[:400])
    if out1b:
        # No earlier audio exists, so the delay is baked in with audio-only re-encode
        # (video stays a lossless copy) -- an edit list would be ignored by players.
        _w1b = (j.get("result") or {}).get("warnings") or []
        check(any("音声のみ再エンコード" in str(x) for x in _w1b),
              "the no-room case bakes the delay into the audio: " + str(_w1b)[:200])
        _c1b = ((j.get("result") or {}).get("audio") or {}).get("contentMs") or {}
        check(_c1b.get("audioDelay") == 2000.0, "the job result records the baked delay: " + str(_c1b))
        _a1b = [s for s in streams_of(out1b) if s.get("codec_type") == "audio"]
        _v1b = [s for s in streams_of(out1b) if s.get("codec_type") == "video"]
        check(_a1b and abs(float(_a1b[0].get("start_time") or 0)) < 0.25,
              "the baked delay keeps the audio at zero (no edit list needed): "
              + str(_a1b[0].get("start_time") if _a1b else None))
        check(_v1b and abs(float(_v1b[0].get("start_time") or 0)) < 0.25,
              "the video is still untouched at zero: " + str(_v1b[0].get("start_time") if _v1b else None))
    # Re-encode route: the shift is baked in with adelay, so it works on every
    # player even at the file head (this is the always-working escape hatch).
    st, j = export(marker["id"], 500_000, 4_000_000,
                   {"audioShiftMs": 800, "audioTiming": True}, mode="reencode")
    outR = (j.get("result") or {}).get("outputPath") if j.get("status") == "done" else None
    check(j.get("status") == "done" and outR, "reencode +800ms export succeeds: " + str(j.get("error"))[:400])
    if outR:
        _auR = (j.get("result") or {}).get("audio") or {}
        check(_auR.get("contentMs", {}).get("filterMs") == 800.0,
              "the job result records the re-encoded shift: " + str(_auR)[:200])
        check(any("再エンコード" in str(x) for x in ((j.get("result") or {}).get("warnings") or [])),
              "the re-encoded shift warns about the audio re-encode")
        _bp = beep_time(outR)
        check(_bp is not None and abs(_bp - 1.3) < 0.15,
              "the re-encoded sound really moves by +800ms at the content level: measured %s" % _bp)
    st, j = export(vid["id"], 2_000_000, 6_000_000, {"audioShiftMs": -2000})
    out2 = (j.get("result") or {}).get("outputPath") if j.get("status") == "done" else None
    check(j.get("status") == "done" and out2, "export -2000ms succeeds: " + str(j.get("error"))[:400])
    if out2:
        # A negative shift advances the ORIGINAL audio's content: both tracks stay at
        # zero (so no player can normalise the shift away) and the audio comes from
        # [start + 2s, end + 2s].
        src = packet_times(vpath, "0:a")
        exact = [t0 for t0 in src if 4.0 - 1e-6 <= t0 < 8.0 - 1e-6]
        got2 = packet_times(out2, "0:a")
        check(len(exact) <= len(got2) <= len(exact) + 1,
              "boundary: the advanced audio interval has the right packet count: %d vs %d"
              % (len(got2), len(exact)))
        check(abs(got2[0]) < 0.2,
              "boundary: the advanced audio still starts together with the video: " + str(got2[0]))
        ast = [s for s in streams_of(out2) if s.get("codec_type") == "audio"]
        vst = [s for s in streams_of(out2) if s.get("codec_type") == "video"]
        check(packet_md5(out2, "0:a") == packet_md5(vpath, "0:a", 4.0, 4.0),
              "-2000ms advances the audio content (packets from the source's 4s-8s)")
        check(abs(float(vst[0].get("start_time") or 0)) < 0.25,
              "-2000ms leaves the video (the reference track) at zero: start="
              + str(vst[0].get("start_time")))
        check(abs(float(ast[0].get("start_time") or 0)) < 0.25,
              "-2000ms leaves the audio at zero as well: start=" + str(ast[0].get("start_time")))
        print("   starts:", {s["codec_type"]: s.get("start_time") for s in ast + vst})

    # --- 3: audio-only +/- (plan 0.7 / E2E 3) ---
    st, j = export(aud["id"], 1_000_000, 5_000_000, {"audioShiftMs": 1500})
    out3 = (j.get("result") or {}).get("outputPath") if j.get("status") == "done" else None
    check(j.get("status") == "done" and out3, "audio-only +1500ms succeeds: " + str(j.get("error"))[:400])
    if out3:
        ast = streams_of(out3)
        check(abs(float(ast[0].get("duration") or 0) - L) < 0.15, "audio-only +1500ms length: " + str(ast[0].get("duration")))
        check(abs(float(ast[0].get("start_time") or 0) - 1.5) < 0.3,
              "audio-only +1500ms lands at the shift: start=" + str(ast[0].get("start_time")))
    st, j = export(aud["id"], 1_000_000, 5_000_000, {"audioShiftMs": -1500})
    out3b = (j.get("result") or {}).get("outputPath") if j.get("status") == "done" else None
    check(j.get("status") == "done" and out3b, "audio-only -1500ms (mp4) succeeds: " + str(j.get("error"))[:400])

    # --- the content-level oracle: does the shift really move the sound? ---
    # The picture turns white at source 1.0s and the tone starts at source 1.0s, so the
    # measured (tone - cut) must equal the requested shift with its sign. This is
    # independent of packet metadata (the E2E 1/2 checks) and catches an inverted sign.
    print("\n-- content level shift (picture cut vs tone onset) --")
    for shift, want in ((0, 0.0), (100, 0.1), (-100, -0.1), (600, 0.6)):
        st, j = export(marker["id"], 500_000, 4_000_000, {"audioShiftMs": shift, "audioTiming": True})
        mout = (j.get("result") or {}).get("outputPath") if j.get("status") == "done" else None
        check(j.get("status") == "done" and mout, "marker export %+dms succeeds: %s"
              % (shift, str(j.get("error"))[:200]))
        if not mout:
            continue
        fl, bp = flash_time(mout), beep_time(mout)
        got = None if (fl is None or bp is None) else round(bp - fl, 4)
        check(got is not None and abs(got - want) < 0.06,
              "the sound really moves by %+dms at the content level: measured %s" % (shift, got))
        # positive shifts are expressed as the audio's container start; negative ones ride
        # in the content, so their start must stay at zero
        _a = [s for s in streams_of(mout) if s.get("codec_type") == "audio"]
        _v = [s for s in streams_of(mout) if s.get("codec_type") == "video"]
        # A delay is carried either in the content (cut reaches back, start stays 0)
        # or baked in with audio-only re-encode (also start 0); only the mixed /
        # no-room timestamp route would show a nonzero start.
        _cm = ((j.get("result") or {}).get("audio") or {}).get("contentMs") or {}
        _baked = (_cm.get("audioDelay") or 0) > 0 or (_cm.get("reachBack") or 0) > 0
        _want_start = 0.0 if _baked else max(0.0, shift) / 1000.0
        check(_a and abs(float(_a[0].get("start_time") or 0) - _want_start) < 0.12,
              "a %+dms shift places the audio start at %.3fs: %s"
              % (shift, _want_start, (_a[0].get("start_time") if _a else None)))
        check(_v and abs(float(_v[0].get("start_time") or 0)) < 0.12,
              "a %+dms shift never moves the video (the reference track): %s"
              % (shift, (_v[0].get("start_time") if _v else None)))

    # --- subtitles ride with the video on every route ---
    # Regression: gating the subtitle cut on `shifted` dropped subtitles on the
    # plain route and on the negative-shift (content-advance) route, where all
    # offsets are zero.  Cues must come from the video interval [2,6) every time.
    spath = os.path.abspath(os.path.join(D, "sub_e2e_" + stamp + ".srt"))
    with open(spath, "w", encoding="utf-8") as fh:
        for i in range(6):
            fh.write("%d\n00:00:%02d,000 --> 00:00:%02d,000\ncue %d\n\n"
                       % (i + 1, 2 * i, 2 * i + 1, i + 1))
    subpath = os.path.abspath(os.path.join(D, "sub_e2e_" + stamp + ".mkv"))
    run([FF, "-y", "-v", "error", "-i", vpath, "-i", spath,
         "-map", "0:v", "-map", "0:a", "-map", "1", "-c", "copy", "-shortest", subpath])
    st, r6 = call("POST", "/api/sources/open", {"path": subpath})
    sub = (r6 or {}).get("source") or {}
    if not sub.get("id"):
        print("subtitle fixture open failed"); return 1
    for _ in range(120):
        st, kf = call("GET", "/api/sources/%s/keyframes" % sub["id"])
        if (kf or {}).get("state") in ("ready", "error"):
            break
        time.sleep(0.4)
    for shift in (0, -2000, 2000):
        st, j = export(sub["id"], 2_000_000, 6_000_000,
                       {"audioShiftMs": shift, "audioTiming": True, "container": "matroska"})
        sout = (j.get("result") or {}).get("outputPath") if j.get("status") == "done" else None
        check(j.get("status") == "done" and sout, "subtitle export %+dms succeeds: %s"
              % (shift, str(j.get("error"))[:200]))
        if not sout:
            continue
        sst = [s for s in streams_of(sout) if s.get("codec_type") == "subtitle"]
        check(len(sst) == 1, "subtitle survives a %+dms shift: %d subtitle tracks"
              % (shift, len(sst)))
        if sst:
            check(sst[0].get("codec_name") in ("srt", "subrip"),
                  "the subtitle track stays srt/subrip (copied, not re-encoded): "
                  + str(sst[0].get("codec_name")))
            check(subtitle_texts(sout) == subtitle_texts(subpath, 2.0, 4.0),
                  "subtitle cues come from the video interval [2s,6s) at %+dms: %s"
                  % (shift, subtitle_texts(sout)))

    # --- 4: added mode with addedStartMs (plan E2E 4) ---
    st, j = export(vid["id"], 2_000_000, 6_000_000,
                   {"audioMode": "added", "addedSourceId": aud["id"], "addedStartMs": 1000, "audioTiming": True})
    out4 = (j.get("result") or {}).get("outputPath") if j.get("status") == "done" else None
    check(j.get("status") == "done" and out4, "added mode succeeds: " + str(j.get("error"))[:400])
    if out4:
        ast = [s for s in streams_of(out4) if s.get("codec_type") == "audio"]
        check(len(ast) == 1, "added mode has exactly one audio track")
        check(packet_md5(out4, "0:a") == packet_md5(apath, "0:a", 1.0, 4.0),
              "added audio comes from addedStartMs=1000")
        check(abs(float(ast[0].get("start_time") or 0)) < 0.1,
              "the added-only track starts at zero (the head skip is content, not an offset): "
              + str(ast[0].get("start_time")))

    # --- 12: the re-encode checkbox really re-encodes only the added track ---
    st, j = export(vid["id"], 2_000_000, 6_000_000,
                   {"audioMode": "added", "addedSourceId": aud["id"], "addedStartMs": 0,
                    "audioTiming": True, "addedReencode": False})
    outR0 = (j.get("result") or {}).get("outputPath") if j.get("status") == "done" else None
    check(j.get("status") == "done" and outR0, "added copy export succeeds: " + str(j.get("error"))[:300])
    if outR0:
        check(packet_md5(outR0, "0:a") == packet_md5(apath, "0:a", 0.0, 4.0),
              "checkbox off: the added track is a bit exact copy")
    st, j = export(vid["id"], 2_000_000, 6_000_000,
                   {"audioMode": "added", "addedSourceId": aud["id"], "addedStartMs": 0,
                    "audioTiming": True, "addedReencode": True})
    outR1 = (j.get("result") or {}).get("outputPath") if j.get("status") == "done" else None
    check(j.get("status") == "done" and outR1, "added re-encode export succeeds: " + str(j.get("error"))[:300])
    if outR1:
        check(packet_md5(outR1, "0:a") != packet_md5(apath, "0:a", 0.0, 4.0),
              "checkbox on: the added track is re-encoded")
        check(any("再エンコード" in str(w) for w in ((j.get("result") or {}).get("warnings") or [])),
              "checkbox on: the result warns about the added re-encode")
        ast = [s for s in streams_of(outR1) if s.get("codec_type") == "audio"]
        check(len(ast) == 1 and ast[0].get("codec_name") == "aac",
              "the re-encoded track uses the container codec: " + str([s.get("codec_name") for s in ast]))
    # a codec the container cannot copy is refused unless the checkbox allows it
    st, j = export(vid["id"], 2_000_000, 6_000_000,
                   {"audioMode": "added", "addedSourceId": flac["id"], "audioTiming": True,
                    "addedReencode": False})
    check(st == 400, "an incompatible added codec is refused while the checkbox is off: " + str(st))
    st, j = export(vid["id"], 2_000_000, 6_000_000,
                   {"audioMode": "added", "addedSourceId": flac["id"], "audioTiming": True,
                    "addedReencode": True})
    check(j.get("status") == "done", "the checkbox lets an incompatible codec through: " + str(j.get("error"))[:300])

    # --- added mode reports that the original shift does not apply (plan 0.8b) ---
    st, j = export(vid["id"], 2_000_000, 6_000_000,
                   {"audioMode": "added", "addedSourceId": aud["id"], "addedStartMs": 0,
                    "audioShiftMs": 500, "audioTiming": True})
    _w = ((j.get("result") or {}).get("warnings") or [])
    check(j.get("status") == "done" and any("追加のみ" in str(x) for x in _w),
          "added mode reports the ignored original shift: " + str(_w)[:160])

    # --- 5/6: bothTracks with independent shifts (plan E2E 5/6) ---
    st, j = export(vid["id"], 2_000_000, 6_000_000,
                   {"audioMode": "bothTracks", "addedSourceId": aud["id"],
                    "audioShiftMs": -1000, "addedShiftMs": -500, "audioTiming": True})
    out5 = (j.get("result") or {}).get("outputPath") if j.get("status") == "done" else None
    check(j.get("status") == "done" and out5, "bothTracks with both shifts succeeds: " + str(j.get("error"))[:400])
    if out5:
        ast = [s for s in streams_of(out5) if s.get("codec_type") == "audio"]
        check(len(ast) == 2, "bothTracks keeps two audio tracks: " + str(len(ast)))
        if len(ast) == 2:
            check(packet_md5(out5, "0:a:0") == packet_md5(vpath, "0:a", 3.0, 4.0),
                  "track 0 is the original audio advanced by 1000ms (content based)")
            check(packet_md5(out5, "0:a:1") == packet_md5(apath, "0:a", 0.5, 4.0),
                  "track 1 is the added audio advanced by 500ms (head skip)")
            print("   starts:", {i: s.get("start_time") for i, s in enumerate(ast)})

    # --- 7: bothMix (plan 0.4 / E2E 15) ---
    st, j = export(vid["id"], 2_000_000, 6_000_000,
                   {"audioMode": "bothMix", "addedSourceId": aud["id"], "addedShiftMs": 800, "audioTiming": True})
    out6 = (j.get("result") or {}).get("outputPath") if j.get("status") == "done" else None
    check(j.get("status") == "done" and out6, "bothMix succeeds: " + str(j.get("error"))[:120])

    # the plan's coverage table had empty cells for the mix route at 0 and at a negative
    # original shift: both must still produce one track of the interval length
    for shift, label in ((0, "0ms"), (-1200, "-1200ms")):
        st, j = export(vid["id"], 2_000_000, 6_000_000,
                       {"audioMode": "bothMix", "addedSourceId": aud["id"], "audioShiftMs": shift,
                        "addedShiftMs": 0, "audioTiming": True})
        outm = (j.get("result") or {}).get("outputPath") if j.get("status") == "done" else None
        check(j.get("status") == "done" and outm,
              "bothMix with the original %s succeeds: %s" % (label, str(j.get("error"))[:200]))
        if outm:
            ast = [s for s in streams_of(outm) if s.get("codec_type") == "audio"]
            check(len(ast) == 1, "bothMix %s outputs one mixed track" % label)
            check(abs(float(ast[0].get("duration") or 0) - L) < 0.2,
                  "bothMix %s keeps the interval length: %s" % (label, ast[0].get("duration")))
    if out6:
        ast = [s for s in streams_of(out6) if s.get("codec_type") == "audio"]
        check(len(ast) == 1, "bothMix outputs one mixed track")
        check(abs(float(ast[0].get("duration") or 0) - L) < 0.3,
              "bothMix keeps the interval length: " + str(ast[0].get("duration")))
        check(any(w for w in (j.get("result") or {}).get("warnings", []) if "再エンコード" in w),
              "bothMix warns about the audio re-encode")

    # --- 8: mute (plan E2E 8) ---
    st, j = export(vid["id"], 2_000_000, 6_000_000, {"audioMode": "mute", "audioTiming": True})
    out7 = (j.get("result") or {}).get("outputPath") if j.get("status") == "done" else None
    check(j.get("status") == "done" and out7, "mute succeeds")
    if out7:
        check(not [s for s in streams_of(out7) if s.get("codec_type") == "audio"], "mute has no audio stream")

    # --- 9: audioTiming=false ignores every timing option (plan E2E 9) ---
    st, j = export(vid["id"], 2_000_000, 6_000_000,
                   {"audioTiming": False, "audioMode": "added", "addedSourceId": aud["id"],
                    "audioShiftMs": 3000, "addedShiftMs": 3000})
    out8 = (j.get("result") or {}).get("outputPath") if j.get("status") == "done" else None
    check(j.get("status") == "done" and out8, "audioTiming=false with added options is accepted")
    if out8:
        ast = [s for s in streams_of(out8) if s.get("codec_type") == "audio"]
        check(len(ast) == 1, "audioTiming=false ignores the added track")
        _w = ((j.get("result") or {}).get("warnings") or [])
        check(any("OFF" in str(x) for x in _w),
              "a shift typed while the switch is off is reported: " + str(_w)[:160])
        _au = (j.get("result") or {}).get("audio") or {}
        check(_au.get("timingOn") is False and _au.get("ignored"),
              "the job result records what the switch dropped: " + str(_au)[:160])
        check(packet_md5(out8, "0:a") == packet_md5(vpath, "0:a", 2.0, 4.0),
              "audioTiming=false keeps the original audio bit exact")
        check(abs(float(ast[0].get("start_time") or 0)) < 0.25,
              "audioTiming=false does not shift: start=" + str(ast[0].get("start_time")))

    # --- 9b: delayNoReencode (opt-in; packets copied, container timestamp delay) ---
    _o9path = os.path.abspath(os.path.join(D, "delay_copy_e2e_" + stamp + ".mp4"))
    st, j = export(vid["id"], 0, 4_000_000, {"audioShiftMs": 500, "delayNoReencode": True,
                                             "outputPath": _o9path})
    out9 = (j.get("result") or {}).get("outputPath") if j.get("status") == "done" else None
    check(j.get("status") == "done" and out9,
          "delayNoReencode export succeeds: " + str(j.get("error"))[:300])
    if out9:
        _au = (j.get("result") or {}).get("audio") or {}
        check(_au.get("delayMode") == "timestamp",
              "the job reports the timestamp delay: " + str(_au)[:200])
        _ast = [s for s in streams_of(out9) if s.get("codec_type") == "audio"]
        _start = float((_ast[0] or {}).get("start_time") or 0) if _ast else 0
        check(0.45 <= _start <= 0.55,
              "the audio stream starts ~0.5s late: " + str(_start))
        # interval is half-open [0.0, 4.0): a packet exactly at the out point belongs to
        # neither side; the packet-count check below pins the boundary.
        check(packet_md5(out9, "0:a") == packet_md5(vpath, "0:a", 0.0, 4.0),
              "delayNoReencode keeps the audio packets bit exact (no re-encode)")
        _src_a = [s for s in streams_of(vpath) if s.get("codec_type") == "audio"]
        _same = bool(_ast and _src_a
                     and _ast[0].get("codec_name") == _src_a[0].get("codec_name")
                     and str(_ast[0].get("sample_rate")) == str(_src_a[0].get("sample_rate"))
                     and _ast[0].get("channels") == _src_a[0].get("channels"))
        check(_same, "the copied audio keeps the source codec parameters: " + str(_same))
        _src_count = len([t0 for t0 in packet_times(vpath, "0:a") if 0.0 <= t0 < 4.0])
        _out_count = len(packet_times(out9, "0:a"))
        check(_out_count == _src_count,
              "the copied audio keeps every source packet in the interval: %d vs %d"
              % (_out_count, _src_count))
        _pts = packet_times(out9, "0:a")
        _steps = sorted({round(_pts[i + 1] - _pts[i], 6) for i in range(len(_pts) - 1)})
        check(len(_pts) >= 2 and len(_steps) <= 2 and (max(_steps) - min(_steps) < 0.005),
              "the delayed audio keeps a uniform packet grid: %d packets %s"
              % (len(_pts), _steps[:3]))
        _vsrc_n = len([t0 for t0 in packet_times(vpath, "0:v") if 0.0 <= t0 < 4.0])
        _vout_n = len(packet_times(out9, "0:v"))
        _vst = [s for s in streams_of(out9) if s.get("codec_type") == "video"]
        _vsrc_s = [s for s in streams_of(vpath) if s.get("codec_type") == "video"]
        check(bool(_vst and _vsrc_s and _vst[0].get("codec_name") == _vsrc_s[0].get("codec_name")
                   and _vst[0].get("width") == _vsrc_s[0].get("width")
                   and _vst[0].get("height") == _vsrc_s[0].get("height")
                   and _vsrc_n <= _vout_n <= _vsrc_n + 2),
              "the video stream is copied unchanged (codec/dimensions/packets, +2 priming max): %d vs %d"
              % (_vout_n, _vsrc_n))
        _res = j.get("result") or {}
        check(_res.get("audioReencoded") is False and _res.get("lossless") is True,
              "delayNoReencode is reported as lossless: " + str((_res.get("audioReencoded"), _res.get("lossless"))))
        _w = (_res.get("warnings") or [])
        check(any("タイムスタンプ" in str(x) for x in _w),
              "the player caveat is warned: " + str(_w)[:220])
        check(not any("再エンコード" in str(x) for x in _w),
              "the timestamp route does not claim an audio re-encode: " + str(_w)[:220])

    # the default must stay the exact re-encode (this option is not the default)
    _o9bpath = os.path.abspath(os.path.join(D, "delay_reenc_e2e_" + stamp + ".mp4"))
    st, j = export(vid["id"], 0, 4_000_000, {"audioShiftMs": 500, "outputPath": _o9bpath})
    out9b = (j.get("result") or {}).get("outputPath") if j.get("status") == "done" else None
    if out9b:
        _au = (j.get("result") or {}).get("audio") or {}
        check(_au.get("delayMode") == "reencode",
              "the default still bakes the delay into the audio: " + str(_au)[:160])
        _ast = [s for s in streams_of(out9b) if s.get("codec_type") == "audio"]
        _start = float((_ast[0] or {}).get("start_time") or 0) if _ast else 0
        # The AAC encoder priming shows up as a ~23-67ms start_time even for a "0"
        # start; 250ms is a generous bound that still fails a baked 500ms silence.
        check(abs(_start) < 0.25, "the default export still starts at zero: " + str(_start))
        check(packet_md5(out9b, "0:a") != packet_md5(vpath, "0:a", 0.0, 4.0),
              "the default export re-encodes the audio (unchanged behaviour)")

    # --- 9c: the same option on matroska (block timestamps) ---
    _o9m = os.path.abspath(os.path.join(D, "delay_copy_mkv_e2e_" + stamp + ".mkv"))
    st, j = export(vid["id"], 0, 4_000_000, {"audioShiftMs": 500, "delayNoReencode": True,
                                             "container": "matroska", "outputPath": _o9m})
    out9m = (j.get("result") or {}).get("outputPath") if j.get("status") == "done" else None
    check(j.get("status") == "done" and out9m,
          "delayNoReencode on matroska succeeds: " + str(j.get("error"))[:300])
    if out9m:
        _au = (j.get("result") or {}).get("audio") or {}
        _ast = [s for s in streams_of(out9m) if s.get("codec_type") == "audio"]
        check(_au.get("delayMode") == "timestamp",
              "matroska reports the timestamp delay: " + str(_au)[:160])
        _start = float((_ast[0] or {}).get("start_time") or 0) if _ast else 0
        check(0.45 <= _start <= 0.55, "the matroska audio starts ~0.5s late: " + str(_start))
        _res = j.get("result") or {}
        check(_res.get("audioReencoded") is False and _res.get("lossless") is True,
              "matroska is reported as lossless: " + str((_res.get("audioReencoded"), _res.get("lossless"))))
        check(packet_md5(out9m, "0:a") == packet_md5(vpath, "0:a", 0.0, 4.0),
              "matroska keeps the audio packets bit exact")
        _src_count = len([t0 for t0 in packet_times(vpath, "0:a") if 0.0 <= t0 < 4.0])
        check(len(packet_times(out9m, "0:a")) == _src_count,
              "matroska keeps every source packet in the interval")
        _pts = packet_times(out9m, "0:a")
        _steps = sorted({round(_pts[i + 1] - _pts[i], 6) for i in range(len(_pts) - 1)})
        check(len(_pts) >= 2 and len(_steps) <= 2 and (max(_steps) - min(_steps) < 0.005),
              "matroska keeps a uniform packet grid (no broken intervals): %d packets %s"
              % (len(_pts), _steps[:3]))
        _vst = [s for s in streams_of(out9m) if s.get("codec_type") == "video"]
        _vsrc = [s for s in streams_of(vpath) if s.get("codec_type") == "video"]
        check(bool(_vst and _vsrc and _vst[0].get("codec_name") == _vsrc[0].get("codec_name")
                   and _vst[0].get("width") == _vsrc[0].get("width")
                   and _vst[0].get("height") == _vsrc[0].get("height")),
              "the video stream is still the copied source video")
        _vsrc_n = len([t0 for t0 in packet_times(vpath, "0:v") if 0.0 <= t0 < 4.0])
        _vout_n = len(packet_times(out9m, "0:v"))
        check(_vsrc_n <= _vout_n <= _vsrc_n + 2,
              "the matroska video keeps every source packet (+2 priming max): %d vs %d"
              % (_vout_n, _vsrc_n))
        _w = (_res.get("warnings") or [])
        check(not any("再エンコード" in str(x) for x in _w),
              "matroska does not claim an audio re-encode: " + str(_w)[:220])

    # --- 9d: an edit-list-less container falls back to the exact re-encode ---
    _o9f = os.path.abspath(os.path.join(D, "delay_fallback_e2e_" + stamp + ".flv"))
    st, j = export(vid["id"], 0, 4_000_000, {"audioShiftMs": 500, "delayNoReencode": True,
                                             "container": "flv", "outputPath": _o9f})
    out9f = (j.get("result") or {}).get("outputPath") if j.get("status") == "done" else None
    check(j.get("status") == "done" and out9f,
          "the fallback container still exports: " + str(j.get("error"))[:300])
    if out9f:
        _res = j.get("result") or {}
        _au = _res.get("audio") or {}
        _w = _res.get("warnings") or []
        check(_au.get("delayMode") == "reencode",
              "flv falls back to the exact re-encode: " + str(_au)[:160])
        check(_res.get("audioReencoded") is True,
              "the fallback is reported as re-encoded")
        check(any("無変換の遅延に対応しない" in str(x) for x in _w),
              "the fallback reason is warned: " + str(_w)[:220])
        check(packet_md5(out9f, "0:a") != packet_md5(vpath, "0:a", 0.0, 4.0),
              "the fallback really re-encodes the audio")

    # --- 10: error paths (plan E2E 11/17) ---
    st, r = call("POST", "/api/exports", {"sourceId": aud["id"], "startUs": 0, "endUs": 2_000_000,
                                          "mode": "lossless", "options": {"audioMode": "mute", "audioTiming": True}})
    check(st == 400, "audio-only + mute is rejected: " + str(st))
    st, r = call("POST", "/api/exports", {"sourceId": aud["id"], "startUs": 0, "endUs": 2_000_000,
                                          "mode": "lossless",
                                          "options": {"audioShiftMs": -1500, "container": "wav", "audioTiming": True}})
    check(st == 400, "audio-only + negative shift + elst-less container is rejected: " + str(st))
    st, r = call("POST", "/api/exports", {"sourceId": vid["id"], "startUs": 0, "endUs": 2_000_000,
                                          "mode": "lossless", "options": {"audioMode": "added", "audioTiming": True}})
    check(st == 404, "added mode without a source is rejected: " + str(st))
    st, r = call("POST", "/api/exports", {"sourceId": vid["id"], "startUs": 0, "endUs": 2_000_000,
                                          "mode": "lossless",
                                          "options": {"audioShiftMs": 500, "delayNoReencode": "maybe"}})
    check(st == 400, "an invalid delayNoReencode value is rejected: " + str(st))

    print("RESULT:", "OK" if fails == 0 else "FAIL(%d)" % fails)
    return 0 if fails == 0 else 1


TOKEN = ""
if __name__ == "__main__":
    with urllib.request.urlopen(BASE + "/api/token", timeout=10) as r:
        TOKEN = json.loads(r.read())["token"]
    sys.exit(main())
