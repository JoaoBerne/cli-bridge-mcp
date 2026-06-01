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


# ── council recap: surface what every delegate returned, never a blind spot (user req) ──

def one_phrase(text: str, limit: int = 120) -> str:
    """First meaningful line of an answer, flattened to a one-line gist for the recap."""
    for line in (text or "").splitlines():
        s = line.strip().lstrip("#-*>•· \t").strip()
        if s:
            return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"
    return "(empty)"


def council_recap(rows: list[tuple[str, bool, int, str]], *, title: str = "Council") -> str:
    """The at-a-glance digest the host sees FIRST: one line per delegate — answered?, latency
    (when known), a one-line gist — so there's never a blind spot about what each model said.
    The full answers follow below; this just guarantees every voice is surfaced.

    rows: (display, ok, latency_ms, text). latency_ms<=0 is omitted (workflows don't thread it).
    """
    answered = sum(1 for _, ok, _, _ in rows if ok)
    lines = [f"## {title} — {answered}/{len(rows)} answered", ""]
    for display, ok, ms, text in rows:
        mark = "✅" if ok else "❌"
        ms_s = f" _{ms}ms_" if ms and ms > 0 else ""
        gist = one_phrase(text) if ok else (text or "no answer")
        lines.append(f"- {mark} **{display}**{ms_s} — {gist}")
    return "\n".join(lines)


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


def _assign(roles_def: list[tuple[str, str]],
            lanes: list[LaneSpec]) -> list[tuple[str, str, LaneSpec]]:
    """Round-robin a set of roles over the available lanes.

    Fewer lanes than roles → a lane wears several hats (every role still gets reviewed).
    More lanes than roles → only the first len(roles) lanes are used (one role each).
    """
    if not lanes:
        return []
    return [(role, desc, lanes[i % len(lanes)]) for i, (role, desc) in enumerate(roles_def)]


def assign_roles(lanes: list[LaneSpec]) -> list[tuple[str, str, LaneSpec]]:
    return _assign(REVIEW_ROLES, lanes)


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


def _assemble_report(merged: str, reviews: list[tuple[str, str, str]], meta: dict,
                     heading: str = "Code review (multi-model)") -> str:
    lines = [f"# {heading}", ""]
    flags = []
    if meta.get("truncated"):
        flags.append("diff truncated")
    flags.append("read-only")
    lines.append(f"_Base: `{meta['base']}` · reviewers: {meta['reviewers']} · "
                 f"{' · '.join(flags)}_\n")
    recap_rows = [(f"{role} ({lane})", True, 0, text) for role, lane, text in reviews]
    recap_rows += [(f, False, 0, "failed") for f in meta.get("roles_failed", [])]
    lines.append(council_recap(recap_rows, title="Reviewers"))
    lines.append("")
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


# ── security_review: OWASP-aware, security-only roles (deeper than review_diff's one lens) ──
SECURITY_ROLES: list[tuple[str, str]] = [
    ("injection",
     "SQL/NoSQL/command/template injection, XSS, and any place untrusted input reaches an "
     "interpreter, query, or shell without parameterization/escaping."),
    ("auth & access control",
     "Broken authentication, missing/incorrect authorization checks, IDOR, privilege "
     "escalation, session/token handling, and insecure defaults."),
    ("secrets & crypto",
     "Hardcoded secrets/keys, weak or misused crypto, predictable randomness, secrets in "
     "logs, and insecure storage/transport."),
    ("data exposure & SSRF",
     "Path traversal, SSRF, unsafe deserialization, sensitive data leaks, and unvalidated "
     "redirects/file access."),
]


def security_prompt(role: str, desc: str, diff: str, truncated: bool) -> str:
    trunc = ("\n\n[NOTE: diff truncated to fit context — review only what is shown above]"
             if truncated else "")
    return (
        f"You are an application security reviewer (OWASP-aware). Focus ONLY on **{role}**: "
        f"{desc}\n\nReport each vulnerability with: severity (critical/high/medium/low), the "
        "file:line if visible, the attack/impact, and a concrete remediation. Flag only real "
        f"security issues in your area — if none, reply exactly 'No {role} issues found.' "
        "Do not restate the diff.\n\n"
        f"```diff\n{diff}{trunc}\n```")


