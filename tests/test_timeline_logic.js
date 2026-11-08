// Timeline handle hit testing (design refreshed by the local Qwen).
const { loadQwen } = require("./_qwen_stub.js");
const target = process.argv[2] || "web-qwen/index.html";
const { sandbox } = loadQwen(target);
const pick = sandbox.pickTimelineTarget;

let fails = 0;
function check(label, cond, detail) {
  console.log((cond ? "OK   " : "FAIL ") + label + (cond ? "" : "  " + detail));
  if (!cond) { fails++; }
}
if (typeof pick !== "function") { console.log("FAIL pickTimelineTarget is not defined"); process.exit(1); }

// bar: playhead at 500, IN at 200, OUT at 700; 96px tall -> the zone split sits at ~44px
const BAND = 44;
const T = (px, py, inX = 200, outX = 700, playX = 500, last = null, band = BAND) =>
  pick(px, py, playX, inX, outX, last, band);

// --- the playhead knob lives in the top zone and is the only target there ---
check("top: on the playhead knob", T(500, 15) === "play");
check("top: +15px still the playhead", T(515, 15) === "play");
check("top: -15px still the playhead", T(485, 15) === "play");
check("top: +23px still the playhead", T(523, 15) === "play");
check("top: +25px is empty", T(525, 15) === null);
check("top: just above the split", T(500, BAND - 1) === "play");
check("top: the IN column does not respond in the top zone", T(200, 15) === null);
check("top: empty area is inert", T(400, 15) === null);

// --- IN and OUT knobs live in the bottom zone ---
check("bottom: on the IN knob", T(200, 70) === "in");
check("bottom: +15px still IN", T(215, 70) === "in");
check("bottom: -15px still IN", T(185, 70) === "in");
check("bottom: +25px is empty", T(225, 70) === null);
check("bottom: on the OUT knob", T(700, 70) === "out");
check("bottom: -23px still OUT", T(677, 70) === "out");
check("bottom: the playhead column does not respond below the split", T(500, 70) === null);
check("bottom: empty area is inert", T(450, 70) === null);
check("bottom: the split itself belongs to IN/OUT", T(200, BAND) === "in");

// --- overlapping knobs ---
check("overlap: nearest center wins", T(205, 70, 200, 220) === "in");
check("overlap: nearest center wins (out side)", T(215, 70, 200, 220) === "out");
check("overlap: the selected one wins", T(210, 70, 200, 220, 500, "out") === "out");
check("overlap: the selected one wins (in)", T(210, 70, 200, 220, 500, "in") === "in");

// --- no tap-to-seek anywhere ---
check("no seek from empty space", T(400, 15) === null && T(400, 70) === null);

console.log("RESULT:", fails === 0 ? "OK" : "FAIL(" + fails + ")");
process.exit(fails === 0 ? 0 : 1);
