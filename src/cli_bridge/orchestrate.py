"""Durable fan-out + presets.

`batch_run` is the substrate: run N INDEPENDENT asks concurrently (capped), journaling each to
SQLite (key = hash(run_id, task)) so a `resume_id` replays the tasks that already FINISHED and
only runs the rest — surviving a server restart (the edge over Claude Code's in-session resume).
The host composes the LOGIC (loops, conditions) in its own reasoning; cli-bridge just executes
durably. We deliberately did NOT add a JSON composition DSL — it would be weaker than the host
orchestrating itself, for far more code (council + user signal: don't over-complex).

On top sit PRESETS — coroutines that fan out then post-process with a hardcoded step (a
judge or a grouping), NOT a DSL: map_review, research_verify, fanout_compare, converge, and
the flagship refine_plan ("let the council demolish my plan"). All are resumable and can run in background.

Token frugality (a standing rule): when a preset reviews an ARTIFACT (a plan, a file), it passes
the file PATH via the lane's cwd so each lane reads it itself — never recopy the content inline.

run_lane / lane resolution are injected so this is testable with a fake run_lane (no AI CLI).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import uuid
from dataclasses import asdict, dataclass

from . import config, findings, lanes

MAX_BATCH_TASKS = 64           # anti-runaway: the existing cost model governs spend; this caps count
VERIFY_MAX_ROUNDS = 6          # hard cap on converge review->revise rounds (cost guard)

# Distinct angles refine_plan distributes across lanes (more lanes than angles -> redundancy =
# cross-check; fewer -> one lane covers several). Each is a sharp, single-lens critique.
REFINE_ANGLES: list[tuple[str, str]] = [
    ("technical flaws & failure modes",
     "Find concrete technical flaws, bugs, race conditions, and failure modes."),
    ("gaps & under-specified",
     "Find gaps, missing cases, and parts that are under-specified or hand-waved."),
    ("over-engineering to cut",
     "Find over-engineering, needless abstraction, and scope to cut."),
    ("sequencing & dependencies",
     "Critique the ordering, dependencies, and what must ship before what."),
]


def _new_run_id() -> str:
    return "run_" + uuid.uuid4().hex[:12]


def _task_key(run_id: str, task: dict) -> str:
    blob = json.dumps(task, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(f"{run_id}\x00{blob}".encode()).hexdigest()[:16]


# Output tokens are unknown until a call returns; assume output ~= EST_OUTPUT_MULT × input for the
# conservative (max) credit estimate that the budget RESERVES against, so the cap errs toward
# blocking early rather than overspending.
EST_OUTPUT_MULT = 3


def _est_credits(lane, tokens: float, telemetry) -> float:
    """Estimated credits for `tokens` on `lane` via telemetry's per-lane CREDITS_PER_1K. 0.0 when
    the lane has no rate set (a free lane) or telemetry can't estimate — so free lanes are never
    blocked on credits, only on max_calls."""
    fn = getattr(telemetry, "_est_credits", None)
    if fn is None or lane is None:
        return 0.0
    try:
        return float(fn(lane.key, tokens) or 0.0)
    except Exception:
        return 0.0


def _task_input_tokens(task_text: str) -> int:
    return max(1, len(task_text or "") // config.CHARS_PER_TOKEN)


class _BudgetLedger:
    """Per-invocation spend guard. try_reserve is atomic (asyncio.Lock) so parallel tasks can't
    check-then-increment-interleave past the cap. Reserves the conservative estimate BEFORE a spawn;
    a task that can't reserve is skipped (never spawned)."""
    def __init__(self, max_calls: int = 0, max_credits: float = 0.0):
        self.max_calls = max(0, max_calls)
        self.max_credits = max(0.0, max_credits)
        self.calls = 0
        self.credits = 0.0
        self._lock = asyncio.Lock()

    def active(self) -> bool:
        return self.max_calls > 0 or self.max_credits > 0.0

    async def try_reserve(self, est_credits: float) -> bool:
        async with self._lock:
            if self.max_calls and self.calls >= self.max_calls:
                return False
            if self.max_credits and self.credits + est_credits > self.max_credits:
                return False
            self.calls += 1
            self.credits += est_credits
            return True


