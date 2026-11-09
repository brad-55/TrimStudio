"""Static regression guards for the UI files (no browser needed)."""
import io, re, sys

ROOT = r"L:\dev\Trim"
WEB_HTML = ROOT + r"\web\index.html"
WEB_CSS = ROOT + r"\web\style.css"
WEB_JS = ROOT + r"\web\app.js"
QWEN = ROOT + r"\web-qwen\index.html"
FFMPEG_PY = ROOT + r"\app\ffmpeg_tools.py"
EXPORTS_PY = ROOT + r"\app\exports.py"
MAIN_PY = ROOT + r"\app\main.py"

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
ffmpeg_py = read(ROOT + r"\app\ffmpeg_tools.py")
exports_py = read(ROOT + r"\app\exports.py")
config_py = read(ROOT + r"\app\config.py")
security_py = read(ROOT + r"\app\security.py")
unit_py = read(ROOT + r"\tests\test_unit.py")
readme_md = read(ROOT + r"\README.md")
readme_en_md = read(ROOT + r"\README.en.md")

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

# 19) playback diagnosis fixes: rotation-aware crop, source depth, proxy readiness
check("probe keeps the display rotation", "def stream_rotation(" in ffmpeg_py and "\"rotation\": stream_rotation(st)" in ffmpeg_py)
check("hevc nvenc preserves source depth", "pix = \"p010le\" if ten_bit else \"yuv420p\"" in exports_py)
check("crop clamps in display orientation", "disp_w, disp_h = src_h, src_w" in exports_py and "def video_rotation(" in exports_py)
check("source detail reports proxyReadiness", "\"proxyReady\": media.proxy_path(cfg, source_id).exists()" in main_py)
check("validate resolves the default destination", "is_default = not path" in main_py and "result[\"isDefault\"] = is_default" in main_py)
check("qwen: playback notice", "id=\"videoNotice\"" in qwen and "function updatePlayNotice(" in qwen and "vid.addEventListener(\"error\"" in qwen)
check("qwen: proxy readiness from the api", "state.proxyReady=!!d.proxyReady" in qwen)
check("qwen: output picker starts at the output folder", "outDirStart(cur)" in qwen and "let outDir=" in qwen)
check("qwen: picked output folder is remembered", "outDir=browsePath;saveSettings();" in qwen and "outDir:outDir" in qwen)
check("qwen: validate works with an empty path", "path:p,sourceId:state.source?state.source.id:\"\"" in qwen and "d.isDefault" in qwen)
check("web: playback error explains the proxy", "プロキシを生成」を押してください" in web_js)

# 20) LUT folder UI, frame image sharing, crop preset highlight, beginner README
check("config: lutsDir is configurable", 'self.data.get("lutsDir")' in config_py)
check("main: LUT folder can be chosen", '@app.post("/api/luts/dir")' in main_py and 'cfg.data["lutsDir"] = str(target)' in main_py and "cfg.save()" in main_py)
check("main: LUT folder can be revealed and filled", '@app.post("/api/luts/reveal")' in main_py and '@app.post("/api/luts/upload")' in main_py and "LUT_MAX_BYTES" in main_py)
check("main: luts listing returns the folder", '"luts": scan_luts(), "dir": str(cfg.luts_dir)' in main_py)
check("qwen: LUT folder controls", 'id="lutPickBtn"' in qwen and 'id="lutOpenBtn"' in qwen and 'id="lutReloadBtn"' in qwen and 'id="lutUploadBtn"' in qwen)
check("qwen: LUT folder wiring", "function renderLutOptions(" in qwen and '"/api/luts/dir"' in qwen and '"/api/luts/reveal"' in qwen and '"/api/luts/upload"' in qwen)
check("qwen: LUT folder shown", 'id="lutDirLabel"' in qwen and 'id="lutCount"' in qwen)
check("qwen: frame image modal", 'id="frameModal"' in qwen and 'id="frameShare"' in qwen and 'id="frameSaveBtn"' in qwen)
check("qwen: frame share to the photo library", "navigator.share({files:[f]})" in qwen and "navigator.canShare({files:[f]})" in qwen)
check("qwen: frame button stands out", 'class="btn sm frame-save" id="frameDlBtn"' in qwen and ".btn.frame-save{" in qwen)
check("qwen: crop preset highlight", "function updateCropButtons(" in qwen and ".crop-presets .btn.on{" in qwen and 'class="row crop-presets"' in qwen)
check("readme: the three headline features", readme_md.index("Windows PC 上で動きます") < readme_md.index("操作はスマホからもできます") < readme_md.index("無劣化でトリミングできます"))
check("readme: beginner download steps", "Download ZIP" in readme_md and "すべて展開" in readme_md)
check("readme: python PATH warning", "Add python.exe to PATH" in readme_md)
check("readme: start.cmd step", "start.cmd" in readme_md and "netsh advfirewall" in readme_md)
check("readme: other features moved down", "## 特徴" in readme_md and "## その他の機能" in readme_md and readme_md.index("## その他の機能") > readme_md.index("## 使い方"))
check("qwen: playback notice matches the export mode", "function exportHowText(" in qwen)
check("qwen: video errors are told apart", "vid.error&&vid.error.code" in qwen)
check("qwen: invalid remembered folder falls back", "function browseTo(path,fresh,offset)" in qwen and "前回のフォルダを開けないためビデオフォルダを開きました" in qwen)
check("qwen: explorer pages big folders", "browseMore" in qwen and "さらに表示" in qwen and "&offset=" in qwen)
check("qwen: explorer can delete a file", "del_test" not in qwen and "/api/fs/delete" in qwen and "元に戻せません" in qwen)
check("qwen: dates are three lines for files and folders", "<i>撮影</i>" in qwen and "<i>作成</i>" in qwen and "<i>更新</i>" in qwen)

