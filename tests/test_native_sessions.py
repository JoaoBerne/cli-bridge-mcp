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


def test_fold_overlap_invalidates_native_handle(monkeypatch):
    # Lane's native session saw turns 1..2; compaction then folded 1..4 into a summary turn
    # (turn_number=4 > last_seen=2). Resuming would duplicate context — handle must drop.
    lane = LaneSpec("claude", "Claude", "echo", lambda *a: [], native_session=MINT)
    seen = []

    async def fake_run_lane(ln, args, *, tool="ask", terse=True):
        seen.append(args.get("_native_argv"))
        return RunResult(True, "answer", "ok")
    monkeypatch.setattr(server, "_run_lane", fake_run_lane)

    _res, cid = _convo(lane, {"task": "t1", "conversation": "new"})     # turns 1-2, last_seen=2
    for i in range(3, 5):
        telemetry.convo_append(cid, "ollama", "user", f"q{i}")
        telemetry.convo_append(cid, "ollama", "assistant", f"a{i}")
    assert telemetry.convo_compact(cid, 4, "FOLDED 1-4", "ollama")      # fold past last_seen
    _convo(lane, {"task": "t2", "conversation": cid})
    assert seen[1][0] == "--session-id"            # re-minted, NOT --resume
    sid1 = seen[0][1]
    assert seen[1][1] != sid1                      # fresh session


def test_fold_behind_last_seen_keeps_handle(monkeypatch):
    # Fold point ≤ last_seen: the lane already saw everything folded — resume stays valid.
    lane = LaneSpec("claude", "Claude", "echo", lambda *a: [], native_session=MINT)
    seen = []

    async def fake_run_lane(ln, args, *, tool="ask", terse=True):
        seen.append(args.get("_native_argv"))
        return RunResult(True, "answer", "ok")
    monkeypatch.setattr(server, "_run_lane", fake_run_lane)

    _res, cid = _convo(lane, {"task": "t1", "conversation": "new"})
    _convo(lane, {"task": "t2", "conversation": cid})                   # last_seen=4
    assert telemetry.convo_compact(cid, 2, "FOLDED 1-2", "claude")      # fold ≤ last_seen
    _convo(lane, {"task": "t3", "conversation": cid})
    assert seen[2][0] == "--resume"                # handle kept


