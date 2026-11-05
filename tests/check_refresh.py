import json, urllib.request
BASE="http://127.0.0.1:8003"
def call(method, path, body=None, token=None):
    data=None; h={}
    if body is not None: data=json.dumps(body).encode(); h["Content-Type"]="application/json"
    if token: h["X-Trim-Token"]=token
    req=urllib.request.Request(BASE+path,data=data,headers=h,method=method)
    with urllib.request.urlopen(req,timeout=300) as r: return json.loads(r.read().decode())
tok=call("GET","/api/token")["token"]
p=r"L:\ImageApp\20261103_池尻大橋\mp4\VID_20261103_114920_003.mp4"
res=call("POST","/api/sources/open",{"path":p},tok)
s=res["source"]
print("kind", s.get("kind"), "bitRate", s.get("bitRate"), "video", s.get("videoBitRate"), "audio", s.get("audioBitRate"))
print("meta tags", list((s.get("meta") or {}).get("tags") or {})[:4], "streams", len(s.get("streams") or []))
for st in (s.get("streams") or [])[:2]:
    print(" #%s %s %s bit_rate=%s profile=%s color=%s/%s/%s" % (st.get("index"), st.get("type"), st.get("codec"), st.get("bit_rate"), st.get("profile"), st.get("color_space"), st.get("color_transfer"), st.get("color_primaries")))
