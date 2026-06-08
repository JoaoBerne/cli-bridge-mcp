"""Subprocess runner — spawn an AI CLI safely and return a clean result.

Hardening (learned running these CLIs headless):
- start_new_session + killpg on timeout: the CLI's *children* (network uploads,
  helper daemons) die too, instead of surviving as orphans burning quota/credits.
- stdin=DEVNULL: a CLI that still tries to read input fails fast instead of hanging
  on a hidden prompt until the timeout fires.
- errors="replace": non-UTF8 output can't crash the decode.
- secrets redacted from anything we hand back.
- on success we return stdout only — several CLIs echo their whole banner/transcript
  to stderr at exit 0, which would flood the caller's context with useless tokens.
- output capped: a runaway/garbage dump can't blow up the caller's context window.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import signal
import subprocess
import time
from dataclasses import dataclass

# Opt-in logging: silent by default (a library shouldn't spam). Set CLI_BRIDGE_LOG=debug|info
# to a file (CLI_BRIDGE_LOG_FILE, default stderr) for "which CLI ran, how long, what failed".
log = logging.getLogger("cli_bridge")
if not log.handlers:
    _level = os.environ.get("CLI_BRIDGE_LOG", "").strip().upper()
    if _level in {"DEBUG", "INFO", "WARNING", "ERROR"}:
        _path = os.environ.get("CLI_BRIDGE_LOG_FILE", "").strip()
        _h = logging.FileHandler(_path) if _path else logging.StreamHandler()
        _h.setFormatter(logging.Formatter("%(asctime)s cli-bridge %(levelname)s %(message)s"))
        log.addHandler(_h)
        log.setLevel(_level)
    else:
        log.addHandler(logging.NullHandler())

# Output ceiling (~50k tokens). Real answers pass through whole; only a runaway dump
# is clipped. NOT a "make it short" truncation — the ceiling sits far above any answer.
MAX_OUTPUT_CHARS = 200_000

# Stall guard for the streaming path: if a delegate emits NO line for this long, it's wedged
# (a CLI that hangs after a clean banner, a stuck network call) — kill it instead of waiting
# out the full timeout_s. Only applies when streaming (the buffered path relies on timeout_s).
DEFAULT_NO_OUTPUT_TIMEOUT_S = 120

# Best-effort secret scrubbing for anything we echo back (errors, output).
_REDACTIONS = (
    (re.compile(r"(Authorization:\s*Bearer\s+)\S+", re.I), r"\1[redacted]"),
    (re.compile(r"(X-API-Key:\s*)\S+", re.I), r"\1[redacted]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{6,}"), "[redacted]"),          # OpenAI / Anthropic
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{6,}"), "[redacted]"),     # GitHub tokens
    (re.compile(r"\bAIza[A-Za-z0-9_-]{6,}"), "[redacted]"),         # Google API keys
    (re.compile(r"(\"?(?:api[_-]?key|token|secret|password)\"?\s*[:=]\s*\"?)[^\s\"']+", re.I),
     r"\1[redacted]"),
)

# stderr fingerprints -> a stable, actionable error kind the caller can branch on.
_QUOTA = re.compile(r"RESOURCE_EXHAUSTED|quota|rate.?limit|too many requests|\b429\b", re.I)
_AUTH = re.compile(r"unauthorized|not logged in|authenticat|login required|\b401\b|api key", re.I)
# A delegate can REFUSE on usage-policy grounds and still exit 0 — Claude Code prints
# "API Error: Claude Code is unable to respond to this request, which appears to violate our
# Usage Policy ... Request ID: req_…". Without this, that refusal flows through as a SUCCESSFUL
# answer and gets cached. Require BOTH co-occurring phrases (the refusal sentence AND the policy
# clause) so a normal answer that merely mentions "usage policy" or "API Error" can't misfire.
_POLICY = re.compile(
    r"unable to respond to this request.*violate (?:our|the)\s+usage policy", re.I | re.S)


def _is_policy_refusal(text: str) -> bool:
    return bool(_POLICY.search(text or ""))


def _failure_kind(out: str, err: str) -> str:
    """Classify a delegate result's failure (shared by the exit-0 and non-zero paths)."""
    if _is_policy_refusal(out) or _is_policy_refusal(err):
        return "policy"
    blob = f"{err}\n{out}"
    return "quota" if _QUOTA.search(blob) else "auth" if _AUTH.search(blob) else "failed"

