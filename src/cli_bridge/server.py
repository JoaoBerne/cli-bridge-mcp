"""cli-bridge — let your AI assistant consult a council of other AI CLIs.

Low-level MCP server so we can filter tools per client at list time:
- only lanes whose CLI is installed are exposed,
- the *calling* client's own lane is shown as a normal tool but kept out of fan-out
  (CLI_BRIDGE_HIDE_HOST=1 hides it entirely, sibling-model-consult only),
detected from the MCP `clientInfo.name` (with a CLI_BRIDGE_HOST env override).

Every lane spawns the official CLI as a subprocess — no token extraction, no API keys,
so accounts can't get flagged for ToS-breaking token reuse. Read-only by default.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from typing import cast

from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    GetPromptResult,
    Prompt,
    PromptArgument,
    PromptMessage,
    Resource,
    TextContent,
    Tool,
    ToolAnnotations,
)

from . import (
    budget,
    buildloop,
    config,
    conversations,
    council,
    findings,
    guards,
    jobs,
    orchestrate,
    preamble,
    router,
    runner,
    telemetry,
    workflows,
    worktrees,
)
from . import (
    lanes as lanes_mod,
)
from .config import (
    ASK_ALL_DEFAULT_TIMEOUT_S,
    ASK_ALL_MAX_TIMEOUT_S,
    DEFAULT_TIMEOUT_S,
    INLINE_MAX_CHARS,
    INSTRUCTIONS,
    MAX_TIMEOUT_S,
    OVERFLOW_DIR,
    SETUP_TEXT,
)
from .detect import installed_lanes, is_installed
from .lanes import LaneSpec, all_lanes

# config.py is the single source of truth for env/timeouts/profile/onboarding. These thin
# aliases keep the historical server.* call sites (and tests) working after the extraction.
_int_env = config.int_env
_profile = config.profile
_profile_is_set = config.profile_is_set
_cost_config_is_set = config.cost_config_is_set
# How long a spilled overflow file is kept before best-effort pruning (P0-4).
OVERFLOW_TTL_H = config.int_env("CLI_BRIDGE_OVERFLOW_TTL_H", 24, 0, 24 * 365)


server: Server = Server("cli-bridge", instructions=INSTRUCTIONS)


_OVERFLOW_MAX_FILES = config.int_env("CLI_BRIDGE_OVERFLOW_MAX_FILES", 200, 0, 100_000)


def _prune_overflow() -> None:
    """Best-effort: drop overflow files older than OVERFLOW_TTL_H, and cap the file COUNT (keep
    the newest CLI_BRIDGE_OVERFLOW_MAX_FILES, delete the oldest beyond) so the temp dir can't
    grow without bound even within the TTL window. Never raises — overflow is a convenience."""
    try:
        entries = []
        cutoff = time.time() - OVERFLOW_TTL_H * 3600 if OVERFLOW_TTL_H > 0 else None
        for name in os.listdir(OVERFLOW_DIR):
            p = os.path.join(OVERFLOW_DIR, name)
            try:
                if not os.path.isfile(p):
                    continue
                mtime = os.path.getmtime(p)
            except OSError:
                continue
            if cutoff is not None and mtime < cutoff:
                try:
                    os.remove(p)
                except OSError:
                    pass
            else:
                entries.append((mtime, p))
        # count cap: delete oldest beyond the limit
        if _OVERFLOW_MAX_FILES and len(entries) > _OVERFLOW_MAX_FILES:
            entries.sort()                       # oldest first
            for _mtime, p in entries[:len(entries) - _OVERFLOW_MAX_FILES]:
                try:
                    os.remove(p)
                except OSError:
                    pass
    except OSError:
        pass


def _emit(text: str, label: str = "answer", guard: bool = True) -> TextContent:
    """Return small answers inline; spill big ones to a file and return a preview + path.
    This is what makes a delegate behave like a subagent: the host gets a compact digest,
    and the full output stays out of its context until it deliberately reads the file.

    guard=True (the default) runs the injection/tool-poisoning guard over UNTRUSTED delegate
    output first; internal reports (doctor/usage/lane_stats) pass guard=False — they're ours."""
    if guard:
        text = guards.apply(text)
    if len(text) <= INLINE_MAX_CHARS:
        return TextContent(type="text", text=text)
    try:
        os.makedirs(OVERFLOW_DIR, exist_ok=True)
        _prune_overflow()
        digest = hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:10]
        path = os.path.join(OVERFLOW_DIR, f"{label}-{digest}.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        head = text[:INLINE_MAX_CHARS]
        return TextContent(type="text", text=(
            f"{head}\n\n[... {len(text)} chars total — truncated. Full output saved to:\n{path}\n"
            f"Read it selectively (grep / a subagent), not all at once, to keep context lean.]"))
    except OSError:
        # If we can't write the file, fall back to a hard clip rather than flooding context.
        return TextContent(type="text", text=text[:INLINE_MAX_CHARS] + "\n\n[... clipped]")


async def _emit_progress(done: int, total: int, msg: str = "") -> None:
    """Stream an MCP progress notification during a slow fan-out — so the host shows live "3/5
    lanes done" instead of a frozen spinner. No-op when the host sent no progress token, or
    outside a request context (async jobs / human CLI / tests). NEVER raises into a delegation."""
    try:
        ctx = server.request_context
        token = ctx.meta.progressToken if ctx.meta else None
        if token is None:
            return
        await ctx.session.send_progress_notification(
            progress_token=token, progress=done, total=total,
            message=(f"{msg} ({done}/{total})" if msg else f"{done}/{total}"))
    except Exception:
        return


async def _host_sample(prompt: str, max_tokens: int = 1024) -> str | None:
    """Ask the HOST's own model to complete a prompt via MCP 'sampling' — a FREE judge /
    synthesizer: no lane spawned, no API key, no quota burned. Returns the text, or None if the
    host doesn't support sampling or anything goes wrong (the caller then falls back to a lane).
    Never raises. This is cli-bridge's zero-cost edge: reuse the model you're already running."""
    try:
        from mcp.types import SamplingMessage
        from mcp.types import TextContent as _TC
        ctx = server.request_context
        result = await ctx.session.create_message(
            messages=[SamplingMessage(role="user", content=_TC(type="text", text=prompt))],
            max_tokens=max_tokens,
        )
        text = getattr(getattr(result, "content", None), "text", None)
        return text.strip() if isinstance(text, str) and text.strip() else None
    except Exception:
        return None


# ─────────────────────────────── host detection (self-hide) ───────────────────────────────

def _slug(name: str) -> str:
    """Normalize a client name so 'Claude Code', 'claude-code', 'claude_code' all match."""
    return "".join(c if c.isalnum() else "-" for c in (name or "").lower()).strip("-")


def _host_name() -> str:
    """Who is calling us? Env override wins; else the MCP client's declared name (slugged)."""
    forced = os.environ.get("CLI_BRIDGE_HOST", "").strip()
    if forced:
        return _slug(forced)
    try:
        info = server.request_context.session.client_params.clientInfo  # type: ignore[union-attr]
        return _slug(info.name)
    except Exception:
        return ""


def _is_host(lane: LaneSpec, host: str) -> bool:
    return bool(host) and host in {_slug(c) for c in lane.client_ids}


def _active_lanes() -> tuple[list[LaneSpec], str]:
    """Installed lanes minus the caller's own lane — the delegates used for fan-out/cascade.
    (Asking your OWN model the same question wastes a call, so the host lane is excluded here.)"""
    host = _host_name()
    lanes = [ln for ln in installed_lanes(all_lanes()) if not _is_host(ln, host)]
    allow = config.allowed_lanes()                 # optional team/locked-down allowlist
    if allow:
        lanes = [ln for ln in lanes if ln.key in allow]
    return lanes, host


def _host_lane(host: str) -> LaneSpec | None:
    """The caller's OWN installed lane. Visible as a normal ask_<host> tool by default; with
    CLI_BRIDGE_HIDE_HOST=1 it is hidden and only reachable as an explicit-model SIBLING consult.
    Returned separately from the delegates either way, so it never joins a fan-out."""
    if not host:
        return None
    return next((ln for ln in installed_lanes(all_lanes()) if _is_host(ln, host)), None)


# ─────────────────────────────── tool schema construction ───────────────────────────────

def _ask_schema(lane: LaneSpec) -> dict:
    props: dict = {
        "task": {"type": "string", "description": "The prompt/question for the delegate."},
        "cwd": {"type": "string",
                "description": "Directory the CLI runs in (so it sees those files). "
                               "Empty = the host's launch dir."},
        "timeout_s": {"type": "integer",
                      "description": f"Seconds before kill (default {DEFAULT_TIMEOUT_S}, "
                                     f"max {MAX_TIMEOUT_S})."},
        "conversation": {"type": "string",
                         "description": "Round-table thread (multi-turn memory). Omit = "
                         "stateless (default). 'new' = start a thread; the returned id can be "
                         "reused — even on a DIFFERENT lane — to continue. Or pass an existing "
                         "id to keep going. Survives the host's context reset (/compact)."},
    }
    if "model" in lane.caps:
        props["model"] = {"type": "string",
                          "description": "Model override. Empty = the lane's default."
                          + (" Paid 'opencode-go/*' burns credits; empty = free."
                             if lane.key == "opencode" else "")}
    if "effort" in lane.caps:
        props["effort"] = {"type": "string",
                           "enum": ["", "minimal", "low", "medium", "high", "max"],
                           "description": "Reasoning depth. Higher = harder/slower."}
    if "agent" in lane.caps:
        props["agent"] = {"type": "string", "enum": ["plan", "build"],
                          "description": "'plan' (read-only, default) or 'build' (EDITS FILES directly)."}
    props["role"] = {"type": "string",
                     "description": "Optional persona prepended to the task. A name — "
                     + " / ".join(sorted(preamble.roles())) +
                     " (extend via CLI_BRIDGE_ROLES_FILE) — or write a one-sentence persona "
                     "INLINE, tailored to this exact task (dynamic role assignment; an unknown "
                     "single word is ignored as a probable typo)."}
    if lane.key == "gemini":
        props["images"] = {"type": "array", "items": {"type": "string"},
                           "description": "Image file paths to include (vision, ban-safe — passed to "
                           "the Gemini CLI as @-file references). Experimental: verify with your CLI."}
    return {"type": "object", "properties": props, "required": ["task"]}


def _ann(**kw: bool) -> ToolAnnotations:
    """The MCP SDK types Tool(annotations=) as ToolAnnotations|None but accepts a plain dict of
    hints at runtime (pydantic coerces). This wraps the hint kwargs in that cast in ONE place, so
    the ~40 Tool(...) sites stay readable AND mypy keeps flagging REAL arg-type errors elsewhere
    (vs a blanket disable_error_code)."""
    return cast(ToolAnnotations, kw)


def _tools_for(lanes: list[LaneSpec]) -> list[Tool]:
    tools: list[Tool] = []
    for lane in lanes:
        paid = " [paid lane - spends credits/money on your plan]" if lane.is_paid else ""
        limited = " [limited lane - scarce quota; skipped by ask_all unless requested]" \
            if lane.is_limited else ""
        exp = " [experimental: flags not verified live — report breakage]" if lane.experimental else ""
        # A lane that can WRITE (opencode build) must not advertise read-only.
        can_write = "agent" in lane.caps
        tools.append(Tool(
            name=f"ask_{lane.key}",
            description=f"Consult {lane.display}. {lane.note}{paid}{limited}{exp}",
            inputSchema=_ask_schema(lane),
            annotations=_ann(readOnlyHint=not can_write, openWorldHint=True,
                             destructiveHint=can_write),
        ))
        if lane.models_args is not None:
            tools.append(Tool(
                name=f"list_{lane.key}_models",
                description=f"List models reachable through {lane.display}.",
                inputSchema={"type": "object", "properties": {}},
                annotations=_ann(readOnlyHint=True, destructiveHint=False),
            ))
    if lanes:
        tools.append(Tool(
            name="ask_all",
            description=("Fan-out: ask the SAME question to every available lane in parallel and "
                         "get all answers side by side. Free, non-limited lanes only by default."),
            inputSchema={
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "Prompt sent to every lane."},
                    "include_paid": {"type": "boolean",
                                     "description": "Also query limited/paid lanes. Default false, "
                                                    "except CLI_BRIDGE_PROFILE=max."},
                    "cwd": {"type": "string", "description": "Directory the CLIs run in."},
                    "timeout_s": {"type": "integer",
                                  "description": f"Per-lane timeout (max {ASK_ALL_MAX_TIMEOUT_S} — "
                                                 "the fan-out must finish before the host's own "
                                                 "tool deadline; call one lane directly for a "
                                                 "longer run)."},
                    "synthesize": {"type": "boolean",
                                   "description": "After collecting answers, have one free lane "
                                   "summarize where the models AGREE and DISAGREE. Default false."},
                    "summary_only": {"type": "boolean",
                                     "description": "Return only the recap (+synthesis), not each "
                                     "lane's full answer — fewer tokens. Default false."},
                    "output_format": {"type": "string", "enum": ["markdown", "json"],
                                      "description": "markdown (default) or json (structured)."},
                    "dry_run": {"type": "boolean",
                                "description": "Preview which lanes + estimated cost WITHOUT "
                                               "spawning anything. Default false."},
                },
                "required": ["task"],
            },
            annotations=_ann(readOnlyHint=True, openWorldHint=True, destructiveHint=False),
        ))
        tools.append(Tool(
            name="ask_all_async",
            description=("Like ask_all but NON-BLOCKING: starts the fan-out as a background job "
                         "and returns a job_id immediately (in <1s), so a slow council run can't "
                         "hit the MCP host's tool-call deadline. Poll job_status, fetch "
                         "job_result. Same options as ask_all."),
            inputSchema={
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "Prompt sent to every lane."},
                    "include_paid": {"type": "boolean",
                                     "description": "Also query limited/paid lanes. Default false."},
                    "cwd": {"type": "string", "description": "Directory the CLIs run in."},
                    "timeout_s": {"type": "integer",
                                  "description": f"Per-lane timeout (max {ASK_ALL_MAX_TIMEOUT_S})."},
                    "synthesize": {"type": "boolean",
                                   "description": "Add an agree/disagree summary. Default false."},
                },
                "required": ["task"],
            },
            annotations=_ann(readOnlyHint=True, openWorldHint=True, destructiveHint=False),
        ))
        tools.append(Tool(
            name="job_status",
            description="Status of an async job: running | succeeded | failed | cancelled | "
                        "interrupted. Pass the job_id returned by ask_all_async.",
            inputSchema={"type": "object", "properties": {
                "job_id": {"type": "string", "description": "The job id (e.g. job_ab12…)."}},
                "required": ["job_id"]},
            annotations=_ann(readOnlyHint=True, destructiveHint=False),
        ))
        tools.append(Tool(
            name="job_result",
            description="Fetch a finished async job's output (same body as ask_all; spills to a "
                        "file + preview if huge). Returns a 'still running' note if not done.",
            inputSchema={"type": "object", "properties": {
                "job_id": {"type": "string", "description": "The job id."}},
                "required": ["job_id"]},
            annotations=_ann(readOnlyHint=True, destructiveHint=False),
        ))
        tools.append(Tool(
            name="job_cancel",
            description="Cancel a running async job — kills the delegate CLIs' process groups.",
            inputSchema={"type": "object", "properties": {
                "job_id": {"type": "string", "description": "The job id to cancel."}},
                "required": ["job_id"]},
            annotations=_ann(readOnlyHint=False, destructiveHint=False),
        ))
        tools.append(Tool(
            name="jobs_list",
            description="List recent async jobs (this session first, then persisted history) "
                        "with their status.",
            inputSchema={"type": "object", "properties": {}},
            annotations=_ann(readOnlyHint=True, destructiveHint=False),
        ))
        tools.append(Tool(
            name="batch_run",
            description=("Durable fan-out: run many INDEPENDENT asks in parallel (capped) in ONE "
                         "call instead of N — saves your context and quota. Each result is "
                         "journalled, so resume_id replays the tasks that already finished and "
                         "runs only the rest (survives a restart). YOU compose the logic; this "
                         "just executes it durably. async=true returns a job_id (poll job_status, "
                         "fetch job_result)."),
            inputSchema={
                "type": "object",
                "properties": {
                    "tasks": {"type": "array", "description": "Independent tasks to run.",
                              "items": {"type": "object", "properties": {
                                  "task": {"type": "string"},
                                  "lane": {"type": "string", "description": "Lane key (default: a "
                                           "free lane)."},
                                  "model": {"type": "string"},
                                  "effort": {"type": "string"},
                                  "cwd": {"type": "string", "description": "Dir the lane runs in "
                                          "(point it at a file to review instead of pasting it)."},
                                  "timeout_s": {"type": "integer",
                                                "description": f"Per-task timeout (default "
                                                f"{DEFAULT_TIMEOUT_S}, max {MAX_TIMEOUT_S}) — raise "
                                                "for heavy tasks like reading a file + deep review; "
                                                "use async=true for long batches."}},
                                  "required": ["task"]}},
                    "max_concurrency": {"type": "integer",
                                        "description": "Cap simultaneous spawns (default: profile)."},
                    "max_calls": {"type": "integer",
                                  "description": "Invocation budget: stop after this many spawns; "
                                  "the rest are skipped (resume with a higher cap to run them)."},
                    "max_credits": {"type": "number",
                                    "description": "Invocation budget: skip tasks once estimated "
                                    "credits would exceed this (free lanes never blocked)."},
                    "dry_run": {"type": "boolean",
                                "description": "Return the cost envelope (calls + est token/credit "
                                "range) WITHOUT spawning anything."},
                    "resume_id": {"type": "string",
                                  "description": "A run_id from a previous batch — replays finished "
                                  "tasks from cache, runs the rest."},
                    "async": {"type": "boolean", "description": "Run as a background job."},
                },
                "required": ["tasks"],
            },
            annotations=_ann(readOnlyHint=False, openWorldHint=True, destructiveHint=False),
        ))
        tools.append(Tool(
            name="workflow",
            description=("Run a ready-made multi-model workflow (a 'button') over the durable "
                         "batch substrate. refine_plan: let the council DEMOLISH your plan from "
                         "distinct angles (pass plan_file — each lane reads it, no recopy). "
                         "council_review: N lanes answer one question, optional judge synthesises. "
                         "map_review: review many files in parallel. research_verify: answer "
                         "questions then adversarially cross-check them. verify_repair: one lane "
                         "builds, a DIFFERENT model reviews, repair loop until approved (cross-model "
                         "= uncorrelated blind spots). fanout_compare: same task to N lanes, answers "
                         "side by side to pick/merge. All resumable (resume_id) and async-able."),
            inputSchema={
                "type": "object",
                "properties": {
                    "preset": {"type": "string",
                               "enum": ["refine_plan", "council_review", "map_review",
                                        "research_verify", "verify_repair", "fanout_compare",
                                        "jury"],
                               "description": "Which workflow to run."},
                    "plan_file": {"type": "string",
                                  "description": "refine_plan: path to the plan (PREFERRED — read "
                                  "by each lane, never recopied)."},
                    "plan": {"type": "string", "description": "refine_plan: inline plan (fallback)."},
                    "angles": {"type": "array", "items": {"type": "string"},
                               "description": "refine_plan: override the critique angles."},
                    "question": {"type": "string", "description": "council_review: the question."},
                    "task": {"type": "string",
                             "description": "verify_repair / fanout_compare: the task to run."},
                    "files": {"type": "array", "items": {"type": "string"},
                              "description": "map_review: file paths to review."},
                    "questions": {"type": "array", "items": {"type": "string"},
                                  "description": "research_verify: questions to answer + verify."},
                    "lanes": {"type": "array", "items": {"type": "string"},
                              "description": "Lane keys to use (default: the free council). "
                                             "fanout_compare also accepts 'lane:model' entries "
                                             "(model = the FULL id the CLI expects) — e.g. "
                                             "['opencode:opencode/deepseek-v4-flash-free', "
                                             "'opencode:opencode/mimo-v2.5-free'] compares several "
                                             "models of ONE lane side by side."},
                    "lane": {"type": "string", "description": "map_review: the single reviewer lane."},
                    "builder_lane": {"type": "string",
                                     "description": "verify_repair: lane that produces (default: "
                                     "first council lane)."},
                    "verifier_lane": {"type": "string",
                                      "description": "verify_repair: a DIFFERENT lane that reviews "
                                      "(default: first other council lane)."},
                    "max_rounds": {"type": "integer",
                                   "description": "verify_repair: build->verify->repair rounds "
                                   f"(default 3, max {orchestrate.VERIFY_MAX_ROUNDS})."},
                    "cross_family": {"type": "boolean",
                                     "description": "verify_repair: pick the verifier from a "
                                     "DIFFERENT vendor family (default false)."},
                    "author_lane": {"type": "string",
                                    "description": "jury: lane that produces the answer (default: "
                                    "first council lane)."},
                    "verifier_lanes": {"type": "array", "items": {"type": "string"},
                                       "description": "jury: explicit verifier lanes (default: "
                                       "auto-picked from DIFFERENT vendor families than the author)."},
                    "verifiers": {"type": "integer",
                                  "description": "jury: how many verifiers (default min(3, pool))."},
                    "threshold": {"type": "integer",
                                  "description": "jury: PASS votes needed to APPROVE (default "
                                  "majority); short of it = REJECTED, fail-closed."},
                    "cwd": {"type": "string",
                            "description": "verify_repair / fanout_compare: dir the lanes run in."},
                    "judge_lane": {"type": "string",
                                   "description": "Optional: one lane dedupes + ranks the pooled "
                                   "findings into a single list (else grouped for you to merge). "
                                   "fanout_compare: recommends one option."},
                    "include_paid": {"type": "boolean",
                                     "description": "Allow limited/paid lanes in the default set."},
                    "resume_id": {"type": "string", "description": "Resume a previous run."},
                    "async": {"type": "boolean", "description": "Run as a background job."},
                },
                "required": ["preset"],
            },
            annotations=_ann(readOnlyHint=False, openWorldHint=True, destructiveHint=False),
        ))
        tools.append(Tool(
            name="conversations_list",
            description="List recent round-table threads (id, lanes involved, turn count, last "
                        "activity, preview). Use it to recover a conversation id and continue a "
                        "thread after a context reset.",
            inputSchema={"type": "object", "properties": {}},
            annotations=_ann(readOnlyHint=True, destructiveHint=False),
        ))
        tools.append(Tool(
            name="conversation_show",
            description="Show the full transcript of one round-table thread — every turn, "
                        "attributed by lane. Pass the conversation id.",
            inputSchema={"type": "object", "properties": {
                "conversation": {"type": "string", "description": "The thread id."}},
                "required": ["conversation"]},
            annotations=_ann(readOnlyHint=True, destructiveHint=False),
        ))
        tools.append(Tool(
            name="list_models",
            description="List the models reachable through a lane so you can pick one. If that "
                        "CLI has no list command, shows its default model + how to choose. Pass "
                        "`lane` (e.g. opencode, mistral, gpt).",
            inputSchema={"type": "object", "properties": {
                "lane": {"type": "string", "description": "Lane key to inspect."}},
                "required": ["lane"]},
            annotations=_ann(readOnlyHint=True, destructiveHint=False),
        ))
    tools.append(Tool(
        name="doctor",
        description="Health check: which CLIs are installed, which is the host, paid lanes, "
                    "defaults, current cost profile. Pass deep=true to also probe each lane with a "
                    "tiny live call (checks auth/quota — uses a bit of free quota; skips paid lanes).",
        inputSchema={"type": "object", "properties": {
            "deep": {"type": "boolean", "description": "Live-probe each free lane's auth."}}},
        annotations=_ann(readOnlyHint=True, destructiveHint=False),
    ))
    tools.append(Tool(
        name="setup",
        description="Show the cost-profile choice (saver/balanced/max) to walk the user through "
                    "configuring how cli-bridge spends paid credits/quota. Call this on first use "
                    "if the profile isn't set, ASK the user, then tell them how to set it.",
        inputSchema={"type": "object", "properties": {}},
        annotations=_ann(readOnlyHint=True, destructiveHint=False),
    ))
    tools.append(Tool(
        name="usage_report",
        description="Local usage stats (this machine only): total runs, per-lane counts/success/"
                    "avg latency, ESTIMATED tokens (chars/4) and credits (if CLI_BRIDGE_<LANE>_"
                    "CREDITS_PER_1K is set), and recent calls. All token/credit figures are "
                    "estimates, never exact.",
        inputSchema={"type": "object", "properties": {
            "since": {"type": "string",
                      "description": "Limit to a recent window, e.g. '24h', '7d', '90m' (default: all)."},
            "output_format": {"type": "string", "enum": ["text", "json"],
                              "description": "text (default) or json."}}},
        annotations=_ann(readOnlyHint=True, destructiveHint=False),
    ))
    tools.append(Tool(
        name="usage_budget",
        description="Per-lane runs since UTC midnight vs an optional CLI_BRIDGE_<LANE>_DAILY_LIMIT "
                    "(ENFORCED at spawn once reached), plus estimated tokens/credits spent today. "
                    "Estimates only.",
        inputSchema={"type": "object", "properties": {}},
        annotations=_ann(readOnlyHint=True, destructiveHint=False),
    ))
    tools.append(Tool(
        name="lane_stats",
        description="Per-lane health: total runs, failures, consecutive failures/timeouts, and "
                    "any active cooldown (a lane in cooldown is skipped by ask_all until it clears).",
        inputSchema={"type": "object", "properties": {}},
        annotations=_ann(readOnlyHint=True, destructiveHint=False),
    ))
    tools.append(Tool(
        name="reset_lane_state",
        description="Clear a lane's cooldown + failure counters (e.g. after you re-logged in or "
                    "your quota reset). Pass the lane key, e.g. 'gemini'.",
        inputSchema={"type": "object", "properties": {
            "lane": {"type": "string", "description": "Lane key to reset (e.g. gemini, gpt)."}},
            "required": ["lane"]},
        annotations=_ann(readOnlyHint=False, destructiveHint=False),
    ))
    if lanes:
        tools.append(Tool(
            name="ask_cascade",
            description="Ask ONE model but with automatic fallback: tries lanes cheapest→strongest, "
                        "skipping cooled ones, and moves to the next on quota/auth/timeout/failure. "
                        "Returns the first success (and a note of what was tried). Use this for plain "
                        "cheapest-first; use `ask_best` to route by mode/your ratings, `route_plan` to "
                        "preview the order without running. Free/non-limited by default; include_paid "
                        "to widen.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "The prompt."},
                    "include_paid": {"type": "boolean",
                                     "description": "Allow limited/paid lanes in the chain. "
                                                    "Default false (except CLI_BRIDGE_PROFILE=max)."},
                    "cwd": {"type": "string", "description": "Directory the CLI runs in."},
                    "timeout_s": {"type": "integer",
                                  "description": f"Per-attempt timeout (max {MAX_TIMEOUT_S})."},
                    "escalate": {"type": "boolean",
                                 "description": "Confidence-escalate: a cheap lane that self-reports "
                                 "low confidence ([ESCALATE]) hands off to a stronger one, not just "
                                 "on failure. Self-report is noisy — opt-in. Default false."},
                },
                "required": ["task"],
            },
            annotations=_ann(readOnlyHint=True, openWorldHint=True, destructiveHint=False),
        ))
        tools.append(Tool(
            name="route_plan",
            description="Explain (without running anything) the order ask_cascade would try lanes "
                        "in, given current cost profile and lane cooldowns. Pass a `mode` to "
                        "preview ask_best's order instead.",
            inputSchema={"type": "object", "properties": {
                "include_paid": {"type": "boolean", "description": "Include limited/paid lanes."},
                "mode": {"type": "string", "enum": list(router.MODES),
                         "description": "Preview ask_best's ordering for this mode."}}},
            annotations=_ann(readOnlyHint=True, destructiveHint=False),
        ))
        tools.append(Tool(
            name="ask_best",
            description=("Ask the BEST lane for the job: pick one lane by `mode` (fast/cheap/deep/"
                         "code/review/security) using cost, health and measured latency, then run "
                         "it with automatic fallback. Use this when you don't want to choose a "
                         "lane yourself. (Use ask_all to COMPARE many; ask_cascade for plain "
                         "cheapest-first reliability.)"),
            inputSchema={
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "The prompt."},
                    "mode": {"type": "string", "enum": list(router.MODES),
                             "description": "fast=low latency · cheap=free only (default) · "
                                            "deep/code=stronger lanes · review/security=capable "
                                            "lane. paid lanes only if include_paid/profile allows."},
                    "include_paid": {"type": "boolean",
                                     "description": "Allow limited/paid lanes. Default false "
                                                    "(except CLI_BRIDGE_PROFILE=max)."},
                    "cwd": {"type": "string", "description": "Directory the CLI runs in."},
                    "timeout_s": {"type": "integer",
                                  "description": f"Per-attempt timeout (max {MAX_TIMEOUT_S})."},
                },
                "required": ["task"],
            },
            annotations=_ann(readOnlyHint=True, openWorldHint=True, destructiveHint=False),
        ))
        tools.append(Tool(
            name="rate_lane",
            description=("Teach the router. Score how good a lane's answer was for a task-type "
                         "(mode) and `ask_best` will prefer the lanes that score well for that mode "
                         "ON THIS MACHINE — a local, personalized quality signal that outlives the "
                         "session (stored in sqlite, survives /compact and restart). Call it after "
                         "you've judged or acted on a delegate's answer; the ask_best trace shows "
                         "the exact call."),
            inputSchema={
                "type": "object",
                "properties": {
                    "lane": {"type": "string",
                             "description": "Lane key that answered (e.g. gemini, gpt, mistral)."},
                    "score": {"type": "integer",
                              "description": "Quality 1 (poor) .. 5 (excellent)."},
                    "mode": {"type": "string", "enum": list(router.MODES),
                             "description": "Task-type this score is for — match the ask_best mode "
                                            "(fast/cheap/deep/code/review/security). Omit for a "
                                            "general score not tied to a mode."},
                    "note": {"type": "string",
                             "description": "Optional short reason, stored locally (≤200 chars)."},
                },
                "required": ["lane", "score"],
            },
            annotations=_ann(readOnlyHint=False, destructiveHint=False, openWorldHint=False),
        ))
        tools.append(Tool(
            name="set_lane_cost",
            description=("Teach the cost policy — the counterpart of rate_lane for money. When the "
                         "user tells you what a lane really costs THEM ('my opencode is on the Go "
                         "plan', 'I have Codex free with ChatGPT') or you KNOW a vendor changed a "
                         "tier (a free tier died, a plan launched), record it here: it takes effect "
                         "immediately and persists to the config file, so cli-bridge's cost policy "
                         "evolves with zero maintenance instead of waiting for a code update."),
            inputSchema={
                "type": "object",
                "properties": {
                    "lane": {"type": "string",
                             "description": "Lane key (e.g. gemini, gpt, opencode)."},
                    "cost": {"type": "string", "enum": ["free", "limited", "paid"],
                             "description": "What this lane costs the USER: free=use freely; "
                                            "limited=scarce quota (skip broad fan-out); "
                                            "paid=money/credits."},
                    "note": {"type": "string",
                             "description": "REQUIRED one-line provenance/WHY (shown by doctor) "
                                            "— e.g. 'user: has the Go plan' or 'vendor: free "
                                            "tier sunset 2026-06-18'. ≤200 chars. Required so a "
                                            "delegate's output can't quietly rewrite the cost "
                                            "policy without a stated why."},
                },
                "required": ["lane", "cost", "note"],
            },
            annotations=_ann(readOnlyHint=False, destructiveHint=False, openWorldHint=False),
        ))
        tools.append(Tool(
            name="review_diff",
            description=("Multi-model code review of a git diff: several lanes review in parallel "
                         "with DIFFERENT focuses (correctness/security/tests/maintainability), "
                         "then one lane merges + dedupes into a ranked Markdown report. "
                         "Reviews working-tree changes by default. Free/non-limited lanes only "
                         "unless include_paid. A deliberately longer call than ask_all."),
            inputSchema={
                "type": "object",
                "properties": {
                    "cwd": {"type": "string",
                            "description": "Repo dir to run `git diff` in (default: host launch dir)."},
                    "base": {"type": "string",
                             "description": "git ref/range to diff against. Default HEAD "
                                            "(uncommitted changes). E.g. 'main', 'HEAD~3', 'main...HEAD'."},
                    "diff": {"type": "string",
                             "description": "Review this diff text directly instead of running git."},
                    "include_paid": {"type": "boolean",
                                     "description": "Allow limited/paid lanes as reviewers. "
                                                    "Default false (except CLI_BRIDGE_PROFILE=max)."},
                    "output_format": {"type": "string", "enum": ["markdown", "json"],
                                      "description": "markdown (default, PR-friendly) or json "
                                                     "(structured findings)."},
                    "severity_filter": {"type": "string", "enum": list(findings.SEVERITIES),
                                        "description": "Only show findings at or above this "
                                        "severity (blocker>high>medium>low>info). Default: all."},
                    "timeout_s": {"type": "integer",
                                  "description": f"Per-reviewer timeout (max {MAX_TIMEOUT_S}, "
                                                 f"default {config.REVIEW_DEFAULT_TIMEOUT_S})."},
                },
                "required": [],
            },
            annotations=_ann(readOnlyHint=True, openWorldHint=True, destructiveHint=False),
        ))
        tools.append(Tool(
            name="security_review",
            description=("OWASP-aware SECURITY review of a git diff: lanes review in parallel "
                         "across security categories (injection / auth & access control / "
                         "secrets & crypto / data exposure & SSRF), then merge into a severity-"
                         "ranked report. Deeper than review_diff's single security lens. "
                         "Free/non-limited lanes unless include_paid."),
            inputSchema={
                "type": "object",
                "properties": {
                    "cwd": {"type": "string", "description": "Repo dir to run `git diff` in."},
                    "base": {"type": "string", "description": "git ref/range. Default HEAD."},
                    "diff": {"type": "string", "description": "Review this diff text directly."},
                    "include_paid": {"type": "boolean", "description": "Allow limited/paid lanes."},
                    "output_format": {"type": "string", "enum": ["markdown", "json"],
                                      "description": "markdown (default) or json."},
                    "severity_filter": {"type": "string", "enum": list(findings.SEVERITIES),
                                        "description": "Only show findings at or above this "
                                        "severity (blocker>high>medium>low>info). Default: all."},
                    "timeout_s": {"type": "integer",
                                  "description": f"Per-reviewer timeout (max {MAX_TIMEOUT_S})."},
                },
                "required": [],
            },
            annotations=_ann(readOnlyHint=True, openWorldHint=True, destructiveHint=False),
        ))
        build_lanes = [ln for ln in lanes if "agent" in ln.caps]
        if build_lanes:
            tools.append(Tool(
                name="ask_build",
                description=("DELEGATE real implementation work to another model — a second pair "
                             "of hands, not just advice. REACH FOR THIS (instead of editing "
                             "everything yourself) when a task is well-scoped enough to brief — a "
                             "bug fix, a refactor, a new module, a greenfield scaffold — and you "
                             "want a reviewable result while you keep working, a cheaper model to "
                             "do the mechanical part, or an implementation you'll compare against "
                             "your own. Write the brief like a good ticket: files, constraints, "
                             "tests to run. mode=isolated (default) edits a throwaway worktree and "
                             "returns a DIFF to review then apply (git apply) — your repo is "
                             "untouched. mode=direct builds straight into a target dir, guarded by "
                             "git + a ZONE contract: the delegate may write only inside `zone`, "
                             "all undo is zone-scoped (never a global reset), a per-zone lock "
                             "stops races, and any file written OUTSIDE the zone is detected and "
                             "the build rejected — so the host can build other parts of the SAME "
                             "repo in parallel. async=true makes direct builds steerable mid-run "
                             "(job_tail / build_steer / DoD gate). Greenfield dirs are created "
                             "and git-initialised."),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "task": {"type": "string", "description": "What the agent should build."},
                        "lane": {"type": "string", "enum": [ln.key for ln in build_lanes],
                                 "description": "The build-capable lane that does the work "
                                 "(empty = the first free build-capable lane, router order)."},
                        "apply": {"type": "boolean",
                                  "description": "isolated: apply the resulting diff to YOUR repo "
                                  "as unstaged changes (git apply --check first — a conflict "
                                  "applies NOTHING). Default false: review the diff yourself."},
                        "mode": {"type": "string", "enum": ["isolated", "direct"],
                                 "description": "isolated (default, safe diff) or direct (writes "
                                 "real files in the zone)."},
                        "target_dir": {"type": "string",
                                       "description": "direct: dir to build in (created if absent; "
                                       "default = host launch dir)."},
                        "zone": {"type": "string",
                                 "description": "direct: the ONLY sub-path under target_dir the "
                                 "delegate may write (default = the whole target_dir). Set this to "
                                 "build in parallel with other in-repo work, e.g. 'frontend'."},
                        "interface": {"type": "string",
                                      "description": "direct: optional interface contract to put in "
                                      "the brief (e.g. the API shape the delegate must target)."},
                        "dod": {"type": "string",
                                "description": "direct: optional textual Definition of Done for the "
                                "brief (an executable DoD is a Phase-3 feature)."},
                        "scaffold_git": {"type": "boolean",
                                         "description": "direct: git-init a non-repo target (default "
                                         "true). false on a non-repo is refused (no safety net)."},
                        "confirm_dirty": {"type": "boolean",
                                          "description": "direct: build even if the zone has "
                                          "uncommitted tracked changes (default false)."},
                        "async": {"type": "boolean",
                                  "description": "direct: run as a STEERABLE background job — "
                                  "returns a job_id; follow with job_tail, steer with build_steer "
                                  "(and interrupt), fetch with job_result. Enables multi-turn + DoD."},
                        "dry_run": {"type": "boolean",
                                    "description": "direct: render the composed brief and stop — "
                                    "nothing is launched (review the spec before you send it)."},
                        "dod_cmd": {"type": "array", "items": {"type": "string"},
                                    "description": "direct+async: executable Definition of Done as "
                                    "an argv list (e.g. [\"npm\",\"run\",\"build\"]) — NEVER a shell "
                                    "string. Runs after each turn; pass = done, fail = one more turn "
                                    "with the error fed back. The zone is exposed as $ZONE."},
                        "max_turns": {"type": "integer",
                                      "description": "direct+async: hard cap on total turns "
                                      "(default 12)."},
                        "max_fail_retries": {"type": "integer",
                                             "description": "direct+async: stop after this many "
                                             "CONSECUTIVE DoD failures (default 3)."},
                        "architect_lane": {"type": "string", "enum": [ln.key for ln in lanes],
                                           "description": "isolated only: a (usually stronger) lane "
                                           "that first writes a PLAN the editor implements."},
                        "model": {"type": "string", "description": "Model override (empty = default)."},
                        "effort": {"type": "string",
                                   "enum": ["", "minimal", "low", "medium", "high", "max"],
                                   "description": "Reasoning depth."},
                        "cwd": {"type": "string",
                                "description": "isolated: a dir inside the repo to isolate (default: "
                                               "host launch dir)."},
                        "timeout_s": {"type": "integer",
                                      "description": f"Timeout (max {MAX_TIMEOUT_S})."},
                    },
                    "required": ["task"],
                },
                annotations=_ann(readOnlyHint=False, openWorldHint=True,
                                 destructiveHint=True),   # direct mode writes the real repo
            ))
            tools.append(Tool(
                name="ask_build_isolated",
                description=("[legacy alias of ask_build mode=isolated] Run a build-capable lane in "
                             "WRITE mode but SAFELY: it edits a "
                             "throwaway git worktree checked out at HEAD, and you get the "
                             "resulting diff to review — your real repo is never modified "
                             "(nothing is auto-applied). The recommended way to use write mode."),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "task": {"type": "string", "description": "What the agent should build/edit."},
                        "lane": {"type": "string", "enum": [ln.key for ln in build_lanes],
                                 "description": "The build-capable lane that EDITS the worktree "
                                 "(the editor). Pick a cheaper lane here when using architect_lane."},
                        "architect_lane": {"type": "string", "enum": [ln.key for ln in lanes],
                                           "description": "Optional: a (usually stronger) lane that "
                                           "first writes a precise PLAN, which the editor lane then "
                                           "implements (Aider-style architect/editor split — strong "
                                           "model plans, cheaper model applies). Needs no write mode."},
                        "model": {"type": "string", "description": "Model override (empty = default)."},
                        "effort": {"type": "string",
                                   "enum": ["", "minimal", "low", "medium", "high", "max"],
                                   "description": "Reasoning depth."},
                        "cwd": {"type": "string",
                                "description": "A dir inside the git repo to isolate (default: "
                                               "host launch dir)."},
                        "timeout_s": {"type": "integer",
                                      "description": f"Timeout (max {MAX_TIMEOUT_S})."},
                    },
                    "required": ["task", "lane"],
                },
                annotations=_ann(readOnlyHint=False, openWorldHint=True,
                                 destructiveHint=False),   # edits are isolated + discarded
            ))
            tools.append(Tool(
                name="job_tail",
                description=("Stream a running build's progress log (turn markers, agent output, "
                             "DoD results, steering applied). Pass the job_id from ask_build "
                             "async=true, plus the byte offset returned last time (0 to start). "
                             "Returns the new offset + the new text — poll it to follow live and "
                             "write step summaries for the user."),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "job_id": {"type": "string", "description": "The build job id."},
                        "offset": {"type": "integer",
                                   "description": "Byte offset to read from (0 first; then pass the "
                                   "offset returned previously)."},
                    },
                    "required": ["job_id"],
                },
                annotations=_ann(readOnlyHint=True, openWorldHint=False, destructiveHint=False),
            ))
            tools.append(Tool(
                name="build_steer",
                description=("Steer a running build like a human would. Queue an instruction for "
                             "the NEXT turn (e.g. 'use Tailwind, not inline CSS'), and/or "
                             "interrupt=true to cut the CURRENT turn short (the delegate's process "
                             "is killed; files written so far are KEPT). The build then continues, "
                             "applying your steering. Pass the job_id from ask_build async=true."),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "job_id": {"type": "string", "description": "The build job id."},
                        "instruction": {"type": "string",
                                        "description": "What to change/do next (optional if only "
                                        "interrupting)."},
                        "interrupt": {"type": "boolean",
                                      "description": "Cut the current turn now (default false). "
                                      "Files already written are kept."},
                    },
                    "required": ["job_id"],
                },
                annotations=_ann(readOnlyHint=False, openWorldHint=True, destructiveHint=False),
            ))
        tools.append(Tool(
            name="debate",
            description=("Multi-model debate: each lane answers the question, then sees the "
                         "others and REVISES over a bounded number of rounds, then a judge "
                         "writes the final conclusion (consensus + remaining disagreement). "
                         "Good for hard/contested questions. Free/non-limited lanes unless "
                         "include_paid; bounded to a few debaters to cap cost."),
            inputSchema={
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "The question to debate."},
                    "rounds": {"type": "integer",
                               "description": "Revision rounds after the opening answers "
                                              "(default 1, max 3)."},
                    "adversarial": {"type": "boolean",
                                    "description": "Assign for/against/neutral stances to the "
                                    "openings (sharper disagreement). Default false."},
                    "context_files": {"type": "array", "items": {"type": "string"},
                                      "description": "Up to 5 key file paths the tool reads into "
                                      "every debater prompt (the grounding contract — without "
                                      "this the council only paraphrases your brief). Relative "
                                      "paths resolve against cwd."},
                    "allow_ungrounded": {"type": "boolean",
                                         "description": "If the brief names local files you didn't "
                                         "pass as context_files, the tool stops and asks for them "
                                         "(files_required_to_continue). Set true to debate anyway "
                                         "without reading the code. Default false."},
                    "fact_check": {"type": "boolean",
                                   "description": "Post-judge pass: a free lane extracts the "
                                   "verdict's verifiable claims (commands, model tags, versions) "
                                   "and flags what it cannot confirm. Default ON when a free "
                                   "lane exists; false to skip."},
                    "summary_only": {"type": "boolean",
                                     "description": "Return verdict + disagreements + fact-check "
                                     "only; drop the full per-debater positions (~60-80% fewer "
                                     "tokens)."},
                    "allow_self_judge": {"type": "boolean",
                                         "description": "Let the judge also debate (default: "
                                         "with 3+ lanes one lane is held out to judge "
                                         "independently)."},
                    "steelman": {"type": "boolean",
                                 "description": "If the verdict is unanimous, one lane argues "
                                 "the strongest case AGAINST it and the judge re-concludes "
                                 "(anti-echo-chamber bonus round). Default false."},
                    "dry_run": {"type": "boolean",
                                "description": "Preflight: return a data manifest — which vendors "
                                "would be queried and exactly which files/chars would be sent — "
                                "WITHOUT spawning anything. Default false."},
                    "include_paid": {"type": "boolean", "description": "Allow limited/paid lanes."},
                    "cwd": {"type": "string", "description": "Directory the CLIs run in."},
                    "timeout_s": {"type": "integer",
                                  "description": f"Per-turn timeout (max {MAX_TIMEOUT_S})."},
                },
                "required": ["task"],
            },
            annotations=_ann(readOnlyHint=True, openWorldHint=True, destructiveHint=False),
        ))
        tools.append(Tool(
            name="consensus",
            description=("Council CONSENSUS: every lane answers blind, then each RANKS the "
                         "ANONYMIZED answers (no model can favour its own), the votes are "
                         "aggregated deterministically (Borda count), and the peer-ranked #1 "
                         "answer is returned (SELECTION — research shows it beats blending). "
                         "Use it for 'what's the right answer?' when you want a peer-vetted "
                         "result. Vs `ask_all` (shows every answer) / `fanout_compare` (options side "
                         "by side) / `debate` (multi-round argue). Free/non-limited unless include_paid."),
            inputSchema={
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "The question to resolve."},
                    "context_files": {"type": "array", "items": {"type": "string"},
                                      "description": "Up to 5 key file paths read into every "
                                      "panelist prompt (grounding). Relative paths resolve "
                                      "against cwd."},
                    "allow_ungrounded": {"type": "boolean",
                                         "description": "If the brief names local files you didn't "
                                         "pass as context_files, the tool stops and asks for them "
                                         "(files_required_to_continue). Set true to proceed without "
                                         "reading the code. Default false."},
                    "synthesize": {"type": "boolean",
                                   "description": "Have a chairman BLEND the answers instead of "
                                   "returning the peer-ranked best one verbatim. Default false: "
                                   "synthesis empirically loses to selection (it averages away "
                                   "the variance that makes a council useful)."},
                    "summary_only": {"type": "boolean",
                                     "description": "Return the final answer + vote table only; "
                                     "drop the full per-model answers."},
                    "dry_run": {"type": "boolean",
                                "description": "Preflight data manifest (vendors + files/chars "
                                "that would be sent) without spawning anything. Default false."},
                    "include_paid": {"type": "boolean", "description": "Allow limited/paid lanes."},
                    "cwd": {"type": "string", "description": "Directory the CLIs run in."},
                    "timeout_s": {"type": "integer",
                                  "description": f"Per-call timeout (max {MAX_TIMEOUT_S})."},
                },
                "required": ["task"],
            },
            annotations=_ann(readOnlyHint=True, openWorldHint=True, destructiveHint=False),
        ))
        tools.append(Tool(
            name="challenge",
            description=("Anti-sycophancy: hand a CLAIM to one OUTSIDE lane with a critical-"
                         "reassessment prompt and get its skeptical review — does it actually "
                         "hold up? Pressure-test your OWN conclusion before acting (an "
                         "independent skeptic, not a yes-man). Vs `debate` (multi-round, many "
                         "lanes) / `consensus` (pick best of N): challenge = ONE skeptic on one "
                         "claim. Optional `lane` to choose who."),
            inputSchema={
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "The claim/conclusion to challenge."},
                    "lane": {"type": "string",
                             "description": "Which lane plays skeptic (default: a free one)."},
                    "timeout_s": {"type": "integer",
                                  "description": f"Timeout (max {MAX_TIMEOUT_S})."},
                },
                "required": ["task"],
            },
            annotations=_ann(readOnlyHint=True, openWorldHint=True, destructiveHint=False),
        ))
        tools.append(Tool(
            name="premortem",
            description=("Multi-model PREMORTEM: each lane imagines the change/plan failed and "
                         "lists likely failure modes, root causes, early signs and mitigations; "
                         "one lane merges into a prioritized risk list. Run it BEFORE building."),
            inputSchema={
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "The change or plan to stress-test."},
                    "include_paid": {"type": "boolean", "description": "Allow limited/paid lanes."},
                    "timeout_s": {"type": "integer",
                                  "description": f"Per-lane timeout (max {MAX_TIMEOUT_S})."},
                },
                "required": ["task"],
            },
            annotations=_ann(readOnlyHint=True, openWorldHint=True, destructiveHint=False),
        ))
        tools.append(Tool(
            name="test_plan",
            description=("Multi-model TEST PLAN from a git diff (default: working-tree changes) or "
                         "a description: the behaviors/edge cases to test and the minimal set of "
                         "concrete test cases to add, merged + prioritized."),
            inputSchema={
                "type": "object",
                "properties": {
                    "task": {"type": "string",
                             "description": "Describe the change (or omit to use the git diff)."},
                    "diff": {"type": "string", "description": "Plan tests for this diff text."},
                    "base": {"type": "string", "description": "git ref/range. Default HEAD."},
                    "cwd": {"type": "string", "description": "Repo dir for `git diff`."},
                    "include_paid": {"type": "boolean", "description": "Allow limited/paid lanes."},
                    "timeout_s": {"type": "integer",
                                  "description": f"Per-lane timeout (max {MAX_TIMEOUT_S})."},
                },
                "required": [],
            },
            annotations=_ann(readOnlyHint=True, openWorldHint=True, destructiveHint=False),
        ))
        tools.append(Tool(
            name="commit_msg",
            description=("Generate a Conventional Commit message from your STAGED diff (falls "
                         "back to the working tree if nothing is staged). Read-only — returns "
                         "text, never commits. Optional `lane`, `cwd`."),
            inputSchema={
                "type": "object",
                "properties": {
                    "cwd": {"type": "string", "description": "Repo dir (default: launch dir)."},
                    "lane": {"type": "string", "description": "Which lane (default: a free one)."},
                    "timeout_s": {"type": "integer",
                                  "description": f"Timeout (max {MAX_TIMEOUT_S})."},
                },
                "required": [],
            },
            annotations=_ann(readOnlyHint=True, openWorldHint=True, destructiveHint=False),
        ))
        tools.append(Tool(
            name="pr_describe",
            description=("Generate a PR title + description (Summary / Changes / Testing) from the "
                         "branch's diff and commit log vs a base (default origin/main, then main). "
                         "Read-only. Optional `base`, `lane`, `cwd`."),
            inputSchema={
                "type": "object",
                "properties": {
                    "base": {"type": "string",
                             "description": "Base ref to diff against (default origin/main)."},
                    "cwd": {"type": "string", "description": "Repo dir (default: launch dir)."},
                    "lane": {"type": "string", "description": "Which lane (default: a free one)."},
                    "timeout_s": {"type": "integer",
                                  "description": f"Timeout (max {MAX_TIMEOUT_S})."},
                },
                "required": [],
            },
            annotations=_ann(readOnlyHint=True, openWorldHint=True, destructiveHint=False),
        ))
    return tools


