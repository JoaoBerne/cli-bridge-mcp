"""The Claude Code plugin manifests must stay valid JSON and mutually consistent."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"
PLUGIN_DIR = ROOT / "plugin"
MANIFEST = PLUGIN_DIR / ".claude-plugin" / "plugin.json"


def test_marketplace_is_valid_and_points_at_the_plugin():
    mp = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
    assert mp["name"] and mp["plugins"], "marketplace needs a name and at least one plugin"
    entry = mp["plugins"][0]
    assert entry["name"] == "cli-bridge"
    src = (ROOT / entry["source"]).resolve()
    assert src == PLUGIN_DIR.resolve(), "source must point at the in-repo plugin directory"


def test_plugin_manifest_launches_the_published_package():
    pj = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert pj["name"] == "cli-bridge"
    server = pj["mcpServers"]["cli-bridge"]
    assert server["command"] == "uvx"
    assert server["args"] == ["cli-bridge-mcp"], "must launch the PyPI package, not a local path"


def test_registry_server_json_passes_the_publish_checks():
    import tomllib

    sj = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    assert len(sj["description"]) <= 100, "the MCP registry rejects a longer description (422)"
    assert sj["version"] == sj["packages"][0]["version"] == version
