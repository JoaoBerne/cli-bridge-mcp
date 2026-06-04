"""Cost-truth: tiers are sourced defaults (never presented as detected), the host can evolve
the policy itself (set_lane_cost), and the $0 council example actually loads."""

import asyncio
import json
import os

from cli_bridge import config, lanes, server

# ── honest display ───────────────────────────────────────────────────────────────────────

def test_doctor_says_tiers_are_not_detected():
    text = server._doctor("")
    assert "NOT detected" in text
    assert "(default — yours may differ)" in text          # unconfigured tier labeled as such


def test_doctor_marks_user_set_cost(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_GEMINI_COST", "paid")
    assert "(set by you)" in server._doctor("")


def test_doctor_warns_when_cost_facts_stale(monkeypatch):
    monkeypatch.setattr(lanes, "cost_facts_stale", lambda today=None: True)
    assert "Cost facts last verified" in server._doctor("")


def test_setup_asks_the_binary_question_and_never_claims_detection():
    text = server._setup_recommendation(list(lanes.BUILTIN_LANES))
    assert "by what they cost YOU" not in text             # the old false-authority header
    assert "NOT detected" in text
    assert "flat subscriptions" in text and "metered" in text   # the one question to ask first
    assert "set_lane_cost" in text                         # answers get persisted, not lost


def test_config_snapshot_reports_cost_source(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_GEMINI_COST", "free")
    snap = server._config_snapshot("")
    by_key = {entry["key"]: entry for entry in snap["lanes"]}
    assert by_key["gemini"]["cost_source"] == "user"
    assert by_key["mistral"]["cost_source"] == "default"


# ── self-maintaining policy: set_lane_cost ───────────────────────────────────────────────

def test_set_lane_cost_applies_now_and_persists(tmp_path, monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_CONFIG_FILE", str(tmp_path / "config.json"))
    try:
        out = asyncio.run(server.call_tool("set_lane_cost", {
            "lane": "opencode", "cost": "limited", "note": "user on the Go plan"}))
        text = out[0].text
        assert "opencode" in text and "limited" in text and "persisted" in text
        ln = next(l for l in lanes.BUILTIN_LANES if l.key == "opencode")
        assert ln.cost_label == "limited" and ln.cost_is_configured       # effective immediately
        assert ln.cost_note_effective == "user on the Go plan"            # doctor shows the why
        cfg = json.loads((tmp_path / "config.json").read_text())          # survives a restart
        assert cfg["lanes"]["opencode"]["cost"] == "limited"
        assert cfg["lanes"]["opencode"]["cost_note"] == "user on the Go plan"
    finally:
        os.environ.pop("CLI_BRIDGE_OPENCODE_COST", None)
        os.environ.pop("CLI_BRIDGE_OPENCODE_COST_NOTE", None)


def test_set_lane_cost_validates_lane_and_tier():
    out = asyncio.run(server.call_tool("set_lane_cost", {"lane": "nope", "cost": "free"}))
    assert "[error]" in out[0].text
    out = asyncio.run(server.call_tool("set_lane_cost", {"lane": "gemini", "cost": "cheapish"}))
    assert "[error]" in out[0].text


def test_update_config_file_merges_without_clobbering(tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"profile": "max", "lanes": {"gpt": {"daily_limit": 50}}}))
    monkeypatch.setenv("CLI_BRIDGE_CONFIG_FILE", str(p))
    assert config.update_config_file({"gpt": {"cost": "free"}}) == str(p)
    cfg = json.loads(p.read_text())
    assert cfg["profile"] == "max"                                        # untouched
    assert cfg["lanes"]["gpt"] == {"daily_limit": 50, "cost": "free"}     # merged, not replaced


def test_config_file_maps_cost_note_to_env(tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"lanes": {"gemini": {"cost_note": "learned fact"}}}))
    monkeypatch.setenv("CLI_BRIDGE_CONFIG_FILE", str(p))
    monkeypatch.delenv("CLI_BRIDGE_GEMINI_COST_NOTE", raising=False)
    try:
        config.apply_file_config_to_env()
        assert os.environ["CLI_BRIDGE_GEMINI_COST_NOTE"] == "learned fact"
    finally:
        os.environ.pop("CLI_BRIDGE_GEMINI_COST_NOTE", None)


# ── community lanes: the wider ecosystem plugs in without a fork ─────────────────────────

def test_community_lanes_example_loads_safely(monkeypatch):
    path = os.path.join(os.path.dirname(__file__), "..", "examples", "community-lanes.json")
    monkeypatch.setenv("CLI_BRIDGE_LANES_FILE", path)
    loaded = lanes.load_custom_lanes()
    assert lanes.LANES_LOAD_STATUS["skipped"] == 0
    keys = {ln.key for ln in loaded}
    assert {"aider", "goose", "plandex", "amp", "crush", "q", "droid"} <= keys
    assert not keys & {ln.key for ln in lanes.BUILTIN_LANES}   # no silent built-in override
    for ln in loaded:
        assert ln.experimental                       # flags best-effort, says so
        assert ln.cost_label == "limited"            # cost-safe: out of fan-out until declared
        argv = ln.build_ask("hi", "", "", "")
        assert "hi" in argv and "{task}" not in " ".join(argv)
    by_key = {ln.key: ln for ln in loaded}
    for k in ("aider", "goose", "amp", "q"):         # flagged lanes are drift-checkable
        assert by_key[k].probe_flags


# ── the $0 council ships working ─────────────────────────────────────────────────────────

def test_free_apis_example_loads_as_free_curl_lanes(monkeypatch):
    path = os.path.join(os.path.dirname(__file__), "..", "examples", "free-apis.json")
    monkeypatch.setenv("CLI_BRIDGE_LANES_FILE", path)
    loaded = lanes.load_custom_lanes()
    keys = {ln.key for ln in loaded}
    assert {"groq", "cerebras", "ghmodels", "openrouter-free"} <= keys
    for ln in loaded:
        assert ln.bin_default == "curl"
        assert ln.cost_label == "free"                     # hard-stop providers only
        argv = ln.build_ask("hi", ln.default_model, "", "")
        assert any("chat/completions" in part for part in argv)
        body = argv[-1]
        assert ln.default_model in body and '"hi"' in body  # {model} + {task_json} expanded
    assert lanes.LANES_LOAD_STATUS["argv_secret_risk"] == []   # keys imported INSIDE curl


# ── argv secrets stay out of `ps` (council blocker M11-1) ────────────────────────────────

def test_argv_secret_risk_detector():
    risky = ["-H", "Authorization: Bearer ${KEY}"]
    safe = ["--variable", "%KEY", "--expand-header", "Authorization: Bearer {{KEY}}"]
    assert lanes.argv_secret_risk(risky) is True
    assert lanes.argv_secret_risk(safe) is False               # curl expands internally
    assert lanes.argv_secret_risk(["${HOME}/x", "{task}"]) is False  # env ≠ credential


def test_doctor_warns_on_argv_secret_lane(tmp_path, monkeypatch):
    cfg = tmp_path / "lanes.json"
    cfg.write_text(json.dumps([{
        "key": "leaky", "bin": "curl",
        "ask": ["-H", "Authorization: Bearer ${LEAK_KEY}", "https://x", "{task}"]}]))
    monkeypatch.setenv("CLI_BRIDGE_LANES_FILE", str(cfg))
    text = server._doctor("")
    assert "Secret in argv" in text and "leaky" in text and "--expand-header" in text
