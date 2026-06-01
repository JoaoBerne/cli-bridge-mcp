"""Multi-model workflow tools built on the lane council.

`review_diff` is the first: a git diff is reviewed by several lanes wearing DIFFERENT hats
(correctness / security / tests / maintainability), then one lane merges and de-duplicates the
findings into a single ranked report. Diverse roles beat N identical reviewers — each lens
catches issues the others miss.

Decoupled from server.py on purpose: the orchestration takes a `run_lane` coroutine and an
already-filtered list of target lanes, so it can be unit-tested with fakes (no real CLI, no
network) and the cost/cooldown policy stays in one place (server._ask_all_targets).

Output is for HUMANS to act on, so the reviewer/merge passes run with terse=False (full
reasoning, full sentences). The only machine-readable part is a deterministic trace block we
build ourselves — we never try to parse findings back out of free-text model output.
"""
from __future__ import annotations

import asyncio
import json
import subprocess

from . import config
from .lanes import LaneSpec

# (role, what this reviewer should look for). Order also sets round-robin priority when there
# are fewer lanes than roles — correctness/security first.
REVIEW_ROLES: list[tuple[str, str]] = [
    ("correctness",
     "Logic errors, wrong assumptions, edge cases, off-by-one, null/None handling, "
     "error paths, and concurrency races."),
    ("security",
     "OWASP-aware: injection, broken authz, secrets committed to code, unsafe "
     "deserialization, path traversal, SSRF, and unvalidated input."),
    ("tests",
     "Missing or weak test coverage: untested branches, missing edge-case tests, brittle "
     "assertions, and behaviour changes that no test would catch."),
    ("maintainability",
     "Readability, naming, dead code, duplication, needless complexity, and unclear "
     "interfaces."),
]

_GIT_DIFF_TIMEOUT_S = 30


def git_diff(cwd: str, base: str) -> tuple[str, str]:
    """Return (diff_text, error). Empty error == success; diff_text may be empty (no changes).

    `base` defaults to HEAD, so the natural call reviews uncommitted working-tree changes.
    Pass a ref/range (e.g. 'main', 'HEAD~3', 'main...HEAD') to review something else.
    """
    base = base or "HEAD"
    try:
        proc = subprocess.run(
            ["git", "-C", cwd or ".", "diff", base],
            capture_output=True, text=True, errors="replace",
            timeout=_GIT_DIFF_TIMEOUT_S, check=False)
    except FileNotFoundError:
        return "", "git is not installed / not on PATH."
    except (OSError, subprocess.TimeoutExpired) as e:
        return "", f"git diff failed: {e}"
    if proc.returncode != 0:
        return "", f"git diff exited {proc.returncode}: {proc.stderr.strip()[:300]}"
    return proc.stdout, ""


def assign_roles(lanes: list[LaneSpec]) -> list[tuple[str, str, LaneSpec]]:
    """Round-robin the review roles over the available lanes.

    Fewer lanes than roles → a lane wears several hats (every role still gets reviewed).
    More lanes than roles → only the first len(ROLES) lanes are used (one role each).
    """
    if not lanes:
        return []
    return [(role, desc, lanes[i % len(lanes)])
            for i, (role, desc) in enumerate(REVIEW_ROLES)]


def review_prompt(role: str, desc: str, diff: str, truncated: bool) -> str:
    trunc = ("\n\n[NOTE: diff truncated to fit context — review only what is shown above]"
             if truncated else "")
    return (
        f"You are a senior code reviewer. Review ONLY the **{role}** dimension: {desc}\n\n"
        "For each real issue give: severity (critical/high/medium/low), the file:line if "
        "visible in the diff, the problem, and a concrete fix. Report only genuine issues in "
        f"your dimension — if there are none, reply exactly 'No {role} issues found.' "
        "Do not restate the diff or review other dimensions.\n\n"
        f"```diff\n{diff}{trunc}\n```")


def merge_prompt(reviews: list[tuple[str, str, str]]) -> str:
    body = "\n\n".join(f"### {role} reviewer ({lane})\n{text}" for role, lane, text in reviews)
    return (
        "Merge these role-specific code-review findings into ONE deduplicated report. "
        "Group findings by severity (critical first, then high/medium/low). When several "
        "reviewers flag the same thing, keep ONE entry and note the agreement (it is more "
        "likely real). For each finding give: severity, location (file:line), the issue, and "
        "a concrete fix. Finish with a single-line overall risk verdict. Be precise; no "
        f"padding, no restating the diff.\n\n{body}")


