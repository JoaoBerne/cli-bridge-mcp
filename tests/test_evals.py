"""Evals over a fixture corpus — no network, no real CLI. These guard the parts that decide
review QUALITY: the deterministic prechecks, the tolerant findings parser, and the merge/dedup
+ confidence pipeline (with model replies replayed from fixtures).

They double as a regression corpus: add a diff/reply fixture when a real case slips through.
"""
import asyncio
import pathlib

import pytest

from cli_bridge import findings, runner, workflows
from cli_bridge.lanes import LaneSpec

FIX = pathlib.Path(__file__).parent / "fixtures"


def _diff(name: str) -> str:
    return (FIX / "reviews" / name).read_text()


def _reply(name: str) -> str:
    return (FIX / "replies" / name).read_text()


def _lane(key, display=None):
    return LaneSpec(key, display or key, "echo", lambda *a: [])


# ── prechecks against realistic diffs (fully deterministic safety net) ────────────────────

def test_eval_prechecks_catch_secrets():
    fs = workflows.prechecks(_diff("secret_leak.diff"))
    assert any("secret" in f.title.lower() for f in fs)
    # the secret value itself must be redacted in the evidence, never echoed
    joined = " ".join(f.evidence for f in fs)
    assert "sk-live_abcdef0123456789ABCDEF" not in joined
    assert "ghp_AbCdEf0123456789AbCdEf0123456789abcd" not in joined


def test_eval_prechecks_catch_dangerous_shell():
    titles = {f.title for f in workflows.prechecks(_diff("dangerous_shell.diff"))}
    assert any("os.system" in t for t in titles)
    assert any("shell=True" in t for t in titles)
    assert any("rm -rf" in t for t in titles) or any("download into a shell" in t for t in titles)


def test_eval_prechecks_quiet_on_clean_diff():
    assert workflows.prechecks(_diff("clean.diff")) == []


# ── parser corpus: every real-world reply shape lands somewhere sane, never crashes ───────

@pytest.mark.parametrize("name,parsed_ok,min_count", [
    ("clean_array.json", True, 2),
    ("fenced.txt", True, 1),
    ("prose_wrapped.txt", True, 1),
    ("no_issues.txt", True, 0),
    ("garbage.txt", False, 1),          # unparseable -> wrapped as ONE finding, not dropped
])
def test_eval_parser_corpus(name, parsed_ok, min_count):
    fs, ok = findings.parse_findings(_reply(name), role="correctness", lane="LaneA")
    assert ok is parsed_ok
    assert len(fs) >= min_count
    if name == "fenced.txt":
        assert fs[0].severity == "blocker"      # "critical" normalized
        assert fs[0].file == "db.py" and fs[0].line == 42


# ── end-to-end replay: two lanes return the SAME finding -> merged once, confidence rises ──

def test_eval_merge_raises_confidence_on_agreement():
    reply = _reply("fenced.txt")

    async def run_lane(lane, args, *, tool="ask", terse=True):
        return runner.RunResult(True, reply, "ok", latency_ms=5)

    report = asyncio.run(workflows.review_diff(
        [_lane("a", "LaneA"), _lane("b", "LaneB")], {"diff": _diff("clean.diff")}, run_lane))
    assert report.count("SQL injection") == 1     # deduped to a single entry
    assert "consensus" in report                  # both distinct lanes agreed


def test_eval_review_json_validates_against_schema():
    reply = _reply("clean_array.json")

    async def run_lane(lane, args, *, tool="ask", terse=True):
        return runner.RunResult(True, reply, "ok", latency_ms=5)

    import json
    out = json.loads(asyncio.run(workflows.review_diff(
        [_lane("a")], {"diff": _diff("clean.diff"), "output_format": "json"}, run_lane)))
    assert out["tool"] == "review_diff"
    for f in out["findings"]:
        assert f["severity"] in findings.SEVERITIES
        assert f["confidence"] in ("single", "majority", "consensus")
        assert f["id"].startswith("F")
