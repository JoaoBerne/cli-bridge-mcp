"""Isolated build: the agent edits a throwaway worktree, we return its diff, and the real repo
is never touched. Uses a real temp git repo (git only — no AI CLI, no network)."""
import asyncio
import os
import subprocess

import pytest

from cli_bridge import worktrees
from cli_bridge.lanes import LaneSpec
from cli_bridge.runner import RunResult


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    _git(["init", "-q"], d)
    _git(["config", "user.email", "t@t.t"], d)
    _git(["config", "user.name", "t"], d)
    (d / "a.txt").write_text("original\n")
    _git(["add", "-A"], d)
    _git(["commit", "-qm", "init"], d)
    return d


def _build_lane():
    # a lane that advertises write/build mode (has the 'agent' cap)
    return LaneSpec("opencode", "Opencode", "echo", lambda *a: [], caps=("model", "effort", "agent"))


def _writer_run_lane(filename, content):
    """Fake run_lane: behaves like a build agent — writes a file into the worktree cwd."""
    async def run_lane(lane, args, *, tool="ask", terse=True):
        assert args.get("agent") == "build"          # isolated build must request write mode
        path = os.path.join(args["cwd"], filename)
        with open(path, "w") as fh:
            fh.write(content)
        return RunResult(True, f"wrote {filename}", "ok", latency_ms=10)
    return run_lane


def test_isolated_build_returns_diff_and_leaves_repo_clean(repo):
    rl = _writer_run_lane("new_feature.py", "print('hi')\n")
    report = asyncio.run(worktrees.ask_build_isolated(
        _build_lane(), {"task": "add a feature", "cwd": str(repo)}, rl))

    assert "# Isolated build (worktree)" in report
    assert "wrote new_feature.py" in report
    assert "new_feature.py" in report and "print('hi')" in report   # diff shown
    # real repo untouched: file absent, working tree clean
    assert not (repo / "new_feature.py").exists()
    status = subprocess.run(["git", "status", "--porcelain"], cwd=repo,
                            capture_output=True, text=True).stdout
    assert status.strip() == ""


def test_isolated_build_no_changes(repo):
    async def noop_run_lane(lane, args, *, tool="ask", terse=True):
        return RunResult(True, "nothing to do", "ok", latency_ms=5)
    report = asyncio.run(worktrees.ask_build_isolated(
        _build_lane(), {"task": "noop", "cwd": str(repo)}, noop_run_lane))
    assert "made no file changes" in report


def test_isolated_build_cleans_up_worktree(repo):
    rl = _writer_run_lane("x.py", "1\n")
    asyncio.run(worktrees.ask_build_isolated(_build_lane(), {"task": "t", "cwd": str(repo)}, rl))
    # no leftover worktrees registered on the repo
    out = subprocess.run(["git", "worktree", "list"], cwd=repo,
                         capture_output=True, text=True).stdout
    assert "cli-bridge-wt-" not in out


def test_isolated_build_keep_env(repo, monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_KEEP_WORKTREES", "1")
    rl = _writer_run_lane("x.py", "1\n")
    report = asyncio.run(worktrees.ask_build_isolated(
        _build_lane(), {"task": "t", "cwd": str(repo)}, rl))
    assert "kept at" in report


def test_isolated_build_rejects_non_git(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    rl = _writer_run_lane("x", "y")
    report = asyncio.run(worktrees.ask_build_isolated(
        _build_lane(), {"task": "t", "cwd": str(plain)}, rl))
    assert report.startswith("[error]") and "git repo" in report


def test_isolated_build_rejects_lane_without_build():
    ro_lane = LaneSpec("ro", "ReadOnly", "echo", lambda *a: [], caps=("model",))

    async def rl(lane, args, *, tool="ask", terse=True):
        return RunResult(True, "x", "ok")
    report = asyncio.run(worktrees.ask_build_isolated(ro_lane, {"task": "t"}, rl))
    assert report.startswith("[error]") and "build" in report


# ── M12-2: architect/editor split (strong lane plans, editor lane applies) ─────────────────

def test_architect_editor_split_plans_then_builds(repo):
    calls = []

    async def run_lane(lane, args, *, tool="ask", terse=True):
        calls.append((lane.key, args.get("agent"), args["task"]))
        if args.get("agent") != "build":                     # architect: plan only, no writes
            return RunResult(True, "PLAN: create feature.py printing hi", "ok")
        assert "PLAN (from the architect)" in args["task"]    # editor implements the plan
        with open(os.path.join(args["cwd"], "feature.py"), "w") as fh:
            fh.write("print('hi')\n")
        return RunResult(True, "wrote feature.py", "ok")

    architect = LaneSpec("gpt", "GPT", "echo", lambda *a: [])   # needs no build caps
    report = asyncio.run(worktrees.ask_build_isolated(
        _build_lane(), {"task": "add feature", "cwd": str(repo)}, run_lane, architect=architect))

    assert "## Plan (architect)" in report and "architect: GPT" in report
    assert "feature.py" in report and "print('hi')" in report
    assert [c[0] for c in calls] == ["gpt", "opencode"]        # architect first, then editor
    assert calls[0][1] is None and calls[1][1] == "build"      # only the editor uses write mode


def test_architect_failure_falls_back_to_solo_editor(repo):
    async def run_lane(lane, args, *, tool="ask", terse=True):
        if args.get("agent") != "build":
            return RunResult(False, "boom", "failed")          # architect dies
        assert "PLAN (from the architect)" not in args["task"]  # editor gets the original task
        with open(os.path.join(args["cwd"], "f.py"), "w") as fh:
            fh.write("x\n")
        return RunResult(True, "built solo", "ok")

    architect = LaneSpec("gpt", "GPT", "echo", lambda *a: [])
    report = asyncio.run(worktrees.ask_build_isolated(
        _build_lane(), {"task": "do", "cwd": str(repo)}, run_lane, architect=architect))
    assert "architect GPT FAILED" in report
    assert "## Plan (architect)" not in report
    assert "built solo" in report
