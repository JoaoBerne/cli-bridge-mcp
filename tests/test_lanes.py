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
    lanes._opencode_model_cache.clear()
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
        lanes._opencode_model_cache.clear()


def test_opencode_default_prefers_current_free_model_list(monkeypatch):
    lanes._opencode_model_cache.clear()
    monkeypatch.setattr(lanes.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=0,
        stdout="opencode/big-pickle\nopencode/mimo-v2.5-free\nopencode-go/paid-model\n",
    ))
    try:
        assert _lane("opencode").model_for("") == "opencode/mimo-v2.5-free"
    finally:
        lanes._opencode_model_cache.clear()


def test_opencode_default_keeps_preferred_free_model_when_listed(monkeypatch):
    lanes._opencode_model_cache.clear()
    monkeypatch.setattr(lanes.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=0,
        stdout="opencode/mimo-v2.5-free\nopencode/deepseek-v4-flash-free\n",
    ))
    try:
        assert _lane("opencode").model_for("") == "opencode/deepseek-v4-flash-free"
    finally:
        lanes._opencode_model_cache.clear()


def test_opencode_default_falls_back_when_model_list_fails(monkeypatch):
    lanes._opencode_model_cache.clear()
    monkeypatch.setattr(lanes.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=1,
        stdout="",
    ))
    try:
        assert _lane("opencode").model_for("") == "opencode/deepseek-v4-flash-free"
    finally:
        lanes._opencode_model_cache.clear()


def test_opencode_build_agent_writes():
    lane = _lane("opencode")
    argv = lane.build_ask("hi", lane.model_for(""), "high", "build")
    assert "--dangerously-skip-permissions" in argv and "--variant" in argv


def test_mistral_arg_order():
    argv = _lane("mistral").build_ask("hi", "", "", "")
    assert argv == ["-p", "hi", "--agent", "plan", "--trust"]


# ── build (write) mode: read-only stays the default; build flips the verified write flag ──

def test_claude_plan_is_readonly_build_edits():
    plan = _lane("claude").build_ask("t", "", "", "")
    assert "--permission-mode" in plan and "plan" in plan and "acceptEdits" not in plan
    build = _lane("claude").build_ask("t", "", "", "build")
    assert "acceptEdits" in build and "plan" not in build


def test_claude_model_selects_sibling():
    argv = _lane("claude").build_ask("t", "claude-opus-4-6", "", "")
    assert "--model" in argv and "claude-opus-4-6" in argv


def test_gpt_build_uses_workspace_write():
    plan = _lane("gpt").build_ask("t", "", "", "")
    assert "read-only" in plan and "workspace-write" not in plan
    build = _lane("gpt").build_ask("t", "", "", "build")
    assert "workspace-write" in build and "read-only" not in build


def test_gemini_build_flag_depends_on_bin():
    # gemini -> --yolo ; agy -> --dangerously-skip-permissions (and agy ignores model)
    g = _lane("gemini").build_ask("t", "m", "", "build", "gemini")
    assert "--yolo" in g and "-m" in g
    a = _lane("gemini").build_ask("t", "m", "", "build", "agy")
    assert "--dangerously-skip-permissions" in a and "-m" not in a
    # plan mode: no write flag either way
    assert "--yolo" not in _lane("gemini").build_ask("t", "", "", "", "gemini")


def test_mistral_build_accept_edits():
    argv = _lane("mistral").build_ask("hi", "", "", "build")
    assert argv == ["-p", "hi", "--agent", "accept-edits", "--trust"]


def test_qwen_and_copilot_build_flags():
    assert "--yolo" in _lane("qwen").build_ask("t", "", "", "build")
    assert "--allow-all-tools" in _lane("copilot").build_ask("t", "", "", "build")


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
    assert lane.is_limited is False
    assert lane.cost_label == "free"
    monkeypatch.setenv("CLI_BRIDGE_GEMINI_COST", "paid")
    assert lane.is_paid is True                       # user declares it paid on their plan
    assert lane.cost_label == "paid"
    monkeypatch.setenv("CLI_BRIDGE_GEMINI_COST", "limited")
    assert lane.is_paid is False                      # quota-sensitive but not money
    assert lane.is_limited is True
    assert lane.cost_label == "limited"
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
