"""Tool-schema assembly for the MCP surface.

`_tools_for()` builds the full `Tool` list (one `ask_<lane>` per installed lane plus the council/
workflow/diagnostic tools); `_filter_tools()` applies the LEAN core / ENABLED / DISABLED knobs.
Pulled out of server.py (which only wires these into `@list_tools`) to keep the dispatch module
thin. Pure: depends on config/router/findings/orchestrate/preamble + the lane registry, never on
server.py.
"""
from __future__ import annotations

from typing import cast

from mcp.types import Tool, ToolAnnotations

from . import config, findings, orchestrate, preamble, router
from .config import ASK_ALL_MAX_TIMEOUT_S, DEFAULT_TIMEOUT_S, MAX_TIMEOUT_S
from .lanes import LaneSpec


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
                         "description": "Round-table thread (multi-turn memory). Omit = auto-thread: "
                         "the ask still gets a fresh id you can reuse later to continue (no replay "
                         "on this turn). 'new' is the same, explicit. Pass an existing id — even from "
                         "a DIFFERENT lane — to continue that thread. Survives the host's context "
                         "reset (/compact)."},
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
                         "side by side to pick/merge. converge: governance loop — an author drafts, "
                         "an independent ARBITER commits a BLIND verdict, anonymized cross-family "
                         "peers review, the arbiter adjudicates every issue WITH A REASON, then "
                         "revise-or-converge; converges only if the peers (not the arbiter alone) "
                         "approve and no blocker remains. All resumable (resume_id) and async-able."),
            inputSchema={
                "type": "object",
                "properties": {
                    "preset": {"type": "string",
                               "enum": ["refine_plan", "council_review", "map_review",
                                        "research_verify", "verify_repair", "fanout_compare",
                                        "jury", "converge"],
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
                                   f"(default 3); converge: review->revise rounds (default 5); "
                                   f"max {orchestrate.VERIFY_MAX_ROUNDS}."},
                    "cross_family": {"type": "boolean",
                                     "description": "verify_repair: pick the verifier from a "
                                     "DIFFERENT vendor family (default false)."},
                    "author_lane": {"type": "string",
                                    "description": "jury / converge: lane that drafts the answer "
                                    "(default: first council lane)."},
                    "arbiter_lane": {"type": "string",
                                     "description": "converge: the independent decider that gives "
                                     "the blind verdict + adjudicates (default: a cross-family lane)."},
                    "peer_lanes": {"type": "array", "items": {"type": "string"},
                                   "description": "converge: explicit peer reviewer lanes (default: "
                                   "cross-family, distinct from author + arbiter)."},
                    "verifier_lanes": {"type": "array", "items": {"type": "string"},
                                       "description": "jury: explicit verifier lanes (default: "
                                       "auto-picked from DIFFERENT vendor families than the author)."},
                    "verifiers": {"type": "integer",
                                  "description": "jury verifiers / converge peers — how many "
                                  "(default min(3, pool))."},
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
