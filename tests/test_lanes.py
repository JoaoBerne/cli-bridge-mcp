import json

from cli_bridge import lanes


def _lane(key):
    return next(ln for ln in lanes.BUILTIN_LANES if ln.key == key)


def test_gpt_effort_and_model():
    argv = _lane("gpt").build_ask("do it", "gpt-5.5", "high", "")
    assert "exec" in argv
    assert "model_reasoning_effort=high" in " ".join(argv)
    assert "-m" in argv and "gpt-5.5" in argv and argv[-1] == "do it"


def test_gpt_no_model_no_flag():
    argv = _lane("gpt").build_ask("hi", "", "", "")
    assert "-m" not in argv


def test_opencode_free_default_applied():
    lane = _lane("opencode")
    model = lane.model_for("")                      # caller omitted model
    argv = lane.build_ask("hi", model, "", "plan")
    assert "opencode/deepseek-v4-flash-free" in argv      # never a paid default
    assert "--dangerously-skip-permissions" not in argv   # plan = read-only


def test_opencode_build_agent_writes():
    lane = _lane("opencode")
    argv = lane.build_ask("hi", lane.model_for(""), "high", "build")
    assert "--dangerously-skip-permissions" in argv and "--variant" in argv


def test_mistral_arg_order():
    argv = _lane("mistral").build_ask("hi", "", "", "")
    assert argv == ["-p", "hi", "--agent", "plan", "--trust"]


def test_env_bin_override(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_GEMINI_BIN", "agy")
    assert _lane("gemini").bin == "agy"


def test_env_model_override(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_GPT_MODEL", "gpt-x")
    assert _lane("gpt").model_for("") == "gpt-x"
    assert _lane("gpt").model_for("explicit") == "explicit"  # caller wins


def test_custom_lane_from_json(tmp_path, monkeypatch):
    cfg = tmp_path / "lanes.json"
    cfg.write_text(json.dumps([{
        "key": "foo", "display": "Foo CLI", "bin": "foocli",
        "ask": ["chat", "{task}"], "model_flag": "-m", "default_model": "foo-1",
        "client_ids": ["foo-host"],
    }]))
    monkeypatch.setenv("CLI_BRIDGE_LANES_FILE", str(cfg))
    custom = {ln.key: ln for ln in lanes.all_lanes()}
    assert "foo" in custom
    argv = custom["foo"].build_ask("hello", "foo-1", "", "")
    assert argv == ["-m", "foo-1", "chat", "hello"]


def test_all_lanes_includes_builtins():
    keys = {ln.key for ln in lanes.all_lanes()}
    assert {"claude", "gpt", "gemini", "mistral", "opencode", "qwen", "copilot"} <= keys
