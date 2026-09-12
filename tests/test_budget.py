"""The pre-spawn spend guards in server._run_lane (run limit + credit cap) — docs/BUDGET.md."""

import asyncio
import os

import pytest

from cli_bridge import server, telemetry
from cli_bridge.lanes import LaneSpec
from cli_bridge.runner import RunResult


def _lane(key="fakelane", cost="free"):
    return LaneSpec(key, key.title(), "echo", lambda *a: [], cost_default=cost)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in list(os.environ):
        if k.startswith("CLI_BRIDGE_FAKELANE_") or k in {
                "CLI_BRIDGE_DAILY_CREDIT_CAP", "CLI_BRIDGE_MOCK", "CLI_BRIDGE_DEPTH"}:
            monkeypatch.delenv(k, raising=False)


def _run(monkeypatch, lane):
    """Drive _run_lane with a counting fake spawn; returns (result, spawns)."""
    spawned = {"n": 0}

    async def fake_arun(argv, timeout, cwd=None, env=None):
        spawned["n"] += 1
        return RunResult(True, "x", "ok")
    monkeypatch.setattr(server.runner, "arun", fake_arun)
    return asyncio.run(server._run_lane(lane, {"task": "hi"})), spawned["n"]


def test_no_limits_allows(monkeypatch):
    monkeypatch.setattr(telemetry, "lane_runs_today", lambda lane: 999)
    r, n = _run(monkeypatch, _lane())
    assert r.ok and n == 1


def test_daily_limit_blocks_at_limit(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_FAKELANE_DAILY_LIMIT", "5")
    monkeypatch.setattr(telemetry, "lane_runs_today", lambda lane: 5)
    r, n = _run(monkeypatch, _lane())
    assert r.kind == "blocked" and n == 0
    assert "daily run limit" in r.output and "5/5" in r.output


def test_daily_limit_allows_below_limit(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_FAKELANE_DAILY_LIMIT", "5")
    monkeypatch.setattr(telemetry, "lane_runs_today", lambda lane: 4)
    r, _ = _run(monkeypatch, _lane())
    assert r.ok


def test_credit_cap_gates_rated_limited_lane(monkeypatch):
    # A limited lane the user rated with CREDITS_PER_1K spends credits -> the cap sees it.
    monkeypatch.setenv("CLI_BRIDGE_DAILY_CREDIT_CAP", "2")
    monkeypatch.setenv("CLI_BRIDGE_FAKELANE_CREDITS_PER_1K", "0.1")
    monkeypatch.setattr(telemetry, "est_credits_today", lambda: 3.0)
    r, n = _run(monkeypatch, _lane(cost="limited"))
    assert r.kind == "blocked" and "credit cap" in r.output and n == 0


def test_credit_cap_ignores_unrated_free_lane(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_DAILY_CREDIT_CAP", "2")
    monkeypatch.setattr(telemetry, "est_credits_today", lambda: 99.0)
    r, _ = _run(monkeypatch, _lane(cost="free"))
    assert r.ok


def test_lane_runs_today_counts_only_today_and_lane(tmp_path, monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_STATE_DB", str(tmp_path / "state.sqlite"))
    monkeypatch.setenv("CLI_BRIDGE_TELEMETRY", "on")
    telemetry._reset_for_tests()
    try:
        for lane in ("fakelane", "otherlane"):
            rec = telemetry.start("ask", lane, "m1", "t")
            telemetry.record(rec, True, "ok", output_chars=4, input_chars=4)
        assert telemetry.lane_runs_today("fakelane") == 1
        assert telemetry.lane_runs_today("nope") == 0
    finally:
        telemetry._reset_for_tests()
