"""Mock/dry-run, transient retry, and the trace bundle."""
import asyncio
import json

from cli_bridge import detect, server
from cli_bridge.lanes import LaneSpec
from cli_bridge.runner import RunResult


def _lane():
    return LaneSpec("x", "X", "echo", lambda *a: [])


async def _fast_sleep(_s):
    return None


# ── mock / dry-run ────────────────────────────────────────────────────────────────────────

def test_mock_returns_canned_without_spawning(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_MOCK", "1")
    spawned = {"n": 0}

    async def boom(*a, **k):
        spawned["n"] += 1
        return RunResult(True, "REAL", "ok")
    monkeypatch.setattr(server.runner, "arun", boom)

    r = asyncio.run(server._run_lane(_lane(), {"task": "hello"}))
    assert r.ok and "[mock:x]" in r.output and "hello" in r.output
    assert spawned["n"] == 0          # no CLI was spawned


def test_mock_reports_every_lane_installed(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_MOCK", "1")
    assert detect.is_installed(LaneSpec("zzz", "Z", "zzz-no-such-bin", lambda *a: []))


# ── transient retry ───────────────────────────────────────────────────────────────────────

def test_retry_succeeds_after_transient(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_RETRIES", "2")
    monkeypatch.setattr(server.asyncio, "sleep", _fast_sleep)
    calls = {"n": 0}

    async def flaky(argv, timeout, cwd=None, env=None):
        calls["n"] += 1
        return RunResult(False, "blip", "failed") if calls["n"] < 3 else RunResult(True, "ok", "ok")
    monkeypatch.setattr(server.runner, "arun", flaky)

    r = asyncio.run(server._spawn_with_retry(["x"], 10, None))
    assert r.ok and calls["n"] == 3   # 1 + 2 retries


def test_retry_not_used_for_quota(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_RETRIES", "3")
    monkeypatch.setattr(server.asyncio, "sleep", _fast_sleep)
    calls = {"n": 0}

    async def quota(argv, timeout, cwd=None, env=None):
        calls["n"] += 1
        return RunResult(False, "rate limited", "quota")
    monkeypatch.setattr(server.runner, "arun", quota)

    r = asyncio.run(server._spawn_with_retry(["x"], 10, None))
    assert not r.ok and calls["n"] == 1   # quota is sticky — not retried


def test_retries_zero_means_single_attempt(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_RETRIES", "0")
    calls = {"n": 0}

    async def fail(argv, timeout, cwd=None, env=None):
        calls["n"] += 1
        return RunResult(False, "boom", "failed")
    monkeypatch.setattr(server.runner, "arun", fail)

    asyncio.run(server._spawn_with_retry(["x"], 10, None))
    assert calls["n"] == 1


# ── trace bundle ──────────────────────────────────────────────────────────────────────────

def test_trace_writes_redacted_json(monkeypatch, tmp_path):
    monkeypatch.setenv("CLI_BRIDGE_TRACE_DIR", str(tmp_path))
    res = RunResult(True, "here is sk-abcdef123456 leaked", "ok", latency_ms=7)
    server._write_trace(_lane(), "m1", ["echo", "Authorization: Bearer TOKabcdef123456"],
                        None, 10, res)
    files = list(tmp_path.glob("x-*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text())
    assert data["lane"] == "x" and data["ok"] is True and data["kind"] == "ok"
    blob = json.dumps(data)
    assert "TOKabcdef123456" not in blob          # secret in argv redacted
    assert "sk-abcdef123456" not in data["output"]  # secret in output redacted


def test_trace_off_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("CLI_BRIDGE_TRACE_DIR", raising=False)
    server._write_trace(_lane(), "m", ["echo", "hi"], None, 10, RunResult(True, "x", "ok"))
    assert not list(tmp_path.glob("*.json"))      # nothing written when off


# ── ask_all concurrency cap ─────────────────────────────────────────────────────────────────

def test_ask_all_respects_max_parallel(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_MAX_PARALLEL", "2")
    monkeypatch.setattr(server.telemetry, "cooldown_remaining", lambda key: 0)
    lanes = [LaneSpec(f"l{i}", f"L{i}", "echo", lambda *a: []) for i in range(6)]
    state = {"now": 0, "max": 0}

    async def fake_run_lane(lane, args, *, tool="ask", terse=True):
        state["now"] += 1
        state["max"] = max(state["max"], state["now"])
        await asyncio.sleep(0.02)         # hold the slot so overlap is observable
        state["now"] -= 1
        return RunResult(True, "ok", "ok", latency_ms=1)
    monkeypatch.setattr(server, "_run_lane", fake_run_lane)

    asyncio.run(server._ask_all_body(lanes, {"task": "hi"}))
    assert state["max"] <= 2              # never more than the cap ran at once


# ── cost-safety + team controls (cluster 1) ─────────────────────────────────────────────────

def _paid_lane():
    return LaneSpec("p", "Paid", "echo", lambda *a: [], paid=True)


def test_daily_credit_cap_blocks_paid(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_DAILY_CREDIT_CAP", "1.0")
    monkeypatch.setattr(server.telemetry, "est_credits_today", lambda: 1.5)  # already over
    spawned = {"n": 0}

    async def boom(*a, **k):
        spawned["n"] += 1
        return RunResult(True, "x", "ok")
    monkeypatch.setattr(server.runner, "arun", boom)

    r = asyncio.run(server._run_lane(_paid_lane(), {"task": "hi"}))
    assert not r.ok and r.kind == "blocked" and spawned["n"] == 0


def test_daily_credit_cap_allows_free(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_DAILY_CREDIT_CAP", "1.0")
    monkeypatch.setattr(server.telemetry, "est_credits_today", lambda: 99.0)

    async def ok(*a, **k):
        return RunResult(True, "free answer", "ok")
    monkeypatch.setattr(server.runner, "arun", ok)
    r = asyncio.run(server._run_lane(_lane(), {"task": "hi"}))   # _lane() is free
    assert r.ok                                                   # cap only gates paid lanes


def test_build_disabled_forces_plan(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_DISABLE_BUILD", "1")
    captured = {}

    async def cap(argv, timeout, cwd=None, env=None):
        captured["argv"] = argv
        return RunResult(True, "ok", "ok")
    monkeypatch.setattr(server.runner, "arun", cap)
    lane = LaneSpec("x", "X", "echo", lambda task, m, e, agent, b="": [f"agent={agent}"],
                    caps=("agent",))
    asyncio.run(server._run_lane(lane, {"task": "hi", "agent": "build"}))
    assert "agent=plan" in captured["argv"]      # build downgraded to plan


def test_allowlist_filters_lanes(monkeypatch):
    a = LaneSpec("a", "A", "echo", lambda *x: [])
    b = LaneSpec("b", "B", "echo", lambda *x: [])
    monkeypatch.setattr(server, "installed_lanes", lambda lst: [a, b])
    monkeypatch.setenv("CLI_BRIDGE_HOST", "claude-code")
    monkeypatch.setenv("CLI_BRIDGE_ALLOW_LANES", "b")
    lanes, _ = server._active_lanes()
    assert [ln.key for ln in lanes] == ["b"]     # only allowlisted lane exposed


# ── ask_all output_format / summary_only / dry_run (cluster 2) ───────────────────────────────

def _two_lanes():
    return [LaneSpec("a", "LaneA", "echo", lambda *x: []),
            LaneSpec("b", "LaneB", "echo", lambda *x: [])]


def _ok_run_lane(monkeypatch):
    monkeypatch.setattr(server.telemetry, "cooldown_remaining", lambda key: 0)

    async def rl(lane, args, *, tool="ask", terse=True):
        return RunResult(True, f"answer from {lane.key}", "ok", latency_ms=5)
    monkeypatch.setattr(server, "_run_lane", rl)


def test_ask_all_json_output(monkeypatch):
    _ok_run_lane(monkeypatch)
    out = asyncio.run(server._ask_all_body(_two_lanes(), {"task": "hi", "output_format": "json"}))
    data = json.loads(out)
    assert data["tool"] == "ask_all" and len(data["lanes"]) == 2
    assert data["lanes"][0]["ok"] is True and "answer from a" in data["lanes"][0]["output"]


def test_ask_all_summary_only_omits_blocks(monkeypatch):
    _ok_run_lane(monkeypatch)
    out = asyncio.run(server._ask_all_body(_two_lanes(), {"task": "hi", "summary_only": True}))
    assert "## Council" in out                    # recap kept
    assert "## LaneA - OK" not in out             # full per-lane block dropped


def test_ask_all_dry_run_spawns_nothing(monkeypatch):
    monkeypatch.setattr(server.telemetry, "cooldown_remaining", lambda key: 0)
    spawned = {"n": 0}

    async def rl(lane, args, *, tool="ask", terse=True):
        spawned["n"] += 1
        return RunResult(True, "x", "ok")
    monkeypatch.setattr(server, "_run_lane", rl)
    out = asyncio.run(server._ask_all_body(_two_lanes(), {"task": "hello", "dry_run": True}))
    assert "dry run" in out and spawned["n"] == 0
    # json dry run too
    j = json.loads(asyncio.run(server._ask_all_body(
        _two_lanes(), {"task": "hello", "dry_run": True, "output_format": "json"})))
    assert j["dry_run"] is True and j["est_input_tokens_total"] >= 1

