import json, os, subprocess, time, urllib.request, urllib.error
BASE="http://127.0.0.1:8003"
FF=r"L:\dev\Trim\tools\ffmpeg\bin\ffmpeg.exe"
FP=r"L:\dev\Trim\tools\ffmpeg\bin\ffprobe.exe"
D=r"L:\dev\Trim\data\test"

def call(method, path, body=None, token=None):
    data=None; h={}
    if body is not None: data=json.dumps(body).encode(); h["Content-Type"]="application/json"
    if token: h["X-Trim-Token"]=token
    req=urllib.request.Request(BASE+path,data=data,headers=h,method=method)
    try:
        with urllib.request.urlopen(req,timeout=600) as r: return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e: return e.code, e.read().decode("utf-8","replace")

def wait(jid):
    for _ in range(900):
        c,jr=call("GET","/api/jobs/%s"%jid); j=jr["job"]
        if j["status"] in ("done","error","cancelled"): return j
        time.sleep(0.4)
    return j

def probe(path):
    q=subprocess.run([FP,"-v","error","-show_entries","stream=index,codec_type,codec_name","-of","json",path],capture_output=True,text=True,encoding="utf-8",errors="replace")
    streams=json.loads(q.stdout or "{}").get("streams") or []
    d=subprocess.run([FP,"-v","error","-show_entries","format=duration","-of","default=nw=1:nk=1",path],capture_output=True,text=True)
    try: dur=round(float(d.stdout.strip()),3)
    except ValueError: dur=None
    return streams, dur

def make(name, enc):
    p=os.path.join(D,name)
    subprocess.run([FF,"-hide_banner","-loglevel","error","-y","-f","lavfi","-i","testsrc2=size=320x180:rate=25",
                    "-f","lavfi","-i","sine=frequency=440:duration=6","-t","6"]+enc+[p])
    return p

cases=[
  ("wmv2 video + wmav2 audio", "t_wmv2.wmv", ["-c:v","wmv2","-c:a","wmav2","-b:a","128k"]),
  ("msmpeg4 video + pcm audio", "t_msmpeg4.avi", ["-c:v","msmpeg4","-c:a","pcm_s16le"]),
  ("flv1 video + mp3 audio", "t_flv1.flv", ["-c:v","flv1","-c:a","libmp3lame"]),
  ("wav pcm_alaw", "t_alaw.wav", ["-vn","-c:a","pcm_alaw"]),
]
c,tok=call("GET","/api/token"); token=tok["token"]
fails=0
for label,name,enc in cases:
    p=make(name,enc)
    c,res=call("POST","/api/sources/open",{"path":p},token)
    if c!=200 or not isinstance(res,dict) or "source" not in res:
        print("%-28s open failed %s %s" % (label,c,str(res)[:80])); fails+=1; continue
    s=res["source"]
    for _ in range(120):
        c,kf=call("GET","/api/sources/%s/keyframes"%s["id"])
        if kf.get("state")=="ready": break
        time.sleep(0.5)
    c,job=call("POST","/api/exports",{"sourceId":s["id"],"startUs":1000000,"endUs":4000000,"mode":"lossless","options":{"outputPath":D}},token)
    if c!=200:
        print("%-28s export create failed %s" % (label,str(job)[:80])); fails+=1; continue
    j=wait(job["jobId"]); r=j.get("result") or {}
    if j["status"]!="done":
        print("%-28s status=%s err=%s" % (label,j["status"],str(j.get("error"))[:100])); fails+=1; continue
    streams,dur=probe(r["outputPath"])
    vids=[x for x in streams if x["codec_type"]=="video"]; auds=[x for x in streams if x["codec_type"]=="audio"]
    want_v = 1 if s.get("kind")=="video" else 0
    target = (r.get("actualEndUs", 4000000) - r.get("actualStartUs", 1000000)) / 1e6
    ok = len(vids)==want_v and len(auds)==1 and dur is not None and abs(dur-target)<=0.35
    print("%-28s kind=%-5s container=%-8s v=%d a=%d dur=%s target=%s warnings=%s %s" % (label, s.get("kind"), r.get("container"), len(vids), len(auds), dur, round(target,3), len(r.get("warnings") or []), "OK" if ok else "FAIL"))
    fails += 0 if ok else 1
print("RESULT:", "OK" if fails==0 else "FAIL(%d)"%fails)