def _self_ask_tool(lane: LaneSpec) -> Tool:
    """ask_<host> in CLI_BRIDGE_HIDE_HOST mode — requires an explicit `model` so it's only ever
    used to reach a SIBLING model (asking your own running model the same thing is pointless)."""
    schema = _ask_schema(lane)
    schema["required"] = ["task", "model"]
    can_write = "agent" in lane.caps
    return Tool(
        name=f"ask_{lane.key}",
        description=(f"Consult a DIFFERENT model of your own family via {lane.display}. "
                     "Requires an explicit `model` (e.g. a sibling like claude-opus-4-6); empty "
                     f"model is rejected. {lane.note}"),
        inputSchema=schema,
        annotations=_ann(readOnlyHint=not can_write, openWorldHint=True,
                         destructiveHint=can_write),
    )


def _host_ask_tool(lane: LaneSpec) -> Tool:
    """ask_<host> as a NORMAL direct tool (default): the caller's own lane is visible and callable
    like any other (model optional). It still stays out of ask_all/ask_cascade fan-out."""
    can_write = "agent" in lane.caps
    return Tool(
        name=f"ask_{lane.key}",
        description=(f"Consult {lane.display} — your own lane (e.g. a fresh instance, or a sibling "
                     f"model via `model`). Kept out of ask_all/ask_cascade fan-out. {lane.note}"),
        inputSchema=_ask_schema(lane),
        annotations=_ann(readOnlyHint=not can_write, openWorldHint=True,
                         destructiveHint=can_write),
    )


