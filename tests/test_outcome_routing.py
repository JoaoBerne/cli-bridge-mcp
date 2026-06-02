"""Outcome-tracked routing: host feedback (rate_lane) personalizes ask_best ON THIS MACHINE.

No network, no real CLI. Exercises three layers: the telemetry rating store, the router's
quality bucket, and end-to-end through call_tool (rate a lane, then ask_best picks it).
"""
import asyncio

import pytest

from cli_bridge import router, server, telemetry
from cli_bridge.lanes import LaneSpec
from cli_bridge.runner import RunResult


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_STATE_DB", str(tmp_path / "s.sqlite"))
    telemetry._reset_for_tests()
    yield
    telemetry._reset_for_tests()


# ── telemetry: ratings store + per-mode aggregation ──────────────────────────────────────

def test_rate_lane_records_and_averages():
    telemetry.rate_lane("gemini", "deep", 4)
    res = telemetry.rate_lane("gemini", "deep", 5)
    assert res == {"n": 2, "avg": 4.5}


def test_lane_quality_isolates_by_mode():
    telemetry.rate_lane("gpt", "code", 5)
    telemetry.rate_lane("gpt", "code", 5)
    telemetry.rate_lane("gpt", "review", 1)
    by_code = telemetry.lane_quality("code")
    by_review = telemetry.lane_quality("review")
    pooled = telemetry.lane_quality()           # empty mode pools every rating
    assert by_code["gpt"] == {"n": 2, "avg": 5.0}
    assert by_review["gpt"] == {"n": 1, "avg": 1.0}
    assert pooled["gpt"]["n"] == 3


def test_rate_lane_noop_when_telemetry_off(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_TELEMETRY", "off")
    telemetry._reset_for_tests()
    assert telemetry.rate_lane("gemini", "deep", 5) == {}


# ── router: quality steers, but only with enough data ────────────────────────────────────

def _two_free_lanes():
    # Same cost, same caps -> without ratings they tie and fall back to key order (alpha first).
    a = LaneSpec("alpha", "Alpha", "echo", lambda *x: [], cost_default="free",
                 caps=frozenset({"model", "effort"}))
    b = LaneSpec("bravo", "Bravo", "echo", lambda *x: [], cost_default="free",
                 caps=frozenset({"model", "effort"}))
    return a, b


def _order(lanes, mode):
    q = telemetry.lane_quality(mode)
    return [ln.key for ln in router.order_for_mode(
        lanes, lambda _k: 0, lambda _k: {}, mode, include_paid=False,
        quality_of=lambda k: q.get(k, {}))]


def test_no_ratings_keeps_baseline_order():
    a, b = _two_free_lanes()
    assert _order([a, b], "deep") == ["alpha", "bravo"]   # tie -> alphabetical


def test_proven_good_lane_jumps_to_front():
    a, b = _two_free_lanes()
    telemetry.rate_lane("bravo", "deep", 5)
    telemetry.rate_lane("bravo", "deep", 5)               # >= MIN_RATINGS, avg 5 -> strong
    assert _order([a, b], "deep") == ["bravo", "alpha"]   # outcome overrides alphabetical


def test_single_rating_below_threshold_does_not_steer():
    a, b = _two_free_lanes()
    telemetry.rate_lane("bravo", "deep", 5)               # only 1 rating < MIN_RATINGS -> neutral
    assert _order([a, b], "deep") == ["alpha", "bravo"]   # unchanged


def test_proven_bad_lane_sinks_below_untried():
    a, b = _two_free_lanes()
    telemetry.rate_lane("alpha", "deep", 1)
    telemetry.rate_lane("alpha", "deep", 1)               # avg 1 -> poor, sinks below untried bravo
    assert _order([a, b], "deep") == ["bravo", "alpha"]


def test_ratings_for_other_mode_do_not_leak():
    a, b = _two_free_lanes()
    telemetry.rate_lane("bravo", "code", 5)
    telemetry.rate_lane("bravo", "code", 5)               # only 'code' is rated
    assert _order([a, b], "deep") == ["alpha", "bravo"]   # 'deep' order untouched


# ── server dispatch: validation + end-to-end personalization ─────────────────────────────

def _install(monkeypatch, lanes):
    monkeypatch.setattr(server, "_active_lanes", lambda: (list(lanes), ""))


def test_rate_lane_dispatch_records(monkeypatch):
    a, b = _two_free_lanes()
    _install(monkeypatch, [a, b])
    out = asyncio.run(server.call_tool("rate_lane", {"lane": "bravo", "mode": "deep", "score": 5}))
    assert "Recorded 5/5 for bravo" in out[0].text
    assert telemetry.lane_quality("deep")["bravo"] == {"n": 1, "avg": 5.0}


def test_rate_lane_rejects_bad_input(monkeypatch):
    a, b = _two_free_lanes()
    _install(monkeypatch, [a, b])
    bad_score = asyncio.run(server.call_tool("rate_lane", {"lane": "alpha", "score": 9}))
    unknown = asyncio.run(server.call_tool("rate_lane", {"lane": "nope", "score": 5}))
    bad_mode = asyncio.run(server.call_tool("rate_lane", {"lane": "alpha", "score": 5, "mode": "x"}))
    assert "between 1 and 5" in bad_score[0].text
    assert "unknown lane" in unknown[0].text
    assert "unknown mode" in bad_mode[0].text


def test_ask_best_prefers_the_rated_lane(monkeypatch):
    a, b = _two_free_lanes()
    _install(monkeypatch, [a, b])

    tried_first: list[str] = []

    async def fake_run_lane(lane, args, *, tool="ask", terse=True):
        tried_first.append(lane.key)
        return RunResult(True, f"{lane.key}-answer", "ok", latency_ms=1)
    monkeypatch.setattr(server, "_run_lane", fake_run_lane)

    # Baseline: tie -> alphabetical -> alpha answers first.
    base = asyncio.run(server.call_tool("ask_best", {"task": "q", "mode": "deep"}))
    assert tried_first[0] == "alpha" and "alpha-answer" in base[0].text

    # Teach the router bravo is great at 'deep', then ask again: bravo now leads.
    asyncio.run(server.call_tool("rate_lane", {"lane": "bravo", "mode": "deep", "score": 5}))
    asyncio.run(server.call_tool("rate_lane", {"lane": "bravo", "mode": "deep", "score": 5}))
    tried_first.clear()
    after = asyncio.run(server.call_tool("ask_best", {"task": "q", "mode": "deep"}))
    assert tried_first[0] == "bravo" and "bravo-answer" in after[0].text
    assert 'rate_lane(lane="bravo"' in after[0].text       # feedback loop is discoverable
