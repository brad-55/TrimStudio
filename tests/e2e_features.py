import json
import sys
import time
import urllib.error
import urllib.request
import uuid

BASE = "http://127.0.0.1:8003"


def call(method, path, body=None, token=None, form=None):
    data = None
    headers = {}
    if form is not None:
        boundary = "----trim" + uuid.uuid4().hex
        parts = []
        for name, filename, content, ctype in form:
            parts.append(("--" + boundary + "\r\n").encode())
            parts.append(("Content-Disposition: form-data; name=\"" + name + "\"; filename=\"" + filename + "\"\r\n").encode())
            parts.append(("Content-Type: " + ctype + "\r\n\r\n").encode())
            parts.append(content)
            parts.append(b"\r\n")
        parts.append(("--" + boundary + "--\r\n").encode())
        data = b"".join(parts)
        headers["Content-Type"] = "multipart/form-data; boundary=" + boundary
    elif body is not None:
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

    # variant fix: existing h264 source must be direct-playable
    code, res = call("POST", "/api/sources/open", {"path": "L:/dev/Trim/data/test/src_h264.mp4"}, token)
    sid = res["source"]["id"]
    code, detail = call("GET", "/api/sources/%s" % sid)
    print("variant", detail["variant"], "directPlayable", detail["directPlayable"])

    # frames endpoint
    code, fr = call("GET", "/api/sources/%s/frames?fromUs=1000000&countFrames=8&spanUs=1000000" % sid)
    print("frames", code, fr["frames"][:8])

    # sprite job
    code, sr = call("POST", "/api/sources/%s/sprite" % sid, {}, token)
    job = wait_job(sr["jobId"])
    print("sprite", job["status"], json.dumps(job.get("result"), ensure_ascii=False)[:160], job.get("error"))

    # upload the generated mp4 via multipart
    with open(r"L:\dev\Trim\data\test\src_h264.mp4", "rb") as fh:
        blob = fh.read()
    code, up = call("POST", "/api/sources/upload", token=token, form=[("file", "uploaded.mp4", blob, "video/mp4")])
    print("upload", code, json.dumps(up, ensure_ascii=False)[:200])
    if code == 200:
        usid = up["source"]["id"]
        code, det2 = call("GET", "/api/sources/%s" % usid)
        print("uploaded origin", up["source"]["origin"], "variant", det2["variant"])
        code, delc = call("DELETE", "/api/sources/%s" % usid, token=token)
        print("delete uploaded", code, delc)

    # delete guard: local source must remain on disk
    import os
    existed = os.path.exists(r"L:\dev\Trim\data\test\src_h264.mp4")
    print("local file still exists:", existed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
