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
import tempfile

from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from . import runner
from .detect import is_installed, installed_lanes
from .lanes import LANES_LOAD_STATUS as _LANES_LOAD_STATUS, LaneSpec, all_lanes


def lanes_load_status() -> dict:
    return dict(_LANES_LOAD_STATUS)

DEFAULT_TIMEOUT_S = 120
MAX_TIMEOUT_S = 900
ASK_ALL_DEFAULT_TIMEOUT_S = 45
ASK_ALL_MAX_TIMEOUT_S = 60
ASK_ALL_SYNTH_TIMEOUT_S = 45

# Subagent-style return: a delegate works in its OWN context and should hand back a DIGEST,
# not its whole transcript. Anything longer than this is spilled to a file and only a head
# preview + path comes back — so a 50k-token answer never floods the host's context. The
# host re-reads the file selectively (grep, or a dedicated subagent) when it needs the rest.
def _int_env(name: str, default: int, lo: int, hi: int) -> int:
    """Parse an int env var without ever crashing the server at import on a bad value."""
    try:
        return max(lo, min(int(os.environ.get(name, "").strip() or default), hi))
    except (TypeError, ValueError):
        return default


INLINE_MAX_CHARS = _int_env("CLI_BRIDGE_INLINE_MAX_CHARS", 12000, 500, 1_000_000)
OVERFLOW_DIR = os.environ.get("CLI_BRIDGE_OVERFLOW_DIR", "").strip() \
    or os.path.join(tempfile.gettempdir(), "cli-bridge-overflow")

# COST PROFILE — how aggressively to spend paid credits / quota. The user sets it once via
# CLI_BRIDGE_PROFILE; there is no universal "free is best" — someone on a big plan may not
# care about tokens and want top models by default. Unset => balanced, but the server's
# `instructions` tell the host assistant to ASK the user on first use (see SETUP_TEXT).
#   saver    = free lanes only; never spend credits or scarce quota unless explicitly told.
#   balanced = free by default; limited/paid lanes need explicit include_paid.
#   max      = quality first; ask_all includes free, limited, and paid lanes.
_VALID_PROFILES = ("saver", "balanced", "max")


def _profile() -> str:
    p = os.environ.get("CLI_BRIDGE_PROFILE", "").strip().lower()
    return p if p in _VALID_PROFILES else "balanced"


def _profile_is_set() -> bool:
    return os.environ.get("CLI_BRIDGE_PROFILE", "").strip().lower() in _VALID_PROFILES


def _cost_config_is_set() -> bool:
    """The user has expressed cost intent if they set a profile OR any per-lane COST."""
    if _profile_is_set():
        return True
    return any(k.startswith("CLI_BRIDGE_") and k.endswith("_COST") and v.strip()
               for k, v in os.environ.items())


SETUP_TEXT = (
    "Help the user configure cli-bridge to THEIR situation. Don't impose a preset — every "
    "person's plans differ (one may have unlimited Gemini but metered opencode credits, "
    "another a tight GPT quota). Have a short conversation:\n\n"
    "1. Run `doctor` first to see which CLIs they actually have installed.\n"
    "2. For EACH installed lane, ask what it costs THEM and how freely to use it — e.g. "
    "\"is your opencode on paid credits or a flat plan?\", \"do you mind me spending GPT quota "
    "on big tasks?\". Listen to their actual answer; don't assume free=best.\n"
    "3. Translate their answers into config (env vars on the MCP server entry, or just honour "
    "them for this session):\n"
    "     CLI_BRIDGE_<LANE>_COST = free | limited | paid\n"
    "          free=use freely in ask_all; limited=scarce quota, direct calls OK but skip "
    "ask_all by default; paid=money/credits\n"
    "     CLI_BRIDGE_<LANE>_ENABLED = false       (hide a lane they don't want used)\n"
    "     CLI_BRIDGE_<LANE>_MODEL = <id>          (their preferred default model for a lane)\n"
    "     CLI_BRIDGE_PROFILE = saver|balanced|max (optional shorthand if they'd rather not "
    "go lane-by-lane: saver=free only, balanced=paid when it earns it, max=best by default)\n"
    "4. Confirm back what you understood. The user stays in control — this just sets your "
    "default behaviour so they don't have to repeat it each call."
)

INSTRUCTIONS = (
    "cli-bridge lets you consult other AI CLIs (Gemini, GPT, Mistral, opencode, …) as a "
    "council. Each lane spawns the official CLI (ban-safe, no key extraction), read-only by "
    "default.\n\n"
    "FIRST RUN — understand the user's cost situation: if their preferences aren't configured "
    "(no CLI_BRIDGE_PROFILE / per-lane COST set), call `setup` and have a brief conversation "
    "to learn what each CLI costs THEM and how freely to use it. Do NOT assume 'free is best' "
    "— someone on a big plan may want top models by default; someone on metered credits won't. "
    "Configure to their actual answer.\n\n"
    "Then: `ask_<lane>` for one model, `ask_all` to poll several in parallel, `doctor` to see "
    "what's installed and the current cost/quota stance."
)

server: Server = Server("cli-bridge", instructions=INSTRUCTIONS)