# doctor/setup are how a host learns what's installed and how to configure cost — never hide them.
ESSENTIAL_TOOLS = {"doctor", "setup"}

# CLI_BRIDGE_LEAN core surface (validated by a 2-tier model council): the daily-driver tools.
# Per-lane `ask_<lane>` are kept too (handled by prefix below). Everything else hides behind the
# opt-in. NOT including ask_all_async / ask_build_isolated(alias) — the prefix excludes those.
_LEAN_CORE = {"ask_all", "ask_best", "ask_cascade", "review_diff", "security_review", "ask_build",
              "workflow", "jobs_list", "job_tail", "commit_msg", "pr_describe", "doctor"}
_NON_LANE_ASKS = {"ask_all", "ask_all_async", "ask_best", "ask_cascade", "ask_build",
                  "ask_build_isolated"}


def _lean_keep(name: str) -> bool:
    """A per-lane ask (ask_gpt/ask_gemini/…) or a curated core tool."""
    return (name in _LEAN_CORE or name in ESSENTIAL_TOOLS
            or (name.startswith("ask_") and name not in _NON_LANE_ASKS))


def _filter_tools(tools: list[Tool]) -> list[Tool]:
    """Apply CLI_BRIDGE_ENABLED_TOOLS (allowlist) / _DISABLED_TOOLS (denylist) so a host pays
    context only for the tools it wants. Stole the pattern from pal-mcp-server, whose #1 issue is
    ~30-40k idle tokens from an unfilterable surface. Essentials are always kept."""
    enabled = config.enabled_tools()
    disabled = config.disabled_tools()
    # LEAN: curated core surface, unless the host set an explicit allow/deny list (that wins).
    if config.lean() and not enabled and not disabled:
        return [t for t in tools if _lean_keep(t.name.lower())]
    if not enabled and not disabled:
        return tools
    out = []
    for t in tools:
        name = t.name.lower()
        if name in ESSENTIAL_TOOLS:
            out.append(t)
        elif enabled and name not in enabled:
            continue
        elif name in disabled:
            continue
        else:
            out.append(t)
    return out


