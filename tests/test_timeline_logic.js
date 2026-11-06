// Unit tests for the timeline decision logic (extracted from the inline script).
const { loadQwen } = require("./_qwen_stub.js");
const target = process.argv[2] || "web-qwen/index.html";
const { sandbox } = loadQwen(target);
const pick = sandbox.pickTimelineTarget;
const resolve = sandbox.resolveDrag;

let fails = 0;
function check(label, cond, detail) {
  console.log((cond ? "OK   " : "FAIL ") + label + (cond ? "" : "  " + detail));
  if (!cond) { fails++; }
}
if (typeof pick !== "function" || typeof resolve !== "function") {
  console.log("FAIL timeline helpers are not defined");
  process.exit(1);
}

const T = (x, inX, outX, row, last, lock) => pick(x, 1000, inX, outX, row, last, !!lock);

check("seek row far -> seek", T(500, 100, 700, "seek", null) === "seek");
check("trim row +15px -> in", T(115, 100, 700, "trim", null) === "in");
check("trim row -15px -> in", T(85, 100, 700, "trim", null) === "in");
check("trim row +15px -> out", T(715, 100, 700, "trim", null) === "out");
check("seek row near in -> in", T(115, 100, 700, "seek", null) === "in");
check("seek row near out -> out", T(715, 100, 700, "seek", null) === "out");
check("trim row middle (gap 600) -> range", T(500, 100, 700, "trim", null) === "range");
check("trim row middle (gap 30) -> none", T(500, 100, 130, "trim", null) === "none");
check("close handles sticky in", T(115, 100, 130, "trim", "in") === "in");
check("close handles sticky out", T(115, 100, 130, "trim", "out") === "out");
check("close handles no sticky -> out", T(115, 100, 130, "trim", null) === "out");
check("only out in range -> out", T(125, 100, 145, "trim", null) === "out");
check("locked trim near in -> none", T(115, 100, 700, "trim", null, true) === "none");
check("locked trim middle -> none", T(500, 100, 700, "trim", null, true) === "none");
check("locked seek middle -> seek", T(500, 100, 700, "seek", null, true) === "seek");
check("locked seek near in -> seek", T(115, 100, 700, "seek", null, true) === "seek");
check("dead zone 7px -> tap", resolve(7) === "tap");
check("dead zone -7px -> tap", resolve(-7) === "tap");
check("dead zone 8px -> drag", resolve(8) === "drag");
check("dead zone 20px -> drag", resolve(20) === "drag");


// event ordering: a lostpointercapture style cancel after a committed pointerup
// must not roll anything back (tlDrag is cleared before the commit).
check("cancel after up is a no-op", (function () {
  sandbox.tlUp({ clientX: 0 });
  const a = sandbox.tlState();
  sandbox.tlCancel();
  const b = sandbox.tlState();
  return a.inUs === b.inUs && a.outUs === b.outUs && b.dragging === false;
})());
// pure seeks stay out of the undo history; IN/OUT changes are recorded
sandbox.pushUndo("再生位置", { inUs: 0, outUs: 10, curUs: 0 }, { inUs: 0, outUs: 10, curUs: 5 });
check("pure seek is not undoable", sandbox.tlState().undo === 0, sandbox.tlState().undo);
sandbox.pushUndo("IN", { inUs: 0, outUs: 10, curUs: 5 }, { inUs: 2, outUs: 10, curUs: 5 });
check("IN change is undoable", sandbox.tlState().undo === 1, sandbox.tlState().undo);
sandbox.undo();
check("undo restores and fills redo", sandbox.tlState().undo === 0 && sandbox.tlState().redo === 1);

console.log("RESULT:", fails === 0 ? "OK" : "FAIL(" + fails + ")");
process.exit(fails === 0 ? 0 : 1);
