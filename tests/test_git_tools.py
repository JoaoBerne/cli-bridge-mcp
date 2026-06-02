"""commit_msg + pr_describe: read-only git → text. git is faked, no real repo, no real CLI."""
import asyncio

from cli_bridge import server, telemetry, workflows
from cli_bridge.lanes import LaneSpec
from cli_bridge.runner import RunResult

LANE = LaneSpec("gemini", "Gemini", "echo", lambda *x: [])


def _lane_ok(text):
    async def run_lane(lane, args, *, tool="ask", terse=True):
        return RunResult(True, text, "ok")
    return run_lane


def test_commit_msg_uses_staged(monkeypatch):
    monkeypatch.setattr(workflows, "_git",
                        lambda cwd, a: ("diff --git a/x b/x", "") if a == ["diff", "--staged"] else ("", ""))
    out = asyncio.run(workflows.commit_msg([LANE], {}, _lane_ok("feat: add x")))
    assert "feat: add x" in out and "staged" in out


def test_commit_msg_falls_back_to_working_tree(monkeypatch):
    def fake_git(cwd, a):
        if a == ["diff", "--staged"]:
            return "", ""                 # nothing staged
        if a == ["diff"]:
            return "diff --git a/y b/y", ""
        return "", ""
    monkeypatch.setattr(workflows, "_git", fake_git)
    out = asyncio.run(workflows.commit_msg([LANE], {}, _lane_ok("fix: y")))
    assert "fix: y" in out and "working tree" in out


def test_commit_msg_clean_tree(monkeypatch):
    monkeypatch.setattr(workflows, "_git", lambda cwd, a: ("", ""))
    out = asyncio.run(workflows.commit_msg([LANE], {}, _lane_ok("x")))
    assert "no changes" in out


def test_commit_msg_surfaces_git_error(monkeypatch):
    monkeypatch.setattr(workflows, "_git", lambda cwd, a: ("", "git is not installed / not on PATH."))
    out = asyncio.run(workflows.commit_msg([LANE], {}, _lane_ok("x")))
    assert "[error]" in out and "git is not installed" in out


def test_pr_describe_builds_description(monkeypatch):
    monkeypatch.setattr(workflows, "git_diff", lambda cwd, base: ("diff --git a/z b/z", ""))
    monkeypatch.setattr(workflows, "_git", lambda cwd, a: ("abc123 feat: z", ""))
    out = asyncio.run(workflows.pr_describe([LANE], {"base": "main"},
                                            _lane_ok("Title\n## Summary\nx")))
    assert "PR description" in out and "## Summary" in out


def test_pr_describe_no_diff(monkeypatch):
    monkeypatch.setattr(workflows, "git_diff", lambda cwd, base: ("", ""))
    out = asyncio.run(workflows.pr_describe([LANE], {"base": "main"}, _lane_ok("x")))
    assert "no diff" in out


def test_commit_msg_dispatch(monkeypatch, tmp_path):
    monkeypatch.setenv("CLI_BRIDGE_STATE_DB", str(tmp_path / "s.sqlite"))
    telemetry._reset_for_tests()
    monkeypatch.setattr(server, "_active_lanes", lambda: ([LANE], ""))
    monkeypatch.setattr(workflows, "_git", lambda cwd, a: ("diff x", ""))

    async def fr(lane, args, *, tool="ask", terse=True):
        return RunResult(True, "chore: bump deps", "ok")
    monkeypatch.setattr(server, "_run_lane", fr)
    out = asyncio.run(server.call_tool("commit_msg", {}))[0].text
    assert "chore: bump deps" in out
    telemetry._reset_for_tests()
