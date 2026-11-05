import sqlite3, sys, time
sys.path.insert(0, r"L:\dev\Trim")
from app import ffmpeg_tools
c = sqlite3.connect(r"L:\dev\Trim\data\trim.db")
c.row_factory = sqlite3.Row
row = c.execute("select * from sources where name like 'VID_20261103_114920%' order by size desc limit 1").fetchone()
if not row:
    print("no row"); raise SystemExit
src = dict(row)
fp = r"L:\dev\Trim\tools\ffmpeg\bin\ffprobe.exe"
size = src.get("size") or 0
print("file", src["name"], round(size / 1048576.0, 1), "MB", "spec", src.get("video_spec"))
t0 = time.time()
kf = ffmpeg_tools.keyframes(fp, src["path"], src.get("video_spec") or "v:0", timeout=1800)
el = time.time() - t0
print("keyframes=%d elapsed=%.1fs MB_per_s=%.1f" % (len(kf), el, (size / 1048576.0) / max(el, 0.001)))
