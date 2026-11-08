"""E2E for the audio timing export wiring (docs/PLAN_AUDIO_EXPORT.md section 6.2)."""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8003"
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


def export(src_id, a, b, options):
    # the source may still be indexing: the range only lands on the keyframes once the
    # index exists, so retry until the requested start is honoured
    j = {}
    for _ in range(30):
        st, r = call("POST", "/api/exports", {"sourceId": src_id, "startUs": a, "endUs": b,
                                              "mode": "lossless", "options": options})
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


def seg_md5(path, spec, start, dur):
    p = run([FF, "-v", "error", "-ss", str(start), "-t", str(dur), "-i", path, "-map", spec, "-f", "md5", "-"])
    return (p.stdout or "").strip()


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
    if out1:
        ast = [s for s in streams_of(out1) if s.get("codec_type") == "audio"]
        vst = [s for s in streams_of(out1) if s.get("codec_type") == "video"]
        check(packet_md5(out1, "0:a") == packet_md5(vpath, "0:a", 2.0, 4.0),
              "+2000ms keeps the audio packets bit exact")
        check(abs(float(ast[0].get("duration")) - L) < 0.15, "+2000ms keeps the interval length: " + str(ast[0].get("duration")))
        check(abs(float(ast[0].get("start_time") or 0) - 2.0) < 0.25,
              "+2000ms delays the audio: start=" + str(ast[0].get("start_time")))
        check(elst_media_times(out1), "+2000ms writes an edit list (mp4)")
        print("   starts:", {s["codec_type"]: s.get("start_time") for s in ast + vst})
    st, j = export(vid["id"], 2_000_000, 6_000_000, {"audioShiftMs": -2000})
    out2 = (j.get("result") or {}).get("outputPath") if j.get("status") == "done" else None
    check(j.get("status") == "done" and out2, "export -2000ms succeeds: " + str(j.get("error"))[:400])
    if out2:
        ast = [s for s in streams_of(out2) if s.get("codec_type") == "audio"]
        vst = [s for s in streams_of(out2) if s.get("codec_type") == "video"]
        check(packet_md5(out2, "0:a") == packet_md5(vpath, "0:a", 2.0, 4.0),
              "-2000ms keeps the audio packets bit exact")
        check(abs(float(vst[0].get("start_time") or 0) - 2.0) < 0.25,
              "-2000ms moves the video instead: start=" + str(vst[0].get("start_time")))
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
            check(packet_md5(out5, "0:a:0") == packet_md5(vpath, "0:a", 2.0, 4.0),
                  "track 0 is the untouched original audio")
            check(packet_md5(out5, "0:a:1") == packet_md5(apath, "0:a", 0.5, 4.0),
                  "track 1 is the added audio advanced by 500ms (head skip)")
            print("   starts:", {i: s.get("start_time") for i, s in enumerate(ast)})

    # --- 7: bothMix (plan 0.4 / E2E 15) ---
    st, j = export(vid["id"], 2_000_000, 6_000_000,
                   {"audioMode": "bothMix", "addedSourceId": aud["id"], "addedShiftMs": 800, "audioTiming": True})
    out6 = (j.get("result") or {}).get("outputPath") if j.get("status") == "done" else None
    check(j.get("status") == "done" and out6, "bothMix succeeds: " + str(j.get("error"))[:120])
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
        check(packet_md5(out8, "0:a") == packet_md5(vpath, "0:a", 2.0, 4.0),
              "audioTiming=false keeps the original audio bit exact")
        check(abs(float(ast[0].get("start_time") or 0)) < 0.25,
              "audioTiming=false does not shift: start=" + str(ast[0].get("start_time")))

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

    print("RESULT:", "OK" if fails == 0 else "FAIL(%d)" % fails)
    return 0 if fails == 0 else 1


TOKEN = ""
if __name__ == "__main__":
    with urllib.request.urlopen(BASE + "/api/token", timeout=10) as r:
        TOKEN = json.loads(r.read())["token"]
    sys.exit(main())
