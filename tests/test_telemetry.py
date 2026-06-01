"""Phase 1: telemetry records runs, cools lanes on repeated failure, exposes stats."""

import pytest

from cli_bridge import telemetry


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


# ── accounting (M6): estimated tokens + credits, budget, since filter, lane_perf ──────────

def _run_chars(lane, in_chars, out_chars):
    rec = telemetry.start("ask", lane, "m1", "t" * in_chars)
    telemetry.record(rec, True, "ok", output_chars=out_chars, input_chars=in_chars)


def test_usage_report_estimates_tokens():
    _run_chars("gemini", 400, 800)               # /4 -> 100 in, 200 out
    by = {r["lane"]: r for r in telemetry.usage_report()["by_lane"]}
    assert by["gemini"]["est_input_tokens"] == 100
    assert by["gemini"]["est_output_tokens"] == 200


def test_usage_report_estimates_credits(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_GEMINI_CREDITS_PER_1K", "2.0")   # 2 credits / 1k tokens
    _run_chars("gemini", 400, 800)               # 300 total tokens -> 0.6 credits
    rep = telemetry.usage_report()
    by = {r["lane"]: r for r in rep["by_lane"]}
    assert by["gemini"]["est_credits"] == 0.6
    assert rep["est_total_credits"] == 0.6


def test_usage_report_no_rate_means_no_credits():
    _run_chars("mistral", 40, 40)
    by = {r["lane"]: r for r in telemetry.usage_report()["by_lane"]}
    assert by["mistral"]["est_credits"] is None


def test_usage_budget_counts_today_and_flags_over_limit(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_GPT_DAILY_LIMIT", "1")
    _run_chars("gpt", 40, 40)
    _run_chars("gpt", 40, 40)                     # 2 runs > limit 1
    rep = telemetry.usage_budget()
    by = {r["lane"]: r for r in rep["by_lane"]}
    assert by["gpt"]["runs_today"] == 2 and by["gpt"]["daily_limit"] == 1
    assert by["gpt"]["over_limit"] is True


def test_usage_report_since_filter():
    _run_chars("gemini", 40, 40)
    # a 1-second window still includes the just-recorded run
    assert telemetry.usage_report(since_s=1)["total_runs"] >= 1
    # a window ending before any run (negative) excludes everything
    assert telemetry.usage_report(since_s=-100)["total_runs"] == 0


def test_lane_perf_shape():
    _run_chars("gemini", 40, 40)
    rec = telemetry.start("ask", "gemini", "m1", "t")
    telemetry.record(rec, False, "failed", output_chars=0)
    perf = telemetry.lane_perf()
    assert perf["gemini"]["runs"] == 2
    assert 0.0 < perf["gemini"]["fail_rate"] <= 1.0