# 21) tailnet (Tailscale) access
check("security: tailnet range helpers", "TAILNET_NETWORKS" in security_py and "def is_tailnet_ip(" in security_py and "def is_allowed_source(" in security_py)
check("security: own tailnet identity", "def tailnet_info(" in security_py and "TailscaleIPs" in security_py and "ts.net" in security_py)
check("main: tailnet sources and hosts allowed", "is_allowed_source(client, allow_tailnet)" in main_py and "security.tailnet_info()" in main_py and "allowTailnet" in main_py)
check("config: allowTailnet switch", "\"allowTailnet\": True" in config_py)
check("unit: tailnet cases", "is_tailnet_ip" in unit_py and "ts.net" in unit_py and "is_allowed_source" in unit_py)
check("readme: tailscale section", "外出先から使う（Tailscale / tailnet）" in readme_md and "tailscale ip -4" in readme_md and "allowTailnet" in readme_md)

# 22) timeline: modern two-zone design with labelled knobs (refreshed by the local Qwen)
check("timeline: 96px two-zone bar", ".timeline{position:relative;height:96px;" in qwen and "tlH=96" in qwen)
check("timeline: mobile height tweak", "@media(max-width:430px){.timeline{height:88px}" in qwen)
check("timeline: 48px hit targets", "const TL_HIT_R=24;" in qwen and "const TL_DRAG_EPS=3;" in qwen)
check("timeline: playhead knob is a round marker with a glyph", ".playhead .dia{top:9px;width:28px;height:28px;border-radius:999px;" in qwen and "content:'\u25b6'" in qwen)
check("timeline: IN/OUT knobs are labelled", ".handle.in .dia::after{content:'IN'}" in qwen and ".handle.out .dia::after{content:'OUT'" in qwen)
check("timeline: selected and grab feedback", ".selected" in qwen and ".grab" in qwen and "scale(1.12)" in qwen)
check("timeline: zone split by height", "const sep=(band!=null&&band>0)?band:Math.round(tlH*0.46);" in qwen and "if(py<sep)return tlHorizontalHit(px,playX,tlW)?'play':null;" in qwen)
check("timeline: empty areas return null", "return null;" in qwen and "empty areas return null" in qwen.lower() + qwen)
check("timeline: edge-pinned knobs stay reachable", "TL_HIT_R" in qwen and "right=Math.min(w,Math.max(right,2*TL_HIT_R));" in qwen)
check("timeline: keeps the required ids", "id=\"timeline\"" in qwen and "id=\"region\"" in qwen and "id=\"hIn\"" in qwen and "id=\"hOut\"" in qwen and "id=\"playhead\"" in qwen)
check("timeline: keeps the public functions", "function pickTimelineTarget(px,py,playX,inX,outX,last,band)" in qwen and "function updateTimeline()" in qwen and "function tlDown(" in qwen and "function tlMoveEv(" in qwen and "function tlUp(" in qwen and "function tlCancel(" in qwen)
check("timeline: relative drag and cancel restore", "TL_DRAG_EPS" in qwen and "function tlCancel(" in qwen)
check("timeline: pick only on grab", "pickTimelineTarget" not in qwen[qwen.index("function tlMoveEv("):qwen.index("function tlUp(")])

