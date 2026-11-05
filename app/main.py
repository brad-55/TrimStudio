"""Trim: LAN-only lossless video trimmer (FastAPI application)."""
import asyncio
import json
import os
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import cleanup, exports, ffmpeg_tools, fsops, media, security, sources
from .config import ROOT, Config
from .db import Database
from .jobs import JobManager

# Device-specific extensions are included: Insta360/GoPro .lrv/.insv/.insp/.360 (MP4 content),
# prosumer .mxf, .dv, .vob, RealMedia .rm/.rmvb, Flash .f4v, .3g2, camcorder .mod/.tod, .m2t.
VIDEO_EXTS = {".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".wmv", ".flv", ".ts", ".m2ts", ".mts", ".m2t",
              ".mpg", ".mpeg", ".3gp", ".3g2", ".ogv", ".lrv", ".insv", ".insp", ".360", ".mxf",
              ".dv", ".vob", ".rm", ".rmvb", ".f4v", ".mod", ".tod"}
AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".oga", ".opus", ".wma", ".aif", ".aiff"}
MEDIA_EXTS = VIDEO_EXTS | AUDIO_EXTS
MIME = {".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime", ".mkv": "video/x-matroska",
        ".webm": "video/webm", ".avi": "video/x-msvideo", ".ts": "video/mp2t", ".m2ts": "video/mp2t",
        ".mts": "video/mp2t", ".mpg": "video/mpeg", ".mpeg": "video/mpeg", ".wmv": "video/x-ms-wmv",
        ".flv": "video/x-flv", ".ogv": "video/ogg", ".3gp": "video/3gpp", ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg", ".png": "image/png", ".mp3": "audio/mpeg", ".m4a": "audio/mp4",
        ".aac": "audio/aac", ".wav": "audio/wav", ".flac": "audio/flac", ".ogg": "audio/ogg",
        ".oga": "audio/ogg", ".opus": "audio/ogg", ".wma": "audio/x-ms-wma", ".aif": "audio/aiff",
        ".aiff": "audio/aiff", ".lrv": "video/mp4", ".insv": "video/mp4", ".insp": "video/mp4",
        ".360": "video/mp4", ".mxf": "application/mxf", ".dv": "video/x-dv", ".vob": "video/mpeg",
        ".rm": "application/vnd.rn-realmedia", ".rmvb": "application/vnd.rn-realmedia-vbr",
        ".f4v": "video/x-f4v", ".3g2": "video/3gpp2", ".m2t": "video/mp2t", ".mod": "video/mpeg",
        ".tod": "video/mpeg"}


def err(code, message, status=400, detail=None):
    body = {"code": code, "message": message}
    if detail is not None:
        body["detail"] = detail
    return JSONResponse(body, status_code=status)


