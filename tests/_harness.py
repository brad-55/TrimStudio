"""Shared helpers for the TrimStudio suites.

Every suite talks to a long-lived server process and decodes media with an ffmpeg
binary.  If either differs from the working tree the suite silently validates the
wrong thing (this actually happened: a fix was "verified" against a stale process),
so each suite calls require_current() and require_ffmpeg() before doing any work.
"""
import hashlib
import json
import os
import subprocess
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Keep in sync with app/main.py:_build_stamp
STAMP_TARGETS = ["app/main.py", "app/exports.py", "app/jobs.py", "app/ffmpeg_tools.py",
                 "app/sources.py", "app/audio_sync.py", "app/security.py", "app/config.py",
                 "web-qwen/index.html"]


def local_build_stamp():
    h = hashlib.sha256()
    for rel in STAMP_TARGETS:
        p = ROOT / rel
        h.update(p.name.encode())
        try:
            h.update(p.read_bytes())
        except OSError:
            h.update(b"missing")
    return h.hexdigest()[:12]


def health(base, token=None):
    req = urllib.request.Request(base.rstrip("/") + "/api/health")
    if token:
        req.add_header("X-Trim-Token", token)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def require_current(base, token=None):
    """Hard fail when the server is not running this working tree."""
    want = local_build_stamp()
    got = health(base, token).get("build")
    if got != want:
        raise SystemExit(
            "STALE SERVER: /api/health build=%s but this working tree is %s.\n"
            "Restart the server before trusting any test result:\n"
            "  Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
            "Where-Object { $_.CommandLine -match 'app.serve' } | "
            "ForEach-Object { taskkill /PID $_.ProcessId /F /T }" % (got, want))
    return True


def require_ffmpeg(base, ffmpeg_path, token=None):
    """The decoding ffmpeg must be the very binary the app runs."""
    h = health(base, token)
    if not h.get("ffmpeg"):
        raise SystemExit("the server has no working ffmpeg")
    app_path = os.path.normcase(os.path.abspath(str(h.get("ffmpegPath") or "")))
    test_path = os.path.normcase(os.path.abspath(str(ffmpeg_path)))
    if app_path and app_path != test_path:
        raise SystemExit("FFMPEG MISMATCH: the app runs %s but the test uses %s"
                         % (h.get("ffmpegPath"), ffmpeg_path))
    line = subprocess.run([str(ffmpeg_path), "-version"], capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stdout.splitlines()[0]
    version = h.get("ffmpegVersion")
    if version and version not in line:
        raise SystemExit("FFMPEG VERSION MISMATCH: the app reports %s but %s" % (version, line))
    return line


def ffprobe_bin():
    return str(ROOT / "tools" / "ffmpeg" / "bin" / "ffprobe.exe")


def packet_times(path, spec="0:a"):
    """Every packet PTS of a stream read straight from the file (no seek).

    This is the independent oracle: the export is compared against the *source's*
    packet grid rather than against a re-run of the same seek the pipeline uses.
    """
    # ffprobe stream specifiers have no input-file prefix ("0:a" -> "a")
    if spec.startswith("0:"):
        spec = spec[2:]
    p = subprocess.run([ffprobe_bin(), "-v", "error", "-select_streams", spec,
                        "-show_entries", "packet=pts_time", "-of", "json", str(path)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise RuntimeError("ffprobe failed for %s: %s" % (path, (p.stderr or "")[:200]))
    out = []
    for pk in json.loads(p.stdout).get("packets", []):
        try:
            out.append(round(float(pk.get("pts_time")), 6))
        except (TypeError, ValueError):
            pass
    return out
