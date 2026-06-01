"""Multi-model workflow tools built on the lane council.

`review_diff` is the first: a git diff is reviewed by several lanes wearing DIFFERENT hats
(correctness / security / tests / maintainability), each returning a JSON array of findings,
which are then merged DETERMINISTICALLY by file/line/title (see findings.py) — no second LLM
merge pass, so it's cheaper, reproducible, and can't fabricate findings. Diverse roles beat N
identical reviewers — each lens catches issues the others miss. Deterministic prechecks
(secrets, dangerous shell) run first as a model-independent safety net.

Decoupled from server.py on purpose: the orchestration takes a `run_lane` coroutine and an
already-filtered list of target lanes, so it can be unit-tested with fakes (no real CLI, no
network) and the cost/cooldown policy stays in one place (server._ask_all_targets).

Reviewers run with terse=False — they must emit clean JSON, not a compressed prose answer.
"""
from __future__ import annotations

import asyncio
import json
import re
import subprocess

from . import config, findings, runner
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


_JSON_RULES = (
    "Return ONLY a JSON array of findings — no prose, no markdown fences. Each finding is an "
    'object: {"severity": "blocker|high|medium|low", "title": "<short label>", "file": '
    '"<path>" or null, "line": <int> or null, "evidence": "<what and why it is a problem>", '
    '"recommendation": "<concrete fix>"}. Use null for file/line when the exact location is '
    "not visible in the diff. If there are no genuine issues, return []."
)


def review_prompt(role: str, desc: str, diff: str, truncated: bool) -> str:
    trunc = ("\n\n[NOTE: diff truncated to fit context — review only what is shown above]"
             if truncated else "")
    return (
        f"You are a senior code reviewer. Review ONLY the **{role}** dimension: {desc}\n\n"
        f"{_JSON_RULES} Report only real {role} issues; do not restate the diff or review "
        f"other dimensions.\n\n```diff\n{diff}{trunc}\n```")


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
        f"{desc}\n\n{_JSON_RULES} (Put the attack/impact in 'evidence' and the remediation in "
        f"'recommendation'.) Flag only real security issues in your area; do not restate the "
        f"diff.\n\n```diff\n{diff}{trunc}\n```")


# ── deterministic prechecks: a model-independent safety net run BEFORE the LLM reviewers ──
# Each match becomes a finding from the synthetic STATIC_SOURCE; if a model also flags it,
# the merge raises its confidence. Line numbers are left null (honest — we track only the file).
_DANGEROUS = [
    (re.compile(r"\brm\s+-rf\b"), "high", "Destructive `rm -rf`",
     "Verify the path can't be empty or attacker-controlled before forcing a recursive delete."),
    (re.compile(r"\|\s*(?:sudo\s+)?(?:ba)?sh\b"), "high", "Piping a download into a shell",
     "`curl … | sh` runs unverified remote code; download, verify, then run."),
    (re.compile(r"\beval\s*\("), "high", "Use of eval()",
     "eval on untrusted input is arbitrary code execution; parse explicitly instead."),
    (re.compile(r"\bos\.system\s*\("), "high", "os.system() shell-out",
     "Shells out without arg isolation; use subprocess with an argv list and shell=False."),
    (re.compile(r"shell\s*=\s*True"), "medium", "subprocess with shell=True",
     "shell=True invites command injection; pass an argv list with shell=False."),
    (re.compile(r"\b(?:c?pickle)\.loads?\b"), "high", "Unsafe deserialization (pickle)",
     "pickle executes arbitrary code on load; use a safe format for untrusted data."),
    (re.compile(r"\byaml\.load\s*\((?![^)]*Loader)"), "medium", "yaml.load without SafeLoader",
     "Use yaml.safe_load to avoid arbitrary object construction from untrusted YAML."),
]


def prechecks(diff: str) -> list[findings.Finding]:
    """Scan ADDED diff lines for secrets (reusing runner's redaction patterns) and dangerous
    constructs. Pure + deterministic — catches issues even if every LLM reviewer misses them."""
    out: list[findings.Finding] = []
    current: str | None = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[4:].strip()
            current = (path[2:] if path.startswith("b/") else path) or None
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue
        added = line[1:]
        for pattern, _repl in runner._REDACTIONS:
            if pattern.search(added):
                out.append(findings.Finding(
                    severity="high", title="Possible secret committed in diff", file=current,
                    evidence=runner.redact(added.strip())[:120],
                    recommendation="Remove the secret, rotate it, and load it from an env var "
                                   "or secret store.",
                    models=[findings.STATIC_SOURCE], roles=["precheck"]))
                break
        for pattern, sev, title, rec in _DANGEROUS:
            if pattern.search(added):
                out.append(findings.Finding(
                    severity=sev, title=title, file=current,
                    evidence=f"`{added.strip()[:120]}`", recommendation=rec,
                    models=[findings.STATIC_SOURCE], roles=["precheck"]))
    return out


