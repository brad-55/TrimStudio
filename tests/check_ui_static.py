"""Static regression guards for the UI files (no browser needed)."""
import io, re, sys

ROOT = r"L:\dev\Trim"
WEB_HTML = ROOT + r"\web\index.html"
WEB_CSS = ROOT + r"\web\style.css"
WEB_JS = ROOT + r"\web\app.js"
QWEN = ROOT + r"\web-qwen\index.html"

fails = 0

def check(label, cond, detail=""):
    global fails
    print(("OK  " if cond else "FAIL") + " " + label + ("" if cond else "  " + detail))
    if not cond:
        fails += 1

def read(path):
    return io.open(path, encoding="utf-8").read()

web_css = read(WEB_CSS)
web_html = read(WEB_HTML)
web_js = read(WEB_JS)
qwen = read(QWEN)
exp = read(ROOT + r"\app\exports.py")
main_py = read(ROOT + r"\app\main.py")

# 1) [hidden] must beat class display rules (this bug froze both UIs behind the spinner)
check("web css: [hidden] guard", re.search(r"\[hidden\]\s*\{\s*display:\s*none\s*!important", web_css) is not None)
check("qwen: [hidden] guard", re.search(r"\[hidden\]\s*\{\s*display:\s*none\s*!important", qwen) is not None)

# 2) the loading overlay starts hidden and offers a manual escape
m = re.search(r'<div id="spinner"[^>]*>', web_html)
check("web: overlay has hidden attr", bool(m) and "hidden" in m.group(0), m.group(0) if m else "not found")
check("web: escape button", 'id="spinEscape"' in web_html and "releaseSpinner" in web_js)
check("qwen: overlay has hidden attr", 'id="spinOverlay" class="spin-overlay" hidden' in qwen)
check("qwen: escape button", 'id="spinEscape"' in qwen and "releaseSpinner" in qwen)
check("web: escape button starts hidden", re.search(r'id="spinEscape"[^>]*hidden', web_html) is not None)
check("qwen: escape button starts hidden", re.search(r'id="spinEscape"[^>]*hidden', qwen) is not None)
check("web: keyframes call has a long timeout", "/keyframes\", null, false, 180000" in web_js)
check("qwen: keyframes call has a long timeout", '/keyframes",{timeoutMs:180000' in qwen)

# 3) API calls can never hang forever
check("web: AbortController timeout", "AbortController" in web_js and "API_TIMEOUT" in web_js and "abortTimer" in web_js)
check("qwen: AbortController timeout", "AbortController" in qwen and "API_TIMEOUT" in qwen and "abortTimer" in qwen)
check("web: upload gets a long timeout", re.search(r"/api/sources/upload\", form, true, \d+", web_js) is not None)
check("qwen: upload gets a long timeout", "timeoutMs:1800000" in qwen)

# 4) the stuck indicator appears before the request would time out
check("web: stuck watchdog", "STUCK_AFTER" in web_js and "armStuck" in web_js)
check("qwen: stuck watchdog", "STUCK_AFTER" in qwen and "armStuck" in qwen)
check("web: timeout smaller than stuck delay is false",
      int(re.search(r"API_TIMEOUT = (\d+)", web_js).group(1)) > int(re.search(r"STUCK_AFTER = (\d+)", web_js).group(1)))
check("qwen: stuck delay before timeout",
      int(re.search(r"API_TIMEOUT=(\d+)", qwen).group(1)) > int(re.search(r"STUCK_AFTER=(\d+)", qwen).group(1)))

# 5) the explorer keeps its own scroll and can switch drives (Qwen)
check("qwen: explorer scroll containment", "overscroll-behavior:contain" in qwen)
check("qwen: body scroll lock", "body.no-scroll{overflow:hidden" in qwen and "no-scroll" in qwen)
check("qwen: drive select", 'id="driveSel"' in qwen and "syncDrive" in qwen)
check("qwen: metadata outside the button row",
      qwen.index('class="meta-details" style="margin:0 14px 10px"') > qwen.index('id="srcbar"'),
      "meta-details must not sit inside .srcbar")

# 6) copy/move buttons exist in both explorers
check("web: explorer copy/move", 'openOutBrowse("copy"' in web_js and 'openOutBrowse("move"' in web_js)
check("qwen: explorer copy/move", 'pickAction="copy"' in qwen and 'pickAction="move"' in qwen)

