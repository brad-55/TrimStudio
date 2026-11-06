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
// band = half of the 72px bar (the boundary between the playhead zone and the IN/OUT zone)
const T = (px, py, inX, outX, playX, last, band) => pick(px, py, playX === undefined ? 500 : playX, inX, outX, last || null, band === undefined ? 36 : band);

// --- the playhead handle lives in the TOP band ---
check("top: on the playhead handle", T(500, 15, 200, 700) === "play");
check("top: +15px still the playhead", T(515, 15, 200, 700) === "play");
check("top: -15px still the playhead", T(485, 15, 200, 700) === "play");
check("top: stays in the top band just above the middle", T(500, 35, 200, 700) === "play");
check("top: far from the handle -> nothing", T(521, 15, 200, 700) === null);
check("top: above IN but IN handle is at the bottom -> nothing", T(200, 15, 200, 700) === null);

// --- IN and OUT handles live in the LOWER band ---
check("bottom: on the IN handle", T(200, 50, 200, 700) === "in");
check("bottom: +15px still IN", T(215, 50, 200, 700) === "in");
check("bottom: the middle starts the lower band", T(200, 36, 200, 700) === "in");
check("bottom: on the OUT handle", T(700, 50, 200, 700) === "out");
check("bottom: -15px still OUT", T(685, 50, 200, 700) === "out");
check("bottom: empty area -> nothing", T(450, 50, 200, 700) === null);
check("bottom: below the playhead -> nothing (its handle is on top)", T(500, 50, 200, 700) === null);
check("bottom: far from everything -> nothing", T(20, 60, 200, 700) === null);

// --- overlapping handles ---
check("overlap: nearer handle wins", T(205, 50, 200, 220) === "in");
check("overlap: nearer handle wins (out side)", T(215, 50, 200, 220) === "out");
check("overlap: last grabbed wins", T(210, 50, 200, 220, 500, "out") === "out");
check("overlap: last grabbed wins (in)", T(210, 50, 200, 220, 500, "in") === "in");

// --- the rest of the bar is inert ---
check("no seek by tapping empty space", T(400, 15, 200, 700) === null && T(400, 50, 200, 700) === null);


// --- exact boundaries of the grab area (40px wide -> +/-20) ---
check("boundary: +20px still hits the playhead", T(520, 15, 200, 700) === "play");
check("boundary: +21px misses the playhead", T(521, 15, 200, 700) === null);
check("boundary: -20px still hits the playhead", T(480, 15, 200, 700) === "play");
check("boundary: -21px misses the playhead", T(479, 15, 200, 700) === null);
check("boundary: +20px still hits IN", T(220, 50, 200, 700) === "in");
check("boundary: +21px misses IN", T(221, 50, 200, 700) === null);
check("boundary: -20px still hits OUT", T(680, 50, 200, 700) === "out");
check("boundary: -21px misses OUT", T(679, 50, 200, 700) === null);

console.log("RESULT:", fails === 0 ? "OK" : "FAIL(" + fails + ")");
process.exit(fails === 0 ? 0 : 1);
