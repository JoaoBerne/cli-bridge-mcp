"""Native session continuity: lanes that can hold their own session (claude mints a UUID,
opencode names its session in --print-logs output) resume natively; the prompt replays only
the cross-lane delta. Replay stays the source of truth — every turn is still recorded."""
import asyncio
import re

import pytest

from cli_bridge import server, telemetry
from cli_bridge.lanes import LaneSpec
from cli_bridge.runner import RunResult

MINT = {"mode": "mint", "first": ["--session-id", "{sid}"], "resume": ["--resume", "{sid}"]}
CAPTURE = {"mode": "capture", "spawn": ["--print-logs"],
           "pattern": r"ses_[A-Za-z0-9]{10,}", "resume": ["-s", "{sid}"]}


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_STATE_DB", str(tmp_path / "s.sqlite"))
    telemetry._reset_for_tests()
    yield
    telemetry._reset_for_tests()


def _convo(lane, args):
    return asyncio.run(server._run_lane_maybe_convo(lane, args))


def test_mint_lane_mints_then_resumes(monkeypatch):
    lane = LaneSpec("claude", "Claude", "echo", lambda *a: [], native_session=MINT)
    seen = []

    async def fake_run_lane(ln, args, *, tool="ask", terse=True):
        seen.append(args.get("_native_argv"))
        return RunResult(True, "answer", "ok")
    monkeypatch.setattr(server, "_run_lane", fake_run_lane)

    _res, cid = _convo(lane, {"task": "t1", "conversation": "new"})
    _convo(lane, {"task": "t2", "conversation": cid})
    assert seen[0][0] == "--session-id" and re.fullmatch(r"[0-9a-f-]{36}", seen[0][1])
    assert seen[1] == ["--resume", seen[0][1]]            # same minted handle, resumed


def test_resume_turn_replays_only_the_delta(monkeypatch):
    a = LaneSpec("claude", "Claude", "echo", lambda *x: [], native_session=MINT)
    b = LaneSpec("ollama", "Ollama", "echo", lambda *x: [])
    prompts = []

    async def fake_run_lane(ln, args, *, tool="ask", terse=True):
        prompts.append(args["task"])
        return RunResult(True, f"answer-{len(prompts)}", "ok")
    monkeypatch.setattr(server, "_run_lane", fake_run_lane)

    _res, cid = _convo(a, {"task": "claude-q1", "conversation": "new"})
    _convo(b, {"task": "ollama-q", "conversation": cid})
    _convo(a, {"task": "claude-q2", "conversation": cid})
    final = prompts[-1]
    assert "ollama-q" in final                            # the delta IS replayed
    assert "claude-q1" not in final                       # already inside claude's own session


def test_capture_lane_captures_from_stderr_then_resumes(monkeypatch):
    lane = LaneSpec("opencode", "Opencode", "echo", lambda *a: [], native_session=CAPTURE)
    seen = []

    async def fake_run_lane(ln, args, *, tool="ask", terse=True):
        seen.append(args.get("_native_argv"))
        return RunResult(True, "answer", "ok", err="INFO session created ses_abc123DEF456xy")
    monkeypatch.setattr(server, "_run_lane", fake_run_lane)

    _res, cid = _convo(lane, {"task": "t1", "conversation": "new"})
    _convo(lane, {"task": "t2", "conversation": cid})
    assert seen[0] == ["--print-logs"]                    # first turn spawns verbose
    assert seen[1] == ["-s", "ses_abc123DEF456xy"]        # captured handle, resumed


def test_failed_resume_drops_handle_and_falls_back(monkeypatch):
    lane = LaneSpec("claude", "Claude", "echo", lambda *a: [], native_session=MINT)
    prompts = []

    async def fake_run_lane(ln, args, *, tool="ask", terse=True):
        prompts.append(args)
        if args.get("_native_argv", [""])[0] == "--resume":
            return RunResult(False, "session gone", "failed")     # vendor lost the session
        return RunResult(True, "answer", "ok")
    monkeypatch.setattr(server, "_run_lane", fake_run_lane)

    _res, cid = _convo(lane, {"task": "t1", "conversation": "new"})
    res2, _ = _convo(lane, {"task": "t2", "conversation": cid})
    assert not res2.ok                                    # the broken turn fails visibly
    res3, _ = _convo(lane, {"task": "t3", "conversation": cid})
    assert res3.ok
    argv3 = prompts[-1].get("_native_argv")
    assert argv3 and argv3[0] == "--session-id"           # re-minted: handle was dropped
    assert "t1" in prompts[-1]["task"]                    # full replay backs the fresh session


def test_lane_without_native_session_uses_pure_replay(monkeypatch):
    lane = LaneSpec("ollama", "Ollama", "echo", lambda *a: [])
    seen = []

    async def fake_run_lane(ln, args, *, tool="ask", terse=True):
        seen.append(args)
        return RunResult(True, "answer", "ok")
    monkeypatch.setattr(server, "_run_lane", fake_run_lane)

    _res, cid = _convo(lane, {"task": "t1", "conversation": "new"})
    _convo(lane, {"task": "t2", "conversation": cid})
    assert all("_native_argv" not in a for a in seen)
    assert "t1" in seen[1]["task"]                        # classic replay


def test_env_off_forces_pure_replay(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_NATIVE_SESSIONS", "off")
    lane = LaneSpec("claude", "Claude", "echo", lambda *a: [], native_session=MINT)
    seen = []

    async def fake_run_lane(ln, args, *, tool="ask", terse=True):
        seen.append(args)
        return RunResult(True, "answer", "ok")
    monkeypatch.setattr(server, "_run_lane", fake_run_lane)

    _res, cid = _convo(lane, {"task": "t1", "conversation": "new"})
    _convo(lane, {"task": "t2", "conversation": cid})
    assert all("_native_argv" not in a for a in seen)


def test_native_argv_inserted_before_task():
    lane = LaneSpec("claude", "Claude", "echo",
                    lambda task, model, effort, agent, bin="": ["--print", task])
    # emulate _run_lane's insertion contract
    argv = ["echo"] + lane.build_ask("the task", "", "", "", "echo")
    extra = ["--resume", "abc"]
    argv = argv[:-1] + extra + argv[-1:]
    assert argv == ["echo", "--print", "--resume", "abc", "the task"]