def create_app():
    app = FastAPI(title="Trim", docs_url=None, redoc_url=None)
    cfg = Config()
    db = Database(cfg.db_path)
    jobs = JobManager(db, cfg.get("jobConcurrency", 2))
    app.state.cfg = cfg
    app.state.db = db
    app.state.jobs = jobs
    app.state.token = security.load_or_create_token(cfg.data_dir)
    app.state.local_ips = security.local_interface_ips()
    app.state.ips_ts = time.time()
    app.state.self_names = security.self_host_names()

    @app.on_event("startup")
    def _startup():
        try:
            ff, fp = ffmpeg_tools.ensure_ffmpeg(cfg, log=print)
            app.state.ffmpeg = ff
            app.state.ffprobe = fp
        except Exception as exc:
            app.state.ffmpeg = None
            app.state.ffprobe = None
            print("ffmpeg unavailable: " + repr(exc))
        try:
            cleanup.remove_orphans(cfg)
            cleanup.enforce(cfg, db, jobs)
        except Exception as exc:
            print("cleanup failed: " + repr(exc))
        try:
            # Jobs interrupted by a restart can never finish; fail them so the UI stops waiting.
            db.execute("UPDATE jobs SET status='error', error='interrupted by restart', "
                       "message='interrupted by restart', updated_at=? "
                       "WHERE status IN ('queued', 'running')", (time.time(),))
        except Exception as exc:
            print("job reconciliation failed: " + repr(exc))

    def refresh_ips():
        now = time.time()
        if now - app.state.ips_ts > 60:
            app.state.local_ips = security.local_interface_ips()
            app.state.self_names = security.self_host_names()
            app.state.ips_ts = now

    @app.middleware("http")
    async def guard(request: Request, call_next):
        client = request.client.host if request.client else ""
        if not security.is_private_ip(client):
            return err("lan_only", "access is limited to the local network", 403)
        refresh_ips()
        host = request.headers.get("host", "")
        if not security.host_allowed(host, app.state.local_ips, app.state.self_names):
            return err("bad_host", "host header is not allowed", 403)
        path = request.url.path
        strong = bool(cfg.get("strongMode"))
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            if path != "/api/auth":
                if strong:
                    if request.cookies.get("trim_session", "") != app.state.token:
                        return err("token_required", "session token required", 403)
                elif request.headers.get("x-trim-token", "") != app.state.token:
                    return err("token_required", "csrf token required", 403)
            origin = request.headers.get("origin") or request.headers.get("referer")
            if origin:
                netloc = urlsplit(origin).netloc
                if netloc and netloc.lower() != host.lower():
                    return err("bad_origin", "cross-origin request rejected", 403)
        elif strong and path.startswith("/api/") and path not in ("/api/auth", "/api/health", "/api/config"):
            if request.cookies.get("trim_session", "") != app.state.token:
                return err("token_required", "session token required", 403)
        return await call_next(request)

    @app.exception_handler(LookupError)
    async def _lookup_handler(request: Request, exc: LookupError):
        return err("not_found", "not found", 404)

    def source_or_404(source_id):
        source = db.get_source(source_id)
        if not source:
            raise LookupError(source_id)
        db.touch_source(source_id)
        return source

    async def json_object(request: Request):
        """Parse a JSON object body, returning None for malformed or non-object payloads."""
        try:
            body = await request.json()
        except (ValueError, AttributeError):
            return None
        return body if isinstance(body, dict) else None

    @app.get("/api/health")
    def health():
        return {"ok": True, "ffmpeg": bool(app.state.ffmpeg), "ffmpegVersion": ffmpeg_tools.ffmpeg_version(app.state.ffmpeg), "version": "0.1.0"}

    @app.get("/api/token")
    def token():
        if cfg.get("strongMode"):
            return err("token_disabled", "token is not exposed in strong mode; use /api/auth", 403)
        return {"token": app.state.token, "strongMode": False}

    @app.post("/api/auth")
    async def auth(request: Request):
        body = await json_object(request)
        if body is None:
            return err("invalid_request", "request body must be a JSON object", 400)
        if body.get("token") != app.state.token:
            return err("invalid_token", "invalid token", 403)
        response = JSONResponse({"ok": True})
        response.set_cookie("trim_session", app.state.token, httponly=True, samesite="strict")
        return response

    @app.get("/api/config")
    def config():
        return {
            "allowedRoots": cfg.allowed_roots,
            "defaultUploadOutput": exports.known_videos_dir(),
            "videosDir": exports.known_videos_dir(),
            "strongMode": bool(cfg.get("strongMode")),
            "previewMode": cfg.get("previewMode", "auto"),
            "defaultUi": cfg.get("defaultUi", "qwen"),
            "maxUploadBytes": cfg.get("maxUploadBytes"),
        }

    @app.get("/api/roots")
    def roots():
        result = []
        for root in cfg.allowed_roots:
            p = Path(root)
            result.append({"path": root, "name": p.name or root, "exists": p.exists()})
        return {"roots": result}

    @app.get("/api/browse")
    def browse(path: str = "", showAll: bool = False):
        base = path or (cfg.allowed_roots[0] if cfg.allowed_roots else str(Path.home()))
        try:
            real = security.check_path(base, cfg)
        except (ValueError, PermissionError) as exc:
            return err("invalid_path", str(exc), 400)
        entries = []
        try:
            for item in sorted(Path(real).iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                try:
                    is_dir = item.is_dir()
                except OSError:
                    continue
                if not is_dir and item.suffix.lower() not in MEDIA_EXTS:
                    continue
                if item.name.startswith("$"):
                    continue
                entry = {"name": item.name, "path": str(item), "dir": is_dir}
                try:
                    entry["size"] = item.stat().st_size if not is_dir else None
                except OSError:
                    entry["size"] = None
                entries.append(entry)
        except OSError as exc:
            return err("read_failed", str(exc), 400)
        parent = str(Path(real).parent) if Path(real).parent != Path(real) else None
        return {"path": real, "parent": parent, "entries": entries}

    @app.post("/api/fs/mkdir")
    async def make_directory(request: Request):
        body = await json_object(request)
        if body is None:
            return err("invalid_request", "request body must be a JSON object", 400)
        raw = (body.get("path") or "").strip()
        if not raw:
            return err("invalid_path", "path is required", 400)
        parent = Path(raw).parent
        name = exports.sanitize_dir_name(Path(raw).name)
        if not name:
            return err("invalid_path", "folder name is required", 400)
        target = str(parent / name)
        try:
            security.check_path(target, cfg)
        except (ValueError, PermissionError) as exc:
            return err("invalid_path", str(exc), 400)
        try:
            Path(target).mkdir(parents=False, exist_ok=True)
        except OSError as exc:
            return err("mkdir_failed", str(exc), 400)
        return {"path": str(Path(target))}

    @app.get("/api/fs/download")
    def fs_download(path: str = ""):
        """Serve a file from an allowed root as an attachment (download buttons)."""
        raw = (path or "").strip()
        if not raw:
            return err("invalid_path", "path is required", 400)
        try:
            real = security.check_path(raw, cfg)
        except (ValueError, PermissionError) as exc:
            return err("invalid_path", str(exc), 400)
        target = Path(real)
        if target.suffix.lower() not in MEDIA_EXTS:
            # Keep the server a media appliance: never serve arbitrary files from the LAN.
            return err("invalid_path", "動画・音声ファイルのみダウンロードできます", 400)
        if not target.is_file():
            return err("not_found", "ファイルが見つかりません: " + raw, 404)
        return FileResponse(str(target),
                            media_type=MIME.get(target.suffix.lower(), "application/octet-stream"),
                            filename=target.name)

    async def fs_transfer(request: Request, move: bool):
        body = await json_object(request)
        if body is None:
            return err("invalid_request", "request body must be a JSON object", 400)
        src = str(body.get("source") or "").strip()
        dst = str(body.get("destination") or "").strip()
        if not src or not dst:
            return err("invalid_path", "source and destination are required", 400)
        for label, value in (("source", src), ("destination", dst)):
            try:
                security.check_path(value, cfg)
            except (ValueError, PermissionError) as exc:
                return err("invalid_path", label + ": " + str(exc), 400)
        if not Path(src).exists():
            return err("not_found", "コピー元が見つかりません: " + src, 404)
        if Path(dst).exists() and not Path(dst).is_dir():
            return err("invalid_path", "destination must be a folder", 400)
        # Reject pointless transfers up front so the UI gets an immediate 400 (not a failed job).
        try:
            src_res = Path(src).resolve()
            dst_res = Path(dst).resolve()
            if src_res == dst_res:
                return err("invalid_path", "コピー元とコピー先が同じです", 400)
            if Path(src).is_dir():
                try:
                    dst_res.relative_to(src_res)
                    return err("invalid_path", "フォルダ自身の中にはコピー/移動できません", 400)
                except ValueError:
                    pass
            if move and src_res.parent == dst_res:
                return err("invalid_path", "移動先が同じフォルダです", 400)
        except OSError as exc:
            return err("invalid_path", str(exc), 400)
        try:
            job = fsops.start(cfg, db, jobs, src, dst, move=move)
        except RuntimeError as exc:
            return err("fs_failed", str(exc), 400)
        except OSError as exc:
            return err("fs_failed", str(exc), 400)
        return {"jobId": job.id}

    @app.post("/api/fs/copy")
    async def fs_copy(request: Request):
        return await fs_transfer(request, move=False)

    @app.post("/api/fs/move")
    async def fs_move(request: Request):
        return await fs_transfer(request, move=True)

    @app.post("/api/sources/open")
    async def open_source(request: Request):
        body = await json_object(request)
        if body is None:
            return err("invalid_request", "request body must be a JSON object", 400)
        try:
            rec = sources.open_source(cfg, db, jobs, body.get("path", ""))
        except (ValueError, PermissionError) as exc:
            return err("invalid_path", str(exc), 400)
        except FileNotFoundError:
            return err("not_found", "file not found", 404)
        except RuntimeError as exc:
            return err("probe_failed", str(exc), 400)
        return {"source": public_source(rec)}

    @app.post("/api/sources/upload")
    async def upload(file: UploadFile = File(...)):
        try:
            rec = sources.upload(cfg, db, jobs, file.filename, file.file)
        except ValueError as exc:
            return err("invalid_upload", str(exc), 400)
        except RuntimeError as exc:
            return err("probe_failed", str(exc), 400)
        return {"source": public_source(rec)}

    @app.get("/api/sources")
    def list_sources():
        return {"sources": [public_source(s) for s in sources.list_sources(db)]}

    @app.get("/api/sources/{source_id}")
    def get_source(source_id: str):
        source = db.get_source(source_id)
        if not source:
            return err("not_found", "source not found", 404)
        info = media.streams_to_info(source)
        return {"source": public_source(source), "directPlayable": ffmpeg_tools.direct_playable(info),
                "variant": media.variant_for(cfg, source)}

    @app.get("/api/sources/{source_id}/keyframes")
    def keyframes(source_id: str):
        source = db.get_source(source_id)
        if not source:
            return err("not_found", "source not found", 404)
        return {"state": source.get("index_state"), "keyframes": db.get_keyframes(source_id, 0)}

    @app.get("/api/sources/{source_id}/frames")
    def frames(source_id: str, fromUs: int = 0, countFrames: int = 48, spanUs: int = 4000000):
        source = db.get_source(source_id)
        if not source:
            return err("not_found", "source not found", 404)
        if not media.streams_to_info(source).get("video"):
            return {"frames": []}
        ff, fp = ffmpeg_tools.ffmpeg_paths(cfg)
        values = ffmpeg_tools.frame_times(fp, media.long_path(source["path"]), source.get("video_spec") or "v:0", fromUs, spanUs, countFrames)
        return {"frames": values}

    @app.get("/api/sources/{source_id}/frame")
    def frame(source_id: str, tUs: int = 0, width: int = 1280):
        source = source_or_404(source_id)
        if not media.streams_to_info(source).get("video"):
            return err("no_video", "source has no video stream", 404)
        try:
            path = media.extract_frame(cfg, source, tUs, width=max(160, min(width, 1920)))
        except RuntimeError as exc:
            return err("frame_failed", str(exc), 500)
        return FileResponse(str(path), media_type="image/jpeg", headers={"Cache-Control": "public, max-age=3600"})

    @app.post("/api/sources/{source_id}/proxy")
    def proxy(source_id: str):
        source = db.get_source(source_id)
        if not source:
            return err("not_found", "source not found", 404)
        job = media.start_proxy(cfg, db, jobs, source_id)
        return {"jobId": job.id}

    @app.get("/api/sources/{source_id}/sprite")
    def sprite(source_id: str):
        path = Path(cfg.work_dir) / "sprite" / (source_id + ".jpg")
        if not path.exists():
            return err("not_ready", "sprite not ready", 404)
        return FileResponse(str(path), media_type="image/jpeg")

    @app.post("/api/sources/{source_id}/sprite")
    def sprite_build(source_id: str):
        source = db.get_source(source_id)
        if not source:
            return err("not_found", "source not found", 404)
        job = media.start_sprite(cfg, db, jobs, source_id)
        return {"jobId": job.id}

    @app.delete("/api/sources/{source_id}")
    def delete_source(source_id: str, keepUpload: bool = False):
        ok = sources.delete_source(cfg, db, source_id, keep_upload=keepUpload)
        if not ok:
            return err("not_found", "source not found", 404)
        return {"deleted": True}

    @app.get("/api/sources/{source_id}/media")
    def stream_media(source_id: str, request: Request, variant: str = ""):
        source = source_or_404(source_id)
        chosen = variant or media.variant_for(cfg, source)
        if chosen == "proxy":
            path = media.proxy_path(cfg, source_id)
            if not path.exists():
                return err("proxy_not_ready", "proxy is not ready", 409)
        else:
            path = Path(source["path"])
        if not path.exists():
            return err("not_found", "media not found", 404)
        return range_response(str(path), request)

    @app.post("/api/exports")
    async def create_export(request: Request):
        body = await json_object(request)
        if body is None:
            return err("invalid_request", "request body must be a JSON object", 400)
        source = db.get_source(body.get("sourceId", ""))
        if not source:
            return err("not_found", "source not found", 404)
        options = body.get("options") or {}
        for key in ("videoBitrate", "audioBitrate"):
            value = options.get(key)
            if value in (None, "", 0, "0"):
                options.pop(key, None)
                continue
            try:
                number = int(value)
            except (TypeError, ValueError):
                return err("invalid_bitrate", key + " must be a positive integer in kbps", 400)
            if number <= 0:
                return err("invalid_bitrate", key + " must be a positive integer in kbps", 400)
            options[key] = number
        if body.get("mode"):
            options["mode"] = body.get("mode")
        options.setdefault("mode", "lossless")
        if options.get("outputPath"):
            try:
                security.check_path(options["outputPath"], cfg)
            except (ValueError, PermissionError) as exc:
                return err("invalid_output", str(exc), 400)
        try:
            start_us = int(body.get("startUs", 0))
            end_us = int(body.get("endUs", 0))
        except (TypeError, ValueError):
            return err("invalid_request", "startUs and endUs must be integers", 400)
        if end_us <= start_us:
            return err("invalid_range", "endUs must be greater than startUs", 400)
        try:
            container, selected_streams, _excluded = exports.decide_streams(
                source, json.loads(source.get("streams_json") or "[]"), options.get("container"))
        except ValueError as exc:
            return err("invalid_container", str(exc), 400)
        if options.get("mode") == "reencode" and options.get("audioReencode"):
            audio_stream = next((st for st in selected_streams if st.get("type") == "audio"), None)
            codec = exports.REENCODE_AUDIO_CODECS.get(container, "aac")
            if codec in ("wmav2", "libmp3lame", "mp2") and audio_stream and int(audio_stream.get("channels") or 2) > 2:
                return err("invalid_container",
                           "このコンテナの音声再エンコードは2チャンネルまでです", 400)
        try:
            job = exports.start_export(cfg, db, jobs, source, start_us, end_us, options)
        except ValueError as exc:
            return err("invalid_range", str(exc), 400)
        return {"jobId": job.id}

    def with_source_name(job):
        sid = job.get("sourceId")
        if sid:
            try:
                row = db.get_source(sid)
                if row:
                    job["sourceName"] = row["name"]
            except Exception:
                pass
        return job

    def persisted_job(row):
        try:
            result = json.loads(row.get("result_json") or "null")
        except ValueError:
            result = None
        return with_source_name({"id": row["id"], "kind": row.get("kind"), "sourceId": row.get("source_id"),
                                 "status": row.get("status"), "progress": row.get("progress"),
                                 "message": row.get("message"), "result": result, "error": row.get("error"),
                                 "persisted": True})

    @app.get("/api/jobs")
    def list_jobs(history: int = 20):
        live = {job["id"]: with_source_name(job) for job in jobs.list()}
        merged = list(live.values())
        if history:
            for row in db.list_jobs(limit=max(1, min(int(history), 100))):
                if row["id"] not in live:
                    merged.append(persisted_job(row))
        return {"jobs": merged}

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        job = jobs.get(job_id)
        if job:
            return {"job": with_source_name(job.to_dict())}
        row = db.get_job(job_id)
        if row:
            return {"job": persisted_job(row)}
        return err("not_found", "job not found", 404)

    @app.get("/api/jobs/{job_id}/events")
    async def job_events(job_id: str, request: Request):
        job = jobs.get(job_id)
        if not job:
            return err("not_found", "job not found", 404)
        last = 0
        header = request.headers.get("last-event-id")
        if header and header.isdigit():
            last = int(header)

        async def gen():
            queue = asyncio.Queue()

            def pump():
                for event in job.stream(last):
                    asyncio.run_coroutine_threadsafe(queue.put(event), loop)
                asyncio.run_coroutine_threadsafe(queue.put(None), loop)

            loop = asyncio.get_running_loop()
            threading.Thread(target=pump, daemon=True).start()
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield "id: " + str(event["id"]) + "\n" + "event: " + event["kind"] + "\n" + "data: " + json.dumps(event["data"], ensure_ascii=False) + "\n\n"
                if event.get("kind") == "done":
                    break

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str):
        if not jobs.cancel(job_id):
            return err("not_found", "job not found", 404)
        return {"cancelling": True}

    @app.get("/api/luts")
    def luts():
        result = []
        for ext in ("*.cube", "*.3dl", "*.dat"):
            for item in cfg.luts_dir.glob(ext):
                result.append({"name": item.name, "path": str(item)})
        return {"luts": sorted(result, key=lambda x: x["name"])}

    @app.post("/api/paths/validate")
    async def validate(request: Request):
        body = await json_object(request)
        if body is None:
            return err("invalid_request", "request body must be a JSON object", 400)
        path = body.get("path") or ""
        if not path:
            return err("invalid_path", "path is required", 400)
        try:
            security.check_path(path, cfg)
        except (ValueError, PermissionError) as exc:
            return err("invalid_path", str(exc), 400)
        source = db.get_source(body.get("sourceId", "")) if body.get("sourceId") else None
        return exports.validate_output(cfg, db, source, path, body.get("startUs"), body.get("endUs"))

    @app.get("/compare", response_class=HTMLResponse)
    def compare():
        return HTMLResponse(COMPARE_HTML)

    # Qwen UI (TrimStudio) is the primary interface served at the root;
    # the original UI stays available at /web and /qwen keeps working for old links.
    app.mount("/web", StaticFiles(directory=str(cfg.web_dir), html=True), name="web")
    app.mount("/qwen", StaticFiles(directory=str(cfg.web_qwen_dir), html=True), name="qwen")
    app.mount("/", StaticFiles(directory=str(cfg.web_qwen_dir), html=True), name="root")
    return app


