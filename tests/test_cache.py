"""Opt-in response cache: roundtrip + TTL, off by default, _run_lane serves a hit without
re-spawning, and a build (write) run is never cached."""
import asyncio

import pytest

from cli_bridge import config, lanes, runner, server, telemetry


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_STATE_DB", str(tmp_path / "state.sqlite"))
    monkeypatch.setenv("CLI_BRIDGE_TELEMETRY", "on")
    telemetry._reset_for_tests()
    yield
    telemetry._reset_for_tests()


def test_cache_roundtrip_and_ttl():
    assert telemetry.cache_get("k1", 60) is None              # miss
    telemetry.cache_put("k1", True, "hello", "ok")
    assert telemetry.cache_get("k1", 60) == (True, "hello", "ok")
    assert telemetry.cache_get("k1", 0) is None               # ttl 0 = disabled
    # stale: ask for a fresh entry younger than -1s -> always stale
    assert telemetry.cache_get("k1", -5) is None


def _fake_lane():
    return lanes.LaneSpec("fk", "Fake", "echo", lambda task, m, e, a, b="": [task])


def _count_runner(monkeypatch):
    calls = {"n": 0}

    async def fake_arun(argv, timeout, cwd=None, env=None):
        calls["n"] += 1
        return runner.RunResult(True, f"answer #{calls['n']}", "ok")
    monkeypatch.setattr(server.runner, "arun", fake_arun)
    return calls


def test_cache_off_by_default(monkeypatch):
    monkeypatch.setattr(config, "CACHE_TTL_S", 0)
    calls = _count_runner(monkeypatch)
    lane, args = _fake_lane(), {"task": "hi"}
    asyncio.run(server._run_lane(lane, args))
    asyncio.run(server._run_lane(lane, args))
    assert calls["n"] == 2                                     # no caching -> two spawns


def test_cache_hit_skips_spawn(monkeypatch):
    monkeypatch.setattr(config, "CACHE_TTL_S", 300)
    calls = _count_runner(monkeypatch)
    lane, args = _fake_lane(), {"task": "hi"}
    r1 = asyncio.run(server._run_lane(lane, args))
    r2 = asyncio.run(server._run_lane(lane, args))
    assert calls["n"] == 1                                     # second served from cache
    assert r2.output == r1.output and r2.latency_ms == 0


def test_cache_key_separates_model_and_task(monkeypatch):
    monkeypatch.setattr(config, "CACHE_TTL_S", 300)
    calls = _count_runner(monkeypatch)
    lane = _fake_lane()
    asyncio.run(server._run_lane(lane, {"task": "hi"}))
    asyncio.run(server._run_lane(lane, {"task": "different"}))    # different task -> miss
    asyncio.run(server._run_lane(lane, {"task": "hi"}))           # repeat -> hit
    assert calls["n"] == 2


def test_build_run_not_cached(monkeypatch):
    monkeypatch.setattr(config, "CACHE_TTL_S", 300)
    calls = _count_runner(monkeypatch)
    lane = lanes.LaneSpec("fk", "Fake", "echo",
                          lambda task, m, e, a, b="": [task], caps=frozenset({"agent"}))
    args = {"task": "edit it", "agent": "build"}
    asyncio.run(server._run_lane(lane, args))
    asyncio.run(server._run_lane(lane, args))
    assert calls["n"] == 2                                     # writes never served stale
