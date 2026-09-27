"""Shared in-memory job registry for long-running background work (a Monte
Carlo batch, a guided search, a stress test). Extracted from api.py so new
route modules (passport_api.py) can start and report on jobs the same way
without a circular import between api.py and them.
"""
from __future__ import annotations

import queue
import threading
import time
import uuid


class Job:
    def __init__(self, job_id: str, kind: str, label: str, total: int):
        self.id = job_id
        self.kind = kind
        self.label = label
        self.total = total
        self.completed = 0
        self.status = "running"
        self.phase = "simulating"
        self.started = time.time()
        self.error: str | None = None
        self.result: dict | None = None
        self.batch_id: str | None = None
        self.events: queue.Queue = queue.Queue(maxsize=4096)
        self.latest: dict = {}

    def push(self, payload: dict) -> None:
        self.latest = payload
        try:
            self.events.put_nowait(payload)
        except queue.Full:
            pass

    def snapshot(self) -> dict:
        return dict(
            job_id=self.id, kind=self.kind, label=self.label, status=self.status,
            phase=self.phase, completed=self.completed, total=self.total,
            elapsed_s=round(time.time() - self.started, 2),
            batch_id=self.batch_id, error=self.error,
            runs_per_second=round(
                self.completed / max(time.time() - self.started, 1e-6), 2),
            latest=self.latest,
        )


JOBS: dict[str, Job] = {}
JOB_LOCK = threading.Lock()


def new_job(kind: str, label: str, total: int) -> Job:
    job = Job(uuid.uuid4().hex[:12], kind, label, total)
    with JOB_LOCK:
        JOBS[job.id] = job
    return job


def progress_for(job: Job):
    def cb(p: dict):
        job.completed = p.get("completed", job.completed)
        if p.get("phase"):
            job.phase = p["phase"]
        if p.get("batch_id"):
            job.batch_id = p["batch_id"]
        job.push(p)
    return cb


def finish_job(job: Job, result: dict | None, batch_id: str | None = None):
    job.status = "complete"
    job.phase = "complete"
    job.result = result
    if batch_id:
        job.batch_id = batch_id
    job.push(dict(phase="complete", batch_id=job.batch_id,
                  completed=job.completed, total=job.total))


def fail_job(job: Job, exc: Exception):
    job.status = "error"
    job.phase = "error"
    job.error = f"{type(exc).__name__}: {exc}"
    job.push(dict(phase="error", error=job.error))
