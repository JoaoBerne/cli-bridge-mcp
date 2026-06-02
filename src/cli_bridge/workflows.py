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

    raw = await asyncio.gather(*[_review(r, d, ln) for r, d, ln in roles],
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
    sev_floor = (args.get("severity_filter") or "").strip().lower()
    filtered_out = 0
    if sev_floor in findings.SEVERITIES:
        before = len(merged)
        merged = findings.filter_by_severity(merged, sev_floor)
        filtered_out = before - len(merged)
    meta = {
        "base": base,
        "reviewers": reviewers,
        "roles_failed": failures,
        "truncated": truncated,
        "diff_chars": len(diff),
        "prechecks": sum(1 for f in all_findings if "precheck" in f.roles),
        "severity_filter": sev_floor or None,
        "filtered_out": filtered_out,
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


_STANCES = {
    "for": "Take the FOR position: argue in favour and surface the genuine strengths and best "
           "case. But do not defend the indefensible — if it is fundamentally flawed, say so.",
    "against": "Take the AGAINST position: argue critically and surface the real weaknesses and "
               "failure modes. But acknowledge genuine strengths — do not manufacture objections.",
    "neutral": "Take a NEUTRAL position: weigh both sides objectively, by actual impact.",
}


def _stance_preamble(stance: str) -> str:
    return _STANCES.get(stance, _STANCES["neutral"])


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


async def debate(targets: list[LaneSpec], args: dict, run_lane, progress=None) -> str:
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
    adversarial = bool(args.get("adversarial"))
    _stance_cycle = ("for", "against", "neutral")

    async def _ask(lane: LaneSpec, prompt: str):
        res = await run_lane(lane, {"task": prompt, "timeout_s": timeout}, tool="debate")
        return lane, res

    def _open(i: int) -> str:
        if adversarial:
            return (f"{_stance_preamble(_stance_cycle[i % len(_stance_cycle)])}\n\n"
                    f"{debate_open_prompt(question)}")
        return debate_open_prompt(question)

    # Round 0: independent answers (optionally with assigned for/against/neutral stances).
    raw = await asyncio.gather(*[_ask(ln, _open(i)) for i, ln in enumerate(debaters)],
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
    if progress:
        await progress(1, 2, "opening")

    # Revision rounds: each lane sees the full transcript and revises.
    rounds_run = 0
    for _ in range(rounds):
        if len(positions) < 2:
            break                         # nothing to debate against
        transcript = _debate_transcript(list(positions.values()))
        live = [ln for ln in debaters if ln.key in positions]
        raw = await asyncio.gather(
            *[_ask(ln, debate_revise_prompt(question, transcript)) for ln in live],
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
        "adversarial": adversarial,
    }
    # Judge: prefer a free non-experimental lane; fall back to the first debater.
    judge = next((ln for ln in targets
                  if not ln.is_paid and not ln.is_limited and not ln.experimental), debaters[0])
    if len(final_positions) >= 2:
        jr = await run_lane(judge, {"task": debate_judge_prompt(question, transcript),
                                    "timeout_s": timeout}, tool="debate")
        final = jr.output if jr.ok else transcript
        meta["judge"] = judge.display if jr.ok else f"FAILED ({jr.kind}) — showing raw positions"
    else:
        final = final_positions[0][1]
        meta["judge"] = "n/a (single debater)"
    if progress:
        await progress(2, 2, "final")

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


# ── challenge: an independent skeptic to counter reflexive agreement ──────────────────────────

def challenge_prompt(claim: str) -> str:
    return (
        "CRITICAL REASSESSMENT — do not reflexively agree. Evaluate the statement below strictly "
        "on its merits: is it accurate, complete, and well-reasoned? Investigate if needed. If "
        "you find flaws, gaps, hidden assumptions, or counter-evidence, state them plainly with "
        "your reasoning. If it genuinely holds up, say why — do NOT manufacture disagreement. Be "
        f"concise and specific.\n\nSTATEMENT:\n{claim}")


async def challenge(targets: list[LaneSpec], args: dict, run_lane) -> str:
    """Hand a claim to ONE outside lane with an anti-sycophancy prompt and return its skeptical
    review — an outside view to pressure-test the host's own conclusion. `run_lane` injected for
    tests. The 'against' stance carries an integrity guardrail (don't manufacture disagreement)."""
    claim = (args.get("task") or args.get("claim") or "").strip()
    if not claim:
        return "[error] task (the claim to challenge) is required"
    if not targets:
        return ("[error] no lane available to challenge. Install/login a CLI, name a `lane`, or "
                "widen with include_paid=true / CLI_BRIDGE_PROFILE=max.")
    timeout = _timeout(args.get("timeout_s"))
    lane = targets[0]
    res = await run_lane(lane, {"task": challenge_prompt(claim), "timeout_s": timeout},
                         tool="challenge")
    if not res.ok:
        return f"[challenge via {lane.display} FAILED ({res.kind})]\n{res.output}".strip()
    return (f"# Challenge — skeptic: {lane.display}\n\n"
            f"_Claim:_ {one_phrase(claim, 200)}\n\n{res.output.strip()}")


# ── consensus: anonymized peer-ranking + chairman synthesis ───────────────────────────────
# Karpathy's "LLM council", done better: answers are RANKED ANONYMOUSLY (so a model can't favour
# its own), the ranking is aggregated DETERMINISTICALLY (Borda count — not an LLM's vibe), and
# the whole thing is cost-bounded and ban-safe (official CLIs, no keys).

CONSENSUS_MAX_LANES = 5
_LABELS = "ABCDEFGH"


def consensus_answer_prompt(question: str) -> str:
    return f"Answer the question as well as you can — concise, concrete, self-contained:\n\n{question}"


def consensus_rank_prompt(question: str, labeled: list[tuple[str, str]]) -> str:
    block = "\n\n".join(f"--- Answer {lab} ---\n{txt}" for lab, txt in labeled)
    labels = ", ".join(lab for lab, _ in labeled)
    return (
        "Below are ANONYMOUS answers to the same question — you do NOT know which model wrote "
        "which, so judge only on merit (correctness, completeness, usefulness). Rank them best "
        "to worst.\n\nReply with EXACTLY one line, then nothing else:\n"
        f"RANKING: <labels best-to-worst, comma-separated, using only {labels}>\n\n"
        f"QUESTION:\n{question}\n\nANSWERS:\n{block}")


def consensus_synth_prompt(question: str, winner_text: str, labeled: list[tuple[str, str]]) -> str:
    alla = "\n\n".join(f"--- {lab} ---\n{txt}" for lab, txt in labeled)
    return (
        "You are the chairman of a model council. Using the top-ranked answer as the base, write "
        "the best FINAL answer: keep what is strongest, fold in any better points from the "
        "others, and flag any important disagreement. Be precise and concise.\n\n"
        f"QUESTION:\n{question}\n\nTOP-RANKED ANSWER:\n{winner_text}\n\nALL ANSWERS:\n{alla}")


def _parse_ranking(text: str, valid: set[str]) -> list[str]:
    """Pull the 'RANKING: B, A, C' line into an ordered list of known labels. Line-scoped and
    token-based: splits on separators and keeps tokens that are EXACTLY a valid label, so junk
    or a stray prose word can't pollute or truncate the ranking (dedup, order preserved)."""
    m = re.search(r"RANKING:\s*([^\n]+)", text or "", re.I)
    if not m:
        return []
    order, seen = [], set()
    for tok in re.split(r"[,\s>]+", m.group(1).strip()):
        u = tok.upper()
        if u in valid and u not in seen:
            seen.add(u)
            order.append(u)
    return order


def aggregate_rankings(rankings: list[list[str]], labels: list[str]) -> dict:
    """Borda count over (possibly partial) rankings. A label at position i of a k-long ranking
    scores (k - i). Winner = most points; ties broken by first-place votes, then label order."""
    points = {lab: 0 for lab in labels}
    firsts = {lab: 0 for lab in labels}
    for r in rankings:
        k = len(r)
        for i, lab in enumerate(r):
            points[lab] += k - i
            if i == 0:
                firsts[lab] += 1
    order = sorted(labels, key=lambda lab: (-points[lab], -firsts[lab], labels.index(lab)))
    return {"points": points, "firsts": firsts, "order": order}


async def consensus(targets: list[LaneSpec], args: dict, run_lane, progress=None) -> str:
    """Poll the panel for blind answers, have each lane rank the ANONYMIZED set, aggregate the
    rankings deterministically (Borda), then a chairman synthesizes the winner. `run_lane`
    injected for tests."""
    question = (args.get("task") or args.get("question") or "").strip()
    if not question:
        return "[error] task (the question) is required"
    if not targets:
        return ("[error] no lanes available for consensus. Install/login a CLI, or set "
                "include_paid=true / CLI_BRIDGE_PROFILE=max to allow limited/paid lanes.")
    timeout = _timeout(args.get("timeout_s"))
    panel = targets[:CONSENSUS_MAX_LANES]

    async def _ask(lane: LaneSpec, prompt: str):
        res = await run_lane(lane, {"task": prompt, "timeout_s": timeout}, tool="consensus")
        return lane, res

    # 1. Blind independent answers.
    raw = await asyncio.gather(*[_ask(ln, consensus_answer_prompt(question)) for ln in panel],
                               return_exceptions=True)
    answers: list[tuple[LaneSpec, str]] = []
    for item in raw:
        if isinstance(item, BaseException):
            continue
        lane, res = item
        if res.ok and res.output.strip():
            answers.append((lane, res.output.strip()))
    if not answers:
        return "[error] no lane produced an answer. Check `doctor`."
    if len(answers) == 1:
        lane, txt = answers[0]
        return f"# Consensus\n\n_Only {lane.display} answered — no panel to rank._\n\n{txt}"

    labeled = [(_LABELS[i], txt) for i, (_, txt) in enumerate(answers)]
    label_to_lane = {_LABELS[i]: lane for i, (lane, _) in enumerate(answers)}
    text_by_label = dict(labeled)
    labels = [lab for lab, _ in labeled]
    valid = set(labels)
    if progress:
        await progress(1, 3, "answers")

    # 2. Each lane ranks the anonymized set.
    rraw = await asyncio.gather(*[_ask(ln, consensus_rank_prompt(question, labeled))
                                  for ln, _ in answers], return_exceptions=True)
    rankings: list[list[str]] = []
    for item in rraw:
        if isinstance(item, BaseException):
            continue
        _lane, res = item
        if res.ok:
            order = _parse_ranking(res.output, valid)
            if order:
                rankings.append(order)
    agg = aggregate_rankings(rankings, labels) if rankings else None
    if progress:
        await progress(2, 3, "rankings")

    # 3. Chairman synthesis (free non-experimental lane, else the first answerer).
    if agg:
        win_label = agg["order"][0]
        winner_text = text_by_label[win_label]
    else:
        winner_text = answers[0][1]
    chair = next((ln for ln in targets
                  if not ln.is_paid and not ln.is_limited and not ln.experimental), answers[0][0])
    cr = await run_lane(chair, {"task": consensus_synth_prompt(question, winner_text, labeled),
                                "timeout_s": timeout}, tool="consensus")
    final = cr.output.strip() if cr.ok else winner_text
    if progress:
        await progress(3, 3, "synthesis")

    lines = ["# Consensus", ""]
    lines.append(f"_Panel: {', '.join(ln.display for ln, _ in answers)} · rankings: "
                 f"{len(rankings)} · chairman: {chair.display}_\n")
    lines.append("## Final answer\n")
    lines.append(final or "_(chairman produced no output)_")
    if agg:
        lines.append("\n## Consensus ranking (anonymized peer vote, Borda)\n")
        lines.append("| rank | answer | model | score | 1st-place |")
        lines.append("|---|---|---|---|---|")
        for pos, lab in enumerate(agg["order"], 1):
            lines.append(f"| {pos} | {lab} | {label_to_lane[lab].display} | "
                         f"{agg['points'][lab]} | {agg['firsts'][lab]} |")
        win = agg["order"][0]
        lines.append(f"\n_Agreement: {agg['firsts'][win]}/{len(rankings)} rankers ranked the "
                     "winner first._")
    else:
        lines.append("\n_No parseable rankings — showing answers without a peer vote._")
    lines.append("\n## All answers\n")
    for lab, txt in labeled:
        lines.append(f"<details><summary>{lab} — {label_to_lane[lab].display}</summary>\n\n"
                     f"{txt}\n\n</details>")
    return "\n".join(lines)


# ── commit message / PR description from the live git state (read-only — emits text, never commits) ──

def _git(cwd: str, args: list[str]) -> tuple[str, str]:
    """Run a read-only git command; return (stdout, error). Empty error == success."""
    try:
        proc = subprocess.run(["git", "-C", cwd or ".", *args],
                              capture_output=True, text=True, errors="replace",
                              timeout=_GIT_DIFF_TIMEOUT_S, check=False)
    except FileNotFoundError:
        return "", "git is not installed / not on PATH."
    except (OSError, subprocess.TimeoutExpired) as e:
        return "", f"git failed: {e}"
    if proc.returncode != 0:
        return "", f"git {' '.join(args)} exited {proc.returncode}: {proc.stderr.strip()[:300]}"
    return proc.stdout, ""


def commit_msg_prompt(diff: str, truncated: bool) -> str:
    trunc = "\n\n[diff truncated to fit context]" if truncated else ""
    return (
        "Write ONE Conventional Commit message for the changes below. Format: a subject line "
        "`type(scope): summary` (type in feat/fix/docs/refactor/test/chore/perf/build/ci; scope "
        "optional; imperative mood; <=72 chars), a blank line, then a concise body explaining "
        "WHAT changed and WHY (wrap ~72 cols, bullets ok). Output ONLY the commit message — no "
        f"code fences, no preamble.\n\n```diff\n{diff}{trunc}\n```")


async def commit_msg(targets: list[LaneSpec], args: dict, run_lane) -> str:
    """Conventional-commit message from the STAGED diff (falls back to the working tree if
    nothing is staged). Read-only: never commits — returns text to use. `run_lane` injected."""
    cwd = (args.get("cwd") or "").strip()
    diff, err = _git(cwd, ["diff", "--staged"])
    scope = "staged"
    if not err and not diff.strip():
        diff, err = _git(cwd, ["diff"])
        scope = "working tree (nothing staged)"
    if err:
        return f"[error] {err}"
    if not diff.strip():
        return "[error] no changes to describe (working tree clean)."
    if not targets:
        return "[error] no lane available. Install/login a CLI or set CLI_BRIDGE_MOCK=1."
    truncated = len(diff) > config.REVIEW_DIFF_MAX_CHARS
    diff_in = diff[:config.REVIEW_DIFF_MAX_CHARS] if truncated else diff
    lane = targets[0]
    res = await run_lane(lane, {"task": commit_msg_prompt(diff_in, truncated),
                                "timeout_s": _timeout(args.get("timeout_s"))}, tool="commit_msg")
    if not res.ok:
        return f"[commit_msg via {lane.display} FAILED ({res.kind})] {res.output}".strip()
    return f"# Commit message ({scope} · via {lane.display})\n\n```\n{res.output.strip()}\n```"


def pr_describe_prompt(log: str, diff: str, truncated: bool) -> str:
    trunc = "\n\n[diff truncated to fit context]" if truncated else ""
    return (
        "Write a pull-request description for the changes below. Output: a one-line **Title** "
        "(imperative), then **## Summary** (what & why, 2-5 sentences), **## Changes** (bullets), "
        "**## Testing** (how to verify / what was tested). Be concrete, no fluff.\n\n"
        f"COMMITS:\n{log or '(none)'}\n\n```diff\n{diff}{trunc}\n```")


async def pr_describe(targets: list[LaneSpec], args: dict, run_lane) -> str:
    """PR title + description from the branch's diff and commit log vs a base (default
    origin/main, falling back to main). Read-only. `run_lane` injected for tests."""
    cwd = (args.get("cwd") or "").strip()
    base = (args.get("base") or "").strip() or "origin/main"
    rng = f"{base}...HEAD"
    diff, err = git_diff(cwd, rng)
    if err and base == "origin/main":
        rng = "main...HEAD"
        diff, err = git_diff(cwd, rng)
    if err:
        return f"[error] {err} (pass base= a ref that exists, e.g. base='develop')."
    if not diff.strip():
        return f"[error] no diff for {rng} — is the base right and the branch ahead?"
    if not targets:
        return "[error] no lane available. Install/login a CLI or set CLI_BRIDGE_MOCK=1."
    log, _ = _git(cwd, ["log", "--oneline", rng])
    truncated = len(diff) > config.REVIEW_DIFF_MAX_CHARS
    diff_in = diff[:config.REVIEW_DIFF_MAX_CHARS] if truncated else diff
    lane = targets[0]
    res = await run_lane(lane, {"task": pr_describe_prompt(log.strip(), diff_in, truncated),
                                "timeout_s": _timeout(args.get("timeout_s"))}, tool="pr_describe")
    if not res.ok:
        return f"[pr_describe via {lane.display} FAILED ({res.kind})] {res.output}".strip()
    return f"# PR description ({rng} · via {lane.display})\n\n{res.output.strip()}"


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

    raw = await asyncio.gather(*[_ask(ln) for ln in targets], return_exceptions=True)
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
