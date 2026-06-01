"""review_diff workflow: role assignment, diff fetch, orchestration — all with fakes."""
import asyncio
import json
from types import SimpleNamespace

from cli_bridge import lanes, runner, workflows


def _lane(key, display=None, paid="free"):
    return lanes.LaneSpec(key, display or key, "echo", lambda task, m, e, a: [task],
                          cost_default=paid)


def test_assign_roles_round_robin_two_lanes():
    a, b = _lane("a"), _lane("b")
    got = workflows.assign_roles([a, b])
    roles = [r for r, _, _ in got]
    assert roles == [r for r, _ in workflows.REVIEW_ROLES]      # every role covered
    assert [ln.key for _, _, ln in got] == ["a", "b", "a", "b"]  # lanes cycle


def test_assign_roles_more_lanes_than_roles_uses_first_n():
    pool = [_lane(k) for k in ("a", "b", "c", "d", "e")]
    got = workflows.assign_roles(pool)
    assert len(got) == len(workflows.REVIEW_ROLES)               # one role each
    assert [ln.key for _, _, ln in got] == ["a", "b", "c", "d"]  # 5th lane unused


def test_assign_roles_empty():
    assert workflows.assign_roles([]) == []


def test_git_diff_success(monkeypatch):
    monkeypatch.setattr(workflows.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=0, stdout="diff --git a/x b/x\n+hi\n", stderr=""))
    text, err = workflows.git_diff("/repo", "HEAD")
    assert err == "" and "diff --git" in text


def test_git_diff_failure(monkeypatch):
    monkeypatch.setattr(workflows.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=128, stdout="", stderr="fatal: not a git repository"))
    text, err = workflows.git_diff("/nope", "")
    assert text == "" and "128" in err and "not a git repository" in err


def _fake_run_lane(record, *, ok=True, output="finding: bug", kind="ok"):
    async def run_lane(lane, args, *, tool="ask", terse=True):
        record.append({"lane": lane.key, "tool": tool, "terse": terse, "task": args["task"]})
        return runner.RunResult(ok, output, kind)
    return run_lane


def test_review_diff_end_to_end():
    rec = []
    targets = [_lane("a", "LaneA"), _lane("b", "LaneB")]
    args = {"diff": "diff --git a/f b/f\n+oops\n", "base": "HEAD"}
    report = asyncio.run(workflows.review_diff(targets, args, _fake_run_lane(rec)))

    assert "# Code review (multi-model)" in report
    assert "## Merged findings" in report
    assert "## Trace" in report
    # 4 role reviews + 1 merge pass
    assert len(rec) == len(workflows.REVIEW_ROLES) + 1
    # structured workflow must NOT compress with the terse preamble
    assert all(c["terse"] is False for c in rec)
    assert all(c["tool"] == "review_diff" for c in rec)
    # trace is valid JSON and lists every reviewer
    trace = json.loads(report.split("```json\n", 1)[1].split("\n```", 1)[0])
    assert trace["base"] == "HEAD"
    assert len(trace["reviewers"]) == len(workflows.REVIEW_ROLES)
    assert trace["merge_lane"] == "LaneA"


def test_review_diff_empty_diff():
    report = asyncio.run(workflows.review_diff([_lane("a")], {"diff": "   \n"}, _fake_run_lane([])))
    assert "empty diff" in report


def test_review_diff_git_error_propagates(monkeypatch):
    monkeypatch.setattr(workflows.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=128, stdout="", stderr="fatal: bad revision"))
    report = asyncio.run(workflows.review_diff([_lane("a")], {"base": "nope"}, _fake_run_lane([])))
    assert report.startswith("[error]") and "128" in report


def test_review_diff_all_reviewers_fail():
    rec = []
    rl = _fake_run_lane(rec, ok=False, output="rate limited", kind="quota")
    report = asyncio.run(workflows.review_diff([_lane("a")], {"diff": "x\n"}, rl))
    assert report.startswith("[error] all reviewers failed")
    assert "quota" in report


