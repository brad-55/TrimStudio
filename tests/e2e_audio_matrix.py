"""E2E matrix: original/added audio shifts on real h264/HEVC media.

Plan: docs/PLAN_ADDED_SHIFT_MATRIX.md (reviewed to full-Go).  Cases: 110
(20 baseline + 80 core + 4 addedReencode + 2 delayNoReencode + 4 full-source).

Run:  python tests/e2e_audio_matrix.py http://127.0.0.1:8013 [--filter=substr] [--skip-full]
"""
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

import numpy as np

BASE = "http://127.0.0.1:8013"
for _a in sys.argv[1:]:
    if _a.startswith("http://") or _a.startswith("https://"):
        BASE = _a
FILTER = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--filter=")), None)
SKIP_FULL = "--skip-full" in sys.argv

FF = os.path.abspath(os.path.join("tools", "ffmpeg", "bin", "ffmpeg.exe"))
FP = os.path.abspath(os.path.join("tools", "ffmpeg", "bin", "ffprobe.exe"))
D = os.path.join("data", "test", "matrix")
H264_FULL = r"L:\dev\VID_20261103_114920_003.trim-00h03m09s172-00h09m54s453.trim-00h00m00s000-00h06m45s269.mp4"
HEVC_FULL = r"L:\dev\ScreenRecording_05-25-2026 19-41-41_1_切出6.006s-24.814s_無変換_切出0s-18.938s_再エンコード_H265-NVENC_20261110-2358.mp4"
EXCERPT = os.path.join(D, "src_h264_real20.mp4")

SR = {"h264": EXCERPT, "hevc": HEVC_FULL}       # 元
AD = {"h264": HEVC_FULL, "hevc": EXCERPT}       # 追加
FL = {"h264": H264_FULL, "hevc": HEVC_FULL}     # full source
SR_DUR = {"h264": None, "hevc": None}
AD_DUR = {"h264": None, "hevc": None}
FULL_DUR = {"h264": None, "hevc": None}

S0, E0 = 6_000_000, 10_000_000
fails = 0
checks = 0
TOKEN = None
SRC_ID = {}


def log(msg):
    print(msg, flush=True)


def check(cond, label):
    global fails, checks
    checks += 1
    if not cond:
        fails += 1
        log("FAIL " + label)
    return cond


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {}
    if TOKEN:
        headers["X-Trim-Token"] = TOKEN
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw.decode("utf-8", "replace"))
        except Exception:
            return e.code, {"raw": raw[:200].decode("utf-8", "replace")}


def wait_job(jid, timeout=900):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st, r = call("GET", "/api/jobs/" + jid)
        j = (r or {}).get("job") or {}
        if j.get("status") in ("done", "error", "cancelled"):
            return j
        time.sleep(0.4)
    return {"status": "timeout"}


def run(args, timeout=1200):
    return subprocess.run(args, capture_output=True, timeout=timeout)


def probe_streams(path):
    p = run([FP, "-v", "error", "-print_format", "json", "-show_streams", "-show_format", path])
    try:
        return json.loads(p.stdout)
    except Exception:
        return {}


def streams(path):
    return (probe_streams(path) or {}).get("streams") or []


def stream_duration(path, kind="audio"):
    for s in streams(path):
        if s.get("codec_type") != kind:
            continue
        try:
            return float(s.get("duration") or 0)
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def start_time(path, spec="0:a:0"):
    """start_time of the nth audio stream (spec form 0:a:N)."""
    ss = streams(path)
    try:
        nth = int(spec.split(":")[-1])
    except Exception:
        nth = 0
    audios = [s for s in ss if s.get("codec_type") == "audio"]
    if nth >= len(audios):
        return None
    try:
        return float(audios[nth].get("start_time"))
    except (TypeError, ValueError):
        return None


def media_duration(path):
    fmt = (probe_streams(path) or {}).get("format") or {}
    try:
        return float(fmt.get("duration") or 0)
    except (TypeError, ValueError):
        return 0.0


