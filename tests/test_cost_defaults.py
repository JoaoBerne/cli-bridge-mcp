"""P1: realistic cost defaults + per-lane env overrides + first-run detection."""

from cli_bridge import lanes, server


def _lane(key):
    return next(l for l in lanes.BUILTIN_LANES if l.key == key)


def test_subscription_lanes_default_limited():
    assert _lane("claude").cost_label == "limited"
    assert _lane("gpt").cost_label == "limited"
    assert _lane("copilot").cost_label == "limited"


def test_free_lanes_default_free():
    for k in ("gemini", "mistral", "opencode", "qwen"):
        assert _lane(k).cost_label == "free", k


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


def test_ask_all_targets_skip_limited_and_paid():
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
