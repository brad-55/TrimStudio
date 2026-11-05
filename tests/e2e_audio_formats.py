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

def dur(p):
    q=subprocess.run([FP,"-v","error","-show_entries","format=duration","-of","default=nw=1:nk=1",p],capture_output=True,text=True)
    try: return round(float(q.stdout.strip()),3)
    except ValueError: return None

srcs={"m4a":["-c:a","aac","-b:a","128k"],"flac":["-c:a","flac"],"wav":["-c:a","pcm_s16le"],
      "ogg":["-c:a","libvorbis","-q:a","5"],"opus":["-c:a","libopus","-b:a","96k"],"wma":["-c:a","wmav2","-b:a","128k"]}
c,tok=call("GET","/api/token"); token=tok["token"]
for ext,enc in srcs.items():
    p=os.path.join(D,"a2."+ext)
    subprocess.run([FF,"-hide_banner","-loglevel","error","-y","-f","lavfi","-i","sine=frequency=440:duration=8"]+enc+[p])
    c,res=call("POST","/api/sources/open",{"path":p},token)
    if c!=200 or not isinstance(res,dict) or "source" not in res:
        print(ext,"open failed",c,str(res)[:120]); continue
    s=res["source"]
    c,job=call("POST","/api/exports",{"sourceId":s["id"],"startUs":1000000,"endUs":4000000,"mode":"lossless","options":{}},token)
    j=wait(job["jobId"]); r=j.get("result") or {}
    print("%-5s kind=%-5s container=%-8s status=%-5s dur=%s err=%s" % (ext, s.get("kind"), r.get("container"), j["status"], dur(r["outputPath"]) if r.get("outputPath") else None, str(j.get("error"))[:60]))
