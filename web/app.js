(function () {
  "use strict";
  var state = { token: "", source: null, kind: "video", activeJobId: null, durationUs: 0, fps: 30, keyframes: [], inUs: 0, outUs: 0, curUs: 0, busy: false, variant: "original", showFrame: false, frameTimer: null };

  function $(id) { return document.getElementById(id); }
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function formatTime(us) {
    var ms = Math.max(0, Math.floor(us / 1000));
    var s = Math.floor(ms / 1000), m = Math.floor(s / 60), h = Math.floor(m / 60);
    return pad(h) + ":" + pad(m % 60) + ":" + pad(s % 60) + "." + ("00" + (ms % 1000)).slice(-3);
  }
  function parseTime(text) {
    var m = /^(\d+):(\d+):(\d+)(?:[.,](\d{1,3}))?$/.exec(String(text).trim());
    if (!m) { m = /^(\d+):(\d+)(?:[.,](\d{1,3}))?$/.exec(String(text).trim()); if (!m) { return null; } return ((+m[1]) * 60 + (+m[2])) * 1000000 + (+((m[3] || "0") + "00").slice(0, 3)) * 1000; }
    return ((+m[1]) * 3600 + (+m[2]) * 60 + (+m[3])) * 1000000 + (+(((m[4] || "0") + "00").slice(0, 3))) * 1000;
  }
  function setStatus(t) { $("status").textContent = t || ""; }

  var pendingCalls = 0, spinTimer = null, spinOn = false, stuckTimer = null;
  var API_TIMEOUT = 60000, STUCK_AFTER = 25000;

  function showSpinner(on) {
    var el = $("spinner");
    if (el) { el.hidden = !on; }
    if (!on) {
      var t = $("spinner-text");
      if (t) { t.textContent = "サーバー応答待ち…"; }
      var esc = $("spinEscape");
      if (esc) { esc.hidden = true; }
    }
  }

  function armStuck() {
    if (stuckTimer) { return; }
    stuckTimer = setTimeout(function () {
      stuckTimer = null;
      var t = $("spinner-text");
      if (t) { t.textContent = "サーバーの応答がありません（待機中）"; }
      var esc = $("spinEscape");
      if (esc) { esc.hidden = false; }
    }, STUCK_AFTER);
  }

  function clearStuck() { if (stuckTimer) { clearTimeout(stuckTimer); stuckTimer = null; } }

  function releaseSpinner() {
    pendingCalls = 0;
    if (spinTimer) { clearTimeout(spinTimer); spinTimer = null; }
    clearStuck();
    spinOn = false;
    showSpinner(false);
    setStatus("応答待ちを解除しました（通信は完了していない可能性があります）");
  }

  function spin(delta, silent) {
    if (silent) { return; }
    pendingCalls += delta;
    if (pendingCalls < 0) { pendingCalls = 0; }
    if (pendingCalls > 0) {
      if (!spinOn && !spinTimer) {
        spinTimer = setTimeout(function () {
          spinTimer = null;
          if (pendingCalls > 0) { spinOn = true; showSpinner(true); armStuck(); }
        }, 180);
      }
    } else {
      if (spinTimer) { clearTimeout(spinTimer); spinTimer = null; }
      clearStuck();
      if (spinOn) { spinOn = false; showSpinner(false); }
    }
  }

  async function api(method, path, body, isForm, timeoutMs, silent) {
    var headers = {};
    if (state.token) { headers["X-Trim-Token"] = state.token; }
    var options = { method: method, headers: headers };
    if (isForm) { options.body = body; }
    else if (body !== undefined && body !== null) { headers["Content-Type"] = "application/json"; options.body = JSON.stringify(body); }
    var limit = timeoutMs || API_TIMEOUT;
    var ctl = (typeof AbortController !== "undefined") ? new AbortController() : null;
    var abortTimer = null;
    if (ctl) {
      options.signal = ctl.signal;
      abortTimer = setTimeout(function () { try { ctl.abort(); } catch (e) {} }, limit);
      armStuck();
    }
    spin(1, silent);
    try {
      var resp = await fetch(path, options);
      var text = await resp.text();
      var data;
      try { data = JSON.parse(text); } catch (e) { data = text; }
      if (!resp.ok) { var msg = (data && data.message) ? data.message : String(text).slice(0, 200); throw new Error(msg); }
      return data;
    } catch (err) {
      if (err && (err.name === "AbortError" || err.code === 20)) {
        throw new Error("サーバーの応答がありません（" + Math.round(limit / 1000) + "秒でタイムアウト）");
      }
      throw err;
    } finally {
      if (abortTimer) { clearTimeout(abortTimer); }
      spin(-1, silent);
    }
  }

  async function init() {
    try {
      var t = await api("GET", "/api/token");
      state.token = t.token;
    } catch (e) {
      var manual = window.prompt("トークンを入力してください（PC のコンソールに表示されます）");
      if (manual) {
        try {
          await fetch("/api/auth", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token: manual }) });
          state.token = "cookie";
        } catch (e2) { setStatus("auth failed"); }
      } else { setStatus("token error"); }
    }
    try {
      var h = await api("GET", "/api/health");
      setStatus(h.ffmpeg ? "ffmpeg ready" : "ffmpeg missing");
    } catch (e) { setStatus("offline"); }
    browse("");
    loadRecent();
    refreshJobs();
    setInterval(refreshJobs, 3000);
    loadLuts();
    loadRoots();
    bind();
  }

  function bind() {
    document.querySelectorAll(".tabs button").forEach(function (b) {
      b.addEventListener("click", function () {
        document.querySelectorAll(".tabs button").forEach(function (x) { x.classList.remove("active"); });
        b.classList.add("active");
        ["browse", "upload", "recent"].forEach(function (name) { $("tab-" + name).hidden = (name !== b.dataset.tab); });
      });
    });
    $("seek").addEventListener("input", function () { seekTo(parseInt(this.value, 10) / 100000 * state.durationUs); });
    $("step-back-frame").addEventListener("click", function () { seekTo(state.curUs - 1000000 / state.fps); });
    $("step-fwd-frame").addEventListener("click", function () { seekTo(state.curUs + 1000000 / state.fps); });
    $("step-back-1s").addEventListener("click", function () { seekTo(state.curUs - 1000000); });
    $("step-fwd-1s").addEventListener("click", function () { seekTo(state.curUs + 1000000); });
    $("step-back-kf").addEventListener("click", function () { seekTo(findKeyframe(-1)); });
    $("step-fwd-kf").addEventListener("click", function () { seekTo(findKeyframe(1)); });
    $("set-in").addEventListener("click", function () { state.inUs = state.curUs; $("in-time").value = formatTime(state.inUs); updateRangeInfo(); });
    $("set-out").addEventListener("click", function () { state.outUs = state.curUs; $("out-time").value = formatTime(state.outUs); updateRangeInfo(); });
    $("goto-in").addEventListener("click", function () { seekTo(state.inUs); });
    $("goto-out").addEventListener("click", function () { seekTo(state.outUs); });
    $("in-time").addEventListener("change", function () { var v = parseTime(this.value); if (v !== null) { state.inUs = v; updateRangeInfo(); } });
    $("out-time").addEventListener("change", function () { var v = parseTime(this.value); if (v !== null) { state.outUs = v; updateRangeInfo(); } });
    $("in-snap").addEventListener("change", updateRangeInfo);
    $("out-mode").addEventListener("change", updateRangeInfo);
    if ($("cancel-btn")) { $("cancel-btn").addEventListener("click", cancelActiveJob); }
    if ($("spinEscape")) { $("spinEscape").addEventListener("click", releaseSpinner); }
    if ($("output-browse")) { $("output-browse").addEventListener("click", openOutBrowse); }
    if ($("out-close")) { $("out-close").addEventListener("click", function () { $("out-browse").hidden = true; }); }
    if ($("out-use")) { $("out-use").addEventListener("click", useOutDir); }
    if ($("out-up")) { $("out-up").addEventListener("click", function () { if (outParent) { outBrowse(outParent); } }); }
    if ($("out-mkdir")) { $("out-mkdir").addEventListener("click", makeOutDir); }
    $("upload-btn").addEventListener("click", doUpload);
    $("export-btn").addEventListener("click", doExport);
    $("proxy-btn").addEventListener("click", buildProxy);
    if ($("frame-dl")) { $("frame-dl").addEventListener("click", downloadFrame); }
    $("player").addEventListener("error", function () {
    if (state.variant !== "proxy") {
      $("proxy-btn").hidden = false;
      setStatus("この形式（H.265 / 10bit など）はブラウザで直接再生できません。「プロキシを生成」を押してください（書き出しは元の画質のまま無変換です）");
    } else {
      setStatus("プロキシを再生できません。もう一度生成してください");
    }
  });
    document.querySelectorAll("input[name=mode]").forEach(function (r) {
      r.addEventListener("change", function () { $("reencode-options").hidden = (this.value !== "reencode"); updateRangeInfo(); });
    });
    $("player").addEventListener("timeupdate", function () {
      if (state.busy) { return; }
      state.curUs = Math.round(this.currentTime * 1000000);
      updatePos();
    });
  }

  function findKeyframe(dir) {
    var kf = state.keyframes;
    if (!kf.length) { return state.curUs + dir * 1000000; }
    if (dir < 0) { var prev = 0; for (var i = 0; i < kf.length; i++) { if (kf[i] < state.curUs - 1000) { prev = kf[i]; } else { break; } } return prev; }
    for (var j = 0; j < kf.length; j++) { if (kf[j] > state.curUs + 1000) { return kf[j]; } }
    return state.durationUs;
  }

  function seekTo(us) {
    us = Math.max(0, Math.min(state.durationUs, Math.round(us)));
    state.curUs = us;
    var player = $("player");
    if (player.readyState >= 1) { player.currentTime = us / 1000000; }
    updatePos();
  }

  function updatePos() {
    $("pos-label").textContent = formatTime(state.curUs);
    if (state.durationUs > 0) { $("seek").value = String(Math.round(state.curUs / state.durationUs * 100000)); }
    if (state.showFrame) { scheduleFramePreview(); }
  }

  function scheduleFramePreview() {
    if (state.frameTimer) { clearTimeout(state.frameTimer); }
    state.frameTimer = setTimeout(updateFramePreview, 250);
  }

  function downloadFrame() {
    if (!state.source || state.kind === "audio") { setStatus("動画を読み込んでください"); return; }
    var t = Math.round(state.curUs);
    var url = "/api/sources/" + state.source.id + "/frame?tUs=" + t + "&width=" + (state.source.width || 1280);
    var name = String(state.source.name || "frame").replace(/\.[^.]*$/, "") + "_" + formatTime(t).replace(/[:.]/g, "-") + ".jpg";
    var a = document.createElement("a");
    a.href = url; a.setAttribute("download", name);
    document.body.appendChild(a); a.click(); a.remove();
    setStatus("フレーム画像を保存: " + name);
  }

  function updateFramePreview() {
    if (!state.source || state.kind === "audio") { return; }
    var img = $("frame-preview");
    img.hidden = false;
    img.src = "/api/sources/" + state.source.id + "/frame?tUs=" + Math.round(state.curUs) + "&width=640&_=" + Date.now();
  }

  async function buildProxy() {
    if (!state.source) { return; }
    $("proxy-btn").disabled = true;
    try {
      var data = await api("POST", "/api/sources/" + state.source.id + "/proxy", {});
      await watchJob(data.jobId);
      state.variant = "proxy";
      $("player").src = "/api/sources/" + state.source.id + "/media?variant=proxy&_=" + Date.now();
      $("player").load();
      $("proxy-btn").hidden = true;
    } catch (e) { setStatus("proxy error: " + e.message); }
    finally { $("proxy-btn").disabled = false; }
  }

  function prevKeyframe(us) {
    var prev = 0;
    for (var i = 0; i < state.keyframes.length; i++) {
      if (state.keyframes[i] <= us) { prev = state.keyframes[i]; } else { break; }
    }
    return prev;
  }

  function actualRange() {
    var kf = state.keyframes || [];
    if (!kf.length) { return { start: state.inUs, end: state.outUs, snapped: false }; }
    var inSnap = $("in-snap").value;
    var outMode = $("out-mode").value;
    var start;
    if (inSnap === "next") {
      var later = kf.filter(function (k) { return k >= state.inUs; });
      start = (!later.length || later[0] >= state.outUs) ? prevKeyframe(state.inUs) : later[0];
    } else {
      start = prevKeyframe(state.inUs);
    }
    var end;
    if (outMode === "keyframeBefore") { end = prevKeyframe(state.outUs); }
    else if (outMode === "keyframeAfter") {
      var after = kf.filter(function (k) { return k >= state.outUs; });
      end = after.length ? after[0] : state.outUs;
    } else { end = state.outUs; }
    return { start: start, end: end, snapped: true };
  }

  function updateRangeInfo() {
    $("in-time").value = formatTime(state.inUs);
    $("out-time").value = formatTime(state.outUs);
    var mode = document.querySelector("input[name=mode]:checked").value;
    var a = actualRange();
    var text = "目的 " + formatTime(state.inUs) + " - " + formatTime(state.outUs) + " / 長さ " + formatTime(Math.max(0, state.outUs - state.inUs));
    if (mode === "lossless" && a.snapped) {
      text += chr_nl + "実カット " + formatTime(a.start) + " - " + formatTime(a.end) + " / 差分 IN " + ((a.start - state.inUs) / 1000).toFixed(0) + "ms OUT " + ((a.end - state.outUs) / 1000).toFixed(0) + "ms";
    }
    $("range-info").textContent = text;
  }

  var chr_nl = String.fromCharCode(10);

  var outBrowsePath = "";
  var outParent = null;

  var outMode = "output";
  var outPick = null;

  async function openOutBrowse(mode, pickPath) {
    outMode = mode || "output";
    outPick = pickPath || null;
    var title = outMode === "copy" ? "コピー先フォルダを選択（元: " + baseName(outPick) + "）"
              : (outMode === "move" ? "移動先フォルダを選択（元: " + baseName(outPick) + "）" : "出力先フォルダを選択");
    if ($("out-title")) { $("out-title").textContent = title; }
    if ($("out-use")) { $("out-use").textContent = outMode === "output" ? "このフォルダを使う" : (outMode === "copy" ? "ここにコピー" : "ここに移動"); }
    $("out-browse").hidden = false;
    try {
      var data = await api("GET", "/api/roots");
      var sel = $("out-roots");
      sel.innerHTML = "";
      (data.roots || []).forEach(function (r) {
        var opt = document.createElement("option");
        opt.value = r.path;
        opt.textContent = r.name || r.path;
        sel.appendChild(opt);
      });
      sel.onchange = function () { outBrowse(this.value); };
    } catch (e) { $("out-status").textContent = "ルート取得失敗"; }
    var current = $("output-path").value.trim();
    outBrowse(current || "");
  }

  async function outBrowse(path) {
    var q = path ? "?path=" + encodeURIComponent(path) : "";
    $("out-status").textContent = "読み込み中…";
    try {
      var data = await api("GET", "/api/browse" + q);
      outBrowsePath = data.path;
      outParent = data.parent;
      $("out-current").textContent = data.path;
      var list = $("out-list");
      list.innerHTML = "";
      (data.entries || []).forEach(function (e) {
        if (!e.dir) { return; }
        var li = document.createElement("li");
        var b = document.createElement("button");
        b.type = "button";
        b.textContent = "[DIR] " + e.name;
        b.addEventListener("click", function () { outBrowse(e.path); });
        li.appendChild(b);
        list.appendChild(li);
      });
      $("out-status").textContent = "";
    } catch (e) { $("out-status").textContent = "取得失敗: " + e.message; }
  }

  async function useOutDir() {
    if (!outBrowsePath) { return; }
    if (outMode === "output") {
      $("output-path").value = outBrowsePath;
      $("out-browse").hidden = true;
      return;
    }
    var verb = outMode === "move" ? "移動" : "コピー";
    $("out-status").textContent = verb + "を開始しています…";
    try {
      var url = outMode === "move" ? "/api/fs/move" : "/api/fs/copy";
      await api("POST", url, { source: outPick, destination: outBrowsePath });
      $("out-browse").hidden = true;
      setStatus(verb + "を開始しました（ジョブ一覧に表示されます）");
      refreshJobs();
    } catch (e) { $("out-status").textContent = verb + "失敗: " + e.message; }
  }

  async function makeOutDir() {
    var name = $("out-new-name").value.trim();
    if (!name || !outBrowsePath) { $("out-status").textContent = "フォルダ名を入力してください"; return; }
    var sep = outBrowsePath.indexOf("\\") >= 0 ? "\\" : "/";
    var target = outBrowsePath.replace(/[\\/]+$/, "") + sep + name;
    try {
      var data = await api("POST", "/api/fs/mkdir", { path: target });
      $("out-new-name").value = "";
      await outBrowse(data.path);
    } catch (e) { $("out-status").textContent = "作成失敗: " + e.message; }
  }

  async function browse(path) {
    setStatus("loading...");
    var q = path ? ("?path=" + encodeURIComponent(path)) : "";
    try {
      var data = await api("GET", "/api/browse" + q);
      var bc = $("breadcrumb");
      bc.textContent = data.path || "";
      var ul = $("file-list");
      ul.innerHTML = "";
      if (data.parent) { ul.appendChild(makeRow(".. (上へ)", data.parent, true)); }
      (data.entries || []).forEach(function (e) {
        ul.appendChild(makeRow(e.name + (e.dir ? "/" : ""), e.path, e.dir, e.size));
      });
      setStatus("");
    } catch (e) { setStatus("browse error"); }
  }

  function makeRow(label, path, isDir, size) {
    var li = document.createElement("li");
    var b = document.createElement("button");
    b.type = "button";
    b.textContent = label;
    b.addEventListener("click", function () { if (isDir) { browse(path); } else { openSource(path); } });
    li.appendChild(b);
    if (size) { var s = document.createElement("span"); s.className = "meta"; s.textContent = (size / 1048576).toFixed(1) + " MB"; li.appendChild(s); }
    if (label.indexOf("..") !== 0) {
      var cp = document.createElement("button");
      cp.type = "button"; cp.className = "tiny"; cp.textContent = "コピー";
      cp.addEventListener("click", function () { openOutBrowse("copy", path); });
      li.appendChild(cp);
      var mv = document.createElement("button");
      mv.type = "button"; mv.className = "tiny"; mv.textContent = "移動";
      mv.addEventListener("click", function () { openOutBrowse("move", path); });
      li.appendChild(mv);
      var dl2 = document.createElement("a");
      dl2.className = "tiny";
      dl2.textContent = "ダウンロード";
      dl2.href = "/api/fs/download?path=" + encodeURIComponent(path);
      dl2.setAttribute("download", "");
      li.appendChild(dl2);
    }
    return li;
  }

  async function openSource(path) {
    setStatus("opening...");
    try {
      var data = await api("POST", "/api/sources/open", { path: path });
      await loadSource(data.source);
      setStatus("");
    } catch (e) { setStatus("open error: " + e.message); }
  }

  async function loadSource(source) {
    state.source = source;
    state.kind = source.kind || "video";
    state.durationUs = source.durationUs || 0;
    state.fps = source.fps || 30;
    state.inUs = 0;
    state.outUs = state.durationUs;
    state.keyframes = [];
    updateRangeInfo();
    $("editor").hidden = false;
    var info = source.name + " - " + (source.width || "?") + "x" + (source.height || "?") + " " + (source.videoCodec || "") + "/" + (source.audioCodec || "") + " " + ((state.durationUs / 1e6).toFixed(2)) + "s " + state.fps.toFixed(3) + "fps";
    $("video-info").textContent = info;
    renderMetadata(source);
    var detail = await api("GET", "/api/sources/" + source.id);
    var variant = detail.variant || "original";
    state.variant = variant;
    $("proxy-btn").hidden = (variant !== "proxy" || state.kind === "audio");
    if (state.kind === "audio") {
      if ($("frame-dl")) { $("frame-dl").hidden = true; }
      if ($("frame-preview")) { $("frame-preview").hidden = true; }
      if ($("kf-ticks")) { $("kf-ticks").hidden = true; }
    }
    if (variant === "proxy") { $("video-info").textContent = info + " [proxy]"; }
    $("player").src = "/api/sources/" + source.id + "/media?variant=" + variant;
    $("player").load();
    await pollKeyframes(source.id);
    $("player").addEventListener("loadedmetadata", function () { state.durationUs = Math.round(this.duration * 1000000) || state.durationUs; updateRangeInfo(); }, { once: true });
    $("editor").scrollIntoView({ behavior: "smooth" });
  }

  function kbps(value) {
    if (!value) { return "—"; }
    if (value >= 1000000) { return (Math.round(value / 100000) / 10) + " Mbps"; }
    return (Math.round(value / 1000) + " kbps");
  }

  function fmtRate(value) {
    if (value === null || value === undefined || value === "") { return "—"; }
    return String(value);
  }

  function renderMetadata(source) {
    var streams = source.streams || [];
    var meta = source.meta || {};
    var video = null, audio = null;
    streams.forEach(function (st) {
      if (st.type === "video" && !st.attached_pic && !video) { video = st; }
      if (st.type === "audio" && !audio) { audio = st; }
    });
    var rows = [
      ["コンテナ", meta.format_long_name || source.container || "—"],
      ["長さ", formatTime(source.durationUs || 0)],
      ["サイズ", source.size ? (Math.round(source.size / 1048576 * 10) / 10 + " MB") : "—"],
      ["全体ビットレート", kbps(source.bitRate)],
      ["映像", (source.videoCodec || "—") + " " + (video && video.profile ? "(" + video.profile + (video.level ? "@L" + video.level : "") + ")" : "")],
      ["解像度", source.width ? (source.width + "x" + source.height) : "—"],
      ["フレームレート", source.fps ? (Math.round(source.fps * 1000) / 1000 + " fps") : "—"],
      ["映像ビットレート", kbps(source.videoBitRate)],
      ["音声", source.audioCodec || "—"],
      ["音声ビットレート", kbps(source.audioBitRate)],
      ["サンプルレート", audio && audio.sample_rate ? (audio.sample_rate + " Hz") : "—"],
      ["チャンネル", audio && audio.channels ? (audio.channels + (audio.channel_layout ? " (" + audio.channel_layout + ")" : "")) : "—"],
      ["ピクセル形式", source.pixFmt || "—"],
      ["総フレーム数", video && video.nb_frames ? String(video.nb_frames) : "—"]
    ];
    var box = $("meta-summary");
    box.textContent = "";
    rows.forEach(function (row) {
      var span = document.createElement("span");
      span.textContent = row[0] + ": " + row[1];
      box.appendChild(span);
    });
    var detail = $("meta-detail");
    detail.textContent = "";
    var fmt = document.createElement("div");
    fmt.className = "stream-box";
    var fmtTitle = document.createElement("h4");
    fmtTitle.textContent = "コンテナ情報";
    fmt.appendChild(fmtTitle);
    [["format_name", meta.format_name], ["nb_streams", meta.nb_streams], ["start_time", meta.start_time],
     ["probe_score", meta.probe_score], ["duration", formatTime(source.durationUs || 0)]].forEach(function (kv) {
      var d = document.createElement("div");
      d.textContent = kv[0] + ": " + fmtRate(kv[1]);
      fmt.appendChild(d);
    });
    var tags = meta.tags || {};
    Object.keys(tags).forEach(function (key) {
      var d = document.createElement("div");
      d.textContent = "tag " + key + ": " + tags[key];
      fmt.appendChild(d);
    });
    detail.appendChild(fmt);
    streams.forEach(function (st) {
      var boxEl = document.createElement("div");
      boxEl.className = "stream-box";
      var title = document.createElement("h4");
      title.textContent = "#" + st.index + " " + st.type + " " + (st.codec || "") + (st.attached_pic ? " (attached_pic)" : "");
      boxEl.appendChild(title);
      var fields = [
        ["codec_long_name", st.codec_long_name], ["profile", st.profile], ["level", st.level],
        ["width x height", st.width ? st.width + "x" + st.height : null],
        ["pix_fmt", st.pix_fmt], ["field_order", st.field_order],
        ["avg_frame_rate", st.avg_frame_rate], ["r_frame_rate", st.r_frame_rate],
        ["bit_rate", st.bit_rate ? kbps(st.bit_rate) : null],
        ["nb_frames", st.nb_frames], ["duration", st.duration_us ? (st.duration_us / 1e6).toFixed(3) + "s" : null],
        ["sample_rate", st.sample_rate], ["channels", st.channels], ["channel_layout", st.channel_layout],
        ["color_space", st.color_space], ["color_transfer", st.color_transfer], ["color_primaries", st.color_primaries],
        ["bits_per_raw_sample", st.bits_per_raw_sample], ["start_time", st.start_time],
        ["default", st.default ? "yes" : "no"], ["forced", st.forced ? "yes" : "no"]
      ];
      fields.forEach(function (kv) {
        if (kv[1] === null || kv[1] === undefined || kv[1] === "") { return; }
        var d = document.createElement("div");
        d.textContent = kv[0] + ": " + kv[1];
        boxEl.appendChild(d);
      });
      var stTags = st.tags || {};
      Object.keys(stTags).forEach(function (key) {
        var d = document.createElement("div");
        d.textContent = "tag " + key + ": " + stTags[key];
        boxEl.appendChild(d);
      });
      detail.appendChild(boxEl);
    });
  }

  async function pollKeyframes(sourceId) {
    for (var i = 0; i < 600; i++) {
      var data = await api("GET", "/api/sources/" + sourceId + "/keyframes", null, false, 180000, true);
      if (data.state === "ready") { state.keyframes = data.keyframes || []; renderTicks(); updateRangeInfo(); return; }
      if (data.state === "error") { return; }
      await new Promise(function (r) { setTimeout(r, 500); });
    }
  }

  function renderTicks() {
    var box = $("kf-ticks");
    box.innerHTML = "";
    if (!state.durationUs) { return; }
    state.keyframes.forEach(function (kf) {
      if (kf < 0 || kf > state.durationUs) { return; }
      var s = document.createElement("span");
      s.style.left = (kf / state.durationUs * 100) + "%";
      box.appendChild(s);
    });
  }

  async function doUpload() {
    var input = $("upload-input");
    if (!input.files || !input.files.length) { return; }
    var form = new FormData();
    form.append("file", input.files[0]);
    $("upload-progress").textContent = "アップロード中...";
    try {
      var data = await api("POST", "/api/sources/upload", form, true, 1800000);
      $("upload-progress").textContent = "完了";
      await loadSource(data.source);
    } catch (e) { $("upload-progress").textContent = "失敗: " + e.message; }
  }

  var recentShowAll = false;
  var recentCache = [];

  function midEllipsis(name, limit) {
    var s = String(name || "");
    var lim = limit || 36;
    if (s.length <= lim) { return s; }
    var keep = lim - 1, head = Math.ceil(keep * 0.6), tail = keep - head;
    return s.slice(0, head) + "…" + s.slice(s.length - tail);
  }

  async function loadRecent() {
    try {
      var data = await api("GET", "/api/sources");
      recentCache = data.sources || [];
      var ul = $("recent-list");
      ul.innerHTML = "";
      var LIMIT = 8;
      var shown = recentShowAll ? recentCache : recentCache.slice(0, LIMIT);
      shown.forEach(function (s) {
        var li = document.createElement("li");
        var b = document.createElement("button");
        b.type = "button";
        b.textContent = midEllipsis(s.name, 34) + " (" + ((s.durationUs || 0) / 1e6).toFixed(1) + "s)";
        b.title = s.name;
        b.addEventListener("click", function () { loadSource(s); });
        li.appendChild(b);
        var x = document.createElement("button");
        x.type = "button";
        x.className = "tiny";
        x.textContent = "✕";
        x.title = "この履歴を削除";
        x.addEventListener("click", async function () {
          if (!window.confirm("「" + s.name + "」を一覧から削除しますか？（アップロードしたファイルは削除されますが、PC 上の元ファイルは残ります）")) { return; }
          try {
            await api("DELETE", "/api/sources/" + s.id);
            setStatus("履歴から削除しました");
            loadRecent();
          } catch (e) { setStatus("削除に失敗: " + e.message); }
        });
        li.appendChild(x);
        ul.appendChild(li);
      });
      if (recentCache.length > LIMIT) {
        var more = document.createElement("li");
        var mb = document.createElement("button");
        mb.type = "button";
        mb.textContent = recentShowAll ? "表示を減らす" : ("他 " + (recentCache.length - LIMIT) + " 件を表示");
        mb.addEventListener("click", function () { recentShowAll = !recentShowAll; loadRecent(); });
        more.appendChild(mb);
        ul.appendChild(more);
      }
    } catch (e) {}
  }

  async function loadLuts() {
    try {
      var data = await api("GET", "/api/luts");
      var sel = $("lut");
      sel.innerHTML = '<option value="">なし</option>';
      (data.luts || []).forEach(function (l) {
        var o = document.createElement("option");
        o.value = l.path; o.textContent = l.name;
        sel.appendChild(o);
      });
    } catch (e) {}
  }

  async function loadRoots() {
    try {
      var data = await api("GET", "/api/roots");
      var sel = $("roots");
      sel.innerHTML = "";
      (data.roots || []).forEach(function (r) {
        var o = document.createElement("option");
        o.value = r.path;
        o.textContent = (r.name || r.path) + " (" + r.path + ")";
        sel.appendChild(o);
      });
      sel.addEventListener("change", function () { browse(this.value); });
    } catch (e) {}
  }

  function parseCrop(text) {
    var m = /^(\d+):(\d+):(\d+):(\d+)$/.exec(String(text).trim());
    if (!m) { return null; }
    return { w: +m[1], h: +m[2], x: +m[3], y: +m[4] };
  }

  async function doExport() {
    if (!state.source) { return; }
    var mode = document.querySelector("input[name=mode]:checked").value;
    if (mode === "reencode" && !confirm("再エンコードは非無変換です。画質は完全一致しません。実行しますか？")) { return; }
    var options = { mode: mode, inSnap: $("in-snap").value, outMode: $("out-mode").value };
    if (mode === "reencode") {
      var lut = $("lut").value;
      if (lut) { options.lut = lut; }
      if ($("stabilize").checked) { options.stabilize = true; }
      var crop = parseCrop($("crop").value);
      if (crop) { options.crop = crop; }
      options.encoder = $("encoder").value;
      var vbr = parseInt($("video-bitrate").value, 10);
      if (vbr > 0) { options.videoBitrate = vbr; }
      var abr = parseInt($("audio-bitrate").value, 10);
      if (abr > 0) { options.audioBitrate = abr; }
      if ($("audio-reencode").checked) { options.audioReencode = true; }
    }
    var outPath = $("output-path").value.trim();
    if (outPath) { options.outputPath = outPath; }
    if ($("container").value) { options.container = $("container").value; }
    var btn = $("export-btn");
    btn.disabled = true;
    $("result").textContent = "";
    try {
      var data = await api("POST", "/api/exports", { sourceId: state.source.id, startUs: state.inUs, endUs: state.outUs, mode: mode, options: options });
      refreshJobs();
      await watchJob(data.jobId);
    } catch (e) {
      $("result").textContent = "失敗: " + e.message;
    } finally { btn.disabled = false; }
  }

  function renderJobResult(job) {
    var box = $("result");
    box.textContent = "";
    if (job.status === "done") {
      var r = job.result || {};
      var span = document.createElement("span");
      span.className = "ok";
      var extra = "";
      if (r.actualStartUs !== undefined) { extra = " / 実カット " + formatTime(r.actualStartUs) + " - " + formatTime(r.actualEndUs); }
      span.textContent = "完了: " + (r.outputPath || "") + " (" + (Math.round((r.bytes || 0) / 1048576 * 10) / 10) + " MB, " + (r.lossless ? "無変換" : "再エンコード") + extra + (r.note ? " / " + r.note : "") + ")";
      box.appendChild(span);
      if (r.outputPath) {
        var dl = document.createElement("a");
        dl.className = "tiny";
        dl.textContent = "書き出したファイルを保存";
        dl.href = "/api/fs/download?path=" + encodeURIComponent(r.outputPath);
        dl.setAttribute("download", "");
        box.appendChild(document.createElement("br"));
        box.appendChild(dl);
      }
      (r.warnings || []).forEach(function (w) {
        var div = document.createElement("div");
        div.className = "small";
        div.textContent = "警告: " + w;
        box.appendChild(div);
      });
    } else {
      var e2 = document.createElement("span");
      e2.className = "err";
      e2.textContent = "失敗: " + (job.error || job.status);
      box.appendChild(e2);
    }
  }

  async function pollJob(jobId, finish) {
    var misses = 0;
    for (var i = 0; i < 7200; i++) {
      try {
        var d = await api("GET", "/api/jobs/" + jobId, null, false, 0, true);
        var j = d.job;
        misses = 0;
        if (j.progress !== undefined && $("progress").firstChild) { $("progress").firstChild.style.width = Math.round(j.progress * 100) + "%"; }
        if (j.status === "done" || j.status === "error" || j.status === "cancelled") { finish(j); return; }
      } catch (e) {
        misses += 1;
        if (misses >= 5) { finish({ status: "error", error: "ジョブが見つかりません（サーバが再起動された可能性があります）" }); return; }
      }
      await new Promise(function (r) { setTimeout(r, 1500); });
    }
  }

  async function cancelActiveJob() {
    if (!state.activeJobId) { return; }
    try {
      await api("POST", "/api/jobs/" + state.activeJobId + "/cancel");
      setStatus("停止を要求しました");
    } catch (e) { setStatus("停止に失敗: " + e.message); }
  }

  var KIND_LABEL = { export: "書き出し", proxy: "プロキシ", sprite: "サムネイル", index: "索引", copy: "コピー", move: "移動" };
  var STATUS_LABEL = { queued: "待機中", running: "実行中", done: "完了", error: "失敗", cancelled: "キャンセル" };

  function kindLabel(k) { return KIND_LABEL[k] || k || "ジョブ"; }
  function statusLabel(s) { return STATUS_LABEL[s] || s || "?"; }

  function baseName(p) { return String(p || "").split(/[\\/]/).pop(); }

  async function refreshJobs() {
    var box = $("jobs-list");
    if (!box) { return; }
    try {
      var d = await api("GET", "/api/jobs?history=20", null, false, 0, true);
      var list = d.jobs || [];
      box.innerHTML = "";
      var running = 0, queued = 0;
      list.forEach(function (j) {
        if (j.status === "running") { running += 1; }
        if (j.status === "queued") { queued += 1; }
        var li = document.createElement("li");
        li.className = "job-" + (j.status || "queued");
        var head = document.createElement("div");
        head.className = "job-head";
        var pct = (j.status === "running" || j.status === "queued") && j.progress != null ? " " + Math.round(j.progress * 100) + "%" : "";
        head.textContent = kindLabel(j.kind) + " / " + statusLabel(j.status) + pct;
        li.appendChild(head);
        var name = j.sourceName || baseName((j.result || {}).outputPath) || "";
        var sub = document.createElement("div");
        sub.className = "job-sub";
        sub.textContent = name + (j.status === "queued" ? "（順番待ち）" : "");
        if (name || j.status === "queued") { li.appendChild(sub); }
        box.appendChild(li);
      });
      var sum = $("jobs-summary");
      if (sum) { sum.textContent = list.length ? (running + " 実行中 / " + queued + " 待機中 / 計 " + list.length) : "なし"; }
    } catch (e) {}
  }

  function watchJob(jobId) {
    return new Promise(function (resolve) {
      state.activeJobId = jobId;
      if ($("cancel-btn")) { $("cancel-btn").hidden = false; }
      var bar = $("progress");
      bar.innerHTML = "<div></div>";
      var finished = false;
      var es = new EventSource("/api/jobs/" + jobId + "/events");
      function finish(job) { if (finished) { return; } finished = true; try { es.close(); } catch (e) {} state.activeJobId = null; if ($("cancel-btn")) { $("cancel-btn").hidden = true; } renderJobResult(job); refreshJobs(); resolve(); }
      function onEvent(ev) {
        var data = {};
        try { data = JSON.parse(ev.data); } catch (e) {}
        if (data.progress !== undefined && bar.firstChild) { bar.firstChild.style.width = Math.round(data.progress * 100) + "%"; }
        if (ev.type === "log" && data.message) { setStatus(data.message); }
        if (ev.type === "done") { finish(data); }
      }
      es.addEventListener("state", onEvent);
      es.addEventListener("log", onEvent);
      es.addEventListener("done", onEvent);
      es.onerror = function () { pollJob(jobId, finish); };
      pollJob(jobId, finish);
    });
  }

  document.addEventListener("DOMContentLoaded", init);
})();
