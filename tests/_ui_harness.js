// Shared DOM/fetch stub for the UI behaviour tests.
//
// The inline script of web-qwen/index.html runs in a VM against this stub, so the real
// handlers are driven (not pattern-matched source).  load() can be called more than once
// with the same store to simulate a page reload with the browser's localStorage intact.
const fs = require("fs");
const vm = require("vm");

function load(opts) {
  opts = opts || {};
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
    const r = el("radio:" + v); r.value = v; r.name = "audioModeRadio"; return r;
  });
  // A real radio group unchecks its siblings; the stub has to do the same or a saved
  // audio mode would look unchanged while the "original" radio is still ticked.
  radios.forEach((r) => {
    let on = false;
    Object.defineProperty(r, "checked", {
      get() { return on; },
      set(v) { on = !!v; if (on) { radios.forEach((other) => { if (other !== r) other._setChecked(false); }); } },
    });
    r._setChecked = (v) => { on = !!v; };
  });
  radios[0].checked = true;
  const shiftButtons = [];
  ["orig", "added"].forEach((t) => [-1000, -100, -10, 10, 100, 1000].forEach((d) => {
    const b = el("btn:" + t + ":" + d); b.dataset = { shift: t, delta: String(d) }; shiftButtons.push(b);
  }));
  const document = {
    getElementById: (id) => el(id),
    querySelector(sel) {
      if (sel.indexOf("audioModeRadio") >= 0) {
        const m = sel.match(/\[value="([^"]+)"\]/);
        if (m) { return radios.filter((r) => r.value === m[1])[0] || null; }
        return radios.filter((r) => r.checked)[0] || null;
      }
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
  const store = opts.store || new Map();
  const sandbox = {
    console, setTimeout, clearTimeout, setInterval: () => 0, clearInterval: () => {},
    URLSearchParams, Promise, JSON, Math, Object, Array, String, Number, Boolean, RegExp, Error,
    Date: DateShim, Audio: FakeAudio, document,
    localStorage: {
      getItem: (k) => (store.has(k) ? store.get(k) : null),
      setItem: (k, v) => store.set(k, String(v)),
      removeItem: (k) => store.delete(k),
    },
    fetch: opts.fetch || (() => Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve("{}"), json: () => Promise.resolve({}) })),
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
  const target = (opts && opts.target) || process.argv[2] || "web-qwen/index.html";
  const html = fs.readFileSync(target, "utf8");
  const m = html.match(/<script>([\s\S]*?)<\/script>/);
  if (!m) { throw new Error("no inline script in " + target); }
  // expose the module-private bindings to the test only (the page itself is untouched)
  const probe = "\n;globalThis.__probe={state:()=>state,vid:()=>vid,prev:()=>({url:previewUrl,busy:previewBusy,orig:previewOrigSrc}),crop:()=>crop,ready:()=>settingsReady,lutReady:()=>lutListLoaded};";
  vm.runInContext(m[1] + probe, sandbox, { filename: target });
  return {
    sandbox, el, audios, store,
    probe: () => sandbox.__probe,
    step: () => { const q = rafQueue.splice(0); q.forEach((f) => f(0)); return q.length; },
    advance: (ms) => { clock += ms; },
    els,
  };
}

module.exports = { load };