@server.list_tools()
async def list_tools() -> list[Tool]:
    lanes, host = _active_lanes()
    tools = _tools_for(lanes)
    own = _host_lane(host)
    if own:
        if config.hide_host():
            if "model" in own.caps:                # legacy: reach a sibling model of your own family
                tools.insert(0, _self_ask_tool(own))
        else:
            tools.insert(0, _host_ask_tool(own))   # visible by default: a normal direct ask_<host>
    return _filter_tools(tools)


# ─────────────────────────────── MCP prompts (host-native slash commands) ───────────────────────────────
# Each prompt returns a user message that points the host at the matching cli-bridge tool, so
# the council's workflows show up as native slash commands / prompt pickers in MCP hosts.

def _p_review_diff(a: dict) -> str:
    base = (a or {}).get("base", "").strip()
    against = f" against `{base}`" if base else ""
    return (f"Use the cli-bridge `review_diff` tool to review the git diff{against}, then "
            "summarize the merged findings grouped by severity.")


def _p_security_review(a: dict) -> str:
    base = (a or {}).get("base", "").strip()
    against = f" against `{base}`" if base else ""
    return (f"Use the cli-bridge `security_review` tool on the git diff{against}, then report "
            "the security findings by severity with remediations.")


def _p_debate(a: dict) -> str:
    q = (a or {}).get("question", "").strip()
    return (f"Use the cli-bridge `debate` tool to debate this question across models, then give "
            f"me the final conclusion:\n\n{q}" if q
            else "Use the cli-bridge `debate` tool to debate a question across models. Ask me "
                 "for the question if I didn't provide one.")


def _p_cost_setup(a: dict) -> str:
    return ("Call the cli-bridge `setup` tool, then walk me through choosing a cost profile "
            "(saver / balanced / max) and how to set it for my plan.")


def _p_premortem(a: dict) -> str:
    plan = (a or {}).get("plan", "").strip()
    return (f"Use the cli-bridge `premortem` tool on this plan, then give me the prioritized "
            f"risks and mitigations:\n\n{plan}" if plan
            else "Use the cli-bridge `premortem` tool to stress-test a plan. Ask me for the plan "
                 "if I didn't give one.")


def _p_test_plan(a: dict) -> str:
    base = (a or {}).get("base", "").strip()
    against = f" against `{base}`" if base else ""
    return (f"Use the cli-bridge `test_plan` tool on the git diff{against}, then give me the "
            "prioritized test cases to add.")


def _p_apilookup(a: dict) -> str:
    q = (a or {}).get("query", "").strip()
    subject = q or "the library/API I name next"
    # A current-docs guard (prior art: workflow MCP servers' apilookup): forces a dated,
    # current-year lookup via a WEB-AWARE lane so a stale training cutoff can't answer. Zero
    # tool-surface cost — it's a prompt, not another tool.
    return (
        f"Look up CURRENT documentation for {subject} and answer from it, not from memory:\n"
        "1. First state today's date.\n"
        "2. Use a web-aware cli-bridge lane — `ask_gemini` (or `ask_grok`) — to fetch the "
        "CURRENT-YEAR official docs/changelog/release notes; do NOT trust your training cutoff.\n"
        "3. Give the answer with the version it applies to and link the source."
        + (f"\n\nQuery: {q}" if q else ""))


_PROMPTS: dict[str, dict] = {
    "review_diff": {
        "description": "Multi-model code review of your current git diff.",
        "arguments": [PromptArgument(
            name="base", description="git ref/range to diff against (default HEAD)", required=False)],
        "build": _p_review_diff,
    },
    "security_review": {
        "description": "OWASP-aware multi-model security review of your git diff.",
        "arguments": [PromptArgument(
            name="base", description="git ref/range to diff against (default HEAD)", required=False)],
        "build": _p_security_review,
    },
    "debate": {
        "description": "Debate a question across several models, then a judge concludes.",
        "arguments": [PromptArgument(
            name="question", description="The question to debate", required=True)],
        "build": _p_debate,
    },
    "cost_setup": {
        "description": "Configure how cli-bridge spends paid credits/quota (cost profile).",
        "arguments": [],
        "build": _p_cost_setup,
    },
    "premortem": {
        "description": "Stress-test a plan across models before building it.",
        "arguments": [PromptArgument(
            name="plan", description="The plan/change to premortem", required=False)],
        "build": _p_premortem,
    },
    "test_plan": {
        "description": "Derive a prioritized test plan from your git diff across models.",
        "arguments": [PromptArgument(
            name="base", description="git ref/range to diff against (default HEAD)", required=False)],
        "build": _p_test_plan,
    },
    "apilookup": {
        "description": "Look up a library/API in CURRENT docs via a web-aware lane (beats a "
                       "stale training cutoff).",
        "arguments": [PromptArgument(
            name="query", description="library/API + what you need", required=False)],
        "build": _p_apilookup,
    },
}


@server.list_prompts()
async def list_prompts() -> list[Prompt]:
    return [Prompt(name=name, description=spec["description"], arguments=spec["arguments"])
            for name, spec in _PROMPTS.items()]


@server.get_prompt()
async def get_prompt(name: str, arguments: dict | None) -> GetPromptResult:
    spec = _PROMPTS.get(name)
    if spec is None:
        raise ValueError(f"unknown prompt: {name}")
    text = spec["build"](arguments or {})
    return GetPromptResult(
        description=spec["description"],
        messages=[PromptMessage(role="user", content=TextContent(type="text", text=text))])


