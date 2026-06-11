"""Rolling summary: a thread that outgrows the replay budget gets its old tail condensed by
the lane that just answered, instead of silently dropping turns off the window."""
import asyncio

import pytest

from cli_bridge import conversations, server, telemetry
from cli_bridge.lanes import LaneSpec
from cli_bridge.runner import RunResult


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_STATE_DB", str(tmp_path / "s.sqlite"))
    telemetry._reset_for_tests()
    yield
    telemetry._reset_for_tests()


def _fill(cid, turns, size=300):
    for i in range(turns):
        telemetry.convo_append(cid, "opencode", "user", f"q{i} " + "x" * size)
        telemetry.convo_append(cid, "opencode", "assistant", f"a{i} " + "y" * size)


# ── compaction_plan (pure decision) ───────────────────────────────────────────────────────────


def test_no_compaction_under_budget():
    _fill("c1", 3)
    assert conversations.compaction_plan("c1", 100_000) == (0, "")


def test_compaction_targets_old_tail_keeps_recent():
    _fill("c2", 10)
    upto, excerpt = conversations.compaction_plan("c2", 4000)
    assert upto >= 2                              # something to fold
    turns = telemetry.convo_turns("c2")
    kept = [t for t in turns if t["turn_number"] > upto]
    assert sum(len(t["content"]) for t in kept) <= 2000   # recent tail fits half the budget
    assert "q0" in excerpt                        # oldest turn is in the excerpt
    assert f"q{9}" not in excerpt                 # newest stays out of the fold


def test_tiny_thread_never_folded():
    telemetry.convo_append("c3", "opencode", "user", "x" * 50_000)   # one huge turn
    assert conversations.compaction_plan("c3", 4000) == (0, "")      # cut<2 → keep as is


# ── convo_compact (storage) ───────────────────────────────────────────────────────────────────


def test_compact_replaces_old_turns_with_summary():
    _fill("c4", 6)
    assert telemetry.convo_compact("c4", 8, "SUMMARY-BLOB", "opencode")
    turns = telemetry.convo_turns("c4")
    assert turns[0]["role"] == "summary" and turns[0]["content"] == "SUMMARY-BLOB"
    assert turns[0]["turn_number"] == 8
    assert all(t["turn_number"] > 8 for t in turns[1:])
    assert len(turns) == 1 + 4                    # 12 turns: 8 folded, 4 kept


def test_summary_turn_renders_in_replay():
    telemetry.convo_append("c5", "opencode", "summary", "earlier: code word DELTA")
    telemetry.convo_append("c5", "opencode", "user", "next question")
    prefix, _ = conversations.build_history_prefix("c5", "gemini", 32000)
    assert "Summary of earlier turns" in prefix and "DELTA" in prefix


# ── server hook (end-to-end with a fake lane) ─────────────────────────────────────────────────


def test_hook_compacts_via_the_answering_lane(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_CONVO_MAX_CHARS", "3000")
    lane = LaneSpec("opencode", "Opencode", "echo", lambda *a: [])
    calls = []

    async def fake_run_lane(ln, args, *, tool="ask", terse=True):
        calls.append(tool)
        if tool == "convo_summary":
            assert conversations.SUMMARY_PROMPT.splitlines()[0] in args["task"]
            return RunResult(True, "CONDENSED", "ok")
        return RunResult(True, "answer " + "z" * 500, "ok")
    monkeypatch.setattr(server, "_run_lane", fake_run_lane)

    cid = ""
    for i in range(8):
        res, cid = asyncio.run(server._run_lane_maybe_convo(
            lane, {"task": f"question {i} " + "w" * 500, "conversation": cid or "new"}))
        assert res.ok
    assert "convo_summary" in calls               # compaction fired
    turns = telemetry.convo_turns(cid)
    assert any(t["role"] == "summary" and t["content"] == "CONDENSED" for t in turns)
    total = sum(len(t["content"]) for t in turns)
    assert total < 8 * 1000                       # thread actually shrank


def test_hook_failure_leaves_thread_intact(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_CONVO_MAX_CHARS", "3000")
    lane = LaneSpec("opencode", "Opencode", "echo", lambda *a: [])

    async def fake_run_lane(ln, args, *, tool="ask", terse=True):
        if tool == "convo_summary":
            return RunResult(False, "", "empty")            # summarizer dead
        return RunResult(True, "answer " + "z" * 500, "ok")
    monkeypatch.setattr(server, "_run_lane", fake_run_lane)

    cid = ""
    for i in range(8):
        _res, cid = asyncio.run(server._run_lane_maybe_convo(
            lane, {"task": f"q{i} " + "w" * 500, "conversation": cid or "new"}))
    turns = telemetry.convo_turns(cid)
    assert all(t["role"] != "summary" for t in turns)       # nothing folded
    assert len(turns) == 16                                 # nothing lost either


def test_summary_disabled_by_env(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_CONVO_MAX_CHARS", "3000")
    monkeypatch.setenv("CLI_BRIDGE_CONVO_SUMMARY", "off")
    lane = LaneSpec("opencode", "Opencode", "echo", lambda *a: [])
    calls = []

    async def fake_run_lane(ln, args, *, tool="ask", terse=True):
        calls.append(tool)
        return RunResult(True, "answer " + "z" * 500, "ok")
    monkeypatch.setattr(server, "_run_lane", fake_run_lane)

    cid = ""
    for i in range(8):
        _res, cid = asyncio.run(server._run_lane_maybe_convo(
            lane, {"task": f"q{i} " + "w" * 500, "conversation": cid or "new"}))
    assert "convo_summary" not in calls
