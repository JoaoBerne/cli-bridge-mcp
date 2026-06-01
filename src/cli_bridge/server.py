"""cli-bridge — let your AI assistant consult a council of other AI CLIs.

Low-level MCP server so we can filter tools per client at list time:
- only lanes whose CLI is installed are exposed,
- the *calling* client's own lane is hidden (no point asking yourself),
detected from the MCP `clientInfo.name` (with a CLI_BRIDGE_HOST env override).

Every lane spawns the official CLI as a subprocess — no token extraction, no API keys,
so accounts can't get flagged for ToS-breaking token reuse. Read-only by default.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import time

from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    GetPromptResult, Prompt, PromptArgument, PromptMessage, TextContent, Tool,
)

from . import config, guards, jobs, preamble, router, runner, telemetry, workflows
from .config import (
    ASK_ALL_DEFAULT_TIMEOUT_S, ASK_ALL_MAX_TIMEOUT_S, ASK_ALL_SYNTH_TIMEOUT_S,
    DEFAULT_TIMEOUT_S, INLINE_MAX_CHARS, INSTRUCTIONS, MAX_TIMEOUT_S, OVERFLOW_DIR,
    SETUP_TEXT,
)
from .detect import is_installed, installed_lanes
from .lanes import LANES_LOAD_STATUS as _LANES_LOAD_STATUS, LaneSpec, all_lanes

# config.py is the single source of truth for env/timeouts/profile/onboarding. These thin
# aliases keep the historical server.* call sites (and tests) working after the extraction.
_int_env = config.int_env
_profile = config.profile
_profile_is_set = config.profile_is_set
_cost_config_is_set = config.cost_config_is_set
# How long a spilled overflow file is kept before best-effort pruning (P0-4).
OVERFLOW_TTL_H = config.int_env("CLI_BRIDGE_OVERFLOW_TTL_H", 24, 0, 24 * 365)


def lanes_load_status() -> dict:
    return dict(_LANES_LOAD_STATUS)


server: Server = Server("cli-bridge", instructions=INSTRUCTIONS)


def _prune_overflow() -> None:
    """Best-effort: drop overflow files older than OVERFLOW_TTL_H so the temp dir can't grow
    without bound. Never raises — overflow is a convenience, not a guarantee."""
    if OVERFLOW_TTL_H <= 0:
        return
    cutoff = time.time() - OVERFLOW_TTL_H * 3600
    try:
        for name in os.listdir(OVERFLOW_DIR):
            p = os.path.join(OVERFLOW_DIR, name)
            try:
                if os.path.isfile(p) and os.path.getmtime(p) < cutoff:
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
    return lanes, host


def _host_lane(host: str) -> LaneSpec | None:
    """The caller's OWN installed lane, if it supports model selection — so the host can
    consult a DIFFERENT model of its own family (e.g. Claude Code -> ask Opus 4.6). Returned
    separately from the delegates so it never joins a fan-out, only direct ask_<host> calls."""
    if not host:
        return None
    own = next((ln for ln in installed_lanes(all_lanes()) if _is_host(ln, host)), None)
    return own if own and "model" in own.caps else None


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
    return {"type": "object", "properties": props, "required": ["task"]}


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
            annotations={"readOnlyHint": not can_write, "openWorldHint": True,
                         "destructiveHint": can_write},
        ))
        if lane.models_args is not None:
            tools.append(Tool(
                name=f"list_{lane.key}_models",
                description=f"List models reachable through {lane.display}.",
                inputSchema={"type": "object", "properties": {}},
                annotations={"readOnlyHint": True, "destructiveHint": False},
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
                                  "description": f"Per-lane timeout (max {MAX_TIMEOUT_S})."},
                    "synthesize": {"type": "boolean",
                                   "description": "After collecting answers, have one free lane "
                                   "summarize where the models AGREE and DISAGREE. Default false."},
                },
                "required": ["task"],
            },
            annotations={"readOnlyHint": True, "openWorldHint": True, "destructiveHint": False},
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
            annotations={"readOnlyHint": True, "openWorldHint": True, "destructiveHint": False},
        ))
        tools.append(Tool(
            name="job_status",
            description="Status of an async job: running | succeeded | failed | cancelled | "
                        "interrupted. Pass the job_id returned by ask_all_async.",
            inputSchema={"type": "object", "properties": {
                "job_id": {"type": "string", "description": "The job id (e.g. job_ab12…)."}},
                "required": ["job_id"]},
            annotations={"readOnlyHint": True, "destructiveHint": False},
        ))
        tools.append(Tool(
            name="job_result",
            description="Fetch a finished async job's output (same body as ask_all; spills to a "
                        "file + preview if huge). Returns a 'still running' note if not done.",
            inputSchema={"type": "object", "properties": {
                "job_id": {"type": "string", "description": "The job id."}},
                "required": ["job_id"]},
            annotations={"readOnlyHint": True, "destructiveHint": False},
        ))
        tools.append(Tool(
            name="job_cancel",
            description="Cancel a running async job — kills the delegate CLIs' process groups.",
            inputSchema={"type": "object", "properties": {
                "job_id": {"type": "string", "description": "The job id to cancel."}},
                "required": ["job_id"]},
            annotations={"readOnlyHint": False, "destructiveHint": False},
        ))
        tools.append(Tool(
            name="jobs_list",
            description="List recent async jobs (this session first, then persisted history) "
                        "with their status.",
            inputSchema={"type": "object", "properties": {}},
            annotations={"readOnlyHint": True, "destructiveHint": False},
        ))
    tools.append(Tool(
        name="doctor",
        description="Health check: which CLIs are installed, which is the host (hidden), paid lanes, "
                    "defaults, current cost profile. Pass deep=true to also probe each lane with a "
                    "tiny live call (checks auth/quota — uses a bit of free quota; skips paid lanes).",
        inputSchema={"type": "object", "properties": {
            "deep": {"type": "boolean", "description": "Live-probe each free lane's auth."}}},
        annotations={"readOnlyHint": True, "destructiveHint": False},
    ))
    tools.append(Tool(
        name="setup",
        description="Show the cost-profile choice (saver/balanced/max) to walk the user through "
                    "configuring how cli-bridge spends paid credits/quota. Call this on first use "
                    "if the profile isn't set, ASK the user, then tell them how to set it.",
        inputSchema={"type": "object", "properties": {}},
        annotations={"readOnlyHint": True, "destructiveHint": False},
    ))
    tools.append(Tool(
        name="usage_report",
        description="Local usage stats (this machine only): total runs, per-lane counts/success/"
                    "avg latency, and the most recent calls. Helps see what your council spent.",
        inputSchema={"type": "object", "properties": {}},
        annotations={"readOnlyHint": True, "destructiveHint": False},
    ))
    tools.append(Tool(
        name="lane_stats",
        description="Per-lane health: total runs, failures, consecutive failures/timeouts, and "
                    "any active cooldown (a lane in cooldown is skipped by ask_all until it clears).",
        inputSchema={"type": "object", "properties": {}},
        annotations={"readOnlyHint": True, "destructiveHint": False},
    ))
    tools.append(Tool(
        name="reset_lane_state",
        description="Clear a lane's cooldown + failure counters (e.g. after you re-logged in or "
                    "your quota reset). Pass the lane key, e.g. 'gemini'.",
        inputSchema={"type": "object", "properties": {
            "lane": {"type": "string", "description": "Lane key to reset (e.g. gemini, gpt)."}},
            "required": ["lane"]},
        annotations={"readOnlyHint": False, "destructiveHint": False},
    ))
    if lanes:
        tools.append(Tool(
            name="ask_cascade",
            description="Ask ONE model but with automatic fallback: tries lanes cheapest→strongest, "
                        "skipping cooled ones, and moves to the next on quota/auth/timeout/failure. "
                        "Returns the first success (and a note of what was tried). Free/non-limited "
                        "by default; include_paid to widen.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "The prompt."},
                    "include_paid": {"type": "boolean",
                                     "description": "Allow limited/paid lanes in the chain. "
                                                    "Default false (except CLI_BRIDGE_PROFILE=max)."},
                    "cwd": {"type": "string", "description": "Directory the CLI runs in."},
                    "timeout_s": {"type": "integer", "description": f"Per-attempt timeout (max {MAX_TIMEOUT_S})."},
                },
                "required": ["task"],
            },
            annotations={"readOnlyHint": True, "openWorldHint": True, "destructiveHint": False},
        ))
        tools.append(Tool(
            name="route_plan",
            description="Explain (without running anything) the order ask_cascade would try lanes "
                        "in, given current cost profile and lane cooldowns.",
            inputSchema={"type": "object", "properties": {
                "include_paid": {"type": "boolean", "description": "Include limited/paid lanes."}}},
            annotations={"readOnlyHint": True, "destructiveHint": False},
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
                    "timeout_s": {"type": "integer",
                                  "description": f"Per-reviewer timeout (max {MAX_TIMEOUT_S}, "
                                                 f"default {config.REVIEW_DEFAULT_TIMEOUT_S})."},
                },
                "required": [],
            },
            annotations={"readOnlyHint": True, "openWorldHint": True, "destructiveHint": False},
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
                    "timeout_s": {"type": "integer",
                                  "description": f"Per-reviewer timeout (max {MAX_TIMEOUT_S})."},
                },
                "required": [],
            },
            annotations={"readOnlyHint": True, "openWorldHint": True, "destructiveHint": False},
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
                    "include_paid": {"type": "boolean", "description": "Allow limited/paid lanes."},
                    "cwd": {"type": "string", "description": "Directory the CLIs run in."},
                    "timeout_s": {"type": "integer",
                                  "description": f"Per-turn timeout (max {MAX_TIMEOUT_S})."},
                },
                "required": ["task"],
            },
            annotations={"readOnlyHint": True, "openWorldHint": True, "destructiveHint": False},
        ))
    return tools


def _self_ask_tool(lane: LaneSpec) -> Tool:
    """ask_<host> for the caller's OWN family — requires an explicit `model` so it's only ever
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
        annotations={"readOnlyHint": not can_write, "openWorldHint": True,
                     "destructiveHint": can_write},
    )


