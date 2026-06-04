"""debate adversarial stance assignment + consensus agreement metric."""
import asyncio

from cli_bridge import workflows
from cli_bridge.lanes import LaneSpec
from cli_bridge.runner import RunResult


def _panel():
    return [LaneSpec("gemini", "Gemini", "echo", lambda *x: []),
            LaneSpec("gpt", "GPT", "echo", lambda *x: []),
            LaneSpec("mistral", "Mistral", "echo", lambda *x: [])]


def test_debate_adversarial_assigns_for_against_neutral():
    seen = []

    async def run_lane(lane, args, *, tool="ask", terse=True):
        seen.append(args["task"])
        return RunResult(True, f"pos {lane.display}", "ok")

    # 4 lanes: one is held out as the independent judge, the other 3 open with stances
    panel = _panel() + [LaneSpec("opencode", "OpenCode", "echo", lambda *x: [])]
    asyncio.run(workflows.debate(panel, {"task": "X?", "rounds": 0, "adversarial": True},
                                 run_lane))
    openings = " ".join(seen[:3])      # the 3 opening prompts (judge call comes after)
    assert "FOR position" in openings
    assert "AGAINST position" in openings
    assert "NEUTRAL position" in openings


def test_debate_default_has_no_stances():
    seen = []

    async def run_lane(lane, args, *, tool="ask", terse=True):
        seen.append(args["task"])
        return RunResult(True, "pos", "ok")

    asyncio.run(workflows.debate(_panel(), {"task": "X?", "rounds": 0}, run_lane))
    assert "FOR position" not in " ".join(seen)


def test_consensus_reports_agreement():
    async def run_lane(lane, args, *, tool="ask", terse=True):
        if "chairman of a model council" in args["task"]:
            return RunResult(True, "final", "ok")
        if "Rank them best to worst" in args["task"]:
            return RunResult(True, "RANKING: A, B, C", "ok")
        return RunResult(True, f"ans {lane.display}", "ok")

    out = asyncio.run(workflows.consensus(_panel(), {"task": "q"}, run_lane))
    assert "Agreement: 3/3" in out
