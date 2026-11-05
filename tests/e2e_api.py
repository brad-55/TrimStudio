import json
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8003"
FF = r"L:\dev\Trim\tools\ffmpeg\bin\ffmpeg.exe"
FP = r"L:\dev\Trim\tools\ffmpeg\bin\ffprobe.exe"


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
        with urllib.request.urlopen(req, timeout=300) as resp:
            raw = resp.read()
            try:
                return resp.status, json.loads(raw.decode("utf-8"))
            except ValueError:
                return resp.status, raw
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def wait_health():
    for _ in range(120):
        try:
            code, body = call("GET", "/api/health")
            if code == 200:
                return body
        except Exception:
            pass
        time.sleep(1)
    raise SystemExit("server did not become healthy")


def frame_hashes(args):
    proc = subprocess.run([FF, "-hide_banner", "-v", "error"] + args + ["-f", "framemd5", "-"],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    hashes = []
    for line in proc.stdout.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 6:
            hashes.append(parts[-1])
    return hashes


def main():
    print("health", wait_health())
    code, tok = call("GET", "/api/token")
    token = tok["token"]
    print("config", call("GET", "/api/config")[1])
    code, res = call("POST", "/api/sources/open", {"path": "L:/dev/Trim/data/test/src_h264.mp4"}, token)
    print("open", code, json.dumps(res, ensure_ascii=False)[:400])
    if code != 200:
        return 1
    sid = res["source"]["id"]
    kf = {}
    for _ in range(180):
        code, kf = call("GET", "/api/sources/%s/keyframes" % sid)
        if kf.get("state") == "ready":
            break
        time.sleep(0.5)
    print("keyframes", kf.get("state"), kf.get("keyframes"))

    code, job = call("POST", "/api/exports", {"sourceId": sid, "startUs": 2500000, "endUs": 7500000,
                                              "mode": "lossless", "options": {"inSnap": "prev", "outMode": "exact"}}, token)
    print("export", code, job)

    # Range request check
    req = urllib.request.Request(BASE + "/api/sources/%s/media?variant=original" % sid, headers={"Range": "bytes=0-1023"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        print("range", resp.status, resp.headers.get("Content-Range"), len(resp.read()))

    # frame check
    code, res2 = call("GET", "/api/sources/%s/frame?tUs=3000000" % sid)
    print("frame status", code)

    jid = job["jobId"]
    j = {}
    for _ in range(600):
        code, jr = call("GET", "/api/jobs/%s" % jid)
        j = jr["job"]
        if j["status"] in ("done", "error", "cancelled"):
            break
        time.sleep(0.5)
    print("job", j["status"], json.dumps(j.get("result"), ensure_ascii=False))
    if j["status"] != "done":
        print("job error:", j.get("error"))
        return 1

    result = j["result"]
    out = result["outputPath"]
    start_us = result["actualStartUs"]
    end_us = result["actualEndUs"]
    dur = (end_us - start_us) / 1e6
    out_hashes = frame_hashes(["-i", out])
    src_hashes = frame_hashes(["-ss", "%.6f" % (start_us / 1e6), "-i", r"L:\dev\Trim\data\test\src_h264.mp4", "-t", "%.6f" % (dur + 2.0)])
    matched = 0
    best = 0
    for offset in range(0, max(1, len(src_hashes) - len(out_hashes) + 1)):
        m = sum(1 for i, h in enumerate(out_hashes) if i + offset < len(src_hashes) and src_hashes[i + offset] == h)
        if m > best:
            best = m
    ratio = best / max(1, len(out_hashes))
    print("framemd5 out=%d src=%d best_match=%d ratio=%.4f" % (len(out_hashes), len(src_hashes), best, ratio))
    return 0 if ratio > 0.95 else 2


if __name__ == "__main__":
    sys.exit(main())
