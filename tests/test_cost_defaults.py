"""P1: realistic cost defaults + per-lane env overrides + first-run detection."""

from cli_bridge import lanes, server


def _lane(key):
    return next(l for l in lanes.BUILTIN_LANES if l.key == key)


def test_subscription_lanes_default_limited():
    assert _lane("claude").cost_label == "limited"
    assert _lane("gpt").cost_label == "limited"
    assert _lane("copilot").cost_label == "limited"


def test_free_lanes_default_free():
    for k in ("gemini", "mistral", "opencode"):
        assert _lane(k).cost_label == "free", k


def test_qwen_defaults_paid_since_oauth_shutdown():
    # Qwen's OAuth free tier was discontinued 2026-04-15 (docs/COSTS.md) — a metered API key is
    # the only script-legal path, so the sourced default is paid (user overrides per their plan).
    assert _lane("qwen").cost_label == "paid"
    assert "2026" in _lane("qwen").cost_note


def test_grok_defaults_limited_subscription():
    assert _lane("grok").cost_label == "limited"   # SuperGrok / X Premium+ required


def test_cost_is_configured_reflects_user_intent(monkeypatch):
    monkeypatch.delenv("CLI_BRIDGE_GEMINI_COST", raising=False)
    assert _lane("gemini").cost_is_configured is False        # sourced default, not the user's
    monkeypatch.setenv("CLI_BRIDGE_GEMINI_COST", "paid")
    assert _lane("gemini").cost_is_configured is True


def test_cost_note_effective_prefers_learned_fact(monkeypatch):
    lane = _lane("gemini")
    assert lane.cost_note_effective == lane.cost_note          # shipped default
    monkeypatch.setenv("CLI_BRIDGE_GEMINI_COST_NOTE", "user migrated to agy")
    assert lane.cost_note_effective == "user migrated to agy"  # host-learned fact wins


def test_cost_facts_staleness_clock():
    from datetime import date, timedelta
    verified = date.fromisoformat(lanes.COST_FACTS_VERIFIED)
    assert lanes.cost_facts_age_days(verified) == 0
    assert lanes.cost_facts_stale(verified + timedelta(days=30)) is False
    assert lanes.cost_facts_stale(verified + timedelta(days=120)) is True


def test_env_overrides_cost(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_GPT_COST", "free")        # user on an unlimited plan
    assert _lane("gpt").cost_label == "free"
    monkeypatch.setenv("CLI_BRIDGE_GEMINI_COST", "paid")
    assert _lane("gemini").is_paid is True


def test_dashed_key_maps_to_underscore_env(monkeypatch):
    from cli_bridge.lanes import LaneSpec
    ln = LaneSpec("my-lane", "My", "x", lambda *a: [])
    monkeypatch.setenv("CLI_BRIDGE_MY_LANE_COST", "paid")    # '-' -> '_'
    assert ln.is_paid is True


def test_cost_config_is_set_via_per_lane(monkeypatch):
    monkeypatch.delenv("CLI_BRIDGE_PROFILE", raising=False)
    assert server._cost_config_is_set() is False
    monkeypatch.setenv("CLI_BRIDGE_OPENCODE_COST", "free")
    assert server._cost_config_is_set() is True


def test_ask_all_targets_skip_limited_and_paid(tmp_path, monkeypatch):
    # isolate from the developer's real state DB: a lane in live cooldown (e.g. repeated
    # auth failures earlier the same day) would otherwise vanish from include_paid=True
    monkeypatch.setenv("CLI_BRIDGE_STATE_DB", str(tmp_path / "state.sqlite"))
    lns = lanes.BUILTIN_LANES
    free_only = server._ask_all_targets(lns, include_paid=False)
    keys = {l.key for l in free_only}
    assert "gpt" not in keys and "claude" not in keys      # limited -> skipped
    assert {"gemini", "mistral", "opencode"} <= keys        # free -> included
    all_in = server._ask_all_targets(lns, include_paid=True)
    assert "gpt" in {l.key for l in all_in}                  # include_paid -> everything


def test_custom_lane_rejects_string_models(tmp_path, monkeypatch):
    import json
    cfg = tmp_path / "l.json"
    cfg.write_text(json.dumps([{"key": "x", "ask": ["{task}"], "models": "modelsnotalist"}]))
    monkeypatch.setenv("CLI_BRIDGE_LANES_FILE", str(cfg))
    x = next(l for l in lanes.all_lanes() if l.key == "x")
    assert x.models_args is None                              # bad type -> None, not chars


def test_lanes_load_status_reports_bad_json(tmp_path, monkeypatch):
    cfg = tmp_path / "bad.json"
    cfg.write_text("{not json")
    monkeypatch.setenv("CLI_BRIDGE_LANES_FILE", str(cfg))
    lanes.load_custom_lanes()
    assert "invalid JSON" in lanes.LANES_LOAD_STATUS["error"]


def test_int_env_never_crashes(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_INLINE_MAX_CHARS", "not-a-number")
    assert server._int_env("CLI_BRIDGE_INLINE_MAX_CHARS", 12000, 500, 1_000_000) == 12000


def test_install_hint_present():
    assert _lane("gemini").install_hint
    assert _lane("opencode").install_hint
