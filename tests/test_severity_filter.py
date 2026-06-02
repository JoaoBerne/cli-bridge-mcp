"""severity_filter: drop findings below a threshold in review_diff / security_review."""
import asyncio

from cli_bridge import findings, workflows
from cli_bridge.lanes import LaneSpec
from cli_bridge.runner import RunResult


def test_filter_by_severity_unit():
    reply = ('[{"severity":"low","title":"a"},{"severity":"high","title":"b"},'
             '{"severity":"blocker","title":"c"}]')
    fs, ok = findings.parse_findings(reply, role="x", lane="L")
    assert ok
    kept = {f.severity for f in findings.filter_by_severity(fs, "high")}
    assert kept == {"high", "blocker"}                 # at or above 'high'
    assert len(findings.filter_by_severity(fs, "")) == 3        # empty -> keep all
    assert len(findings.filter_by_severity(fs, "garbage")) == 3  # unknown -> keep all


def test_review_diff_applies_severity_filter():
    reply = ('[{"severity":"low","title":"style nit","file":"x.py","line":1,'
             '"evidence":"minor","recommendation":"tidy"},'
             '{"severity":"blocker","title":"sql injection","file":"x.py","line":2,'
             '"evidence":"concat","recommendation":"parametrize"}]')

    async def run_lane(lane, args, *, tool="ask", terse=True):
        return RunResult(True, reply, "ok")

    lane = LaneSpec("a", "A", "echo", lambda *x: [])
    out = asyncio.run(workflows.review_diff(
        [lane], {"diff": "diff --git a/x.py b/x.py", "severity_filter": "high"}, run_lane))
    assert "sql injection" in out          # blocker kept
    assert "style nit" not in out          # low dropped
