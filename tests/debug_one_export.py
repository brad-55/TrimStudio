import json, os, subprocess, time, urllib.request, urllib.error
BASE = "http://127.0.0.1:8003"
def call(method, path, body=None, token=None):
    data = None; headers = {}
    if body is not None:
        data = json.dumps(body).encode(); headers["Content-Type"] = "application/json"
    if token: headers["X-Trim-Token"] = token
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=600) as r: return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e: return e.code, e.read().decode()
code, tok = call("GET", "/api/token"); token = tok["token"]
code, res = call("POST", "/api/sources/open", {"path": r"L:\dev\Trim\data\test\src_h264.mp4"}, token)
sid = res["source"]["id"]
for _ in range(120):
    code, kf = call("GET", "/api/sources/%s/keyframes" % sid)
    if kf.get("state") == "ready": break
    time.sleep(0.5)
code, job = call("POST", "/api/exports", {"sourceId": sid, "startUs": 2000000, "endUs": 7500000, "mode": "lossless",
                                          "options": {"inSnap": "prev", "outMode": "exact"}}, token)
for _ in range(600):
    code, jr = call("GET", "/api/jobs/%s" % job["jobId"]); j = jr["job"]
    if j["status"] in ("done", "error", "cancelled"): break
    time.sleep(0.5)
print("job", j["status"], j.get("message"))
print("result", json.dumps(j.get("result"), ensure_ascii=False)[:300])
print("error", j.get("error"))
out = (j.get("result") or {}).get("outputPath")
if out:
    fp = r"L:\dev\Trim\tools\ffmpeg\bin\ffprobe.exe"
    p = subprocess.run([fp, "-v", "error", "-count_frames", "-select_streams", "v:0",
                        "-show_entries", "stream=start_time,nb_read_frames", "-of", "csv=p=0", out],
                       capture_output=True, text=True)
    print("out probe", p.stdout.strip(), p.stderr.strip()[:200])
    print("exists", os.path.exists(out), os.path.getsize(out) if os.path.exists(out) else 0)