def estimate(tasks: list[dict], *, resolve_lane, default_lane, telemetry) -> dict:
    """Pre-execution cost envelope (no spawn): per-task lane + estimated input tokens + a credit
    RANGE (min = input-only, max = input + ~EST_OUTPUT_MULT× output, since output is unknown)."""
    rows, in_tot, cmin, cmax = [], 0, 0.0, 0.0
    for t in tasks[:MAX_BATCH_TASKS]:
        lane = resolve_lane(t["lane"]) if t.get("lane") else default_lane
        in_tok = _task_input_tokens(t.get("task", ""))
        lo = _est_credits(lane, in_tok, telemetry)
        hi = _est_credits(lane, in_tok * (1 + EST_OUTPUT_MULT), telemetry)
        in_tot += in_tok
        cmin += lo
        cmax += hi
        rows.append({"lane": (lane.key if lane else t.get("lane") or "—"),
                     "est_input_tokens": in_tok})
    return {"n_calls": len(rows), "est_input_tokens_total": in_tot,
            "est_credits_min": round(cmin, 4), "est_credits_max": round(cmax, 4),
            "tasks": rows,
            "note": "estimate only (chars/4; output tokens unknown -> min=input, max=input+~3x)"}


def render_estimate(env: dict) -> str:
    lines = [f"# batch — cost envelope ({env['n_calls']} calls, nothing spawned)", "",
             f"_~{env['est_input_tokens_total']} input tokens; est credits "
             f"{env['est_credits_min']}–{env['est_credits_max']} ({env['note']})_\n"]
    for r in env["tasks"]:
        lines.append(f"- {r['lane']} — ~{r['est_input_tokens']} in-tok")
    return "\n".join(lines)


async def batch_run(tasks: list[dict], *, run_lane, resolve_lane, default_lane, telemetry,
                    run_id: str = "", max_concurrency: int = 0, max_calls: int = 0,
                    max_credits: float = 0.0, progress=None
                    ) -> tuple[str, list[dict]]:
    """Fan out `tasks` (each {task, lane?, model?, effort?, cwd?}) concurrently, journalling each.
    Returns (run_id, results) where results align with tasks: {task, lane, ok, output, cached, +
    provenance}. A finished (ok) task is replayed from the journal on a resume; failed/missing
    tasks re-run. max_calls/max_credits cap the invocation: over-budget tasks are SKIPPED (never
    spawned, not journalled) so a resume with a higher cap runs them."""
    run_id = run_id or _new_run_id()
    cached = telemetry.batch_get(run_id)
    ledger = _BudgetLedger(max_calls, max_credits)
    sem = asyncio.Semaphore(max_concurrency if max_concurrency > 0 else config.max_parallel())
    total = len(tasks)
    done = 0
    prog_lock = asyncio.Lock()

    async def _one(i: int, t: dict) -> dict:
        nonlocal done
        key = _task_key(run_id, t)
        hit = cached.get(key)
        if hit and hit["status"] == "done":                  # resume: replay a finished task
            out = {"i": i, "task": t.get("task", ""), "lane": t.get("lane", ""),
                   "ok": True, "output": hit["result"] or "", "cached": True,
                   "model": t.get("model") or "", "kind": "ok", "latency_ms": 0,
                   "exit_code": None}
        else:
            lane = resolve_lane(t["lane"]) if t.get("lane") else default_lane
            if lane is None:
                telemetry.batch_put(run_id, key, "failed", error="no such lane")
                out = {"i": i, "task": t.get("task", ""), "lane": t.get("lane", ""),
                       "ok": False, "output": f"[error] no such lane: {t.get('lane')}",
                       "cached": False, "model": t.get("model") or "", "kind": "failed",
                       "latency_ms": 0, "exit_code": None}
            elif ledger.active() and not await ledger.try_reserve(
                    _est_credits(lane, _task_input_tokens(t.get("task", "")) * (1 + EST_OUTPUT_MULT),
                                 telemetry)):
                # Over the invocation budget — skip WITHOUT spawning and WITHOUT journalling, so a
                # resume with a higher cap will run it.
                out = {"i": i, "task": t.get("task", ""), "lane": lane.key, "ok": False,
                       "output": "[skipped: invocation budget reached]", "cached": False,
                       "model": t.get("model") or "", "kind": "blocked", "latency_ms": 0,
                       "exit_code": None}
            else:
                async with sem:
                    r = await run_lane(lane, {"task": t.get("task", ""), "model": t.get("model"),
                                              "effort": t.get("effort"), "cwd": t.get("cwd"),
                                              "timeout_s": t.get("timeout_s")})
                telemetry.batch_put(run_id, key, "done" if r.ok else "failed",
                                    result=r.output if r.ok else None,
                                    error=None if r.ok else r.render())
                # Provenance (the council's day-1 requirement): carry model/kind/latency/exit so a
                # downstream step can gate on them and the host can debug a run.
                out = {"i": i, "task": t.get("task", ""), "lane": lane.key,
                       "ok": r.ok, "output": r.render(), "cached": False,
                       "model": getattr(r, "model", "") or (t.get("model") or ""),
                       "kind": r.kind, "latency_ms": r.latency_ms, "exit_code": r.exit_code}
        async with prog_lock:
            done += 1
            d = done
        if progress is not None:
            await progress(d, total, out["lane"])
        return out

    raw = await asyncio.gather(*[_one(i, t) for i, t in enumerate(tasks)], return_exceptions=True)
    results = []
    for i, r in enumerate(raw):
        if isinstance(r, BaseException):                     # one crash must not sink the batch
            results.append({"i": i, "task": tasks[i].get("task", ""), "lane": "",
                            "ok": False, "output": f"[crash] {r}", "cached": False})
        else:
            results.append(r)
    results.sort(key=lambda d: d["i"])
    return run_id, results


