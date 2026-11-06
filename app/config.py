"""Configuration for the Trim lossless video trimmer."""
import json
import string
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"

DEFAULT_CONFIG = {
    "host": "0.0.0.0",
    "port": 8003,
    "allowedRoots": [],
    "denyRoots": [],
    "dataDir": "data",
    "lutsDir": "luts",
    "workCacheBytes": 21474836480,
    "maxUploadBytes": 68719476736,
    "strongMode": False,
    "allowTailnet": True,
    "previewMode": "auto",
    "jobConcurrency": 2,
    "activeWindowSeconds": 600,
    "indexTargetSeconds": 300,
    "defaultUi": "mine",
    "ffmpeg": {
        "version": "9.0.2",
        "url": "https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-9.0.2-essentials_build.zip",
        "sha256": "60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba",
    },
}


def fixed_drives():
    return [d + ":/" for d in string.ascii_uppercase if Path(d + ":/").exists()]


class Config:
    def __init__(self, path=CONFIG_PATH):
        self.path = Path(path)
        self.data = json.loads(json.dumps(DEFAULT_CONFIG))
        if self.path.exists():
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            for key, value in loaded.items():
                if isinstance(value, dict) and isinstance(self.data.get(key), dict):
                    self.data[key].update(value)
                else:
                    self.data[key] = value
        if not self.data.get("allowedRoots"):
            self.data["allowedRoots"] = fixed_drives()

    def save(self):
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def get(self, key, default=None):
        return self.data.get(key, default)

    def __getitem__(self, key):
        return self.data[key]

    def resolve_dir(self, value):
        p = Path(value)
        if not p.is_absolute():
            p = ROOT / p
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def data_dir(self):
        return self.resolve_dir(self.data["dataDir"])

    @property
    def work_dir(self):
        return self.resolve_dir(self.data_dir / "work")

    @property
    def upload_dir(self):
        return self.resolve_dir(self.data_dir / "uploads")

    @property
    def thumbs_dir(self):
        return self.resolve_dir(self.data_dir / "thumbs")

    @property
    def logs_dir(self):
        return self.resolve_dir(self.data_dir / "logs")

    @property
    def db_path(self):
        return self.data_dir / "trim.db"

    @property
    def luts_dir(self):
        configured = self.data.get("lutsDir")
        return self.resolve_dir(configured or (ROOT / "luts"))

    @property
    def tools_dir(self):
        return self.resolve_dir(ROOT / "tools")

    @property
    def web_dir(self):
        return ROOT / "web"

    @property
    def web_qwen_dir(self):
        return ROOT / "web-qwen"

    @property
    def allowed_roots(self):
        return [str(Path(r)) for r in self.data.get("allowedRoots", [])]

    @property
    def deny_roots(self):
        return [str(Path(r)) for r in self.data.get("denyRoots", [])]
