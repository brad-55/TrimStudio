// Behavioural tests for the audio timing panel (the class that leaked twice).
//
// The inline script runs in a VM with a DOM stub that keeps element identity and records
// event handlers, so the REAL handlers are driven instead of pattern-matching the source.
// The sync loop is stepped frame by frame with a controllable clock.
const { load } = require("./_ui_harness.js");
let fails = 0;
function check(label, cond, detail) {
  console.log((cond ? "OK   " : "FAIL ") + label + (cond ? "" : "  " + (detail === undefined ? "" : detail)));
  if (!cond) { fails++; }
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

// --- G. opening another video clears the audio timing -------------------------------
S.fetch = async () => ok({ ok: true, cached: true, url: "/api/preview/media/ffff.mp4", sourceTimelineOffsetUs: 0, outputStartOffsetUs: 0 });
await S.applyPreview();
check("reset: a preview is applied before the switch", $("previewRevertBtn").hidden === false);
S.setAudioShift('orig', 500);
$("addedShiftInp").value = "80"; $("addedShiftInp").dispatch("input");
$("addedStartInp").value = "120"; $("addedStartInp").dispatch("input");
$("addedReencodeChk").checked = true; $("addedReencodeChk").dispatch("change");
const tracks = $("radio:bothTracks"); tracks.checked = true; tracks.dispatch("change");
P.state().addedSource = { id: "a1", name: "x", durationUs: 1000000 };
S.resetAudioTiming();
check("reset: the original shift goes back to 0", String($("origShiftInp").value) === "0", $("origShiftInp").value);
check("reset: the added shift goes back to 0", String($("addedShiftInp").value) === "0", $("addedShiftInp").value);
check("reset: the added start goes back to 0", String($("addedStartInp").value) === "0", $("addedStartInp").value);
check("reset: the audio mode goes back to original",
      P.state().audioMode === "original" && $("radio:original").checked === true, P.state().audioMode);
check("reset: the extra track is forgotten", P.state().addedSource === null);
check("reset: the re-encode flag is cleared", $("addedReencodeChk").checked === false);
check("reset: the preview is marked unapplied",
      String($("previewState").textContent).indexOf("未反映") >= 0, $("previewState").textContent);
check("reset: the applied preview is reverted on the old element",
      $("previewRevertBtn").hidden === true && String(vid.src).indexOf("/api/preview/media/") < 0, vid.src);

// --- H. a preview build that finishes after the material changed is discarded ------
S.revertPreview();
let releasePreview;
const previewGate = new Promise((r) => { releasePreview = r; });
S.fetch = () => previewGate.then(() => ok({ ok: true, cached: true, url: "/api/preview/media/hhhh.mp4", sourceTimelineOffsetUs: 0, outputStartOffsetUs: 0 }));
const pendingPreview = S.applyPreview();
S.resetAudioTiming();
releasePreview();
await pendingPreview;
check("reset: a preview build that finishes after the switch is discarded",
      String(vid.src).indexOf("/api/preview/media/hhhh.mp4") < 0
      && $("previewRevertBtn").hidden === true, vid.src);

console.log(fails ? "RESULT: FAIL(" + fails + ")" : "RESULT: OK");
process.exit(fails ? 1 : 0);
})();
