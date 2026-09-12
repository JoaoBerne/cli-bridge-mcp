"""Tool-schema assembly for the MCP surface.

`_tools_for()` builds the full `Tool` list (one `ask_<lane>` per installed lane plus the council/
workflow/diagnostic tools); `_filter_tools()` applies the one CLI_BRIDGE_TOOLS knob.
Pulled out of server.py (which only wires these into `@list_tools`) to keep the dispatch module
thin. Pure: depends on config/router/findings/orchestrate/preamble + the lane registry, never on
server.py.
"""
from __future__ import annotations

from typing import cast

from mcp.types import Tool, ToolAnnotations

from . import config, findings, orchestrate, preamble, router
from .config import ASK_ALL_MAX_TIMEOUT_S, DEFAULT_TIMEOUT_S, MAX_TIMEOUT_S
from .lanes import LaneSpec, known_models
from .mcp_compat import from_wire

# Model ids named inline in the `model` parameter. Enough to show what a lane offers without
# swamping the schema — lanes with hundreds of models point at their list tool for the rest.
_MODELS_IN_SCHEMA = 8

# Parameters many tools share — declared once so every schema says the same thing. A site whose
# meaning differs (a shorter cap, a preset-specific task) overrides the description in place.
_P: dict[str, dict] = {
    "task": {"type": "string", "description": "The prompt / task."},
    "cwd": {"type": "string",
            "description": "Directory the CLI runs in (empty = host workspace root, else server "
                           "launch dir)."},
    "timeout_s": {"type": "integer",
                  "description": f"Seconds before kill (default {DEFAULT_TIMEOUT_S}, max "
                                 f"{MAX_TIMEOUT_S})."},
    "include_paid": {"type": "boolean",
                     "description": "Also use limited/paid lanes. Default false except "
                                    "CLI_BRIDGE_PROFILE=max (refused under saver)."},
    "lane": {"type": "string", "description": "Lane key (e.g. gemini, gpt, opencode)."},
    "dry_run": {"type": "boolean",
                "description": "Preview (lanes/order/cost/files that would be sent) WITHOUT "
                               "spawning anything."},
    "output_format": {"type": "string", "enum": ["markdown", "json"],
                      "description": "markdown (default) or json."},
    "base": {"type": "string",
             "description": "git ref/range to diff against (default HEAD): 'main', 'HEAD~3', "
                            "'main...HEAD'."},
    "diff": {"type": "string", "description": "Use this diff text instead of running git."},
    "async": {"type": "boolean",
              "description": "Run as a background job; returns a job_id (manage with `job`)."},
    "summary_only": {"type": "boolean",
                     "description": "Return only the recap/verdict, not each lane's full answer "
                                    "— fewer tokens. Default false."},
    "resume_id": {"type": "string",
                  "description": "A run_id from a previous run — replays the finished tasks from "
                                 "the journal, runs the rest."},
}


