"""Unit tests for server-side helpers that don't need a live MCP session."""
import asyncio

from cli_bridge import server
from cli_bridge.lanes import LaneSpec
from cli_bridge.runner import RunResult


def test_slug_normalizes_host_names():
    assert server._slug("Claude Code") == "claude-code"
    assert server._slug("claude_code") == "claude-code"
    assert server._slug("claude-code") == "claude-code"
    assert server._slug("Anthropic  Claude!") == "anthropic--claude"


def test_str_coerces_null_to_empty():
    assert server._str({"x": None}, "x") == ""        # JSON null must not become "None"
    assert server._str({}, "x") == ""
    assert server._str({"x": "  hi "}, "x") == "hi"
    assert server._str({"x": 123}, "x") == "123"


def test_timeout_guard():
    assert server._timeout("abc") == server.DEFAULT_TIMEOUT_S
    assert server._timeout(None) == server.DEFAULT_TIMEOUT_S
    assert server._timeout(10) == 10
    assert server._timeout(99999) == server.MAX_TIMEOUT_S
    assert server._timeout(0) == 1


def test_ask_all_timeout_guard():
    assert server._ask_all_timeout("abc") == server.ASK_ALL_DEFAULT_TIMEOUT_S
    assert server._ask_all_timeout(None) == server.ASK_ALL_DEFAULT_TIMEOUT_S
    assert server._ask_all_timeout(10) == 10
    assert server._ask_all_timeout(99999) == server.ASK_ALL_MAX_TIMEOUT_S
    assert server._ask_all_timeout(0) == 1


def test_ask_all_targets_skip_limited_and_paid_by_default(monkeypatch):
    from cli_bridge.lanes import LaneSpec
    free = LaneSpec("free", "Free", "echo", lambda *a: [])
    limited = LaneSpec("limited", "Limited", "echo", lambda *a: [])
    paid = LaneSpec("paid", "Paid", "echo", lambda *a: [], paid=True)
    monkeypatch.setenv("CLI_BRIDGE_LIMITED_COST", "limited")

    targets = server._ask_all_targets([free, limited, paid], include_paid=False)
    assert targets == [free]
    assert server._ask_all_targets([free, limited, paid], include_paid=True) == [
        free, limited, paid]


def test_ask_all_include_paid_profile(monkeypatch):
    monkeypatch.delenv("CLI_BRIDGE_PROFILE", raising=False)
    assert server._ask_all_include_paid({}) is False
    monkeypatch.setenv("CLI_BRIDGE_PROFILE", "max")
    assert server._ask_all_include_paid({}) is True
    assert server._ask_all_include_paid({"include_paid": False}) is False


def test_cascade_trace_shows_attempts_and_chosen(monkeypatch):
    a = LaneSpec("a", "LaneA", "echo", lambda *x: [])
    b = LaneSpec("b", "LaneB", "echo", lambda *x: [])
    monkeypatch.setattr(server.telemetry, "cooldown_remaining", lambda key: 0)

    async def fake_run_lane(lane, args, *, tool="ask", terse=True):
        if lane.key == "a":
            return RunResult(False, "rate limited", "quota", latency_ms=12)
        return RunResult(True, "the answer", "ok", latency_ms=34)
    monkeypatch.setattr(server, "_run_lane", fake_run_lane)

    out = asyncio.run(server._ask_cascade([a, b], {"task": "hi"}))
    text = out[0].text
    assert "the answer" in text
    assert "Trace — cascade" in text
    assert "❌ a [free] 12ms — quota" in text
    assert "✅ **b** [free] 34ms — chosen" in text


def test_cascade_trace_on_total_failure(monkeypatch):
    a = LaneSpec("a", "LaneA", "echo", lambda *x: [])
    monkeypatch.setattr(server.telemetry, "cooldown_remaining", lambda key: 0)

    async def fake_run_lane(lane, args, *, tool="ask", terse=True):
        return RunResult(False, "boom", "failed", latency_ms=5)
    monkeypatch.setattr(server, "_run_lane", fake_run_lane)

    out = asyncio.run(server._ask_cascade([a], {"task": "hi"}))
    text = out[0].text
    assert text.startswith("[error] all lanes failed")
    assert "Trace — cascade" in text and "❌ a [free] 5ms — failed" in text


def _claude_lane():
    from cli_bridge.lanes import BUILTIN_LANES
    return next(ln for ln in BUILTIN_LANES if ln.key == "claude")


def test_host_lane_exposed_for_sibling_model(monkeypatch):
    claude = _claude_lane()
    monkeypatch.setattr(server, "installed_lanes", lambda lst: [claude])
    monkeypatch.setenv("CLI_BRIDGE_HOST", "claude-code")
    # host's own claude lane is NOT a delegate (excluded from fan-out)...
    delegates, host = server._active_lanes()
    assert claude not in delegates and host == "claude-code"
    # ...but IS available as a self-consult lane (has model cap)
    assert server._host_lane("claude-code") is claude


def test_self_ask_tool_listed_and_requires_model(monkeypatch):
    claude = _claude_lane()
    monkeypatch.setattr(server, "installed_lanes", lambda lst: [claude])
    monkeypatch.setenv("CLI_BRIDGE_HOST", "claude-code")
    tools = asyncio.run(server.list_tools())
    ask_claude = next((t for t in tools if t.name == "ask_claude"), None)
    assert ask_claude is not None
    assert "model" in ask_claude.inputSchema["required"]


def test_self_ask_rejects_missing_model(monkeypatch):
    claude = _claude_lane()
    monkeypatch.setattr(server, "installed_lanes", lambda lst: [claude])
    monkeypatch.setenv("CLI_BRIDGE_HOST", "claude-code")
    out = asyncio.run(server.call_tool("ask_claude", {"task": "hi"}))
    assert "explicit `model`" in out[0].text


def test_self_ask_runs_with_explicit_model(monkeypatch):
    claude = _claude_lane()
    monkeypatch.setattr(server, "installed_lanes", lambda lst: [claude])
    monkeypatch.setenv("CLI_BRIDGE_HOST", "claude-code")
    captured = {}

    async def fake_run_lane(lane, args, *, tool="ask", terse=True):
        captured["key"] = lane.key
        captured["model"] = args.get("model")
        return RunResult(True, "sibling says hi", "ok", latency_ms=7)
    monkeypatch.setattr(server, "_run_lane", fake_run_lane)

    out = asyncio.run(server.call_tool("ask_claude", {"task": "hi", "model": "claude-opus-4-6"}))
    assert "sibling says hi" in out[0].text
    assert captured == {"key": "claude", "model": "claude-opus-4-6"}


def test_is_host_matches_via_slug():
    lane = LaneSpec("x", "X", "x", lambda *a: [], client_ids=frozenset({"claude-code"}))
    assert server._is_host(lane, "claude-code")
    assert server._is_host(lane, server._slug("Claude Code"))
    assert not server._is_host(lane, "codex")
    assert not server._is_host(lane, "")