# ── presets ──────────────────────────────────────────────────────────────────────────────────

_GROUPED_NOTE = ("Grouped per lane — dedupe + integrate yourself, or pass judge_lane for a single "
                 "deduped list.")


def _render_results(results: list[dict], title: str, note: str, head: str = "") -> str:
    """One renderer for every fan-out ([{lane, ok, output, cached, model}]); `head` is the
    per-result heading prefix ('{i}. ', 'Option {i} — ', or none). Grouping as-is is the default
    synthesis: the HOST (or judge_lane) does the semantic dedupe string matching can't."""
    ok = sum(1 for r in results if r["ok"])
    lines = [f"# {title} — {ok}/{len(results)} ok", f"_{note}_\n"]
    for i, r in enumerate(results, 1):
        who = r["lane"] or "—"
        if r.get("model"):
            who += f" ({r['model']})"
        if r.get("cached"):
            who += " (cached)"
        lines.append(f"## {head.format(i=i)}{'✅' if r['ok'] else '❌'} {who}\n")
        lines.append((r["output"].strip() or "_(no output)_") + "\n")
    return "\n".join(lines)


async def _judge(judge_lane, run_lane, results: list[dict], instruction: str) -> str:
    """Hardcoded post-fan-out step (NOT a task, NOT a DSL): one lane dedupes + ranks the pooled
    findings into a single actionable list."""
    pooled = "\n\n".join(f"### from {r['lane']}\n{r['output'].strip()}"
                         for r in results if r["ok"] and r["output"].strip())
    if not pooled:
        return "[error] no successful findings to judge."
    r = await run_lane(judge_lane, {"task": f"{instruction}\n\n{pooled}"})
    return f"# Synthesis (judge: {judge_lane.display})\n\n{r.render().strip()}"


def _lanes_or_default(lane_keys, resolve_lane, default_lanes):
    if lane_keys:
        out = [resolve_lane(k) for k in lane_keys]
        return [ln for ln in out if ln is not None]
    return list(default_lanes)


async def map_review(*, run_lane, resolve_lane, default_lanes, telemetry, files: list[str],
                     lane=None, judge_lane=None, run_id="", progress=None) -> str:
    ln = resolve_lane(lane) if lane else (default_lanes[0] if default_lanes else None)
    if ln is None:
        return "[error] no lane available for map_review."
    tasks = []
    for f in files[:MAX_BATCH_TASKS]:
        path = os.path.abspath(os.path.expanduser(f))
        tasks.append({"lane": ln.key, "cwd": os.path.dirname(path),
                      "task": f"Review the file `{os.path.basename(path)}` (in your working dir) "
                              "for bugs, risks, and issues. Return a terse findings list "
                              "(severity, location, problem, fix). No preamble."})
    run_id, results = await batch_run(tasks, run_lane=run_lane, resolve_lane=resolve_lane,
                                      default_lane=ln, telemetry=telemetry, run_id=run_id,
                                      progress=progress)
    # relabel each result with its file (tasks align with results order)
    for r, f in zip(results, files, strict=False):
        r["lane"] = f"{r['lane']} · {os.path.basename(f)}"
    if judge_lane:
        jl = resolve_lane(judge_lane)
        if jl:
            return await _judge(jl, run_lane, results,
                                "Merge these per-file reviews into one prioritised list.")
    return _render_results(results, "Map review (per file)", _GROUPED_NOTE)


