"""Local telemetry + lane health/cooldown — stdlib sqlite3, no external deps, privacy-first.

Why: routing/cooldown need facts (which lane is failing, in quota cooldown, slow), not
guesses from current process state. This records one row per delegate run and keeps a small
per-lane health table.

Privacy: we store a task HASH + short PREVIEW only, never the full prompt/output, unless
CLI_BRIDGE_STORE_TRANSCRIPTS=true. The DB lives under the user's data dir and never leaves
the machine. Telemetry is on by default but fully disablable (CLI_BRIDGE_TELEMETRY=off);
every call is best-effort and must NEVER break a delegation if the DB is unavailable.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
import time
from dataclasses import dataclass

from . import config

_LOCK = threading.Lock()
_CONN: sqlite3.Connection | None = None
_DISABLED = False  # set if init fails, so we stop trying


def _now() -> float:
    return time.time()


def _connect() -> sqlite3.Connection | None:
    global _CONN, _DISABLED
    if _DISABLED or not config.telemetry_enabled():
        return None
    if _CONN is not None:
        return _CONN
    try:
        path = config.state_db_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        conn = sqlite3.connect(path, check_same_thread=False, timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)
        conn.commit()
        _CONN = conn
        return conn
    except (OSError, sqlite3.Error):
        _DISABLED = True
        return None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tool TEXT NOT NULL,
  lane TEXT,
  model TEXT,
  status TEXT NOT NULL,
  kind TEXT NOT NULL,
  task_hash TEXT,
  task_preview TEXT,
  duration_ms INTEGER,
  output_chars INTEGER,
  started_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS lane_state (
  lane TEXT PRIMARY KEY,
  consecutive_failures INTEGER NOT NULL DEFAULT 0,
  consecutive_timeouts INTEGER NOT NULL DEFAULT 0,
  cooldown_until REAL,
  last_kind TEXT,
  last_model TEXT,
  last_run_at REAL,
  total_runs INTEGER NOT NULL DEFAULT 0,
  total_failures INTEGER NOT NULL DEFAULT 0
);
"""


@dataclass
class RunStart:
    tool: str
    lane: str
    model: str
    task: str
    started_at: float


def start(tool: str, lane: str, model: str, task: str) -> RunStart:
    return RunStart(tool=tool, lane=lane, model=model, task=task, started_at=_now())


def _store_transcripts() -> bool:
    return os.environ.get("CLI_BRIDGE_STORE_TRANSCRIPTS", "").strip().lower() in {"1", "true", "yes", "on"}


def record(run: RunStart, ok: bool, kind: str, output_chars: int) -> None:
    """Record a finished run + update the lane's health/cooldown. Best-effort: never raises."""
    conn = _connect()
    if conn is None:
        return
    duration_ms = int((_now() - run.started_at) * 1000)
    task_hash = hashlib.sha1(run.task.encode("utf-8", "replace")).hexdigest()[:16]
    preview = (run.task[:120] if _store_transcripts() else run.task[:60]).replace("\n", " ")
    status = "ok" if ok else "error"
    try:
        with _LOCK:
            conn.execute(
                "INSERT INTO runs (tool, lane, model, status, kind, task_hash, task_preview, "
                "duration_ms, output_chars, started_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (run.tool, run.lane, run.model, status, kind, task_hash, preview,
                 duration_ms, output_chars, run.started_at))
            _update_lane_state(conn, run.lane, ok, kind, run.model)
            conn.commit()
    except sqlite3.Error:
        pass


# Failure kinds that should cool a lane down (transient/credential, not "the task was bad").
_COOLING_KINDS = {"timeout", "quota", "auth"}


