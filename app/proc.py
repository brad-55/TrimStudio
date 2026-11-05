"""Run an ffmpeg child with progress reporting and job cancellation."""
import threading

from . import ffmpeg_tools


def _log_cmd(cmd):
    try:
        import os
        import time
        from pathlib import Path
        log = Path(__file__).resolve().parent.parent / "data" / "logs" / "ffmpeg_cmds.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(time.strftime("%H:%M:%S") + " " + " ".join(str(c) for c in cmd) + chr(10))
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