# ─────────────────────────────── MCP resources (read-only views) ───────────────────────────────
# Inspectable JSON snapshots of cli-bridge's own state — handy for hosts that browse resources
# and for the human CLI. All read-only and local; no delegate output here.

_REVIEW_DIFF_SCHEMA = {
    "title": "review_diff / security_review JSON result",
    "type": "object",
    "properties": {
        "tool": {"type": "string"},
        "status": {"type": "string"},
        "summary": {"type": "string"},
        "verdict": {"type": "string"},
        "findings": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"},
            "severity": {"enum": list(findings.SEVERITIES)},
            "confidence": {"enum": ["single", "majority", "consensus"]},
            "title": {"type": "string"},
            "file": {"type": ["string", "null"]},
            "line": {"type": ["integer", "null"]},
            "models": {"type": "array", "items": {"type": "string"}},
            "evidence": {"type": "string"},
            "recommendation": {"type": "string"},
        }}},
        "residual_risk": {"type": "string"},
        "meta": {"type": "object"},
    },
}


def _config_snapshot(host: str) -> dict:
    return {
        "host": host or None,
        "profile": _profile(),
        "profile_set": _profile_is_set(),
        "guard": guards.level(),
        "terse": preamble.level(),
        "cache_ttl_s": config.CACHE_TTL_S,
        "lanes": [
            {"key": ln.key, "installed": is_installed(ln), "enabled": ln.enabled,
             "cost": ln.cost_label,
             "cost_source": "user" if ln.cost_is_configured else "default",
             "model": ln.model_for(""), "experimental": ln.experimental,
             "caps": sorted(ln.caps)}
            for ln in all_lanes()
        ],
    }


_RESOURCES = {
    "cli-bridge://config": ("Effective config", "Profile, guard, terse, and per-lane cost/model."),
    "cli-bridge://lane-stats": ("Lane health", "Per-lane runs/failures/cooldown (JSON)."),
    "cli-bridge://usage-summary": ("Usage summary", "Estimated tokens/credits by lane (JSON)."),
    "cli-bridge://workflow-schemas/review-diff": (
        "review_diff schema", "JSON schema of the structured review result."),
}


@server.list_resources()
async def list_resources() -> list[Resource]:
    # uri is our own constant str; the SDK types it AnyUrl but pydantic coerces str at runtime.
    return [Resource(uri=uri, name=name, description=desc,  # type: ignore[arg-type]
                     mimeType="application/json")
            for uri, (name, desc) in _RESOURCES.items()]


@server.read_resource()
async def read_resource(uri) -> str:
    key = str(uri)
    if key == "cli-bridge://config":
        return json.dumps(_config_snapshot(_host_name()), indent=2)
    if key == "cli-bridge://lane-stats":
        return json.dumps(telemetry.lane_stats(), indent=2)
    if key == "cli-bridge://usage-summary":
        return json.dumps(telemetry.usage_report(), indent=2)
    if key == "cli-bridge://workflow-schemas/review-diff":
        return json.dumps(_REVIEW_DIFF_SCHEMA, indent=2)
    raise ValueError(f"unknown resource: {key}")


# ─────────────────────────────── execution helpers ───────────────────────────────

def _str(args: dict, key: str) -> str:
    """Coerce an arg to a clean string. JSON-RPC callers often send null -> must not become
    the literal 'None'."""
    val = args.get(key)
    return str(val).strip() if val is not None else ""


def _timeout(raw) -> int:
    try:
        t = int(raw)
    except (TypeError, ValueError):
        t = DEFAULT_TIMEOUT_S
    return max(1, min(t, MAX_TIMEOUT_S))


def _ask_all_timeout(raw) -> int:
    """Keep fan-out below typical MCP client call deadlines.

    Individual `ask_<lane>` calls may run for minutes, but `ask_all` needs room for every
    parallel lane plus optional synthesis before the host gives up on the MCP call.
    """
    try:
        t = int(raw)
    except (TypeError, ValueError):
        t = ASK_ALL_DEFAULT_TIMEOUT_S
    return max(1, min(t, ASK_ALL_MAX_TIMEOUT_S))


def _ask_all_include_paid(args: dict) -> bool:
    # One shared rule (config.include_paid_resolved): saver = include_paid refused, enforced.
    return config.include_paid_resolved(args.get("include_paid"))


def _ask_all_targets(lanes: list[LaneSpec], include_paid: bool,
                     skip_cooled: bool = True) -> list[LaneSpec]:
    out = [ln for ln in lanes if include_paid or (not ln.is_paid and not ln.is_limited)]
    if skip_cooled:
        out = [ln for ln in out if telemetry.cooldown_remaining(ln.key) == 0]
    return out


def _cache_key(lane: LaneSpec, model: str, effort: str, agent: str, cwd: str,
               task: str, terse_level: str) -> str:
    raw = "\x00".join([lane.key, model, effort, agent, cwd or "", terse_level, task])
    return hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()


# Transient kinds worth a quick retry (a flaky CLI blip). NOT timeout (would burn another full
# wait), nor quota/auth/not_found (those are sticky and cooled — retrying just wastes a call).
_RETRYABLE = {"failed", "spawn"}


async def _spawn_with_retry(argv: list[str], timeout: int, cwd: str | None,
                            env: dict | None = None) -> runner.RunResult:
    """Run the CLI, retrying a TRANSIENT failure up to CLI_BRIDGE_RETRIES times with backoff —
    so an occasionally-flaky lane 'works the first time' from the caller's point of view."""
    attempts = config.retries() + 1
    res = await runner.arun(argv, timeout, cwd, env)
    n = 1
    while not res.ok and res.kind in _RETRYABLE and n < attempts:
        await asyncio.sleep(min(0.4 * (2 ** (n - 1)), 3.0))
        res = await runner.arun(argv, timeout, cwd, env)
        n += 1
    return res


def _write_trace(lane: LaneSpec, model: str, argv: list[str], cwd: str | None,
                 timeout: int, res: runner.RunResult) -> None:
    """Best-effort reproducible trace (redacted argv + output, timing) for debug/audit. Off
    unless CLI_BRIDGE_TRACE_DIR is set. Never raises into a delegation."""
    d = config.trace_dir()
    if not d:
        return
    try:
        os.makedirs(d, exist_ok=True)
        rec = {"ts": time.time(), "lane": lane.key, "model": model,
               "argv": [runner.redact(a) for a in argv], "cwd": cwd or "", "timeout_s": timeout,
               "ok": res.ok, "kind": res.kind, "exit_code": res.exit_code,
               "latency_ms": res.latency_ms,
               "output_chars": len(res.output), "output": runner.redact(res.output)[:4000]}
        h = hashlib.sha1("\x00".join(argv).encode("utf-8", "replace")).hexdigest()[:10]
        with open(os.path.join(d, f"{lane.key}-{h}.json"), "w", encoding="utf-8") as fh:
            json.dump(rec, fh, indent=2)
    except OSError:
        pass


def _mock_answer(lane: LaneSpec, model: str, task: str) -> str:
    return (f"[mock:{lane.key}] dry-run — no CLI spawned (CLI_BRIDGE_MOCK). "
            f"model={model or 'default'} would answer:\n{task[:300]}")


async def _run_lane(lane: LaneSpec, args: dict, *, tool: str = "ask",
                    terse: bool = True) -> runner.RunResult:
    task = _str(args, "task")
    if not task:
        return runner.RunResult(False, "task is required", "failed")
    model = lane.model_for(_str(args, "model"))
    # M11-7: a non-paid lane resolving to a paid opencode-go/* model (usually a per-call override)
    # spends real credits — the doctor cost-mismatch only catches the DEFAULT model, so warn here
    # too. Best-effort log (no behaviour change): visible with CLI_BRIDGE_LOG=warning.
    if not lane.is_paid and lanes_mod.is_paid_opencode_model(model):
        runner.log.warning("%s is a free lane but model %r spends credits (opencode-go/*)",
                           lane.key, model)
    if config.mock():                          # dry-run: canned answer, no spawn
        return runner.RunResult(True, _mock_answer(lane, model, task), "ok", latency_ms=0)
    # Re-entry guard: a delegate cli-bridge spawns is given CLI_BRIDGE_DEPTH below. If THIS bridge
    # is already a delegate at/over the cap, it must not spawn another — else a delegate configured
    # to load cli-bridge could fork-bomb the council and the user's quota.
    depth = config.current_depth()
    if depth >= config.max_depth():
        return runner.RunResult(False, (
            f"re-entry guard: this cli-bridge is a delegate at depth {depth} (max "
            f"{config.max_depth()}); refusing to spawn another to avoid recursion. Raise "
            "CLI_BRIDGE_MAX_DEPTH only if you deliberately want nested delegation."),
            "blocked")
    # Spend guard (budget.py): the one pre-spawn chokepoint — per-lane daily run limit
    # (any lane) + daily credit cap (paid or CREDITS_PER_1K-rated lanes).
    block_reason = budget.check_spawn(lane)
    if block_reason:
        return runner.RunResult(False, block_reason, "blocked")
    agent = _str(args, "agent").lower()
    if agent not in {"", "plan", "build"}:    # never let a hallucinated value enable writes
        agent = "plan"
    if agent == "build" and config.build_disabled():   # team lock: no delegate edits files
        agent = "plan"
    effort = _str(args, "effort")
    cwd = _str(args, "cwd")
    expanded = os.path.expanduser(cwd) if cwd else None
    if expanded and not os.path.isdir(expanded):
        return runner.RunResult(False, f"cwd `{cwd}` is not an existing directory", "failed")
    # Opt-in response cache (CLI_BRIDGE_CACHE_TTL_S>0): an identical call returns the stored
    # answer instead of re-spawning the CLI. Keyed on everything that changes the output,
    # incl. the terse level (it changes the prompt) and a build run is never served stale.
    terse_level = preamble.level() if terse else "off"
    ttl = config.CACHE_TTL_S
    key = ""
    # Never cache native-session turns: the same prompt means something different inside a
    # session (the CLI holds prior context the cache key can't see).
    if ttl > 0 and agent != "build" and not args.get("_native_argv"):
        key = _cache_key(lane, model, effort, agent, expanded or "", task, terse_level)
        hit = telemetry.cache_get(key, ttl)
        if hit is not None:
            return runner.RunResult(hit[0], hit[1], hit[2], latency_ms=0)
    # Compress the FINAL answer (cuts host context + delegate output tokens). Skipped for
    # structured-output tools (terse=False) so JSON stays intact. Telemetry keys on the raw
    # task, not the prefixed prompt.
    task = preamble.with_role(_str(args, "role"), task)   # V.2: optional named persona
    images = args.get("images")                           # V.3: vision via Gemini CLI @-file refs
    if images and lane.key == "gemini" and isinstance(images, list):
        refs = [f"@{os.path.abspath(os.path.expanduser(str(p)))}"
                for p in images if str(p).strip()]
        if refs:
            task = f"{task}\n\n{' '.join(refs)}"
    prompt = preamble.apply(task) if terse else task
    argv = [lane.bin] + lane.build_ask(prompt, model, effort, agent, lane.bin)
    # Native-session extras (conversation turns only): inserted just before the task — the
    # last argv element for every built-in lane (custom lanes never set _native_argv).
    native_extra = args.get("_native_argv")
    if native_extra and len(argv) > 1:
        argv = argv[:-1] + [str(a) for a in native_extra] + argv[-1:]
    # Some lanes select the model via ENV (e.g. vibe's VIBE_ACTIVE_MODEL), not a flag. Merge any
    # such overrides onto a COPY of the environment (a bare dict would drop the CLI's own PATH/auth).
    extra_env = lane.env_ask(model, effort, agent) if lane.env_ask else {}
    # Opt-in nested-session guard: strip the host's own CLAUDE_*/CODEX_* session markers so a
    # delegate `claude`/`codex` doesn't refuse to run "inside a session" (auth tokens kept).
    base_env = config.strip_nesting(dict(os.environ)) if config.strip_nesting_env() else os.environ
    # Always stamp the child's depth (current+1) so a delegate that itself loads cli-bridge trips
    # the re-entry guard above. Merge onto a COPY of the env (a bare dict drops the CLI's PATH/auth).
    spawn_env = {**base_env, **extra_env, "CLI_BRIDGE_DEPTH": str(depth + 1)}
    await runner.pace(lane.key, lane.min_interval_s)   # anti-burst (opt-in, per lane)
    rec = telemetry.start(tool, lane.key, model, task, role=_str(args, "role"))
    timeout = _timeout(args.get("timeout_s"))
    t0 = time.monotonic()
    res = await _spawn_with_retry(argv, timeout, expanded, spawn_env)
    res.latency_ms = int((time.monotonic() - t0) * 1000)
    res.model = model                          # provenance: the resolved model that actually ran
    telemetry.record(rec, res.ok, res.kind, len(res.output), input_chars=len(prompt))
    _write_trace(lane, model, argv, expanded, timeout, res)
    if key and res.ok:                        # cache only successes; failures are transient
        telemetry.cache_put(key, res.ok, res.output, res.kind)
    return res


async def _run_lane_maybe_convo(lane: LaneSpec, args: dict) -> tuple[runner.RunResult, str]:
    """Round-table wrapper around _run_lane. With no `conversation` it's a plain ask (zero
    change). With one, it replays the thread's recipient-aware history before the task, runs the
    lane, then records the exchange so the NEXT turn — on this or another lane — sees it.
    Returns (result, conversation_id) where the id is "" when no thread is in play."""
    cid = _str(args, "conversation").strip()
    if not cid:
        return await _run_lane(lane, args), ""
    if cid.lower() == "new":
        cid = conversations.new_id()
    elif not conversations.is_valid_id(cid):
        return runner.RunResult(False, f"invalid conversation id: {cid!r}", "failed"), ""
    task = _str(args, "task")
    sub = dict(args)
    # Native session continuity (claude mint / opencode capture …): the lane's own session
    # carries the turns it has already seen, so the prompt replays only the DELTA other lanes
    # added since. Replay stays the cross-lane source of truth (sqlite records every turn).
    ns = lane.native_session if config.native_sessions_enabled() else None
    sid, last_seen = "", 0
    if ns:
        extra, sid, last_seen = conversations.native_step(ns, cid, lane.key)
        if extra:
            sub["_native_argv"] = extra
    prefix, _trimmed = conversations.build_history_prefix(
        cid, lane.key, config.convo_max_chars(), since_turn=last_seen)
    if prefix:
        sub["task"] = f"{prefix}\n{task}"
    res = await _run_lane(lane, sub)
    if ns and not res.ok and last_seen:        # broken resume → fall back to replay next turn
        conversations.native_drop(cid, lane.key)
    if task and res.ok:                        # only record a real exchange
        conversations.record_turn(cid, lane.key, "user", task)
        n = conversations.record_turn(cid, lane.key, "assistant", res.output)
        if ns:
            conversations.native_commit(ns, cid, lane.key, sid,
                                        f"{res.err}\n{res.output}", n)
        await _maybe_compact_convo(cid, lane)
    return res, cid


