"""In-process async jobs so slow council runs survive MCP host tool-call deadlines.

A job wraps a coroutine (e.g. the ask_all body) in asyncio.create_task and returns a job id
immediately; the host polls `job_status` and fetches `job_result` later. The live registry is
the source of truth for THIS process; a best-effort sqlite row lets a restart flip stale
'running' jobs to 'interrupted' — v1 does NOT resume work across restarts (the spawned CLIs
are already gone). Cancelling a job cancels its task, which propagates into runner.arun and
kills the delegate's whole process group.
"""
from __future__ import annotations

import asyncio
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from . import config, telemetry

RUNNING, SUCCEEDED, FAILED, CANCELLED, INTERRUPTED = (
    "running", "succeeded", "failed", "cancelled", "interrupted")


@dataclass
class Job:
    id: str
    kind: str
    preview: str
    created_at: float
    status: str = RUNNING
    result: str | None = None
    error: str | None = None
    result_path: str | None = None
    task: asyncio.Task | None = field(default=None, repr=False)


_JOBS: dict[str, Job] = {}


def _new_id() -> str:
    return "job_" + uuid.uuid4().hex[:12]


def _spill(job_id: str, text: str) -> str | None:
    """Persist a finished job's result to the overflow dir so it can be fetched later (and,
    if huge, streamed selectively). Best-effort — the in-memory copy is the primary store."""
    try:
        os.makedirs(config.OVERFLOW_DIR, exist_ok=True)
        path = os.path.join(config.OVERFLOW_DIR, f"{job_id}.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path
    except OSError:
        return None


def log_path_for(job_id: str) -> str:
    """Deterministic per-job log path in the overflow dir. A long-running build appends its
    turn-by-turn progress here so `job_tail` can stream it (byte-offset reads)."""
    try:
        os.makedirs(config.OVERFLOW_DIR, exist_ok=True)
    except OSError:
        pass
    return os.path.join(config.OVERFLOW_DIR, f"{job_id}.log")


def _read(path: str | None) -> str | None:
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


async def _run(job: Job, make_coro: Callable[[], Awaitable[str]]) -> None:
    try:
        result = await make_coro()
        job.result = result
        job.result_path = _spill(job.id, result)
        job.status = SUCCEEDED
        telemetry.job_put(job.id, job.kind, SUCCEEDED, job.preview, result_path=job.result_path)
    except asyncio.CancelledError:
        job.status = CANCELLED
        telemetry.job_put(job.id, job.kind, CANCELLED, job.preview, error="cancelled")
        raise                                   # let the task settle as cancelled
    except Exception as e:                       # a crashing job must not sink the server loop
        job.status = FAILED
        job.error = f"{type(e).__name__}: {e}"
        telemetry.job_put(job.id, job.kind, FAILED, job.preview, error=job.error)


def start_job(kind: str, make_coro: Callable[[], Awaitable[str]], preview: str) -> str:
    """Schedule `make_coro()` as a background task and return its id immediately (<<1s).
    Must be called from within the running event loop (it is — from a tool dispatch)."""
    job = Job(id=_new_id(), kind=kind, preview=(preview or "").strip()[:120].replace("\n", " "),
              created_at=time.time())
    _JOBS[job.id] = job
    telemetry.job_put(job.id, kind, RUNNING, job.preview)
    job.task = asyncio.create_task(_run(job, make_coro))
    return job.id


def status(job_id: str) -> dict | None:
    """Live job if this process started it, else a persisted row (e.g. 'interrupted' after a
    restart), else None for an unknown id."""
    job = _JOBS.get(job_id)
    if job is not None:
        return {"id": job.id, "kind": job.kind, "status": job.status, "preview": job.preview,
                "error": job.error, "result_path": job.result_path, "created_at": job.created_at}
    return telemetry.job_row(job_id)


def result(job_id: str) -> tuple[str, str] | None:
    """(status, body) or None if the id is unknown. body is '' while still running."""
    job = _JOBS.get(job_id)
    if job is not None:
        if job.status == RUNNING:
            return (RUNNING, "")
        if job.result is not None:
            return (job.status, job.result)
        body = _read(job.result_path)
        if body is not None:
            return (job.status, body)
        return (job.status, f"[{job.status}] {job.error or ''}".strip())
    row = telemetry.job_row(job_id)
    if row is None:
        return None
    body = _read(row.get("result_path"))
    if body is None:
        body = f"[{row['status']}] {row.get('error') or ''}".strip()
    return (row["status"], body)


def cancel(job_id: str) -> str:
    """Request cancellation. Returns 'cancelling' once the task is signalled (the final
    'cancelled' status lands asynchronously), or the current status if already finished."""
    job = _JOBS.get(job_id)
    if job is None:
        row = telemetry.job_row(job_id)
        return "unknown" if row is None else row["status"]
    if job.status != RUNNING or job.task is None:
        return job.status
    job.task.cancel()
    return "cancelling"


def listing(limit: int = 20) -> list[dict]:
    """Live jobs (this process) first, then persisted rows not held in memory."""
    live = sorted(_JOBS.values(), key=lambda j: j.created_at, reverse=True)
    out = [{"id": j.id, "kind": j.kind, "status": j.status, "preview": j.preview} for j in live]
    seen = {j.id for j in live}
    for row in telemetry.jobs_recent(limit):
        if row["id"] not in seen:
            out.append({"id": row["id"], "kind": row["kind"], "status": row["status"],
                        "preview": row["task_preview"]})
    return out[:limit]


def mark_interrupted_on_startup() -> int:
    return telemetry.jobs_mark_running_interrupted()


def _reset_for_tests() -> None:
    _JOBS.clear()