@server.list_tools()
async def list_tools() -> list[Tool]:
    lanes, host = _active_lanes()
    tools = _tools_for(lanes)
    own = _host_lane(host)
    if own:
        tools.insert(0, _self_ask_tool(own))   # reach a sibling model of your own family
    return tools


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
    if "include_paid" in args and args["include_paid"] is not None:
        return bool(args["include_paid"])
    return _profile() == "max"


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


async def _run_lane(lane: LaneSpec, args: dict, *, tool: str = "ask",
                    terse: bool = True) -> runner.RunResult:
    task = _str(args, "task")
    if not task:
        return runner.RunResult(False, "task is required", "failed")
    model = lane.model_for(_str(args, "model"))
    agent = _str(args, "agent").lower()
    if agent not in {"", "plan", "build"}:    # never let a hallucinated value enable writes
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
    if ttl > 0 and agent != "build":
        key = _cache_key(lane, model, effort, agent, expanded or "", task, terse_level)
        hit = telemetry.cache_get(key, ttl)
        if hit is not None:
            return runner.RunResult(hit[0], hit[1], hit[2], latency_ms=0)
    # Compress the FINAL answer (cuts host context + delegate output tokens). Skipped for
    # structured-output tools (terse=False) so JSON stays intact. Telemetry keys on the raw
    # task, not the prefixed prompt.
    prompt = preamble.apply(task) if terse else task
    argv = [lane.bin] + lane.build_ask(prompt, model, effort, agent, lane.bin)
    rec = telemetry.start(tool, lane.key, model, task)
    t0 = time.monotonic()
    res = await runner.arun(argv, _timeout(args.get("timeout_s")), expanded)
    res.latency_ms = int((time.monotonic() - t0) * 1000)
    telemetry.record(rec, res.ok, res.kind, len(res.output))
    if key and res.ok:                        # cache only successes; failures are transient
        telemetry.cache_put(key, res.ok, res.output, res.kind)
    return res


