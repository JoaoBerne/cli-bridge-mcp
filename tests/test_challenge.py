"""challenge: an independent skeptic that pressure-tests a claim (anti-sycophancy)."""
import asyncio

import pytest

from cli_bridge import server, telemetry, workflows
from cli_bridge.lanes import LaneSpec
from cli_bridge.runner import RunResult


def test_challenge_prompt_is_anti_sycophantic():
    p = workflows.challenge_prompt("X is always faster than Y")
    assert "do not reflexively agree" in p.lower()
    assert "manufacture disagreement" in p.lower()      # integrity guardrail
    assert "X is always faster than Y" in p             # the claim is embedded


def test_challenge_runs_one_lane():
    async def run_lane(lane, args, *, tool="ask", terse=True):
        assert tool == "challenge"
        assert "reassessment" in args["task"].lower()
        return RunResult(True, "Counter-point: Y wins on nearly-sorted input.", "ok")
    lane = LaneSpec("gemini", "Gemini", "echo", lambda *x: [])
    out = asyncio.run(workflows.challenge([lane], {"task": "quicksort always beats mergesort"},
                                          run_lane))
    assert "skeptic: Gemini" in out and "Y wins on nearly-sorted input" in out


def test_challenge_requires_a_lane():
    out = asyncio.run(workflows.challenge([], {"task": "x"}, None))
    assert "no lane available" in out


@pytest.fixture
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_STATE_DB", str(tmp_path / "s.sqlite"))
    telemetry._reset_for_tests()
    yield
    telemetry._reset_for_tests()


def test_challenge_dispatch_picks_explicit_lane(isolate, monkeypatch):
    a = LaneSpec("gemini", "Gemini", "echo", lambda *x: [])
    b = LaneSpec("gpt", "GPT", "echo", lambda *x: [])
    monkeypatch.setattr(server, "_active_lanes", lambda: ([a, b], ""))
    used = {}

    async def fake_run_lane(lane, args, *, tool="ask", terse=True):
        used["lane"] = lane.key
        return RunResult(True, "critique", "ok")
    monkeypatch.setattr(server, "_run_lane", fake_run_lane)

    out = asyncio.run(server.call_tool("challenge", {"task": "claim", "lane": "gpt"}))[0].text
    assert used["lane"] == "gpt" and "skeptic: GPT" in out
