"""Unit tests for server-side helpers that don't need a live MCP session."""
from cli_bridge import server


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


def test_is_host_matches_via_slug():
    from cli_bridge.lanes import LaneSpec
    lane = LaneSpec("x", "X", "x", lambda *a: [], client_ids=frozenset({"claude-code"}))
    assert server._is_host(lane, "claude-code")
    assert server._is_host(lane, server._slug("Claude Code"))
    assert not server._is_host(lane, "codex")
    assert not server._is_host(lane, "")
