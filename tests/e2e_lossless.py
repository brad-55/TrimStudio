import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8003"
FF = r"L:\dev\Trim\tools\ffmpeg\bin\ffmpeg.exe"


def call(method, path, body=None, token=None):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["X-Trim-Token"] = token
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=900) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def wait_job(jid):
    for _ in range(1200):
        code, jr = call("GET", "/api/jobs/%s" % jid)
        job = jr["job"]
        if job["status"] in ("done", "error", "cancelled"):
            return job
        time.sleep(0.5)
    return job


def video_hashes(args):
    proc = subprocess.run([FF, "-hide_banner", "-v", "error"] + args + ["-map", "0:v:0", "-f", "framemd5", "-"],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    values = []
    for line in proc.stdout.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 6:
            values.append(parts[-1])
    return values


def video_start(path):
    proc = subprocess.run([FF if False else r"L:\dev\Trim\tools\ffmpeg\bin\ffprobe.exe", "-v", "error",
                           "-select_streams", "v:0", "-show_entries", "stream=start_time",
                           "-of", "default=nw=1:nk=1", path],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return -1.0


def stream_start_duration(path, kind):
    proc = subprocess.run([r"L:\dev\Trim\tools\ffmpeg\bin\ffprobe.exe", "-v", "error",
                           "-select_streams", kind, "-show_entries", "stream=start_time,duration",
                           "-of", "csv=p=0", path],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    lines = [l.strip() for l in proc.stdout.splitlines() if l.strip()]
    if not lines:
        return None, None
    parts = lines[0].split(",")
    def num(v):
        try:
            return float(v)
        except ValueError:
            return None
    start = num(parts[0]) if parts else None
    dur = num(parts[1]) if len(parts) > 1 else None
    return start, dur


def container_duration(path):
    proc = subprocess.run([r"L:\dev\Trim\tools\ffmpeg\bin\ffprobe.exe", "-v", "error",
                           "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", path],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return None


def decode_errors(path):
    proc = subprocess.run([FF, "-v", "error", "-i", path, "-f", "null", "-"],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    text = (proc.stderr or "").strip()
    return text


def align(out_hashes, src_hashes):
    if not out_hashes or not src_hashes:
        return 0, 0, list(range(len(out_hashes)))
    best = (0, -1)
    for offset in range(-len(out_hashes) + 1, len(src_hashes)):
        m = sum(1 for i, h in enumerate(out_hashes) if 0 <= i + offset < len(src_hashes) and src_hashes[i + offset] == h)
        if m > best[1]:
            best = (offset, m)
    offset = best[0]
    mismatches = [i for i, h in enumerate(out_hashes) if not (0 <= i + offset < len(src_hashes)) or src_hashes[i + offset] != h]
    return offset, best[1], mismatches


def ratio(out_hashes, src_hashes):
    if not out_hashes or not src_hashes:
        return 0.0
    best = 0
    for offset in range(-len(out_hashes) + 1, len(src_hashes)):
        m = 0
        for i, h in enumerate(out_hashes):
            j = i + offset
            if 0 <= j < len(src_hashes) and src_hashes[j] == h:
                m += 1
        if m > best:
            best = m
    return best / len(out_hashes)


def lossless_check(token, path, start_us, end_us):
    code, res = call("POST", "/api/sources/open", {"path": path}, token)
    if code != 200:
        print("  open failed", code, res)
        return False
    sid = res["source"]["id"]
    for _ in range(240):
        code, kf = call("GET", "/api/sources/%s/keyframes" % sid)
        if kf.get("state") == "ready":
            break
        time.sleep(0.5)
    code, job = call("POST", "/api/exports", {"sourceId": sid, "startUs": start_us, "endUs": end_us,
                                              "mode": "lossless", "options": {"inSnap": "prev", "outMode": "exact"}}, token)
    j = wait_job(job["jobId"])
    if j["status"] != "done":
        print("  export failed", j.get("error"))
        return False
    r = j["result"]
    out = r["outputPath"]
    a, b = r["actualStartUs"], r["actualEndUs"]
    oh = video_hashes(["-i", out])
    sh = video_hashes(["-ss", "%.6f" % (a / 1e6), "-i", path, "-t", "%.6f" % ((b - a) / 1e6 + 2.0)])
    best_offset, best_match, mismatches = align(oh, sh)
    total = len(oh)
    interior_bad = [i for i in mismatches if 8 <= i < total - 8]
    errs = decode_errors(out)
    vstart = video_start(out)
    astart, adur = stream_start_duration(out, "a:0")
    cdur = container_duration(out)
    target = (b - a) / 1e6
    dur_ok = (cdur is None or abs(cdur - target) <= 0.3) and (adur is None or abs(adur - target) <= 0.3)
    sync_ok = (astart is None or astart < 0.25) and (vstart < 0.2)
    print("  " + os.path.basename(path) + " start=%.3f end=%.3f frames=%d offset=%d match=%d/%d interior_bad=%d vstart=%.3f astart=%s adur=%s cdur=%s dur_ok=%s sync_ok=%s errors=%s"
          % (a / 1e6, b / 1e6, total, best_offset, best_match, total, len(interior_bad), vstart,
             astart, adur, cdur, dur_ok, sync_ok, "none" if not errs else errs[:80]))
    return len(interior_bad) == 0 and not errs and sync_ok and dur_ok


def main():
    code, tok = call("GET", "/api/token")
    token = tok["token"]
    ok = True
    print("lossless H.264 MP4:")
    ok &= lossless_check(token, r"L:\dev\Trim\data\test\src_h264.mp4", 2500000, 7500000)
    print("lossless H.265 MKV:")
    ok &= lossless_check(token, r"L:\dev\Trim\data\test\src_h265.mkv", 2500000, 7500000)

    # inSnap=next fallback near the end must not fail
    code, res = call("POST", "/api/sources/open", {"path": r"L:\dev\Trim\data\test\src_h264.mp4"}, token)
    sid = res["source"]["id"]
    code, job = call("POST", "/api/exports", {"sourceId": sid, "startUs": 11000000, "endUs": 11500000,
                                              "mode": "lossless", "options": {"inSnap": "next", "outMode": "exact"}}, token)
    j = wait_job(job["jobId"])
    print("inSnap=next fallback:", code, j["status"], (j.get("result") or {}).get("fallback"), (j.get("result") or {}).get("warnings"))

    # validate without sourceId must not 500
    code, val = call("POST", "/api/paths/validate", {"path": r"L:\dev\Trim\data\test"}, token)
    print("paths/validate:", code, json.dumps(val, ensure_ascii=False)[:200])

    print("RESULT:", "OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
