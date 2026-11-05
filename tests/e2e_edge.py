import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8003"
FF = r"L:\dev\Trim\tools\ffmpeg\bin\ffmpeg.exe"
FP = r"L:\dev\Trim\tools\ffmpeg\bin\ffprobe.exe"
SRC = r"L:\dev\Trim\data\test\src_h264.mp4"


def call(method, path, body=None, token=None, headers=None):
    data = None
    h = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    if token:
        h["X-Trim-Token"] = token
    req = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=900) as resp:
            raw = resp.read()
            try:
                return resp.status, json.loads(raw.decode("utf-8")), dict(resp.headers)
            except ValueError:
                return resp.status, raw, dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace"), {}


def wait_job(jid):
    for _ in range(1800):
        code, jr, _ = call("GET", "/api/jobs/%s" % jid)
        j = jr["job"]
        if j["status"] in ("done", "error", "cancelled"):
            return j
        time.sleep(0.5)
    return j


def hashes(args):
    proc = subprocess.run([FF, "-hide_banner", "-v", "error"] + args + ["-map", "0:v:0", "-f", "framemd5", "-"],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = []
    for line in proc.stdout.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 6:
            out.append(parts[-1])
    return out


def first_frame(path, ss=None):
    cmd = [FF, "-hide_banner", "-v", "error"]
    if ss is not None:
        cmd += ["-ss", str(ss)]
    cmd += ["-i", path, "-frames:v", "1"]
    h = hashes(cmd)
    return h[0] if h else None


def starts(path):
    result = {}
    for kind in ("v:0", "a:0"):
        proc = subprocess.run([FP, "-v", "error", "-select_streams", kind, "-show_entries",
                               "stream=start_time,duration", "-of", "csv=p=0", path],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        line = proc.stdout.strip().splitlines()
        if line:
            parts = line[0].split(",")
            result[kind] = parts
    return result


def run_case(token, sid, start_us, end_us, label):
    code, job, _ = call("POST", "/api/exports", {"sourceId": sid, "startUs": start_us, "endUs": end_us,
                                                 "mode": "lossless", "options": {"inSnap": "prev", "outMode": "exact"}}, token)
    if code != 200:
        print(label, "create failed", code, job)
        return False
    j = wait_job(job["jobId"])
    if j["status"] != "done":
        print(label, "job", j["status"], str(j.get("error"))[:160])
        return False
    r = j["result"]
    out = r["outputPath"]
    info = starts(out)
    dur = (r.get("actualEndUs", end_us) - r.get("actualStartUs", start_us)) / 1e6
    oh = hashes(["-i", out])
    proc = subprocess.run([FP, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", out],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        cdur = float(proc.stdout.strip())
    except ValueError:
        cdur = None
    vstart = float(info["v:0"][0]) if "v:0" in info and info["v:0"][0] not in ("", "N/A") else None
    astart = float(info["a:0"][0]) if "a:0" in info and info["a:0"][0] not in ("", "N/A") else None
    if start_us == 0:
        expected_first = first_frame(SRC, 0)
        actual_first = first_frame(out)
        first_ok = expected_first == actual_first
    else:
        first_ok = True
    sync_ok = vstart is not None and astart is not None and abs(vstart - astart) < 0.05
    dur_ok = cdur is not None and abs(cdur - dur) <= 0.3
    print("%-12s frames=%-4d cdur=%-8s vstart=%-8s astart=%-8s first_ok=%s sync_ok=%s dur_ok=%s"
          % (label, len(oh), cdur, vstart, astart, first_ok, sync_ok, dur_ok))
    return first_ok and sync_ok and dur_ok


def main():
    code, tok, _ = call("GET", "/api/token")
    token = tok["token"]
    code, res, _ = call("POST", "/api/sources/open", {"path": SRC}, token)
    sid = res["source"]["id"]
    for _ in range(240):
        code, kf, _ = call("GET", "/api/sources/%s/keyframes" % sid)
        if kf.get("state") == "ready":
            break
        time.sleep(0.5)
    duration = res["source"]["durationUs"]
    ok = True
    ok &= run_case(token, sid, 0, duration, "full")
    ok &= run_case(token, sid, 0, 700000, "IN0-short")
    ok &= run_case(token, sid, 500000, 3000000, "IN0.5")
    ok &= run_case(token, sid, 4000000, 9000000, "mid")

    # security: bad host and missing token
    req = urllib.request.Request(BASE + "/api/health", headers={"Host": "evil.example.com"})
    try:
        urllib.request.urlopen(req, timeout=10)
        host_blocked = False
    except urllib.error.HTTPError as exc:
        host_blocked = exc.code == 403
    code, body, _ = call("POST", "/api/sources/open", {"path": SRC})
    token_required = code == 403
    print("security: host_blocked=%s token_required=%s" % (host_blocked, token_required))

    # suffix range
    req = urllib.request.Request(BASE + "/api/sources/%s/media?variant=original" % sid, headers={"Range": "bytes=-1000"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read()
        print("suffix range:", resp.status, resp.headers.get("Content-Range"), len(data))
        suffix_ok = resp.status == 206 and len(data) == 1000
    print("RESULT:", "OK" if (ok and host_blocked and token_required and suffix_ok) else "FAIL")
    return 0 if (ok and host_blocked and token_required and suffix_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
