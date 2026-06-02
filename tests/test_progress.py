"""MCP progress streaming: a no-op outside a request context, and per-stage callbacks fire."""
import asyncio

from cli_bridge import server, workflows
from cli_bridge.lanes import LaneSpec
from cli_bridge.runner import RunResult


def _panel():
    return [LaneSpec("gemini", "Gemini", "echo", lambda *x: []),
            LaneSpec("gpt", "GPT", "echo", lambda *x: [])]


def test_emit_progress_is_noop_outside_request_context():
    # No MCP request context (tests / async jobs / CLI) -> must return quietly, never raise.
    asyncio.run(server._emit_progress(1, 3, "x"))


def test_consensus_streams_progress():
    calls = []

    async def prog(d, t, m):
        calls.append((d, t, m))

    async def run_lane(lane, args, *, tool="ask", terse=True):
        if "chairman of a model council" in args["task"]:
            return RunResult(True, "final", "ok")
        if "Rank them best to worst" in args["task"]:
            return RunResult(True, "RANKING: A, B", "ok")
        return RunResult(True, f"ans {lane.display}", "ok")

    asyncio.run(workflows.consensus(_panel(), {"task": "q"}, run_lane, progress=prog))
    assert [c[0] for c in calls] == [1, 2, 3]
    assert calls[-1] == (3, 3, "synthesis")


def test_debate_streams_progress():
    calls = []

    async def prog(d, t, m):
        calls.append((d, t, m))

    async def run_lane(lane, args, *, tool="ask", terse=True):
        return RunResult(True, f"pos {lane.display}", "ok")

    asyncio.run(workflows.debate(_panel(), {"task": "q", "rounds": 0}, run_lane, progress=prog))
    assert (1, 2, "opening") in calls and (2, 2, "final") in calls
