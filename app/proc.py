"""Run an ffmpeg child with progress reporting and job cancellation."""
LOG_RETENTION_DAYS = 7
_PRUNE_EVERY = 200   # writes between size checks
import threading

from . import ffmpeg_tools


def _log_path(name):
    from pathlib import Path
    return Path(__file__).resolve().parent.parent / "data" / "logs" / name


_log_writes = {"n": 0}


def prune_logs(days=LOG_RETENTION_DAYS):
    """Drop log lines older than the retention window (called on startup and while writing)."""
    import time
    try:
        from pathlib import Path
        cutoff = time.time() - days * 86400
        logs = _log_path("").parent
        if not logs.exists():
            return 0
        dropped = 0
        for log in logs.glob("*.log"):
            try:
                if log.stat().st_mtime < cutoff:
                    log.unlink()
                    dropped += 1
                    continue
                keep = []
                with open(log, "r", encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        stamp = line[:19]
                        try:
                            t = time.mktime(time.strptime(stamp, "%Y-%m-%d %H:%M:%S"))
                        except ValueError:
                            try:
                                t = time.mktime(time.strptime(time.strftime("%Y-%m-%d ") + line[:8], "%Y-%m-%d %H:%M:%S"))
                            except ValueError:
                                t = time.time()
                        if t >= cutoff:
                            keep.append(line)
                if len(keep) != sum(1 for _ in open(log, "r", encoding="utf-8", errors="replace")):
                    with open(log, "w", encoding="utf-8") as fh:
                        fh.writelines(keep)
            except Exception:
                continue
        return dropped
    except Exception:
        return 0


def _log_cmd(cmd):
    try:
        import os
        import time
        from pathlib import Path
        log = Path(__file__).resolve().parent.parent / "data" / "logs" / "ffmpeg_cmds.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(time.strftime("%Y-%m-%d %H:%M:%S") + " " + " ".join(str(c) for c in cmd) + chr(10))
        _log_writes["n"] += 1
        if _log_writes["n"] % _PRUNE_EVERY == 0:
            prune_logs()
    except Exception:
        pass


def run_ffmpeg_job(job, ff, args, total_us=None, cwd=None):
    cmd = [ff, "-hide_banner", "-nostdin", "-y", "-progress", "pipe:1", "-nostats"] + list(args)
    _log_cmd(cmd)
    proc = ffmpeg_tools.spawn(cmd, cwd=cwd)
    job.set_proc(proc)
    stderr_lines = []

    def drain():
        try:
            for line in proc.stderr:
                stderr_lines.append(line)
                if len(stderr_lines) > 400:
                    del stderr_lines[:200]
        except (OSError, ValueError):
            pass

    thread = threading.Thread(target=drain, daemon=True)
    thread.start()
    try:
        for line in proc.stdout:
            if job.is_cancelled():
                break
            line = line.strip()
            if line.startswith("out_time_us=") and total_us:
                try:
                    done = int(line.split("=", 1)[1])
                    job.update(progress=max(0.0, min(0.99, done / float(max(1, total_us)))))
                except ValueError:
                    pass
    finally:
        try:
            proc.stdout.close()
        except (OSError, ValueError):
            pass
    rc = proc.wait()
    thread.join(timeout=5)
    tail = "".join(stderr_lines[-20:])[:1000]
    if job.is_cancelled():
        raise RuntimeError("cancelled")
    if rc != 0:
        raise RuntimeError("ffmpeg failed rc=" + str(rc) + ": " + tail)
    return tail

def log_debug(label, **fields):
    """Append one JSON line to data/logs/export_debug.log.

    The raw command log answers "what did we run"; this answers "what did we decide and
    what did the file actually end up containing", which is what a sync complaint needs.
    """
    try:
        import json
        import time
        from pathlib import Path
        log = Path(__file__).resolve().parent.parent / "data" / "logs" / "export_debug.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        rec = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "label": label}
        rec.update(fields)
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False, default=str) + chr(10))
        _log_writes["n"] += 1
        if _log_writes["n"] % _PRUNE_EVERY == 0:
            prune_logs()
    except Exception:
        pass


def probe_media(fp, path):
    """Stream starts, durations and mp4 edit lists of a finished file."""
    import json
    import os
    import struct
    import subprocess

    info = {"path": str(path), "start": {}, "duration": {}, "elst": [], "codec": {}}
    try:
        out = subprocess.run([str(fp), "-v", "error", "-print_format", "json", "-show_streams", str(path)],
                             capture_output=True, text=True, encoding="utf-8", errors="replace",
                             creationflags=CREATE_NO_WINDOW).stdout
        for st in json.loads(out or "{}").get("streams", []):
            kind = st.get("codec_type")
            key = str(kind) + (":" + str(st.get("index")) if kind == "audio" else "")
            info["start"][str(st.get("index"))] = st.get("start_time")
            info["duration"][str(st.get("index"))] = st.get("duration")
            info["codec"][str(st.get("index"))] = str(st.get("codec_name")) + "/" + str(st.get("pix_fmt") or "")
    except Exception as exc:
        info["probe_error"] = str(exc)[:200]
    # edit lists (mp4/mov only): the media_time is how a player offsets the track
    try:
        size_total = os.path.getsize(path)
        with open(path, "rb") as fh:
            def walk(start, end):
                pos = start
                while pos + 8 <= end:
                    fh.seek(pos)
                    hdr = fh.read(8)
                    if len(hdr) < 8:
                        return
                    size = struct.unpack(">I", hdr[:4])[0]
                    kind = hdr[4:8]
                    if size == 1:
                        size = struct.unpack(">Q", fh.read(8))[0]
                    if size < 8 or pos + size > size_total + 8:
                        return
                    if kind in (b"moov", b"trak", b"mdia", b"minf", b"edts"):
                        walk(pos + 8, pos + size)
                    elif kind == b"elst":
                        body = fh.read(size - 8)
                        if len(body) >= 8:
                            count = struct.unpack(">I", body[4:8])[0]
                            p2 = 8
                            for _ in range(count):
                                if p2 + 8 > len(body):
                                    break
                                dur, mt = struct.unpack(">ii", body[p2:p2 + 8])
                                p2 += 8
                                if body[0] == 1:
                                    p2 += 8
                                info["elst"].append({"media_time_ms": round(mt / 1000.0, 3),
                                                     "segment_ms": round(dur / 1000.0, 3)})
                    pos += size
            walk(0, size_total)
    except Exception as exc:
        info["elst_error"] = str(exc)[:120]
    return info
