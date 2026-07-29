"""MCP resources: list + read JSON snapshots of cli-bridge's own state."""
import asyncio
import json

import pytest

from cli_bridge import server
from cli_bridge.mcp_compat import attr  # mcp 2.0 renamed model fields to snake_case


def test_list_resources():
    res = asyncio.run(server.list_resources())
    uris = {str(r.uri) for r in res}
    assert {"cli-bridge://config", "cli-bridge://lane-stats", "cli-bridge://usage-summary",
            "cli-bridge://workflow-schemas/review-diff"} <= uris
    assert all(attr(r, "mimeType") == "application/json" for r in res)


def test_read_config_resource(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_GUARD", "strict")
    out = asyncio.run(server.read_resource("cli-bridge://config"))
    data = json.loads(out)
    assert data["guard"] == "strict"
    assert isinstance(data["lanes"], list) and data["lanes"]
    assert {"key", "installed", "cost", "caps"} <= set(data["lanes"][0])


def test_read_review_schema_resource():
    out = asyncio.run(server.read_resource("cli-bridge://workflow-schemas/review-diff"))
    schema = json.loads(out)
    assert schema["properties"]["findings"]["type"] == "array"
    sev = schema["properties"]["findings"]["items"]["properties"]["severity"]["enum"]
    assert "blocker" in sev


def test_read_lane_stats_and_usage_are_json(monkeypatch, tmp_path):
    monkeypatch.setenv("CLI_BRIDGE_STATE_DB", str(tmp_path / "s.sqlite"))
    from cli_bridge import telemetry
    telemetry._reset_for_tests()
    json.loads(asyncio.run(server.read_resource("cli-bridge://lane-stats")))
    json.loads(asyncio.run(server.read_resource("cli-bridge://usage-summary")))


def test_read_unknown_resource_raises():
    with pytest.raises(ValueError):
        asyncio.run(server.read_resource("cli-bridge://nope"))
