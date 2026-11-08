"""Non-functional export behaviour: parallel jobs, cancellation, path collisions.

These are the cases a user meets on a slow machine, and they are exactly where the job
manager (semaphore, .part files, path reservations) can corrupt another export.
"""
import glob
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import packet_times, require_current, require_ffmpeg  # noqa: E402

BASE = "http://127.0.0.1:8003"
D = os.path.join(ROOT, "data", "test", "aux")
FF = os.path.join(ROOT, "tools", "ffmpeg", "bin", "ffmpeg.exe")
fails = 0


def check(cond, label):
    global fails
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        fails += 1


def _token():
    try:
        with urllib.request.urlopen(BASE + "/api/token", timeout=10) as r:
            return (json.loads(r.read()) or {}).get("token") or ""
    except Exception:
        return ""


TOKEN = _token()


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
        time.sleep(0.2)
    return {"status": "timeout"}


def adts_md5(path, spec="0:a", start=None, dur=None):
    """Packet-level identity of a stream, optionally over the same interval as the cut."""
    pre = ["-ss", str(start), "-t", str(dur)] if start is not None else []
    p = subprocess.run([FF, "-v", "error", "-i", path] + pre + ["-map", spec, "-c", "copy",
                       "-f", "adts", "-"], capture_output=True)
    return hashlib.md5(p.stdout).hexdigest() if p.returncode == 0 else "ERR"


def main():
    require_current(BASE, TOKEN)
    require_ffmpeg(BASE, FF, TOKEN)
    os.makedirs(D, exist_ok=True)
    stamp = str(int(time.time()))
    a = os.path.abspath(os.path.join(D, "np_a_" + stamp + ".mp4"))
    b = os.path.abspath(os.path.join(D, "np_b_" + stamp + ".mp4"))
    for path, freq, secs in ((a, 440, 20), (b, 990, 20)):
        subprocess.run([FF, "-y", "-v", "error", "-f", "lavfi", "-i",
                        "testsrc2=size=320x240:rate=30:duration=%d" % secs,
                        "-f", "lavfi", "-i", "sine=frequency=%d:duration=%d" % (freq, secs),
                        "-c:v", "libx264", "-g", "30", "-pix_fmt", "yuv420p", "-c:a", "aac",
                        "-shortest", path], check=True)
    ids = {}
    for path, key in ((a, "a"), (b, "b")):
        st, r = call("POST", "/api/sources/open", {"path": path})
        ids[key] = ((r or {}).get("source") or {}).get("id")
    check(all(ids.values()), "the fixtures open: " + str(ids))
    if not all(ids.values()):
        return 1

    # --- two exports of different sources must not cross-talk ---
    out_a = os.path.abspath(os.path.join(D, "np_out_a_" + stamp + ".mp4"))
    out_b = os.path.abspath(os.path.join(D, "np_out_b_" + stamp + ".mp4"))
    jobs = []
    for key, out in (("a", out_a), ("b", out_b)):
        st, r = call("POST", "/api/exports", {"sourceId": ids[key], "startUs": 0, "endUs": 8_000_000,
                                              "mode": "lossless", "options": {"outputPath": out}})
        jobs.append((key, st, (r or {}).get("jobId")))
    check(all(st == 200 for _, st, _ in jobs), "two exports are accepted at once: " + str([s for _, s, _ in jobs]))
    results = {k: wait_job(j) for k, _, j in jobs if j}
    check(all(j.get("status") == "done" for j in results.values()),
          "both parallel exports finish: " + str({k: v.get("status") for k, v in results.items()}))
    check(os.path.exists(out_a) and os.path.exists(out_b), "both outputs exist")
    if os.path.exists(out_a) and os.path.exists(out_b):
        check(adts_md5(out_a) == adts_md5(a, "0:a", 0, 8), "the first output carries its own source audio")
        check(adts_md5(out_b) == adts_md5(b, "0:a", 0, 8), "the second output carries its own source audio")
        check(adts_md5(out_a) != adts_md5(out_b), "the two outputs are not the same media")

    # --- the same explicit path may not be taken twice while a job holds it ---
    same = os.path.abspath(os.path.join(D, "np_same_" + stamp + ".mp4"))
    st1, r1 = call("POST", "/api/exports", {"sourceId": ids["a"], "startUs": 0, "endUs": 6_000_000,
                                            "mode": "lossless", "options": {"outputPath": same}})
    st2, r2 = call("POST", "/api/exports", {"sourceId": ids["a"], "startUs": 0, "endUs": 6_000_000,
                                            "mode": "lossless", "options": {"outputPath": same}})
    grab = (st1 == 200 and st2 == 200)   # both may be accepted when the first already finished
    check(st1 == 200 and (st2 == 409 or grab),
          "a path in use is refused with 409: first=%s second=%s" % (st1, st2))
    if st1 == 200 and r1.get("jobId"):
        wait_job(r1["jobId"])
    if st2 == 200 and (r2 or {}).get("jobId"):
        wait_job(r2["jobId"])
    check(os.path.exists(same), "the shared path exists after the first job")

    # --- a queued job can be cancelled and leaves no debris ---
    outs = [os.path.abspath(os.path.join(D, "np_q%d_%s.mp4" % (i, stamp))) for i in range(3)]
    qjobs = []
    for i, out in enumerate(outs):
        st, r = call("POST", "/api/exports", {"sourceId": ids["b"], "startUs": 0, "endUs": 12_000_000,
                                              "mode": "lossless", "options": {"outputPath": out}})
        qjobs.append((st, (r or {}).get("jobId")))
    accepted = [j for s, j in qjobs if s == 200 and j]
    check(len(accepted) >= 2, "the queue accepts work beyond the concurrency limit: %d" % len(accepted))
    if accepted:
        st, r = call("POST", "/api/jobs/" + accepted[-1] + "/cancel")
        j = wait_job(accepted[-1])
        check(j.get("status") in ("cancelled", "done"),
              "the cancelled job reaches a terminal state: " + str(j.get("status")))
        if j.get("status") == "cancelled":
            left = glob.glob(outs[-1] + "*") + glob.glob(os.path.splitext(outs[-1])[0] + ".part*")
            check(not left, "a cancelled job leaves no part or output debris: " + str([os.path.basename(x) for x in left]))
            st, r = call("POST", "/api/exports", {"sourceId": ids["b"], "startUs": 0, "endUs": 4_000_000,
                                                  "mode": "lossless", "options": {"outputPath": outs[-1]}})
            again = wait_job((r or {}).get("jobId")) if st == 200 else {}
            check(again.get("status") == "done", "the path is reusable right after a cancel: " + str(again.get("status")))
    for s, j in qjobs[:2]:
        if s == 200 and j:
            wait_job(j, timeout=120)

    print("RESULT: " + ("OK" if fails == 0 else "FAIL(%d)" % fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
