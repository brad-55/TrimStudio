"""Automatic audio sync: estimate the delay between two audio tracks.

The estimator is a plain GCC-PHAT cross correlation on 16 kHz mono PCM, which is cheap
(one FFT per window) and robust enough for dialogue and ambient sound. Repetitive music
or silence produces a low confidence value, so the caller can ask the user to align by
hand instead of trusting the number.
"""
import numpy as np

SAMPLE_RATE = 16000


def _to_float(pcm):
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0


def estimate_offset(ref, tgt, rate=SAMPLE_RATE, max_lag_s=5.0):
    """Estimate how much *tgt* must be delayed to line up with *ref*.

    Returns (offset_samples, ratio, quality):
      offset_samples  positive = delay the target by that many samples
      ratio           GCC-PHAT peak / second peak (sharpness of the peak, >= 1)
      quality         Pearson correlation of the overlapping parts (0..1)
    """
    ref = np.asarray(ref, dtype=np.float32)
    tgt = np.asarray(tgt, dtype=np.float32)
    if ref.size == 0 or tgt.size == 0:
        return 0, 0.0, 0.0
    ref = ref - float(np.mean(ref))
    tgt = tgt - float(np.mean(tgt))
    if not np.any(ref) or not np.any(tgt):
        return 0, 0.0, 0.0
    n = 1
    while n < ref.size + tgt.size:
        n *= 2
    R = np.fft.rfft(ref, n)
    T = np.fft.rfft(tgt, n)
    cross = R * np.conj(T)
    mag = np.abs(cross)
    mag[mag < 1e-12] = 1e-12
    corr = np.fft.irfft(cross / mag, n)
    max_lag = max(1, min(int(max_lag_s * rate), min(ref.size, tgt.size) - 1))
    # Linear lags: negative ones live at the tail of the circular buffer.
    lags = np.concatenate([np.arange(-max_lag, 0), np.arange(0, max_lag + 1)])
    vals = np.concatenate([corr[n - max_lag:n], corr[0:max_lag + 1]])
    k = int(np.argmax(np.abs(vals)))
    lag = int(lags[k])
    peak = float(vals[k])
    guard = max(1, int(0.020 * rate))
    masked = np.abs(vals).copy()
    masked[max(0, k - guard):k + guard + 1] = 0.0
    second = float(np.max(masked)) if masked.size else 0.0
    ratio = float(abs(peak) / second) if second > 1e-9 else 99.0
    # Quality: Pearson correlation of the overlapping part at the chosen lag.
    if lag >= 0:
        a, b = ref[lag:], tgt[:max(0, tgt.size - lag)]
    else:
        a, b = ref[:max(0, ref.size + lag)], tgt[-lag:]
    m = min(a.size, b.size)
    if m > 1:
        aa = a[:m] - float(np.mean(a[:m]))
        bb = b[:m] - float(np.mean(b[:m]))
        denom = float(np.sqrt(float(np.sum(aa ** 2)) * float(np.sum(bb ** 2)))) or 1.0
        quality = abs(float(np.sum(aa * bb)) / denom)
    else:
        quality = 0.0
    return lag, ratio, float(quality)


def estimate_consistent(windows, rate=SAMPLE_RATE):
    """Combine several window estimates: return the median and whether they agree.

    windows: list of (offset_samples, ratio, peak). Agreement within 30 ms counts as a
    single constant delay; a wider spread means the two recordings drift (different clocks)
    and no single offset can align the whole file.
    """
    good = [w for w in windows if w[1] >= 1.5 and w[2] >= 0.15]
    if not good:
        return 0, 0.0, False, 0.0
    offsets = sorted(w[0] for w in good)
    median = offsets[len(offsets) // 2]
    spread_samples = offsets[-1] - offsets[0]
    consistent = spread_samples <= int(0.030 * rate)
    ratio = min(w[1] for w in good)
    peak = min(w[2] for w in good)
    return int(median), float(min(ratio, 99.0)), bool(consistent), float(peak)


def analyze(cfg, ff, ref_path, tgt_path, ref_start_us=0, tgt_start_us=0,
            window_us=60_000_000, range_us=5_000_000, windows=3, span_us=None):
    """Extract PCM with ffmpeg and estimate the offset for one or more windows.

    windows spreads the analysis points across span_us (default: window * windows), so a
    long file is checked at several places. A wide spread between the estimates means the
    two recordings drift (different clocks) rather than sharing one constant delay.
    """
    from . import ffmpeg_tools

    win = max(1_000_000, int(window_us))
    rng = max(0, int(range_us))
    span = win + 2 * rng
    available = int(span_us) if span_us else win * max(1, windows)
    starts = []
    for i in range(max(1, windows)):
        frac = 0.0 if windows <= 1 else (i / float(windows - 1)) * 0.8
        starts.append(max(0, min(int(available * frac), max(0, available - span))))
    results = []
    for start_off in starts:
        ref = ffmpeg_tools.read_pcm16_mono(ff, ref_path, ref_start_us + start_off, span, SAMPLE_RATE)
        tgt = ffmpeg_tools.read_pcm16_mono(ff, tgt_path, max(0, tgt_start_us + start_off), span, SAMPLE_RATE)
        if ref is None or tgt is None:
            continue
        r = _to_float(ref)
        t = _to_float(tgt)
        if r.size < SAMPLE_RATE or t.size < SAMPLE_RATE:
            continue
        results.append(estimate_offset(r, t, SAMPLE_RATE, rng / 1e6))
    if not results:
        return {"ok": False, "reason": "no_audio", "offsetMs": 0, "confidence": 0.0}
    lag, ratio, consistent, peak = estimate_consistent(results)
    if ratio < 1.5 or peak < 0.15:
        return {"ok": False, "reason": "low_confidence", "offsetMs": 0,
                "confidence": round(peak, 3), "ratio": round(ratio, 2)}
    offset_ms = int(round(lag / float(SAMPLE_RATE) * 1000.0))
    return {"ok": True, "offsetMs": offset_ms, "confidence": round(peak, 3),
            "ratio": round(ratio, 2), "consistent": consistent, "windows": len(results)}


def start_analysis(cfg, db, jobs, ref_source, tgt_source, start_us=0,
                   window_us=60_000_000, range_us=5_000_000, windows=3):
    """Queue the sync analysis as a job; the result carries offsetMs/confidence."""
    from . import ffmpeg_tools

    def runner(job):
        job.update(message="analysing audio sync")
        ff, _fp = ffmpeg_tools.ffmpeg_paths(cfg)
        if not ff:
            raise RuntimeError("ffmpeg is not available")
        span = None
        ref_dur = ref_source.get("duration_us") or 0
        tgt_dur = tgt_source.get("duration_us") or 0
        if ref_dur:
            span = max(0, min(ref_dur, tgt_dur or ref_dur) - int(start_us))
        job.update(message="comparing the two audio tracks")
        return analyze(cfg, ff, ref_source["path"], tgt_source["path"], int(start_us), 0,
                       window_us, range_us, windows, span)

    return jobs.create("audioSync", ref_source["id"], runner)