def _update_lane_state(conn: sqlite3.Connection, lane: str, ok: bool, kind: str, model: str) -> None:
    if not lane:
        return
    row = conn.execute(
        "SELECT consecutive_failures, consecutive_timeouts, total_runs, total_failures "
        "FROM lane_state WHERE lane=?", (lane,)).fetchone()
    cf, ct, total, tfail = row if row else (0, 0, 0, 0)

    cooldown_until = None
    if ok:
        cf = ct = 0
    else:
        tfail += 1
        ct = ct + 1 if kind == "timeout" else 0
        cf = cf + 1 if kind in _COOLING_KINDS else cf
        if kind == "quota":
            cooldown_until = _now() + config.COOLDOWN_QUOTA_S
        elif kind == "auth":
            cooldown_until = _now() + config.COOLDOWN_AUTH_S
        elif kind == "timeout" and ct >= config.COOLDOWN_TIMEOUT_THRESHOLD:
            cooldown_until = _now() + config.COOLDOWN_TIMEOUT_S

    conn.execute(
        "INSERT INTO lane_state (lane, consecutive_failures, consecutive_timeouts, "
        "cooldown_until, last_kind, last_model, last_run_at, total_runs, total_failures) "
        "VALUES (?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(lane) DO UPDATE SET consecutive_failures=excluded.consecutive_failures, "
        "consecutive_timeouts=excluded.consecutive_timeouts, cooldown_until=excluded.cooldown_until, "
        "last_kind=excluded.last_kind, last_model=excluded.last_model, "
        "last_run_at=excluded.last_run_at, total_runs=excluded.total_runs, "
        "total_failures=excluded.total_failures",
        (lane, cf, ct, cooldown_until, kind, model, _now(), total + 1, tfail))


def cooldown_remaining(lane: str) -> int:
    """Seconds left in this lane's cooldown, 0 if none / unknown. Best-effort."""
    conn = _connect()
    if conn is None or not lane:
        return 0
    try:
        with _LOCK:
            row = conn.execute("SELECT cooldown_until FROM lane_state WHERE lane=?", (lane,)).fetchone()
    except sqlite3.Error:
        return 0
    if not row or not row[0]:
        return 0
    return max(0, int(row[0] - _now()))


def reset_lane(lane: str) -> bool:
    """Clear a lane's cooldown/failure counters. Returns True if a row was cleared."""
    conn = _connect()
    if conn is None:
        return False
    try:
        with _LOCK:
            cur = conn.execute(
                "UPDATE lane_state SET consecutive_failures=0, consecutive_timeouts=0, "
                "cooldown_until=NULL WHERE lane=?", (lane,))
            conn.commit()
            return cur.rowcount > 0
    except sqlite3.Error:
        return False


def lane_stats() -> list[dict]:
    conn = _connect()
    if conn is None:
        return []
    try:
        with _LOCK:
            rows = conn.execute(
                "SELECT lane, total_runs, total_failures, consecutive_failures, "
                "consecutive_timeouts, cooldown_until, last_kind, last_model, last_run_at "
                "FROM lane_state ORDER BY lane").fetchall()
    except sqlite3.Error:
        return []
    out = []
    for (lane, total, tfail, cf, ct, cd, kind, model, last) in rows:
        out.append({
            "lane": lane, "total_runs": total, "total_failures": tfail,
            "consecutive_failures": cf, "consecutive_timeouts": ct,
            "cooldown_remaining_s": max(0, int(cd - _now())) if cd else 0,
            "last_kind": kind, "last_model": model, "last_run_at": last,
        })
    return out


def usage_report(limit_recent: int = 10) -> dict:
    conn = _connect()
    if conn is None:
        return {"enabled": False}
    try:
        with _LOCK:
            total = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
            by_lane = conn.execute(
                "SELECT lane, COUNT(*), SUM(status='ok'), AVG(duration_ms) "
                "FROM runs GROUP BY lane ORDER BY COUNT(*) DESC").fetchall()
            recent = conn.execute(
                "SELECT tool, lane, model, status, kind, duration_ms, task_preview "
                "FROM runs ORDER BY id DESC LIMIT ?", (limit_recent,)).fetchall()
    except sqlite3.Error:
        return {"enabled": False}
    return {
        "enabled": True,
        "total_runs": total,
        "by_lane": [
            {"lane": l, "runs": n, "ok": int(ok or 0),
             "avg_ms": int(avg or 0)} for (l, n, ok, avg) in by_lane],
        "recent": [
            {"tool": t, "lane": l, "model": m, "status": s, "kind": k,
             "duration_ms": d, "task": p} for (t, l, m, s, k, d, p) in recent],
    }


def _reset_for_tests() -> None:
    """Test helper: drop the in-process connection so a new DB path is picked up."""
    global _CONN, _DISABLED
    with _LOCK:
        if _CONN is not None:
            try:
                _CONN.close()
            except sqlite3.Error:
                pass
        _CONN = None
        _DISABLED = False