def _residual_risk(meta: dict) -> str:
    bits = ["this is a static review of the shown diff only — no runtime, dependency, or "
            "deployment/secrets-config analysis was performed"]
    if meta.get("truncated"):
        bits.insert(0, "the diff was truncated, so code past the cutoff was NOT reviewed")
    if meta.get("roles_failed"):
        bits.insert(0, f"reviewer role(s) failed ({', '.join(meta['roles_failed'])}); their "
                       "categories are unassessed")
    return "Treat with care — " + "; ".join(bits) + "."


async def _diff_review(targets, args, run_lane, *, roles_def, prompt_fn, heading, tool,
                       residual: bool = False) -> str:
    """Shared engine for review_diff / security_review: fetch a diff, run deterministic
    prechecks, fan role-diverse reviewers across lanes in parallel (each returns JSON), then
    merge findings deterministically by file/line/title. `run_lane` is injected for tests.

    output_format=json returns the structured result; default 'markdown' renders a PR-friendly
    report. No second LLM merge pass — the merge is pure code (cheaper, reproducible, and it
    can't fabricate findings)."""
    cwd = (args.get("cwd") or "").strip()
    base = (args.get("base") or "").strip() or "HEAD"
    output_format = (args.get("output_format") or "markdown").strip().lower()
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
    all_findings: list[findings.Finding] = list(prechecks(diff_in))
    recap_rows: list[tuple[str, bool, int, str]] = []
    reviewer_displays: set[str] = set()
    reviewers: list[str] = []
    failures: list[str] = []
    for item in raw:
        if isinstance(item, BaseException):
            failures.append(f"crash:{item}")
            recap_rows.append(("crashed reviewer", False, 0, str(item)))
            continue
        role, lane, res = item
        if res.ok:
            fs, parsed_ok = findings.parse_findings(res.output, role=role, lane=lane.display)
            all_findings.extend(fs)
            reviewer_displays.add(lane.display)
            reviewers.append(f"{role} ({lane.display})")
            note = "" if parsed_ok else " [unparsed → wrapped]"
            recap_rows.append((f"{role} ({lane.display})", True, res.latency_ms,
                               f"{len(fs)} finding(s){note}"))
        else:
            failures.append(f"{role}={res.kind}")
            recap_rows.append((f"{role} ({lane.display})", False, res.latency_ms, res.kind))

    if not reviewer_displays and not [f for f in all_findings if f.roles == ["precheck"]]:
        return "[error] all reviewers failed: " + ", ".join(failures) + ". Check `doctor`."

    merged = findings.merge_findings(all_findings)
    total_reviewers = len(reviewer_displays)
    meta = {
        "base": base,
        "reviewers": reviewers,
        "roles_failed": failures,
        "truncated": truncated,
        "diff_chars": len(diff),
        "prechecks": sum(1 for f in all_findings if "precheck" in f.roles),
    }
    residual_risk = _residual_risk(meta) if residual else ""

    if output_format == "json":
        summary = f"{len(merged)} finding(s); {findings.verdict(merged)}"
        return json.dumps(findings.result_json(
            merged, total_reviewers=total_reviewers, tool=tool, summary=summary,
            meta=meta, residual_risk=residual_risk), indent=2)

    recap = council_recap(recap_rows, title="Reviewers")
    return findings.render_markdown(merged, total_reviewers=total_reviewers, heading=heading,
                                    meta=meta, recap=recap, residual_risk=residual_risk)


async def review_diff(targets: list[LaneSpec], args: dict, run_lane) -> str:
    """Multi-model code review of a git diff (correctness/security/tests/maintainability)."""
    return await _diff_review(targets, args, run_lane, roles_def=REVIEW_ROLES,
                              prompt_fn=review_prompt,
                              heading="Code review (multi-model)", tool="review_diff")


async def security_review(targets: list[LaneSpec], args: dict, run_lane) -> str:
    """OWASP-aware security review of a git diff — security-only role-diverse reviewers."""
    return await _diff_review(targets, args, run_lane, roles_def=SECURITY_ROLES,
                              prompt_fn=security_prompt,
                              heading="Security review (OWASP-aware)", tool="security_review",
                              residual=True)


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


# ── premortem / test_plan: fan a specialized question across lanes, then merge ──────────────

