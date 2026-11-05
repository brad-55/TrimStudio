import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8003"


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
        with urllib.request.urlopen(req, timeout=600) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def wait_job(jid):
    job = {}
    for _ in range(1200):
        code, jr = call("GET", "/api/jobs/%s" % jid)
        job = jr["job"]
        if job["status"] in ("done", "error", "cancelled"):
            return job
        time.sleep(0.5)
    return job


def main():
    code, tok = call("GET", "/api/token")
    token = tok["token"]
    code, res = call("POST", "/api/sources/open", {"path": "L:/dev/Trim/data/test/src_h264.mp4"}, token)
    sid = res["source"]["id"]
    for _ in range(120):
        code, kf = call("GET", "/api/sources/%s/keyframes" % sid)
        if kf.get("state") == "ready":
            break
        time.sleep(0.5)
    print("source", sid, "keyframes", kf.get("state"))

    code, pr = call("POST", "/api/sources/%s/proxy" % sid, {}, token)
    print("proxy job", code, pr)
    job = wait_job(pr["jobId"])
    print("proxy", job["status"], json.dumps(job.get("result"), ensure_ascii=False)[:200], job.get("error"))

    cases = [
        ("crop", {"crop": {"w": 320, "h": 180, "x": 0, "y": 0}, "encoder": "libx264"}),
        ("lut", {"lut": "L:/dev/Trim/luts/identity.cube", "encoder": "libx264"}),
        ("stabilize", {"stabilize": True, "encoder": "libx264"}),
        ("stab_crop_lut", {"stabilize": True, "crop": {"w": 320, "h": 180, "x": 0, "y": 0}, "lut": "L:/dev/Trim/luts/identity.cube", "encoder": "libx265"}),
    ]
    for name, options in cases:
        payload = {"sourceId": sid, "startUs": 2000000, "endUs": 6000000, "mode": "reencode",
                   "options": dict(options, inSnap="prev", outMode="exact")}
        code, jr = call("POST", "/api/exports", payload, token)
        if code != 200:
            print(name, "create failed", code, jr)
            continue
        job = wait_job(jr["jobId"])
        summary = json.dumps(job.get("result"), ensure_ascii=False) if job.get("result") else job.get("error")
        print(name, job["status"], str(summary)[:220])
    return 0


if __name__ == "__main__":
    sys.exit(main())
