"""Durable fan-out + presets.

`batch_run` is the substrate: run N INDEPENDENT asks concurrently (capped), journaling each to
SQLite (key = hash(run_id, task)) so a `resume_id` replays the tasks that already FINISHED and
only runs the rest — surviving a server restart (the edge over Claude Code's in-session resume).
The host composes the LOGIC (loops, conditions) in its own reasoning; cli-bridge just executes
durably. We deliberately did NOT add a JSON composition DSL — it would be weaker than the host
orchestrating itself, for far more code (council + user signal: don't over-complex).

On top sit four PRESETS — coroutines that fan out then post-process with a hardcoded step (a
judge or a grouping), NOT a DSL: council_review, map_review, research_verify, and the flagship
refine_plan ("let the council demolish my plan"). All are resumable and can run in background.

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

from . import config, lanes

MAX_BATCH_TASKS = 64           # anti-runaway: the existing cost model governs spend; this caps count
VERIFY_MAX_ROUNDS = 6          # hard cap on the build->verify->repair loop (cost guard)

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


def render_batch(run_id: str, results: list[dict]) -> str:
    cached = sum(1 for r in results if r.get("cached"))
    ok = sum(1 for r in results if r["ok"])
    lines = [f"# batch_run — {ok}/{len(results)} ok ({cached} replayed from cache)",
             f"_resume with resume_id `{run_id}` (re-runs only what didn't finish)_\n"]
    for i, r in enumerate(results, 1):
        tag = "✅" if r["ok"] else "❌"
        cache = " (cached)" if r.get("cached") else ""
        lines.append(f"## {i}. {tag} {r['lane'] or '—'}{cache}\n")
        lines.append(f"_task: {r['task'][:200]}_\n" if r["task"] else "")
        lines.append((r["output"].strip() or "_(no output)_") + "\n")
    return "\n".join(lines)


# ── presets ──────────────────────────────────────────────────────────────────────────────────

def _group(results: list[dict], header: str) -> str:
    """Default synthesis: group findings as-is for the HOST to dedupe + integrate (string dedup
    fails — 'lock race' == 'TOCTOU lockfile' needs a semantic merge, i.e. the host or a judge)."""
    lines = [f"# {header}", "_Grouped per lane — dedupe + integrate yourself, or pass judge_lane "
             "for a single deduped list._\n"]
    for r in results:
        tag = "✅" if r["ok"] else "❌"
        lines.append(f"## {tag} {r['lane'] or '—'}\n")
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


async def council_review(*, run_lane, resolve_lane, default_lanes, telemetry, question: str,
                         lanes=None, judge_lane=None, run_id="", progress=None) -> str:
    use = _lanes_or_default(lanes, resolve_lane, default_lanes)
    if not use:
        return "[error] no lanes available for council_review."
    tasks = [{"lane": ln.key, "task": question} for ln in use]
    run_id, results = await batch_run(tasks, run_lane=run_lane, resolve_lane=resolve_lane,
                                      default_lane=use[0], telemetry=telemetry, run_id=run_id,
                                      progress=progress)
    if judge_lane:
        jl = resolve_lane(judge_lane)
        if jl:
            return await _judge(jl, run_lane, results,
                                "Synthesise these answers into one: agreements, disagreements, "
                                "and the best conclusion.")
    return _group(results, "Council review")


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
    return _group(results, "Map review (per file)")


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
    return _group(results, "Plan pressure-test (refine_plan)")


# ── verify-repair: cross-model build -> review -> repair loop ───────────────────────────────────

def _verdict(text: str) -> str:
    """Read the verifier's verdict. Last `VERDICT: APPROVED|ISSUES` wins; absent => ISSUES
    (fail-closed — never approve on a malformed/empty review, the adversarial-verify default)."""
    hits = re.findall(r"VERDICT:\s*(APPROVED|ISSUES)", text or "", re.IGNORECASE)
    return hits[-1].upper() if hits else "ISSUES"


def _other_lane(default_lanes, not_key: str):
    """First default lane whose key differs from `not_key` — the cross-model verifier."""
    return next((ln for ln in default_lanes if ln.key != not_key), None)


async def verify_repair(*, run_lane, resolve_lane, default_lanes, task: str, builder_lane: str = "",
                        verifier_lane: str = "", max_rounds: int = 3, cwd: str = "",
                        cross_family: bool = False, progress=None) -> str:
    """A (builder) produces -> B (a DIFFERENT model, verifier) reviews -> if VERDICT: ISSUES the
    issues go back to A -> loop until VERDICT: APPROVED or max_rounds. Cross-model is the point:
    B's failure modes are uncorrelated with A's, so it catches what A's own self-review can't. A
    light convention (the verifier ends with VERDICT: APPROVED|ISSUES), no schema. cross_family=True
    picks a verifier from a DIFFERENT vendor family (default False = first other lane, back-compat)."""
    builder = resolve_lane(builder_lane) if builder_lane else (default_lanes[0] if default_lanes else None)
    if builder is None:
        return "[error] no builder lane available for verify_repair."
    if verifier_lane:
        verifier = resolve_lane(verifier_lane)
    elif cross_family:
        verifier = next(iter(_cross_family_verifiers(default_lanes, builder, 1)), None) \
            or _other_lane(default_lanes, builder.key)
    else:
        verifier = _other_lane(default_lanes, builder.key)
    if verifier is None:
        return ("[error] no verifier lane available — verify_repair needs a SECOND lane (a "
                "different model). Install/login another CLI or pass verifier_lane.")
    rounds = max(1, min(int(max_rounds or 1), VERIFY_MAX_ROUNDS))
    same = verifier.key == builder.key
    sub = {"cwd": cwd} if cwd else {}

    lines = [f"# verify_repair — builder: {builder.display} · verifier: {verifier.display}"]
    if same:
        lines.append("> ⚠️ verifier is the SAME lane as builder — no cross-model benefit. "
                     "Pass a distinct verifier_lane for uncorrelated review.\n")
    approved = False
    last = ""
    prev_output = ""
    for rnd in range(1, rounds + 1):
        if rnd == 1:
            btask = (f"{task}\n\nDo the work and output the complete result (code/diff/answer). "
                     "No preamble.")
        else:
            btask = (f"{task}\n\nYour previous attempt:\n{prev_output}\n\nA reviewer (a different "
                     f"model) found these issues:\n{last}\n\nRevise to fully address every issue. "
                     "Output the corrected, complete result. No preamble.")
        br = await run_lane(builder, {**sub, "task": btask}, tool="verify_repair")
        if not br.ok:
            lines.append(f"\n## Round {rnd} — builder {builder.display} FAILED ({br.kind})\n")
            return "\n".join(lines) + "\n\n---\n**Final: ⚠️ aborted — builder failed.**"
        prev_output = br.output.strip()

        vtask = (f"You are a STRICT reviewer, a DIFFERENT model than the author. The task:\n{task}"
                 f"\n\nThe author's result:\n{prev_output}\n\nReview it rigorously for correctness, "
                 "completeness, bugs, and missed requirements. List concrete issues. Then end with "
                 "exactly one final line: `VERDICT: APPROVED` if it fully and correctly satisfies "
                 "the task, otherwise `VERDICT: ISSUES`. Default to ISSUES if unsure.")
        vr = await run_lane(verifier, {**sub, "task": vtask}, tool="verify_repair")
        if progress is not None:
            await progress(rnd, rounds, f"round {rnd}")
        if not vr.ok:
            lines.append(f"\n## Round {rnd}\n**Builder:**\n{prev_output}\n\n"
                         f"**Verifier {verifier.display} FAILED ({vr.kind})** — stopping.\n")
            return "\n".join(lines) + "\n\n---\n**Final: ⚠️ aborted — verifier failed.**"
        last = vr.output.strip()
        verdict = _verdict(last)
        lines.append(f"\n## Round {rnd} — {'✅ APPROVED' if verdict == 'APPROVED' else '🔧 ISSUES'}\n")
        lines.append(f"**Builder ({builder.display}):**\n\n{prev_output}\n")
        lines.append(f"**Verifier ({verifier.display}):**\n\n{last}\n")
        if verdict == "APPROVED":
            approved = True
            break

    head = (f"**Final: ✅ APPROVED in {rnd} round(s).**" if approved
            else f"**Final: ⚠️ NOT APPROVED after {rounds} round(s) — the last issues stand. "
                 "Increase max_rounds or fix manually.**")
    return "\n".join(lines) + f"\n\n---\n{head}"


# ── fanout-compare: same task to N lanes, side by side ──────────────────────────────────────────

def _compare(results: list[dict], task: str) -> str:
    ok = sum(1 for r in results if r["ok"])
    lines = [f"# fanout_compare — {ok}/{len(results)} lanes answered the SAME task",
             f"_task: {task[:200]}_",
             "_Same prompt, N models — compare the alternatives and pick/merge one, or re-run with "
             "judge_lane for a recommendation._\n"]
    for i, r in enumerate(results, 1):
        tag = "✅" if r["ok"] else "❌"
        lines.append(f"## Option {i} — {tag} {r['lane'] or '—'}\n")
        lines.append((r["output"].strip() or "_(no output)_") + "\n")
    return "\n".join(lines)


async def fanout_compare(*, run_lane, resolve_lane, default_lanes, telemetry, task: str,
                         lanes=None, judge_lane=None, cwd: str = "", run_id="", progress=None) -> str:
    """Same task to N lanes, answers rendered SIDE BY SIDE for the host/human to compare and merge
    (e.g. 'fix this bug' on 3 CLIs -> pick the best diff). Optional judge_lane recommends one."""
    use = _lanes_or_default(lanes, resolve_lane, default_lanes)
    if not use:
        return "[error] no lanes available for fanout_compare."
    tasks = [{"lane": ln.key, "task": task, "cwd": cwd} for ln in use]
    run_id, results = await batch_run(tasks, run_lane=run_lane, resolve_lane=resolve_lane,
                                      default_lane=use[0], telemetry=telemetry, run_id=run_id,
                                      progress=progress)
    if judge_lane:
        jl = resolve_lane(judge_lane)
        if jl:
            return await _judge(jl, run_lane, results,
                                "These are alternative solutions to the SAME task. Compare them, "
                                "note key differences and trade-offs, and recommend ONE to adopt "
                                "(or a specific merge), with reasons.")
    return _compare(results, task)


# ── jury: cross-vendor verification with author≠reviewer-FAMILY (the product) ───────────────────

def _vote(text: str) -> str:
    """pass | fail | abstain — last VERDICT line wins; absent => abstain (never counts as a pass:
    fail-closed, so a malformed/empty review can't approve)."""
    hits = re.findall(r"VERDICT:\s*(PASS|FAIL|ABSTAIN)", text or "", re.IGNORECASE)
    return hits[-1].lower() if hits else "abstain"


def _cross_family_verifiers(default_lanes, author, n: int):
    fam = lanes.family_of(author)
    pool = [ln for ln in default_lanes if lanes.family_of(ln) != fam]
    return pool[:n] if n > 0 else pool


def _jury_vote_prompt(task: str, answer: str) -> str:
    return ("You are a juror reviewing ANOTHER model's answer — you did NOT write it. Judge it "
            f"rigorously for correctness and completeness.\n\nTASK:\n{task}\n\nANSWER TO JUDGE:\n"
            f"{answer}\n\nList any concrete problems, then end with EXACTLY one line: "
            "`VERDICT: PASS` (correct + complete), `VERDICT: FAIL` (wrong or incomplete), or "
            "`VERDICT: ABSTAIN` (cannot tell). Default to ABSTAIN if unsure.")


def _render_jury(author, answer, votes, verdict, passes, fails, k, n, agreement, degraded) -> str:
    head = [f"# jury — {verdict}  ({passes}/{n} PASS, threshold {k}; agreement {agreement})",
            f"_author: {author.display} · verifiers: "
            f"{', '.join(v['lane'] + '(' + v['family'] + ')' for v in votes)}_"]
    if degraded:
        head.append("> ⚠️ DEGRADED: no cross-family verifier available (mono-family pool) — voted by "
                    "same-family lanes, so blind spots may be correlated. Add a different-vendor CLI.")
    lines = head + ["", "## Answer (author)", "", answer or "_(empty)_", "", "## Verdicts", ""]
    for v in votes:
        mark = {"pass": "✅ PASS", "fail": "❌ FAIL", "abstain": "➖ ABSTAIN"}[v["vote"]]
        lines.append(f"### {mark} — {v['lane']} ({v['family']})\n\n{v['review'] or '_(no review)_'}\n")
    return "\n".join(lines)


async def jury(*, run_lane, resolve_lane, default_lanes, telemetry, task: str, author_lane: str = "",
               verifier_lanes=None, verifiers: int = 0, threshold: int = 0, cwd: str = "",
               run_id: str = "", progress=None) -> str:
    """Author produces -> N verifiers from DIFFERENT vendor families vote PASS/FAIL/ABSTAIN ->
    k-of-N (fail-closed). Cross-vendor is the point: a model can't review its own family's blind
    spots. Mono-family pool degrades (same-family vote + a warning), never an undefined verdict."""
    author = resolve_lane(author_lane) if author_lane else (default_lanes[0] if default_lanes else None)
    if author is None:
        return "[error] no author lane available for jury."
    degraded = False
    if verifier_lanes:
        panel = [ln for ln in (resolve_lane(k) for k in verifier_lanes)
                 if ln is not None and ln.key != author.key]
    else:
        want = verifiers if verifiers > 0 else min(3, max(0, len(default_lanes) - 1))
        panel = _cross_family_verifiers(default_lanes, author, want)
        if not panel:                              # mono-family pool: degrade, never undefined
            panel = [ln for ln in default_lanes if ln.key != author.key][:max(1, want)]
            degraded = True
    if not panel:
        return ("[error] jury needs at least one verifier lane distinct from the author — install/"
                "login a second CLI or pass verifier_lanes.")
    sub = {"cwd": cwd} if cwd else {}
    ar = await run_lane(author, {**sub, "task": task}, tool="jury")
    if not ar.ok:
        return f"# jury — author {author.display} FAILED ({ar.kind})\n\n{ar.render()}"
    answer = ar.output.strip()
    vtasks = [{"lane": v.key, "cwd": cwd, "task": _jury_vote_prompt(task, answer)} for v in panel]
    _rid, results = await batch_run(vtasks, run_lane=run_lane, resolve_lane=resolve_lane,
                                    default_lane=panel[0], telemetry=telemetry, run_id=run_id,
                                    progress=progress)
    votes = []
    for v, r in zip(panel, results, strict=False):
        votes.append({"lane": v.key, "family": lanes.family_of(v),
                      "vote": _vote(r["output"]) if r["ok"] else "abstain",
                      "review": r["output"].strip()})
    n = len(votes)
    k = threshold if threshold > 0 else (n // 2 + 1)
    passes = sum(1 for x in votes if x["vote"] == "pass")
    fails = sum(1 for x in votes if x["vote"] == "fail")
    verdict = "APPROVED" if passes >= k else "REJECTED"        # fail-closed: short of k => rejected
    agreement = round(passes / n, 2) if n else 0.0
    return _render_jury(author, answer, votes, verdict, passes, fails, k, n, agreement, degraded)
