"""Two-phase job history check.

Phase 1 (create):  python tests/e2e_jobhistory.py --create
   Restart the server, then:
Phase 2 (verify):  python tests/e2e_jobhistory.py --verify
"""
import json, os, sys, time, urllib.request, urllib.error

BASE = "http://127.0.0.1:8003"
ROOT = r"L:\dev\Trim"
D = os.path.join(ROOT, "data", "test")
SRC = os.path.join(D, "src_h264.mp4")
STATE = os.path.join(ROOT, "data", "jobhistory_state.json")


def call(method, path, body=None, token=None):
    data = None
    h = {}
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    if token:
        h["X-Trim-Token"] = token
    req = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw


def wait(jid):
    for _ in range(600):
        c, jr = call("GET", "/api/jobs/%s" % jid)
        j = jr["job"]
        if j["status"] in ("done", "error", "cancelled"):
            return j
        time.sleep(0.4)
    return j


def create():
    c, tok = call("GET", "/api/token")
    token = tok["token"]
    c, res = call("POST", "/api/sources/open", {"path": SRC}, token)
    sid = res["source"]["id"]
    for _ in range(120):
        c, kf = call("GET", "/api/sources/%s/keyframes" % sid)
        if kf.get("state") == "ready":
            break
        time.sleep(0.4)
    c, job = call("POST", "/api/exports", {"sourceId": sid, "startUs": 2000000, "endUs": 4000000,
                  "mode": "lossless", "options": {"outputPath": D}}, token)
    ok_id = job["jobId"]
    ok_job = wait(ok_id)
    c, job2 = call("POST", "/api/exports", {"sourceId": sid, "startUs": 2000000, "endUs": 4000000,
                   "mode": "lossless", "options": {"outputPath": r"L:\ImageApp"}}, token)
    err_id = job2["jobId"]
    err_job = wait(err_id)
    json.dump({"done": ok_id, "error": err_id}, open(STATE, "w", encoding="utf-8"))
    print("phase1 done: done=%s(%s) error=%s(%s)" % (ok_id, ok_job["status"], err_id, err_job["status"]))
    return 0 if ok_job["status"] == "done" and err_job["status"] == "error" else 1


def verify():
    if not os.path.exists(STATE):
        print("phase1 state file missing; run --create first")
        return 1
    ids = json.load(open(STATE, encoding="utf-8"))
    fails = 0
    c, jr = call("GET", "/api/jobs/%s" % ids["done"])
    if c != 200 or not (jr.get("job") or {}).get("persisted") or not (jr["job"].get("result") or {}).get("outputPath"):
        print("FAIL done job after restart:", c, str(jr)[:120]); fails += 1
    else:
        print("OK done job persisted, status=%s, output=%s" % (jr["job"]["status"], os.path.basename(jr["job"]["result"]["outputPath"])))
    c, jr = call("GET", "/api/jobs/%s" % ids["error"])
    if c != 200 or not (jr.get("job") or {}).get("persisted") or not (jr["job"] or {}).get("error"):
        print("FAIL error job after restart:", c, str(jr)[:120]); fails += 1
    else:
        print("OK error job persisted, message=%s" % str(jr["job"]["error"])[:60])
    c, jr = call("GET", "/api/jobs?history=100")
    jobs_list = jr.get("jobs") or []
    by_id = {j.get("id"): j for j in jobs_list}
    if ids["done"] in by_id and ids["error"] in by_id:
        persisted = sum(1 for j in by_id.values() if j.get("persisted"))
        print("OK history list: %d rows (%d persisted; in-memory takes precedence)" % (len(by_id), persisted))
    elif len(jobs_list) >= 100:
        print("OK history list: limit 100 reached; older rows (our jobs) legitimately omitted")
    else:
        print("FAIL history list missing our jobs"); fails += 1
    c, _ = call("GET", "/api/jobs/deadbeefdeadbeef")
    if c != 404:
        print("FAIL unknown job should be 404, got", c); fails += 1
    else:
        print("OK unknown job -> 404")
    print("RESULT:", "OK" if fails == 0 else "FAIL(%d)" % fails)
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "--create"
    sys.exit(create() if mode == "--create" else verify())
