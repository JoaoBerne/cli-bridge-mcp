"""Phase 1: telemetry records runs, cools lanes on repeated failure, exposes stats."""
import time

import pytest

from cli_bridge import telemetry, config


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_STATE_DB", str(tmp_path / "state.sqlite"))
    monkeypatch.setenv("CLI_BRIDGE_TELEMETRY", "on")
    telemetry._reset_for_tests()
    yield
    telemetry._reset_for_tests()


def _run(lane, ok, kind, task="t"):
    rec = telemetry.start("ask", lane, "m1", task)
    telemetry.record(rec, ok, kind, output_chars=10)


def test_records_runs_and_usage():
    _run("gemini", True, "ok")
    _run("gemini", True, "ok")
    rep = telemetry.usage_report()
    assert rep["enabled"] and rep["total_runs"] == 2
    by = {r["lane"]: r for r in rep["by_lane"]}
    assert by["gemini"]["runs"] == 2 and by["gemini"]["ok"] == 2


def test_quota_failure_cools_lane_immediately():
    _run("gpt", False, "quota")
    assert telemetry.cooldown_remaining("gpt") > 0


def test_auth_failure_cools_lane():
    _run("claude", False, "auth")
    assert telemetry.cooldown_remaining("claude") > 0


def test_two_timeouts_cool_lane_but_one_does_not():
    _run("mistral", False, "timeout")
    assert telemetry.cooldown_remaining("mistral") == 0      # one timeout: not yet
    _run("mistral", False, "timeout")
    assert telemetry.cooldown_remaining("mistral") > 0       # second consecutive: cooled


def test_success_resets_counters():
    _run("opencode", False, "timeout")
    _run("opencode", True, "ok")
    _run("opencode", False, "timeout")
    assert telemetry.cooldown_remaining("opencode") == 0     # streak was reset by the ok


def test_reset_lane_clears_cooldown():
    _run("gpt", False, "quota")
    assert telemetry.cooldown_remaining("gpt") > 0
    assert telemetry.reset_lane("gpt") is True
    assert telemetry.cooldown_remaining("gpt") == 0


def test_lane_stats_shape():
    _run("gemini", True, "ok")
    _run("gemini", False, "failed")
    stats = {s["lane"]: s for s in telemetry.lane_stats()}
    assert stats["gemini"]["total_runs"] == 2
    assert stats["gemini"]["total_failures"] == 1


def test_disabled_telemetry_is_silent(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_TELEMETRY", "off")
    telemetry._reset_for_tests()
    _run("gemini", True, "ok")
    assert telemetry.usage_report() == {"enabled": False}
    assert telemetry.cooldown_remaining("gemini") == 0


def test_transcripts_not_stored_by_default():
    _run("gemini", True, "ok", task="super secret prompt content " * 10)
    rep = telemetry.usage_report()
    # preview is capped at 60 chars when not storing transcripts
    assert all(len(r["task"]) <= 60 for r in rep["recent"])