# 24) audio panel (implemented by the local Qwen, verified by the lead)
check("audio: mode radios", qwen.count("name='audioModeRadio'") == 5 and "value='bothMix'" in qwen and "value='mute'" in qwen)
check("audio: shift controls", "id='origShiftInp'" in qwen and "id='addedShiftInp'" in qwen and "id='origShiftRange'" in qwen and "data-shift" in qwen)
check("audio: 1ms controls", qwen.count("data-delta='-1'") == 2 and qwen.count("data-delta='1'") == 2 and "class='btn ms'" in qwen)
check("audio: fine slider and readout", "id='origShiftFine'" in qwen and "id='addedShiftFine'" in qwen and "id='origShiftVal'" in qwen and "function msLabel(" in qwen)
check("audio: added track controls", "id='addedBrowseBtn'" in qwen and "id='addedFileInput'" in qwen and "id='addedInfo'" in qwen and "id='addedReencodeChk'" in qwen)
check("audio: auto sync wiring", "id='audioSyncBtn'" in qwen and "/api/audio/sync" in qwen and "d.job||{}" in qwen and "function pollSyncJob(" in qwen)
check("audio: preview toggle wiring", "id='auditionToggle'" in qwen and "id='auditionState'" in qwen and "音声タイミング調整" in qwen and "function syncAudition(" in qwen and "id='muteOrigAuditionChk'" in qwen)
check("audio: audition formula", "vid.currentTime-(state.audioShiftMs||0)/1000" in qwen or "t-s1/1000" in qwen)
check("audio: audition resync", "requestAnimationFrame(auditionTick)" in qwen and "visibilitychange" in qwen)
check("audio: settings persistence", "audioMode:modeRadio?modeRadio.value" in qwen and "addedShiftMs" in qwen and "addedReencode" in qwen)
check("audio: export payload", "o.audioMode=am" in qwen and "o.addedSourceId=" in qwen and "o.addedShiftMs=" in qwen and "o.addedStartMs=" in qwen and "o.addedReencode=" in qwen)
check("audio: no media reload on start", "origAudio.getAttribute('data-src')!==audSrc" in qwen and "addedAudio.getAttribute('data-src')!==ap" in qwen)
check("audio: never seeks while loading", "el.readyState<1||el.seeking" in qwen)
check("audio: hard seek only on a real desync", "Math.abs(d)>0.5" in qwen and "const now=Date.now();" in qwen and "now-Number(el.dataset.seekAt)<400" in qwen)
check("audio: playback rate is never modulated", "1+k" not in qwen and "Math.max(-0.01,Math.min(0.01" not in qwen and "if(el.playbackRate!==1)el.playbackRate=1;" in qwen)
check("audio: the preview UI removals", "auditionBar" not in qwen and "barStopBtn" not in qwen and "data-bar" not in qwen and "abHoldBtn" not in qwen and "testToneBtn" not in qwen and "playTestTone" not in qwen and "auditionBtn" not in qwen)
check("audio: L/R split capability kept", "function ensureAudioGraph(" in qwen and "createStereoPanner" in qwen)
check("audio: single alignment after metadata", "addEventListener('loadedmetadata',apply,{once:true})" in qwen)
check("audio: overlay routing only when meaningful", "function applyAuditionMute()" in qwen and "origSilent&&!overlay" in qwen and "vid.muted=!(overlay&&!origSilent);" in qwen and "abCompare=" not in qwen and "abCompare?" not in qwen and "volume" not in qwen[qwen.index("function applyAuditionMute()"):qwen.index("function applyAuditionMute()")+430])
_sa = qwen[qwen.index("function startAudition("):qwen.index("function stopAudition(")]
check("audio: preview never starts the video", "vid.play(" not in _sa)
check("audio: toggle sits between the mode and the shift", qwen.index("id='auditionToggle'") > qwen.index("name='audioModeRadio'") and qwen.index("id='auditionToggle'") < qwen.index("id='origShiftBox'"))
check("audio: audition plays inside the tap", "origAudio.play()" in qwen[qwen.index("function startAudition("):qwen.index("function stopAudition(")])
check("audio: added url falls back to the original variant", "addedAudio.onerror=function()" in qwen and "variant=original" in qwen)
check("audio: overlay toggle keeps the video audible", "id='abCompareChk'" in qwen and "vid.muted=!(" in qwen)


