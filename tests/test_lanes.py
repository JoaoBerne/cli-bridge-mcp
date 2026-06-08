import json
from types import SimpleNamespace

from cli_bridge import lanes


def _lane(key):
    return next(ln for ln in lanes.BUILTIN_LANES if ln.key == key)


def test_family_of_derives_from_client_ids_and_key():
    fam = {ln.key: lanes.family_of(ln) for ln in lanes.BUILTIN_LANES}
    assert fam["claude"] == "anthropic" and fam["gpt"] == "openai"
    assert fam["gemini"] == "google" and fam["mistral"] == "mistral"
    assert fam["opencode"] == "opencode"


def test_family_of_env_override(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_FAMILY_OVERRIDES", "gpt:acme")
    assert lanes.family_of(_lane("gpt")) == "acme"
    assert lanes.family_of(_lane("gemini")) == "google"          # others unaffected


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


# ── Grok built-in lane (experimental; no hardcoded model) ──────────────────────────────

def test_grok_lane_exists_no_hardcoded_model():
    lane = _lane("grok")
    assert lane.experimental and "model" in lane.caps
    assert lane.default_model == ""                       # never pin a model that can age out
    argv = lane.build_ask("hi", "", "", "")
    assert argv == ["-p", "hi"]                           # official headless flag; no model pinned
    argv2 = lane.build_ask("hi", "grok-x", "", "")
    assert "--model" in argv2 and "grok-x" in argv2


# ── Ollama built-in lane (local models, ban-safe) ──────────────────────────────────────

def test_ollama_argv_requires_hidethinking():
    # --hidethinking is mandatory: ollama models are thinking models, so without it stdout
    # carries the chain of thought before the answer.
    argv = _lane("ollama").build_ask("Reply OK", "qwen3.5:0.8b", "", "")
    assert argv == ["run", "--hidethinking", "qwen3.5:0.8b", "Reply OK"]


def test_ollama_is_read_only_free_lane():
    lane = _lane("ollama")
    assert lane.cost_label == "free" and lane.is_paid is False
    assert lane.caps == frozenset({"model"})              # no effort/agent — read-only, no build
    assert lanes.family_of(lane) == "ollama"              # distinct family for jury decorrelation


def test_ollama_spawn_env_strips_ansi():
    # ollama writes ANSI cursor codes to stdout even when redirected; NO_COLOR + dumb TERM fix it.
    env = _lane("ollama").env_ask("", "", "")
    assert env == {"NO_COLOR": "1", "TERM": "dumb"}


def test_ollama_default_model_skips_header(monkeypatch):
    # `ollama list` prints a header row then model rows; the empty-model default is the first
    # model's first column. The header is skipped UNCONDITIONALLY (not by matching its text).
    lanes._ollama_model_cache.clear()
    monkeypatch.setattr(lanes.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=0,
        stdout="NAME       ID       SIZE    MODIFIED\n"
               "gemma4:e4b-it-qat   ee66   6.1 GB   41 hours ago\n"
               "qwen3.5:0.8b        f381   1.0 GB   5 weeks ago\n"))
    try:
        assert _lane("ollama").model_for("") == "gemma4:e4b-it-qat"
    finally:
        lanes._ollama_model_cache.clear()


def test_ollama_default_model_empty_on_failure(monkeypatch):
    lanes._ollama_model_cache.clear()
    monkeypatch.setattr(lanes.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=1, stdout=""))
    try:
        assert _lane("ollama").model_for("") == ""        # no models pulled → empty, re-probe later
    finally:
        lanes._ollama_model_cache.clear()


# ── opencode free-model discovery is PATTERN-based, not a pinned name ───────────────────

def test_opencode_default_never_picks_a_paid_model(monkeypatch):
    # Cost-safety: a bare `opencode/*` Zen model bills per-token and `opencode-go/*` spends
    # credits. With NO `-free` model listed, the empty-model default must NOT silently select a
    # paid one — it falls to the free seed instead.
    lanes._opencode_model_cache.clear()
    monkeypatch.setattr(lanes.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=0, stdout="opencode/zen-next\nopencode-go/paid-pro\n"))
    try:
        picked = _lane("opencode").model_for("")
        assert picked.endswith("-free")                       # never the paid zen / go model
        assert picked not in {"opencode/zen-next", "opencode-go/paid-pro"}
    finally:
        lanes._opencode_model_cache.clear()


def test_opencode_default_de_pinned_picks_any_free(monkeypatch):
    # Future-proof: not tied to a specific name. If deepseek-* is gone, another `-free` is picked.
    lanes._opencode_model_cache.clear()
    monkeypatch.setattr(lanes.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=0, stdout="opencode/new-mini-free\nopencode/zen-paid\nopencode-go/pro\n"))
    try:
        assert _lane("opencode").model_for("") == "opencode/new-mini-free"
    finally:
        lanes._opencode_model_cache.clear()


# ── flag-drift health check (pure part) + custom-lane probe derivation ──────────────────

def test_missing_flags_pure():
    help_text = "Usage: codex exec [--sandbox MODE] [-m MODEL]"
    assert lanes.missing_flags(help_text, ("--sandbox", "-m")) == []
    assert lanes.missing_flags(help_text, ("--sandbox", "--gone")) == ["--gone"]
    assert lanes.missing_flags("", ("-m",)) == []          # no help -> can't tell -> no alarm
    assert lanes.missing_flags(help_text, ()) == []        # nothing to probe


def test_builtin_lanes_declare_probe_flags():
    for key in ("claude", "gpt", "gemini", "mistral", "opencode", "grok"):
        assert _lane(key).probe_flags, f"{key} should declare probe_flags for drift detection"


def test_custom_lane_derives_probe_flags(tmp_path, monkeypatch):
    cfg = tmp_path / "lanes.json"
    cfg.write_text(json.dumps([{
        "key": "grok2", "display": "Grok2", "bin": "grok", "model_flag": "-m",
        "ask": ["chat", "--json", "{task}"]}]))
    monkeypatch.setenv("CLI_BRIDGE_LANES_FILE", str(cfg))
    lane = next(ln for ln in lanes.load_custom_lanes() if ln.key == "grok2")
    assert lane.probe_flags == ("-m", "--json")            # model flag + dash-args from template


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
