"""Anti-burst spawn pacing (runner.pace): opt-in per-lane spacing so a same-lane burst can't
rate-limit a free tier into returning empty (the June-2026 eval failure mode)."""
import asyncio
import time

import pytest

from cli_bridge import runner, server, telemetry
from cli_bridge.lanes import LaneSpec
from cli_bridge.runner import RunResult


@pytest.fixture(autouse=True)
def _fresh_pacer(tmp_path, monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_STATE_DB", str(tmp_path / "s.sqlite"))
    telemetry._reset_for_tests()
    runner._PACE_LAST.clear()
    runner._PACE_LOCKS.clear()
    yield
    runner._PACE_LAST.clear()
    runner._PACE_LOCKS.clear()
    telemetry._reset_for_tests()


def test_pace_noop_at_zero():
    t0 = time.monotonic()
    assert asyncio.run(runner.pace("x", 0)) == 0.0
    assert asyncio.run(runner.pace("x", -1)) == 0.0
    assert time.monotonic() - t0 < 0.05            # immediate


def test_pace_spaces_same_key():
    async def burst():
        w1 = await runner.pace("lane", 0.05)
        w2 = await runner.pace("lane", 0.05)
        return w1, w2
    t0 = time.monotonic()
    w1, w2 = asyncio.run(burst())
    assert w1 == 0.0                                # first spawn never waits
    assert w2 > 0.0                                 # second is spaced
    assert time.monotonic() - t0 >= 0.04


def test_pace_other_keys_unaffected():
    async def burst():
        await runner.pace("a", 0.5)
        return await runner.pace("b", 0.5)          # different lane: no wait
    t0 = time.monotonic()
    assert asyncio.run(burst()) == 0.0
    assert time.monotonic() - t0 < 0.2


def test_lane_min_interval_property(monkeypatch):
    lane = LaneSpec("gemini", "Gemini", "echo", lambda *a: [])
    assert lane.min_interval_s == 0.0               # default off
    monkeypatch.setenv("CLI_BRIDGE_GEMINI_MIN_INTERVAL_S", "2.5")
    assert lane.min_interval_s == 2.5
    monkeypatch.setenv("CLI_BRIDGE_GEMINI_MIN_INTERVAL_S", "junk")
    assert lane.min_interval_s == 0.0               # invalid -> off, never crashes
    monkeypatch.setenv("CLI_BRIDGE_GEMINI_MIN_INTERVAL_S", "-3")
    assert lane.min_interval_s == 0.0


def test_run_lane_paces_before_spawn(monkeypatch):
    paced = []

    async def fake_pace(key, interval):
        paced.append((key, interval))
        return 0.0

    async def fake_spawn(argv, timeout, cwd, env=None):
        return RunResult(True, "ok", "ok")

    monkeypatch.setattr(runner, "pace", fake_pace)
    monkeypatch.setattr(server, "_spawn_with_retry", fake_spawn)
    monkeypatch.setenv("CLI_BRIDGE_GEMINI_MIN_INTERVAL_S", "2")
    lane = LaneSpec("gemini", "Gemini", "echo", lambda *a: [])
    res = asyncio.run(server._run_lane(lane, {"task": "hi"}))
    assert res.ok
    assert paced == [("gemini", 2.0)]


def test_stats_hint_on_burst_ratelimited_lane(monkeypatch):
    row = {"lane": "gemini", "total_runs": 100, "total_failures": 80,
           "consecutive_failures": 0, "last_kind": "empty", "cooldown_remaining_s": 0}
    monkeypatch.setattr(telemetry, "lane_stats", lambda: [row])
    out = server._render_lane_stats()
    assert "CLI_BRIDGE_GEMINI_MIN_INTERVAL_S" in out      # hint shown
    monkeypatch.setenv("CLI_BRIDGE_GEMINI_MIN_INTERVAL_S", "2")
    out2 = server._render_lane_stats()
    assert "CLI_BRIDGE_GEMINI_MIN_INTERVAL_S=2`" not in out2   # pacing set -> no nagging