async def _council_synth(targets, run_lane, *, ask: str, merge, heading: str, tool: str,
                         timeout: int) -> str:
    """Ask every target the same specialized prompt, recap who said what, then have one lane
    merge the answers into a single prioritized result. terse=False (structured prose)."""
    if not targets:
        return ("[error] no lanes available. Install/login a CLI, or set include_paid=true / "
                "CLI_BRIDGE_PROFILE=max to allow limited/paid lanes.")

    async def _ask(lane: LaneSpec):
        res = await run_lane(lane, {"task": ask, "timeout_s": timeout}, tool=tool, terse=False)
        return lane, res

    raw = await asyncio.gather(*[_ask(l) for l in targets], return_exceptions=True)
    answers: list[tuple[str, str]] = []
    rows: list[tuple[str, bool, int, str]] = []
    for item in raw:
        if isinstance(item, BaseException):
            rows.append(("crashed", False, 0, str(item)))
            continue
        lane, res = item
        if res.ok:
            answers.append((lane.display, res.output))
            rows.append((lane.display, True, res.latency_ms, res.output))
        else:
            rows.append((lane.display, False, res.latency_ms, res.kind))
    if not answers:
        return f"[error] all lanes failed for {tool}. Check `doctor`."

    if len(answers) >= 2:
        transcript = "\n\n".join(f"### {d}\n{t}" for d, t in answers)
        jr = await run_lane(targets[0], {"task": merge(transcript), "timeout_s": timeout},
                            tool=tool, terse=False)
        merged = jr.output if jr.ok else answers[0][1]
    else:
        merged = answers[0][1]

    lines = [f"# {heading}", "", council_recap(rows, title="Council"), "", "## Merged\n",
             merged.strip() or "_(merge produced no output)_"]
    if len(answers) > 1:
        lines.append("\n## Per-model detail\n")
        for d, t in answers:
            lines.append(f"<details><summary>{d}</summary>\n\n{t.strip()}\n\n</details>")
    return "\n".join(lines)


def _premortem_ask(subject: str) -> str:
    return (
        "Run a PREMORTEM. Assume the change/plan below has FAILED badly some months from now. "
        "Working backwards, give the most LIKELY failure modes, each with: its root cause, an "
        "early warning sign, and a concrete mitigation. Prioritize by likelihood × impact; be "
        f"specific to THIS change, not generic.\n\nCHANGE / PLAN:\n{subject}")


def _premortem_merge(transcript: str) -> str:
    return ("Several models ran a premortem on the same change. Merge into ONE prioritized risk "
            "list (highest likelihood × impact first), deduped; when several flag the same risk, "
            "keep one entry and note the agreement. Each: risk, root cause, early sign, "
            f"mitigation. End with the single biggest thing to de-risk first.\n\n{transcript}")


def _test_plan_ask(subject: str, is_diff: bool) -> str:
    what = "git diff" if is_diff else "description"
    return (
        f"Produce a TEST PLAN for the change below (given as a {what}). List the behaviors and "
        "edge cases that must be tested, the failure modes a test should catch, and the minimal "
        "set of concrete test cases (unit / integration) to add — each mapped to the code area "
        "it covers. Prefer the smallest suite that would catch a regression; don't pad.\n\n"
        f"{subject}")


def _test_plan_merge(transcript: str) -> str:
    return ("Several models proposed a test plan for the same change. Merge into ONE deduped, "
            "prioritized plan: the must-have cases first, then nice-to-have. Group by code area; "
            f"note where models agreed a case is essential.\n\n{transcript}")


async def premortem(targets: list[LaneSpec], args: dict, run_lane) -> str:
    """Multi-model premortem: each lane lists how the plan could fail; one merges into a
    prioritized risk list."""
    subject = (args.get("task") or "").strip()
    if not subject:
        return "[error] task (the change/plan to premortem) is required"
    return await _council_synth(targets, run_lane, ask=_premortem_ask(subject),
                                merge=_premortem_merge, heading="Premortem (multi-model)",
                                tool="premortem", timeout=_timeout(args.get("timeout_s")))


async def test_plan(targets: list[LaneSpec], args: dict, run_lane) -> str:
    """Multi-model test plan from a git diff (default: working-tree changes) or a description."""
    task = (args.get("task") or "").strip()
    diff = args.get("diff") or ""
    is_diff = False
    if task and not diff:
        subject = task
    else:
        cwd = (args.get("cwd") or "").strip()
        base = (args.get("base") or "").strip() or "HEAD"
        if not diff:
            diff, err = git_diff(cwd, base)
            if err:
                return f"[error] {err}"
        if not diff.strip():
            return ("[test_plan] empty diff and no task. Pass `task` (a description), or make "
                    "changes / pass a `diff`/`base`.")
        truncated = len(diff) > config.REVIEW_DIFF_MAX_CHARS
        subject = (diff[:config.REVIEW_DIFF_MAX_CHARS] if truncated else diff)
        if truncated:
            subject += "\n\n[diff truncated to fit context]"
        subject = f"```diff\n{subject}\n```"
        is_diff = True
    return await _council_synth(targets, run_lane, ask=_test_plan_ask(subject, is_diff),
                                merge=_test_plan_merge, heading="Test plan (multi-model)",
                                tool="test_plan", timeout=_timeout(args.get("timeout_s")))