def packet_md5(path, spec="0:a", start=None, dur=None):
    pre = []
    if start is not None:
        pre = ["-ss", "%.6f" % start, "-t", "%.6f" % dur]
    p = run([FF, "-v", "error", "-i", path] + pre + ["-map", spec, "-c", "copy", "-f", "adts", "-"])
    if p.returncode != 0 or not p.stdout:
        return "ERR"
    return hashlib.md5(p.stdout).hexdigest()


def decode(path, spec="0:a:0", start=None, dur=None, sr=48000):
    pre = []
    if start is not None:
        pre = ["-ss", "%.6f" % start, "-t", "%.6f" % dur]
    p = run([FF, "-v", "error", "-i", path] + pre +
            ["-map", spec, "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"])
    if p.returncode != 0 or not p.stdout:
        return None
    return np.frombuffer(p.stdout, dtype="<f4").astype(np.float64)


def packet_count(path, spec="0:v"):
    p = run([FP, "-v", "error", "-select_streams", spec, "-count_packets",
             "-show_entries", "stream=nb_read_packets", "-of", "json", path])
    try:
        return int(json.loads(p.stdout)["streams"][0]["nb_read_packets"])
    except Exception:
        return -1


def video_interval_count(path, start, dur):
    """Packets whose PTS is inside [start, start+dur) on the video stream."""
    p = run([FP, "-v", "error", "-select_streams", "v:0", "-show_entries",
             "packet=pts_time", "-of", "json", path])
    try:
        pkts = json.loads(p.stdout)["packets"]
        xs = [float(x["pts_time"]) for x in pkts if x.get("pts_time") not in (None, "N/A")]
        return len([x for x in xs if start - 1e-6 <= x < start + dur - 1e-6])
    except Exception:
        return -1


