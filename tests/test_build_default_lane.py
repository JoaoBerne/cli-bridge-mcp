"""ask_build with no `lane`: routes to the first FREE build-capable lane (router order)."""
import asyncio

import pytest

from cli_bridge import server, telemetry
from cli_bridge.lanes import LaneSpec


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_STATE_DB", str(tmp_path / "s.sqlite"))
    telemetry._reset_for_tests()
    yield
    telemetry._reset_for_tests()


def _lanes():
    # ollama: free but NO build cap; opencode: free + build; gpt: limited + build
    return [
        LaneSpec("ollama", "Ollama", "echo", lambda *a: [], cost_default="free"),
        LaneSpec("opencode", "Opencode", "echo", lambda *a: [],
                 cost_default="free", caps=("model", "effort", "agent")),
        LaneSpec("gpt", "GPT", "echo", lambda *a: [],
                 cost_default="limited", caps=("model", "effort", "agent")),
    ]


def test_default_lane_is_first_free_build_capable(monkeypatch):
    monkeypatch.setattr(server, "_active_lanes", lambda: (_lanes(), ""))
    picked = {}

    async def fake_isolated(lane, args, run_lane, architect=None):
        picked["lane"] = lane.key
        return "BUILD-REPORT"
    monkeypatch.setattr(server.worktrees, "ask_build_isolated", fake_isolated)
    out = asyncio.run(server.call_tool("ask_build", {"task": "t"}))[0].text
    assert picked["lane"] == "opencode" and "BUILD-REPORT" in out


def test_no_free_build_capable_lane_errors(monkeypatch):
    only = [LaneSpec("ollama", "Ollama", "echo", lambda *a: [], cost_default="free")]
    monkeypatch.setattr(server, "_active_lanes", lambda: (only, ""))
    out = asyncio.run(server.call_tool("ask_build", {"task": "t"}))[0].text
    assert "no free build-capable lane" in out


def test_explicit_lane_still_wins(monkeypatch):
    monkeypatch.setattr(server, "_active_lanes", lambda: (_lanes(), ""))
    picked = {}

    async def fake_isolated(lane, args, run_lane, architect=None):
        picked["lane"] = lane.key
        return "ok"
    monkeypatch.setattr(server.worktrees, "ask_build_isolated", fake_isolated)
    asyncio.run(server.call_tool("ask_build", {"task": "t", "lane": "gpt"}))
    assert picked["lane"] == "gpt"
