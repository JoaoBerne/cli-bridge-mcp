"""Consensus: anonymized peer-ranking + deterministic Borda aggregation + chairman synthesis."""
import asyncio

import pytest

from cli_bridge import server, telemetry, workflows
from cli_bridge.lanes import LaneSpec
from cli_bridge.runner import RunResult


def test_parse_ranking_is_robust():
    valid = {"A", "B", "C"}
    assert workflows._parse_ranking("RANKING: B, A, C\nbecause...", valid) == ["B", "A", "C"]
    assert workflows._parse_ranking("blah\nRANKING: C > A", valid) == ["C", "A"]
    assert workflows._parse_ranking("RANKING: A, A, Z, B", valid) == ["A", "B"]   # dedup + junk
    assert workflows._parse_ranking("no ranking here", valid) == []


def test_aggregate_borda_picks_majority_winner():
    labels = ["A", "B", "C"]
    agg = workflows.aggregate_rankings([["A", "B", "C"], ["A", "C", "B"], ["B", "A", "C"]], labels)
    assert agg["order"][0] == "A"          # A: 3+3+2=8 beats B: 2+1+3=6
    assert agg["firsts"]["A"] == 2


def test_aggregate_tie_broken_by_first_place_votes():
    labels = ["A", "B"]
    # equal points (A:3, B:3) but A has more firsts
    agg = workflows.aggregate_rankings([["A", "B"], ["A", "B"], ["B", "A"], ["B", "A"]], labels)
    assert agg["points"]["A"] == agg["points"]["B"]
    assert agg["order"][0] in {"A", "B"}   # deterministic, firsts tie too -> label order


def _panel():
    return [LaneSpec("gemini", "Gemini", "echo", lambda *x: []),
            LaneSpec("gpt", "GPT", "echo", lambda *x: []),
            LaneSpec("mistral", "Mistral", "echo", lambda *x: [])]


def test_consensus_full_flow_anonymized_and_deterministic():
    async def run_lane(lane, args, *, tool="ask", terse=True):
        assert tool == "consensus"
        t = args["task"]
        if "chairman of a model council" in t:
            return RunResult(True, "FINAL: refined winning answer.", "ok")
        if "Rank them best to worst" in t:
            return RunResult(True, "RANKING: A, B, C", "ok")   # everyone prefers A (=Gemini)
        return RunResult(True, f"answer from {lane.display}", "ok")

    out = asyncio.run(workflows.consensus(_panel(), {"task": "what is best?"}, run_lane))
    assert "# Consensus" in out
    assert "FINAL: refined winning answer." in out
    assert "Consensus ranking" in out
    # Gemini (answer A) wins the Borda vote -> rank 1 row names Gemini
    rank_section = out.split("Consensus ranking", 1)[1]
    first_row = rank_section.split("| 1 |", 1)[1].splitlines()[0]
    assert "Gemini" in first_row
    # answers stay anonymized (A/B/C labels present); panel lists all three
    assert "Gemini" in out and "GPT" in out and "Mistral" in out


def test_consensus_single_answer_short_circuits():
    async def run_lane(lane, args, *, tool="ask", terse=True):
        # only gemini answers; others fail
        if lane.key == "gemini" and "Rank" not in args["task"]:
            return RunResult(True, "solo answer", "ok")
        return RunResult(False, "down", "failed")
    out = asyncio.run(workflows.consensus(_panel(), {"task": "q"}, run_lane))
    assert "Only Gemini answered" in out and "solo answer" in out


def test_consensus_no_parseable_rankings_falls_back():
    async def run_lane(lane, args, *, tool="ask", terse=True):
        if "chairman of a model council" in args["task"]:
            return RunResult(True, "chair final", "ok")
        if "Rank them best to worst" in args["task"]:
            return RunResult(True, "I refuse to rank", "ok")   # unparseable
        return RunResult(True, f"answer {lane.display}", "ok")
    out = asyncio.run(workflows.consensus(_panel(), {"task": "q"}, run_lane))
    assert "No parseable rankings" in out and "chair final" in out


@pytest.fixture
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_STATE_DB", str(tmp_path / "s.sqlite"))
    telemetry._reset_for_tests()
    yield
    telemetry._reset_for_tests()


def test_consensus_dispatch(isolate, monkeypatch):
    monkeypatch.setattr(server, "_active_lanes", lambda: (_panel(), ""))

    async def fake_run_lane(lane, args, *, tool="ask", terse=True):
        if "chairman of a model council" in args["task"]:
            return RunResult(True, "dispatched final", "ok")
        if "Rank them best to worst" in args["task"]:
            return RunResult(True, "RANKING: A, B, C", "ok")
        return RunResult(True, f"ans {lane.display}", "ok")
    monkeypatch.setattr(server, "_run_lane", fake_run_lane)

    out = asyncio.run(server.call_tool("consensus", {"task": "decide"}))[0].text
    assert "# Consensus" in out and "dispatched final" in out
