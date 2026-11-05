import glob, json, os, subprocess, time, urllib.request, urllib.error
BASE="http://127.0.0.1:8003"
D=r"L:\dev\Trim\data\test"
SRC=os.path.join(D,"src_h264.mp4")
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

def wait(jid, timeout=900):
    t0=time.time()
    while time.time()-t0 < timeout:
        c,jr=call("GET","/api/jobs/%s"%jid); j=jr["job"]
        if j["status"] in ("done","error","cancelled"): return j
        time.sleep(0.4)
    return j

def open_src(p, token):
    c,res=call("POST","/api/sources/open",{"path":p},token)
    if c!=200 or not isinstance(res,dict) or "source" not in res: return None
    s=res["source"]
    for _ in range(180):
        c,kf=call("GET","/api/sources/%s/keyframes"%s["id"])
        if kf.get("state") in ("ready","error"): break
        time.sleep(0.4)
    return s

c,tok=call("GET","/api/token"); token=tok["token"]
fails=0
sa=open_src(SRC,token); sb=open_src(os.path.join(D,"src_h265.mkv"),token)

# 1) load another video while an export is running
c,job=call("POST","/api/exports",{"sourceId":sa["id"],"startUs":0,"endUs":sa["durationUs"],"mode":"reencode","options":{"outputPath":D,"encoder":"libx265"}},token)
jid=job["jobId"]
time.sleep(1.5)
c,res=call("POST","/api/sources/open",{"path":os.path.join(D,"src_h265.mkv")},token)   # load another video mid-export
loaded_ok = c==200 and "source" in res
j=wait(jid)
s1_ok = loaded_ok and j["status"]=="done"
print("1) 別動画の読み込み中も書き出し継続: loaded=%s job=%s %s" % (loaded_ok, j["status"], "OK" if s1_ok else "FAIL"))
fails += 0 if s1_ok else 1

# 2) queue a second export on the same source (per-source lock serializes)
c,jobA=call("POST","/api/exports",{"sourceId":sa["id"],"startUs":0,"endUs":sa["durationUs"],"mode":"reencode","options":{"outputPath":D,"encoder":"libx265"}},token)
c,jobB=call("POST","/api/exports",{"sourceId":sa["id"],"startUs":0,"endUs":3000000,"mode":"lossless","options":{"outputPath":D}},token)
c,br=call("GET","/api/jobs/%s"%jobB["jobId"])
queued_at_create = (br.get("job") or {}).get("status") == "queued"
ja=wait(jobA["jobId"]); jb=wait(jobB["jobId"])
serial_ok = queued_at_create and ja["status"]=="done" and jb["status"]=="done"
print("2) 同一ソースへの連続書き出し: B作成直後=%s A=%s B=%s %s" % (queued_at_create, ja["status"], jb["status"], "OK" if serial_ok else "FAIL"))
fails += 0 if serial_ok else 1

# 3) browser closed: create the job and never watch it
c,jobC=call("POST","/api/exports",{"sourceId":sa["id"],"startUs":6000000,"endUs":9000000,"mode":"lossless","options":{"outputPath":D}},token)
jc=wait(jobC["jobId"])
out=(jc.get("result") or {}).get("outputPath")
s3_ok = jc["status"]=="done" and out and os.path.exists(out)
print("3) ブラウザを閉じてもサーバ側で完了: status=%s exists=%s %s" % (jc["status"], bool(out and os.path.exists(out)), "OK" if s3_ok else "FAIL"))
fails += 0 if s3_ok else 1

# 4) cancel mid-export (use the large source so the copy takes a while; SKIP if absent)
if not os.path.exists(BIG):
    print("4) 停止: SKIP (large source not present)")
else:
    sbig=open_src(BIG,token)
    c,jobD=call("POST","/api/exports",{"sourceId":sbig["id"],"startUs":0,"endUs":120000000,"mode":"lossless","options":{"outputPath":D}},token)
    jidD=jobD["jobId"]
    running=False
    for _ in range(40):
        c,jr2=call("GET","/api/jobs/%s"%jidD); st=jr2["job"]["status"]
        if st=="running": running=True; break
        if st in ("done","error","cancelled"): break
        time.sleep(0.1)
    if not running:
        jd=wait(jidD)
        print("4) 停止: SKIP (ジョブが先に終了: %s)" % jd["status"])
    else:
        c,_=call("POST","/api/jobs/%s/cancel"%jidD,None,token)
        jd=wait(jidD)
        parts=glob.glob(os.path.join(D,"*.part*"))
        s4_ok = jd["status"]=="cancelled" and not parts
        print("4) 停止: status=%s 残part=%d %s" % (jd["status"], len(parts), "OK" if s4_ok else "FAIL"))
        fails += 0 if s4_ok else 1

# 5) default output dir unwritable -> fallback with warning
if os.path.exists(BIG):
    sbig=open_src(BIG,token)
    c,jobE=call("POST","/api/exports",{"sourceId":sbig["id"],"startUs":1000000,"endUs":3000000,"mode":"lossless","options":{}},token)
    je=wait(jobE["jobId"])
    r=je.get("result") or {}
    out=r.get("outputPath","")
    warn=r.get("warnings") or []
    s5_ok = je["status"]=="done" and out.startswith(r"L:\dev\Trim\data\exports") and any("変更" in w for w in warn)
    print("5) 既定出力先が不可書 -> フォールバック: status=%s out=%s warn=%s %s" % (je["status"], os.path.basename(out), bool(warn), "OK" if s5_ok else "FAIL"))
    fails += 0 if s5_ok else 1
else:
    print("5) SKIP (big source not present)")

print("RESULT:", "OK" if fails==0 else "FAIL(%d)"%fails)