def _ask_schema(lane: LaneSpec) -> dict:
    props: dict = {
        "task": _P["task"],
        "cwd": _P["cwd"],
        "timeout_s": _P["timeout_s"],
        "conversation": {"type": "string",
                         "description": "Round-table thread (multi-turn memory). Omit = auto-thread: "
                         "the ask still gets a fresh id you can reuse later to continue (no replay "
                         "on this turn). 'new' is the same, explicit. Pass an existing id — even from "
                         "a DIFFERENT lane — to continue that thread. Survives the host's context "
                         "reset (/compact)."},
    }
    if "model" in lane.caps:
        # Name the models this ACCOUNT may actually use, right where the choice is made. Without
        # it a caller defaults to whatever the CLI is configured for and never learns the plan
        # already includes something better — a silent capability loss, not an error.
        avail, _ = known_models(lane)
        # Capped, not dumped: one lane lists 172 models and another 400+, which would bury the
        # rest of the schema. A handful names the shape of what's there; the list tool has the rest.
        shown = ", ".join(avail[:_MODELS_IN_SCHEMA])
        more = len(avail) - _MODELS_IN_SCHEMA
        props["model"] = {"type": "string",
                          "description": "Model override. Empty = the lane's default."
                          + (f" Available to YOU: {shown}"
                             + (f" (+{more} more — call list_models(lane=\"{lane.key}\"))."
                                if more > 0 else ".") if avail else "")
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
    if "images" in lane.caps:
        how = (f"as `{lane.image_arg} <path>` arguments" if lane.image_arg.startswith("-")
               else "as path references in the prompt")
        props["images"] = {"type": "array", "items": {"type": "string"},
                           "description": f"Image file paths to include (vision, ban-safe — passed "
                           f"to the CLI {how}). Experimental: whether the image is actually READ "
                           "depends on the model behind the lane, not the lane itself."}
    return {"type": "object", "properties": props, "required": ["task"]}


def _ann(**kw: bool) -> ToolAnnotations:
    """The MCP SDK types Tool(annotations=) as ToolAnnotations|None but accepts a plain dict of
    hints at runtime (pydantic coerces). This wraps the hint kwargs in that cast in ONE place, so
    the ~40 tool sites stay readable AND mypy keeps flagging REAL arg-type errors elsewhere
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
        tools.append(from_wire(Tool,
            name=f"ask_{lane.key}",
            description=f"Consult {lane.display}. {lane.note}{paid}{limited}{exp}",
            inputSchema=_ask_schema(lane),
            annotations=_ann(readOnlyHint=not can_write, openWorldHint=True,
                             destructiveHint=can_write),
        ))
    if lanes:
        tools.append(from_wire(Tool,
            name="ask_all",
            description=("Fan-out: ask the SAME question to every available lane in parallel and "
                         "get all answers side by side. Free, non-limited lanes only by default."),
            inputSchema={
                "type": "object",
                "properties": {
                    "task": _P["task"],
                    "include_paid": _P["include_paid"],
                    "cwd": _P["cwd"],
                    "timeout_s": {**_P["timeout_s"],
                                  "description": f"Per-lane timeout (max {ASK_ALL_MAX_TIMEOUT_S} — "
                                                 "the fan-out must finish before the host's own "
                                                 "tool deadline; call one lane directly for a "
                                                 "longer run)."},
                    "synthesize": {"type": "boolean",
                                   "description": "After collecting answers, have one free lane "
                                   "summarize where the models AGREE and DISAGREE. Default false."},
                    "summary_only": _P["summary_only"],
                    "output_format": _P["output_format"],
                    "dry_run": _P["dry_run"],
                    "async": _P["async"],
                },
                "required": ["task"],
            },
            annotations=_ann(readOnlyHint=True, openWorldHint=True, destructiveHint=False),
        ))
        tools.append(from_wire(Tool,
            name="job",
            description=("Manage background jobs (ask_all / workflow / batch_run / ask_build with "
                         "async=true). status: running | succeeded | failed | cancelled | "
                         "interrupted (+ live build progress). result: the finished output "
                         "(spills to a file if huge; a 'still running' note if not done). cancel: "
                         "kill the delegates' process groups. list: recent jobs. tail: a running "
                         "build's progress log from `offset` (0 first, then the offset returned). "
                         "steer: queue an `instruction` for a build's NEXT turn and/or "
                         "interrupt=true to cut the current turn (files written so far are kept)."),
            inputSchema={"type": "object", "properties": {
                "action": {"type": "string",
                           "enum": ["status", "result", "cancel", "list", "tail", "steer"],
                           "description": "What to do."},
                "job_id": {"type": "string",
                           "description": "The job id (e.g. job_ab12…) — every action but list."},
                "offset": {"type": "integer", "description": "tail: byte offset to read from."},
                "instruction": {"type": "string",
                                "description": "steer: what to change/do next (optional if only "
                                               "interrupting)."},
                "interrupt": {"type": "boolean",
                              "description": "steer: cut the current turn now (default false)."},
            }, "required": ["action"]},
            annotations=_ann(readOnlyHint=False, destructiveHint=False),
        ))
        tools.append(from_wire(Tool,
            name="batch_run",
            description=("Durable fan-out: run many INDEPENDENT asks in parallel (capped) in ONE "
                         "call instead of N — saves your context and quota. Each result is "
                         "journalled, so resume_id replays the tasks that already finished and "
                         "runs only the rest (survives a restart). YOU compose the logic; this "
                         "just executes it durably. async=true returns a job_id (manage with "
                         "`job`)."),
            inputSchema={
                "type": "object",
                "properties": {
                    "tasks": {"type": "array", "description": "Independent tasks to run.",
                              "items": {"type": "object", "properties": {
                                  "task": _P["task"],
                                  "lane": _P["lane"],
                                  "model": {"type": "string"},
                                  "effort": {"type": "string"},
                                  "cwd": _P["cwd"],
                                  "timeout_s": _P["timeout_s"]},
                                  "required": ["task"]}},
                    "max_concurrency": {"type": "integer",
                                        "description": "Cap simultaneous spawns (default: profile)."},
                    "max_calls": {"type": "integer",
                                  "description": "Invocation budget: stop after this many spawns; "
                                  "the rest are skipped (resume with a higher cap to run them)."},
                    "max_credits": {"type": "number",
                                    "description": "Invocation budget: skip tasks once estimated "
                                    "credits would exceed this (free lanes never blocked)."},
                    "dry_run": _P["dry_run"],
                    "resume_id": _P["resume_id"],
                    "async": _P["async"],
                },
                "required": ["tasks"],
            },
            annotations=_ann(readOnlyHint=False, openWorldHint=True, destructiveHint=False),
        ))
        tools.append(from_wire(Tool,
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
                         "approve and no blocker remains. premortem: each lane imagines the plan "
                         "FAILED and lists failure modes + mitigations, merged into a ranked risk "
                         "list — run BEFORE building. test_plan: behaviours/edge cases + concrete "
                         "test cases from a git diff (default: working tree) or a description. "
                         "challenge: anti-sycophancy — ONE outside lane critically reassesses a "
                         "claim (pressure-test your own conclusion). All resumable (resume_id) "
                         "and async-able."),
            inputSchema={
                "type": "object",
                "properties": {
                    "preset": {"type": "string",
                               "enum": ["refine_plan", "council_review", "map_review",
                                        "research_verify", "verify_repair", "fanout_compare",
                                        "jury", "converge", "premortem", "test_plan", "challenge"],
                               "description": "Which workflow to run."},
                    "plan_file": {"type": "string",
                                  "description": "refine_plan: path to the plan (PREFERRED — read "
                                  "by each lane, never recopied)."},
                    "plan": {"type": "string", "description": "refine_plan: inline plan (fallback)."},
                    "angles": {"type": "array", "items": {"type": "string"},
                               "description": "refine_plan: override the critique angles."},
                    "question": {"type": "string", "description": "council_review: the question."},
                    "task": {**_P["task"],
                             "description": "verify_repair / fanout_compare: the task to run. "
                                            "premortem: the plan. challenge: the claim. test_plan: "
                                            "describe the change (or omit to use the git diff)."},
                    "base": _P["base"],
                    "diff": _P["diff"],
                    "timeout_s": _P["timeout_s"],
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
                    "lane": {"type": "string",
                             "description": "map_review / challenge: the single lane (challenge "
                                            "default: a free one)."},
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
                    "cwd": _P["cwd"],
                    "judge_lane": {"type": "string",
                                   "description": "Optional: one lane dedupes + ranks the pooled "
                                   "findings into a single list (else grouped for you to merge). "
                                   "fanout_compare: recommends one option."},
                    "include_paid": _P["include_paid"],
                    "resume_id": _P["resume_id"],
                    "async": _P["async"],
                },
                "required": ["preset"],
            },
            annotations=_ann(readOnlyHint=False, openWorldHint=True, destructiveHint=False),
        ))
        tools.append(from_wire(Tool,
            name="conversations",
            description="Round-table threads. No id: list recent threads (id, lanes, turns, last "
                        "activity, preview) — recover a thread after /compact. With id: the full "
                        "transcript, every turn attributed by lane.",
            inputSchema={"type": "object", "properties": {
                "id": {"type": "string", "description": "The thread id (omit to list)."}},
                "required": []},
            annotations=_ann(readOnlyHint=True, destructiveHint=False),
        ))
        tools.append(from_wire(Tool,
            name="list_models",
            description="List the models reachable through a lane so you can pick one. If that "
                        "CLI has no list command, shows its default model + how to choose. Pass "
                        "`lane` (e.g. opencode, mistral, gpt).",
            inputSchema={"type": "object", "properties": {"lane": _P["lane"]},
                         "required": ["lane"]},
            annotations=_ann(readOnlyHint=True, destructiveHint=False),
        ))
    tools.append(from_wire(Tool,
        name="doctor",
        description="Health check: which CLIs are installed, which is the host, paid lanes, "
                    "defaults, current cost profile. Pass deep=true to also probe each lane with a "
                    "tiny live call (checks auth/quota — uses a bit of free quota; skips paid lanes).",
        inputSchema={"type": "object", "properties": {
            "deep": {"type": "boolean", "description": "Live-probe each free lane's auth."}}},
        annotations=_ann(readOnlyHint=True, destructiveHint=False),
    ))
    tools.append(from_wire(Tool,
        name="setup",
        description="Show the cost-profile choice (saver/balanced/max) to walk the user through "
                    "configuring how cli-bridge spends paid credits/quota. Call this on first use "
                    "if the profile isn't set, ASK the user, then tell them how to set it.",
        inputSchema={"type": "object", "properties": {}},
        annotations=_ann(readOnlyHint=True, destructiveHint=False),
    ))
    tools.append(from_wire(Tool,
        name="reset_lane_state",
        description="Clear a lane's cooldown + failure counters (e.g. after you re-logged in or "
                    "your quota reset). Pass the lane key, e.g. 'gemini'.",
        inputSchema={"type": "object", "properties": {"lane": _P["lane"]}, "required": ["lane"]},
        annotations=_ann(readOnlyHint=False, destructiveHint=False),
    ))
    if lanes:
        tools.append(from_wire(Tool,
            name="ask_cascade",
            description="Ask ONE model but with automatic fallback: tries lanes cheapest→strongest, "
                        "skipping cooled ones, and moves to the next on quota/auth/timeout/failure. "
                        "Returns the first success (and a note of what was tried). Use this for plain "
                        "cheapest-first; use `ask_best` to route by mode/your ratings. "
                        "Free/non-limited by default; include_paid to widen.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task": _P["task"],
                    "include_paid": _P["include_paid"],
                    "cwd": _P["cwd"],
                    "timeout_s": _P["timeout_s"],
                    "dry_run": _P["dry_run"],
                },
                "required": ["task"],
            },
            annotations=_ann(readOnlyHint=True, openWorldHint=True, destructiveHint=False),
        ))
        tools.append(from_wire(Tool,
            name="ask_best",
            description=("Ask the BEST lane for the job: pick one lane by `mode` (fast/cheap/deep/"
                         "code/review/security) using cost, health and measured latency, then run "
                         "it with automatic fallback. Use this when you don't want to choose a "
                         "lane yourself. (Use ask_all to COMPARE many; ask_cascade for plain "
                         "cheapest-first reliability.)"),
            inputSchema={
                "type": "object",
                "properties": {
                    "task": _P["task"],
                    "mode": {"type": "string", "enum": list(router.MODES),
                             "description": "fast=low latency · cheap=free only (default) · "
                                            "deep/code=stronger lanes · review/security=capable "
                                            "lane. paid lanes only if include_paid/profile allows."},
                    "include_paid": _P["include_paid"],
                    "cwd": _P["cwd"],
                    "timeout_s": _P["timeout_s"],
                    "dry_run": _P["dry_run"],
                },
                "required": ["task"],
            },
            annotations=_ann(readOnlyHint=True, openWorldHint=True, destructiveHint=False),
        ))
        tools.append(from_wire(Tool,
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
                    "lane": _P["lane"],
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
        tools.append(from_wire(Tool,
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
                    "lane": _P["lane"],
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
        tools.append(from_wire(Tool,
            name="review_diff",
            description=("Multi-model code review of a git diff: several lanes review in parallel "
                         "with DIFFERENT focuses (correctness/security/tests/maintainability), "
                         "then one lane merges + dedupes into a ranked Markdown report. "
                         "Reviews working-tree changes by default. Free/non-limited lanes only "
                         "unless include_paid. A deliberately longer call than ask_all."),
            inputSchema={
                "type": "object",
                "properties": {
                    "focus": {"type": "string", "enum": ["code", "security"],
                              "description": "code (default): correctness/design review. security: "
                                             "OWASP-style review — lanes split across injection / "
                                             "auth & access control / secrets & crypto / data "
                                             "exposure & SSRF, with the security role set."},
                    "cwd": {"type": "string",
                            "description": "Repo dir to run `git diff` in (default: host launch dir)."},
                    "base": _P["base"],
                    "diff": _P["diff"],
                    "include_paid": _P["include_paid"],
                    "output_format": _P["output_format"],
                    "severity_filter": {"type": "string", "enum": list(findings.SEVERITIES),
                                        "description": "Only show findings at or above this "
                                        "severity (blocker>high>medium>low>info). Default: all."},
                    "timeout_s": {**_P["timeout_s"],
                                  "description": f"Per-reviewer timeout (default "
                                                 f"{config.REVIEW_DEFAULT_TIMEOUT_S}, max "
                                                 f"{MAX_TIMEOUT_S})."},
                },
                "required": [],
            },
            annotations=_ann(readOnlyHint=True, openWorldHint=True, destructiveHint=False),
        ))
        build_lanes = [ln for ln in lanes if "agent" in ln.caps]
        if build_lanes:
            tools.append(from_wire(Tool,
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
                             "(job action=tail/steer, DoD gate). Greenfield dirs are created "
                             "and git-initialised."),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "task": _P["task"],
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
                                  "returns a job_id; follow with job(action=tail), steer with "
                                  "job(action=steer) (and interrupt), fetch with "
                                  "job(action=result). Enables multi-turn + DoD."},
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
                        "timeout_s": _P["timeout_s"],
                    },
                    "required": ["task"],
                },
                annotations=_ann(readOnlyHint=False, openWorldHint=True,
                                 destructiveHint=True),   # direct mode writes the real repo
            ))
        tools.append(from_wire(Tool,
            name="debate",
            description=("Multi-model debate: each lane answers the question, then sees the "
                         "others and REVISES over a bounded number of rounds, then a judge "
                         "writes the final conclusion (consensus + remaining disagreement). "
                         "Good for hard/contested questions. vote=borda instead SELECTS the "
                         "peer-ranked best blind answer (no rounds). Free/non-limited lanes "
                         "unless include_paid; bounded to a few debaters to cap cost."),
            inputSchema={
                "type": "object",
                "properties": {
                    "task": _P["task"],
                    "vote": {"type": "string", "enum": ["judge", "borda"],
                             "description": "judge (default): revision rounds then an independent "
                                            "judge concludes. borda: NO rounds — blind answers, each "
                                            "lane ranks the ANONYMIZED set, Borda count SELECTS the "
                                            "peer-ranked #1 (selection beats synthesis). rounds/"
                                            "adversarial/steelman/fact_check ignored under borda."},
                    "synthesize": {"type": "boolean",
                                   "description": "borda only: a chairman BLENDS the answers "
                                                  "instead of returning the winner verbatim "
                                                  "(weaker; default false)."},
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
                    "summary_only": _P["summary_only"],
                    "allow_self_judge": {"type": "boolean",
                                         "description": "Let the judge also debate (default: "
                                         "with 3+ lanes one lane is held out to judge "
                                         "independently)."},
                    "steelman": {"type": "boolean",
                                 "description": "If the verdict is unanimous, one lane argues "
                                 "the strongest case AGAINST it and the judge re-concludes "
                                 "(anti-echo-chamber bonus round). Default false."},
                    "dry_run": _P["dry_run"],
                    "include_paid": _P["include_paid"],
                    "cwd": _P["cwd"],
                    "timeout_s": _P["timeout_s"],
                },
                "required": ["task"],
            },
            annotations=_ann(readOnlyHint=True, openWorldHint=True, destructiveHint=False),
        ))
        tools.append(from_wire(Tool,
            name="git_text",
            description=("Read-only git → text via one lane. kind=commit: Conventional Commit "
                         "message from the STAGED diff (falls back to the working tree). kind=pr: "
                         "title + Summary/Changes/Testing from branch diff + log vs base (default "
                         "origin/main, then main). Never commits."),
            inputSchema={
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["commit", "pr"],
                             "description": "commit message or PR description."},
                    "base": {"type": "string",
                             "description": "pr only: base ref to diff against (default origin/main)."},
                    "cwd": _P["cwd"],
                    "lane": {**_P["lane"], "description": "Which lane (default: a free one)."},
                    "timeout_s": _P["timeout_s"],
                },
                "required": ["kind"],
            },
            annotations=_ann(readOnlyHint=True, openWorldHint=True, destructiveHint=False),
        ))
    return tools


def _host_ask_tool(lane: LaneSpec) -> Tool:
    """ask_<host>: the caller's own lane is visible and callable like any other (model optional).
    It still stays out of ask_all/ask_cascade fan-out."""
    can_write = "agent" in lane.caps
    return from_wire(Tool,
        name=f"ask_{lane.key}",
        description=(f"Consult {lane.display} — your own lane (e.g. a fresh instance, or a sibling "
                     f"model via `model`). Kept out of ask_all/ask_cascade fan-out. {lane.note}"),
        inputSchema=_ask_schema(lane),
        annotations=_ann(readOnlyHint=not can_write, openWorldHint=True,
                         destructiveHint=can_write),
    )


# The default surface — what a host sees with CLI_BRIDGE_TOOLS unset (plus every ask_<lane>).
# The rest (batch_run, reset_lane_state) is opt-in: CLI_BRIDGE_TOOLS=all, or named in a list.
DEFAULT_TOOLS = frozenset({"ask_all", "ask_cascade", "ask_best", "ask_build", "review_diff", "debate",
                           "workflow", "git_text", "job", "conversations", "list_models",
                           "rate_lane", "set_lane_cost", "doctor", "setup"})


def _filter_tools(tools: list[Tool], always: set[str]) -> list[Tool]:
    """Apply the one CLI_BRIDGE_TOOLS knob (config.tools) so a host pays schema context only for
    the tools it wants. `always` = the per-lane ask_<lane> names, kept in every mode; doctor/setup
    are never hidden either. List-time only — call_tool still executes any registered name."""
    want = config.tools()
    if "all" in want:
        return tools
    keep = set(DEFAULT_TOOLS) if not want or "default" in want else set()
    keep |= want | {"doctor", "setup"} | always
    return [t for t in tools if t.name in keep]