def public_source(rec):
    streams = json.loads(rec.get("streams_json") or "[]")
    meta = json.loads(rec.get("meta_json") or "{}")
    has_video = any(st.get("type") == "video" and not st.get("attached_pic") for st in streams)
    kind = "video" if has_video else ("audio" if any(st.get("type") == "audio" for st in streams) else "other")
    video_stream = next((st for st in streams if st.get("type") == "video" and not st.get("attached_pic")), None)
    audio_stream = next((st for st in streams if st.get("type") == "audio"), None)
    return {
        "bitRate": meta.get("bit_rate"),
        "videoBitRate": (video_stream or {}).get("bit_rate"),
        "audioBitRate": (audio_stream or {}).get("bit_rate"),
        "meta": meta,
        "id": rec["id"], "kind": kind, "name": rec["name"], "path": rec["path"], "origin": rec["origin"],
        "container": rec.get("container"), "durationUs": rec.get("duration_us"), "size": rec.get("size"),
        "width": rec.get("width"), "height": rec.get("height"), "fps": rec.get("fps"),
        "videoCodec": rec.get("video_codec"), "audioCodec": rec.get("audio_codec"),
        "pixFmt": rec.get("pix_fmt"), "indexState": rec.get("index_state"),
        "streams": json.loads(rec.get("streams_json") or "[]"),
    }


