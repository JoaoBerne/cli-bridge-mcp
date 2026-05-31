import json
from types import SimpleNamespace

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


def test_opencode_free_default_applied(monkeypatch):
    lanes._current_opencode_free_model.cache_clear()
    monkeypatch.setattr(lanes.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=0,
        stdout="opencode/deepseek-v4-flash-free\n",
    ))
    lane = _lane("opencode")
    assert lane.is_paid is False                         # ask_all includes the free default
    try:
        model = lane.model_for("")                      # caller omitted model
        argv = lane.build_ask("hi", model, "", "plan")
        assert "opencode/deepseek-v4-flash-free" in argv      # never a paid default
        assert "--dangerously-skip-permissions" not in argv   # plan = read-only
    finally:
        lanes._current_opencode_free_model.cache_clear()


def test_opencode_default_prefers_current_free_model_list(monkeypatch):
    lanes._current_opencode_free_model.cache_clear()
    monkeypatch.setattr(lanes.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=0,
        stdout="opencode/big-pickle\nopencode/mimo-v2.5-free\nopencode-go/paid-model\n",
    ))
    try:
        assert _lane("opencode").model_for("") == "opencode/mimo-v2.5-free"
    finally:
        lanes._current_opencode_free_model.cache_clear()


def test_opencode_default_keeps_preferred_free_model_when_listed(monkeypatch):
    lanes._current_opencode_free_model.cache_clear()
    monkeypatch.setattr(lanes.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=0,
        stdout="opencode/mimo-v2.5-free\nopencode/deepseek-v4-flash-free\n",
    ))
    try:
        assert _lane("opencode").model_for("") == "opencode/deepseek-v4-flash-free"
    finally:
        lanes._current_opencode_free_model.cache_clear()


def test_opencode_default_falls_back_when_model_list_fails(monkeypatch):
    lanes._current_opencode_free_model.cache_clear()
    monkeypatch.setattr(lanes.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=1,
        stdout="",
    ))
    try:
        assert _lane("opencode").model_for("") == "opencode/deepseek-v4-flash-free"
    finally:
        lanes._current_opencode_free_model.cache_clear()


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


def test_cost_env_override(monkeypatch):
    lane = _lane("gemini")
    assert lane.is_paid is False                      # free by default
    monkeypatch.setenv("CLI_BRIDGE_GEMINI_COST", "paid")
    assert lane.is_paid is True                       # user declares it paid on their plan
    monkeypatch.setenv("CLI_BRIDGE_OPENCODE_COST", "free")
    assert _lane("opencode").is_paid is False         # user declares opencode free for them


def test_enabled_env(monkeypatch):
    assert _lane("gpt").enabled is True
    monkeypatch.setenv("CLI_BRIDGE_GPT_ENABLED", "false")
    assert _lane("gpt").enabled is False


def test_gemini_bin_falls_back_to_agy(monkeypatch):
    import shutil
    real = shutil.which
    monkeypatch.setattr(lanes.shutil, "which",
                        lambda b: "/x/agy" if b == "agy" else (None if b == "gemini" else real(b)))
    assert _lane("gemini").bin == "agy"               # gemini absent -> agy fallback


def test_custom_lane_rejects_string_ask(tmp_path, monkeypatch):
    cfg = tmp_path / "bad.json"
    cfg.write_text(json.dumps([{"key": "bad", "ask": "not-a-list"}]))   # string, not list
    monkeypatch.setenv("CLI_BRIDGE_LANES_FILE", str(cfg))
    assert "bad" not in {ln.key for ln in lanes.all_lanes()}


def test_custom_lane_rejects_reserved_key(tmp_path, monkeypatch):
    cfg = tmp_path / "r.json"
    cfg.write_text(json.dumps([{"key": "all", "ask": ["{task}"]}]))
    monkeypatch.setenv("CLI_BRIDGE_LANES_FILE", str(cfg))
    assert "all" not in {ln.key for ln in lanes.all_lanes()}
