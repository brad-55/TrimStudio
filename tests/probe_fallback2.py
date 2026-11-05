import json, os, time, urllib.request, urllib.error
BASE="http://127.0.0.1:8003"
BIG=r"L:\ImageApp\20261103_池尻大橋\mp4\VID_20261103_114920_003.mp4"
def call(method, path, body=None, token=None):
    data=None; h={}
    if body is not None: data=json.dumps(body).encode(); h["Content-Type"]="application/json"
    if token: h["X-Trim-Token"]=token
    req=urllib.request.Request(BASE+path,data=data,headers=h,method=method)
    try:
        with urllib.request.urlopen(req,timeout=900) as r: return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raw=e.read().decode("utf-8","replace")
        try: return e.code, json.loads(raw)
        except ValueError: return e.code, raw
c,tok=call("GET","/api/token"); token=tok["token"]
c,res=call("POST","/api/sources/open",{"path":BIG},token)
s=res["source"]
for _ in range(200):
    c,kf=call("GET","/api/sources/%s/keyframes"%s["id"])
    if kf.get("state") in ("ready","error"): break
    time.sleep(0.5)
print("keyframes", kf.get("state"), len(kf.get("keyframes") or []))
c,job=call("POST","/api/exports",{"sourceId":s["id"],"startUs":1000000,"endUs":3000000,"mode":"lossless","options":{}},token)
for _ in range(600):
    c,jr=call("GET","/api/jobs/%s"%job["jobId"]); j=jr["job"]
    if j["status"] in ("done","error","cancelled"): break
    time.sleep(0.5)
r=j.get("result") or {}
print("status", j["status"])
print("error", str(j.get("error"))[:300])
print("out", r.get("outputPath"))
print("warnings", r.get("warnings"))
print("exists", os.path.exists(r.get("outputPath") or ""))
