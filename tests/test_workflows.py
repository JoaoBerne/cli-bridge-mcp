"""review_diff workflow: role assignment, diff fetch, orchestration — all with fakes."""
import asyncio
import json
from types import SimpleNamespace

from cli_bridge import lanes, runner, workflows


def _lane(key, display=None, paid="free"):
    return lanes.LaneSpec(key, display or key, "echo", lambda task, m, e, a: [task],
                          cost_default=paid)


def test_assign_round_robin_two_lanes():
    a, b = _lane("a"), _lane("b")
    got = workflows._assign(workflows.REVIEW_ROLES, [a, b])
    roles = [r for r, _, _ in got]
    assert roles == [r for r, _ in workflows.REVIEW_ROLES]      # every role covered
    assert [ln.key for _, _, ln in got] == ["a", "b", "a", "b"]  # lanes cycle


def test_assign_more_lanes_than_roles_uses_first_n():
    pool = [_lane(k) for k in ("a", "b", "c", "d", "e")]
    got = workflows._assign(workflows.REVIEW_ROLES, pool)
    assert len(got) == len(workflows.REVIEW_ROLES)               # one role each
    assert [ln.key for _, _, ln in got] == ["a", "b", "c", "d"]  # 5th lane unused


def test_assign_empty():
    assert workflows._assign(workflows.REVIEW_ROLES, []) == []


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


# reviewers now return a JSON array of findings (M3 structured output)
_JSON_FINDING = ('[{"severity":"high","title":"Bug X","file":"f.py","line":3,'
                 '"evidence":"oops","recommendation":"fix it"}]')


def _fake_run_lane(record, *, ok=True, output=_JSON_FINDING, kind="ok", latency_ms=5):
    async def run_lane(lane, args, *, tool="ask", terse=True):
        record.append({"lane": lane.key, "tool": tool, "terse": terse, "task": args["task"]})
        return runner.RunResult(ok, output, kind, latency_ms=latency_ms)
    return run_lane


def test_review_diff_end_to_end():
    rec = []
    targets = [_lane("a", "LaneA"), _lane("b", "LaneB")]
    args = {"diff": "diff --git a/f b/f\n+oops\n", "base": "HEAD"}
    report = asyncio.run(workflows.review_diff(targets, args, _fake_run_lane(rec)))

    assert "# Code review (multi-model)" in report
    assert "**Bug X**" in report and "`f.py:3`" in report
    assert "consensus" in report                 # both lanes raised the identical finding
    assert "## Trace" in report
    # 4 role reviews, NO separate LLM merge pass (merge is deterministic now)
    assert len(rec) == len(workflows.REVIEW_ROLES)
    # structured workflow must NOT compress with the terse preamble
    assert all(c["terse"] is False for c in rec)
    assert all(c["tool"] == "review_diff" for c in rec)
    trace = json.loads(report.split("```json\n", 1)[1].split("\n```", 1)[0])
    assert trace["base"] == "HEAD"
    assert len(trace["reviewers"]) == len(workflows.REVIEW_ROLES)
    assert "merge_lane" not in trace             # deterministic merge has no judge lane


def test_review_diff_json_output():
    rec = []
    report = asyncio.run(workflows.review_diff(
        [_lane("a", "LaneA")], {"diff": "diff\n+oops\n", "output_format": "json"},
        _fake_run_lane(rec)))
    data = json.loads(report)                    # whole body is JSON
    assert data["tool"] == "review_diff" and data["status"] == "ok"
    assert data["findings"][0]["title"] == "Bug X"
    assert data["findings"][0]["id"] == "F001"


def test_review_diff_unparsed_reply_is_wrapped_not_dropped():
    rec = []
    rl = _fake_run_lane(rec, output="I think there's a bug somewhere, trust me")
    report = asyncio.run(workflows.review_diff([_lane("a")], {"diff": "x\n+y\n"}, rl))
    assert "Unparsed" in report                  # free-text reply preserved as a finding


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
    report = asyncio.run(workflows.review_diff([_lane("a")], {"diff": "x\n+benign\n"}, rl))
    assert report.startswith("[error] all reviewers failed")
    assert "quota" in report


def test_review_diff_precheck_catches_secret_even_if_reviewers_blank():
    rec = []
    rl = _fake_run_lane(rec, output="[]")        # reviewers find nothing
    diff = 'diff --git a/c.py b/c.py\n+++ b/c.py\n+api_key = "sk-abcdef123456789"\n'
    report = asyncio.run(workflows.review_diff([_lane("a")], {"diff": diff}, rl))
    assert "secret" in report.lower()            # deterministic precheck caught it
    assert "sk-abcdef123456789" not in report    # ...and redacted the value


