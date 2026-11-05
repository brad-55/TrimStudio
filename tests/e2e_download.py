import json, os, shutil, urllib.request, urllib.error
BASE="http://127.0.0.1:8003"
D=r"L:\dev\Trim\data\test"

def status_of(url):
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()

fails=0
def check(label, cond, detail=""):
    global fails
    print(("OK  " if cond else "FAIL") + " " + label + ("" if cond else "  " + str(detail)[:120]))
    if not cond: fails += 1

plain=os.path.join(D,"src_h264.mp4")
url=BASE+"/api/fs/download?path="+urllib.parse.quote(plain)
st,hd,body=status_of(url)
check("download a normal file", st==200 and len(body)==os.path.getsize(plain), "%s len=%s" % (st, len(body)))
check("attachment disposition", "attachment" in (hd.get("content-disposition","").lower()), hd.get("content-disposition"))
check("filename in disposition", "src_h264" in hd.get("content-disposition",""), hd.get("content-disposition"))

jp=os.path.join(D,"テスト_切出0s-1s_無変換.mp4")
shutil.copyfile(os.path.join(D,"a.mp3") if os.path.exists(os.path.join(D,"a.mp3")) else plain, jp)
st,hd,body=status_of(BASE+"/api/fs/download?path="+urllib.parse.quote(jp))
check("japanese filename download", st==200 and len(body)==os.path.getsize(jp), st)
cd=hd.get("content-disposition","")
check("japanese filename encoded", "filename*=utf-8''" in cd.lower(), cd)

st,_,_=status_of(BASE+"/api/fs/download")
check("missing path -> 400", st==400, st)
st,_,_=status_of(BASE+"/api/fs/download?path="+urllib.parse.quote(r"Q:\nope.mp4"))
check("outside root -> 400", st==400, st)
st,_,_=status_of(BASE+"/api/fs/download?path="+urllib.parse.quote(os.path.join(D,"does_not_exist.mp4")))
check("missing file -> 404", st==404, st)
st,_,_=status_of(BASE+"/api/fs/download?path="+urllib.parse.quote(D))
check("directory without media ext -> 400", st==400, st)
fake=os.path.join(D,"fake_dir.mp4")
os.makedirs(fake, exist_ok=True)
st,_,_=status_of(BASE+"/api/fs/download?path="+urllib.parse.quote(fake))
check("media-named directory -> 404", st==404, st)
try: os.rmdir(fake)
except OSError: pass

txt=os.path.join(D,"secret_notes.txt")
open(txt,"w",encoding="utf-8").write("not media")
st,_,body=status_of(BASE+"/api/fs/download?path="+urllib.parse.quote(txt))
check("non-media (.txt) -> 400", st==400 and b"not media" not in body, st)
try: os.remove(txt)
except OSError: pass

try: os.remove(jp)
except OSError: pass
print("RESULT:", "OK" if fails==0 else "FAIL(%d)"%fails)