def _assemble_report(merged: str, reviews: list[tuple[str, str, str]], meta: dict) -> str:
    lines = ["# Code review (multi-model)", ""]
    flags = []
    if meta.get("truncated"):
        flags.append("diff truncated")
    flags.append("read-only")
    lines.append(f"_Base: `{meta['base']}` · reviewers: {meta['reviewers']} · "
                 f"{' · '.join(flags)}_\n")
    lines.append("## Merged findings\n")
    lines.append(merged.strip() or "_(merge step produced no output)_")
    if len(reviews) > 1 or not merged.strip():
        lines.append("\n## Per-reviewer detail\n")
        for role, lane, text in reviews:
            lines.append(f"<details><summary>{role} — {lane}</summary>\n\n"
                         f"{text.strip()}\n\n</details>")
    lines.append("\n## Trace\n")
    lines.append("```json\n" + json.dumps(meta, indent=2) + "\n```")
    return "\n".join(lines)


def _timeout(raw) -> int:
    try:
        return max(1, min(int(raw), config.MAX_TIMEOUT_S))
    except (TypeError, ValueError):
        return config.REVIEW_DEFAULT_TIMEOUT_S


async def review_diff(targets: list[LaneSpec], args: dict, run_lane) -> str:
    """Multi-model review of a git diff. `targets` are pre-filtered eligible lanes (free /
    non-cooled, paid only if the caller widened). `run_lane(lane, args, *, tool, terse)` is the
    server's lane runner, injected so this stays testable without a real CLI."""
    cwd = (args.get("cwd") or "").strip()
    base = (args.get("base") or "").strip() or "HEAD"
    diff = args.get("diff") or ""
    if not diff:
        diff, err = git_diff(cwd, base)
        if err:
            return f"[error] {err}"
    if not diff.strip():
        return (f"[review_diff] empty diff (base={base}). Nothing to review. "
                "Make changes first, or pass a different `base` / a `diff` directly.")
    if not targets:
        return ("[error] no lanes available for review. Install/login a CLI, or set "
                "include_paid=true / CLI_BRIDGE_PROFILE=max to allow limited/paid lanes.")

    truncated = len(diff) > config.REVIEW_DIFF_MAX_CHARS
    diff_in = diff[:config.REVIEW_DIFF_MAX_CHARS] if truncated else diff
    timeout = _timeout(args.get("timeout_s"))
    roles = assign_roles(targets)

    async def _review(role: str, desc: str, lane: LaneSpec):
        sub = {"task": review_prompt(role, desc, diff_in, truncated),
               "cwd": cwd, "timeout_s": timeout}
        res = await run_lane(lane, sub, tool="review_diff", terse=False)
        return role, lane, res

    raw = await asyncio.gather(*[_review(r, d, l) for r, d, l in roles],
                               return_exceptions=True)
    reviews: list[tuple[str, str, str]] = []
    failures: list[str] = []
    for item in raw:
        if isinstance(item, BaseException):
            failures.append(f"crash:{item}")
            continue
        role, lane, res = item
        if res.ok:
            reviews.append((role, lane.display, res.output))
        else:
            failures.append(f"{role}={res.kind}")

    if not reviews:
        return "[error] all reviewers failed: " + ", ".join(failures) + ". Check `doctor`."

    meta = {
        "base": base,
        "reviewers": [f"{role} ({lane})" for role, lane, _ in reviews],
        "roles_failed": failures,
        "truncated": truncated,
        "diff_chars": len(diff),
    }

    # Merge pass only earns its cost with ≥2 reviews; a single review is already the report.
    if len(reviews) >= 2:
        judge = targets[0]
        merged = await run_lane(judge, {"task": merge_prompt(reviews), "timeout_s": timeout},
                                tool="review_diff", terse=False)
        merged_text = merged.output if merged.ok else ""
        meta["merge_lane"] = judge.display if merged.ok else f"FAILED ({merged.kind})"
    else:
        merged_text = reviews[0][2]
        meta["merge_lane"] = "n/a (single reviewer)"

    return _assemble_report(merged_text, reviews, meta)