def _emit(text: str, label: str = "answer") -> TextContent:
    """Return small answers inline; spill big ones to a file and return a preview + path.
    This is what makes a delegate behave like a subagent: the host gets a compact digest,
    and the full output stays out of its context until it deliberately reads the file."""
    if len(text) <= INLINE_MAX_CHARS:
        return TextContent(type="text", text=text)
    try:
        os.makedirs(OVERFLOW_DIR, exist_ok=True)
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
    """Installed lanes minus the caller's own lane."""
    host = _host_name()
    lanes = [ln for ln in installed_lanes(all_lanes()) if not _is_host(ln, host)]
    return lanes, host


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
    return tools


@server.list_tools()
async def list_tools() -> list[Tool]:
    lanes, _ = _active_lanes()
    return _tools_for(lanes)


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


async def _run_lane(lane: LaneSpec, args: dict) -> runner.RunResult:
    task = _str(args, "task")
    if not task:
        return runner.RunResult(False, "task is required", "failed")
    model = lane.model_for(_str(args, "model"))
    agent = _str(args, "agent").lower()
    if agent not in {"", "plan", "build"}:    # never let a hallucinated value enable writes
        agent = "plan"
    argv = [lane.bin] + lane.build_ask(task, model, _str(args, "effort"), agent)
    cwd = _str(args, "cwd")
    expanded = os.path.expanduser(cwd) if cwd else None
    if expanded and not os.path.isdir(expanded):
        return runner.RunResult(False, f"cwd `{cwd}` is not an existing directory", "failed")
    return await runner.arun(argv, _timeout(args.get("timeout_s")), expanded)


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
        return [_emit(text, label="doctor")]

    if name == "usage_report":
        return [_emit(_render_usage(), label="usage_report")]

    if name == "lane_stats":
        return [_emit(_render_lane_stats(), label="lane_stats")]

    if name == "reset_lane_state":
        lane = _str(args, "lane")
        ok = telemetry.reset_lane(lane) if lane else False
        msg = (f"Lane '{lane}' cooldown/failure counters cleared." if ok
               else f"No state to clear for lane '{lane}' (already clean or unknown).")
        return [TextContent(type="text", text=msg)]

    if name == "ask_all":
        return await _ask_all(lanes, args)

    if name.startswith("ask_"):
        lane = _lane_by_key(name[4:], lanes)
        if not lane:
            return [TextContent(type="text", text=f"[error] no such lane: {name[4:]}")]
        res = await _run_lane(lane, args)
        return [_emit(res.render(), label=f"ask_{lane.key}")]

    if name.startswith("list_") and name.endswith("_models"):
        lane = _lane_by_key(name[5:-7], lanes)
        if not lane or lane.models_args is None:
            return [TextContent(type="text", text=f"[error] no model list for: {name}")]
        res = await runner.arun([lane.bin] + lane.models_args, 60)
        return [_emit(res.render(), label=f"list_{lane.key}_models")]

    return [TextContent(type="text", text=f"[error] unknown tool: {name}")]


async def _ask_all(lanes: list[LaneSpec], args: dict) -> list[TextContent]:
    # Explicit arg wins. Otherwise the cost profile decides: 'max' polls paid lanes too,
    # saver/balanced stay free-only by default (the caller can still pass include_paid).
    include_paid = _ask_all_include_paid(args)
    targets = _ask_all_targets(lanes, include_paid)
    if not targets:
        held = [ln.display for ln in lanes if ln.is_paid or ln.is_limited]
        if held:
            msg = ("[error] no FREE lanes to fan out to. Limited/paid lanes available: "
                   f"{', '.join(held)}. Call ask_all with include_paid=true, or mark a lane "
                   "free for your plan via CLI_BRIDGE_<LANE>_COST=free.")
        else:
            msg = ("[error] no delegate CLIs installed. Run `doctor` to see install hints, "
                   "then install/log into at least one CLI (e.g. gemini, mistral, opencode).")
        return [TextContent(type="text", text=msg)]
    sub = {"task": _str(args, "task"), "cwd": _str(args, "cwd"),
           "timeout_s": _ask_all_timeout(args.get("timeout_s"))}
    # return_exceptions: one broken lane must not sink the whole fan-out.
    results = await asyncio.gather(*[_run_lane(ln, sub) for ln in targets],
                                   return_exceptions=True)
    blocks = []
    for lane, res in zip(targets, results):
        if isinstance(res, BaseException):
            blocks.append(f"## {lane.display} - FAILED (crash)\n\n[crash] {res}")
        else:
            status = "OK" if res.ok else f"FAILED ({res.kind})"
            blocks.append(f"## {lane.display} - {status}\n\n{res.render()}")
    skipped = [ln.display for ln in lanes if (ln.is_paid or ln.is_limited) and not include_paid]
    footer = (f"\n\n---\n_Skipped limited/paid lanes: {', '.join(skipped)} "
              f"(set include_paid=true)._"
              if skipped else "")
    body = "\n\n".join(blocks) + footer

    if bool(args.get("synthesize")):
        ok = [(lane, res) for lane, res in zip(targets, results)
              if not isinstance(res, BaseException) and res.ok]
        synth = await _synthesize(_str(args, "task"), ok, targets)
        if synth:
            body += f"\n\n---\n## Synthesis (agreement / disagreement)\n\n{synth}"
    return [_emit(body, label="ask_all")]


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
        res = await _run_lane(ln, {"task": "Reply with exactly: OK", "timeout_s": 60})
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
    async def _serve() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
