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
import os

from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from . import runner
from .detect import is_installed, installed_lanes
from .lanes import LaneSpec, all_lanes

DEFAULT_TIMEOUT_S = 120
MAX_TIMEOUT_S = 900

server: Server = Server("cli-bridge")


# ─────────────────────────────── host detection (self-hide) ───────────────────────────────

def _host_name() -> str:
    """Who is calling us? Env override wins; else the MCP client's declared name."""
    forced = os.environ.get("CLI_BRIDGE_HOST", "").strip().lower()
    if forced:
        return forced
    try:
        info = server.request_context.session.client_params.clientInfo  # type: ignore[union-attr]
        return (info.name or "").strip().lower()
    except Exception:
        return ""


def _is_host(lane: LaneSpec, host: str) -> bool:
    return bool(host) and host in {c.lower() for c in lane.client_ids}


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
                             if lane.paid else "")}
    if "effort" in lane.caps:
        props["effort"] = {"type": "string",
                           "enum": ["", "minimal", "low", "medium", "high", "max"],
                           "description": "Reasoning depth. Higher = harder/slower."}
    if "agent" in lane.caps:
        props["agent"] = {"type": "string",
                          "description": "'plan' (read-only, default) or 'build' (EDITS FILES directly)."}
    return {"type": "object", "properties": props, "required": ["task"]}


def _tools_for(lanes: list[LaneSpec]) -> list[Tool]:
    tools: list[Tool] = []
    for lane in lanes:
        paid = " [paid lane - spends credits]" if lane.paid else ""
        tools.append(Tool(
            name=f"ask_{lane.key}",
            description=f"Consult {lane.display}. {lane.note}{paid}",
            inputSchema=_ask_schema(lane),
            annotations={"readOnlyHint": True, "openWorldHint": True, "destructiveHint": False},
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
                         "get all answers side by side. Free lanes only by default (no credits)."),
            inputSchema={
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "Prompt sent to every lane."},
                    "include_paid": {"type": "boolean",
                                     "description": "Also query paid lanes (spends credits). Default false."},
                    "cwd": {"type": "string", "description": "Directory the CLIs run in."},
                    "timeout_s": {"type": "integer",
                                  "description": f"Per-lane timeout (max {MAX_TIMEOUT_S})."},
                },
                "required": ["task"],
            },
            annotations={"readOnlyHint": True, "openWorldHint": True, "destructiveHint": False},
        ))
    tools.append(Tool(
        name="doctor",
        description="Health check: which CLIs are installed, which is the host (hidden), paid lanes, defaults.",
        inputSchema={"type": "object", "properties": {}},
        annotations={"readOnlyHint": True, "destructiveHint": False},
    ))
    return tools


@server.list_tools()
async def list_tools() -> list[Tool]:
    lanes, _ = _active_lanes()
    return _tools_for(lanes)


# ─────────────────────────────── execution helpers ───────────────────────────────

def _timeout(raw) -> int:
    try:
        t = int(raw)
    except (TypeError, ValueError):
        t = DEFAULT_TIMEOUT_S
    return max(1, min(t, MAX_TIMEOUT_S))


async def _run_lane(lane: LaneSpec, args: dict) -> runner.RunResult:
    task = str(args.get("task", "")).strip()
    if not task:
        return runner.RunResult(False, "task is required", "failed")
    model = lane.model_for(str(args.get("model", "")))
    argv = [lane.bin] + lane.build_ask(
        task, model, str(args.get("effort", "")), str(args.get("agent", "")))
    cwd = str(args.get("cwd", "")).strip()
    expanded = os.path.expanduser(cwd) if cwd else None
    if expanded and not os.path.isdir(expanded):
        return runner.RunResult(False, f"cwd `{cwd}` is not an existing directory", "failed")
    return await asyncio.to_thread(
        runner.run, argv, _timeout(args.get("timeout_s")), expanded)


def _lane_by_key(key: str, lanes: list[LaneSpec]) -> LaneSpec | None:
    return next((ln for ln in lanes if ln.key == key), None)


# ─────────────────────────────── tool dispatch ───────────────────────────────

@server.call_tool()
async def call_tool(name: str, args: dict) -> list[TextContent]:
    lanes, host = _active_lanes()

    if name == "doctor":
        return [TextContent(type="text", text=_doctor(host))]

    if name == "ask_all":
        return await _ask_all(lanes, args)

    if name.startswith("ask_"):
        lane = _lane_by_key(name[4:], lanes)
        if not lane:
            return [TextContent(type="text", text=f"[error] no such lane: {name[4:]}")]
        res = await _run_lane(lane, args)
        return [TextContent(type="text", text=res.render())]

    if name.startswith("list_") and name.endswith("_models"):
        lane = _lane_by_key(name[5:-7], lanes)
        if not lane or lane.models_args is None:
            return [TextContent(type="text", text=f"[error] no model list for: {name}")]
        res = await asyncio.to_thread(runner.run, [lane.bin] + lane.models_args, 60)
        return [TextContent(type="text", text=res.render())]

    return [TextContent(type="text", text=f"[error] unknown tool: {name}")]


async def _ask_all(lanes: list[LaneSpec], args: dict) -> list[TextContent]:
    include_paid = bool(args.get("include_paid", False))
    targets = [ln for ln in lanes if include_paid or not ln.paid]
    if not targets:
        return [TextContent(type="text", text="[error] no lanes available to query")]
    sub = {"task": args.get("task", ""), "cwd": args.get("cwd", ""),
           "timeout_s": args.get("timeout_s")}
    results = await asyncio.gather(*[_run_lane(ln, sub) for ln in targets])
    blocks = []
    for lane, res in zip(targets, results):
        status = "OK" if res.ok else f"FAILED ({res.kind})"
        blocks.append(f"## {lane.display} - {status}\n\n{res.render()}")
    skipped = [ln.display for ln in lanes if ln.paid and not include_paid]
    footer = (f"\n\n---\n_Skipped paid lanes: {', '.join(skipped)} (set include_paid=true)._"
              if skipped else "")
    return [TextContent(type="text", text="\n\n".join(blocks) + footer)]


def _doctor(host: str) -> str:
    lines = ["# cli-bridge - health check", ""]
    lines.append(f"Host (caller): **{host or 'unknown'}** - its own lane is hidden.\n")
    for lane in all_lanes():
        installed = is_installed(lane)
        mark = "installed" if installed else "NOT on PATH"
        hidden = " - hidden (this is the host)" if _is_host(lane, host) else ""
        paid = " - paid" if lane.paid else " - free"
        model = lane.model_for("")
        default = f" - default model: {model}" if model else ""
        lines.append(f"- **{lane.key}** ({lane.bin}) - {mark}{paid}{hidden}{default}")
    lines.append("\nAdd your own CLI via a JSON file in CLI_BRIDGE_LANES_FILE - no code changes.")
    return "\n".join(lines)


def main() -> None:
    async def _serve() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
