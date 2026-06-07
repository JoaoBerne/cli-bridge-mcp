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


def test_flag_drift_section_flags_broken_lane(monkeypatch):
    clean = LaneSpec("c", "C", "cbin", lambda *x: [], help_args=["--help"], probe_flags=("-p", "-m"))
    broke = LaneSpec("b", "B", "bbin", lambda *x: [], help_args=["--help"], probe_flags=("--old",))
    gone = LaneSpec("g", "G", "gbin", lambda *x: [], help_args=["--help"], probe_flags=("-x",))

    async def fake_arun(argv, timeout, cwd=None, env=None):
        text = {"cbin": "options: -p PROMPT, -m MODEL", "bbin": "options: --fresh only"}.get(argv[0])
        if text is None:                                   # gbin: CLI not installed
            return RunResult(False, "not found", "not_found")
        return RunResult(True, text, "ok")
    monkeypatch.setattr(server.runner, "arun", fake_arun)

    out = asyncio.run(server._flag_drift_section([clean, broke, gone]))
    assert "Flag drift" in out
    assert "**b**" in out and "--old" in out               # broke: flag missing from help
    assert "**c**" not in out                              # clean: all flags present
    assert "**g**" not in out                              # uninstalled: no help -> no false alarm


def test_flag_drift_section_clean_when_all_present(monkeypatch):
    lane = LaneSpec("c", "C", "cbin", lambda *x: [], help_args=["--help"], probe_flags=("-p",))

    async def fake_arun(argv, timeout, cwd=None, env=None):
        return RunResult(True, "usage: -p PROMPT", "ok")
    monkeypatch.setattr(server.runner, "arun", fake_arun)

    out = asyncio.run(server._flag_drift_section([lane]))
    assert "still present" in out and "drift" not in out.lower()


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


def test_ask_best_picks_a_lane_and_traces(monkeypatch):
    a = LaneSpec("a", "LaneA", "echo", lambda *x: [])
    b = LaneSpec("b", "LaneB", "echo", lambda *x: [])
    monkeypatch.setattr(server.telemetry, "cooldown_remaining", lambda key: 0)
    monkeypatch.setattr(server.telemetry, "lane_perf", lambda: {})

    async def fake_run_lane(lane, args, *, tool="ask", terse=True):
        assert tool == "ask_best"
        return RunResult(True, "best answer", "ok", latency_ms=20)
    monkeypatch.setattr(server, "_run_lane", fake_run_lane)

    out = asyncio.run(server._ask_best([a, b], {"task": "hi", "mode": "cheap"}))
    text = out[0].text
    assert "best answer" in text and "mode 'cheap'" in text


def test_ask_best_falls_through_empty_lane(monkeypatch):
    # The live scenario: the top-routed lane (agy/gemini) exits clean but says NOTHING. ask_best
    # must skip that blank and return the lane that actually answers — not hand back "".
    a = LaneSpec("a", "LaneA", "echo", lambda *x: [])
    b = LaneSpec("b", "LaneB", "echo", lambda *x: [])
    monkeypatch.setattr(server.telemetry, "cooldown_remaining", lambda key: 0)
    monkeypatch.setattr(server.telemetry, "lane_perf", lambda: {})

    async def fake_run_lane(lane, args, *, tool="ask", terse=True):
        if lane.key == "a":
            return RunResult(False, "`agy` returned no output (exit 0)", "empty", latency_ms=9)
        return RunResult(True, "real answer", "ok", latency_ms=15)
    monkeypatch.setattr(server, "_run_lane", fake_run_lane)

    out = asyncio.run(server._ask_best([a, b], {"task": "hi", "mode": "cheap"}))
    text = out[0].text
    assert "real answer" in text
    assert "❌ a [free] 9ms — empty" in text and "✅ **b**" in text


def test_ask_best_rejects_unknown_mode(monkeypatch):
    a = LaneSpec("a", "LaneA", "echo", lambda *x: [])
    out = asyncio.run(server._ask_best([a], {"task": "hi", "mode": "wizardry"}))
    assert out[0].text.startswith("[error] unknown mode")


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


def test_list_prompts_exposes_workflows():
    names = {p.name for p in asyncio.run(server.list_prompts())}
    assert {"review_diff", "security_review", "debate", "cost_setup", "apilookup"} <= names


def test_apilookup_prompt_forces_current_docs():
    text = asyncio.run(server.get_prompt(
        "apilookup", {"query": "fastapi background tasks"})).messages[0].content.text
    assert "today's date" in text and "training cutoff" in text
    assert "ask_gemini" in text and "fastapi background tasks" in text


def test_get_prompt_review_diff_with_base():
    res = asyncio.run(server.get_prompt("review_diff", {"base": "main"}))
    text = res.messages[0].content.text
    assert "review_diff" in text and "main" in text