def security_merge_prompt(reviews: list[tuple[str, str, str]]) -> str:
    body = "\n\n".join(f"### {role} reviewer ({lane})\n{text}" for role, lane, text in reviews)
    return (
        "Merge these security findings into ONE deduplicated report, OWASP-style. Group by "
        "severity (critical first). Dedupe (same issue from several reviewers = one entry, note "
        "the agreement). For each: severity, location, attack/impact, remediation. End with a "
        f"one-line overall security verdict (ship / fix-first / block). No padding.\n\n{body}")


async def _diff_review(targets, args, run_lane, *, roles_def, prompt_fn, merge_fn, heading,
                       tool) -> str:
    """Shared engine for review_diff / security_review: fetch a diff, fan role-diverse reviewers
    across lanes in parallel, then merge+dedupe into one report. `run_lane` is injected so this
    is testable without a real CLI."""
    cwd = (args.get("cwd") or "").strip()
    base = (args.get("base") or "").strip() or "HEAD"
    diff = args.get("diff") or ""
    if not diff:
        diff, err = git_diff(cwd, base)
        if err:
            return f"[error] {err}"
    if not diff.strip():
        return (f"[{tool}] empty diff (base={base}). Nothing to review. "
                "Make changes first, or pass a different `base` / a `diff` directly.")
    if not targets:
        return ("[error] no lanes available for review. Install/login a CLI, or set "
                "include_paid=true / CLI_BRIDGE_PROFILE=max to allow limited/paid lanes.")

    truncated = len(diff) > config.REVIEW_DIFF_MAX_CHARS
    diff_in = diff[:config.REVIEW_DIFF_MAX_CHARS] if truncated else diff
    timeout = _timeout(args.get("timeout_s"))
    roles = _assign(roles_def, targets)

    async def _review(role: str, desc: str, lane: LaneSpec):
        sub = {"task": prompt_fn(role, desc, diff_in, truncated),
               "cwd": cwd, "timeout_s": timeout}
        res = await run_lane(lane, sub, tool=tool, terse=False)
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
        merged = await run_lane(judge, {"task": merge_fn(reviews), "timeout_s": timeout},
                                tool=tool, terse=False)
        merged_text = merged.output if merged.ok else ""
        meta["merge_lane"] = judge.display if merged.ok else f"FAILED ({merged.kind})"
    else:
        merged_text = reviews[0][2]
        meta["merge_lane"] = "n/a (single reviewer)"

    return _assemble_report(merged_text, reviews, meta, heading=heading)


async def review_diff(targets: list[LaneSpec], args: dict, run_lane) -> str:
    """Multi-model code review of a git diff (correctness/security/tests/maintainability)."""
    return await _diff_review(targets, args, run_lane, roles_def=REVIEW_ROLES,
                              prompt_fn=review_prompt, merge_fn=merge_prompt,
                              heading="Code review (multi-model)", tool="review_diff")


async def security_review(targets: list[LaneSpec], args: dict, run_lane) -> str:
    """OWASP-aware security review of a git diff — security-only role-diverse reviewers."""
    return await _diff_review(targets, args, run_lane, roles_def=SECURITY_ROLES,
                              prompt_fn=security_prompt, merge_fn=security_merge_prompt,
                              heading="Security review (OWASP-aware)", tool="security_review")


# ── debate: lanes answer, see each other, revise over bounded rounds, a judge concludes ──
DEBATE_DEFAULT_ROUNDS = 1
DEBATE_MAX_ROUNDS = 3
DEBATE_MAX_DEBATERS = 4   # bound the call count: debaters × (1 + rounds) + 1 judge


def debate_open_prompt(question: str) -> str:
    return f"Answer this question and argue your reasoning concisely:\n\n{question}"


def debate_revise_prompt(question: str, transcript: str) -> str:
    return (
        "Several AIs answered the same question. Read all answers below, then give your "
        "REVISED answer: keep what holds up, correct what others rightly challenged, and state "
        "where you still disagree and why. Be concise.\n\n"
        f"QUESTION:\n{question}\n\nALL ANSWERS SO FAR:\n{transcript}")