async def research_verify(*, run_lane, resolve_lane, default_lanes, telemetry, questions: list[str],
                          lanes=None, run_id="", progress=None) -> str:
    use = _lanes_or_default(lanes, resolve_lane, default_lanes)
    if not use:
        return "[error] no lanes available for research_verify."
    # Phase 1: answer each question (round-robin across lanes).
    ans_tasks = [{"lane": use[i % len(use)].key, "task": q}
                 for i, q in enumerate(questions[:MAX_BATCH_TASKS])]
    run_id, answers = await batch_run(ans_tasks, run_lane=run_lane, resolve_lane=resolve_lane,
                                      default_lane=use[0], telemetry=telemetry, run_id=run_id,
                                      progress=progress)
    # Phase 2: adversarially verify each answer on a DIFFERENT lane.
    ver_tasks = []
    for i, a in enumerate(answers):
        verifier = use[(i + 1) % len(use)]
        ver_tasks.append({"lane": verifier.key,
                          "task": f"Question: {a['task']}\n\nA claimed answer:\n{a['output']}\n\n"
                                  "Verify it. Flag anything wrong, unsupported, or missing. If it "
                                  "is correct, say so briefly."})
    _vrun, verdicts = await batch_run(ver_tasks, run_lane=run_lane, resolve_lane=resolve_lane,
                                      default_lane=use[0], telemetry=telemetry, progress=progress)
    lines = ["# research_verify", f"_resume_id `{run_id}` (phase-1 answers)_\n"]
    for a, v in zip(answers, verdicts, strict=False):
        lines += [f"## Q: {a['task'][:200]}\n", "**Answer:**\n", a["output"].strip() or "_(none)_",
                  "\n**Verification:**\n", v["output"].strip() or "_(none)_", ""]
    return "\n".join(lines)


def _refine_prompt(angle: str, instruction: str, fname: str, plan_text: str) -> str:
    head = (f"You are pressure-testing an implementation plan, angle: {angle}.\n{instruction}\n"
            "Return a terse findings list — each: severity (blocker/high/medium/low), location in "
            "the plan, the problem, and a concrete fix. No preamble, no praise.")
    if fname:                                                # file-based: the lane reads it itself
        return f"{head}\n\nThe plan is in the file `{fname}` in your working directory. Read it."
    return f"{head}\n\nPLAN:\n{plan_text}"                    # inline fallback


async def refine_plan(*, run_lane, resolve_lane, default_lanes, telemetry, plan_file: str = "",
                      plan: str = "", lanes=None, angles=None, judge_lane=None, run_id="",
                      progress=None) -> str:
    """The flagship: fan the plan out to N lanes, each demolishing it from a DISTINCT angle, then
    group (host synthesises) or judge (one deduped patch list). plan_file is preferred — each lane
    reads the file from its cwd, so the plan is NEVER recopied into N prompts (token-frugal)."""
    use = _lanes_or_default(lanes, resolve_lane, default_lanes)
    if not use:
        return "[error] no lanes available for refine_plan."
    if not plan_file and not plan.strip():
        return "[error] pass plan_file (preferred) or plan."
    fname, cwd = "", ""
    if plan_file:
        ap = os.path.abspath(os.path.expanduser(plan_file))
        if not os.path.isfile(ap):
            return f"[error] plan_file not found: {plan_file}"
        fname, cwd = os.path.basename(ap), os.path.dirname(ap)
    angle_names = angles or [a[0] for a in REFINE_ANGLES]
    instr = {a[0]: a[1] for a in REFINE_ANGLES}
    tasks = []
    for i, angle in enumerate(angle_names):
        lane = use[i % len(use)]
        tasks.append({"lane": lane.key, "cwd": cwd,
                      "task": _refine_prompt(angle, instr.get(angle, f"Critique re: {angle}."),
                                             fname, plan)})
    run_id, results = await batch_run(tasks, run_lane=run_lane, resolve_lane=resolve_lane,
                                      default_lane=use[0], telemetry=telemetry, run_id=run_id,
                                      progress=progress)
    for r, angle in zip(results, angle_names, strict=False):
        r["lane"] = f"{r['lane']} · {angle}"
    if judge_lane:
        jl = resolve_lane(judge_lane)
        if jl:
            return await _judge(jl, run_lane, results,
                                "Dedupe these plan critiques (semantic, not string), sort by "
                                "severity, and output one actionable patch list for the plan.")
    return _render_results(results, "Plan pressure-test (refine_plan)", _GROUPED_NOTE)