def corr_peak(actual, expected, max_lag_s=0.10, window_s=None, sr=48000):
    """Normalized cross-correlation peak (height, lag_s) of actual vs expected."""
    if actual is None or expected is None:
        return 0.0, 99.0
    n = min(len(actual), len(expected))
    if window_s is not None:
        n = min(n, int(window_s * sr))
    a = actual[:n]
    e = expected[:n]
    n = min(len(a), len(e))
    if n < sr // 10:
        return 0.0, 99.0
    a = a[:n] - a[:n].mean()
    e = e[:n] - e[:n].mean()
    na, ne = np.linalg.norm(a), np.linalg.norm(e)
    if na <= 1e-9 or ne <= 1e-9:
        return 0.0, 99.0
    nfft = 1 << (int(n * 2 - 1).bit_length())
    fa = np.fft.rfft(a, nfft)
    fe = np.fft.rfft(e, nfft)
    cc = np.fft.irfft(fa * np.conj(fe), nfft)
    lags = np.arange(nfft)
    lags = np.where(lags > nfft // 2, lags - nfft, lags)
    lim = int(max_lag_s * sr)
    mask = np.abs(lags) <= lim
    if not mask.any():
        return 0.0, 99.0
    idx = np.argmax(np.where(mask, cc, -1e30))
    return float(cc[idx] / (na * ne)), float(lags[idx] / sr)


def comp_threshold(e1, e2):
    total = e1 + e2
    if total <= 0:
        return 0.05
    # The energy of a component in the mix bounds how much it can correlate with the
    # sum: corr(sum, comp) ~= sqrt(E_comp / E_sum).  Allow 30% degradation.
    return max(0.02, 0.3 * float(np.sqrt(e1 / total)))


def energy(x):
    return float(np.sum(x * x)) if x is not None and len(x) else 0.0


def norm_len(x, n):
    if x is None:
        return np.zeros(n)
    if len(x) >= n:
        return x[:n]
    return np.concatenate([x, np.zeros(n - len(x))])


def zpad(x, sec, sr=48000):
    if x is None:
        return np.zeros(0)
    if sec <= 0:
        return x
    return np.concatenate([np.zeros(int(sec * sr)), x])


def ensure_excerpt():
    os.makedirs(D, exist_ok=True)
    os.makedirs(os.path.join(D, "out"), exist_ok=True)
    os.makedirs(os.path.join(D, "proxies"), exist_ok=True)
    if os.path.exists(EXCERPT) and os.path.getsize(EXCERPT) > 1_000_000:
        return
    run([FF, "-y", "-v", "error", "-ss", "0", "-t", "20", "-i", H264_FULL,
         "-map", "0:v:0", "-map", "0:a:0", "-c", "copy", "-avoid_negative_ts", "make_zero", EXCERPT])


def main():
    global TOKEN, fails, checks
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _harness import require_current, require_ffmpeg

    TOKEN = call("GET", "/api/token")[1]["token"]
    require_current(BASE, TOKEN)
    require_ffmpeg(BASE, FF, TOKEN)
    log("ffmpeg ok")
    ensure_excerpt()
    for role in ("h264", "hevc"):
        st, r = call("POST", "/api/sources/open", {"path": os.path.abspath(SR[role])})
        if st != 200:
            log("open failed: %s %s" % (role, r))
            return 1
        SRC_ID[role] = r["source"]["id"]
        st, r2 = call("POST", "/api/sources/open", {"path": os.path.abspath(AD[role])})
        if st != 200:
            log("open added failed: %s %s" % (role, r2))
            return 1
        AD_ID = r2["source"]["id"]
        SRC_ID[role + "_add"] = AD_ID
        SR_DUR[role] = float(r["source"].get("durationUs") or 0) / 1e6
        AD_DUR[role] = float(r2["source"].get("durationUs") or 0) / 1e6
        st, r3 = call("POST", "/api/sources/open", {"path": os.path.abspath(FL[role])})
        if st != 200:
            log("open full failed: %s %s" % (role, r3))
            return 1
        SRC_ID[role + "_full"] = r3["source"]["id"]
        FULL_DUR[role] = float(r3["source"].get("durationUs") or 0) / 1e6
    log("sources: src_dur=%s add_dur=%s full_dur=%s" % (SR_DUR, AD_DUR, FULL_DUR))

    cases = build_cases()
    if FILTER:
        cases = [c for c in cases if FILTER in c["id"]]
    if SKIP_FULL:
        cases = [c for c in cases if c.get("variant") != "full"]
    log("cases: %d" % len(cases))
    for c in cases:
        log("== " + c["id"])
        try:
            if c["target"] == "export":
                run_export_case(c)
            else:
                run_preview_case(c)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            check(False, c["id"] + " raised " + repr(exc))
    log("checks=%d fail=%d" % (checks, fails))
    log("RESULT: " + ("OK" if fails == 0 else "FAIL(%d)" % fails))
    return 0 if fails == 0 else 1


def opt_common(c, *, added=True, extra=None):
    o = {"audioTiming": True, "audioMode": c["mode"],
         "audioShiftMs": c["b"], "addedShiftMs": c["a"], "addedStartMs": 0}
    if added and c["mode"] in ("added", "bothTracks", "bothMix"):
        o["addedSourceId"] = SRC_ID[c["role"] + "_add"]
        o["addedReencode"] = bool(c.get("addedReencode"))
    if c.get("delayNoReencode"):
        o["delayNoReencode"] = True
    if extra:
        o.update(extra)
    return o


def build_cases():
    roles = ("h264", "hevc")
    modes = ("original", "added", "bothTracks", "bothMix", "mute")
    shifts = ((-500, -500), (500, 500), (-500, 500), (500, -500))
    cases = []

    def add(target, role, mode, b, a, **kw):
        c = {"id": "%s-%s-%s-%+d_%+d" % (target, role, mode, b, a),
             "target": target, "role": role, "mode": mode, "b": b, "a": a}
        if kw:
            if kw.get("variant"):
                c["id"] += "-" + kw["variant"]
            c.update(kw)
        cases.append(c)

    for target in ("export", "preview"):
        for role in roles:
            for mode in modes:
                add(target, role, mode, 0, 0, interval=(S0, E0))
    for target in ("export", "preview"):
        for role in roles:
            for mode in modes:
                for b, a in shifts:
                    add(target, role, mode, b, a, interval=(S0, E0))
    for role in roles:
        for a in (-500, 500):
            add("export", role, "added", 0, a, variant="addedReencode", addedReencode=True,
                interval=(S0, E0))
    for role in roles:
        add("export", role, "original", 500, 0, variant="delayNoReencode",
            delayNoReencode=True, interval=(0, 4_000_000))
    if not SKIP_FULL:
        for role in roles:
            add("export", role, "bothMix", 500, 500, variant="full", full=True, interval=(S0, E0))
            add("preview", role, "bothMix", 500, 500, variant="full", full=True)
    return cases


def src_path(c):
    return os.path.abspath(FL[c["role"]] if c.get("full") else SR[c["role"]])


def check_video(c, out, S, L):
    ss = streams(out)
    vs = [s for s in ss if s.get("codec_type") == "video"]
    src_vs = [s for s in streams(os.path.abspath(SR[c["role"]])) if s.get("codec_type") == "video"] if not c.get("full") \
        else [s for s in streams(os.path.abspath(FL[c["role"]])) if s.get("codec_type") == "video"]
    if not check(bool(vs), c["id"] + " has a video stream"):
        return
    v, sv = vs[0], (src_vs[0] if src_vs else {})
    check(v.get("codec_name") == sv.get("codec_name"),
          c["id"] + " video codec kept: %s vs %s" % (v.get("codec_name"), sv.get("codec_name")))
    check((v.get("width"), v.get("height")) == (sv.get("width"), sv.get("height")),
          c["id"] + " video dimensions kept: %sx%s" % (v.get("width"), v.get("height")))
    src_path = os.path.abspath(FL[c["role"]] if c.get("full") else SR[c["role"]])
    exp_n = video_interval_count(src_path, S, L)
    got_n = packet_count(out, "v:0")
    check(0 <= got_n - exp_n <= 8,
          c["id"] + " video packets: %d vs %d (+0..8, keyframe snap)" % (got_n, exp_n))


def check_av(c, out, S, L):
    vd = stream_duration(out, "video")
    ad = stream_duration(out, "audio")
    if ad:
        # The audio stream must carry the whole interval; a trim/loss shows up here even
        # when the video is one GOP longer (the earlier broad 0.25s A/V diff hid that).
        check(abs(ad - L) <= 0.12,
              c["id"] + " audio stream duration ~interval: %.3f vs %.3f" % (ad, L))
    if vd:
        check(L - 0.05 <= vd <= L + 0.35,
              c["id"] + " video stream duration (GOP priming allowed): %.3f vs %.3f" % (vd, L))
    md = media_duration(out)
    if md:
        # Container growth comes from a stream that starts at +0.5s (timestamp delay):
        # an added-track timestamp or the delayNoReencode route.
        extra = 0.0
        if c["mode"] in ("added", "bothTracks") and c["a"] > 0:
            extra = 0.5
        if c.get("delayNoReencode"):
            extra = 0.5
        check(L - 0.25 <= md <= L + extra + 0.25,
              c["id"] + " container duration ~cut: %.3f vs %.3f (+%.1f)" % (md, L, extra))


def check_warnings(c, res):
    mode = c["mode"]
    w = [str(x) for x in ((res.get("warnings") or []))]
    blob = " | ".join(w)
    if mode == "mute":
        if c["b"] or c["a"]:
            check("消音ではずらしを無視" in blob, c["id"] + " mute warns about ignored shifts: " + blob[:160])
    elif mode == "added":
        if c["b"]:
            check("追加のみモードでは元音声のずらし" in blob, c["id"] + " added warns about ignored orig shift")
    elif mode == "bothMix":
        check("音声をミックスするため音声のみ再エンコード" in blob, c["id"] + " mix warns re-encode")
    if c.get("addedReencode"):
        check("追加音声のみ再エンコード" in blob, c["id"] + " added re-encode is warned")
    if mode == "original" and not c.get("delayNoReencode"):
        check(not any("再エンコード" in x for x in w),
              c["id"] + " original is lossless (no re-encode warning): " + blob[:160])
        check(not any("追加のみモード" in x or "追加音声を利用できない" in x for x in w),
              c["id"] + " original ignores the added shift without a warning")


def check_metadata(c, res):
    au = res.get("audio") or {}
    mode, b, a = c["mode"], c["b"], c["a"]
    if mode == "mute":
        check(au.get("delayMode") == "none", c["id"] + " mute delayMode none")
        check(all(abs(float(x)) < 1e-6 for x in (au.get("appliedMs") or {}).values()),
              c["id"] + " mute appliedMs zero")
        return
    if c.get("delayNoReencode"):
        check(au.get("delayMode") == "timestamp", c["id"] + " delayMode timestamp")
        check(res.get("lossless") is True, c["id"] + " lossless true")
        return
    if mode in ("original", "bothMix"):
        if b > 0:
            check(au.get("delayMode") in ("content", "timestamp"),
                  c["id"] + " positive orig delayMode: " + str(au.get("delayMode")))
        elif b < 0:
            check(au.get("delayMode") == "none", c["id"] + " negative orig delayMode none")
    if mode == "original" and b > 0:
        check(((au.get("contentMs") or {}).get("reachBack") or 0) == 500,
              c["id"] + " reachBack reported")
    if mode in ("added", "bothTracks"):
        check(au.get("appliedMs", {}).get("added") == (500 if a > 0 else 0),
              c["id"] + " appliedMs added: " + str(au.get("appliedMs")))
        if a > 0:
            # delayMode reflects the original track only; an added timestamp is reported
            # via appliedMs.added and the track PTS (documented limitation).
            want = "content" if (mode == "bothTracks" and b > 0) else "none"
            check(au.get("delayMode") == want,
                  c["id"] + " added delayMode is the original-track value: " + str(au.get("delayMode")))
    if mode == "bothMix":
        check(au.get("delayMode") == ("timestamp" if b > 0 else "none"),
              c["id"] + " mix delayMode from the original track: " + str(au.get("delayMode")))
        check(au.get("appliedMs", {}).get("added") == (500 if a > 0 else 0),
              c["id"] + " mix appliedMs added")
        check((au.get("appliedMs", {}).get("audio") or 0) == max(0, b),
              c["id"] + " mix appliedMs audio")


def base_component(c, S, L, b):
    """Expected base waveform for an EXPORT mix route (filter semantics)."""
    src = src_path(c)
    if b > 0:
        return zpad(decode(src, "0:a:0", S, L - b), b)
    if b < 0:
        return decode(src, "0:a:0", S - b, L)
    return decode(src, "0:a:0", S, L)


def added_component_export(c, L, a):
    src = os.path.abspath(AD[c["role"]])
    if a > 0:
        return zpad(decode(src, "0:a:0", 0.0, L - a), a)
    if a < 0:
        return decode(src, "0:a:0", 0.5, L)
    return decode(src, "0:a:0", 0.0, L)


def check_mix_corr(c, out, comps, window_s, S, L):
    actual = decode(out, "0:a:0")
    if actual is None:
        check(False, c["id"] + " audio decodes")
        return
    expected = np.zeros(int(window_s * 48000))
    for comp in comps:
        if comp is not None:
            expected = expected + norm_len(comp, len(expected))
    height, lag = corr_peak(actual, expected, window_s=window_s)
    check(height >= CORR_MIN and abs(lag) <= 0.09,
          c["id"] + " mix waveform matches expected (corr=%.3f lag=%.3fs)" % (height, lag))
    e = [energy(norm_len(x, len(expected))) for x in comps]
    total = sum(e)
    for i, comp in enumerate(comps):
        if comp is None or total <= 0:
            continue
        h, lg = corr_peak(actual, norm_len(comp, len(expected)), window_s=window_s)
        need = comp_threshold(e[i], total - e[i])
        check(h >= need and abs(lg) <= 0.09,
              c["id"] + " component %d present (corr=%.3f >= %.2f lag=%.3f)" % (i, h, need, lg))
    # discriminative: zero-shift and sign-flipped expectations
    wrong = []
    if c["b"] or c["a"]:
        wrong.append(mix_expected_for(c, window_s, 0, 0, S, L))
        wrong.append(mix_expected_for(c, window_s, -c["b"], -c["a"], S, L))
    for w in wrong:
        h, _ = corr_peak(actual, w, window_s=window_s)
        check(height >= h + 0.15,
              c["id"] + " alignment beats wrong shift (%.3f vs %.3f)" % (height, h))


def mix_expected_for(c, window_s, b, a, S, L):
    """Build the expected mixed waveform for an EXPORT case with the given shifts."""
    n = int(window_s * 48000)
    out = np.zeros(n)
    out = out + norm_len(base_component(c, S, L, b / 1000.0), n)
    out = out + norm_len(added_component_export(c, L, a / 1000.0), n)
    return out


def preview_base(c, P, b):
    src = src_path(c)
    if b > 0:
        return zpad(decode(src, "0:a:0", 0.0, P - b), b)
    if b < 0:
        off = abs(b)
        x = decode(src, "0:a:0", off, P)
        return norm_len(x, int(P * 48000))
    return decode(src, "0:a:0", 0.0, P)


def preview_added(c, P, a):
    src = os.path.abspath(AD[c["role"]])
    if a > 0:
        return zpad(decode(src, "0:a:0", 0.0, P - a), a)
    if a < 0:
        off = abs(a)
        x = decode(src, "0:a:0", off, P)
        return norm_len(x, int(P * 48000))
    return norm_len(decode(src, "0:a:0", 0.0, P), int(P * 48000))


CORR_MIN = 0.80


def run_export_case(c):
    role = c["role"]
    start_us, end_us = c["interval"]
    out = os.path.abspath(os.path.join(D, "out", c["id"] + ".mp4"))
    if os.path.exists(out):
        os.unlink(out)
    opts = opt_common(c, extra={"outputPath": out})
    source_id = SRC_ID[role + ("_full" if c.get("full") else "")]
    st, r = call("POST", "/api/exports", {"sourceId": source_id,
                                          "startUs": start_us, "endUs": end_us,
                                          "mode": "lossless", "options": opts})
    if not check(st == 200, c["id"] + " export accepted: " + str(st) + " " + str(r)[:200]):
        return
    j = wait_job(r["jobId"])
    if not check(j.get("status") == "done", c["id"] + " job done: " + str(j.get("error"))[:300]):
        return
    res = j.get("result") or {}
    out = res.get("outputPath") or out
    if not check(os.path.exists(out), c["id"] + " output exists"):
        return
    S = float(res.get("actualStartUs") or 0) / 1e6
    E = float(res.get("actualEndUs") or 0) / 1e6
    L = E - S
    log("   range S=%.3f E=%.3f L=%.3f" % (S, E, L))
    ss = streams(out)
    audio = [s for s in ss if s.get("codec_type") == "audio"]
    mode, b, a = c["mode"], c["b"], c["a"]
    want = {"original": 1, "added": 1, "bothTracks": 2, "bothMix": 1, "mute": 0}[mode]
    check(len(audio) == want, c["id"] + " audio streams %d == %d" % (len(audio), want))
    check_warnings(c, res)
    check_video(c, out, S, L)
    check_av(c, out, S, L)
    check_metadata(c, res)

    if c.get("delayNoReencode"):
        got = packet_md5(out, "0:a")
        exp = packet_md5(os.path.abspath(SR[role]), "0:a", S, L)
        check(got == exp, c["id"] + " audio packets == source [%.3f,%.3f) (no re-encode)" % (S, S + L))
        stt = start_time(out, "0:a:0")
        check(stt is not None and 0.44 <= stt <= 0.56, c["id"] + " audio PTS ~0.5: " + str(stt))
        return

    if c.get("addedReencode"):
        src = os.path.abspath(AD[role])
        exp = decode(src, "0:a:0", 0.5 if a < 0 else 0.0, L)
        actual = decode(out, "0:a:0", 0.0, L)
        h, lag = corr_peak(actual, exp, window_s=L)
        check(h >= CORR_MIN and abs(lag) <= 0.09,
              c["id"] + " re-encoded added placement (corr=%.3f lag=%.3f)" % (h, lag))
        check(packet_md5(out, "0:a") != packet_md5(src, "0:a", 0.5 if a < 0 else 0.0, L),
              c["id"] + " added audio really re-encoded")
        if a > 0:
            stt = start_time(out, "0:a:0")
            check(stt is not None and 0.44 <= stt <= 0.56, c["id"] + " added PTS ~0.5: " + str(stt))
        au = res.get("audio") or {}
        check((au.get("appliedMs") or {}).get("added") == (500 if a > 0 else 0),
              c["id"] + " re-encoded added appliedMs")
        # the added track is not part of delayMode (original-track value only)
        check(au.get("delayMode") == "none",
              c["id"] + " re-encoded added delayMode (original-track value): " + str(au.get("delayMode")))
        return

    if mode == "mute":
        return

    if mode in ("original", "bothTracks"):
        got = packet_md5(out, "0:a:0")
        start = S - b / 1000.0
        exp = packet_md5(os.path.abspath(SR[role]), "0:a", start, L)
        check(got == exp, c["id"] + " base packets == source [%.3f..%.3f)" % (start, start + L))
        if b != 0:
            unshifted = packet_md5(os.path.abspath(SR[role]), "0:a", S, L)
            check(got != unshifted, c["id"] + " base content really shifted")
        stt = start_time(out, "0:a:0")
        if b > 0:
            check(stt is not None and abs(stt) < 0.25, c["id"] + " base start ~0 (content reach-back): " + str(stt))
        else:
            check(stt is not None and abs(stt) < 0.25, c["id"] + " base start ~0: " + str(stt))
    if mode in ("added", "bothTracks"):
        spec = "0:a:0" if mode == "added" else "0:a:1"
        got = packet_md5(out, spec)
        start = 0.5 if a < 0 else 0.0
        exp = packet_md5(os.path.abspath(AD[role]), "0:a", start, L)
        check(got == exp, c["id"] + " added packets == source [%.3f..%.3f)" % (start, start + L))
        if a < 0:
            unshifted = packet_md5(os.path.abspath(AD[role]), "0:a", 0.0, L)
            check(got != unshifted, c["id"] + " added content really shifted")
        stt = start_time(out, spec)
        if a > 0:
            check(stt is not None and 0.44 <= stt <= 0.56, c["id"] + " added PTS ~0.5: " + str(stt))
        else:
            check(stt is not None and abs(stt) < 0.25, c["id"] + " added start ~0: " + str(stt))
    if mode == "original" and b != 0:
        actual = decode(out, "0:a:0", 0.0, L)
        exp = decode(src_path(c), "0:a:0", S - b / 1000.0, L)
        h, lag = corr_peak(actual, exp, window_s=L)
        check(h >= 0.90 and abs(lag) <= 0.09,
              c["id"] + " decoded base waveform cross-check (corr=%.3f lag=%.3f)" % (h, lag))
    if mode == "bothMix":
        check_mix_corr(c, out, [base_component(c, S, L, b / 1000.0),
                                added_component_export(c, L, a / 1000.0)], L, S, L)


def download(url, dest):
    req = urllib.request.Request(BASE + url, headers={"X-Trim-Token": TOKEN})
    with urllib.request.urlopen(req, timeout=900) as r, open(dest, "wb") as fh:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)