def test_prune_cascades_native_sessions(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_CONVO_MAX_STORED", "1")
    telemetry.convo_append("old-thread", "claude", "user", "x")
    telemetry.convo_session_set("old-thread", "claude", "uuid-old", 1)
    telemetry.convo_append("new-thread", "claude", "user", "y")        # prunes old-thread
    assert telemetry.convo_session("old-thread", "claude") == ("", 0)  # cascaded


def test_capture_pattern_no_match_stores_nothing(monkeypatch):
    lane = LaneSpec("opencode", "Opencode", "echo", lambda *a: [], native_session=CAPTURE)

    async def fake_run_lane(ln, args, *, tool="ask", terse=True):
        return RunResult(True, "answer", "ok", err="no session marker in these logs")
    monkeypatch.setattr(server, "_run_lane", fake_run_lane)

    _res, cid = _convo(lane, {"task": "t1", "conversation": "new"})
    assert telemetry.convo_session(cid, "opencode") == ("", 0)   # nothing captured
    # next turn retries capture (spawn flags again), never a bogus resume
    seen = []

    async def fake2(ln, args, *, tool="ask", terse=True):
        seen.append(args.get("_native_argv"))
        return RunResult(True, "a", "ok", err="still nothing")
    monkeypatch.setattr(server, "_run_lane", fake2)
    _convo(lane, {"task": "t2", "conversation": cid})
    assert seen[0] == ["--print-logs"]


def test_native_turn_never_served_from_cache(monkeypatch):
    # Same prompt twice on a native-session thread must spawn twice — inside a session the
    # same text means something different (the vendor holds prior context the key can't see).
    monkeypatch.setenv("CLI_BRIDGE_CACHE_TTL_S", "3600")
    import importlib

    from cli_bridge import config as cfg
    importlib.reload(cfg)
    try:
        lane = LaneSpec("claude", "Claude", "echo", lambda *a: [], native_session=MINT)
        spawns = []

        async def fake_run_lane(ln, args, *, tool="ask", terse=True):
            spawns.append(args["task"])
            return RunResult(True, "answer", "ok")
        monkeypatch.setattr(server, "_run_lane", fake_run_lane)
        _res, cid = _convo(lane, {"task": "same text", "conversation": "new"})
        _convo(lane, {"task": "same text", "conversation": cid})
        assert len(spawns) == 2                      # no cache hit on the second turn
    finally:
        monkeypatch.delenv("CLI_BRIDGE_CACHE_TTL_S")
        importlib.reload(cfg)


def test_custom_lane_json_native_session(tmp_path):
    import json as _json

    from cli_bridge import lanes as lanes_mod
    path = tmp_path / "lanes.json"
    path.write_text(_json.dumps([{
        "key": "mycli", "bin": "echo", "ask": ["run", "{task}"],
        "native_session": {"mode": "capture", "spawn": ["--vs"],
                           "pattern": "sess-[0-9]+", "resume": ["--resume", "{sid}"]},
    }, {
        "key": "badns", "bin": "echo", "ask": ["{task}"],
        "native_session": {"mode": "weird"},
    }]))
    loaded = lanes_mod.load_custom_lanes(str(path))
    by_key = {ln.key: ln for ln in loaded}
    assert by_key["mycli"].native_session == {
        "mode": "capture", "first": [], "spawn": ["--vs"],
        "pattern": "sess-[0-9]+", "resume": ["--resume", "{sid}"]}
    assert by_key["badns"].native_session is None    # malformed block dropped, lane kept


# ── the high-water mark must never claim more than the prompt delivered ───────────────────

def test_turn_landing_during_the_spawn_invalidates_the_handle(monkeypatch):
    # The commit reads MAX(turn_number) AFTER the spawn. If another lane appended a turn while
    # this one was awaiting, that turn gets marked "already seen" by a session that never got
    # it — and later deltas filter on turn_number > last_turn, so it is lost to this lane
    # forever. Correctness beats the optimisation: drop the handle and full-replay instead.
    lane = LaneSpec("claude", "Claude", "echo", lambda *a: [], native_session=MINT)
    box, prompts = {}, []

    async def fake_run_lane(ln, args, *, tool="ask", terse=True):
        prompts.append(args["task"])
        if box.get("cid"):                  # another lane answers mid-spawn
            telemetry.convo_append(box["cid"], "ollama", "user", "MIDQ")
            telemetry.convo_append(box["cid"], "ollama", "assistant", "MIDA")
            box.pop("cid")
        return RunResult(True, "answer", "ok")
    monkeypatch.setattr(server, "_run_lane", fake_run_lane)

    _res, cid = _convo(lane, {"task": "t1", "conversation": "new"})
    box["cid"] = cid
    _convo(lane, {"task": "t2", "conversation": cid})
    _convo(lane, {"task": "t3", "conversation": cid})
    assert "MIDQ" in prompts[-1]            # the interleaved turn still reaches this lane


def test_trimmed_delta_invalidates_the_handle(monkeypatch):
    # Same lie by a different route: the delta was cut to fit the char budget, so the session
    # never received the turns that were cut. Needs a delta of several turns, so another lane
    # piles them up between two turns of the native one.
    monkeypatch.setenv("CLI_BRIDGE_CONVO_MAX_CHARS", "200")
    lane = LaneSpec("claude", "Claude", "echo", lambda *a: [], native_session=MINT)

    async def fake_run_lane(ln, args, *, tool="ask", terse=True):
        return RunResult(True, "answer", "ok")
    monkeypatch.setattr(server, "_run_lane", fake_run_lane)

    _res, cid = _convo(lane, {"task": "t1", "conversation": "new"})
    assert telemetry.convo_session(cid, "claude")[0]          # handle minted on turn 1
    for i in range(6):                                        # other lane floods the thread
        telemetry.convo_append(cid, "ollama", "user", f"Q{i} " + "x" * 120)
        telemetry.convo_append(cid, "ollama", "assistant", f"A{i} " + "y" * 120)
    _convo(lane, {"task": "t2", "conversation": cid})          # delta too big → trimmed
    assert telemetry.convo_session(cid, "claude") == ("", 0)   # handle dropped, not advanced


def test_mock_stores_no_native_handle(monkeypatch):
    # Nothing is spawned under mock, so a stored handle names a session that never existed.
    monkeypatch.setenv("CLI_BRIDGE_MOCK", "1")
    lane = LaneSpec("claude", "Claude", "echo", lambda *a: [], native_session=MINT)
    _res, cid = _convo(lane, {"task": "t1", "conversation": "new"})
    assert telemetry.convo_session(cid, "claude") == ("", 0)


def test_native_extra_never_splits_a_flag_from_its_value(monkeypatch):
    # Custom lanes CAN declare a native_session, and their template may end in a flag's value.
    lane = LaneSpec("mycli", "My", "echo",
                    lambda task, m, e, a, b="": ["-p", task, "--output-format", "json"])
    seen = []

    async def cap(argv, timeout, cwd=None, env=None, **kw):
        seen.append(list(argv))
        return RunResult(True, "ok", "ok")
    monkeypatch.setattr(server.runner, "arun", cap)

    asyncio.run(server._run_lane(lane, {"task": "T", "_native_argv": ["--session-id", "S"]}))
    assert seen[0][-2:] == ["--output-format", "json"]      # flag and value stay together
    assert "--session-id" in seen[0]