# Cross-platform process-tree control. POSIX: new session + killpg(group). Windows: new
# process group + taskkill /T (whole tree). Without this, timeout/cancel cleanup crashes on
# Windows (os.killpg / os.getpgid don't exist there).
_IS_WINDOWS = os.name == "nt"


def _spawn_kwargs() -> dict:
    if _IS_WINDOWS:
        # getattr keeps mypy happy on POSIX (the attr is Windows-only); the _IS_WINDOWS guard
        # already prevents the 0 fallback from ever being used off Windows.
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    return {"start_new_session": True}


def _kill_tree(pid: int, sig: int) -> None:
    """Kill the whole process tree so a CLI's children don't survive as orphans."""
    if _IS_WINDOWS:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                       capture_output=True, check=False)
    else:
        os.killpg(os.getpgid(pid), sig)


def redact(text: str) -> str:
    for pattern, repl in _REDACTIONS:
        text = pattern.sub(repl, text)
    return text


def _clip(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + (
        f"\n\n[... output clipped at {MAX_OUTPUT_CHARS} chars — re-run with a narrower task]"
    )


@dataclass
class RunResult:
    ok: bool
    output: str
    kind: str = "ok"          # ok|timeout|not_found|quota|auth|failed|spawn|empty|policy|stalled
    exit_code: int | None = None
    latency_ms: int = 0       # wall time of the spawn, filled in by the caller (server._run_lane)
    model: str = ""           # resolved model that ran, filled in by the caller (provenance)

    def render(self) -> str:
        """One string for the MCP tool result. Errors are prefixed so the caller can tell
        them apart from a successful answer that merely contains the word 'error'."""
        if self.ok:
            return self.output
        hint = {
            "timeout": " (raise timeout_s for heavier tasks)",
            "quota": " - this CLI's quota/rate limit is exhausted; try later or another lane",
            "auth": " - log into this CLI in your terminal, then retry",
            "not_found": " - is the CLI installed and on PATH?",
            "empty": " - this CLI exited cleanly but returned nothing - on a free tier this is "
                     "almost always silent quota/rate-limit exhaustion; trying another lane (the "
                     "lane is cooled down after repeated empties)",
            "policy": " - this CLI refused on usage-policy grounds; revise the request or skip "
                      "this lane",
            "stalled": " - this CLI produced no output for a long stretch and was killed; "
                       "retry or try another lane",
        }.get(self.kind, "")
        return f"[{self.kind}] {self.output}{hint}".rstrip()


# ── per-lane spawn pacing: opt-in anti-burst throttle ───────────────────────────────────────
# Field finding (June 2026 quality eval): firing several calls at ONE lane back-to-back gets a
# free tier rate-limited into returning empty (gemini: 315/343 calls dead in one run) — and the
# failure-cooldown never trips because successes interleave with the empties. Pacing spaces
# same-lane spawns; DIFFERENT lanes are unaffected, so council fan-out stays parallel. Opt-in
# per lane: CLI_BRIDGE_<LANE>_MIN_INTERVAL_S=2 (seconds, float).
_PACE_LAST: dict[str, float] = {}
_PACE_LOCKS: dict[str, asyncio.Lock] = {}


async def pace(key: str, min_interval_s: float) -> float:
    """Delay so consecutive spawns of `key` are >= min_interval_s apart. Returns the wait that
    was applied (0.0 when none). Same-key callers serialize through a lock so a parallel burst
    becomes an evenly-spaced queue; other keys never wait. No-op at <= 0."""
    if min_interval_s <= 0:
        return 0.0
    lock = _PACE_LOCKS.setdefault(key, asyncio.Lock())
    async with lock:
        last = _PACE_LAST.get(key)
        wait = max(0.0, min_interval_s - (time.monotonic() - last)) if last is not None else 0.0
        if wait > 0:
            await asyncio.sleep(wait)
        _PACE_LAST[key] = time.monotonic()
        return wait


def _ok_or_empty(out: str, err: str, argv: list[str]) -> RunResult:
    """Map an exit-0 run to a result. stdout is the answer; stderr is usually banner/progress
    noise, but a few CLIs put a short answer there, so fall back to it. An exit-0 with NO output
    at all is a SOFT failure ("empty") — some CLIs (e.g. `agy`/gemini in print mode) exit clean yet
    say nothing, which on a free tier is almost always silent quota exhaustion — so ask_cascade/
    ask_best fall THROUGH to a lane that actually answers. A single empty is per-call (fall-through,
    not cached); telemetry cools the lane down only after REPEATED consecutive empties (quota)."""
    text = out or err
    if not text:
        return RunResult(False, f"`{argv[0]}` returned no output (exit 0) - likely quota/rate-limit "
                         "exhausted on a free tier", "empty", 0)
    # Exit 0 but the delegate REFUSED on policy grounds — a soft failure, like "empty":
    # cascade/ask_best fall through to a lane that answers, and it is never cached. Check both
    # streams AND the combined blob so a refusal split across stdout+stderr is still caught.
    if _is_policy_refusal(out) or _is_policy_refusal(err) or _is_policy_refusal(f"{out}\n{err}"):
        return RunResult(False, _clip(text), "policy", 0)
    return RunResult(True, _clip(text), "ok", 0)


def _finish(returncode, out, err, argv) -> RunResult:
    out = redact((out or "").strip())
    err = redact((err or "").strip())
    if returncode == 0:
        return _ok_or_empty(out, err, argv)
    detail = err or out or "(no output)"
    return RunResult(False, _clip(f"{argv[0]} exit {returncode}: {detail}"),
                     _failure_kind(out, err), returncode)


async def _terminate(proc) -> None:
    """Kill the spawned process and its whole group, escalating SIGTERM -> SIGKILL. Shared by
    the buffered and streaming paths, and by host-cancel / timeout / stall cleanup."""
    try:
        _kill_tree(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except ProcessLookupError:
            return
    try:
        await asyncio.wait_for(proc.wait(), timeout=3)
    except (asyncio.TimeoutError, ProcessLookupError):
        try:
            _kill_tree(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass


async def _arun_streamed(proc, argv: list[str], timeout_s: int, on_line, log_path: str | None,
                         no_output_timeout: float) -> RunResult:
    """Streaming variant: read stdout AND stderr concurrently so neither pipe can deadlock the
    other (qwen #4: a 64 KB stderr burst while stdout idles must not wedge), emit each line to
    `on_line(stream, text)` and/or append it to `log_path`, and classify the final result through
    the SAME `_finish` as the buffered path. Two guards run on top:
      • outer timeout (`timeout_s`) — `wait_for` ONLY here, over the whole gather, never over a
        bare readline (a reader cancelled mid-read would corrupt the captured output);
      • stall guard — if no line arrives for `no_output_timeout`s, it KILLS the process, which
        EOFs the pipes and lets the readers finish naturally; we then report kind=`stalled`.
    """
    out_lines: list[str] = []
    err_lines: list[str] = []
    last_activity = time.monotonic()
    stalled = False

    log_fh = None
    if log_path:
        try:
            # newline="" → identical log bytes on POSIX and Windows (no \n -> \r\n translation).
            log_fh = open(log_path, "w", encoding="utf-8", errors="replace", newline="")
        except OSError as e:                       # best-effort sink: never fail the spawn over it
            log.warning("log_path %s could not open: %s", log_path, e)

    async def _reader(stream, sink: list[str], name: str) -> None:
        nonlocal last_activity
        while True:
            raw = await stream.readline()
            if not raw:                            # EOF
                break
            last_activity = time.monotonic()
            text = redact(raw.decode("utf-8", "replace"))   # redact before it leaves the process
            sink.append(text)
            if log_fh:
                log_fh.write(text)
                log_fh.flush()
            if on_line is not None:
                try:
                    on_line(name, text)
                except Exception:                  # a bad callback must never break the pump
                    log.exception("on_line callback raised")

    async def _stall_guard() -> None:
        nonlocal stalled
        while True:
            remaining = no_output_timeout - (time.monotonic() - last_activity)
            if remaining <= 0:
                stalled = True
                await _terminate(proc)             # kill -> pipes EOF -> readers finish
                return
            await asyncio.sleep(remaining)         # wakes exactly at the deadline; resets on output

    core = asyncio.gather(
        _reader(proc.stdout, out_lines, "stdout"),
        _reader(proc.stderr, err_lines, "stderr"),
        proc.wait(),
    )
    guard = (asyncio.ensure_future(_stall_guard())
             if no_output_timeout and no_output_timeout > 0 else None)

    try:
        await asyncio.wait_for(core, timeout=timeout_s)
    except asyncio.TimeoutError:
        if guard:
            guard.cancel()
        await _terminate(proc)
        if log_fh:
            log_fh.close()
        log.error("%s timed out after %ss (process group killed)", argv[0], timeout_s)
        return RunResult(False, f"`{argv[0]}` timed out after {timeout_s}s", "timeout")
    except asyncio.CancelledError:
        if guard:
            guard.cancel()
        await _terminate(proc)
        if log_fh:
            log_fh.close()
        log.info("%s cancelled by host (process group killed)", argv[0])
        raise

    if guard is not None:
        guard.cancel()
        try:
            await guard
        except asyncio.CancelledError:
            pass
    if log_fh:
        log_fh.close()

    if stalled:
        partial = ("".join(out_lines) or "".join(err_lines)).strip()
        log.error("%s stalled (no output for %ss; process group killed)",
                  argv[0], no_output_timeout)
        return RunResult(
            False,
            _clip(f"`{argv[0]}` produced no output for {no_output_timeout:g}s (stalled, killed)"
                  + (f"\n{partial}" if partial else "")),
            "stalled")

    res = _finish(proc.returncode, "".join(out_lines), "".join(err_lines), argv)
    log.info("%s exit=%s kind=%s out=%dch (streamed)",
             argv[0], proc.returncode, res.kind, len(res.output))
    return res


async def arun(argv: list[str], timeout_s: int, cwd: str | None = None,
               env: dict | None = None, on_line=None, log_path: str | None = None,
               no_output_timeout: float = DEFAULT_NO_OUTPUT_TIMEOUT_S) -> RunResult:
    """The one spawn path (server and CLI both come through here). If the MCP host CANCELS
    the call (disconnect, client timeout), the CancelledError propagates here and we kill the
    whole process group — so the CLI can't keep burning quota/credits after the host gave up.

    Pass `on_line(stream, text)` and/or `log_path` to OBSERVE the delegate live (each stdout/
    stderr line as it arrives). That switches to the streaming path (`_arun_streamed`), which
    also enforces a no-output stall guard (`no_output_timeout`). With neither set, behaviour is
    the original buffered `communicate()` — byte-for-byte unchanged, no regression.
    """
    if not argv:
        return RunResult(False, "empty command", "spawn")
    log.info("spawn %s (timeout=%ss, cwd=%s)", argv[0], timeout_s, cwd or ".")
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL, cwd=cwd or None, env=env,
            **_spawn_kwargs(),
        )
    except FileNotFoundError:
        log.error("%s not found on PATH", argv[0])
        return RunResult(False, f"`{argv[0]}` not found on PATH", "not_found")
    except (PermissionError, OSError) as e:
        log.error("%s could not start: %s", argv[0], e)
        return RunResult(False, f"`{argv[0]}` could not start: {e}", "spawn")

    if on_line is not None or log_path is not None:
        return await _arun_streamed(proc, argv, timeout_s, on_line, log_path, no_output_timeout)

    try:
        out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        await _terminate(proc)
        log.error("%s timed out after %ss (process group killed)", argv[0], timeout_s)
        return RunResult(False, f"`{argv[0]}` timed out after {timeout_s}s", "timeout")
    except asyncio.CancelledError:
        await _terminate(proc)          # host gave up — don't leave the CLI running
        log.info("%s cancelled by host (process group killed)", argv[0])
        raise
    res = _finish(proc.returncode,
                  out_b.decode("utf-8", "replace"), err_b.decode("utf-8", "replace"), argv)
    log.info("%s exit=%s kind=%s out=%dch", argv[0], proc.returncode, res.kind, len(res.output))
    return res