def _lane_by_key(key: str, lanes: list[LaneSpec]) -> LaneSpec | None:
    return next((ln for ln in lanes if ln.key == key), None)


# ─────────────────────────────── tool dispatch ───────────────────────────────

@server.call_tool()
async def call_tool(name: str, args: dict) -> list[TextContent]:
    lanes, host = _active_lanes()

    if name == "setup":
        cur = _profile() + ("" if _profile_is_set() else " (default — not explicitly set)")
        return [TextContent(type="text", text=f"Current profile: **{cur}**\n\n{SETUP_TEXT}")]

    if name == "doctor":
        text = await _doctor_deep(host, lanes) if bool(args.get("deep")) else _doctor(host)
        return [_emit(text, label="doctor", guard=False)]

    if name == "usage_report":
        return [_emit(_render_usage(), label="usage_report", guard=False)]

    if name == "lane_stats":
        return [_emit(_render_lane_stats(), label="lane_stats", guard=False)]

    if name == "reset_lane_state":
        lane = _str(args, "lane")
        ok = telemetry.reset_lane(lane) if lane else False
        msg = (f"Lane '{lane}' cooldown/failure counters cleared." if ok
               else f"No state to clear for lane '{lane}' (already clean or unknown).")
        return [TextContent(type="text", text=msg)]

    if name == "ask_cascade":
        return await _ask_cascade(lanes, args)

    if name == "route_plan":
        include_paid = (bool(args["include_paid"]) if args.get("include_paid") is not None
                        else _profile() == "max")
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
        st = jobs.status(_str(args, "job_id"))
        if st is None:
            return [TextContent(type="text", text=f"[error] unknown job_id: {_str(args, 'job_id')}")]
        return [TextContent(type="text", text=_render_job_status(st))]

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
        return [_emit(await workflows.debate(targets, args, _run_lane), label="debate")]

    if name.startswith("ask_"):
        key = name[4:]
        lane = _lane_by_key(key, lanes)
        if not lane:
            # Maybe it's the host's OWN family lane (sibling-model consultation): allowed only
            # with an explicit model so the host doesn't just re-ask its own running model.
            own = _host_lane(host)
            if own and own.key == key:
                if not _str(args, "model"):
                    return [TextContent(type="text", text=(
                        f"[error] ask_{key} is your own family — pass an explicit `model` to "
                        "consult a SIBLING model (e.g. claude-opus-4-6). Re-asking the model "
                        "you're already running is pointless."))]
                lane = own
            else:
                return [TextContent(type="text", text=f"[error] no such lane: {key}")]
        res = await _run_lane(lane, args)
        return [_emit(res.render(), label=f"ask_{lane.key}")]

    if name.startswith("list_") and name.endswith("_models"):
        lane = _lane_by_key(name[5:-7], lanes)
        if not lane or lane.models_args is None:
            return [TextContent(type="text", text=f"[error] no model list for: {name}")]
        res = await runner.arun([lane.bin] + lane.models_args, 60)
        return [_emit(res.render(), label=f"list_{lane.key}_models")]

    return [TextContent(type="text", text=f"[error] unknown tool: {name}")]


