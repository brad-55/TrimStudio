// Round-trip test for the "the browser remembers the settings" promise.
//
// The page is loaded twice against the same localStorage: the first session changes the
// controls like a user would, the second session is the reload.  Global preferences must
// come back; the material-specific audio timing must not (it belongs to the clip being
// edited and opening another video resets it).
const { load } = require("./_ui_harness.js");

let fails = 0;
function check(label, cond, detail) {
  console.log((cond ? "OK   " : "FAIL ") + label + (cond ? "" : "  " + (detail === undefined ? "" : detail)));
  if (!cond) { fails++; }
}
// saveSettings() is synchronous, so "the save has landed" needs no timer: draining the
// microtask queue is enough.  The only asynchronous part of start-up is the fetch-fed
// data (LUT list), which gets an explicit condition wait.
const MICROTASK_DRAIN_ROUNDS = 12;
async function drain() {
  for (let i = 0; i < MICROTASK_DRAIN_ROUNDS; i++) { await Promise.resolve(); }
}
const RESTORE_TIMEOUT_MS = 2000;
async function flush(handle) {
  if (handle) {
    let ready = false;
    const ok = await waitFor(() => {
      try {
        ready = !!(handle.probe().ready && handle.probe().ready() && handle.probe().lutReady && handle.probe().lutReady());
      } catch (e) { ready = false; }
      return ready;
    }, RESTORE_TIMEOUT_MS);
    if (!ok) { console.log("LOG  settings restore did not become ready in 1500ms"); check("flush: the page finished restoring the settings", false); }
  }
  await drain();
}
async function waitFor(cond, ms) {
  const end = Date.now() + (ms || 1500);
  while (Date.now() < end) {
    if (cond()) return true;
    await new Promise((r) => setTimeout(r, 10));
  }
  return false;
}

const LUT_PATH = "L:\\\\luts\\\\a.cube";
const fetchStub = (url) => Promise.resolve({
  ok: true, status: 200,
  text: () => Promise.resolve("{}"),
  json: () => Promise.resolve(String(url).indexOf("/api/luts") >= 0
    ? { dir: "L:\\\\luts", luts: [{ path: LUT_PATH, name: "a.cube" }] }
    : {}),
});

