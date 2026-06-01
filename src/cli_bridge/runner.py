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

import logging
import os
import re
import signal
import subprocess
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

# Cross-platform process-tree control. POSIX: new session + killpg(group). Windows: new
# process group + taskkill /T (whole tree). Without this, timeout/cancel cleanup crashes on
# Windows (os.killpg / os.getpgid don't exist there).
_IS_WINDOWS = os.name == "nt"


def _spawn_kwargs() -> dict:
    if _IS_WINDOWS:
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
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
    kind: str = "ok"          # ok | timeout | not_found | quota | auth | failed | spawn
    exit_code: int | None = None
    latency_ms: int = 0       # wall time of the spawn, filled in by the caller (server._run_lane)

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
        }.get(self.kind, "")
        return f"[{self.kind}] {self.output}{hint}".rstrip()


def run(argv: list[str], timeout_s: int, cwd: str | None = None,
        env: dict | None = None) -> RunResult:
    if not argv:
        return RunResult(False, "empty command", "spawn")
    try:
        proc = subprocess.Popen(
            argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, errors="replace", stdin=subprocess.DEVNULL,
            cwd=cwd or None, env=env, **_spawn_kwargs(),
        )
    except FileNotFoundError:
        return RunResult(False, f"`{argv[0]}` not found on PATH", "not_found")
    except (PermissionError, OSError) as e:
        return RunResult(False, f"`{argv[0]}` could not start: {e}", "spawn")

    try:
        out, err = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        try:
            proc.communicate(timeout=5)  # reap, free pipes — bounded so a zombie can't hang us
        except subprocess.TimeoutExpired:
            pass
        return RunResult(False, f"`{argv[0]}` timed out after {timeout_s}s", "timeout")

    out = redact((out or "").strip())
    err = redact((err or "").strip())

    if proc.returncode == 0:
        # stdout only on success; stderr here is banner/progress noise. Fall back to
        # stderr if stdout is empty (a few CLIs put a short answer there).
        return RunResult(True, _clip(out or err or "(empty response)"), "ok", 0)

    blob = f"{err}\n{out}"
    kind = "quota" if _QUOTA.search(blob) else "auth" if _AUTH.search(blob) else "failed"
    detail = err or out or "(no output)"
    return RunResult(False, _clip(f"{argv[0]} exit {proc.returncode}: {detail}"),
                     kind, proc.returncode)


def _kill_group(proc: subprocess.Popen) -> None:
    """Kill the whole process tree so the CLI's children don't survive as orphans."""
    try:
        _kill_tree(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        proc.kill()
        return
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            _kill_tree(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            proc.kill()


def _finish(returncode, out, err, argv) -> RunResult:
    out = redact((out or "").strip())
    err = redact((err or "").strip())
    if returncode == 0:
        # stdout only on success; stderr here is banner/progress noise. Fall back to stderr
        # if stdout is empty (a few CLIs put a short answer there).
        return RunResult(True, _clip(out or err or "(empty response)"), "ok", 0)
    blob = f"{err}\n{out}"
    kind = "quota" if _QUOTA.search(blob) else "auth" if _AUTH.search(blob) else "failed"
    detail = err or out or "(no output)"
    return RunResult(False, _clip(f"{argv[0]} exit {returncode}: {detail}"), kind, returncode)


async def arun(argv: list[str], timeout_s: int, cwd: str | None = None,
               env: dict | None = None) -> RunResult:
    """Async runner used by the server. Unlike the threaded `run`, if the MCP host CANCELS
    the call (disconnect, client timeout), the CancelledError propagates here and we kill the
    whole process group — so the CLI can't keep burning quota/credits after the host gave up.
    """
    if not argv:
        return RunResult(False, "empty command", "spawn")
    import asyncio  # local import keeps `run` usable without an event loop
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

    async def _terminate():
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

    try:
        out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        await _terminate()
        log.error("%s timed out after %ss (process group killed)", argv[0], timeout_s)
        return RunResult(False, f"`{argv[0]}` timed out after {timeout_s}s", "timeout")
    except asyncio.CancelledError:
        await _terminate()              # host gave up — don't leave the CLI running
        log.info("%s cancelled by host (process group killed)", argv[0])
        raise
    res = _finish(proc.returncode,
                  out_b.decode("utf-8", "replace"), err_b.decode("utf-8", "replace"), argv)
    log.info("%s exit=%s kind=%s out=%dch", argv[0], proc.returncode, res.kind, len(res.output))
    return res