async def _ask_cascade(lanes: list[LaneSpec], args: dict) -> list[TextContent]:
    task = _str(args, "task")
    if not task:
        return [TextContent(type="text", text="[error] task is required")]
    include_paid = (bool(args["include_paid"]) if args.get("include_paid") is not None
                    else _profile() == "max")
    ordered = router.order_lanes(lanes, telemetry.cooldown_remaining, include_paid)
    if not ordered:
        return [TextContent(type="text", text=(
            "[error] no lanes eligible for cascade. Install/login a CLI, or set include_paid=true "
            "/ CLI_BRIDGE_PROFILE=max to allow limited/paid lanes."))]
    sub = {"task": task, "cwd": _str(args, "cwd"), "timeout_s": args.get("timeout_s")}
    attempts: list[tuple[LaneSpec, runner.RunResult]] = []
    for lane in ordered:
        res = await _run_lane(lane, sub, tool="ask_cascade")
        attempts.append((lane, res))
        if res.ok:
            return [_emit(f"{res.output}\n\n{_cascade_trace(attempts, chosen=lane)}",
                          label="ask_cascade")]
    return [TextContent(type="text", text=(
        "[error] all lanes failed in cascade: "
        + ", ".join(f"{ln.key}={r.kind}" for ln, r in attempts)
        + ". Try again later or check `doctor`.\n\n" + _cascade_trace(attempts, chosen=None)))]


