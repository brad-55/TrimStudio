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
  const probe = "\n;globalThis.__probe={state:()=>state,vid:()=>vid,orig:()=>origAudio,"
    + "added:()=>addedAudio,active:()=>auditionActive,audio:()=>audios};";
  vm.runInContext(m[1] + probe, sandbox, { filename: target });
  return {
    sandbox, el, audios,
    probe: () => sandbox.__probe,
    step: () => { const q = rafQueue.splice(0); q.forEach((f) => f(0)); return q.length; },
    advance: (ms) => { clock += ms; },
    els,
  };
}

const H = load();
const $ = H.el;
const S = H.sandbox;
const P = H.probe();
if (!P) { console.log("FAIL the probe is unavailable"); process.exit(1); }

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

// --- B. the timing switch controls the settings box ----------------------------------
S.setAuditionToggle(false);
check("toggle: OFF hides the settings box", $("audioTimingBox").hidden === true, $("audioTimingBox").hidden);
check("toggle: OFF shows the OFF label", $("auditionState").textContent === "OFF", $("auditionState").textContent);
S.setAuditionToggle(true);
check("toggle: ON shows the settings box", $("audioTimingBox").hidden === false, $("audioTimingBox").hidden);
check("toggle: ON shows the ON label", $("auditionState").textContent === "ON", $("auditionState").textContent);

// --- C. the preview sync loop stays smooth ------------------------------------------
P.state().source = { id: "s1", durationUs: 12e6 };
P.state().inUs = 0;
P.state().addedSource = null;
$("auditionToggle").checked = true;
S.setAudioShift("orig", 0);
S.startAudition();
check("sync: the audition starts", P.active() === true);
const o = P.orig();
check("sync: the audio track is created", !!o);
const writes0 = o._writes.length;
const v = P.vid();
v.src = "/api/sources/s1/media";
v.paused = false;
v.currentTime = 2;
for (let i = 0; i < 40; i++) { v.currentTime = 2 + i * 0.001; S.syncAudition(false); }
check("sync: the playback rate is never modulated", o.playbackRate === 1, o.playbackRate);
check("sync: an in-sync track is not re-seeked", o._writes.length - writes0 <= 1, (o._writes.length - writes0));
// a burst of forced syncs must be throttled by the cooldown
const writes1 = o._writes.length;
for (let i = 0; i < 25; i++) { S.syncAudition(true); }
check("sync: a burst of forced syncs is throttled", o._writes.length - writes1 <= 2, (o._writes.length - writes1));
// a real desync must be corrected
H.advance(1000);
v.currentTime = 9;
const writes2 = o._writes.length;
S.syncAudition(false);
check("sync: a real desync (7s) is corrected", o._writes.length - writes2 === 1, (o._writes.length - writes2));
// while the target is still negative the track stays silent, parked at the head
const pauses0 = o._pauses;
S.setAudioShift("orig", 5000);
v.currentTime = 1;
for (let i = 0; i < 10; i++) { S.syncAudition(false); }
check("hold: the track is silent while it waits", o.volume === 0, o.volume);
check("hold: the waiting track stays silent and parked at the head",
      o.volume === 0 && (o.currentTime <= 0.05 || o.seeking === true),
      "vol=" + o.volume + " t=" + o.currentTime);
check("hold: parking pauses at most once (no per-frame pause churn)",
      o._pauses - pauses0 <= 1, "pauses=" + (o._pauses - pauses0));
check("hold: the rate stays 1", o.playbackRate === 1, o.playbackRate);
S.stopAudition();
check("sync: stopping clears the active flag", P.active() === false, P.active());
check("sync: stopping playback keeps the master switch ON (export still shifts)",
      $("auditionToggle").checked === true, $("auditionToggle").checked);
// turning the switch OFF yourself must still disable it
$("auditionToggle").checked = false;
$("auditionToggle").dispatch("change");
check("toggle: turning it off by hand disables the settings",
      $("auditionToggle").checked === false && $("audioTimingBox").hidden === true,
      $("auditionToggle").checked + "/" + $("audioTimingBox").hidden);

// --- D. a held onset is never lost (the "plays at the original timing" regression) ---
S.stopAudition();
S.setAudioShift("orig", 1500);
P.state().inUs = 0;
v.paused = false;
v.currentTime = 0;
$("auditionToggle").checked = true;
S.startAudition();
check("held onset: the delayed track starts silent", o.volume === 0, o.volume);
check("held onset: the pending flag is armed", o.dataset.head === "1", o.dataset.head);
const w3 = o._writes.length;
o.readyState = 1;
o.seeking = true;
v.currentTime = 1.6;
S.syncAudition(false);
check("held onset: a seeking element is not aligned yet", o._writes.length === w3, o._writes.length - w3);
check("held onset: the flag survives a failed alignment", o.dataset.head === "1", o.dataset.head);
o.seeking = false;
S.syncAudition(false);
check("held onset: the alignment is retried and lands on the target",
      o._writes.length === w3 + 1 && Math.abs(o._writes[o._writes.length - 1] - 0.1) < 0.06,
      o._writes[o._writes.length - 1]);
check("held onset: the flag clears once aligned", o.dataset.head === undefined, o.dataset.head);
const w4 = o._writes.length;
S.setAudioShift("orig", 0);
S.syncAudition(false);
check("a changed shift bypasses the churn guard", o._writes.length === w4 + 1, o._writes.length - w4);
const w5 = o._writes.length;
S.syncAudition(false);
S.syncAudition(false);
check("the same target is still throttled", o._writes.length - w5 <= 1, o._writes.length - w5);
S.stopAudition();

// --- E. small drift is left alone, only a real desync seeks ---------------------
S.stopAudition();
S.setAudioShift("orig", 0);
P.state().source = { id: "s1", durationUs: 12e6 };
P.state().inUs = 0;
P.state().addedSource = null;
$("auditionToggle").checked = true;
v.paused = false;
v.currentTime = 2;
S.startAudition();
const oo = P.orig();
oo.currentTime = 2;            // exactly in sync
oo.playbackRate = 1;
S.syncAudition(false);
check("smooth: in sync means rate 1", oo.playbackRate === 1, oo.playbackRate);

oo.currentTime = 2.06;         // 60 ms ahead: below the ear's threshold
const wSmall = oo._writes.length;   // count AFTER positioning the track
S.syncAudition(false);
check("stable: a 60ms drift is left alone (no seek, no rate wobble)",
      oo._writes.length === wSmall && oo.playbackRate === 1,
      "writes=" + (oo._writes.length - wSmall) + " rate=" + oo.playbackRate);
check("stable: the rate is never modulated", oo.playbackRate === 1, oo.playbackRate);

H.advance(2000);
oo.currentTime = 3.5;          // 1.5 s: genuinely out of sync
const wBig = oo._writes.length;
S.syncAudition(false);
check("desync: a 1.5s error seeks once", oo._writes.length === wBig + 1,
      oo._writes.length - wBig);

// a target past the end must never park the track on its last frames
H.advance(2000);
S.setAudioShift("orig", -9000);   // target = t + 9s, way past the 12s duration
v.currentTime = 10;
S.syncAudition(true);
const last = oo._writes[oo._writes.length - 1];
check("clamp: a seek past the end is clamped inside the media",
      last !== undefined && last <= 12 && last >= 0, "wrote " + last);
S.stopAudition();

console.log(fails ? "RESULT: FAIL(" + fails + ")" : "RESULT: OK");
process.exit(fails ? 1 : 0);