# ── fanout-compare: same task to N lanes, side by side ──────────────────────────────────────────

def _parse_lane_entries(lane_keys, resolve_lane, default_lanes):
    """Resolve ['gpt', 'opencode:opencode/deepseek-v4-flash-free', …] to (LaneSpec, model) pairs.
    The 'lane:model' form lets ONE gateway lane field several of its models side by side —
    e.g. a council of opencode's free models — without hand-writing custom lanes."""
    if not lane_keys:
        return [(ln, "") for ln in default_lanes]
    out = []
    for entry in lane_keys:
        key, _, model = str(entry).partition(":")
        ln = resolve_lane(key.strip())
        if ln is not None:
            out.append((ln, model.strip()))
    return out


async def fanout_compare(*, run_lane, resolve_lane, default_lanes, telemetry, task: str,
                         lanes=None, judge_lane=None, cwd: str = "", run_id="", progress=None) -> str:
    """Same task to N lanes, answers rendered SIDE BY SIDE for the host/human to compare and merge
    (e.g. 'fix this bug' on 3 CLIs -> pick the best diff). Lanes accept 'lane:model' to compare
    several models of ONE lane (e.g. opencode's free models). Optional judge_lane recommends one."""
    use = _parse_lane_entries(lanes, resolve_lane, default_lanes)
    if not use:
        return "[error] no lanes available for fanout_compare."
    tasks = [{"lane": ln.key, "model": model, "task": task, "cwd": cwd} for ln, model in use]
    run_id, results = await batch_run(tasks, run_lane=run_lane, resolve_lane=resolve_lane,
                                      default_lane=use[0][0], telemetry=telemetry, run_id=run_id,
                                      progress=progress)
    if judge_lane:
        jl = resolve_lane(judge_lane)
        if jl:
            return await _judge(jl, run_lane, results,
                                "These are alternative solutions to the SAME task. Compare them, "
                                "note key differences and trade-offs, and recommend ONE to adopt "
                                "(or a specific merge), with reasons.")
    return _render_results(results, "fanout_compare", f"task: {task[:200]} · same prompt, N models — "
                           "compare the alternatives and pick/merge one, or re-run with "
                           "judge_lane for a recommendation.", head="Option {i} — ")


# ── cross-family lane picking (converge) ───────────────────────────────────────────────────────

def _cross_family_verifiers(default_lanes, author, n: int):
    fam = lanes.family_of(author)
    pool = [ln for ln in default_lanes if lanes.family_of(ln) != fam]
    return pool[:n] if n > 0 else pool


# ── converge: governance loop (blind-verdict-first + no-silent-dismissal + no-self-approval) ──
# An author drafts a plan, an independent ARBITER commits a BLIND verdict before seeing anyone,
# cross-family ANONYMIZED peers review, the arbiter adjudicates every issue (fail-closed: an
# ignored or reason-less dismissal counts as ACCEPTED), then revise-or-converge, bounded by
# max_rounds. Convergence needs the PEERS to carry it: arbiter approves AND ≥1 peer responded AND
# every responding peer approves AND no accepted (unfixed) issue. Any weak signal blocks.

APPROVE, REJECT, ABSTAIN = "approve", "reject", "abstain"
ACCEPT, DISMISS, DEFER = "accept", "dismiss", "defer"
_DECISIONS = {ACCEPT, DISMISS, DEFER}
_NEEDS_REASON = {DISMISS, DEFER}