def _cascade_trace(attempts: list[tuple[LaneSpec, runner.RunResult]],
                   chosen: LaneSpec | None) -> str:
    """Compact, honest record of what the cascade did: order tried (cheapest→strongest),
    each lane's cost tier + latency, why it was skipped, and which one answered."""
    lines = ["---", "_Trace — cascade (cheapest→strongest):_"]
    for lane, res in attempts:
        if chosen is not None and lane is chosen:
            lines.append(f"- ✅ **{lane.key}** [{lane.cost_label}] {res.latency_ms}ms — chosen")
        else:
            lines.append(f"- ❌ {lane.key} [{lane.cost_label}] {res.latency_ms}ms — {res.kind}")
    return "\n".join(lines)


async def _ask_all(lanes: list[LaneSpec], args: dict) -> list[TextContent]:
    return [_emit(await _ask_all_body(lanes, args), label="ask_all")]


async def _ask_all_body(lanes: list[LaneSpec], args: dict) -> str:
    """The fan-out itself, returning the report as a plain string so it can run either inline
    (ask_all) or inside a background job (ask_all_async)."""
    # Explicit arg wins. Otherwise the cost profile decides: 'max' polls paid lanes too,
    # saver/balanced stay free-only by default (the caller can still pass include_paid).
    include_paid = _ask_all_include_paid(args)
    targets = _ask_all_targets(lanes, include_paid)
    if not targets:
        held = [ln.display for ln in lanes if ln.is_paid or ln.is_limited]
        if held:
            return ("[error] no FREE lanes to fan out to. Limited/paid lanes available: "
                    f"{', '.join(held)}. Call ask_all with include_paid=true, or mark a lane "
                    "free for your plan via CLI_BRIDGE_<LANE>_COST=free.")
        return ("[error] no delegate CLIs installed. Run `doctor` to see install hints, "
                "then install/log into at least one CLI (e.g. gemini, mistral, opencode).")
    sub = {"task": _str(args, "task"), "cwd": _str(args, "cwd"),
           "timeout_s": _ask_all_timeout(args.get("timeout_s"))}
    # return_exceptions: one broken lane must not sink the whole fan-out.
    results = await asyncio.gather(*[_run_lane(ln, sub) for ln in targets],
                                   return_exceptions=True)
    blocks = []
    rows = []
    for lane, res in zip(targets, results):
        if isinstance(res, BaseException):
            blocks.append(f"## {lane.display} - FAILED (crash)\n\n[crash] {res}")
            rows.append((lane.display, False, 0, f"crash: {res}"))
        else:
            status = "OK" if res.ok else f"FAILED ({res.kind})"
            blocks.append(f"## {lane.display} - {status} _[{lane.cost_label}, {res.latency_ms}ms]_"
                          f"\n\n{res.render()}")
            rows.append((lane.display, res.ok, res.latency_ms,
                         res.output if res.ok else res.kind))
    skipped = [ln.display for ln in lanes if (ln.is_paid or ln.is_limited) and not include_paid]
    footer = (f"\n\n---\n_Skipped limited/paid lanes: {', '.join(skipped)} "
              f"(set include_paid=true)._"
              if skipped else "")
    # Recap first so the host gets an at-a-glance digest of every lane before the full blocks.
    recap = workflows.council_recap(rows, title="Council")
    body = recap + "\n\n" + "\n\n".join(blocks) + footer

    if bool(args.get("synthesize")):
        ok = [(lane, res) for lane, res in zip(targets, results)
              if not isinstance(res, BaseException) and res.ok]
        synth = await _synthesize(_str(args, "task"), ok, targets)
        if synth:
            body += f"\n\n---\n## Synthesis (agreement / disagreement)\n\n{synth}"
    return body


async def _review_diff(lanes: list[LaneSpec], args: dict) -> list[TextContent]:
    # Same cost policy as ask_all: free/non-limited reviewers unless the caller widens, and
    # never a cooled lane. Then hand off to the (decoupled, testable) workflow engine.
    include_paid = _ask_all_include_paid(args)
    targets = _ask_all_targets(lanes, include_paid)
    report = await workflows.review_diff(targets, args, _run_lane)
    return [_emit(report, label="review_diff")]


