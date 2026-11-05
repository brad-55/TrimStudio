import json, os, subprocess, time, urllib.request, urllib.error
BASE="http://127.0.0.1:8003"
FF=r"L:\dev\Trim\tools\ffmpeg\bin\ffmpeg.exe"
FP=r"L:\dev\Trim\tools\ffmpeg\bin\ffprobe.exe"
D=r"L:\dev\Trim\data\test"

ENC={"mp3":["-c:a","libmp3lame","-q:a","2"],"m4a":["-c:a","aac","-b:a","128k"],
     "aac":["-c:a","aac","-b:a","128k"],"wav":["-c:a","pcm_s16le"],"flac":["-c:a","flac"],
     "ogg":["-c:a","libvorbis","-q:a","5"],"opus":["-c:a","libopus","-b:a","96k"],
     "wma":["-c:a","wmav2","-b:a","128k"],"aif":["-c:a","pcm_s16be"],"aiff":["-c:a","pcm_s16be"]}

def call(method, path, body=None, token=None):
    data=None; h={}
    if body is not None: data=json.dumps(body).encode(); h["Content-Type"]="application/json"
    if token: h["X-Trim-Token"]=token
    req=urllib.request.Request(BASE+path,data=data,headers=h,method=method)
    try:
        with urllib.request.urlopen(req,timeout=300) as r: return r.status, json.loads(r.read().decode())
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

def upload(path, filename):
    boundary="----trimtest"
    with open(path,"rb") as fh: payload=fh.read()
    body=(("--%s\r\nContent-Disposition: form-data; name=file; filename=%s\r\nContent-Type: application/octet-stream\r\n\r\n"%(boundary,filename)).encode()+payload+("\r\n--%s--\r\n"%boundary).encode())
    req=urllib.request.Request(BASE+"/api/sources/upload",data=body,headers={"Content-Type":"multipart/form-data; boundary="+boundary,"X-Trim-Token":TOKEN},method="POST")
    with urllib.request.urlopen(req,timeout=300) as r: return json.loads(r.read().decode())

c,tok=call("GET","/api/token"); TOKEN=tok["token"]
fails=0
for ext,enc in ENC.items():
    src=os.path.join(D,"up_src."+ext)
    subprocess.run([FF,"-hide_banner","-loglevel","error","-y","-f","lavfi","-i","sine=frequency=440:duration=6"]+enc+[src])
    try:
        s=upload(src,"uploaded."+ext)["source"]
    except Exception as exc:
        print("%-5s upload FAILED %s" % (ext, str(exc)[:80])); fails+=1; continue
    ok_kind = s.get("kind")=="audio"
    c,job=call("POST","/api/exports",{"sourceId":s["id"],"startUs":1000000,"endUs":4000000,"mode":"lossless","options":{"outputPath":D}},TOKEN)
    if c!=200:
        print("%-5s export create failed %s" % (ext, str(job)[:80])); fails+=1; continue
    j=wait(job["jobId"]); r=j.get("result") or {}
    d=dur(r.get("outputPath")) if r.get("outputPath") else None
    good = j["status"]=="done" and d is not None and abs(d-3.0)<=0.3
    print("%-5s upload=%s kind=%s container=%-6s status=%-5s dur=%s %s" % (ext, s.get("name"), s.get("kind"), r.get("container"), j["status"], d, "OK" if good else "FAIL"))
    fails += 0 if (good and ok_kind) else 1
print("RESULT:", "OK" if fails==0 else "FAIL(%d)"%fails)