@dataclass
class CriticalIssue:
    id: str
    peer: str                       # neutral label, e.g. "Reviewer A"
    title: str
    detail: str = ""
    category: str | None = None     # taxonomy value (already normalized) or None


def _converge_author_prompt(task: str) -> str:
    return ("Produce a complete, concrete PLAN / answer for the task below. It will be scrutinised "
            "by independent peer reviewers and an arbiter, so make it specific and defensible — no "
            f"hand-waving.\n\nTASK:\n{task}")


_CONVERGE_BLIND = (
    "You are the ARBITER. Judge the PLAN below ON ITS OWN MERITS — you have NOT seen anyone else's "
    "opinion and you must commit your independent verdict NOW (it is recorded before any peer "
    "review, so you cannot be anchored by them).\n\nTASK:\n{task}\n\nPLAN:\n{plan}\n\nGive a "
    "one-paragraph assessment, then end with EXACTLY one line: `VERDICT: APPROVE` (ship it), "
    "`VERDICT: REQUEST_CHANGES` (needs work), or `VERDICT: ABSTAIN` (cannot tell). Default to "
    "REQUEST_CHANGES if unsure.")


def _converge_peer_prompt(task: str, plan: str) -> str:
    return (
        "You are an independent reviewer. Review the PLAN for the TASK and surface ONLY genuine "
        f"BLOCKING problems — do not pad with nitpicks or out-of-scope rewrites.\n\nTASK:\n{task}"
        f"\n\nPLAN:\n{plan}\n\n"
        'Return ONLY a JSON array of issues — each {"category": '
        '"security|correctness|scope|ambiguity|performance|ops", "title": "<short>", "detail": '
        '"<what is wrong and why it blocks>"}. Return [] if there are no blocking problems. '
        "Then on a FINAL separate line write exactly one of: `STANCE: APPROVE` (ship as-is) or "
        "`STANCE: REJECT` (must change first).")


def _parse_verdict(text: str) -> str:
    hits = re.findall(r"VERDICT:\s*(APPROVE|REQUEST_CHANGES|ABSTAIN)", text or "", re.IGNORECASE)
    if not hits:
        return ABSTAIN                                          # fail-closed: no verdict => abstain
    v = hits[-1].upper()
    return APPROVE if v == "APPROVE" else (ABSTAIN if v == "ABSTAIN" else REJECT)


def _parse_stance(text: str) -> str:
    hits = re.findall(r"STANCE:\s*(APPROVE|REJECT|ABSTAIN)", text or "", re.IGNORECASE)
    return hits[-1].lower() if hits else ABSTAIN                # fail-closed: no stance => abstain


def _peer_issues(text: str, label: str) -> list:
    """Parse a peer's JSON issue array into CriticalIssues. Tolerant + fail-safe: anything that
    isn't a clean array of titled objects yields NO issues (the STANCE line still carries the
    signal), so a chatty reply can't fabricate a blocker."""
    val, _ = findings.extract_json(text or "")
    out = []
    if isinstance(val, list):
        for idx, it in enumerate(val, 1):
            if not isinstance(it, dict):
                continue
            title = str(it.get("title") or it.get("issue") or "").strip()
            if not title:
                continue
            out.append(CriticalIssue(
                id=f"{label.replace(' ', '')}-{idx}", peer=label, title=title[:160],
                detail=str(it.get("detail") or it.get("evidence") or "").strip()[:600],
                category=findings.normalize_category(it.get("category") or it.get("type"))))
    return out


def _adjudicate_prompt(task: str, plan: str, issues: list) -> str:
    listed = "\n".join(f"- [{i.id}] ({i.category or 'general'}) {i.title}: {i.detail}"
                       for i in issues)
    return ("You are the ARBITER. Peers raised the ISSUES below about the PLAN. Rule on EACH one "
            "honestly: accept the real blockers, dismiss the wrong or out-of-scope ones, defer the "
            f"real-but-non-blocking ones.\n\nTASK:\n{task}\n\nPLAN:\n{plan}\n\nISSUES:\n{listed}\n\n"
            'Return ONLY a JSON array, one object per issue id: {"id": "<id>", "decision": '
            '"accept|dismiss|defer", "reason": "<why — REQUIRED for dismiss and defer>"}. '
            "accept = a real blocker the plan must fix; dismiss = not a real problem; defer = real "
            "but can ship and fix later.")


