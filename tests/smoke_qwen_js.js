// Runtime smoke test: execute the inline script with a DOM stub and report
// top-level errors (e.g. a function that was never defined).
const { loadQwen } = require("./_qwen_stub.js");
const target = process.argv[2] || "web-qwen/index.html";
try {
  loadQwen(target);
  console.log("SMOKE OK: inline script executed without a top-level error");
  process.exit(0);
} catch (err) {
  console.log("SMOKE FAIL: " + (err && err.message ? err.message : String(err)));
  process.exit(1);
}