async def _maybe_compact_convo(cid: str, lane: LaneSpec) -> None:
    """Rolling summary: once the stored thread outgrows the replay budget, the lane that just
    answered (it had the full history in front of it — no third model to route) condenses the
    old tail into one summary turn. Best-effort: any failure leaves the thread as it was."""
    if not config.convo_summary_enabled():
        return
    try:
        upto, excerpt = conversations.compaction_plan(cid, config.convo_max_chars())
        if not upto:
            return
        res = await _run_lane(lane, {"task": conversations.SUMMARY_PROMPT + excerpt},
                              tool="convo_summary")
        if res.ok and res.output.strip():
            conversations.apply_compaction(cid, upto, res.output, lane.key)
    except Exception:                          # noqa: BLE001 — never break the user's call
        pass


def _rel_time(ts: float | None) -> str:
    if not ts:
        return "?"
    s = max(0, int(time.time() - ts))
    if s < 60:
        return f"{s}s ago"
    if s < 3600:
        return f"{s // 60}m ago"
    if s < 86400:
        return f"{s // 3600}h ago"
    return f"{s // 86400}d ago"


def _lane_by_key(key: str, lanes: list[LaneSpec]) -> LaneSpec | None:
    return next((ln for ln in lanes if ln.key == key), None)


def _setup_recommendation(lanes: list[LaneSpec]) -> str:
    """Beginner-proof onboarding: detect what's installed, sort it by what it costs the user,
    and RECOMMEND a concrete profile + cap they can accept or tweak — so nobody has to pick a
    profile in the abstract."""
    if not lanes:
        return ("No delegate CLIs detected on PATH yet. Install one (run `doctor` for hints) or "
                "set CLI_BRIDGE_MOCK=1 to explore cli-bridge without any CLI.")
    free = [ln.key for ln in lanes if not ln.is_paid and not ln.is_limited]
    limited = [ln.key for ln in lanes if ln.is_limited]
    paid = [ln.key for ln in lanes if ln.is_paid]

    def _tag(keys: list[str]) -> str:
        if not keys:
            return "—"
        by = {ln.key: ln for ln in lanes}
        return ", ".join(k + ("" if by[k].cost_is_configured else " (default)") for k in keys)

    lines = [
        "**Installed lanes — typical cost (sourced defaults from docs/COSTS.md, NOT detected; "
        "'(default)' means the user hasn't told us their plan yet):**",
        f"- free: {_tag(free)}",
        f"- limited (scarce quota): {_tag(limited)}",
        f"- paid (money/credits): {_tag(paid)}",
        "",
        "**First, ask the user ONE question:** do you pay for these as flat subscriptions "
        "(Pro/Max-style plans), metered API/credits, or a mix? Their answer — not our defaults — "
        "decides each lane's real cost tier. Apply it symmetrically to every installed lane, and "
        "record each answer with `set_lane_cost(lane, cost, note)` so it persists.",
        "",
    ]
    if config.profile_is_set():
        lines.append(f"Profile already set to **{config.profile()}** — you're configured. Adjust "
                     "any lane with CLI_BRIDGE_<LANE>_COST=free|limited|paid.")
        return "\n".join(lines)
    if paid or limited:
        lines.append(
            "**Recommended: `balanced` + a daily cap.** Free lanes handle routine work; a "
            "paid/limited lane is used only when a task earns it, and the cap is a hard safety "
            "net so you never overspend by surprise:\n"
            "    CLI_BRIDGE_PROFILE=balanced\n"
            "    CLI_BRIDGE_DAILY_CREDIT_CAP=5      # est. paid 'credits'/day — tune to you\n"
            "(Set CLI_BRIDGE_<LANE>_CREDITS_PER_1K so the cap can estimate spend.)")
    else:
        lines.append(
            "**Recommended: `balanced`** (or `max`). Everything installed is free — nothing to "
            "overspend, so balanced already uses it all freely:\n"
            "    CLI_BRIDGE_PROFILE=balanced")
    lines += [
        "",
        "Profiles in plain terms: **saver**=free-only fan-out, include_paid refused (direct "
        "calls to a paid lane still work) · **balanced**=free by default, paid joins fan-out "
        "only when the caller passes include_paid · **max**=best by default, paid lanes join "
        "automatically.",
    ]
    return "\n".join(lines)


# ─────────────────────────────── tool dispatch ───────────────────────────────

@server.call_tool()
async def call_tool(name: str, args: dict) -> list[TextContent]:
    lanes, host = _active_lanes()

    if name == "setup":
        cur = _profile() + ("" if _profile_is_set() else " (default — not explicitly set)")
        reco = _setup_recommendation(lanes)
        return [_emit(f"Current profile: **{cur}**\n\n{reco}\n\n---\n{SETUP_TEXT}",
                      label="setup", guard=False)]

    if name == "doctor":
        text = await _doctor_deep(host, lanes) if bool(args.get("deep")) else _doctor(host)
        return [_emit(text, label="doctor", guard=False)]

    if name == "usage_report":
        since_s = _parse_since(_str(args, "since"))
        rep = telemetry.usage_report(since_s=since_s)
        # output_format is the project-wide name; accept legacy `format` too (no break).
        if (_str(args, "output_format") or _str(args, "format")).lower() == "json":
            return [_emit(json.dumps(rep, indent=2), label="usage_report", guard=False)]
        return [_emit(_render_usage(rep), label="usage_report", guard=False)]

    if name == "usage_budget":
        return [_emit(_render_budget(telemetry.usage_budget()), label="usage_budget", guard=False)]

    if name == "lane_stats":
        return [_emit(_render_lane_stats(), label="lane_stats", guard=False)]

    if name == "reset_lane_state":
        lane_key = _str(args, "lane")
        ok = telemetry.reset_lane(lane_key) if lane_key else False
        msg = (f"Lane '{lane_key}' cooldown/failure counters cleared." if ok
               else f"No state to clear for lane '{lane_key}' (already clean or unknown).")
        return [TextContent(type="text", text=msg)]

    if name == "ask_cascade":
        return await _ask_cascade(lanes, args)

    if name == "ask_best":
        return await _ask_best(lanes, args)

    if name == "rate_lane":
        return _rate_lane(lanes, args)

    if name == "set_lane_cost":
        return _set_lane_cost(args)

    if name == "route_plan":
        include_paid = (bool(args["include_paid"]) if args.get("include_paid") is not None
                        else _profile() == "max")
        mode = _str(args, "mode").lower()
        if mode and mode in router.MODES:
            perf = telemetry.lane_perf()
            quality = telemetry.lane_quality(mode)
            return [TextContent(type="text", text=router.explain_mode(
                lanes, telemetry.cooldown_remaining, lambda k: perf.get(k, {}), mode, include_paid,
                quality_of=lambda k: quality.get(k, {})))]
        return [TextContent(type="text", text=router.explain(
            lanes, telemetry.cooldown_remaining, include_paid))]

    if name == "ask_all":
        return await _ask_all(lanes, args)

    if name == "ask_all_async":
        if not _str(args, "task"):
            return [TextContent(type="text", text="[error] task is required")]
        job_id = jobs.start_job("ask_all", lambda: _ask_all_body(lanes, dict(args)),
                                preview=_str(args, "task"))
        return [TextContent(type="text", text=(
            f"Started background job `{job_id}` (ask_all). It runs while you keep working. "
            f"Check it with `job_status {job_id}`, fetch the answer with `job_result {job_id}`."))]

    if name == "job_status":
        info = jobs.status(_str(args, "job_id"))
        if info is None:
            return [TextContent(type="text", text=f"[error] unknown job_id: {_str(args, 'job_id')}")]
        if info.get("kind") == "build":                # fold in live build progress
            snap = buildloop.snapshot(_str(args, "job_id"))
            if snap:
                info = {**info, **snap}
        return [TextContent(type="text", text=_render_job_status(info))]

    if name == "job_result":
        r = jobs.result(_str(args, "job_id"))
        if r is None:
            return [TextContent(type="text", text=f"[error] unknown job_id: {_str(args, 'job_id')}")]
        st, body = r
        if st == jobs.RUNNING:
            return [TextContent(type="text", text=(
                "Job still running — poll `job_status` and fetch again when it's succeeded."))]
        if not body:
            return [TextContent(type="text", text=f"[{st}] job produced no output.")]
        return [_emit(body, label="job_result")]

    if name == "job_cancel":
        st = jobs.cancel(_str(args, "job_id"))
        msg = {"unknown": f"[error] unknown job_id: {_str(args, 'job_id')}",
               "cancelling": "Cancellation requested — the delegates' process groups are being "
                             "killed; poll `job_status` for the final state."}.get(
            st, f"Job is already **{st}** — nothing to cancel.")
        return [TextContent(type="text", text=msg)]

    if name == "jobs_list":
        return [TextContent(type="text", text=_render_jobs_list(jobs.listing()))]

    if name == "review_diff":
        return await _review_diff(lanes, args)

    if name == "security_review":
        targets = _ask_all_targets(lanes, _ask_all_include_paid(args))
        return [_emit(await workflows.security_review(targets, args, _run_lane),
                      label="security_review")]

    if name == "debate":
        targets = _ask_all_targets(lanes, _ask_all_include_paid(args))
        return [_emit(await workflows.debate(targets, args, _run_lane, progress=_emit_progress),
                      label="debate")]

    if name == "consensus":
        targets = _ask_all_targets(lanes, _ask_all_include_paid(args))
        return [_emit(await workflows.consensus(targets, args, _run_lane, progress=_emit_progress),
                      label="consensus")]

    if name == "challenge":
        key = _str(args, "lane")
        if key:
            ln = _lane_by_key(key, lanes)
            targets = [ln] if ln else []
        else:
            targets = _ask_all_targets(lanes, _ask_all_include_paid(args))
        return [_emit(await workflows.challenge(targets, args, _run_lane), label="challenge")]

    if name in ("commit_msg", "pr_describe"):
        key = _str(args, "lane")
        if key:
            ln = _lane_by_key(key, lanes)
            targets = [ln] if ln else []
        else:
            targets = _ask_all_targets(lanes, _ask_all_include_paid(args))
        fn = workflows.commit_msg if name == "commit_msg" else workflows.pr_describe
        return [_emit(await fn(targets, args, _run_lane), label=name)]

    if name == "premortem":
        targets = _ask_all_targets(lanes, _ask_all_include_paid(args))
        return [_emit(await workflows.premortem(targets, args, _run_lane), label="premortem")]

    if name == "test_plan":
        targets = _ask_all_targets(lanes, _ask_all_include_paid(args))
        return [_emit(await workflows.test_plan(targets, args, _run_lane), label="test_plan")]

    if name in ("ask_build", "ask_build_isolated"):
        key = _str(args, "lane")
        if key:
            lane = _lane_by_key(key, lanes)
        else:                                        # no lane named → first free build-capable
            lane = next((ln for ln in _ask_all_targets(lanes, False) if "agent" in ln.caps), None)
        if not lane:
            msg = (f"[error] no such lane: {key}." if key else
                   "[error] no free build-capable lane available.")
            return [TextContent(type="text", text=msg + " Pass a build-capable `lane`.")]
        if "agent" not in lane.caps:
            return [TextContent(type="text", text=(
                f"[error] lane '{key}' has no build/write mode."))]
        mode = _str(args, "mode") or "isolated"      # ask_build_isolated == ask_build mode=isolated
        if name == "ask_build" and mode == "direct":
            if bool(args.get("dry_run")):            # preview the brief, launch nothing
                zlabel = _str(args, "zone") or _str(args, "target_dir") or "the target directory"
                brief = worktrees._build_brief(_str(args, "task"), zlabel,
                                               interface=_str(args, "interface"),
                                               dod=_str(args, "dod"))
                return [_emit("# Dry run — brief preview (nothing was launched)\n\n" + brief,
                              label="ask_build")]
            if config.build_disabled():
                return [_emit("[error] direct builds are disabled on this machine "
                              "(CLI_BRIDGE_NO_BUILD). Use mode=isolated for a review-only diff.",
                              label="ask_build")]
            if bool(args.get("async")):              # steerable background build job
                state = buildloop.BuildState()
                _args = dict(args)
                job_id = jobs.start_job(
                    "build", lambda: buildloop.run_build(state, run_lane=_run_lane, lane=lane,
                                                         args=_args), preview=_str(args, "task"))
                state.log_path = jobs.log_path_for(job_id)
                buildloop.register(job_id, state)
                return [TextContent(type="text", text=(
                    f"Steerable build started: `{job_id}`. Follow it with `job_tail {job_id}`, "
                    f"steer with `build_steer {job_id} \"…\"` (interrupt=true to cut a turn), "
                    f"fetch the result with `job_result {job_id}`."))]
            return [_emit(await worktrees.ask_build_direct(
                lane, args, _run_lane, build_disabled=config.build_disabled()), label="ask_build")]
        architect = None
        akey = _str(args, "architect_lane")
        if akey:
            architect = _lane_by_key(akey, lanes)
            if not architect:
                return [TextContent(type="text", text=(
                    f"[error] no such architect_lane: {akey}."))]
        return [_emit(await worktrees.ask_build_isolated(lane, args, _run_lane, architect=architect),
                      label=name)]

    if name == "job_tail":
        tailed = buildloop.tail(_str(args, "job_id"), int(args.get("offset") or 0))
        if tailed is None:
            return [TextContent(type="text", text=(
                "No live build for that job_id (it may have finished — use `job_result`, or it "
                "was started in another server process)."))]
        new_offset, chunk = tailed
        body = chunk if chunk else "_(no new output yet)_"
        return [_emit(f"offset={new_offset}\n{body}", label="job_tail", guard=False)]

    if name == "build_steer":
        msg = buildloop.steer(_str(args, "job_id"), _str(args, "instruction"),
                              interrupt=bool(args.get("interrupt")))
        if msg == "unknown":
            return [TextContent(type="text", text=(
                "No live build for that job_id (already finished, or started elsewhere)."))]
        return [TextContent(type="text", text=msg)]

    if name == "batch_run":
        raw = args.get("tasks")
        tasks = [t for t in raw if isinstance(t, dict) and t.get("task")] if isinstance(raw, list) \
            else []
        if not tasks:
            return [TextContent(type="text", text=(
                "[error] tasks must be a non-empty list of {task, lane?, model?, effort?, cwd?}."))]
        if len(tasks) > orchestrate.MAX_BATCH_TASKS:
            return [TextContent(type="text", text=(
                f"[error] too many tasks ({len(tasks)} > {orchestrate.MAX_BATCH_TASKS}). Split it."))]
        default_lanes = _ask_all_targets(lanes, _ask_all_include_paid(args))
        default_lane = default_lanes[0] if default_lanes else None

        def _resolve(k):
            return _lane_by_key(k, lanes)

        if bool(args.get("dry_run")):              # cost envelope, nothing spawned
            env = orchestrate.estimate(tasks, resolve_lane=_resolve, default_lane=default_lane,
                                       telemetry=telemetry)
            return [_emit(orchestrate.render_estimate(env), label="batch_run", guard=False)]

        async def _batch_body():
            rid, res = await orchestrate.batch_run(
                tasks, run_lane=_run_lane, resolve_lane=_resolve, default_lane=default_lane,
                telemetry=telemetry, run_id=_str(args, "resume_id"),
                max_concurrency=int(args.get("max_concurrency") or 0),
                max_calls=int(args.get("max_calls") or 0),
                max_credits=float(args.get("max_credits") or 0.0))
            return orchestrate.render_batch(rid, res)
        if bool(args.get("async")):
            job_id = jobs.start_job("batch", _batch_body, preview=f"{len(tasks)} tasks")
            return [TextContent(type="text", text=(
                f"Batch started: `{job_id}`. Poll `job_status {job_id}`, fetch `job_result "
                f"{job_id}`."))]
        return [_emit(await _batch_body(), label="batch_run")]

    if name == "workflow":
        return await _run_workflow_preset(args, lanes)

    if name == "conversations_list":
        rows = telemetry.convo_list()
        if not rows:
            return [_emit("No round-table threads yet. Start one: call any ask_<lane> with "
                          "conversation='new', then reuse the returned id (on any lane).",
                          label="conversations_list", guard=False)]
        lines = ["# Round-table conversations", ""]
        for row in rows:
            lanes_txt = ", ".join(row["lanes"]) or "—"
            lines.append(f"- **{row['conversation_id']}** · {row['turns']} turns · {lanes_txt} · "
                         f"{_rel_time(row['last_at'])}\n      {row['preview']}")
        return [_emit("\n".join(lines), label="conversations_list", guard=False)]

    if name == "conversation_show":
        cid = _str(args, "conversation").strip()
        turns = telemetry.convo_turns(cid)
        if not turns:
            return [_emit(f"[conversation: {cid or '(none)'}] no turns found. "
                          "List threads with conversations_list.",
                          label="conversation_show", guard=False)]
        parts = [f"# Conversation {cid}", ""]
        for t in turns:
            if t["role"] == "summary":
                who = f"Summary of earlier turns (by {t['lane'] or 'a lane'})"
            else:
                who = "User" if t["role"] == "user" else (t["lane"] or "assistant")
            parts.append(f"## Turn {t['turn_number']} — {who}\n{t['content']}")
        return [_emit("\n\n".join(parts), label="conversation_show")]

    if name.startswith("ask_"):
        key = name[4:]
        lane = _lane_by_key(key, lanes)
        if not lane:
            # The host's OWN lane. Visible/callable by default; in CLI_BRIDGE_HIDE_HOST mode it is
            # allowed only with an explicit model (a SIBLING consult, not re-asking yourself).
            own = _host_lane(host)
            if own and own.key == key:
                if config.hide_host() and not _str(args, "model"):
                    return [TextContent(type="text", text=(
                        f"[error] ask_{key} is your own family — pass an explicit `model` to "
                        "consult a SIBLING model (e.g. claude-opus-4-6). Re-asking the model "
                        "you're already running is pointless."))]
                lane = own
            else:
                avail = ", ".join(ln.key for ln in lanes) or "none installed"
                return [TextContent(type="text", text=(
                    f"[error] no such lane: {key}. Available: {avail}. Run `doctor` for install "
                    "hints, or set CLI_BRIDGE_MOCK=1 to try without any CLI."))]
        res, cid = await _run_lane_maybe_convo(lane, args)
        out = res.render()
        if cid:
            out = f"[conversation: {cid}] — reuse this id (on any lane) to continue the thread.\n\n{out}"
        out = _echo_header(lane.key, res.model, _str(args, "task")) + out
        return [_emit(out, label=f"ask_{lane.key}")]

    if name == "list_models":
        key = _str(args, "lane")
        lane = _lane_by_key(key, lanes)
        if not lane:
            avail = ", ".join(ln.key for ln in lanes) or "none installed"
            return [TextContent(type="text",
                                text=f"[error] no such lane: {key or '(none)'}. Available: {avail}.")]
        if lane.models_args is not None:
            res = await runner.arun([lane.bin] + lane.models_args, 60)
            return [_emit(res.render(), label=f"list_models:{lane.key}")]
        # No list command on this CLI — surface the resolved default + how to choose.
        dm = lane.model_for("")
        how = (f"pass model=… per call, or set CLI_BRIDGE_{lane.key.upper()}_MODEL"
               if "model" in lane.caps else "this lane uses its own model (not selectable here)")
        return [_emit(f"{lane.display}: no model-list command exposed by the CLI. "
                      f"Default model: {dm or '(the CLI default)'}. To choose: {how}.",
                      label=f"list_models:{lane.key}", guard=False)]

    if name.startswith("list_") and name.endswith("_models"):
        lane = _lane_by_key(name[5:-7], lanes)
        if not lane or lane.models_args is None:
            return [TextContent(type="text", text=f"[error] no model list for: {name}")]
        res = await runner.arun([lane.bin] + lane.models_args, 60)
        return [_emit(res.render(), label=f"list_{lane.key}_models")]

    return [TextContent(type="text", text=f"[error] unknown tool: {name}")]


