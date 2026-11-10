"""End-to-end tests for the preview API against a running server.

These are the contract checks that a unit test cannot make: the build endpoint's cache /
job / 409 answers, the media route's Range behaviour and key validation.  They skip
cleanly when no server is listening (the same convention as the other e2e suites).
"""
import json
import os
import sys
import uuid
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _harness import local_build_stamp  # noqa: E402

fails = 0
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8003"


def check(label, cond, detail=""):
    global fails
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else "  " + str(detail)))
    if not cond:
        fails += 1


STRICT = os.environ.get("TRIM_E2E_STRICT") == "1"


def skip(reason):
    # A skipped suite is green, so a broken start-up path could silently hollow out the
    # whole E2E layer.  Local manual runs may skip; a release gate sets TRIM_E2E_STRICT=1.
    if STRICT:
        print("RESULT: FAIL (strict mode: " + reason + ")")
        return 1
    print("RESULT: SKIP (" + reason + ")")
    return 0


def request(path, method="GET", body=None, headers=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    if token:
        req.add_header("X-Trim-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def token_for(cfg):
    from app import security
    return security.load_or_create_token(cfg.data_dir)


def main():
    try:
        status, raw = request("/api/health")
    except OSError as exc:
        return skip("no server at " + BASE + ": " + str(exc)[:80])
    if status != 200:
        return skip("health returned %d" % status)
    stamp = local_build_stamp()
    if json.loads(raw).get("build") != stamp:
        return skip("the running server is an older build; restart it first")

    from app.config import Config
    cfg = Config()
    token = token_for(cfg)
    status, raw = request("/api/sources")
    sources = json.loads(raw)
    if isinstance(sources, dict):
        sources = sources.get("sources") or []
    video = next((s for s in sources if s.get("kind") == "video" and s.get("audioCodec")), None)
    if video is None:
        return skip("no video source with audio")

    body = {"sourceId": video["id"], "variant": "original", "audioMode": "original",
            "audioShiftMs": 300}
    status, raw = request("/api/preview/build", "POST", body, token=token)
    check("build accepts a valid request", status in (200, 409), (status, raw[:200]))
    payload = json.loads(raw) if raw else {}
    if status == 409 and payload.get("proxyJobId"):
        # Documented two-step flow: wait for the proxy, then ask for the preview again.
        for _ in range(240):
            time.sleep(0.5)
            _status, job_raw = request("/api/jobs/" + payload["proxyJobId"], token=token)
            proxy = json.loads(job_raw).get("job") or {}
            if proxy.get("status") in ("done", "error", "cancelled"):
                break
        check("the proxy step completed", proxy.get("status") == "done", proxy.get("status"))
        body["variant"] = "proxy"
        status, raw = request("/api/preview/build", "POST", body, token=token)
        payload = json.loads(raw) if raw else {}
        check("the retried build is accepted", status == 200, (status, raw[:200]))
    url = payload.get("url")
    if not url and payload.get("jobId"):
        for _ in range(240):
            time.sleep(0.5)
            _status, job_raw = request("/api/jobs/" + payload["jobId"], token=token)
            job = json.loads(job_raw).get("job") or {}
            if job.get("status") == "done":
                url = (job.get("result") or {}).get("url")
                break
            if job.get("status") in ("error", "cancelled"):
                check("the build finished", False, job.get("error"))
                break
    check("the build produced a media url", bool(url), payload)
    if url:
        status, _ = request(url, headers={"Range": "bytes=0-1023"})
        check("the media route answers a range request with 206", status == 206, status)
        status, _ = request("/api/preview/media/not-a-key.mp4")
        check("a non-hex key is rejected with 400", status == 400, status)
        status, _ = request("/api/preview/media/" + "a" * 40 + ".mp4")
        check("an unknown key is a 404, not a traversal", status == 404, status)

    # Two identical requests fired at the same moment must not start two builds.  The
    # cache key covers every option, so a uuid-derived addedStartMs (ignored by the
    # "original" audio mode) makes this run's key unique without changing the output.
    # Without that, a cached answer from an earlier run would satisfy "one job" trivially
    # without ever exercising the in-flight path.
    run_token = int(uuid.uuid4().int % 80000000) + 1000
    body2 = {"sourceId": video["id"], "variant": body.get("variant", "original"),
             "audioMode": "original", "audioShiftMs": 300, "addedStartMs": run_token}
    barrier = threading.Barrier(2)
    results = []

    def fire():
        barrier.wait()
        results.append(request("/api/preview/build", "POST", body2, token=token))

    threads = [threading.Thread(target=fire) for _ in range(2)]
    [thread.start() for thread in threads]
    [thread.join() for thread in threads]
    codes = [code for code, _raw in results]
    payloads = [json.loads(raw) if raw else {} for _code, raw in results]
    jobs_seen = [payload2["jobId"] for payload2 in payloads if payload2.get("jobId")]
    check("concurrent identical builds are both accepted", codes == [200, 200], codes)
    check("at least one concurrent request started a build", bool(jobs_seen), payloads)
    check("concurrent identical builds share one job", len(set(jobs_seen)) == 1, jobs_seen)
    if jobs_seen:
        job = {}
        for _ in range(240):
            time.sleep(0.2)
            _status, job_raw = request("/api/jobs/" + jobs_seen[0], token=token)
            job = json.loads(job_raw).get("job") or {}
            if job.get("status") in ("done", "error", "cancelled"):
                break
        check("the shared build finished", job.get("status") == "done", job.get("error"))
        # Exactly one job may exist for this run token: a second, silently started build
        # would appear here even if the responses had coincidentally shared an id.
        _status, list_raw = request("/api/jobs", token=token)
        rows = json.loads(list_raw)
        rows = rows if isinstance(rows, list) else (rows.get("jobs") or [])
        matching = [row for row in rows
                    if row.get("kind") == "preview"
                    and (row.get("result") or {}).get("addedStartMs") == run_token]
        check("exactly one job was created for the unique run token", len(matching) == 1,
              [row.get("id") for row in matching])

    status, raw = request("/api/preview/build", "POST",
                          {"sourceId": video["id"], "variant": 5}, token=token)
    check("a non-string variant is a 400", status == 400, (status, raw[:120]))

    print("RESULT: " + ("FAIL(%d)" % fails if fails else "OK"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