def run_preview_case(c):
    role = c["role"]
    source_id = SRC_ID[role + ("_full" if c.get("full") else "")]
    body = {"sourceId": source_id, "audioMode": c["mode"],
            "audioShiftMs": c["b"], "addedShiftMs": c["a"], "addedStartMs": 0}
    if c["mode"] in ("added", "bothTracks", "bothMix"):
        body["addedSourceId"] = SRC_ID[role + "_add"]
    st, r = call("POST", "/api/preview/build", body)
    if st == 409 and (r or {}).get("proxyJobId"):
        pj = wait_job(r["proxyJobId"], timeout=900)
        check(pj.get("status") == "done", c["id"] + " proxy built")
        st, r = call("POST", "/api/preview/build", body)
    if not check(st == 200, c["id"] + " preview accepted: " + str(st) + " " + str(r)[:200]):
        return
    meta = None
    if r.get("jobId"):
        j = wait_job(r["jobId"], timeout=600)
        if j.get("status") == "timeout":
            # Retry once (plan rule for long full-source previews) and record the retry.
            log("RETRY " + c["id"] + " preview job timed out; retrying once")
            st2, r2 = call("POST", "/api/preview/build", body)
            if st2 == 200 and r2.get("jobId"):
                j = wait_job(r2["jobId"], timeout=600)
                if j.get("status") == "done":
                    log("RETRY-OK " + c["id"])
        if not check(j.get("status") == "done", c["id"] + " preview job done: " + str(j.get("error"))[:300]):
            return
        meta = j.get("result") or {}
    else:
        meta = r
    url = meta.get("url")
    P = float(meta.get("durationUs") or 0) / 1e6
    if not check(bool(url) and P > 0, c["id"] + " preview metadata (url/duration)"):
        return
    dest = os.path.abspath(os.path.join(D, "proxies", c["id"] + ".mp4"))
    download(url, dest)
    if not check(os.path.getsize(dest) > 1000, c["id"] + " proxy downloaded"):
        return
    ss = streams(dest)
    audio = [s for s in ss if s.get("codec_type") == "audio"]
    want = 0 if c["mode"] == "mute" else 1
    check(len(audio) == want, c["id"] + " preview audio streams %d == %d" % (len(audio), want))
    vids = [s for s in ss if s.get("codec_type") == "video"]
    check(bool(vids) and vids[0].get("codec_name") == "h264", c["id"] + " preview video is h264")
    if vids and role == "hevc":
        v = vids[0]
        check(max(int(v.get("width") or 0), int(v.get("height") or 0)) <= 1280,
              c["id"] + " hevc preview uses the scaled proxy: %sx%s" % (v.get("width"), v.get("height")))
    if c["mode"] == "mute":
        return
    W = min(P, 45.0)
    b, a = c["b"] / 1000.0, c["a"] / 1000.0
    if c["mode"] == "original":
        exp = preview_base(c, W, b)
        actual = decode(dest, "0:a:0", 0.0, W)
        h, lag = corr_peak(actual, exp, window_s=W)
        check(h >= CORR_MIN and abs(lag) <= 0.09,
              c["id"] + " preview base shifted (corr=%.3f lag=%.3f)" % (h, lag))
    elif c["mode"] == "added":
        exp = preview_added(c, W, a)
        actual = decode(dest, "0:a:0", 0.0, W)
        h, lag = corr_peak(actual, exp, window_s=W)
        check(h >= CORR_MIN and abs(lag) <= 0.09,
              c["id"] + " preview added shifted (corr=%.3f lag=%.3f)" % (h, lag))
    else:
        comps = [preview_base(c, W, b), preview_added(c, W, a)]
        actual = decode(dest, "0:a:0", 0.0, W)
        expected = np.zeros(int(W * 48000))
        for comp in comps:
            expected = expected + norm_len(comp, len(expected))
        h, lag = corr_peak(actual, expected, window_s=W)
        check(h >= CORR_MIN and abs(lag) <= 0.09,
              c["id"] + " preview mix matches (corr=%.3f lag=%.3f)" % (h, lag))
        e = [energy(norm_len(x, len(expected))) for x in comps]
        total = sum(e)
        for i, comp in enumerate(comps):
            hh, lg = corr_peak(actual, norm_len(comp, len(expected)), window_s=W)
            need = comp_threshold(e[i], total - e[i])
            check(hh >= need and abs(lg) <= 0.09,
                  c["id"] + " preview component %d (corr=%.3f >= %.2f)" % (i, hh, need))
        variants = [] if not (c["b"] or c["a"]) else [(0.0, 0.0, "zero")]
        if c["b"] or c["a"]:
            variants.append((-b, -a, "sign-flip"))
        for wb, wa, tag in variants:
            wrong = np.zeros(int(W * 48000))
            wrong = wrong + norm_len(preview_base(c, W, wb), len(wrong))
            wrong = wrong + norm_len(preview_added(c, W, wa), len(wrong))
            hw, _ = corr_peak(actual, wrong, window_s=W)
            check(h >= hw + 0.15,
                  c["id"] + " beats %s expectation (%.3f vs %.3f)" % (tag, h, hw))


if __name__ == "__main__":
    sys.exit(main())
