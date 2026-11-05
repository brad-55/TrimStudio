import json, os, subprocess, time, urllib.request, urllib.error
BASE="http://127.0.0.1:8003"
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
    for _ in range(1200):
        c,jr=call("GET","/api/jobs/%s"%jid); j=jr["job"]
        if j["status"] in ("done","error","cancelled"): return j
        time.sleep(0.4)
    return j

def probe_streams(p):
    q=subprocess.run([FP,"-v","error","-show_streams","-show_format","-of","json",p],capture_output=True,text=True,encoding="utf-8",errors="replace")
    return json.loads(q.stdout or "{}")

c,tok=call("GET","/api/token"); token=tok["token"]
fails=0

# metadata
c,res=call("POST","/api/sources/open",{"path":SRC},token)
s=res["source"]
for _ in range(120):
    c,kf=call("GET","/api/sources/%s/keyframes"%s["id"])
    if kf.get("state")=="ready": break
    time.sleep(0.4)
meta_ok = bool(s.get("bitRate")) and bool(s.get("videoBitRate")) and bool(s.get("audioBitRate")) and bool((s.get("meta") or {}).get("tags"))
streams=s.get("streams") or []
detail_ok = any(st.get("bit_rate") and st.get("codec_long_name") for st in streams)
print("metadata bitRate=%s v=%s a=%s tags=%s detail=%s %s" % (s.get("bitRate"), s.get("videoBitRate"), s.get("audioBitRate"), len((s.get("meta") or {}).get("tags") or {}), detail_ok, "OK" if (meta_ok and detail_ok) else "FAIL"))
fails += 0 if (meta_ok and detail_ok) else 1
sid=s["id"]

# mkdir
newdir=os.path.join(D,"新規 出力先")
if os.path.isdir(newdir):
    os.rmdir(newdir)
c,res=call("POST","/api/fs/mkdir",{"path":newdir},token)
mk_ok = c==200 and os.path.isdir(newdir)
c2,res2=call("POST","/api/fs/mkdir",{"path":r"C:\Windows\TrimTest"},token)
mk_block = c2==400
print("mkdir %s exists=%s / outside %s %s" % (c, os.path.isdir(newdir), c2, "OK" if (mk_ok and mk_block) else "FAIL"))
fails += 0 if (mk_ok and mk_block) else 1

# reencode with explicit bitrates
c,job=call("POST","/api/exports",{"sourceId":sid,"startUs":2000000,"endUs":6000000,"mode":"reencode",
    "options":{"outputPath":D,"videoBitrate":1500,"audioBitrate":64,"audioReencode":True}},token)
j=wait(job["jobId"])
if j["status"]=="done":
    d=probe_streams(j["result"]["outputPath"])
    fmt=int(d["format"]["bit_rate"]); v=[x for x in d["streams"] if x["codec_type"]=="video"][0]; a=[x for x in d["streams"] if x["codec_type"]=="audio"][0]
    vb=int(v.get("bit_rate") or 0); ab=int(a.get("bit_rate") or 0)
    ok = 1100000 <= vb <= 2100000 and 40000 <= ab <= 96000
    print("reencode vbr=1500k abr=64k -> video=%dk audio=%dk total=%dk %s" % (vb/1000, ab/1000, fmt/1000, "OK" if ok else "FAIL"))
    fails += 0 if ok else 1
else:
    print("reencode failed", j["status"], str(j.get("error"))[:100]); fails+=1

# reencode without bitrate: audio follows source (69k)
c,job=call("POST","/api/exports",{"sourceId":sid,"startUs":2000000,"endUs":6000000,"mode":"reencode",
    "options":{"outputPath":D,"audioReencode":True}},token)
j=wait(job["jobId"])
if j["status"]=="done":
    d=probe_streams(j["result"]["outputPath"])
    a=[x for x in d["streams"] if x["codec_type"]=="audio"][0]
    ab=int(a.get("bit_rate") or 0)
    ok = 50000 <= ab <= 100000
    print("reencode default audio follows source -> audio=%dk %s" % (ab/1000, "OK" if ok else "FAIL"))
    fails += 0 if ok else 1
else:
    print("reencode default failed", j["status"], str(j.get("error"))[:100]); fails+=1

# audio-only reencode must carry the source audio bitrate when unspecified
import sqlite3
SRC2=os.path.join(D,"hi320.mp3")
subprocess.run([r"L:\dev\Trim\tools\ffmpeg\bin\ffmpeg.exe","-hide_banner","-loglevel","error","-y","-f","lavfi","-i","sine=frequency=440:duration=6","-c:a","libmp3lame","-b:a","320k",SRC2])
c,res=call("POST","/api/sources/open",{"path":SRC2},token)
s2=res["source"]
for _ in range(120):
    c,kf=call("GET","/api/sources/%s/keyframes"%s2["id"])
    if kf.get("state")=="ready": break
    time.sleep(0.4)