async def _ask_cascade(lanes: list[LaneSpec], args: dict) -> list[TextContent]:
    # Thin glue: the cascade itself lives in council.py; inject the host couplings.
    return await council.ask_cascade(lanes, args, run_lane=_run_lane, emit=_emit)


async def _ask_best(lanes: list[LaneSpec], args: dict) -> list[TextContent]:
    # Thin glue: ask_best lives in council.py; inject the host couplings.
    return await council.ask_best(lanes, args, run_lane=_run_lane, emit=_emit)


def _rate_lane(lanes: list[LaneSpec], args: dict) -> list[TextContent]:
    """Record the host's quality score for a lane on a task-type (outcome-tracked routing). Pure
    dispatch glue: validates, writes via telemetry, reports the lane's new running average."""
    ln = _lane_by_key(_str(args, "lane"), lanes)
    if ln is None:
        return [TextContent(type="text", text=(
            f"[error] unknown lane '{_str(args, 'lane')}'. See `doctor` for lane keys."))]
    try:
        # args.get returns an untyped JSON-RPC value; the except IS the validation (None/str/etc).
        score = int(args.get("score"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return [TextContent(type="text", text="[error] score must be an integer 1..5.")]
    if not 1 <= score <= 5:
        return [TextContent(type="text", text="[error] score must be between 1 and 5.")]
    mode = _str(args, "mode").lower()
    if mode and mode not in router.MODES:
        return [TextContent(type="text", text=(
            f"[error] unknown mode '{mode}'. One of: {', '.join(router.MODES)} — or omit it."))]
    res = telemetry.rate_lane(ln.key, mode, score, _str(args, "note"))
    where = f" for mode '{mode}'" if mode else ""
    if res.get("n"):
        return [TextContent(type="text", text=(
            f"Recorded {score}/5 for {ln.key}{where}. Now {res['n']} rating(s), avg "
            f"{res['avg']}/5 — ask_best will weight {ln.key} accordingly for {mode or 'this'} tasks."))]
    return [TextContent(type="text", text=(
        f"Recorded {score}/5 for {ln.key}{where}, but telemetry is off "
        "(CLI_BRIDGE_TELEMETRY) so it won't steer routing."))]


def _set_lane_cost(args: dict) -> list[TextContent]:
    """Persist a cost fact the host learned (from the user's words or its own knowledge): set the
    lane's tier (+ optional why-note) in THIS process now, and merge it into the JSON config file
    so it survives restarts — the self-maintaining half of the cost policy. Uses all_lanes(), not
    the host-filtered list: the user may well be telling us about the HOST's own lane."""
    lane_key = _str(args, "lane")
    ln = _lane_by_key(lane_key, all_lanes())
    if ln is None:
        return [TextContent(type="text", text=(
            f"[error] unknown lane '{lane_key}'. See `doctor` for lane keys."))]
    cost = _str(args, "cost").lower()
    if cost not in {"free", "limited", "paid"}:
        return [TextContent(type="text", text="[error] cost must be free, limited or paid.")]
    note = _str(args, "note")[:200]
    if not note:
        # Anti-injection friction: every cost write must state its provenance. A delegate's
        # output can't quietly rewrite the policy through the host without leaving a why.
        return [TextContent(type="text", text=(
            "[error] note is required — one line saying who/what established this, e.g. "
            "'user: on the Go plan' or 'vendor: free tier sunset 2026-06-18'."))]
    env_key = ln.key.upper().replace("-", "_")
    shadowed = f"CLI_BRIDGE_{env_key}_COST" in config.ENV_PRESET_KEYS
    os.environ[f"CLI_BRIDGE_{env_key}_COST"] = cost          # effective immediately
    os.environ[f"CLI_BRIDGE_{env_key}_COST_NOTE"] = note
    fields: dict = {"cost": cost, "cost_note": note}
    path = config.update_config_file({ln.key: fields})
    persisted = (f"persisted to `{path}`" if path
                 else "applied for THIS session only — config file not writable")
    why = f" — {note}" if note else ""
    caveat = ""
    if shadowed and path:
        caveat = (f"\n⚠️ Your MCP host config/shell also sets CLI_BRIDGE_{env_key}_COST — env "
                  "wins at every restart, so that value will override this persisted one. "
                  "Remove it from the host config to let the config file apply.")
    return [TextContent(type="text", text=(
        f"Lane **{ln.key}** cost set to **{cost}** (set by you){why}. {persisted}. "
        "ask_all / ask_cascade / ask_best route on it from the next call." + caveat))]


def _echo_header(lane_key: str, model: str, task: str) -> str:
    """'▶ gemini · gemini-2.5-pro — asked: "…"' line prepended to delegation results, so the
    user re-reading the conversation in their CLI sees who was asked what next to the answer
    (no scrolling back to the tool-call args). CLI_BRIDGE_ECHO_TASK=off disables."""
    if not config.echo_task() or not task:
        return ""
    preview = " ".join(task.split())
    if len(preview) > 140:
        preview = preview[:140] + "…"
    who = f"{lane_key} · {model}" if model else lane_key
    return f'▶ {who} — asked: "{preview}"\n\n'


async def _ask_all(lanes: list[LaneSpec], args: dict) -> list[TextContent]:
    out = await _ask_all_body(lanes, args)
    return [_emit(_echo_header("council (ask_all)", "", _str(args, "task")) + out,
                  label="ask_all")]


async def _run_workflow_preset(args: dict, lanes: list[LaneSpec]) -> list[TextContent]:
    """Dispatch a `workflow` preset over the durable orchestrate substrate. Lane resolution +
    _run_lane are injected so orchestrate stays testable. Each preset returns a string report;
    async=true wraps it in a background job."""
    preset = _str(args, "preset")
    default_lanes = _ask_all_targets(lanes, _ask_all_include_paid(args))

    def _resolve(k):
        return _lane_by_key(k, lanes)

    common = dict(run_lane=_run_lane, resolve_lane=_resolve, default_lanes=default_lanes,
                  telemetry=telemetry, run_id=_str(args, "resume_id"))
    judge = _str(args, "judge_lane") or None
    if preset == "refine_plan":
        def make():
            return orchestrate.refine_plan(**common, plan_file=_str(args, "plan_file"),
                                           plan=_str(args, "plan"), lanes=args.get("lanes"),
                                           angles=args.get("angles"), judge_lane=judge)
    elif preset == "council_review":
        def make():
            return orchestrate.council_review(
                **common, question=_str(args, "question") or _str(args, "task"),
                lanes=args.get("lanes"), judge_lane=judge)
    elif preset == "map_review":
        def make():
            return orchestrate.map_review(**common, files=args.get("files") or [],
                                          lane=_str(args, "lane") or None, judge_lane=judge)
    elif preset == "research_verify":
        def make():
            return orchestrate.research_verify(**common, questions=args.get("questions") or [],
                                               lanes=args.get("lanes"))
    elif preset == "verify_repair":
        try:
            max_rounds = int(args.get("max_rounds") or 3)
        except (TypeError, ValueError):
            max_rounds = 3

        def make():
            # verify_repair is a sequential dependent loop (not a fan-out), so it does NOT use the
            # batch journal — pass only what it needs, not the durable **common.
            return orchestrate.verify_repair(
                run_lane=_run_lane, resolve_lane=_resolve, default_lanes=default_lanes,
                task=_str(args, "task"), builder_lane=_str(args, "builder_lane"),
                verifier_lane=_str(args, "verifier_lane"), max_rounds=max_rounds,
                cwd=_str(args, "cwd"), cross_family=bool(args.get("cross_family")))
    elif preset == "fanout_compare":
        def make():
            return orchestrate.fanout_compare(**common, task=_str(args, "task"),
                                              lanes=args.get("lanes"), judge_lane=judge,
                                              cwd=_str(args, "cwd"))
    elif preset == "jury":
        def make():
            return orchestrate.jury(
                **common, task=_str(args, "task"), author_lane=_str(args, "author_lane"),
                verifier_lanes=args.get("verifier_lanes"),
                verifiers=int(args.get("verifiers") or 0),
                threshold=int(args.get("threshold") or 0), cwd=_str(args, "cwd"))
    else:
        return [TextContent(type="text", text=f"[error] unknown preset: {preset or '(none)'}")]

    if bool(args.get("async")):
        job_id = jobs.start_job(f"workflow:{preset}", make, preview=preset)
        return [TextContent(type="text", text=(
            f"Workflow `{preset}` started: `{job_id}`. Poll `job_status {job_id}`, fetch "
            f"`job_result {job_id}`."))]
    return [_emit(await make(), label=f"workflow:{preset}")]


async def _ask_all_body(lanes: list[LaneSpec], args: dict) -> str:
    # Thin glue: the fan-out lives in council.py. Inject host couplings (run_lane/progress/
    # host_sample) and the cost-policy helpers that stay in server.py (shared by dispatch).
    return await council.ask_all_body(
        lanes, args, run_lane=_run_lane, progress=_emit_progress, host_sample=_host_sample,
        include_paid_fn=_ask_all_include_paid, targets_fn=_ask_all_targets,
        timeout_fn=_ask_all_timeout)


async def _review_diff(lanes: list[LaneSpec], args: dict) -> list[TextContent]:
    # Same cost policy as ask_all: free/non-limited reviewers unless the caller widens, and
    # never a cooled lane. Then hand off to the (decoupled, testable) workflow engine.
    include_paid = _ask_all_include_paid(args)
    targets = _ask_all_targets(lanes, include_paid)
    report = await workflows.review_diff(targets, args, _run_lane)
    return [_emit(report, label="review_diff")]


async def _doctor_deep(host: str, lanes: list[LaneSpec]) -> str:
    """doctor + a tiny live probe of each free, exposed lane to check auth/quota for real."""
    base = _doctor(host)
    probes = [ln for ln in lanes if not ln.is_paid and not ln.is_limited]
    if not probes:
        return base + "\n\n_(deep probe: no free lanes to test)_"
    async def _probe(ln):
        # terse=False: the probe wants the literal string "OK"; a style preamble would only
        # tempt the model to reformat it. (Also dodges the preamble's per-call overhead here.)
        res = await _run_lane(ln, {"task": "Reply with exactly: OK", "timeout_s": 60}, terse=False)
        mark = "✅ responds" if res.ok else f"❌ {res.kind}"
        ver = await _lane_version(ln)
        return f"- **{ln.key}**: {mark}{f' · v: {ver}' if ver else ''}"
    results = await asyncio.gather(*[_probe(ln) for ln in probes])
    flags = await _flag_drift_section(lanes)
    return (base + "\n\n## Deep probe (live auth check + CLI version, free lanes)\n\n"
            + "\n".join(results)
            + "\n\n_Versions help spot drift: if a CLI bumped and a lane breaks, file a `[drift]` issue._"
            + flags)


async def _lane_flag_drift(lane: LaneSpec) -> list[str]:
    """Flags this lane EMITS that are now MISSING from its `--help` (likely renamed/removed
    upstream → the invocation would break). Cheap: one `--help` spawn, no model call / quota.
    [] when there's nothing to check or help can't be read (never a false alarm)."""
    if not lane.help_args or not lane.probe_flags:
        return []
    res = await runner.arun([lane.bin, *lane.help_args], 15)
    if not res.ok:
        return []
    return lanes_mod.missing_flags(res.output, lane.probe_flags)


async def _flag_drift_section(lanes: list[LaneSpec]) -> str:
    """Check EVERY installed lane's flags against its CLI help (incl. limited/paid — it costs no
    quota, just `--help`). Surfaces a broken invocation BEFORE it fails silently at call time."""
    drifts = await asyncio.gather(*[_lane_flag_drift(ln) for ln in lanes])
    bad = [(ln, miss) for ln, miss in zip(lanes, drifts, strict=True) if miss]
    if not bad:
        return "\n\n## Flag check\n\n_All installed lanes' flags still present in their `--help`._"
    rows = [f"- ⚠️ **{ln.key}**: `{', '.join(miss)}` missing from `{ln.bin} "
            f"{' '.join(ln.help_args or [])}` — invocation may be broken (upstream flag change?)."
            for ln, miss in bad]
    return ("\n\n## ⚠️ Flag drift — lane invocation may be broken\n\n" + "\n".join(rows)
            + "\n\n_The CLI changed the flags this lane relies on. Update the lane (or pin an old "
            "CLI via `CLI_BRIDGE_<LANE>_BIN`), or file a `[drift]` issue._")


async def _lane_version(lane: LaneSpec) -> str:
    """Best-effort CLI version (first line of `<bin> --version`) — surfaces upstream drift."""
    if not lane.version_args:
        return ""
    res = await runner.arun([lane.bin, *lane.version_args], 15)
    if not res.ok:
        return ""
    first = (res.output or "").strip().splitlines()
    return first[0][:60] if first else ""


_SINCE_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def _parse_since(raw: str) -> float | None:
    """'24h' / '7d' / '90m' / bare seconds -> seconds. Empty/invalid -> None (all-time)."""
    s = (raw or "").strip().lower()
    if not s:
        return None
    m = re.fullmatch(r"(\d+)\s*([smhd])", s)
    if m:
        return int(m.group(1)) * _SINCE_UNITS[m.group(2)]
    try:
        return float(s)
    except ValueError:
        return None


def _render_usage(rep: dict) -> str:
    if not rep.get("enabled"):
        return ("Telemetry is off or unavailable (set CLI_BRIDGE_TELEMETRY=on, or it couldn't "
                "open its local DB). No usage to report.")
    window = f" (last {int(rep['since_s'])}s)" if rep.get("since_s") else ""
    lines = [f"# cli-bridge usage — {rep['total_runs']} total runs{window} (local only)",
             f"_tokens {rep['token_basis']}_", ""]
    lines.append("## By lane")
    for r in rep["by_lane"]:
        cred = f", ~{r['est_credits']} credits" if r.get("est_credits") is not None else ""
        lines.append(f"- **{r['lane']}**: {r['runs']} runs, {r['ok']} ok, ~{r['avg_ms']}ms avg, "
                     f"~{r['est_input_tokens']}+{r['est_output_tokens']} tok{cred}")
    if rep.get("est_total_credits") is not None:
        lines.append(f"\n_Estimated total credits: ~{rep['est_total_credits']}._")
    lines.append("\n## Recent")
    for r in rep["recent"]:
        lines.append(f"- {r['lane'] or r['tool']} [{r['status']}/{r['kind']}] "
                     f"{r['duration_ms']}ms — {r['task']}")
    return "\n".join(lines)


def _render_budget(rep: dict) -> str:
    if not rep.get("enabled"):
        return "Telemetry is off or unavailable. No budget to report."
    if not rep["by_lane"]:
        return "No runs today (since UTC midnight)."
    lines = ["# Today's usage (since UTC midnight) — estimated", ""]
    for r in rep["by_lane"]:
        limit = (f"{r['runs_today']}/{r['daily_limit']}" if r["daily_limit"] is not None
                 else f"{r['runs_today']} (no limit set)")
        cred = f", ~{r['est_credits_today']} credits" if r.get("est_credits_today") is not None else ""
        flag = "  ⚠️ LIMIT REACHED (further spawns blocked today)" if r["over_limit"] else ""
        lines.append(f"- **{r['lane']}**: {limit} runs, ~{r['est_tokens_today']} tok{cred}{flag}")
    lines.append("\n_CLI_BRIDGE_<LANE>_DAILY_LIMIT is enforced at spawn (any lane). "
                 "_CREDITS_PER_1K makes CLI_BRIDGE_DAILY_CREDIT_CAP enforceable — docs/BUDGET.md._")
    return "\n".join(lines)


def _render_job_status(st: dict) -> str:
    lines = [f"Job `{st['id']}` — **{st['status']}** ({st.get('kind', 'ask_all')})"]
    if st.get("preview"):
        lines.append(f"_task: {st['preview']}_")
    if st.get("kind") == "build" and st.get("turn") is not None:
        lines.append(f"turn {st['turn']}/{st.get('max_turns', '?')} · "
                     f"{st.get('files_changed', 0)} files changed in zone `{st.get('zone', '')}` · "
                     f"{st.get('queued_steers', 0)} steer(s) queued")
        if st.get("note"):
            lines.append(f"_{st['note']}_")
    if st.get("error"):
        lines.append(f"error: {st['error']}")
    if st["status"] == jobs.SUCCEEDED:
        lines.append(f"Fetch it with `job_result {st['id']}`.")
    elif st["status"] == jobs.RUNNING:
        if st.get("kind") == "build":
            lines.append(f"Follow with `job_tail {st['id']}`, steer with `build_steer {st['id']}`.")
        else:
            lines.append("Still running — poll again shortly.")
    return "\n".join(lines)


def _render_jobs_list(rows: list[dict]) -> str:
    if not rows:
        return "No async jobs yet. Start one with `ask_all_async`."
    lines = ["# Async jobs", ""]
    for r in rows:
        prev = f" — {r['preview']}" if r.get("preview") else ""
        lines.append(f"- `{r['id']}` **{r['status']}** ({r['kind']}){prev}")
    return "\n".join(lines)


def _render_lane_stats() -> str:
    stats = telemetry.lane_stats()
    if not stats:
        return "No lane stats yet (telemetry off, or no runs recorded)."
    by_key = {ln.key: ln for ln in all_lanes()}
    seat = telemetry.seat_report()
    lines = ["# Lane health", ""]
    for s in stats:
        cd = f", cooldown {s['cooldown_remaining_s']}s" if s["cooldown_remaining_s"] else ""
        lines.append(
            f"- **{s['lane']}**: {s['total_runs']} runs, {s['total_failures']} failed, "
            f"{s['consecutive_failures']} consecutive fail, last={s['last_kind']}{cd}")
        # "Earn their seat" (Lens B, advisory): how a lane votes as a jury verifier over time —
        # shown beside the latency/error stats above (Lens A), never auto-applied to routing.
        sr = seat.get(s["lane"])
        if sr and sr["n_votes"]:
            parts = []
            if sr["accuracy_rate"] is not None:
                parts.append(f"accuracy {sr['accuracy_rate']:.0%} (eval, vs ground truth)")
            if sr["conformity_rate"] is not None:
                parts.append(f"conformity {sr['conformity_rate']:.0%} "
                             "(live — agreement with the verdict, NOT accuracy)")
            if parts:
                lines.append(f"  - ↳ jury seat: {sr['n_votes']} votes · " + "; ".join(parts))
        # Burst rate-limiting pattern (failures interleaved with successes never trip the
        # cooldown): point at the opt-in pacer instead of leaving the lane to die quietly.
        ln = by_key.get(s["lane"])
        if (s["last_kind"] in {"empty", "quota"} and s["total_failures"] >= 5
                and ln is not None and ln.min_interval_s <= 0):
            env_key = s["lane"].upper().replace("-", "_")
            lines.append(f"  - ↳ looks rate-limited under bursts — consider spawn pacing: "
                         f"`CLI_BRIDGE_{env_key}_MIN_INTERVAL_S=2`")
    return "\n".join(lines)


def _doctor(host: str) -> str:
    lines = ["# cli-bridge - health check", ""]
    host_note = ("its own lane is hidden (CLI_BRIDGE_HIDE_HOST)" if config.hide_host()
                 else "its own lane is shown (direct calls only, never in fan-out)")
    lines.append(f"Host (caller): **{host or 'unknown'}** - {host_note}.")
    if _profile_is_set():
        prof = _profile()
    elif _cost_config_is_set():
        prof = _profile() + " (default profile; per-lane costs set)"
    else:
        prof = _profile() + " (default — run `setup` to configure)"
    lines.append(f"Cost profile: **{prof}**")
    cap = config.daily_credit_cap()
    if cap > 0:
        unrated = [ln.key for ln in lanes_mod.all_lanes()
                   if ln.is_paid and config.lane_env_float(ln.key, "CREDITS_PER_1K") is None]
        if unrated:
            lines.append(f"⚠️ _CLI_BRIDGE_DAILY_CREDIT_CAP={cap:g} is set but UNENFORCEABLE for "
                         f"paid lane(s) {', '.join(unrated)} — their spend always estimates to 0. "
                         "Set CLI_BRIDGE_<LANE>_CREDITS_PER_1K (suggestions in docs/COSTS.md)._")
    lines.append("_Cost tiers are NOT detected from your account — '(default)' = a sourced "
                 "typical-plan default (docs/COSTS.md); '(set by you)' = your own setting._")
    if lanes_mod.cost_facts_stale():
        lines.append(f"⚠️ _Cost facts last verified {lanes_mod.COST_FACTS_VERIFIED} "
                     f"({lanes_mod.cost_facts_age_days()} days ago) — plans/quotas churn fast; "
                     "re-check docs/COSTS.md against the vendor pages before trusting defaults._")
    lines.append("")
    for lane in all_lanes():
        installed = is_installed(lane)
        mark = "installed" if installed else "NOT on PATH"
        if not lane.enabled:
            mark += " (disabled by env)"
        hidden = ((" - hidden (this is the host)" if config.hide_host()
                   else " - this is the host (shown; never in fan-out)")
                  if _is_host(lane, host) else "")
        cost_env_key = f"CLI_BRIDGE_{lane.key.upper()}_COST"
        if not lane.cost_is_configured:
            src = "default — yours may differ"
        elif cost_env_key in config.ENV_PRESET_KEYS:
            src = "set by you: host env — wins over the config file"
        else:
            src = "set by you: config file"
        paid = f" - {lane.cost_label} ({src})"
        exp = " - experimental" if lane.experimental else ""
        model = lane.model_for("")
        default = f" - default model: {model}" if model else ""
        lines.append(f"- **{lane.key}** ({lane.bin}) - {mark}{paid}{exp}{hidden}{default}")
        if installed and lane.sunset:
            from datetime import date
            try:
                left = (date.fromisoformat(lane.sunset) - date.today()).days
            except ValueError:
                left = None
            if lane.sunset_passed():
                alts = " / ".join(lane.bin_alts) or "none"
                lines.append(f"  - ⚠️ _free tier SUNSET {lane.sunset}: a 'free' default now "
                             f"degrades to 'limited' and the spawn prefers `{alts}` over "
                             f"`{lane.bin_default}`. Set CLI_BRIDGE_{lane.key.upper()}_COST "
                             "to override._")
                if lane.cost_is_configured and lane.cost_label == "free":
                    lines.append(f"  - ⚠️ _your CLI_BRIDGE_{lane.key.upper()}_COST=free may "
                                 "predate this sunset — re-check that the free tier still "
                                 "exists on your plan._")
            elif left is not None and left <= 14:
                lines.append(f"  - ⚠️ _free tier sunsets {lane.sunset} (in {left} day"
                             f"{'s' if left != 1 else ''}) — after that the lane degrades to "
                             "'limited' and prefers its successor binary automatically._")
        if not installed and lane.install_hint:
            lines.append(f"  - _install: {lane.install_hint}_")
        if installed and lane.cost_note_effective:
            lines.append(f"  - _{lane.cost_note_effective}_")
        daily_limit = config.lane_env_int(lane.key, "DAILY_LIMIT")
        if installed and daily_limit is not None:
            lines.append(f"  - _daily run limit: {telemetry.lane_runs_today(lane.key)}/"
                         f"{daily_limit} today (UTC; enforced at spawn)_")
        if not lane.is_paid and lanes_mod.is_paid_opencode_model(model):
            lines.append(f"  - ⚠️ **cost mismatch**: lane is '{lane.cost_label}' but its model "
                         f"`{model}` spends money/credits — set `CLI_BRIDGE_"
                         f"{lane.key.upper()}_COST=paid` or pick an `opencode/*-free` model.")
    rstat = preamble.roles_file_status()
    if rstat["path"]:
        if rstat["error"]:
            lines.append(f"\n⚠️ **Roles file NOT loaded** ({rstat['path']}): {rstat['error']} — "
                         "running with built-in roles only.")
        else:
            note = f"\nRoles file: {len(rstat['roles'])} custom role(s) loaded from {rstat['path']}"
            if rstat["overrides"]:
                note += f" (overriding built-in: {', '.join(sorted(rstat['overrides']))})"
            if rstat["dropped"]:
                note += f" — ⚠️ dropped non-string entr{'ies' if len(rstat['dropped']) != 1 else 'y'}: " \
                        f"{', '.join(rstat['dropped'])}"
            lines.append(note + ".")
    risky = lanes_mod.LANES_LOAD_STATUS.get("argv_secret_risk") or []
    if risky:
        lines.append(f"\n⚠️ **Secret in argv** — custom lane(s) {', '.join(risky)} expand a "
                     "${ENV} key into the command line, visible in `ps` while the call runs. "
                     "Safe pattern (curl ≥ 8.3): `--variable %MY_KEY` + `--expand-header "
                     "\"Authorization: Bearer {{MY_KEY}}\"` keeps the secret out of argv — "
                     "see examples/free-apis.json.")
    lines.append("\nPer-lane config (your plan): CLI_BRIDGE_<LANE>_COST=free|limited|paid, "
                 "_ENABLED=false, _BIN=<path>, _MODEL=<id>, _DAILY_LIMIT=<runs/day> "
                 "(enforced at spawn — the simplest cap, works for every lane).")
    lines.append("Add your own CLI via a JSON file in CLI_BRIDGE_LANES_FILE - no code changes.")
    return "\n".join(lines)


def main() -> None:
    config.apply_file_config_to_env()   # JSON config fills any unset env var (env still wins)
    # Any job left 'running' in the DB is from a previous process whose delegates are gone —
    # flip it to 'interrupted' so its status is honest (v1 doesn't resume work across restarts).
    jobs.mark_interrupted_on_startup()
    async def _serve() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