def test_get_prompt_debate_uses_question():
    res = asyncio.run(server.get_prompt("debate", {"question": "tabs or spaces?"}))
    assert "tabs or spaces?" in res.messages[0].content.text


def test_get_prompt_debate_without_question_falls_back():
    res = asyncio.run(server.get_prompt("debate", {}))
    assert "debate" in res.messages[0].content.text.lower()


def test_get_prompt_unknown_raises():
    import pytest
    with pytest.raises(ValueError):
        asyncio.run(server.get_prompt("nope", {}))


def test_is_host_matches_via_slug():
    lane = LaneSpec("x", "X", "x", lambda *a: [], client_ids=frozenset({"claude-code"}))
    assert server._is_host(lane, "claude-code")
    assert server._is_host(lane, server._slug("Claude Code"))
    assert not server._is_host(lane, "codex")
    assert not server._is_host(lane, "")


# ── modular tool loading (stolen from pal-mcp-server DISABLED_TOOLS, fixes A.3 bloat) ──

def _tool_names(monkeypatch):
    # a stable lane set so the listing is deterministic regardless of what's installed
    from cli_bridge import lanes as lanes_mod
    panel = [LaneSpec("gemini", "Gemini", "echo", lambda *a: []),
             LaneSpec("gpt", "GPT", "echo", lambda *a: [])]
    monkeypatch.setattr(server, "_active_lanes", lambda: (panel, "claude-code"))
    monkeypatch.setattr(lanes_mod, "all_lanes", lambda: panel)
    return {t.name for t in asyncio.run(server.list_tools())}


def test_no_filter_lists_everything(monkeypatch):
    names = _tool_names(monkeypatch)
    assert {"ask_gemini", "ask_all", "debate", "doctor", "setup"} <= names


def test_disabled_tools_hides_named_tools(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_DISABLED_TOOLS", "debate, premortem")
    names = _tool_names(monkeypatch)
    assert "debate" not in names and "premortem" not in names
    assert "ask_all" in names                      # untouched


def test_disabled_tools_cannot_hide_essentials(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_DISABLED_TOOLS", "doctor,setup")
    names = _tool_names(monkeypatch)
    assert "doctor" in names and "setup" in names   # essentials always kept


def test_enabled_tools_is_a_lean_allowlist(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_ENABLED_TOOLS", "ask_best,ask_all")
    names = _tool_names(monkeypatch)
    assert "ask_best" in names and "ask_all" in names
    assert "doctor" in names                        # essential still present
    assert "debate" not in names and "consensus" not in names   # everything else hidden


def test_lean_mode_exposes_only_core_surface(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_LEAN", "1")
    names = _tool_names(monkeypatch)
    # core tools that exist for any panel (the test panel has no build-capable lane, so
    # ask_build/job_tail aren't registered regardless of LEAN — don't assert those here)
    assert {"ask_best", "ask_all", "ask_cascade", "review_diff", "security_review", "workflow",
            "doctor", "commit_msg", "pr_describe"} <= names
    assert "ask_gpt" in names and "ask_gemini" in names   # per-lane asks kept
    assert "debate" not in names and "premortem" not in names and "route_plan" not in names
    assert "usage_report" not in names and "ask_all_async" not in names   # niche hidden


def test_re_entry_guard_blocks_a_deep_delegate(monkeypatch):
    # A delegate cli-bridge spawns runs with CLI_BRIDGE_DEPTH set; at/over the cap it must refuse.
    monkeypatch.setenv("CLI_BRIDGE_DEPTH", "1")        # default max_depth=1 -> blocked
    monkeypatch.delenv("CLI_BRIDGE_MOCK", raising=False)
    lane = LaneSpec("gemini", "Gemini", "echo", lambda *a: [])
    res = asyncio.run(server._run_lane(lane, {"task": "hi"}))
    assert res.kind == "blocked" and "re-entry guard" in res.output


def test_re_entry_guard_allows_top_level(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_DEPTH", "0")
    monkeypatch.setenv("CLI_BRIDGE_MOCK", "1")          # canned answer, no real spawn
    lane = LaneSpec("gemini", "Gemini", "echo", lambda *a: [])
    res = asyncio.run(server._run_lane(lane, {"task": "hi"}))
    assert res.ok and res.kind == "ok"                 # depth 0 < max -> runs


def test_ann_helper_is_accepted_by_tool_and_coerced():
    # _ann wraps annotation hints so mypy accepts them; at runtime the SDK must still build a real
    # ToolAnnotations from them (pydantic coercion). Guards the typed-helper escape hatch.
    from mcp.types import Tool
    t = Tool(name="x", description="d", inputSchema={"type": "object"},
             annotations=server._ann(readOnlyHint=True, destructiveHint=False))
    assert t.annotations is not None
    assert t.annotations.readOnlyHint is True
    assert t.annotations.destructiveHint is False
