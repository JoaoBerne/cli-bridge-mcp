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

import os
import re
import signal
import subprocess
from dataclasses import dataclass

# Output ceiling (~50k tokens). Real answers pass through whole; only a runaway dump
# is clipped. NOT a "make it short" truncation — the ceiling sits far above any answer.
MAX_OUTPUT_CHARS = 200_000

# Best-effort secret scrubbing for anything we echo back (errors, output).
_REDACTIONS = (
    (re.compile(r"(Authorization:\s*Bearer\s+)[^\s'\"]+", re.I), r"\1[redacted]"),
    (re.compile(r"(X-API-Key:\s*)[^\s'\"]+", re.I), r"\1[redacted]"),
    (re.compile(r"(sk-[A-Za-z0-9_-]{8})[A-Za-z0-9_-]+"), r"\1[redacted]"),
    (re.compile(r"(gh[pousr]_[A-Za-z0-9]{6})[A-Za-z0-9]+"), r"\1[redacted]"),
    (re.compile(r"(\"?(?:api[_-]?key|token|secret|password)\"?\s*[:=]\s*\"?)[^\s\"',]+", re.I),
     r"\1[redacted]"),
)

# stderr fingerprints -> a stable, actionable error kind the caller can branch on.
_QUOTA = re.compile(r"RESOURCE_EXHAUSTED|quota|rate.?limit|too many requests|\b429\b", re.I)
_AUTH = re.compile(r"unauthorized|not logged in|authenticat|login required|\b401\b|api key", re.I)


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
            cwd=cwd or None, env=env, start_new_session=True,
        )
    except FileNotFoundError:
        return RunResult(False, f"`{argv[0]}` not found on PATH", "not_found")
    except (PermissionError, OSError) as e:
        return RunResult(False, f"`{argv[0]}` could not start: {e}", "spawn")

    try:
        out, err = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        proc.communicate()  # reap, free pipes
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
    """Kill the whole process group so the CLI's children don't survive as orphans."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        proc.kill()
        return
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            proc.kill()
