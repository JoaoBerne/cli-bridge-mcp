"""MCP sampling: use the host's own model as a FREE judge/synthesizer, with lane fallback.

Both paths are exercised by monkeypatching _host_sample (the real sampling call can only be
validated against a live host, but the host-first / lane-fallback logic is fully testable).
"""
import asyncio

from cli_bridge import server
from cli_bridge.lanes import LaneSpec
from cli_bridge.runner import RunResult


def test_host_sample_noop_outside_request_context():
    # No MCP request context (tests / async jobs / CLI) -> None, never raises.
    assert asyncio.run(server._host_sample("hi")) is None


def _answered():
    a = LaneSpec("a", "A", "echo", lambda *x: [])
    b = LaneSpec("b", "B", "echo", lambda *x: [])
    return a, b, [(a, RunResult(True, "answer a", "ok")), (b, RunResult(True, "answer b", "ok"))]


def test_synthesize_prefers_host_no_lane_spent(monkeypatch):
    a, b, answered = _answered()

    async def fake_host(prompt, max_tokens=1024):
        return "HOST SYNTHESIS"
    monkeypatch.setattr(server, "_host_sample", fake_host)

    async def boom(*args, **kwargs):
        raise AssertionError("a lane must NOT be spawned when host sampling works")
    monkeypatch.setattr(server, "_run_lane", boom)

    out = asyncio.run(server._synthesize("q", answered, [a, b]))
    assert "HOST SYNTHESIS" in out and "host model" in out


def test_synthesize_falls_back_to_lane(monkeypatch):
    a, b, answered = _answered()

    async def no_host(prompt, max_tokens=1024):
        return None
    monkeypatch.setattr(server, "_host_sample", no_host)

    async def fake_run_lane(lane, args, *, tool="ask", terse=True):
        return RunResult(True, "LANE SYNTHESIS", "ok")
    monkeypatch.setattr(server, "_run_lane", fake_run_lane)

    out = asyncio.run(server._synthesize("q", answered, [a, b]))
    assert "LANE SYNTHESIS" in out
