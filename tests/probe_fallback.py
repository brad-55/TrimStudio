import sys
sys.path.insert(0, r"L:\dev\Trim")
from pathlib import Path
from app.config import Config
from app.exports import writable_probe, known_videos_dir
cfg = Config()
print("data_dir =", cfg.data_dir, "abs?", Path(cfg.data_dir).is_absolute())
print("videos =", known_videos_dir())
for fb in (known_videos_dir(), Path(cfg.data_dir) / "exports"):
    try:
        fb.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(fb, "mkdir failed", exc)
        continue
    print(fb, "->", writable_probe(fb))