def test_review_diff_single_reviewer_no_merge():
    # one lane wears all roles, but if only ONE review comes back ok there's no merge pass.
    rec = []
    calls = {"n": 0}

    async def run_lane(lane, args, *, tool="ask", terse=True):
        calls["n"] += 1
        # first review ok, the rest fail -> only one usable review -> skip merge
        ok = calls["n"] == 1
        return runner.RunResult(ok, "the one finding" if ok else "boom",
                                "ok" if ok else "failed")

    report = asyncio.run(workflows.review_diff([_lane("solo")], {"diff": "x\n"}, run_lane))
    trace = json.loads(report.split("```json\n", 1)[1].split("\n```", 1)[0])
    assert trace["merge_lane"] == "n/a (single reviewer)"
    assert "the one finding" in report
    # 4 role attempts, NO 5th merge call
    assert calls["n"] == len(workflows.REVIEW_ROLES)


def test_review_diff_truncates_large_diff(monkeypatch):
    monkeypatch.setattr(workflows.config, "REVIEW_DIFF_MAX_CHARS", 50)
    rec = []
    big = "diff\n" + ("+x\n" * 100)
    asyncio.run(workflows.review_diff([_lane("a")], {"diff": big}, _fake_run_lane(rec)))
    # the prompt the reviewer received must carry the truncation note and be clipped
    assert "truncated to fit context" in rec[0]["task"]


# ── security_review (shares the diff-review engine, security-only roles) ──

def test_security_review_uses_owasp_roles_and_heading():
    rec = []
    targets = [_lane("a", "LaneA"), _lane("b", "LaneB")]
    report = asyncio.run(workflows.security_review(
        targets, {"diff": "diff --git a/f b/f\n+os.system(x)\n"}, _fake_run_lane(rec)))
    assert "# Security review (OWASP-aware)" in report
    assert all(c["tool"] == "security_review" and c["terse"] is False for c in rec)
    # OWASP framing reaches the reviewer prompt
    assert any("OWASP-aware" in c["task"] for c in rec)
    assert len(rec) == len(workflows.SECURITY_ROLES) + 1   # roles + merge


def test_security_review_empty_diff():
    out = asyncio.run(workflows.security_review([_lane("a")], {"diff": "  "}, _fake_run_lane([])))
    assert "empty diff" in out


# ── debate ──

def test_debate_rounds_and_report():
    rec = []
    targets = [_lane("a", "LaneA"), _lane("b", "LaneB")]
    report = asyncio.run(workflows.debate(targets, {"task": "Best sort?", "rounds": 1},
                                          _fake_run_lane(rec)))
    assert "# Debate" in report and "## Final answer" in report and "## Final positions" in report
    assert "rounds: 1" in report
    # 2 openers + 2 revisions + 1 judge
    assert len(rec) == 5
    assert all(c["tool"] == "debate" for c in rec)


def test_debate_zero_rounds_skips_revision():
    rec = []
    targets = [_lane("a"), _lane("b")]
    asyncio.run(workflows.debate(targets, {"task": "q", "rounds": 0}, _fake_run_lane(rec)))
    assert len(rec) == 3            # 2 openers + judge, no revision round


def test_debate_single_debater_no_judge():
    rec = []
    report = asyncio.run(workflows.debate([_lane("solo", "Solo")], {"task": "q", "rounds": 2},
                                          _fake_run_lane(rec)))
    assert "n/a (single debater)" in report
    assert len(rec) == 1           # one opener; nothing to debate, no judge


def test_debate_requires_question():
    out = asyncio.run(workflows.debate([_lane("a")], {"task": "  "}, _fake_run_lane([])))
    assert out.startswith("[error]")


def test_debate_caps_debaters():
    rec = []
    targets = [_lane(f"l{i}") for i in range(8)]   # 8 lanes, cap is 4
    asyncio.run(workflows.debate(targets, {"task": "q", "rounds": 0}, _fake_run_lane(rec)))
    assert len(rec) == workflows.DEBATE_MAX_DEBATERS + 1   # 4 openers + judge
