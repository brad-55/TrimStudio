import json, os, subprocess, sys, time, urllib.request, urllib.error
BASE="http://127.0.0.1:8003"
FF=r"L:\dev\Trim\tools\ffmpeg\bin\ffmpeg.exe"
FP=r"L:\dev\Trim\tools\ffmpeg\bin\ffprobe.exe"
D=r"L:\dev\Trim\data\test"
MP3=os.path.join(D,"a.mp3")

def call(method, path, body=None, token=None):
    data=None; h={}
    if body is not None: data=json.dumps(body).encode(); h["Content-Type"]="application/json"
    if token: h["X-Trim-Token"]=token
    req=urllib.request.Request(BASE+path,data=data,headers=h,method=method)
    try:
        with urllib.request.urlopen(req,timeout=600) as r: return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raw=e.read().decode("utf-8","replace")
        try: return e.code, json.loads(raw)
        except ValueError: return e.code, raw

def wait(jid):
    for _ in range(1200):
        c,jr=call("GET","/api/jobs/%s"%jid); j=jr["job"]
        if j["status"] in ("done","error","cancelled"): return j
        time.sleep(0.5)
    return j

def dur(p):
    q=subprocess.run([FP,"-v","error","-show_entries","format=duration","-of","default=nw=1:nk=1",p],capture_output=True,text=True)
    try: return float(q.stdout.strip())
    except ValueError: return None

if not os.path.exists(MP3):
    subprocess.run([FF,"-hide_banner","-loglevel","error","-y","-f","lavfi","-i","sine=frequency=440:duration=10","-c:a","libmp3lame","-q:a","2",MP3])
c,tok=call("GET","/api/token"); token=tok["token"]
c,res=call("POST","/api/sources/open",{"path":MP3},token)
print("open mp3", c, res.get("source",{}).get("kind"), res.get("source",{}).get("audioCodec"))
sid=res["source"]["id"]
c,kf=call("GET","/api/sources/%s/keyframes"%sid); print("keyframes", c, kf.get("state"), kf.get("keyframes"))
c,fr=call("GET","/api/sources/%s/frame?tUs=1000000"%sid); print("frame route", c)
# lossless audio cut
c,job=call("POST","/api/exports",{"sourceId":sid,"startUs":2000000,"endUs":7000000,"mode":"lossless","options":{}},token)
j=wait(job["jobId"]); r=j.get("result") or {}
print("lossless", j["status"], r.get("container"), r.get("outputPath"), "dur=", dur(r.get("outputPath","")) if r.get("outputPath") else None)
# reencode audio cut
c,job2=call("POST","/api/exports",{"sourceId":sid,"startUs":1000000,"endUs":4000000,"mode":"reencode","options":{}},token)
j2=wait(job2["jobId"]); r2=j2.get("result") or {}
print("reencode", j2["status"], r2.get("container"), "dur=", dur(r2.get("outputPath","")) if r2.get("outputPath") else None, str(j2.get("error"))[:120])
# unwritable destination -> clear error
c,vid=call("POST","/api/sources/open",{"path":os.path.join(D,"src_h264.mp4")},token)
vsid=vid["source"]["id"]
for _ in range(60):
    c,kf=call("GET","/api/sources/%s/keyframes"%vsid)
    if kf.get("state")=="ready": break
    time.sleep(0.5)
c,job3=call("POST","/api/exports",{"sourceId":vsid,"startUs":2000000,"endUs":3000000,"mode":"lossless","options":{"outputPath":r"L:\ImageApp"}},token)
j3=wait(job3["jobId"])
print("unwritable", j3["status"], str(j3.get("error"))[:220])
