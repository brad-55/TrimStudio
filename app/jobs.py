"""Background job manager with SSE event streams."""
import os
import subprocess
import threading
import time
import uuid

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def kill_process_tree(proc):
    if proc is None or proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, creationflags=CREATE_NO_WINDOW)
        else:
            proc.terminate()
    except OSError:
        pass


class Job:
    def __init__(self, job_id, kind, source_id, db=None):
        self.id = job_id
        self.kind = kind
        self.source_id = source_id
        self.db = db
        self.status = "queued"
        self.progress = 0.0
        self.message = ""
        self.result = None
        self.error = None
        self.cancel = threading.Event()
        self.proc = None
        self.created_at = time.time()
        self.updated_at = self.created_at
        self.events = []
        self.seq = 0
        self.cond = threading.Condition()
        self.thread = None
        self.runner = None

    @property
    def done(self):
        return self.status in ("done", "error", "cancelled")

    def persist(self):
        if self.db is None:
            return
        try:
            self.db.upsert_job({"id": self.id, "kind": self.kind, "source_id": self.source_id,
                                "status": self.status, "progress": self.progress, "message": self.message,
                                "result": self.result, "error": self.error,
                                "created_at": self.created_at, "updated_at": self.updated_at})
        except Exception:
            pass

    def emit(self, kind, data):
        with self.cond:
            self.seq += 1
            self.events.append((self.seq, kind, data, time.time()))
            if len(self.events) > 2000:
                del self.events[:1000]
            self.cond.notify_all()

    def update(self, progress=None, message=None, status=None):
        with self.cond:
            if progress is not None:
                self.progress = float(progress)
            if message is not None:
                self.message = message
            if status is not None:
                self.status = status
            self.updated_at = time.time()
            self.cond.notify_all()
        self.emit("state", self.to_dict())
        self.persist()

    def set_proc(self, proc):
        self.proc = proc

    def is_cancelled(self):
        return self.cancel.is_set()

    def to_dict(self):
        return {
            "id": self.id,
            "kind": self.kind,
            "sourceId": self.source_id,
            "status": self.status,
            "progress": round(self.progress, 4),
            "message": self.message,
            "result": self.result,
            "error": self.error,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }

    def start(self, runner, semaphore, source_lock=None):
        self.runner = runner
        self.source_lock = source_lock
        self.thread = threading.Thread(target=self._run, args=(semaphore,), daemon=True)
        self.thread.start()

    def _run(self, semaphore):
        semaphore.acquire()
        if self.source_lock is not None:
            self.source_lock.acquire()
        try:
            if self.is_cancelled():
                self.status = "cancelled"
                self.emit("done", self.to_dict())
                return
            self.status = "running"
            self.update(message="started")
            result = self.runner(self)
            if self.is_cancelled():
                self.status = "cancelled"
                self.result = result
            else:
                self.status = "done"
                self.result = result
                self.progress = 1.0
        except Exception as exc:
            if self.is_cancelled():
                self.status = "cancelled"
            else:
                self.status = "error"
            self.error = str(exc)
            self.emit("log", {"level": "error", "message": repr(exc)})
        finally:
            self.updated_at = time.time()
            self.persist()
            milestone = self.to_dict()
            self.emit("done", milestone)
            with self.cond:
                self.cond.notify_all()
            if self.source_lock is not None:
                self.source_lock.release()
            semaphore.release()

    def stream(self, after_id=0):
        idx = 0
        while True:
            with self.cond:
                while idx < len(self.events) and self.events[idx][0] <= after_id:
                    idx += 1
                if idx < len(self.events):
                    ev = self.events[idx]
                    idx += 1
                elif self.done:
                    return
                else:
                    self.cond.wait(timeout=10)
                    if idx >= len(self.events) and not self.done:
                        yield {"id": self.seq, "kind": "heartbeat", "data": {}}
                    continue
            yield {"id": ev[0], "kind": ev[1], "data": ev[2], "time": ev[3]}

    def cancel_job(self):
        self.cancel.set()
        kill_process_tree(self.proc)


class JobManager:
    def __init__(self, db, concurrency=2):
        self.db = db
        self.jobs = {}
        self.lock = threading.RLock()
        self.semaphore = threading.Semaphore(max(1, int(concurrency)))
        self.source_locks = {}
        self.lock_guard = threading.Lock()

    def source_lock(self, kind, source_id):
        if not source_id or kind not in ("export", "proxy", "sprite", "index"):
            return None
        key = (kind, source_id)
        with self.lock_guard:
            lock = self.source_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self.source_locks[key] = lock
            return lock

    def create(self, kind, source_id, runner):
        job_id = uuid.uuid4().hex
        job = Job(job_id, kind, source_id, db=self.db)
        with self.lock:
            self.jobs[job_id] = job
        job.persist()
        job.start(runner, self.semaphore, self.source_lock(kind, source_id))
        return job

    def get(self, job_id):
        with self.lock:
            return self.jobs.get(job_id)

    def list(self):
        with self.lock:
            return [job.to_dict() for job in self.jobs.values()]

    def cancel(self, job_id):
        job = self.get(job_id)
        if job is None:
            return False
        job.cancel_job()
        return True