def _parse_adjudications(text: str, issues: list) -> dict[str, str]:
    """Map the arbiter's JSON onto every issue -> {issue_id: decision}. FAIL-CLOSED: an issue the
    arbiter ignored, or dismissed/deferred without a reason, is upgraded to an ACCEPTED blocker —
    never silently dropped."""
    val, _ = findings.extract_json(text or "")
    ruled: dict[str, tuple[str, str]] = {}
    if isinstance(val, list):
        for it in val:
            if isinstance(it, dict) and str(it.get("id") or "").strip():
                dec = str(it.get("decision") or "").strip().lower()
                if dec in _DECISIONS:
                    ruled[str(it["id"]).strip()] = (dec, str(it.get("reason") or "").strip())
    out = {}
    for i in issues:
        dec, reason = ruled.get(i.id, (ACCEPT, ""))
        out[i.id] = ACCEPT if dec in _NEEDS_REASON and not reason else dec
    return out


def _revise_prompt(task: str, plan: str, accepted: list) -> str:
    items = "\n".join(f"- {i.title}: {i.detail}" for i in accepted) or "- (none)"
    return ("Revise the PLAN to FULLY address the ACCEPTED blocking issues below. Keep what works; "
            f"change only what the issues require.\n\nTASK:\n{task}\n\nCURRENT PLAN:\n{plan}\n\n"
            "ACCEPTED ISSUES TO FIX:\n" + items + "\n\nReturn the COMPLETE revised plan.")


def _converge_labels(peers: list) -> dict:
    return {ln.key: f"Reviewer {chr(65 + i)}" for i, ln in enumerate(peers)}


def _render_converge(report: dict, *, task: str, author, arbiter, panel, labels, final_plan) -> str:
    banner = "✅ CONVERGED" if report["outcome"] == "converged" else "⚠️ UNRESOLVED"
    lines = [f"# converge — {banner}  (round {report['settled_round']}/{report['max_rounds']}, "
             f"confidence {report['confidence']})",
             f"_author: {author.display} · arbiter: {arbiter.display} · peers: "
             + ", ".join(f"{labels[p.key]}={p.display}" for p in panel) + "_",
             "",
             "_Guards enforced: blind-verdict-first · no-silent-dismissal · no-self-approval "
             "(peers carry it, not the arbiter)._",
             "", "## Rounds", ""]
    for h in report["history"]:
        peers = ", ".join(f"{p['peer']}:{p['stance']}" + ("" if p["responded"] else "(no-run)")
                          for p in h["peers"]) or "—"
        lines.append(f"- **Round {h['round']}** — arbiter blind: `{h['blind_verdict']}` · peers: "
                     f"{peers} · accepted: {h['accepted']} · deferred: {h['deferred']}")
    if report["unaddressed_issues"]:
        lines += ["", "## Unresolved blocking issues", ""]
        lines += [f"- ({i['category'] or 'general'}) {i['title']} — _{i['peer']}_"
                  for i in report["unaddressed_issues"]]
    if report["residual_issues"]:
        lines += ["", "## Deferred (non-blocking) — residual risk", ""]
        lines += [f"- ({i['category'] or 'general'}) {i['title']} — _{i['peer']}_"
                  for i in report["residual_issues"]]
    lines += ["", "## Final plan", "", final_plan or "_(empty)_"]
    return "\n".join(lines)