src_ab=int(s2.get("audioBitRate") or 0)
c,job=call("POST","/api/exports",{"sourceId":s2["id"],"startUs":1000000,"endUs":4000000,"mode":"reencode","options":{"outputPath":D}},token)
j=wait(job["jobId"])
if j["status"]=="done":
    d=probe_streams(j["result"]["outputPath"]); a=[x for x in d["streams"] if x["codec_type"]=="audio"][0]
    ab=int(a.get("bit_rate") or 0)
    ok = src_ab>0 and abs(ab-src_ab) <= src_ab*0.25
    print("audio-only reencode default: src=%dk out=%dk %s" % (src_ab/1000, ab/1000, "OK" if ok else "FAIL"))
    fails += 0 if ok else 1
else:
    print("audio-only reencode failed", j["status"], str(j.get("error"))[:80]); fails+=1

c,job=call("POST","/api/exports",{"sourceId":s2["id"],"startUs":1000000,"endUs":4000000,"mode":"reencode","options":{"outputPath":D,"audioBitrate":96}},token)
j=wait(job["jobId"])
if j["status"]=="done":
    d=probe_streams(j["result"]["outputPath"]); a=[x for x in d["streams"] if x["codec_type"]=="audio"][0]
    ab=int(a.get("bit_rate") or 0)
    ok = 80000 <= ab <= 112000
    print("audio-only reencode explicit 96k -> %dk %s" % (ab/1000, "OK" if ok else "FAIL"))
    fails += 0 if ok else 1
else:
    print("audio-only explicit failed", j["status"], str(j.get("error"))[:80]); fails+=1

# invalid bitrate -> 400
c_bad1,_=call("POST","/api/exports",{"sourceId":sid,"startUs":1000000,"endUs":4000000,"mode":"reencode","options":{"outputPath":D,"videoBitrate":"abc"}},token)
c_bad2,_=call("POST","/api/exports",{"sourceId":sid,"startUs":1000000,"endUs":4000000,"mode":"reencode","options":{"outputPath":D,"videoBitrate":-5}},token)
bad_ok = c_bad1==400 and c_bad2==400
print("invalid bitrate -> %d/%d %s" % (c_bad1, c_bad2, "OK" if bad_ok else "FAIL"))
fails += 0 if bad_ok else 1

# mkdir outside allowed roots
c3,r3=call("POST","/api/fs/mkdir",{"path":r"Q:\TrimTest"},token)
c4,r4=call("POST","/api/fs/mkdir",{"path":r"\\server\share\TrimTest"},token)
c5,r5=call("POST","/api/fs/mkdir",{"path":r"L:\dev\Trim\data\test\CON"},token)
out_ok = c3==400 and c4==400 and c5==200 and os.path.isdir(os.path.join(D,"_CON"))
print("mkdir outside(Q:/UNC) -> %d/%d reserved CON -> %d as _CON=%s %s" % (c3, c4, c5, os.path.isdir(os.path.join(D,"_CON")), "OK" if out_ok else "FAIL"))
fails += 0 if out_ok else 1

# metadata migration: clear meta_json, reopen, expect refresh and index preserved
db=sqlite3.connect(r"L:\dev\Trim\data\trim.db", timeout=30)
before=db.execute("select index_state from sources where id=?", (sid,)).fetchone()[0]
db.execute("update sources set meta_json=NULL where id=?", (sid,)); db.commit(); db.close()
c,res=call("POST","/api/sources/open",{"path":SRC},token)
s3=res["source"]
after_state=s3.get("indexState")
mig_ok = bool((s3.get("meta") or {}).get("format_name")) and after_state==before and bool(s3.get("bitRate"))
print("meta migration: meta=%s state=%s(%s) bitRate=%s %s" % (bool((s3.get("meta") or {}).get("format_name")), after_state, before, s3.get("bitRate"), "OK" if mig_ok else "FAIL"))
fails += 0 if mig_ok else 1

# dotted folder name preserved, empty name rejected
dotted=os.path.join(D,"2026.11.05 backup")
if os.path.isdir(dotted):
    os.rmdir(dotted)
c6,r6=call("POST","/api/fs/mkdir",{"path":r"L:\dev\Trim\data\test\2026.11.05 backup"},token)
c7,r7=call("POST","/api/fs/mkdir",{"path":"L:\\"},token)
dot_ok = c6==200 and os.path.isdir(dotted) and c7==400
print("mkdir dotted=%d exists=%s empty=%d %s" % (c6, os.path.isdir(dotted), c7, "OK" if dot_ok else "FAIL"))
fails += 0 if dot_ok else 1