# 25) unlimited shift + relative jog sliders
check("shift: no ui clamp", "Math.max(-1000,Math.min(1000" not in qwen and "function clampMs(v){v=parseInt(v,10);if(!isFinite(v))v=0;return v;}" in qwen)
check("shift: number inputs unbounded", "id='origShiftInp' type='number' step='1'" in qwen and "id='addedShiftInp' type='number' step='1'" in qwen and "id='origShiftInp' type='number' min=" not in qwen and "id='addedShiftInp' type='number' min=" not in qwen)
check("shift: sliders are relative jog controls", "el.value=0;base=cur();" in qwen and "setAudioShift(target,base+(parseInt(el.value,10)||0),true);" in qwen)
check("shift: every jog starts at the centre", "[\"origShiftRange\",\"origShiftFine\"].forEach" in qwen and "[\"addedShiftRange\",\"addedShiftFine\"].forEach" in qwen)
check("shift: nothing assigns an absolute position to a jog", "rng.value=c" not in qwen and "if(rng)rng.value=v;" not in qwen and "fine.value=Math.max(-100" not in qwen)
check("shift: the number input updates only the readout", "const live=$(target==='orig'?'origShiftVal':'addedShiftVal');if(live)live.textContent=msLabel(c);" in qwen)
check("shift: both jog sizes follow the enable rules", "$(\"origShiftFine\").disabled=origOff" in qwen and "$(\"addedShiftFine\").disabled=addedOff" in qwen)
check("shift: the stale clamp helper is gone", "setClampMs" not in qwen and "const setShiftInp=" in qwen)
check("shift: hints explain the centre", qwen.count("中央＝現在の値") >= 4)

check("audio: delayed original is silent at the head", "origAudio.dataset.head" in qwen and 'if(oTarget<0)' in qwen)
check("audio: added track is held before IN", "addedAudio.dataset.pre" in qwen and "addedAudio.volume=0" in qwen)
check("audio: added alignment matches the sync formula", "base+Math.max(0,local)" in qwen and "(state.addedStartMs||0)/1000-s2/1000" in qwen)
check("audio: added source cleared safely", "addedAudio.removeAttribute('src')" in qwen and "addedAudio.load()" in qwen)
check("audio: error closure captures the id", "const aid=state.addedSource.id;" in qwen)
check("jog: pointercancel resets", "el.addEventListener('pointercancel',end);" in qwen and "touchstart" not in qwen)
check("audio: context state watched", "auditionCtx.onstatechange" in qwen and "ctx=" in qwen)
check("audio timing: settings hidden until ON", "id='audioTimingBox' hidden" in qwen and "b.hidden=!on" in qwen and "if(b)b.hidden=!on;" in qwen)
check("audio timing: payload carries the switch", "o.audioTiming=!!($(\"auditionToggle\")&&$(\"auditionToggle\").checked);" in qwen)
check("qwen: the opened file name is shown in full", ".src-name{font-weight:700;font-size:15px;white-space:normal" in qwen and "text-overflow:ellipsis;white-space:nowrap" not in qwen.split(".src-name{")[1].split("}")[0])
check("qwen: the player verdict beats the conservative server list", "state.directPlayable=true;" in qwen and "vid.videoWidth>0" in qwen)
check("qwen: the play notice names the real reason", "10bit" in qwen and "再生できる場合もあります" in qwen)
check("audio timing: the added re-encode is explained", "addedReencodeHint" in qwen and "追加した音声のみ再エンコード</label>" in qwen)
check("audio timing: the jog never takes an absolute value", "function setAudioShift(target,v,fromJog)" in qwen and "if(rng)rng.value=v;" not in qwen and "if(fine)fine.value=Math.max(-100,Math.min(100,v));" not in qwen and "setAudioShift(target,base+(parseInt(el.value,10)||0),true)" in qwen)
check("audio: silence is carried by volume, not by pausing", "el.dataset[flag]='1';follow(el);" in qwen or ("el.dataset[flag]='1';" in qwen and "if(!el.paused)el.pause();" not in qwen.split("const handle=function(el,flag,target){")[1].split("handle(origAudio")[0]))
check("audio timing: one mute listener only", qwen.count("muteOrigAuditionChk\").addEventListener('change'") == 1)
check("audio timing: silence is explained", "動画を再生すると聴こえます" in qwen and "ずらしが動画の長さを超えているため無音です" in qwen)
check("qwen: explorer rows show shot/update/create dates", "span.dt" in qwen and "fmtDate(en.mtimeMs)" in qwen and "fillShotDates" in qwen and "/api/media-dates" in qwen)
check("qwen: source detail shows the three dates", "撮影日" in qwen and "s.shotAtMs" in qwen and "s.fileCtimeMs" in qwen and "s.fileMtimeMs" in qwen)
check("qwen: explorer sorts by name or mtime", "id=\"sortSel\"" in qwen and "mtimeDesc" in qwen and "browseTo(browsePath)" in qwen)
print("RESULT:", "OK" if fails == 0 else "FAIL(%d)" % fails)
sys.exit(0 if fails == 0 else 1)
