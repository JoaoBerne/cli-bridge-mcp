"""files_required_to_continue (M12-3): when a brief names local source files that weren't passed
as context_files, debate/consensus ask for them instead of opining on the host's paraphrase."""
import asyncio

from cli_bridge import workflows
from cli_bridge.lanes import LaneSpec
from cli_bridge.runner import RunResult


def _lane(key, display=None):
    return LaneSpec(key, display or key, "echo", lambda *a: [])


def _norun():
    calls = []

    async def run_lane(lane, args, *, tool="ask", terse=True):
        calls.append(lane.key)
        return RunResult(True, "ans", "ok")
    return run_lane, calls


# ── detector ─────────────────────────────────────────────────────────────────────────────────

def test_detect_referenced_files_finds_paths_and_skips_noise():
    got = workflows.detect_referenced_files(
        "Is the retry in runner.py and src/cli_bridge/lanes.py correct? Version 1.0, e.g. this.")
    assert "runner.py" in got and "src/cli_bridge/lanes.py" in got
    assert "1.0" not in got                        # version number, not a file
    # dedup + order preserved
    assert workflows.detect_referenced_files("a.py then a.py again") == ["a.py"]


# ── gate ───────────────────────────────────────────────────────────────────────────────────────

def test_files_required_asks_for_named_existing_file(tmp_path):
    (tmp_path / "runner.py").write_text("x = 1\n")
    out = workflows.files_required("Review the logic in runner.py", None, str(tmp_path))
    assert "files_required_to_continue" in out
    assert '"runner.py"' in out


def test_files_required_silent_when_file_provided(tmp_path):
    (tmp_path / "runner.py").write_text("x = 1\n")
    assert workflows.files_required(
        "Review runner.py", ["runner.py"], str(tmp_path)) == ""
    # basename match also satisfies it (host passed a fuller path)
    assert workflows.files_required(
        "Review runner.py", ["src/runner.py"], str(tmp_path)) == ""


def test_files_required_silent_when_override_or_nonexistent(tmp_path):
    (tmp_path / "runner.py").write_text("x = 1\n")
    assert workflows.files_required(
        "Review runner.py", None, str(tmp_path), allow_ungrounded=True) == ""
    # a named file that doesn't exist here is treated as hypothetical, not blocking
    assert workflows.files_required("Review ghost.py", None, str(tmp_path)) == ""


# ── integration: the gate stops the spawn ──────────────────────────────────────────────────────

def test_debate_blocks_on_ungrounded_named_file(tmp_path):
    (tmp_path / "auth.py").write_text("def f(): ...\n")
    run_lane, calls = _norun()
    out = asyncio.run(workflows.debate(
        [_lane("a"), _lane("b")],
        {"task": "Is the check in auth.py safe?", "cwd": str(tmp_path)}, run_lane))
    assert "files_required_to_continue" in out
    assert calls == []                              # nothing spawned


def test_debate_proceeds_with_allow_ungrounded(tmp_path):
    (tmp_path / "auth.py").write_text("def f(): ...\n")
    run_lane, calls = _norun()
    out = asyncio.run(workflows.debate(
        [_lane("a"), _lane("b")],
        {"task": "Is the check in auth.py safe?", "cwd": str(tmp_path),
         "allow_ungrounded": True}, run_lane))
    assert "files_required_to_continue" not in out
    assert calls                                    # lanes were spawned


def test_consensus_blocks_on_ungrounded_named_file(tmp_path):
    (tmp_path / "api.py").write_text("def g(): ...\n")
    run_lane, calls = _norun()
    out = asyncio.run(workflows.consensus(
        [_lane("a"), _lane("b")],
        {"task": "Does api.py handle errors?", "cwd": str(tmp_path)}, run_lane))
    assert "files_required_to_continue" in out
    assert calls == []
