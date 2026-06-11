"""budget.check_spawn — the single pre-spawn spend guard (run limit + credit cap)."""

import os

import pytest

from cli_bridge import budget, telemetry
from cli_bridge.lanes import LaneSpec


def _lane(key="fakelane", cost="free"):
    return LaneSpec(key, key.title(), "echo", lambda *a: [], cost_default=cost)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in list(os.environ):
        if k.startswith("CLI_BRIDGE_FAKELANE_") or k == "CLI_BRIDGE_DAILY_CREDIT_CAP":
            monkeypatch.delenv(k, raising=False)


def test_no_limits_allows(monkeypatch):
    monkeypatch.setattr(telemetry, "lane_runs_today", lambda lane: 999)
    assert budget.check_spawn(_lane()) is None


def test_daily_limit_blocks_at_limit(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_FAKELANE_DAILY_LIMIT", "5")
    monkeypatch.setattr(telemetry, "lane_runs_today", lambda lane: 5)
    reason = budget.check_spawn(_lane())
    assert reason is not None
    assert "daily run limit" in reason and "5/5" in reason


def test_daily_limit_allows_below_limit(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_FAKELANE_DAILY_LIMIT", "5")
    monkeypatch.setattr(telemetry, "lane_runs_today", lambda lane: 4)
    assert budget.check_spawn(_lane()) is None


def test_daily_limit_applies_to_free_lanes(monkeypatch):
    # The run limit is the universal cap — free quota'd lanes are gated too.
    monkeypatch.setenv("CLI_BRIDGE_FAKELANE_DAILY_LIMIT", "0")
    monkeypatch.setattr(telemetry, "lane_runs_today", lambda lane: 0)
    assert budget.check_spawn(_lane(cost="free")) is not None


def test_credit_cap_blocks_paid_lane(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_DAILY_CREDIT_CAP", "2")
    monkeypatch.setattr(telemetry, "est_credits_today", lambda: 2.5)
    reason = budget.check_spawn(_lane(cost="paid"))
    assert reason is not None and "credit cap" in reason


def test_credit_cap_allows_paid_lane_under_cap(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_DAILY_CREDIT_CAP", "2")
    monkeypatch.setattr(telemetry, "est_credits_today", lambda: 1.0)
    assert budget.check_spawn(_lane(cost="paid")) is None


def test_credit_cap_gates_rated_limited_lane(monkeypatch):
    # A limited lane the user rated with CREDITS_PER_1K spends credits -> the cap sees it.
    monkeypatch.setenv("CLI_BRIDGE_DAILY_CREDIT_CAP", "2")
    monkeypatch.setenv("CLI_BRIDGE_FAKELANE_CREDITS_PER_1K", "0.1")
    monkeypatch.setattr(telemetry, "est_credits_today", lambda: 3.0)
    assert budget.check_spawn(_lane(cost="limited")) is not None


def test_credit_cap_ignores_unrated_free_lane(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_DAILY_CREDIT_CAP", "2")
    monkeypatch.setattr(telemetry, "est_credits_today", lambda: 99.0)
    assert budget.check_spawn(_lane(cost="free")) is None


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
