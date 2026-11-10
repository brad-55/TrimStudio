// Behavioural tests for the audio timing panel (the class that leaked twice).
//
// The inline script runs in a VM with a DOM stub that keeps element identity and records
// event handlers, so the REAL handlers are driven instead of pattern-matching the source.
// The sync loop is stepped frame by frame with a controllable clock.
const fs = require("fs");
const vm = require("vm");
const target = process.argv[2] || "web-qwen/index.html";

let fails = 0;
function check(label, cond, detail) {
  console.log((cond ? "OK   " : "FAIL ") + label + (cond ? "" : "  " + (detail === undefined ? "" : detail)));
  if (!cond) { fails++; }
}

function load() {
  const els = new Map();
  function el(id) {
    if (els.has(id)) { return els.get(id); }
    const e = {
      id, style: {}, dataset: {}, value: "", textContent: "", innerHTML: "", hidden: false,
      checked: false, disabled: false, className: "", src: "", type: "", name: "",
      _h: {}, _plays: 0, _pauses: 0,
      addEventListener(type, fn) { (this._h[type] = this._h[type] || []).push(fn); },
      removeEventListener() {},
      setAttribute(k, v) { this["attr_" + k] = v; if (k === "src") { this.src = v; } },
      getAttribute(k) { return this["attr_" + k] === undefined ? null : this["attr_" + k]; },
      removeAttribute(k) { delete this["attr_" + k]; },
      dispatch(type, ev) {
        (this._h[type] || []).forEach((f) => f(Object.assign({ target: this, preventDefault() {}, stopPropagation() {} }, ev || {})));
      },
      querySelector() { return el(id + ":q"); }, querySelectorAll() { return []; },
      appendChild() {}, removeChild() {}, remove() {}, focus() {}, click() {}, load() {},
      getBoundingClientRect() { return { left: 0, top: 0, right: 100, bottom: 100, width: 100, height: 100 }; },
      classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
      play() { this._plays++; this.paused = false; return { catch() {} }; },
      pause() { this._pauses++; this.paused = true; },
      getContext() { return null; },
      setPointerCapture() {}, releasePointerCapture() {},
    };
    els.set(id, e);
    return e;
  }
  const radios = ["original", "added", "bothTracks", "bothMix", "mute"].map((v) => {
    const r = el("radio:" + v); r.value = v; r.name = "audioModeRadio"; r.checked = (v === "original"); return r;
  });
  const shiftButtons = [];
  ["orig", "added"].forEach((t) => [-1000, -100, -10, 10, 100, 1000].forEach((d) => {
    const b = el("btn:" + t + ":" + d); b.dataset = { shift: t, delta: String(d) }; shiftButtons.push(b);
  }));
  const document = {
    getElementById: (id) => el(id),
    querySelector(sel) {
      if (sel.indexOf("audioModeRadio") >= 0) { return radios.filter((r) => r.checked)[0] || null; }
      return el("sel:" + sel);
    },
    querySelectorAll(sel) {
      if (sel.indexOf("audioModeRadio") >= 0) { return radios; }
      if (sel.indexOf("[data-shift") >= 0) {
        const m = sel.match(/data-shift="(orig|added)"/);
        return m ? shiftButtons.filter((b) => b.dataset.shift === m[1]) : shiftButtons;
      }
      return [];
    },
    createElement: () => el("created:" + Math.random()),
    addEventListener() {}, body: el("body"),
    documentElement: { clientWidth: 360, scrollWidth: 360, style: {} },
  };
  // audio elements record every seek, rate change and pause so the loop can be judged
  const audios = [];
  function FakeAudio() {
    this.paused = true; this.volume = 1; this.muted = false; this.src = ""; this.readyState = 1;
    this.duration = 12; this.preload = ""; this.dataset = {}; this._writes = []; this._plays = 0;
    this._pauses = 0; this._rate = 1; this._h = {}; this._ct = 0;
    const self = this;
    Object.defineProperty(this, "currentTime", {
      get() { return self._ct; },
      set(v) { self._writes.push(v); self._ct = v; },
    });
    Object.defineProperty(this, "playbackRate", {
      get() { return self._rate; },
      set(v) { self._rate = v; },
    });
    this.addEventListener = function (t, f) { (self._h[t] = self._h[t] || []).push(f); };
    this.removeEventListener = function () {};
    this.setAttribute = function (k, v) { self["attr_" + k] = v; if (k === "src") { self.src = v; } };
    this.getAttribute = function (k) { return self["attr_" + k] === undefined ? null : self["attr_" + k]; };
    this.removeAttribute = function (k) { delete self["attr_" + k]; };
    this.play = function () { self._plays++; self.paused = false; return { catch() {} }; };
    this.pause = function () { self._pauses++; self.paused = true; };
    this.load = function () {};
    audios.push(this);
  }
  const rafQueue = [];
  let clock = 1700000000000;
  const RealDate = Date;
  function DateShim() { return new RealDate(); }
  DateShim.now = () => clock; DateShim.parse = RealDate.parse; DateShim.UTC = RealDate.UTC;
  const store = new Map();
  const sandbox = {
    console, setTimeout, clearTimeout, setInterval: () => 0, clearInterval: () => {},
    URLSearchParams, Promise, JSON, Math, Object, Array, String, Number, Boolean, RegExp, Error,
    Date: DateShim, Audio: FakeAudio, document,
    localStorage: {
      getItem: (k) => (store.has(k) ? store.get(k) : null),
      setItem: (k, v) => store.set(k, String(v)),
      removeItem: (k) => store.delete(k),
    },
    fetch: () => Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve("{}"), json: () => Promise.resolve({}) }),
    EventSource: class { constructor() {} addEventListener() {} close() {} },
    IntersectionObserver: class { constructor() {} observe() {} unobserve() {} },
    confirm: () => true, alert: () => {}, prompt: () => null,
    navigator: { userAgent: "node" }, location: { search: "", href: "http://127.0.0.1:8003/" },
    screen: { width: 360 }, visualViewport: { scale: 1, width: 360 },
    requestAnimationFrame: (fn) => { rafQueue.push(fn); return rafQueue.length; },
    cancelAnimationFrame: () => {},
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  sandbox.self = sandbox;
  sandbox.window.addEventListener = () => {};
  sandbox.window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
  sandbox.Image = function () { return el("image"); };
  vm.createContext(sandbox);
  const html = fs.readFileSync(target, "utf8");
  const m = html.match(/<script>([\s\S]*?)<\/script>/);
  if (!m) { throw new Error("no inline script in " + target); }
  // expose the module-private bindings to the test only (the page itself is untouched)
  const probe = "\n;globalThis.__probe={state:()=>state,vid:()=>vid,prev:()=>({url:previewUrl,busy:previewBusy,orig:previewOrigSrc})};";
  vm.runInContext(m[1] + probe, sandbox, { filename: target });
  return {
    sandbox, el, audios,
    probe: () => sandbox.__probe,
    step: () => { const q = rafQueue.splice(0); q.forEach((f) => f(0)); return q.length; },
    advance: (ms) => { clock += ms; },
    els,
  };
}
(async () => {
const H = load();
const $ = H.el;
const S = H.sandbox;
const P = H.probe();
if (!P) { console.log("FAIL the probe is unavailable"); process.exit(1); }
const vid = P.vid();

// --- A. the jog sliders are relative and never move on their own ---------------------
// --- A. the jog sliders are relative and never move on their own ---------------------
S.updateAudioUI();
const range = $("origShiftRange");
const fine = $("origShiftFine");
$("origShiftInp").value = "0";
S.updateAudioUI();
range.dispatch("pointerdown");
range.value = "25";
range.dispatch("input");
check("jog: dragging right raises the value by the delta", String($("origShiftInp").value) === "25", $("origShiftInp").value);
range.dispatch("pointerup");
check("jog: the handle returns to the centre on release", Number(range.value) === 0, range.value);
$("origShiftInp").value = "90";
$("origShiftInp").dispatch("input");
check("typing: the coarse jog does not move", Number(range.value) === 0, range.value);
check("typing: the fine jog does not move", Number(fine.value) === 0, fine.value);
check("typing: the readout follows the typed value", String($("origShiftVal").textContent).indexOf("90") >= 0, $("origShiftVal").textContent);
check("typing: the value reaches the state", (P.state().audioShiftMs || 0) === 90, P.state().audioShiftMs);
range.dispatch("pointerdown");
range.value = "-30";
range.dispatch("input");
check("jog: dragging left lowers the value by the delta", String($("origShiftInp").value) === "60", $("origShiftInp").value);
range.dispatch("pointerup");

// --- F. the preview is a baked proxy loaded as ONE element ---------------------------
function ok(data) { return { ok: true, status: 200, text: async () => "", json: async () => data }; }
function status(code, data) { return { ok: false, status: code, text: async () => "", json: async () => data }; }
function defer() { return new Promise((r) => setTimeout(r, 0)); }
vid.play = function () { vid._plays = (vid._plays || 0) + 1; vid.paused = false; return { catch() {} }; };

S.updateAudioUI();
check("preview: the apply button exists", !!$("previewApplyBtn"));
check("preview: revert starts hidden", $("previewRevertBtn").hidden === true);
check("preview: the state starts as 未反映", String($("previewState").textContent).indexOf("未反映") >= 0, $("previewState").textContent);

P.state().source = { id: "s1" };
S.updateAudioUI();
const plays0 = vid._plays || 0;
S.fetch = async () => ok({ ok: true, cached: true, url: "/api/preview/media/aaaa.mp4", sourceTimelineOffsetUs: 0, outputStartOffsetUs: 0 });
await S.applyPreview();
check("preview: a cached proxy is loaded into the element",
      String(vid.src).indexOf("/api/preview/media/") >= 0, vid.src);
check("preview: revert becomes visible after applying", $("previewRevertBtn").hidden === false);
check("preview: applying never calls play() (iOS gesture is gone)",
      (vid._plays || 0) === plays0, (vid._plays || 0) - plays0);
check("preview: the state reports 反映済み", String($("previewState").textContent).indexOf("反映済み") >= 0, $("previewState").textContent);

// changing a value after applying must mark the preview as stale, not silently lie
S.setAudioShift("orig", 180);
check("preview: a changed shift is marked 未反映（設定が変更されました）",
      String($("previewState").textContent).indexOf("未反映（設定が変更されました）") >= 0, $("previewState").textContent);

// revert puts the original source back
S.revertPreview();
check("preview: revert restores the source", String(vid.src).indexOf("/api/preview/media/") < 0, vid.src);
check("preview: revert hides itself", $("previewRevertBtn").hidden === true);
check("preview: revert resets the state", String($("previewState").textContent).indexOf("未反映") >= 0, $("previewState").textContent);

// a fresh build returns a job id and is polled to completion
const calls = [];
S.fetch = async (url) => {
  calls.push(String(url));
  if (String(url).indexOf("/api/preview/build") >= 0) return ok({ ok: true, jobId: "j1" });
  return ok({ job: { status: "done", result: { url: "/api/preview/media/bbbb.mp4" } } });
};
await S.applyPreview();
check("preview: a build job is polled once", calls.filter((u) => u.indexOf("/api/jobs/") >= 0).length === 1, calls.join(","));
check("preview: the polled result is loaded", String(vid.src).indexOf("/api/preview/media/bbbb.mp4") >= 0, vid.src);

// 409 proxy_required: wait for the proxy job, then retry once
S.revertPreview();
let buildPosts = 0;
S.fetch = async (url) => {
  const isBuild = String(url).indexOf("/api/preview/build") >= 0;
  if (isBuild) {
    buildPosts++;
    if (buildPosts === 1) return status(409, { ok: false, code: "proxy_required", proxyJobId: "p1" });
    return ok({ ok: true, cached: true, url: "/api/preview/media/cccc.mp4" });
  }
  return ok({ job: { status: "done", result: {} } });
};
await S.applyPreview();
check("preview: proxy_required retries the build exactly once", buildPosts === 2, buildPosts);
check("preview: the retry result is loaded", String(vid.src).indexOf("/api/preview/media/cccc.mp4") >= 0, vid.src);

// a failure keeps the old source and reports it
S.revertPreview();
const srcBefore = vid.src;
S.fetch = async () => status(400, { ok: false, message: "boom" });
await S.applyPreview();
check("preview: a failure leaves the element alone", vid.src === srcBefore, vid.src);
check("preview: a failure is reported", String($("previewState").textContent).indexOf("失敗") >= 0, $("previewState").textContent);

// a second tap while the build runs must not start a second job (the button is disabled)
S.revertPreview();
let releaseBuild;
const buildGate = new Promise((r) => { releaseBuild = r; });
let taps = 0;
S.fetch = (url) => {
  if (String(url).indexOf("/api/preview/build") >= 0) {
    taps++;
    return buildGate.then(() => ok({ ok: true, cached: true, url: "/api/preview/media/eeee.mp4" }));
  }
  return ok({ job: { status: "done", result: {} } });
};
const running = S.applyPreview();
const ignored = S.applyPreview();
check("preview: the apply button is disabled while generating", $("previewApplyBtn").disabled === true);
check("preview: a second tap while generating is ignored", taps === 1, taps);
releaseBuild();
await running;
await ignored;
check("preview: the apply button is enabled again after the build", $("previewApplyBtn").disabled === false);
check("preview: the ignored second tap did not load another url",
      String(vid.src).indexOf("/api/preview/media/eeee.mp4") >= 0, vid.src);

console.log(fails ? "RESULT: FAIL(" + fails + ")" : "RESULT: OK");
process.exit(fails ? 1 : 0);
})();