def debate_judge_prompt(question: str, transcript: str) -> str:
    return (
        "Several AIs debated the question below. Produce the best FINAL answer: state the "
        "consensus, flag any remaining disagreement (name who held what), and give the most "
        f"reliable conclusion. Be precise.\n\nQUESTION:\n{question}\n\nDEBATE:\n{transcript}")


def _debate_transcript(positions: list[tuple[str, str]]) -> str:
    return "\n\n".join(f"### {display}\n{text}" for display, text in positions)


async def debate(targets: list[LaneSpec], args: dict, run_lane) -> str:
    """Multi-lane debate: each lane answers, then sees the others and revises over a bounded
    number of rounds, then a judge writes the final conclusion. `run_lane` injected for tests."""
    question = (args.get("task") or args.get("question") or "").strip()
    if not question:
        return "[error] task (the debate question) is required"
    if not targets:
        return ("[error] no lanes available to debate. Install/login a CLI, or set "
                "include_paid=true / CLI_BRIDGE_PROFILE=max to allow limited/paid lanes.")
    try:
        rounds = max(0, min(int(args.get("rounds")), DEBATE_MAX_ROUNDS))
    except (TypeError, ValueError):
        rounds = DEBATE_DEFAULT_ROUNDS
    timeout = _timeout(args.get("timeout_s"))
    debaters = targets[:DEBATE_MAX_DEBATERS]

    async def _ask(lane: LaneSpec, prompt: str):
        res = await run_lane(lane, {"task": prompt, "timeout_s": timeout}, tool="debate")
        return lane, res

    # Round 0: independent answers.
    raw = await asyncio.gather(*[_ask(l, debate_open_prompt(question)) for l in debaters],
                               return_exceptions=True)
    positions: dict[str, tuple[str, str]] = {}   # lane.key -> (display, latest answer)
    for item in raw:
        if isinstance(item, BaseException):
            continue
        lane, res = item
        if res.ok:
            positions[lane.key] = (lane.display, res.output)
    if not positions:
        return "[error] no lane produced an opening answer. Check `doctor`."

    # Revision rounds: each lane sees the full transcript and revises.
    rounds_run = 0
    for _ in range(rounds):
        if len(positions) < 2:
            break                         # nothing to debate against
        transcript = _debate_transcript(list(positions.values()))
        live = [l for l in debaters if l.key in positions]
        raw = await asyncio.gather(
            *[_ask(l, debate_revise_prompt(question, transcript)) for l in live],
            return_exceptions=True)
        for item in raw:
            if isinstance(item, BaseException):
                continue
            lane, res = item
            if res.ok:
                positions[lane.key] = (lane.display, res.output)
        rounds_run += 1

    final_positions = list(positions.values())
    transcript = _debate_transcript(final_positions)
    meta = {
        "question": question[:200],
        "debaters": [d for d, _ in final_positions],
        "rounds": rounds_run,
    }
    # Judge: prefer a free non-experimental lane; fall back to the first debater.
    judge = next((l for l in targets
                  if not l.is_paid and not l.is_limited and not l.experimental), debaters[0])
    if len(final_positions) >= 2:
        jr = await run_lane(judge, {"task": debate_judge_prompt(question, transcript),
                                    "timeout_s": timeout}, tool="debate")
        final = jr.output if jr.ok else transcript
        meta["judge"] = judge.display if jr.ok else f"FAILED ({jr.kind}) — showing raw positions"
    else:
        final = final_positions[0][1]
        meta["judge"] = "n/a (single debater)"

    lines = ["# Debate", ""]
    lines.append(f"_Debaters: {', '.join(meta['debaters'])} · rounds: {rounds_run} · "
                 f"judge: {meta['judge']}_\n")
    lines.append(council_recap([(d, True, 0, t) for d, t in final_positions],
                               title="Final positions"))
    lines.append("")
    lines.append("## Final answer\n")
    lines.append(final.strip() or "_(judge produced no output)_")
    lines.append("\n## Final positions\n")
    for display, text in final_positions:
        lines.append(f"<details><summary>{display}</summary>\n\n{text.strip()}\n\n</details>")
    lines.append("\n## Trace\n```json\n" + json.dumps(meta, indent=2) + "\n```")
    return "\n".join(lines)
