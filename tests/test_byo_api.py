"""The bring-your-own-API path: a custom lane that spawns curl against an OpenAI-compatible
endpoint, with the key pulled from an env var and the prompt JSON-escaped."""
import json
import os

from cli_bridge import lanes


def _load(tmp_path, monkeypatch, spec):
    cfg = tmp_path / "byo.json"
    cfg.write_text(json.dumps([spec]))
    monkeypatch.setenv("CLI_BRIDGE_LANES_FILE", str(cfg))
    return {ln.key: ln for ln in lanes.all_lanes()}


def test_byo_api_builds_curl_with_env_key_and_escaped_task(tmp_path, monkeypatch):
    monkeypatch.setenv("MY_API_KEY", "secret-xyz")
    spec = {
        "key": "myapi", "display": "My API", "bin": "curl", "default_model": "m1",
        "ask": [
            "-sS", "https://api.example.com/v1/chat/completions",
            "-H", "Authorization: Bearer ${MY_API_KEY}",
            "-d", "{\"model\":\"{model}\",\"messages\":[{\"role\":\"user\",\"content\":\"{task_json}\"}]}",
        ],
    }
    lane = _load(tmp_path, monkeypatch, spec)["myapi"]
    argv = lane.build_ask('say "hi"\nthere', "m1", "", "")
    joined = " ".join(argv)
    assert "Authorization: Bearer secret-xyz" in joined          # env expanded
    assert "${MY_API_KEY}" not in joined                          # no leftover placeholder
    # the body must be valid JSON after our escaping (quotes + newline handled)
    body = argv[-1]
    parsed = json.loads(body)
    assert parsed["messages"][0]["content"] == 'say "hi"\nthere'  # round-trips exactly
    assert parsed["model"] == "m1"


def test_missing_env_key_expands_empty(tmp_path, monkeypatch):
    monkeypatch.delenv("MISSING_KEY", raising=False)
    spec = {"key": "k", "bin": "curl", "ask": ["-H", "Authorization: Bearer ${MISSING_KEY}"]}
    lane = _load(tmp_path, monkeypatch, spec)["k"]
    argv = lane.build_ask("t", "", "", "")
    assert argv[-1] == "Authorization: Bearer "                   # empty, not the literal name
