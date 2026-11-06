// Unit tests for the timeline handle (◆) hit testing.
const { loadQwen } = require("./_qwen_stub.js");
const target = process.argv[2] || "web-qwen/index.html";
const { sandbox } = loadQwen(target);
const pick = sandbox.pickTimelineTarget;

let fails = 0;
function check(label, cond, detail) {
  console.log((cond ? "OK   " : "FAIL ") + label + (cond ? "" : "  " + detail));
  if (!cond) { fails++; }
}
if (typeof pick !== "function") {
  console.log("FAIL pickTimelineTarget is not defined");
  process.exit(1);
}

// bar: playhead at 500, IN at 200, OUT at 700 (px), bar height 48 (handle zones split at y=22)
const T = (px, py, inX, outX, playX, last) => pick(px, py, playX === undefined ? 500 : playX, inX, outX, last || null);

// --- the playhead handle lives in the TOP band ---
check("top: on the playhead handle", T(500, 10, 200, 700) === "play");
check("top: +15px still the playhead", T(515, 10, 200, 700) === "play");
check("top: -15px still the playhead", T(485, 10, 200, 700) === "play");
check("top: 21px stays in the top band", T(500, 21, 200, 700) === "play");
check("top: far from the handle -> nothing", T(521, 10, 200, 700) === null);
check("top: above IN but IN handle is at the bottom -> nothing", T(200, 10, 200, 700) === null);

// --- IN and OUT handles live in the LOWER band ---
check("bottom: on the IN handle", T(200, 34, 200, 700) === "in");
check("bottom: +15px still IN", T(215, 34, 200, 700) === "in");
check("bottom: 22px starts the lower band", T(200, 22, 200, 700) === "in");
check("bottom: on the OUT handle", T(700, 34, 200, 700) === "out");
check("bottom: -15px still OUT", T(685, 34, 200, 700) === "out");
check("bottom: empty area -> nothing", T(450, 34, 200, 700) === null);
check("bottom: below the playhead -> nothing (its handle is on top)", T(500, 34, 200, 700) === null);
check("bottom: far from everything -> nothing", T(20, 40, 200, 700) === null);

// --- overlapping handles ---
check("overlap: nearer handle wins", T(205, 34, 200, 220) === "in");
check("overlap: nearer handle wins (out side)", T(215, 34, 200, 220) === "out");
check("overlap: last grabbed wins", T(210, 34, 200, 220, 500, "out") === "out");
check("overlap: last grabbed wins (in)", T(210, 34, 200, 220, 500, "in") === "in");

// --- the rest of the bar is inert ---
check("no seek by tapping empty space", T(400, 10, 200, 700) === null && T(400, 34, 200, 700) === null);


// --- exact boundaries of the grab area (40px wide -> +/-20) ---
check("boundary: +20px still hits the playhead", T(520, 10, 200, 700) === "play");
check("boundary: +21px misses the playhead", T(521, 10, 200, 700) === null);
check("boundary: -20px still hits the playhead", T(480, 10, 200, 700) === "play");
check("boundary: -21px misses the playhead", T(479, 10, 200, 700) === null);
check("boundary: +20px still hits IN", T(220, 34, 200, 700) === "in");
check("boundary: +21px misses IN", T(221, 34, 200, 700) === null);
check("boundary: -20px still hits OUT", T(680, 34, 200, 700) === "out");
check("boundary: -21px misses OUT", T(679, 34, 200, 700) === null);

console.log("RESULT:", fails === 0 ? "OK" : "FAIL(" + fails + ")");
process.exit(fails === 0 ? 0 : 1);
