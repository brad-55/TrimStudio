"""Copy and move operations for the file explorer, executed as background jobs."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from .exports import long_path

CHUNK = 4 * 1024 * 1024


def unique_target(target: Path) -> Path:
    """Never overwrite: append -1, -2, ... while the name is taken."""
    if not target.exists():
        return target
    index = 1
    while True:
        candidate = target.with_name(target.stem + "-" + str(index) + target.suffix)
        if not candidate.exists():
            return candidate
        index += 1


def _copy_file(job, src: Path, dst: Path):
    total = max(1, src.stat().st_size)
    done = 0
    tmp = dst.with_name(dst.name + ".part")
    try:
        with open(long_path(str(src)), "rb") as fh, open(long_path(str(tmp)), "wb") as out:
            while True:
                if job.is_cancelled():
                    raise RuntimeError("cancelled")
                buf = fh.read(CHUNK)
                if not buf:
                    break
                out.write(buf)
                done += len(buf)
                job.update(progress=min(0.99, float(done) / float(total)))
        shutil.copystat(long_path(str(src)), long_path(str(tmp)))
        os.replace(long_path(str(tmp)), long_path(str(dst)))
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def _size(path: Path) -> int:
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for root, _dirs, names in os.walk(long_path(str(path))):
        for name in names:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                pass
    return total


def _copy_tree(job, src: Path, dst: Path):
    files = []
    if src.is_dir():
        for root, _dirs, names in os.walk(long_path(str(src))):
            for name in names:
                files.append(Path(root) / name)
        dst.mkdir(parents=True, exist_ok=True)
    else:
        files = [src]
    total = max(1, len(files))
    for index, item in enumerate(files):
        if job.is_cancelled():
            raise RuntimeError("cancelled")
        if src.is_dir():
            target = dst / item.relative_to(src)
        else:
            target = dst
        target.parent.mkdir(parents=True, exist_ok=True)
        _copy_file(job, item, unique_target(target))
        job.update(progress=min(0.99, float(index + 1) / float(total)))


def start(cfg, db, jobs, source_path, destination, move=False):
    """Copy or move one or more files/folders into the destination folder.

    `source_path` may be a single path or a list; a batch runs as one job so the user
    sees one progress bar and one entry in the job list.
    """
    sources = list(source_path) if isinstance(source_path, (list, tuple)) else [source_path]

    def runner(job):
        dest_root = Path(destination)
        if len(sources) > 1:
            dest_root.mkdir(parents=True, exist_ok=True)
            done, failed = [], []
            for index, one in enumerate(sources):
                job.update(progress=min(0.99, float(index) / float(len(sources))),
                           message="%d/%d %s" % (index + 1, len(sources),
                                                 "移動中" if move else "コピー中"))
                try:
                    done.append(_transfer(job, Path(one), dest_root, move))
                except Exception as exc:  # keep going: one bad file must not stop the batch
                    failed.append({"path": str(one), "error": str(exc)[:200]})
            job.update(progress=1.0, message="done")
            if failed and not done:
                raise RuntimeError("すべて失敗しました: " + "; ".join(f["error"] for f in failed[:3]))
            return {"outputPaths": [d.get("outputPath") for d in done],
                    "count": len(done), "moved": move, "failed": failed}
        return _transfer(job, Path(sources[0]), dest_root, move)

    def _transfer(job, src, dest_root, move):
        if not src.exists():
            raise RuntimeError("コピー元が見つかりません: " + str(src))
        if src.resolve() == dest_root.resolve():
            raise RuntimeError("コピー元とコピー先が同じです")
        if src.is_dir():
            try:
                dest_root.resolve().relative_to(src.resolve())
                raise RuntimeError("フォルダ自身の中にはコピー/移動できません")
            except ValueError:
                pass
        dest_root.mkdir(parents=True, exist_ok=True)
        if move and src.parent.resolve() == dest_root.resolve():
            raise RuntimeError("移動先が同じフォルダです")
        target = unique_target(dest_root / src.name)
        if move:
            job.update(message="moving", progress=0.1)
            try:
                os.replace(long_path(str(src)), long_path(str(target)))
            except OSError:
                try:
                    _copy_tree(job, src, target)
                except Exception:
                    # Cancelled or failed mid-copy: drop the partial destination, keep the source.
                    try:
                        if target.is_dir():
                            shutil.rmtree(long_path(str(target)), ignore_errors=True)
                        elif target.exists():
                            target.unlink()
                    except OSError:
                        pass
                    raise
                try:
                    if src.is_dir():
                        shutil.rmtree(long_path(str(src)))
                    else:
                        src.unlink()
                except OSError as exc:
                    raise RuntimeError(
                        "コピーは完了しましたが元を削除できませんでした（使用中の可能性）: " + str(exc))
            job.update(progress=1.0, message="done")
            return {"outputPath": str(target), "moved": True, "bytes": _size(target)}
        job.update(message="copying", progress=0.05)
        _copy_tree(job, src, target)
        job.update(progress=1.0, message="done")
        return {"outputPath": str(target), "moved": False, "bytes": _size(target)}

    try:
        dest_root = Path(destination)
        if not dest_root.exists():
            dest_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeError("コピー先を作成できません: " + str(exc))
    return jobs.create("move" if move else "copy", None, runner)