async def converge(*, run_lane, resolve_lane, default_lanes, telemetry, task: str,
                   author_lane: str = "", arbiter_lane: str = "", peer_lanes=None, peers: int = 0,
                   max_rounds: int = 5, cwd: str = "", run_id: str = "", progress=None) -> str:
    """Governance converge-loop. Author drafts -> arbiter blind verdict -> anonymized cross-family
    peers review -> arbiter adjudicates (reasoned) -> revise or converge, bounded by max_rounds."""
    if not (task or "").strip():
        return "[error] converge needs a task / plan goal."
    author = resolve_lane(author_lane) if author_lane else (default_lanes[0] if default_lanes else None)
    if author is None:
        return "[error] no author lane available for converge."
    if arbiter_lane:
        arbiter = resolve_lane(arbiter_lane) or author
    else:                                              # prefer an independent (cross-family) arbiter
        arbiter = (next(iter(_cross_family_verifiers(default_lanes, author, 0)), None)
                   or next((ln for ln in default_lanes if ln.key != author.key), None) or author)
    exclude = {author.key, arbiter.key}
    if peer_lanes:
        panel = [ln for ln in (resolve_lane(k) for k in peer_lanes)
                 if ln is not None and ln.key not in exclude]
    else:
        want = peers if peers > 0 else min(3, max(0, len(default_lanes) - 1))
        panel = [ln for ln in _cross_family_verifiers(default_lanes, author, 0)
                 if ln.key not in exclude][:want]
        if not panel:                                  # mono-family / tiny pool: any distinct lane
            panel = [ln for ln in default_lanes if ln.key not in exclude][:max(1, want)]
    if not panel:
        return ("[error] converge needs at least one peer lane distinct from the author and "
                "arbiter — install/login another CLI or pass peer_lanes.")

    labels = _converge_labels(panel)
    sub = {"cwd": cwd} if cwd else {}
    max_rounds = max(1, int(max_rounds or 5))

    ar = await run_lane(author, {**sub, "task": _converge_author_prompt(task)}, tool="converge")
    if not ar.ok:
        return f"# converge — author {author.display} FAILED ({ar.kind})\n\n{ar.render()}"
    plan = ar.output.strip()

    history: list[dict] = []
    for rnd in range(1, max_rounds + 1):
        # 1. arbiter's BLIND verdict — recorded before any peer is consulted
        br = await run_lane(arbiter, {**sub, "task": _CONVERGE_BLIND.format(task=task, plan=plan)},
                            tool="converge")
        blind = _parse_verdict(br.output) if br.ok else ABSTAIN
        # 2. anonymized cross-family peers review the plan in parallel
        ptasks = [{"lane": p.key, **sub, "task": _converge_peer_prompt(task, plan)}
                  for p in panel]
        _rid, presults = await batch_run(ptasks, run_lane=run_lane, resolve_lane=resolve_lane,
                                         default_lane=panel[0], telemetry=telemetry, run_id=run_id,
                                         progress=progress)
        peer_rows, issues = [], []
        for p, r in zip(panel, presults, strict=False):
            lab = labels[p.key]
            raised = _peer_issues(r["output"], lab) if r["ok"] else []
            issues += raised
            peer_rows.append({"peer": lab, "stance": _parse_stance(r["output"]) if r["ok"] else ABSTAIN,
                          "responded": bool(r["ok"]), "issues": len(raised)})
        # 3. arbiter adjudicates EVERY issue with a mandatory reason (fail-closed in the parser)
        decision: dict[str, str] = {}
        if issues:
            jr = await run_lane(arbiter, {**sub, "task": _adjudicate_prompt(task, plan, issues)},
                                tool="converge")
            decision = _parse_adjudications(jr.output if jr.ok else "", issues)
        accepted = [i for i in issues if decision.get(i.id) == ACCEPT]
        deferred = [i for i in issues if decision.get(i.id) == DEFER]
        history.append({"round": rnd, "blind_verdict": blind, "peers": peer_rows,
                        "accepted": len(accepted), "deferred": len(deferred)})
        # 4. no-self-approval, fail-closed: the peers must carry it, not the arbiter alone
        responders = [p for p in peer_rows if p["responded"]]
        converged = (blind == APPROVE and bool(responders)
                     and all(p["stance"] == APPROVE for p in responders) and not accepted)
        if converged or rnd == max_rounds:
            break
        rr = await run_lane(author, {**sub, "task": _revise_prompt(task, plan, accepted)},
                            tool="converge")
        if not rr.ok:
            break                                      # no revision possible → unresolved
        plan = rr.output.strip()

    report = {"outcome": "converged" if converged else "unresolved", "rounds": rnd,
              "max_rounds": max_rounds, "settled_round": rnd,
              "confidence": ("high" if rnd == 1 else "medium" if rnd <= 3 else "low")
              if converged else "none",
              "residual_issues": [asdict(i) for i in deferred],
              "unaddressed_issues": [] if converged else [asdict(i) for i in accepted],
              "history": history}
    return _render_converge(report, task=task, author=author, arbiter=arbiter, panel=panel,
                            labels=labels, final_plan=plan)
