"""Opt-in read-only mutation guard (CLI_BRIDGE_VERIFY_PLAN_READONLY): a 'plan' delegate that writes
to a git workspace is flagged (never auto-reverted). Helpers tested on a real temp repo; the
_run_lane wiring tested with a faked spawn (no real CLI)."""
import asyncio
import subprocess

import pytest

from cli_bridge import server
from cli_bridge.lanes import LaneSpec
from cli_bridge.runner import RunResult


def _git_init(d):
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "--allow-empty", "-qm", "init"], cwd=d, check=True)


def _fake_lane():
    return LaneSpec("gpt", "GPT", "echo", lambda *a: ["x"], caps=frozenset({"model", "agent"}))


# ── snapshot gating ───────────────────────────────────────────────────────────────────────────

def test_snapshot_off_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("CLI_BRIDGE_VERIFY_PLAN_READONLY", raising=False)
    _git_init(tmp_path)
    snap, root = server._readonly_guard_snapshot("plan", str(tmp_path))
    assert snap is None and root == ""


def test_snapshot_skips_build(tmp_path, monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_VERIFY_PLAN_READONLY", "1")
    _git_init(tmp_path)
    snap, _ = server._readonly_guard_snapshot("build", str(tmp_path))   # build may write
    assert snap is None


def test_snapshot_skips_non_repo(tmp_path, monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_VERIFY_PLAN_READONLY", "1")
    snap, _ = server._readonly_guard_snapshot("plan", str(tmp_path))    # not a git repo
    assert snap is None


# ── diff + banner ─────────────────────────────────────────────────────────────────────────────

def test_diff_flags_a_write(tmp_path, monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_VERIFY_PLAN_READONLY", "1")
    _git_init(tmp_path)
    before, root = server._readonly_guard_snapshot("plan", str(tmp_path))
    assert before is not None
    (tmp_path / "snuck_in.py").write_text("x = 1\n")
    assert "snuck_in.py" in server._readonly_guard_diff(root, before)


def test_diff_clean_run_not_flagged(tmp_path, monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_VERIFY_PLAN_READONLY", "1")
    _git_init(tmp_path)
    before, root = server._readonly_guard_snapshot("plan", str(tmp_path))
    assert server._readonly_guard_diff(root, before) == []


def test_banner_lists_paths_and_count():
    b = server._readonly_mutation_banner(["a.py", "b.py"])
    assert "WORKSPACE MUTATION DETECTED" in b and "a.py" in b and "2 path" in b


# ── _run_lane wiring (faked spawn — no real CLI) ───────────────────────────────────────────────

def test_run_lane_flags_readonly_mutation(tmp_path, monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_VERIFY_PLAN_READONLY", "1")
    monkeypatch.setenv("CLI_BRIDGE_STATE_DB", str(tmp_path / "t.sqlite"))
    _git_init(tmp_path)

    async def fake_spawn(argv, timeout, expanded, env):
        (tmp_path / "written_by_delegate.py").write_text("x = 1\n")     # delegate writes despite plan
        return RunResult(True, "here is my analysis", "ok")

    monkeypatch.setattr(server, "_spawn_with_retry", fake_spawn)
    res = asyncio.run(server._run_lane(
        _fake_lane(), {"task": "review", "cwd": str(tmp_path), "agent": "plan"}))
    assert res.mutated is True
    assert "WORKSPACE MUTATION DETECTED" in res.output
    assert "written_by_delegate.py" in res.output
    assert res.output.rstrip().endswith("here is my analysis")          # original answer preserved


def test_run_lane_build_run_not_flagged(tmp_path, monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_VERIFY_PLAN_READONLY", "1")
    monkeypatch.setenv("CLI_BRIDGE_STATE_DB", str(tmp_path / "t.sqlite"))
    _git_init(tmp_path)

    async def fake_spawn(argv, timeout, expanded, env):
        (tmp_path / "built.py").write_text("x = 1\n")                   # build is ALLOWED to write
        return RunResult(True, "built it", "ok")

    monkeypatch.setattr(server, "_spawn_with_retry", fake_spawn)
    res = asyncio.run(server._run_lane(
        _fake_lane(), {"task": "build it", "cwd": str(tmp_path), "agent": "build"}))
    assert res.mutated is False and "MUTATION" not in res.output


def test_run_lane_toggle_off_no_flag(tmp_path, monkeypatch):
    monkeypatch.delenv("CLI_BRIDGE_VERIFY_PLAN_READONLY", raising=False)
    monkeypatch.setenv("CLI_BRIDGE_STATE_DB", str(tmp_path / "t.sqlite"))
    _git_init(tmp_path)

    async def fake_spawn(argv, timeout, expanded, env):
        (tmp_path / "x.py").write_text("x = 1\n")
        return RunResult(True, "analysis", "ok")

    monkeypatch.setattr(server, "_spawn_with_retry", fake_spawn)
    res = asyncio.run(server._run_lane(
        _fake_lane(), {"task": "review", "cwd": str(tmp_path), "agent": "plan"}))
    assert res.mutated is False and "MUTATION" not in res.output


@pytest.mark.parametrize("n,expect_more", [(5, False), (25, True)])
def test_banner_truncates_long_lists(n, expect_more):
    b = server._readonly_mutation_banner([f"f{i}.py" for i in range(n)])
    assert ("more" in b) is expect_more