# 7) job list shows the queue with a summary in both UIs
check("web: jobs summary", 'id="jobs-summary"' in web_html and "待機中" in web_js)
check("qwen: jobs summary", 'id="jobsSummary"' in qwen and "待機中" in qwen)

# 8) background polling must never re-arm the waiting overlay
check("web: spin honours silent", "function spin(delta, silent)" in web_js and "if (silent) { return; }" in web_js)
check("web: pollers are silent", web_js.count("null, false, 0, true)") >= 2 and "180000, true)" in web_js)
check("qwen: spin honours silent", "function spin(d,silent){if(silent)return;" in qwen)
check("qwen: pollers are silent", qwen.count("{silent:true}") >= 2)
check("qwen: silent flag not deleted before use", "delete opt.silent" not in qwen and qwen.index("const silent=!!opt.silent;") < qwen.index("await fetch(path,opt)"))

# 9) long file names: reserved area + middle ellipsis
check("qwen: entry gives the name its own row", "grid-template-areas" in qwen and '"ic nm sz"' in qwen)
check("qwen: explorer actions have their own row", ".entry .acts{" in qwen and 'acts.className="acts"' in qwen)
check("qwen: middle ellipsis helper", "function midEllipsis(" in qwen)
check("qwen: entry name uses middle ellipsis", "midEllipsis(en.name,44)" in qwen)
check("qwen: chip name uses middle ellipsis", "midEllipsis(s.name,26)" in qwen)
check("qwen: chip does not overflow", "max-width:100%;min-width:0;overflow:hidden}" in qwen and ".chip .nm{overflow:hidden" in qwen)

# 10) the source history is bounded and prunable
check("qwen: history limit", "const LIMIT=6" in qwen and "件を表示" in qwen)
check("qwen: history entry can be deleted", '/api/sources/"+s.id,{method:"DELETE"}' in qwen)

check("web: history limit + pruning", "var LIMIT = 8;" in web_js and '/api/sources/" + s.id' in web_js and "件を表示" in web_js)
check("web: middle ellipsis for history names", "function midEllipsis(" in web_js and "midEllipsis(s.name, 34)" in web_js)

# 11) the page must never stay scroll-locked after the browse modal closes
check("qwen: modal-derived scroll lock", "body:has(.modal.show){overflow:hidden}" in qwen)
check("qwen: scroll lock added exactly once", qwen.count('document.body.classList.add("no-scroll")') == 1)
check("qwen: scroll lock released exactly once", qwen.count('document.body.classList.remove("no-scroll")') == 1)
check("qwen: single modal hide path", qwen.count('$("browseModal").classList.remove("show")') == 1 and "function hideBrowse()" in qwen)
check("qwen: picker/copy/close all use hideBrowse", qwen.count("hideBrowse()") >= 4)

# 12) preview thumbnails and layout stability
check("qwen: OUT frame clamped to the last frame", "function frameStamp(" in qwen and "Math.min(us,last)" in qwen)
check("qwen: frame error placeholder", 'img.classList.add("bad")' in qwen)
check("qwen: frames refresh after load", qwen.count("refreshFrames();") >= 3)
check("qwen: source bar cannot reflow with the name", "grid-template-columns:38px minmax(0,1fr) auto" in qwen and ".src-actions{" in qwen)

# 13) the output name carries the export settings
check("exports: readable name helpers", "def time_tag_short(" in exp and "def export_tags(" in exp)
check("exports: readable name used", "export_tags(options, start_us, end_us, has_video)" in exp)

# 14) long strings must not widen the page, and the visual crop must stay wired
check("qwen: toast wraps long names", "#toast{" in qwen and "overflow-wrap:anywhere" in qwen.split("#toast{")[1].split("}")[0])
check("qwen: page width guard", "html,body{overflow-x:clip}" in qwen)
check("web: page width guard", "html, body { overflow-x: clip; }" in web_css and "overflow-wrap: anywhere" in web_css)
check("qwen: crop overlay markup", 'id="cropLayer"' in qwen and 'id="cropBox"' in qwen and 'id="cropSize"' in qwen)
check("qwen: crop handles are ascii", all(h.encode("ascii", "ignore").decode() == h for h in __import__("re").findall(r'data-h="([^"]*)"', qwen)))
check("qwen: crop handles complete", all(h in qwen for h in ['data-h="nw"', 'data-h="ne"', 'data-h="sw"', 'data-h="se"', 'data-h="n"', 'data-h="s"', 'data-h="w"', 'data-h="e"']))
check("qwen: crop presets", all(("data-crop=\"%s\"" % k) in qwen for k in ["full", "16:9", "9:16", "1:1", "4:3"]))
check("qwen: crop pointer logic", "setPointerCapture" in qwen and "setCropRect" in qwen and "videoRect" in qwen)
check("qwen: full-frame crop is treated as no crop", "!isFullCrop()" in qwen)