def range_response(path, request: Request):
    size = os.path.getsize(path)
    mime = MIME.get(Path(path).suffix.lower(), "application/octet-stream")
    range_header = request.headers.get("range")
    headers = {"Accept-Ranges": "bytes", "X-Content-Type-Options": "nosniff", "Content-Disposition": "inline"}
    if not range_header:
        return FileResponse(path, media_type=mime, headers=headers)
    match = re.match(r"bytes=(\d*)-(\d*)", range_header)
    if not match:
        return FileResponse(path, media_type=mime, headers=headers)
    if not match.group(1) and match.group(2):
        # suffix range: bytes=-N means the last N bytes
        length = min(int(match.group(2)), size)
        start = size - length
        end = size - 1
    else:
        start = int(match.group(1)) if match.group(1) else 0
        end = int(match.group(2)) if match.group(2) else size - 1
    start = max(0, min(start, size - 1))
    end = max(start, min(end, size - 1))
    length = end - start + 1
    resp_headers = dict(headers)
    resp_headers["Content-Range"] = "bytes %d-%d/%d" % (start, end, size)
    resp_headers["Content-Length"] = str(length)
    return StreamingResponse(media.read_range(path, start, end + 1), status_code=206, media_type=mime, headers=resp_headers)


COMPARE_HTML = """<!doctype html><meta charset="utf-8"><title>Trim UI compare</title>
<style>html,body{margin:0;height:100%} .row{display:flex;height:100%} iframe{flex:1;border:0;border-right:2px solid #333} header{font:14px sans-serif;padding:6px}</style>
<header>Left: TrimStudio (Qwen UI, /) &nbsp;|&nbsp; Right: classic UI (/web/)</header>
<div class="row"><iframe src="/"></iframe><iframe src="/web/"></iframe></div>"""

app = create_app()