# avi reencode audio codec, asf multichannel rejection
av=os.path.join(D,"re_avi.avi")
subprocess.run([r"L:\dev\Trim\tools\ffmpeg\bin\ffmpeg.exe","-hide_banner","-loglevel","error","-y","-f","lavfi","-i","testsrc2=size=320x180:rate=25","-f","lavfi","-i","sine=frequency=440:duration=6","-t","6","-c:v","msmpeg4","-c:a","pcm_s16le",av])
c,res=call("POST","/api/sources/open",{"path":av},token)
sa=res["source"]
for _ in range(120):
    c,kf=call("GET","/api/sources/%s/keyframes"%sa["id"])
    if kf.get("state")=="ready": break
    time.sleep(0.4)
c,job=call("POST","/api/exports",{"sourceId":sa["id"],"startUs":1000000,"endUs":4000000,"mode":"reencode","options":{"outputPath":D,"audioReencode":True}},token)
j=wait(job["jobId"])
avi_ok=False
if j["status"]=="done":
    d=probe_streams(j["result"]["outputPath"]); a=[x for x in d["streams"] if x["codec_type"]=="audio"]
    avi_ok = bool(a) and a[0]["codec_name"]=="mp3"
    print("avi reencode audio codec=%s %s" % (a[0]["codec_name"] if a else "none", "OK" if avi_ok else "FAIL"))
else:
    print("avi reencode failed", j["status"], str(j.get("error"))[:80])
fails += 0 if avi_ok else 1

mc=os.path.join(D,"re_51.wav")
subprocess.run([r"L:\dev\Trim\tools\ffmpeg\bin\ffmpeg.exe","-hide_banner","-loglevel","error","-y","-f","lavfi","-i","sine=frequency=440:duration=6","-af","pan=5.1|FL=c0|FR=c0|FC=c0|LFE=c0|BL=c0|BR=c0","-c:a","pcm_s16le",mc])
c,res=call("POST","/api/sources/open",{"path":mc},token)
sm=res["source"]
for _ in range(120):
    c,kf=call("GET","/api/sources/%s/keyframes"%sm["id"])
    if kf.get("state")=="ready": break
    time.sleep(0.4)
c8,r8=call("POST","/api/exports",{"sourceId":sm["id"],"startUs":1000000,"endUs":4000000,"mode":"reencode","options":{"outputPath":D,"container":"asf","audioReencode":True}},token)
c9,r9=call("POST","/api/exports",{"sourceId":sm["id"],"startUs":1000000,"endUs":4000000,"mode":"reencode","options":{"outputPath":D,"container":"mpeg","audioReencode":True}},token)
mc_ok=c8==400 and c9==400 and (sm.get("kind")=="audio")
print("6ch audio-only: asf -> %d, mpeg -> %d %s" % (c8, c9, "OK" if mc_ok else "FAIL"))
fails += 0 if mc_ok else 1

# 6ch audio into containers whose re-encode codec is 2ch only (auto-selected container)
for name, vcodec, acodec, ext in (("re6.avi", "msmpeg4", "pcm_s16le", "avi"), ("re6.mpg", "mpeg2video", "ac3", "mpg")):
    p6=os.path.join(D,name)
    subprocess.run([r"L:\dev\Trim\tools\ffmpeg\bin\ffmpeg.exe","-hide_banner","-loglevel","error","-y",
                    "-f","lavfi","-i","testsrc2=size=320x180:rate=25","-f","lavfi","-i","sine=frequency=440:duration=4",
                    "-t","4","-af","pan=5.1|FL=c0|FR=c0|FC=c0|LFE=c0|BL=c0|BR=c0","-c:v",vcodec,"-c:a",acodec,p6])
    c,res=call("POST","/api/sources/open",{"path":p6},token)
    if c!=200:
        print("6ch %s open failed %d" % (ext,c)); fails+=1; continue
    s6=res["source"]
    for _ in range(120):
        c,kf=call("GET","/api/sources/%s/keyframes"%s6["id"])
        if kf.get("state")=="ready": break
        time.sleep(0.4)
    cg,rg=call("POST","/api/exports",{"sourceId":s6["id"],"startUs":500000,"endUs":2500000,"mode":"reencode",
        "options":{"outputPath":D,"audioReencode":True}},token)
    ok6=cg==400
    print("6ch auto container %s -> %d %s" % (ext, cg, "OK" if ok6 else "FAIL"))
    fails += 0 if ok6 else 1

# invalid request bodies and non-integer times
c10,_=call("POST","/api/exports",{"sourceId":sid,"startUs":"abc","endUs":4000000,"mode":"lossless","options":{"outputPath":D}},token)
req=urllib.request.Request(BASE+"/api/sources/open", data=b"{not json", headers={"Content-Type":"application/json","X-Trim-Token":token}, method="POST")
try:
    urllib.request.urlopen(req,timeout=30); c11=200
except urllib.error.HTTPError as e: c11=e.code
bad_ok = c10==400 and c11==400
print("invalid request: startUs abc -> %d, malformed JSON -> %d %s" % (c10, c11, "OK" if bad_ok else "FAIL"))
fails += 0 if bad_ok else 1

print("RESULT:", "OK" if fails==0 else "FAIL(%d)"%fails)