def test_review_diff_single_reviewer_confidence_single():
    rec = []
    calls = {"n": 0}

    async def run_lane(lane, args, *, tool="ask", terse=True):
        calls["n"] += 1
        ok = calls["n"] == 1                      # only the first role returns
        return runner.RunResult(ok, '[{"severity":"high","title":"Solo bug"}]' if ok else "boom",
                                "ok" if ok else "failed", latency_ms=1)

    report = asyncio.run(workflows.review_diff([_lane("solo")], {"diff": "x\n+y\n"}, run_lane))
    assert "Solo bug" in report and "single" in report
    assert calls["n"] == len(workflows.REVIEW_ROLES)   # all role attempts, no merge call


def test_review_diff_truncates_large_diff(monkeypatch):
    monkeypatch.setattr(workflows.config, "REVIEW_DIFF_MAX_CHARS", 50)
    rec = []
    big = "diff\n" + ("+x\n" * 100)
    asyncio.run(workflows.review_diff([_lane("a")], {"diff": big}, _fake_run_lane(rec)))
    # the prompt the reviewer received must carry the truncation note and be clipped
    assert "truncated to fit context" in rec[0]["task"]


# ── security_review (shares the diff-review engine, security-only roles) ──

def test_security_review_uses_owasp_roles_heading_and_residual():
    rec = []
    targets = [_lane("a", "LaneA"), _lane("b", "LaneB")]
    report = asyncio.run(workflows.security_review(
        targets, {"diff": "diff --git a/f b/f\n+++ b/f\n+os.system(x)\n"}, _fake_run_lane(rec)))
    assert "# Security review (OWASP-aware)" in report
    assert all(c["tool"] == "security_review" and c["terse"] is False for c in rec)
    assert any("OWASP-aware" in c["task"] for c in rec)
    assert len(rec) == len(workflows.SECURITY_ROLES)   # roles only, no merge pass
    assert "## Residual risk" in report                # security report carries residual risk
    assert "os.system" in report                       # precheck flagged the dangerous call


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
    # 2 openers + 2 revisions + 1 judge + 1 fact-check (free lane present → default on)
    assert len(rec) == 6
    assert all(c["tool"] == "debate" for c in rec)


def test_debate_zero_rounds_skips_revision():
    rec = []
    targets = [_lane("a"), _lane("b")]
    asyncio.run(workflows.debate(targets, {"task": "q", "rounds": 0}, _fake_run_lane(rec)))
    assert len(rec) == 4            # 2 openers + judge + fact-check, no revision round


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
    assert len(rec) == workflows.DEBATE_MAX_DEBATERS + 2   # 4 openers + judge + fact-check


# ── premortem / test_plan (M7) ──

def test_premortem_requires_task():
    out = asyncio.run(workflows.premortem([_lane("a")], {"task": "  "}, _fake_run_lane([])))
    assert out.startswith("[error]")


def test_premortem_fans_out_and_merges():
    rec = []
    targets = [_lane("a", "LaneA"), _lane("b", "LaneB")]
    rl = _fake_run_lane(rec, output="Risk: data loss; mitigation: backups")
    report = asyncio.run(workflows.premortem(targets, {"task": "ship a migration"}, rl))
    assert "# Premortem (multi-model)" in report
    assert "## Council" in report and "## Merged" in report
    assert len(rec) == 3                          # 2 openers + 1 merge
    assert all(c["terse"] is False for c in rec)
    assert any("PREMORTEM" in c["task"] for c in rec)


def test_test_plan_from_diff():
    rec = []
    rl = _fake_run_lane(rec, output="Test: empty input case")
    report = asyncio.run(workflows.test_plan(
        [_lane("a", "LaneA")], {"diff": "diff --git a/f b/f\n+def g(): ...\n"}, rl))
    assert "# Test plan (multi-model)" in report
    assert any("TEST PLAN" in c["task"] and "```diff" in c["task"] for c in rec)


def test_test_plan_from_task_text():
    rec = []
    rl = _fake_run_lane(rec, output="Test: boundary")
    report = asyncio.run(workflows.test_plan(
        [_lane("a")], {"task": "a function that sums a list"}, rl))
    assert "# Test plan (multi-model)" in report
    assert any("sums a list" in c["task"] for c in rec)


def test_test_plan_empty_diff_no_task():
    out = asyncio.run(workflows.test_plan([_lane("a")], {"diff": "   "}, _fake_run_lane([])))
    assert "empty diff" in out


def test_council_no_lanes():
    out = asyncio.run(workflows.premortem([], {"task": "x"}, _fake_run_lane([])))
    assert out.startswith("[error] no lanes")
