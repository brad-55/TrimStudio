import json, os, subprocess, sys, time, urllib.request, urllib.error
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

def streams(path):
    q=subprocess.run([FP,"-v","error","-show_entries","stream=codec_type,codec_name","-of","json",path],capture_output=True,text=True,encoding="utf-8",errors="replace")
    return json.loads(q.stdout or "{}").get("streams") or []

def dur(path):
    q=subprocess.run([FP,"-v","error","-show_entries","format=duration","-of","default=nw=1:nk=1",path],capture_output=True,text=True)
    try: return round(float(q.stdout.strip()),3)
    except ValueError: return None

def open_src(p, token):
    c,res=call("POST","/api/sources/open",{"path":p},token)
    if c!=200 or not isinstance(res,dict) or "source" not in res: return None,res
    s=res["source"]
    for _ in range(180):
        c,kf=call("GET","/api/sources/%s/keyframes"%s["id"])
        if kf.get("state") in ("ready","error"): break
        time.sleep(0.4)
    return s,None

def export(sid, token, start, end, extra=None, mode="lossless"):
    opts=dict(extra or {}); opts.setdefault("outputPath", D)
    c,job=call("POST","/api/exports",{"sourceId":sid,"startUs":start,"endUs":end,"mode":mode,"options":opts},token)
    if c!=200: return None, job
    return wait(job["jobId"]), None

c,tok=call("GET","/api/token"); token=tok["token"]
results=[]

p=os.path.join(D,"n_audio.mp4")
subprocess.run([FF,"-hide_banner","-loglevel","error","-y","-f","lavfi","-i","testsrc2=size=320x180:rate=30","-t","6","-c:v","libx264","-pix_fmt","yuv420p","-an",p])
s,err=open_src(p,token)
if s:
    j,_=export(s["id"],token,1000000,4000000)
    st=streams(j["result"]["outputPath"]) if j and j["status"]=="done" else []
    results.append(("no-audio video", j["status"] if j else "n/a", "%d streams" % len(st)))
else:
    results.append(("no-audio video","open-failed",str(err)[:60]))

p=os.path.join(D,"n_multi.mkv")
subprocess.run([FF,"-hide_banner","-loglevel","error","-y","-f","lavfi","-i","testsrc2=size=320x180:rate=30","-f","lavfi","-i","sine=frequency=440:duration=6","-f","lavfi","-i","sine=frequency=880:duration=6","-t","6","-map","0:v","-map","1:a","-map","2:a","-c:v","libx264","-pix_fmt","yuv420p","-c:a","aac",p])
s,err=open_src(p,token)
if s:
    j,_=export(s["id"],token,1000000,4000000)
    out=(j or {}).get("result",{}).get("outputPath")
    st=streams(out) if j and j["status"]=="done" else []
    results.append(("multi-audio mkv", j["status"] if j else "n/a", "video=%d audio=%d" % (len([x for x in st if x['codec_type']=='video']), len([x for x in st if x['codec_type']=='audio']))))

p=os.path.join(D,"n_vfr.mp4")
subprocess.run([FF,"-hide_banner","-loglevel","error","-y","-f","lavfi","-i","testsrc2=size=320x180:rate=30","-t","6","-c:v","libx264","-pix_fmt","yuv420p","-fps_mode","vfr","-vf","fps=30",p])
s,err=open_src(p,token)
if s:
    j,_=export(s["id"],token,1000000,4000000)
    out=(j or {}).get("result",{}).get("outputPath")
    results.append(("vfr source", j["status"] if j else "n/a", "dur=%s" % (dur(out) if out else None)))

sub=os.path.join(D,"日本語 フォルダ","深い 階層")
os.makedirs(sub, exist_ok=True)
p=os.path.join(sub,"テスト 動画.mp4")
subprocess.run([FF,"-hide_banner","-loglevel","error","-y","-f","lavfi","-i","testsrc2=size=320x180:rate=30","-t","4","-c:v","libx264","-pix_fmt","yuv420p",p])
s,err=open_src(p,token)
if s:
    j,_=export(s["id"],token,500000,3000000)
    out=(j or {}).get("result",{}).get("outputPath")
    results.append(("non-ascii path", j["status"] if j else "n/a", "dur=%s exists=%s" % (dur(out) if out else None, os.path.exists(out) if out else False)))

p=os.path.join(D,"n_pcm.mkv")
subprocess.run([FF,"-hide_banner","-loglevel","error","-y","-f","lavfi","-i","testsrc2=size=320x180:rate=30","-f","lavfi","-i","sine=frequency=440:duration=6","-t","6","-c:v","libx264","-pix_fmt","yuv420p","-c:a","pcm_s16le",p])
s,err=open_src(p,token)
if s:
    j,_=export(s["id"],token,1000000,4000000,{"container":"matroska"})
    r=(j or {}).get("result",{})
    results.append(("container=matroska", j["status"] if j else "n/a", "container=%s ext=%s" % (r.get("container"), os.path.splitext(r.get("outputPath",""))[1] if r.get("outputPath") else None)))
    c2,res2=call("POST","/api/exports",{"sourceId":s["id"],"startUs":1000000,"endUs":4000000,"mode":"lossless","options":{"container":"mp4","outputPath":D}},token)
    results.append(("container=mp4 on pcm mkv", "http %d" % c2, str(res2)[:90]))
    c3,res3=call("POST","/api/exports",{"sourceId":s["id"],"startUs":1000000,"endUs":4000000,"mode":"lossless","options":{"container":"banana","outputPath":D}},token)
    results.append(("container=banana", "http %d" % c3, str(res3)[:90]))
    multi=os.path.join(D,"n_multi.mkv")
    sm,errm=open_src(multi,token)
    if sm:
        c4,res4=call("POST","/api/exports",{"sourceId":sm["id"],"startUs":1000000,"endUs":4000000,"mode":"lossless","options":{"container":"mp3","outputPath":D}},token)
        results.append(("multi-audio to mp3", "http %d" % c4, str(res4)[:90]))

stale=os.path.join(D,"cleanup.trim-00h00m00s000-00h00m01s000.part.mp4")
stale_new=os.path.join(D,"IMG_1234_切出0s-2s_無変換.part.mp4")
old=time.time()-7200
for sf in (stale,stale_new):
    open(sf,"wb").write(b"x")
    os.utime(sf,(old,old))
s2,err=open_src(os.path.join(D,"src_h264.mp4"),token)
if s2:
    j,_=export(s2["id"],token,2000000,3000000)
    gone = (not os.path.exists(stale)) and (not os.path.exists(stale_new))
    results.append(("stale .part cleanup", j["status"] if j else "n/a", "removed=%s" % gone))

bad=os.path.join(D,"n_broken.mp4")
open(bad,"wb").write(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 200)
c,res=call("POST","/api/sources/open",{"path":bad},token)
results.append(("damaged file", "http %d" % c, str(res)[:80] if c!=200 else "accepted"))

ok_count = 0
for name,status,detail in results:
    good = ("done" in status) or (status.startswith("http 400"))
    ok_count += 1 if good else 0
    print("%-26s %-14s %-12s %s" % (name, status, "OK" if good else "FAIL", detail))
print("RESULT:", "OK" if ok_count == len(results) else "FAIL(%d/%d)" % (ok_count, len(results)))
sys.exit(0 if ok_count == len(results) else 1)
