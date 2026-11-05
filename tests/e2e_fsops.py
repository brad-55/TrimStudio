import json, os, shutil, time, urllib.request, urllib.error
BASE="http://127.0.0.1:8003"
D=r"L:\dev\Trim\data\test"
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
        time.sleep(0.3)
    return j

c,tok=call("GET","/api/token"); token=tok["token"]
fails=0
src_dir=os.path.join(D,"fsops_src"); dst_dir=os.path.join(D,"fsops_dst")
for p in (src_dir,dst_dir):
    shutil.rmtree(p, ignore_errors=True)
    os.makedirs(p, exist_ok=True)
f1=os.path.join(src_dir,"a.bin"); open(f1,"wb").write(b"x"*2_000_000)
f2=os.path.join(src_dir,"b.bin"); open(f2,"wb").write(b"y"*1_000_000)
sub=os.path.join(src_dir,"sub"); os.makedirs(sub, exist_ok=True); open(os.path.join(sub,"c.bin"),"wb").write(b"z"*500_000)

# 1) copy file
c,j=call("POST","/api/fs/copy",{"source":f1,"destination":dst_dir},token)
w=wait(j["jobId"]); out=(w.get("result") or {}).get("outputPath")
ok1 = c==200 and w["status"]=="done" and out and os.path.exists(out) and os.path.getsize(out)==2_000_000 and os.path.exists(f1)
print("1) copy file: status=%s size=%s src_intact=%s %s" % (w["status"], os.path.getsize(out) if out and os.path.exists(out) else None, os.path.exists(f1), "OK" if ok1 else "FAIL")); fails+=0 if ok1 else 1

# 2) move file
c,j=call("POST","/api/fs/move",{"source":f2,"destination":dst_dir},token)
w=wait(j["jobId"]); out2=(w.get("result") or {}).get("outputPath")
ok2 = c==200 and w["status"]=="done" and out2 and os.path.exists(out2) and not os.path.exists(f2)
print("2) move file: status=%s src_gone=%s %s" % (w["status"], not os.path.exists(f2), "OK" if ok2 else "FAIL")); fails+=0 if ok2 else 1

# 3) collision on copy
open(f1,"wb").write(b"x"*2_000_000)
c,j=call("POST","/api/fs/copy",{"source":f1,"destination":dst_dir},token)
w=wait(j["jobId"]); out3=(w.get("result") or {}).get("outputPath")
ok3 = w["status"]=="done" and out3 and out3!=out and os.path.exists(out3) and os.path.exists(out)
print("3) collision: %s vs %s both_exist=%s %s" % (os.path.basename(out or ""), os.path.basename(out3 or ""), bool(out and out3 and os.path.exists(out) and os.path.exists(out3)), "OK" if ok3 else "FAIL")); fails+=0 if ok3 else 1

# 4) copy folder
c,j=call("POST","/api/fs/copy",{"source":sub,"destination":dst_dir},token)
w=wait(j["jobId"]); out4=(w.get("result") or {}).get("outputPath")
ok4 = w["status"]=="done" and out4 and os.path.exists(os.path.join(out4,"c.bin"))
print("4) copy folder: status=%s nested=%s %s" % (w["status"], bool(out4 and os.path.exists(os.path.join(out4,"c.bin"))), "OK" if ok4 else "FAIL")); fails+=0 if ok4 else 1

# 5) containment / validation
c,b=call("POST","/api/fs/copy",{"source":f1,"destination":r"Q:\nowhere"},token)
ok5 = c==400
print("5) outside root -> %s %s" % (c, "OK" if ok5 else "FAIL")); fails+=0 if ok5 else 1
c,b=call("POST","/api/fs/copy",{"source":os.path.join(D,"nope.bin"),"destination":dst_dir},token)
ok5b = c==404
print("5b) missing source -> %s %s" % (c, "OK" if ok5b else "FAIL")); fails+=0 if ok5b else 1
c,b=call("POST","/api/fs/move",{"source":os.path.join(dst_dir,"a.bin"),"destination":dst_dir},token)
ok5d = c==400
print("5d) move into same folder -> %s %s" % (c, "OK" if ok5d else "FAIL")); fails+=0 if ok5d else 1
c,b=call("POST","/api/fs/copy",{"source":src_dir,"destination":sub},token)
ok5e = c==400
print("5e) copy folder into itself -> %s %s" % (c, "OK" if ok5e else "FAIL")); fails+=0 if ok5e else 1

c,b=call("POST","/api/fs/copy",{"destination":dst_dir},token)
ok5c = c==400
print("5c) missing field -> %s %s" % (c, "OK" if ok5c else "FAIL")); fails+=0 if ok5c else 1

# 6) cancel a large copy
if os.path.exists(BIG):
    c,j=call("POST","/api/fs/copy",{"source":BIG,"destination":dst_dir},token)
    time.sleep(2.0)
    call("POST","/api/jobs/%s/cancel"%j["jobId"],None,token)
    w=wait(j["jobId"])
    parts=[p for p in os.listdir(dst_dir) if p.endswith(".part")]
    ok6 = w["status"]=="cancelled" and not parts
    print("6) cancel copy: status=%s parts=%d %s" % (w["status"], len(parts), "OK" if ok6 else "FAIL")); fails+=0 if ok6 else 1
else:
    print("6) cancel copy: SKIP")

# 7) job payload carries sourceName
c,res=call("POST","/api/sources/open",{"path":os.path.join(D,"src_h264.mp4")},token)
sid=res["source"]["id"]
for _ in range(60):
    c,kf=call("GET","/api/sources/%s/keyframes"%sid)
    if kf.get("state") in ("ready","error"): break
    time.sleep(0.4)
c,j=call("POST","/api/exports",{"sourceId":sid,"startUs":0,"endUs":2000000,"mode":"lossless","options":{"outputPath":D}},token)
w=wait(j["jobId"])
c,jr=call("GET","/api/jobs/%s"%j["jobId"])
ok7 = (jr.get("job") or {}).get("sourceName")=="src_h264.mp4"
print("7) sourceName in job: %s %s" % ((jr.get("job") or {}).get("sourceName"), "OK" if ok7 else "FAIL")); fails+=0 if ok7 else 1

print("RESULT:", "OK" if fails==0 else "FAIL(%d)"%fails)