(async () => {
  const store = new Map();
  const first = load({ store, fetch: fetchStub });
  await flush(first);
  const $ = first.el;
  $("zoomSel").value = "100"; $("zoomSel").dispatch("change");
  $("contSel").value = "mp4"; $("contSel").dispatch("change");
  $("inSnapSel").value = "next"; $("inSnapSel").dispatch("change");
  $("outModeSel").value = "keyframeAfter"; $("outModeSel").dispatch("change");
  $("vbrInp").value = "12000"; $("vbrInp").dispatch("change");
  $("encSel").value = "libx265"; $("encSel").dispatch("change");
  $("outPath").value = "D:\\\\out"; $("outPath").dispatch("change");
  $("stabChk").checked = true; $("stabChk").dispatch("change");
  $("audioChk").checked = true; $("audioChk").dispatch("change");
  $("lutSel").value = LUT_PATH; $("lutSel").dispatch("change");
  // a crop change arrives through the preset / drag path, which writes the inputs
  // directly instead of firing input events on them
  first.probe().state().source = { id: "clip-a", width: 1920, height: 1080 };
  first.sandbox.setCropRect({ x: 10, y: 20, w: 640, h: 360 });
  // audio timing is session state; it must NOT be stored.  Exercise every field so a
  // future saveSettings() that starts storing one of them is caught here.
  $("origShiftInp").value = "250"; $("origShiftInp").dispatch("input");
  $("addedShiftInp").value = "80"; $("addedShiftInp").dispatch("input");
  $("addedStartInp").value = "120"; $("addedStartInp").dispatch("input");
  $("addedReencodeChk").checked = true; $("addedReencodeChk").dispatch("change");
  first.probe().state().addedSource = { id: "extra-a", name: "a", durationUs: 1000000 };
  const mix = $("radio:bothMix"); mix.checked = true; mix.dispatch("change");
  await flush();

  const saved = JSON.parse(store.get("trim.settings.v1") || "null") || {};
  check("settings: the zoom is saved", saved.zoom === 100, saved.zoom);
  check("settings: the container is saved", saved.container === "mp4", saved.container);
  check("settings: the IN snap is saved", saved.inSnap === "next", saved.inSnap);
  check("settings: the encoder is saved", saved.encoder === "libx265", saved.encoder);
  check("settings: the output folder is saved", saved.outPath === "D:\\\\out", saved.outPath);
  check("settings: the stabilizer flag is saved", saved.stabilize === true, saved.stabilize);
  check("settings: the audio re-encode flag is saved", saved.audio === true, saved.audio);
  check("settings: a crop change is saved", String(saved.cropW) === "640", saved.cropW);
  check("settings: the crop remembers which source it belongs to", saved.cropSourceId === "clip-a", saved.cropSourceId);
  check("settings: the LUT is saved", saved.lut === LUT_PATH, saved.lut);
  check("settings: the audio shift is NOT stored (it belongs to the clip)",
        saved.audioShiftMs === undefined, saved.audioShiftMs);
  check("settings: the added start is NOT stored", saved.addedStartMs === undefined, saved.addedStartMs);
  check("settings: the audio mode is NOT stored", saved.audioMode === undefined, saved.audioMode);
  check("settings: the added shift is NOT stored", saved.addedShiftMs === undefined, saved.addedShiftMs);
  check("settings: the added re-encode flag is NOT stored", saved.addedReencode === undefined, saved.addedReencode);
  check("settings: the added source is NOT stored", saved.addedSourceId === undefined, saved.addedSourceId);

  // "Reload": the same browser storage, a fresh page.
  const second = load({ store, fetch: fetchStub });
  await flush(second);
  const $2 = second.el;
  const st2 = second.probe().state();
  check("settings: the zoom comes back after a reload", $2("zoomSel").value === "100", $2("zoomSel").value);
  check("settings: the page is zoomed after a reload",
        Number(second.sandbox.document.documentElement.style.zoom) === 1,
        second.sandbox.document.documentElement.style.zoom);
  check("settings: the container comes back", $2("contSel").value === "mp4", $2("contSel").value);
  check("settings: the IN snap comes back", $2("inSnapSel").value === "next", $2("inSnapSel").value);
  check("settings: the OUT mode comes back", $2("outModeSel").value === "keyframeAfter", $2("outModeSel").value);
  check("settings: the OUT mode was saved", saved.outMode === "keyframeAfter", saved.outMode);
  check("settings: the bitrate was saved", String(saved.vbr) === "12000", saved.vbr);
  check("settings: the bitrate comes back", $2("vbrInp").value === "12000", $2("vbrInp").value);
  check("settings: the encoder comes back", $2("encSel").value === "libx265", $2("encSel").value);
  check("settings: the output folder comes back", $2("outPath").value === "D:\\\\out", $2("outPath").value);
  check("settings: the stabilizer flag comes back", $2("stabChk").checked === true);
  check("settings: the audio flag comes back", $2("audioChk").checked === true);
  await waitFor(() => $2("lutSel").value === LUT_PATH, 2000);
  check("settings: the LUT comes back", $2("lutSel").value === LUT_PATH, $2("lutSel").value);
  check("settings: the audio timing starts clean after a reload",
        String($2("origShiftInp").value) === "0" && $2("radio:original").checked === true
        && st2.audioShiftMs === 0, [$2("origShiftInp").value, st2.audioShiftMs]);

  // The crop is restored against the opened source (it is material-dependent).
  second.probe().state().source = { id: "clip-a", width: 1920, height: 1080 };
  second.sandbox.applyPendingCrop();
  const crop2 = second.probe().crop() || {};
  check("settings: the crop comes back on the next source",
        String($2("cropW").value) === "640" && String($2("cropH").value) === "360"
        && crop2.w === 640 && crop2.h === 360, [crop2.w, crop2.h]);
  // the restored crop belongs to the FIRST source opened: opening another one must not
  // re-apply it.  A smaller source makes the oracle discriminating: a second apply would
  // clamp 640x360 down to 320x240, so "still 640x360" proves it was not applied.
  const reapplySource = second.probe().state().source;
  second.probe().state().source = { width: 320, height: 240 };
  const reapplied = second.sandbox.applyPendingCrop();
  const crop2b = second.probe().crop() || {};
  check("settings: the remembered crop is not applied twice",
        reapplied === false && crop2b.w === 640 && crop2b.h === 360, [reapplied, crop2b.w, crop2b.h]);
  second.probe().state().source = reapplySource;

  // The rect must wait for the new video's dimensions instead of clamping against the
  // previous clip (the video element still reports the old size until metadata loads).
  const late = load({ store, fetch: fetchStub });
  await flush(late);
  late.probe().state().source = { id: "clip-a" };
  check("settings: the crop waits until the video dimensions are known",
        late.sandbox.applyPendingCrop() === false && late.probe().crop() === null, late.probe().crop());
  late.probe().state().source = { id: "clip-a", width: 1920, height: 1080 };
  check("settings: the crop is applied when the dimensions arrive",
        late.sandbox.applyPendingCrop() === true && (late.probe().crop() || {}).w === 640,
        late.probe().crop());

  // A saved crop value that the picker does not offer falls back to the default.
  const oddStore = new Map([["trim.settings.v1", JSON.stringify({ zoom: 123 })]]);
  const odd = load({ store: oddStore, fetch: fetchStub });
  await flush(odd);
  check("settings: an unknown saved zoom falls back to the default",
        odd.el("zoomSel").value === "75"
        && Number(odd.sandbox.document.documentElement.style.zoom) === 0.75,
        [odd.el("zoomSel").value, odd.sandbox.document.documentElement.style.zoom]);

  // A saved rect from a bigger clip must be clamped into the smaller one.
  const third = load({ store, fetch: fetchStub });
  await flush(third);
  // same sourceId, smaller resolution: the scope is "same material", so this is a clamp case
  third.probe().state().source = { id: "clip-a", width: 320, height: 240 };
  third.sandbox.applyPendingCrop();
  const crop3 = third.probe().crop() || {};
  check("settings: a crop from a bigger clip is clamped",
        crop3.w <= 320 && crop3.h <= 240 && crop3.x >= 0 && crop3.y >= 0, crop3);

  // Start-up must not overwrite the stored snapshot with the preliminary default values:
  // that was the regression behind "reloading resets everything".  Dedicated store so the
  // check does not depend on what the later sessions write.
  const startupStore = new Map([["trim.settings.v1", JSON.stringify({ zoom: 100, container: "mp4" })]]);
  const startup = load({ store: startupStore, fetch: fetchStub });
  await flush(startup);
  const afterStart = JSON.parse(startupStore.get("trim.settings.v1") || "null") || {};
  check("settings: start-up does not overwrite the stored snapshot",
        afterStart.zoom === 100 && afterStart.container === "mp4",
        [afterStart.zoom, afterStart.container]);

  // Drive the real "open a video" handler: the crop must come back when the video's
  // metadata arrives and the audio timing must be cleared for the new material.
  const sourceInfo = (id, width, height) => ({ source: { id, name: id, kind: "video", width, height, durationUs: 12000000, fps: 30, streams: [] }, directPlayable: true, proxyReady: true });
  const liveFetch = (url) => {
    const u = String(url);
    if (u.indexOf("/api/luts") >= 0) return Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve("{}"), json: () => Promise.resolve({ dir: "L:\\\\luts", luts: [{ path: LUT_PATH, name: "a.cube" }] }) });
    if (u.indexOf("/api/sources/clip-a") >= 0) return Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve("{}"), json: () => Promise.resolve(sourceInfo("clip-a", 1920, 1080)) });
    if (u.indexOf("/api/sources/vid2") >= 0) return Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve("{}"), json: () => Promise.resolve(sourceInfo("vid2", 320, 240)) });
    return Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve("{}"), json: () => Promise.resolve({}) });
  };
  const live = load({ store, fetch: liveFetch });
  await flush(live);
  live.probe().state().audioShiftMs = 500;
  live.probe().state().audioMode = "bothMix";
  await live.sandbox.selectSource("clip-a");
  live.probe().vid().dispatch("loadedmetadata");
  await flush();
  check("settings: opening the same video restores the remembered crop",
        String(live.el("cropW").value) === "640" && (live.probe().crop() || {}).w === 640,
        [live.el("cropW").value, live.probe().crop()]);
  check("settings: opening a video clears the audio timing",
        live.probe().state().audioShiftMs === 0 && live.probe().state().audioMode === "original"
        && String(live.el("origShiftInp").value) === "0",
        [live.probe().state().audioShiftMs, live.probe().state().audioMode]);
  // Turning the LUT off must stay off after a reload (the pendingLut fallback must not
  // resurrect the old selection).
  const offStore = new Map([["trim.settings.v1", JSON.stringify({ lut: LUT_PATH })]]);
  const offFetch = (url) => Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve("{}"),
    json: () => Promise.resolve(String(url).indexOf("/api/luts") >= 0 ? { dir: "L:\\\\luts", luts: [{ path: LUT_PATH, name: "a.cube" }] } : {}) });
  const off = load({ store: offStore, fetch: offFetch });
  await flush(off);
  await waitFor(() => off.el("lutSel").value === LUT_PATH);
  off.el("lutSel").value = "";
  off.el("lutSel").dispatch("change");
  await flush();
  const offSaved = JSON.parse(offStore.get("trim.settings.v1") || "null") || {};
  check("settings: turning the LUT off is saved", offSaved.lut === "", offSaved.lut);
  const offReload = load({ store: offStore, fetch: offFetch });
  await flush(offReload);
  await waitFor(() => offReload.el("lutSel").value === "");
  check("settings: a turned-off LUT stays off after a reload",
        offReload.el("lutSel").value === "", offReload.el("lutSel").value);

  // The remembered crop is tied to the source id: re-opening the SAME video restores it,
  // opening a different video must not inherit it.
  const sameStore = new Map([["trim.settings.v1", JSON.stringify({ cropW: 640, cropH: 360, cropX: 10, cropY: 20, cropSourceId: "vid1" })]]);
  const sameSrc = (id, w, h) => ({ source: { id, name: id, kind: "video", width: w, height: h, durationUs: 12000000, fps: 30, streams: [] }, directPlayable: true, proxyReady: true });
  const sameFetch = (url) => {
    const u = String(url);
    if (u.indexOf("/api/sources/vid1") >= 0) return Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve("{}"), json: () => Promise.resolve(sameSrc("vid1", 1920, 1080)) });
    if (u.indexOf("/api/sources/vid2") >= 0) return Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve("{}"), json: () => Promise.resolve(sameSrc("vid2", 320, 240)) });
    return Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve("{}"), json: () => Promise.resolve({}) });
  };
  const same = load({ store: sameStore, fetch: sameFetch });
  await flush(same);
  await same.sandbox.selectSource("vid1");
  same.probe().vid().dispatch("loadedmetadata");
  await flush();
  check("settings: the crop is restored for the same source",
        (same.probe().crop() || {}).w === 640, same.probe().crop());
  const otherStore = new Map([["trim.settings.v1", JSON.stringify({ cropW: 640, cropH: 360, cropX: 10, cropY: 20, cropSourceId: "vid1" })]]);
  const other = load({ store: otherStore, fetch: sameFetch });
  await flush(other);
  await other.sandbox.selectSource("vid2");
  other.probe().vid().dispatch("loadedmetadata");
  await flush();
  check("settings: a different source does not inherit the crop", other.probe().crop() === null, other.probe().crop());
  // Re-opening the same video inside one session is not a restore point either: the
  // remembered crop is applied once per page load.
  await same.sandbox.selectSource("vid1");
  same.probe().vid().dispatch("loadedmetadata");
  await flush();
  check("settings: the crop is restored only once per page load", same.probe().crop() === null, same.probe().crop());

  // Opening a SECOND video in the same session shows a full frame and must not overwrite
  // the remembered crop (otherwise the next reload would restore the wrong rect).
  await live.sandbox.selectSource("vid2");
  live.probe().vid().dispatch("loadedmetadata");
  await flush();
  const liveCrop = live.probe().crop();
  const storedCrop = JSON.parse(store.get("trim.settings.v1") || "null") || {};
  check("settings: a second video starts with a full frame", liveCrop === null, liveCrop);
  check("settings: a second video does not overwrite the remembered crop",
        String(storedCrop.cropW) === "640", storedCrop.cropW);

  console.log(fails ? "RESULT: FAIL(" + fails + ")" : "RESULT: OK");
  process.exit(fails ? 1 : 0);
})();
