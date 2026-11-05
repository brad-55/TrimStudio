"""SQLite persistence for Trim."""
import json
import os
import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    name TEXT NOT NULL,
    origin TEXT NOT NULL,
    container TEXT,
    duration_us INTEGER,
    size INTEGER,
    width INTEGER,
    height INTEGER,
    fps REAL,
    video_codec TEXT,
    audio_codec TEXT,
    pix_fmt TEXT,
    video_stream_index INTEGER,
    video_spec TEXT,
    index_state TEXT DEFAULT 'none',
    streams_json TEXT,
    meta_json TEXT,
    created_at REAL,
    last_access REAL
);
CREATE TABLE IF NOT EXISTS keyframes (
    source_id TEXT NOT NULL,
    stream_index INTEGER NOT NULL,
    pts_us INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_keyframes ON keyframes(source_id, stream_index, pts_us);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    kind TEXT,
    source_id TEXT,
    status TEXT,
    progress REAL,
    message TEXT,
    error TEXT,
    result_json TEXT,
    created_at REAL,
    updated_at REAL
);
"""


class Database:
    def __init__(self, path):
        self.path = str(path)
        self.lock = threading.RLock()
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            cols = {row[1] for row in conn.execute("PRAGMA table_info(sources)")}
            if "meta_json" not in cols:
                conn.execute("ALTER TABLE sources ADD COLUMN meta_json TEXT")
            job_cols = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
            if "error" not in job_cols:
                conn.execute("ALTER TABLE jobs ADD COLUMN error TEXT")
            conn.commit()

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def execute(self, sql, params=()):
        with self.lock, self.connect() as conn:
            cur = conn.execute(sql, params)
            conn.commit()
            return cur

    def query(self, sql, params=()):
        with self.lock, self.connect() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    # sources
    def upsert_source(self, rec):
        self.execute(
            "INSERT OR REPLACE INTO sources (id, path, name, origin, container, duration_us, size, "
            "width, height, fps, video_codec, audio_codec, pix_fmt, video_stream_index, video_spec, "
            "index_state, streams_json, meta_json, created_at, last_access) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (rec["id"], rec["path"], rec["name"], rec["origin"], rec.get("container"), rec.get("duration_us"),
             rec.get("size"), rec.get("width"), rec.get("height"), rec.get("fps"), rec.get("video_codec"),
             rec.get("audio_codec"), rec.get("pix_fmt"), rec.get("video_stream_index"), rec.get("video_spec"),
             rec.get("index_state", "none"),
             json.dumps(rec.get("streams") or []), json.dumps(rec.get("meta") or {}),
             rec.get("created_at", time.time()), rec.get("last_access", time.time())),
        )

    def get_source(self, source_id):
        rows = self.query("SELECT * FROM sources WHERE id=?", (source_id,))
        return rows[0] if rows else None

    def list_sources(self):
        return self.query("SELECT * FROM sources ORDER BY created_at DESC")

    def touch_source(self, source_id):
        self.execute("UPDATE sources SET last_access=? WHERE id=?", (time.time(), source_id))

    def set_index_state(self, source_id, state):
        self.execute("UPDATE sources SET index_state=? WHERE id=?", (state, source_id))

    def delete_source(self, source_id):
        self.execute("DELETE FROM sources WHERE id=?", (source_id,))
        self.execute("DELETE FROM keyframes WHERE source_id=?", (source_id,))

    # keyframes
    def replace_keyframes(self, source_id, stream_index, pts_us_list):
        with self.lock, self.connect() as conn:
            conn.execute("DELETE FROM keyframes WHERE source_id=? AND stream_index=?", (source_id, stream_index))
            conn.executemany("INSERT INTO keyframes (source_id, stream_index, pts_us) VALUES (?,?,?)",
                             [(source_id, stream_index, int(v)) for v in pts_us_list])
            conn.commit()

    def get_keyframes(self, source_id, stream_index):
        rows = self.query("SELECT pts_us FROM keyframes WHERE source_id=? AND stream_index=? ORDER BY pts_us",
                          (source_id, stream_index))
        return [r["pts_us"] for r in rows]

    # jobs
    def upsert_job(self, rec):
        self.execute(
            "INSERT OR REPLACE INTO jobs (id, kind, source_id, status, progress, message, error, result_json, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (rec["id"], rec.get("kind"), rec.get("source_id"), rec.get("status"), rec.get("progress"),
             rec.get("message"), rec.get("error"), json.dumps(rec.get("result")), rec.get("created_at", time.time()),
             rec.get("updated_at", time.time())),
        )

    def get_job(self, job_id):
        rows = self.query("SELECT * FROM jobs WHERE id=?", (job_id,))
        return rows[0] if rows else None

    def list_jobs(self, limit=50):
        return self.query("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,))