async def _synthesize(question, answered, targets) -> str:
    """Second pass: a free lane reads all answers and flags agreement/disagreement. Picks the
    cheapest free non-paid lane available; returns '' if none can do it."""
    if len(answered) < 2:
        return ""
    judge = next((ln for ln in targets
                  if not ln.is_paid and not ln.is_limited and not ln.experimental), None)
    if judge is None:
        return ""
    transcript = "\n\n".join(f"### {lane.display}\n{res.output}" for lane, res in answered)
    prompt = (
        "Several AI models answered the same question. Summarize concisely: (1) where they "
        "AGREE, (2) where they DISAGREE (name which model said what), (3) the most reliable "
        f"takeaway. Be brief.\n\nQUESTION:\n{question}\n\nANSWERS:\n{transcript}")
    res = await _run_lane(judge, {"task": prompt, "timeout_s": ASK_ALL_SYNTH_TIMEOUT_S})
    return res.output if res.ok else ""


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
        return f"- **{ln.key}**: {mark}"
    results = await asyncio.gather(*[_probe(ln) for ln in probes])
    return base + "\n\n## Deep probe (live auth check, free lanes)\n\n" + "\n".join(results)


def _render_usage() -> str:
    rep = telemetry.usage_report()
    if not rep.get("enabled"):
        return ("Telemetry is off or unavailable (set CLI_BRIDGE_TELEMETRY=on, or it couldn't "
                "open its local DB). No usage to report.")
    lines = [f"# cli-bridge usage — {rep['total_runs']} total runs (local only)", ""]
    lines.append("## By lane")
    for r in rep["by_lane"]:
        lines.append(f"- **{r['lane']}**: {r['runs']} runs, {r['ok']} ok, ~{r['avg_ms']}ms avg")
    lines.append("\n## Recent")
    for r in rep["recent"]:
        lines.append(f"- {r['lane'] or r['tool']} [{r['status']}/{r['kind']}] "
                     f"{r['duration_ms']}ms — {r['task']}")
    return "\n".join(lines)


def _render_job_status(st: dict) -> str:
    lines = [f"Job `{st['id']}` — **{st['status']}** ({st.get('kind', 'ask_all')})"]
    if st.get("preview"):
        lines.append(f"_task: {st['preview']}_")
    if st.get("error"):
        lines.append(f"error: {st['error']}")
    if st["status"] == jobs.SUCCEEDED:
        lines.append(f"Fetch it with `job_result {st['id']}`.")
    elif st["status"] == jobs.RUNNING:
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
    lines = ["# Lane health", ""]
    for s in stats:
        cd = f", cooldown {s['cooldown_remaining_s']}s" if s["cooldown_remaining_s"] else ""
        lines.append(
            f"- **{s['lane']}**: {s['total_runs']} runs, {s['total_failures']} failed, "
            f"{s['consecutive_failures']} consecutive fail, last={s['last_kind']}{cd}")
    return "\n".join(lines)


def _doctor(host: str) -> str:
    lines = ["# cli-bridge - health check", ""]
    lines.append(f"Host (caller): **{host or 'unknown'}** - its own lane is hidden.")
    prof = _profile() + ("" if _profile_is_set() else " (default — run `setup` to configure)")
    lines.append(f"Cost profile: **{prof}**\n")
    for lane in all_lanes():
        installed = is_installed(lane)
        mark = "installed" if installed else "NOT on PATH"
        if not lane.enabled:
            mark += " (disabled by env)"
        hidden = " - hidden (this is the host)" if _is_host(lane, host) else ""
        paid = f" - {lane.cost_label}"
        exp = " - experimental" if lane.experimental else ""
        model = lane.model_for("")
        default = f" - default model: {model}" if model else ""
        lines.append(f"- **{lane.key}** ({lane.bin}) - {mark}{paid}{exp}{hidden}{default}")
    lines.append("\nPer-lane config (your plan): CLI_BRIDGE_<LANE>_COST=free|limited|paid, "
                 "_ENABLED=false, _BIN=<path>, _MODEL=<id>.")
    lines.append("Add your own CLI via a JSON file in CLI_BRIDGE_LANES_FILE - no code changes.")
    return "\n".join(lines)


def main() -> None:
    # Any job left 'running' in the DB is from a previous process whose delegates are gone —
    # flip it to 'interrupted' so its status is honest (v1 doesn't resume work across restarts).
    jobs.mark_interrupted_on_startup()
    async def _serve() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
