import json, os, time, urllib.request, urllib.error
BASE="http://127.0.0.1:8003"
D=r"L:\dev\Trim\data\test"
SRC=os.path.join(D,"src_h264.mp4")

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

def wait(jid):
    for _ in range(900):
        c,jr=call("GET","/api/jobs/%s"%jid); j=jr["job"]
        if j["status"] in ("done","error","cancelled"): return j
        time.sleep(0.4)
    return j

c,tok=call("GET","/api/token"); token=tok["token"]
c,res=call("POST","/api/sources/open",{"path":SRC},token)
sid=res["source"]["id"]
for _ in range(120):
    c,kf=call("GET","/api/sources/%s/keyframes"%sid)
    if kf.get("state") in ("ready","error"): break
    time.sleep(0.4)

fails=0
# lossless
c,j=call("POST","/api/exports",{"sourceId":sid,"startUs":0,"endUs":2000000,"mode":"lossless","options":{"outputPath":D}},token)
w=wait(j["jobId"]); n1=os.path.basename((w.get("result") or {}).get("outputPath") or "")
ok1 = w["status"]=="done" and "切出0s-2s" in n1 and "無変換" in n1 and ".trim-" not in n1
print(("OK  " if ok1 else "FAIL") + " lossless name: " + n1); fails += 0 if ok1 else 1
# re-encode with settings
opts={"outputPath":D,"encoder":"libx265","videoBitrate":1500,"stabilize":False,"crop":{"w":320,"h":180,"x":0,"y":0}}
c,j=call("POST","/api/exports",{"sourceId":sid,"startUs":0,"endUs":2000000,"mode":"reencode","options":opts},token)
w=wait(j["jobId"]); n2=os.path.basename((w.get("result") or {}).get("outputPath") or "")
ok2 = w["status"]=="done" and "再エンコード" in n2 and "H265" in n2 and "1500kbps" in n2 and "切抜320x180" in n2 and "切出0s-2s" in n2
print(("OK  " if ok2 else "FAIL") + " reencode name: " + n2); fails += 0 if ok2 else 1
# audio-only
c,res2=call("POST","/api/sources/open",{"path":os.path.join(D,"a.mp3")},token)
s2=res2["source"]["id"]
for _ in range(60):
    c,kf2=call("GET","/api/sources/%s/keyframes"%s2)
    if kf2.get("state") in ("ready","error"): break
    time.sleep(0.3)
c,j=call("POST","/api/exports",{"sourceId":s2,"startUs":0,"endUs":1000000,"mode":"lossless","options":{"outputPath":D}},token)
w=wait(j["jobId"]); n3=os.path.basename((w.get("result") or {}).get("outputPath") or "")
ok3 = w["status"]=="done" and "切出0s-1s" in n3 and "無変換" in n3
print(("OK  " if ok3 else "FAIL") + " audio name: " + n3); fails += 0 if ok3 else 1
print("RESULT:", "OK" if fails==0 else "FAIL(%d)"%fails)
