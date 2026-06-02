"""Per-lane model selection (incl. env-based, e.g. vibe) + the generic list_models tool.

No real CLI: runner.arun is faked so we can assert the env/argv the lane would spawn with.
"""
import asyncio

import pytest

from cli_bridge import lanes, server, telemetry
from cli_bridge.lanes import LaneSpec
from cli_bridge.runner import RunResult


def _mistral():
    return next(ln for ln in lanes.BUILTIN_LANES if ln.key == "mistral")


def test_mistral_selects_model_via_env_not_flag():
    m = _mistral()
    assert "model" in m.caps and m.env_ask is not None     # selectable, env-based
    assert m.env_ask("devstral-small", "", "") == {"VIBE_ACTIVE_MODEL": "devstral-small"}
    assert m.env_ask("", "", "") == {}                     # empty -> vibe's own default
    # the model is NOT injected as an argv flag (vibe has none)
    assert "devstral-small" not in m.build_ask("hi", "devstral-small", "", "", "vibe")


@pytest.fixture
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_STATE_DB", str(tmp_path / "s.sqlite"))
    telemetry._reset_for_tests()
    yield
    telemetry._reset_for_tests()


def test_run_lane_injects_model_env(isolate, monkeypatch):
    captured = {}

    async def fake_arun(argv, timeout, cwd=None, env=None):
        captured["env"] = env
        return RunResult(True, "ok", "ok")
    monkeypatch.setattr(server.runner, "arun", fake_arun)

    asyncio.run(server._run_lane(_mistral(), {"task": "hi", "model": "devstral-small"}))
    assert captured["env"] is not None
    assert captured["env"]["VIBE_ACTIVE_MODEL"] == "devstral-small"
    assert "PATH" in captured["env"]          # full env copy, not a bare dict (keeps auth/PATH)


def test_run_lane_no_model_inherits_env(isolate, monkeypatch):
    captured = {}

    async def fake_arun(argv, timeout, cwd=None, env=None):
        captured["env"] = env
        return RunResult(True, "ok", "ok")
    monkeypatch.setattr(server.runner, "arun", fake_arun)

    asyncio.run(server._run_lane(_mistral(), {"task": "hi"}))   # no model
    assert captured["env"] is None            # inherit parent env unchanged


def test_list_models_without_command_shows_default(isolate, monkeypatch):
    gpt = LaneSpec("gpt", "GPT", "echo", lambda *x: [], caps=frozenset({"model"}))
    monkeypatch.setattr(server, "_active_lanes", lambda: ([gpt], ""))
    out = asyncio.run(server.call_tool("list_models", {"lane": "gpt"}))[0].text
    assert "no model-list command" in out and "model=" in out


def test_list_models_runs_command_when_available(isolate, monkeypatch):
    oc = LaneSpec("opencode", "OpenCode", "echo", lambda *x: [], models_args=["models"])
    monkeypatch.setattr(server, "_active_lanes", lambda: ([oc], ""))

    async def fake_arun(argv, timeout, cwd=None, env=None):
        assert argv[-1] == "models"
        return RunResult(True, "opencode/free-1\nopencode/free-2", "ok")
    monkeypatch.setattr(server.runner, "arun", fake_arun)

    out = asyncio.run(server.call_tool("list_models", {"lane": "opencode"}))[0].text
    assert "free-1" in out