# 15) downloads and the proxy explanation
check("main: download endpoint", "/api/fs/download" in main_py and "FileResponse" in main_py and "security.check_path(raw, cfg)" in main_py)
check("main: download is media-only", "target.suffix.lower() not in MEDIA_EXTS" in main_py)
check("qwen: result download link", "ダウンロード" in qwen and "ファイルを保存" in qwen)
check("qwen: explorer download link", qwen.count("/api/fs/download?path=") >= 3)
check("web: download links", web_js.count("/api/fs/download?path=") >= 2)
check("qwen: proxy hint is dynamic", 'id="proxyHint"' in qwen and "updateProxyHint" in qwen and "proxyReady" in qwen)
check("qwen: proxy button toggles variant", 'next==="proxy"?"元の画質で再生":"プロキシで再生"' in qwen)

# 16) the approved PLAN_LAYOUT fixes (replaced elements, form grids, nowrap items)
check("qwen: video cannot widen the layout", "max-width:100%;min-width:0;object-fit:contain" in qwen)
check("qwen: stage/viewer tracks use minmax(0,1fr)", "minmax(0,1.5fr) minmax(0,.9fr)" in qwen and "grid-template-columns:minmax(0,1fr);place-items:center" in qwen)
check("qwen: form grids use minmax(0,1fr)", "repeat(4,minmax(0,1fr))" in qwen and "minmax(0,1fr) minmax(0,1fr);gap:10px" in qwen and "minmax(0,1fr) minmax(0,1fr);gap:12px" in qwen)
check("qwen: form controls may shrink", ".inp,select.inp{width:100%;min-width:0" in qwen and ".time-inp{width:100%;min-width:0" in qwen)
check("qwen: modal footer wraps", "align-items:center;flex-wrap:wrap}" in qwen and ".sheet-foot .inp{flex:1 1 120px;min-width:0}" in qwen)
check("qwen: no user-scalable lock", "user-scalable=no" not in qwen and "viewport-fit=cover" in qwen)
check("qwen: layout diagnostic", "function layoutReport(" in qwen and "function inScrollContainer(" in qwen and "debug" in qwen)
check("qwen: diagnostic ignores body/html", "p!==document.body" in qwen)

# 17) this round: persistence, videos default, frame download, metadata port
check("qwen: settings persistence", "SETTINGS_KEY" in qwen and "function saveSettings(" in qwen and "function loadSettings(" in qwen and "bindSettings();" in qwen)
check("qwen: browse starts at the Videos folder", "state.config.videosDir" in qwen and "trim.lastPath" not in qwen)
check("main: config exposes videosDir", "videosDir" in main_py)
check("main: qwen ui is served at root", "name=\"root\"" in main_py and "name=\"web\"" in main_py)
check("qwen: frame download", "id=\"frameDlBtn\"" in qwen and "function downloadFrame(" in qwen and "/frame?tUs=" in qwen)
check("web: frame image is a download", "id=\"frame-dl\"" in web_html and "function downloadFrame(" in web_js and "id=\"toggle-frame\"" not in web_html)
check("qwen: metadata uses the deepseek layout", ".src-sub{display:grid" in qwen and ".stream-box{" in qwen)

# 18) the inline script must be real JS (a misplaced block in <style> broke the app once)
def _between(text, start, end):
    i = text.index(start); j = text.index(end, i)
    return text[i + len(start):j]

qwen_css = _between(qwen, "<style>", "</style>")
qwen_js = _between(qwen, "<script>", "</script>")
check("qwen: no JavaScript left inside <style>", "function " not in qwen_css and "SETTINGS_KEY" not in qwen_css and "const state=" not in qwen_css)
for _fn in ("function saveSettings(", "function loadSettings(", "function bindSettings(", "function downloadFrame(", "function layoutReport(", "function refreshJobs(", "function renderSource("):
    check("qwen: %s lives in <script>" % _fn, _fn in qwen_js)
check("qwen: script is executed last", qwen.rindex("<script>") > qwen.index("</style>"))
print("RESULT:", "OK" if fails == 0 else "FAIL(%d)" % fails)
sys.exit(0 if fails == 0 else 1)
