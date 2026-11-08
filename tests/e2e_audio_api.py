import json, subprocess, sys, time, urllib.request
BASE = "http://127.0.0.1:8003"


def api(path, data=None, method=None):
    url = BASE + path
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method or ("POST" if data is not None else "GET"),
                                 headers={"Content-Type": "application/json"})
    if data is not None:
        tok = json.loads(urllib.request.urlopen(BASE + "/api/token", timeout=10).read())["token"]
        req.add_header("X-Trim-Token", tok)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def main():
    fails = 0
    src = api("/api/sources/open", {"path": r"L:\dev\Trim\data\test\audio_sync\src.mp4"})["source"]
    added = api("/api/sources/open", {"path": r"L:\dev\Trim\data\test\audio_sync\added.m4a"})["source"]
    print("src", src["id"][:8], "added", added["id"][:8])
    job = api("/api/audio/sync", {"sourceId": src["id"], "addedSourceId": added["id"],
                                 "startUs": 0, "windowMs": 10000, "rangeMs": 2000, "windows": 2})
    jid = job["jobId"]
    print("job", jid)
    st = {}
    for _ in range(120):
        st = api("/api/jobs/" + jid).get("job") or {}
        if st.get("status") in ("done", "error", "cancelled"):
            break
        time.sleep(1)
    print("status", st.get("status"), "result", st.get("result"), "error", st.get("error"))
    res = st.get("result") or {}
    ok = st.get("status") == "done" and res.get("ok") and abs(res.get("offsetMs", 0) + 137) <= 25
    print(("OK   " if ok else "FAIL ") + "sync API returns about -137ms")
    fails += 0 if ok else 1

    # validation errors
    try:
        api("/api/audio/sync", {"sourceId": src["id"], "addedSourceId": "nope"})
        print("FAIL unknown added source accepted"); fails += 1
    except urllib.error.HTTPError as e:
        print(("OK   " if e.code == 404 else "FAIL ") + "unknown added source -> " + str(e.code))

    # export validation: bad audioMode
    try:
        api("/api/exports", {"sourceId": src["id"], "startUs": 0, "endUs": 1000000,
                             "options": {"mode": "lossless", "audioMode": "bogus"}})
        print("FAIL bad audioMode accepted"); fails += 1
    except urllib.error.HTTPError as e:
        print(("OK   " if e.code == 400 else "FAIL ") + "bad audioMode -> " + str(e.code))

    # export validation: added source missing for added mode
    try:
        api("/api/exports", {"sourceId": src["id"], "startUs": 0, "endUs": 1000000,
                             "options": {"mode": "lossless", "audioMode": "added"}})
        print("FAIL missing addedSourceId accepted"); fails += 1
    except urllib.error.HTTPError as e:
        print(("OK   " if e.code == 404 else "FAIL ") + "missing added source -> " + str(e.code))

    print("RESULT:", "OK" if fails == 0 else "FAIL(%d)" % fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
