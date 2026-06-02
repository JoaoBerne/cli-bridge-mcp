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
        _migrate(conn)
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
  input_chars INTEGER NOT NULL DEFAULT 0,
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
CREATE TABLE IF NOT EXISTS response_cache (
  key TEXT PRIMARY KEY,
  ok INTEGER NOT NULL,
  output TEXT NOT NULL,
  kind TEXT NOT NULL,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  status TEXT NOT NULL,
  task_preview TEXT,
  result_path TEXT,
  error TEXT,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
"""


# Columns added after v1 shipped — best-effort ALTER so existing DBs gain them without a wipe.
_MIGRATIONS = (("runs", "input_chars", "INTEGER NOT NULL DEFAULT 0"),)


def _migrate(conn: sqlite3.Connection) -> None:
    for table, col, decl in _MIGRATIONS:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
        except sqlite3.Error:
            pass   # already present (or table absent) — fine


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


def record(run: RunStart, ok: bool, kind: str, output_chars: int, input_chars: int = 0) -> None:
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
                "duration_ms, output_chars, input_chars, started_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (run.tool, run.lane, run.model, status, kind, task_hash, preview,
                 duration_ms, output_chars, input_chars, run.started_at))
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


def lane_perf() -> dict:
    """{lane: {"runs", "avg_ms", "fail_rate"}} — used by the router to bias fast/healthy lanes."""
    conn = _connect()
    if conn is None:
        return {}
    try:
        with _LOCK:
            rows = conn.execute(
                "SELECT lane, COUNT(*), SUM(status='ok'), AVG(duration_ms) "
                "FROM runs WHERE lane IS NOT NULL GROUP BY lane").fetchall()
    except sqlite3.Error:
        return {}
    out = {}
    for lane, n, ok, avg in rows:
        n = n or 0
        out[lane] = {"runs": n, "avg_ms": int(avg or 0),
                     "fail_rate": (1 - (ok or 0) / n) if n else 0.0}
    return out


def _est_credits(lane: str, total_tokens: float) -> float | None:
    rate = config.lane_env_float(lane, "CREDITS_PER_1K")   # cost per 1k total tokens
    return round(rate * total_tokens / 1000, 4) if rate is not None else None


def usage_report(limit_recent: int = 10, since_s: float | None = None) -> dict:
    """Local usage with ESTIMATED token/credit figures (chars/4; per-lane CREDITS_PER_1K if set).
    since_s limits to runs in the last N seconds. Estimates are never presented as exact."""
    conn = _connect()
    if conn is None:
        return {"enabled": False}
    where, params = ("WHERE started_at >= ?", (_now() - since_s,)) if since_s else ("", ())
    try:
        with _LOCK:
            total = conn.execute(f"SELECT COUNT(*) FROM runs {where}", params).fetchone()[0]
            by_lane = conn.execute(
                f"SELECT lane, COUNT(*), SUM(status='ok'), AVG(duration_ms), "
                f"SUM(input_chars), SUM(output_chars) FROM runs {where} "
                f"GROUP BY lane ORDER BY COUNT(*) DESC", params).fetchall()
            recent = conn.execute(
                f"SELECT tool, lane, model, status, kind, duration_ms, task_preview "
                f"FROM runs {where} ORDER BY id DESC LIMIT ?", (*params, limit_recent)).fetchall()
    except sqlite3.Error:
        return {"enabled": False}
    cpt = config.CHARS_PER_TOKEN
    lanes_out, est_total = [], 0.0
    have_rate = False
    for (lane, n, ok, avg, inc, outc) in by_lane:
        in_tok, out_tok = int((inc or 0) / cpt), int((outc or 0) / cpt)
        cred = _est_credits(lane, in_tok + out_tok) if lane else None
        if cred is not None:
            have_rate = True
            est_total += cred
        lanes_out.append({"lane": lane, "runs": n, "ok": int(ok or 0), "avg_ms": int(avg or 0),
                          "est_input_tokens": in_tok, "est_output_tokens": out_tok,
                          "est_credits": cred})
    return {
        "enabled": True,
        "total_runs": total,
        "since_s": since_s,
        "token_basis": f"estimated (chars/{cpt})",
        "est_total_credits": round(est_total, 4) if have_rate else None,
        "by_lane": lanes_out,
        "recent": [
            {"tool": t, "lane": ln, "model": m, "status": s, "kind": k,
             "duration_ms": d, "task": p} for (t, ln, m, s, k, d, p) in recent],
    }


def _utc_day_start() -> float:
    t = _now()
    g = time.gmtime(t)
    return t - (g.tm_hour * 3600 + g.tm_min * 60 + g.tm_sec)


def est_credits_today() -> float:
    """Total ESTIMATED paid credits spent since UTC midnight (for the hard budget cap)."""
    rep = usage_budget()
    if not rep.get("enabled"):
        return 0.0
    return round(sum(r["est_credits_today"] or 0 for r in rep["by_lane"]), 4)


def usage_budget() -> dict:
    """Per-lane runs since UTC midnight vs an optional CLI_BRIDGE_<LANE>_DAILY_LIMIT, plus the
    estimated credits spent today. All token/credit figures are estimates."""
    conn = _connect()
    if conn is None:
        return {"enabled": False}
    start = _utc_day_start()
    try:
        with _LOCK:
            rows = conn.execute(
                "SELECT lane, COUNT(*), SUM(input_chars), SUM(output_chars) FROM runs "
                "WHERE started_at >= ? AND lane IS NOT NULL GROUP BY lane", (start,)).fetchall()
    except sqlite3.Error:
        return {"enabled": False}
    cpt = config.CHARS_PER_TOKEN
    lanes = []
    for lane, n, inc, outc in rows:
        limit = config.lane_env_int(lane, "DAILY_LIMIT")
        tok = int(((inc or 0) + (outc or 0)) / cpt)
        lanes.append({
            "lane": lane, "runs_today": n, "daily_limit": limit,
            "over_limit": bool(limit is not None and n > limit),
            "est_tokens_today": tok, "est_credits_today": _est_credits(lane, tok),
        })
    return {"enabled": True, "day_start_utc": start, "by_lane": lanes}


def cache_get(key: str, ttl_s: int) -> tuple[bool, str, str] | None:
    """Return (ok, output, kind) if a fresh cached response exists, else None. Best-effort."""
    if ttl_s <= 0 or not key:
        return None
    conn = _connect()
    if conn is None:
        return None
    try:
        with _LOCK:
            row = conn.execute(
                "SELECT ok, output, kind, created_at FROM response_cache WHERE key=?",
                (key,)).fetchone()
    except sqlite3.Error:
        return None
    if not row or (_now() - row[3]) > ttl_s:
        return None
    return (bool(row[0]), row[1], row[2])


def cache_put(key: str, ok: bool, output: str, kind: str) -> None:
    """Store a response for later identical calls. Best-effort: never raises."""
    conn = _connect()
    if conn is None or not key:
        return
    try:
        with _LOCK:
            conn.execute(
                "INSERT INTO response_cache (key, ok, output, kind, created_at) VALUES (?,?,?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET ok=excluded.ok, output=excluded.output, "
                "kind=excluded.kind, created_at=excluded.created_at",
                (key, 1 if ok else 0, output, kind, _now()))
            conn.commit()
    except sqlite3.Error:
        pass


# ── async jobs (persisted so a restart can flip stale 'running' rows to 'interrupted') ──

def job_put(job_id: str, kind: str, status: str, task_preview: str,
            result_path: str | None = None, error: str | None = None) -> None:
    """Insert/update a job row. Best-effort: never raises (jobs work in-process even if off)."""
    conn = _connect()
    if conn is None or not job_id:
        return
    try:
        with _LOCK:
            conn.execute(
                "INSERT INTO jobs (id, kind, status, task_preview, result_path, error, "
                "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET status=excluded.status, "
                "result_path=excluded.result_path, error=excluded.error, "
                "updated_at=excluded.updated_at",
                (job_id, kind, status, task_preview, result_path, error, _now(), _now()))
            conn.commit()
    except sqlite3.Error:
        pass


def job_row(job_id: str) -> dict | None:
    conn = _connect()
    if conn is None or not job_id:
        return None
    try:
        with _LOCK:
            r = conn.execute(
                "SELECT id, kind, status, task_preview, result_path, error, created_at, "
                "updated_at FROM jobs WHERE id=?", (job_id,)).fetchone()
    except sqlite3.Error:
        return None
    if not r:
        return None
    return {"id": r[0], "kind": r[1], "status": r[2], "task_preview": r[3],
            "result_path": r[4], "error": r[5], "created_at": r[6], "updated_at": r[7]}


def jobs_recent(limit: int = 20) -> list[dict]:
    conn = _connect()
    if conn is None:
        return []
    try:
        with _LOCK:
            rows = conn.execute(
                "SELECT id, kind, status, task_preview, result_path, error, created_at, "
                "updated_at FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    except sqlite3.Error:
        return []
    return [{"id": r[0], "kind": r[1], "status": r[2], "task_preview": r[3],
             "result_path": r[4], "error": r[5], "created_at": r[6], "updated_at": r[7]}
            for r in rows]


def jobs_mark_running_interrupted() -> int:
    """On server start, any row still 'running' is from a dead process — its spawned CLIs are
    gone, so flip it to 'interrupted' (v1 does not resume work across restarts)."""
    conn = _connect()
    if conn is None:
        return 0
    try:
        with _LOCK:
            cur = conn.execute(
                "UPDATE jobs SET status='interrupted', updated_at=? WHERE status='running'",
                (_now(),))
            conn.commit()
            return cur.rowcount
    except sqlite3.Error:
        return 0


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
