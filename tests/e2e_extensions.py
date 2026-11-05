import json, os, shutil, subprocess, time, urllib.request, urllib.error
BASE="http://127.0.0.1:8003"
FF=r"L:\dev\Trim\tools\ffmpeg\bin\ffmpeg.exe"
FP=r"L:\dev\Trim\tools\ffmpeg\bin\ffprobe.exe"
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
    for _ in range(600):
        c,jr=call("GET","/api/jobs/%s"%jid); j=jr["job"]
        if j["status"] in ("done","error","cancelled"): return j
        time.sleep(0.4)
    return j

def open_src(p, token):
    c,res=call("POST","/api/sources/open",{"path":p},token)
    if c!=200 or not isinstance(res,dict) or "source" not in res: return None, res
    s=res["source"]
    for _ in range(180):
        c,kf=call("GET","/api/sources/%s/keyframes"%s["id"])
        if kf.get("state") in ("ready","error"): break
        time.sleep(0.4)
    return s, None

def make(name, cmd):
    p=os.path.join(D,name)
    if os.path.exists(p): os.remove(p)
    subprocess.run([FF,"-hide_banner","-loglevel","error","-y"]+cmd+[p])
    return p if os.path.exists(p) else None

# build device-extension fixtures
base_cmd=["-f","lavfi","-i","testsrc2=size=320x180:rate=25","-f","lavfi","-i","sine=frequency=440:duration=5","-ar","48000","-t","5"]
fixtures={
  "cam.lrv":  ("rename", SRC),                                   # Insta360/GoPro low-res (MP4 content)
  "cam.insv": ("rename", SRC),
  "cam.insp": ("rename", SRC),
  "cam.360":  ("rename", SRC),                                   # GoPro 360
  "cam.3g2":  ("rename", SRC),
  "cam.f4v":  ("flv",  base_cmd+["-c:v","flv1","-c:a","libmp3lame","-f","flv"]),
  "cam.mxf":  ("cmd",  base_cmd+["-an","-c:v","mpeg2video","-q:v","4","-f","mxf"]),
  "cam.dv":   ("cmd",  ["-f","lavfi","-i","testsrc2=size=720x576:rate=25","-f","lavfi","-i","sine=frequency=440:duration=5","-t","5","-c:v","dvvideo","-ac","2","-c:a","pcm_s16le","-ar","48000","-f","dv"]),
  "cam.vob":  ("cmd",  base_cmd+["-c:v","mpeg2video","-q:v","5","-c:a","mp2","-f","vob"]),
  "cam.mod":  ("mpegps", base_cmd+["-c:v","mpeg2video","-q:v","5","-c:a","mp2","-f","mpeg"]),
  "cam.tod":  ("mpegps", base_cmd+["-c:v","mpeg2video","-q:v","5","-c:a","mp2","-f","mpeg"]),
  "cam.rmvb": ("cmd",  base_cmd+["-an","-c:v","rv20","-f","rm"]),
  "xavc.mxf": ("rename", SRC),
}

c,tok=call("GET","/api/token"); token=tok["token"]
fails=0
for name, spec in fixtures.items():
    kind = spec[0]
    if kind == "rename":
        p=os.path.join(D,name); shutil.copyfile(spec[1], p)
    elif kind == "flv":
        p=make(name, spec[1])
    elif kind == "mpegps":
        tmp=os.path.join(D,"_tmp.mpg"); subprocess.run([FF,"-hide_banner","-loglevel","error","-y"]+spec[1]+[tmp]); p=os.path.join(D,name); shutil.move(tmp,p)
    else:
        p=make(name, spec[1])
    if not p:
        print("%-10s SKIP (could not create fixture)" % name); continue
    s,err=open_src(p,token)
    if not s:
        print("%-10s open FAILED %s" % (name, str(err)[:80])); fails+=1; continue
    mode = "reencode" if name.endswith(".rmvb") else "lossless"
    c,job=call("POST","/api/exports",{"sourceId":s["id"],"startUs":1000000,"endUs":3000000,"mode":mode,"options":{"outputPath":D}},token)
    if c!=200:
        print("%-10s kind=%s container=%s export-create %d %s" % (name, s.get("kind"), s.get("container"), c, str(job)[:60])); fails+=1; continue
    j=wait(job["jobId"]); r=j.get("result") or {}
    out=r.get("outputPath")
    expected = "matroska" if name == "xavc.mxf" else None
    ok = j["status"]=="done" and out and os.path.exists(out) and (expected is None or r.get("container") == expected)
    print("%-10s kind=%-5s src_container=%-8s out_container=%-8s status=%-5s %s" % (name, s.get("kind"), s.get("container"), r.get("container"), j["status"], "OK" if ok else "FAIL "+str(j.get("error"))[:60]))
    fails += 0 if ok else 1

# collision avoidance: same source+range exported twice -> two files, second gets -1
sa,err=open_src(SRC,token)
c,j1=call("POST","/api/exports",{"sourceId":sa["id"],"startUs":2000000,"endUs":4000000,"mode":"lossless","options":{"outputPath":D}},token)
w1=wait(j1["jobId"])
c,j2=call("POST","/api/exports",{"sourceId":sa["id"],"startUs":2000000,"endUs":4000000,"mode":"lossless","options":{"outputPath":D}},token)
w2=wait(j2["jobId"])
o1=(w1.get("result") or {}).get("outputPath"); o2=(w2.get("result") or {}).get("outputPath")
coll_ok = w1["status"]=="done" and w2["status"]=="done" and o1 and o2 and o1!=o2 and os.path.exists(o1) and os.path.exists(o2) and os.path.getsize(o1)==os.path.getsize(o2)
print("collision: %s vs %s sizes=%s/%s %s" % (os.path.basename(o1 or ""), os.path.basename(o2 or ""), os.path.getsize(o1) if o1 else None, os.path.getsize(o2) if o2 else None, "OK" if coll_ok else "FAIL"))
fails += 0 if coll_ok else 1

# upload display-name uniqueness
def upload(path, filename):
    boundary="----t"
    payload=open(path,"rb").read()
    body=(("--%s\r\nContent-Disposition: form-data; name=file; filename=%s\r\nContent-Type: application/octet-stream\r\n\r\n"%(boundary,filename)).encode()+payload+("\r\n--%s--\r\n"%boundary).encode())
    req=urllib.request.Request(BASE+"/api/sources/upload",data=body,headers={"Content-Type":"multipart/form-data; boundary="+boundary,"X-Trim-Token":token},method="POST")
    with urllib.request.urlopen(req,timeout=300) as r: return json.loads(r.read().decode())
u1=upload(os.path.join(D,"a.mp3"),"dup.mp3")["source"]["name"]
u2=upload(os.path.join(D,"a.mp3"),"dup.mp3")["source"]["name"]
import re
name_ok = u1 != u2 and bool(re.fullmatch(r"dup(-\d+)?\.mp3", u1)) and bool(re.fullmatch(r"dup(-\d+)?\.mp3", u2))
print("upload names: %s / %s %s" % (u1, u2, "OK" if name_ok else "FAIL"))
fails += 0 if name_ok else 1

print("RESULT:", "OK" if fails==0 else "FAIL(%d)"%fails)
