// Shared DOM stub for running the TrimStudio inline script under Node.
const fs = require("fs");
const vm = require("vm");

function stubEl() {
  const base = {
    style: {}, dataset: {}, children: [], options: [], value: "", textContent: "", innerHTML: "",
    hidden: false, checked: false, disabled: false, className: "", src: "", href: "", title: "",
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    addEventListener() {}, removeEventListener() {}, appendChild() {}, removeChild() {}, remove() {},
    setAttribute() {}, getAttribute() { return null; }, removeAttribute() {},
    querySelector() { return stubEl(); }, querySelectorAll() { return []; },
    getBoundingClientRect() { return { left: 0, top: 0, right: 100, bottom: 100, width: 100, height: 100 }; },
    focus() {}, click() {}, load() {}, play() {}, pause() {},
    setPointerCapture() {}, releasePointerCapture() {},
    getContext() { return null; },
  };
  return new Proxy(base, {
    get(t, k) { if (k in t) { return t[k]; } return () => {}; },
    set(t, k, v) { t[k] = v; return true; },
  });
}

function loadQwen(htmlPath) {
  const html = fs.readFileSync(htmlPath, "utf8");
  const m = html.match(/<script>([\s\S]*?)<\/script>/);
  if (!m) { throw new Error("no <script> block found in " + htmlPath); }
  const code = m[1];
  const sandbox = {
    console,
    setTimeout, clearTimeout,
    setInterval: () => 0, clearInterval: () => {},
    URLSearchParams, Promise, JSON, Math, Date, Object, Array, String, Number, Boolean, RegExp, Error,
    document: {
      getElementById() { return stubEl(); },
      querySelector() { return stubEl(); },
      querySelectorAll() { return []; },
      createElement() { return stubEl(); },
      addEventListener() {},
      body: stubEl(),
      documentElement: { clientWidth: 360, scrollWidth: 360, style: {} },
    },
    localStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
    fetch: () => Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve("{}"), json: () => Promise.resolve({}) }),
    EventSource: class { constructor() {} addEventListener() {} close() {} },
    IntersectionObserver: class { constructor() {} observe() {} unobserve() {} },
    confirm: () => true, alert: () => {}, prompt: () => null,
    navigator: { userAgent: "node" },
    location: { search: "", href: "http://127.0.0.1:8003/" },
    screen: { width: 360 },
    visualViewport: { scale: 1, width: 360 },
    requestAnimationFrame: (f) => setTimeout(f, 0),
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  sandbox.window.addEventListener = () => {};
  sandbox.window.matchMedia = () => ({ matches: false, addEventListener() {} });
  vm.createContext(sandbox);
  vm.runInContext(code, sandbox, { filename: htmlPath, timeout: 15000 });
  return { sandbox, code };
}

module.exports = { loadQwen, stubEl };
