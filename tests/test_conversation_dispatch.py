"""End-to-end round-table through call_tool: memory carries across DIFFERENT lanes.

Fakes _run_lane (no real CLI) and captures the task each lane actually receives, so we can
prove the second lane is handed the first lane's prior answer (the whole point of a
multi-lane thread).
"""
import asyncio
import re

import pytest

from cli_bridge import server, telemetry
from cli_bridge.lanes import LaneSpec
from cli_bridge.runner import RunResult


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_STATE_DB", str(tmp_path / "s.sqlite"))
    telemetry._reset_for_tests()
    a = LaneSpec("gemini", "Gemini", "echo", lambda *x: [])
    b = LaneSpec("gpt", "GPT", "echo", lambda *x: [])
    monkeypatch.setattr(server, "_active_lanes", lambda: ([a, b], ""))
    yield
    telemetry._reset_for_tests()


def test_thread_memory_crosses_lanes(monkeypatch):
    seen: dict[str, str] = {}

    async def fake_run_lane(lane, args, *, tool="ask", terse=True):
        seen[lane.key] = args["task"]          # capture the (maybe history-augmented) task
        return RunResult(True, f"{lane.key}-says: hello", "ok", latency_ms=1)
    monkeypatch.setattr(server, "_run_lane", fake_run_lane)

    # Turn 1 — start a fresh thread on gemini. No prior history => plain task, id returned.
    out1 = asyncio.run(server.call_tool("ask_gemini", {"task": "explain X", "conversation": "new"}))
    text1 = out1[0].text
    cid = re.search(r"\[conversation: (\w+)\]", text1).group(1)
    assert seen["gemini"] == "explain X"       # first turn carries no prefix

    # Turn 2 — continue the SAME thread on gpt. gpt must receive gemini's prior answer + prompt.
    asyncio.run(server.call_tool("ask_gpt", {"task": "do you agree?", "conversation": cid}))
    assert "gemini-says: hello" in seen["gpt"]   # round-table memory crossed lanes
    assert "explain X" in seen["gpt"]            # the earlier user turn too
    assert "do you agree?" in seen["gpt"]        # the new prompt

    # conversation_show renders both lanes' turns; conversations_list surfaces the thread id.
    shown = asyncio.run(server.call_tool("conversation_show", {"conversation": cid}))[0].text
    assert "gemini-says: hello" in shown and "gpt-says: hello" in shown
    listed = asyncio.run(server.call_tool("conversations_list", {}))[0].text
    assert cid in listed


def test_no_conversation_is_stateless(monkeypatch):
    seen: dict[str, str] = {}

    async def fake_run_lane(lane, args, *, tool="ask", terse=True):
        seen[lane.key] = args["task"]
        return RunResult(True, "ok", "ok", latency_ms=1)
    monkeypatch.setattr(server, "_run_lane", fake_run_lane)

    asyncio.run(server.call_tool("ask_gemini", {"task": "plain ask"}))
    assert seen["gemini"] == "plain ask"          # no prefix, no thread
    assert telemetry.convo_list() == []           # nothing recorded


def test_bad_conversation_id_rejected(monkeypatch):
    async def fake_run_lane(lane, args, *, tool="ask", terse=True):
        return RunResult(True, "ok", "ok", latency_ms=1)
    monkeypatch.setattr(server, "_run_lane", fake_run_lane)
    out = asyncio.run(server.call_tool("ask_gemini", {"task": "x", "conversation": "bad id!"}))
    assert "invalid conversation id" in out[0].text
