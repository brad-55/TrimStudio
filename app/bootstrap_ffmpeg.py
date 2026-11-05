"""CLI: ensure ffmpeg is present, downloading the pinned build if needed."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Config  # noqa: E402
from app import ffmpeg_tools  # noqa: E402


def main():
    cfg = Config()
    ff, fp = ffmpeg_tools.ensure_ffmpeg(cfg)
    print("ffmpeg:", ff)
    print("ffprobe:", fp)
    print("version:", ffmpeg_tools.ffmpeg_version(ff))
    return 0


if __name__ == "__main__":
    sys.exit(main())
