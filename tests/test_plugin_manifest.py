"""The Claude Code plugin manifests must stay valid JSON and mutually consistent."""

import json
import re
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


def test_every_skill_has_frontmatter_name_and_description():
    skills = sorted((PLUGIN_DIR / "skills").glob("*/SKILL.md"))
    assert skills, "plugin must ship at least one skill"
    for path in skills:
        text = path.read_text(encoding="utf-8")
        m = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
        assert m, f"{path} is missing YAML frontmatter"
        front = m.group(1)
        name = re.search(r"^name:\s*(\S+)", front, re.MULTILINE)
        assert name and name.group(1) == path.parent.name, \
            f"{path}: frontmatter name must match its directory"
        assert re.search(r"^description:\s*\S", front, re.MULTILINE), \
            f"{path}: description is required (Claude uses it to pick the skill)"


def test_identity_stays_clean():
    # The public identity rule: no real-name leakage in anything shipped.
    for path in (MARKETPLACE, MANIFEST):
        text = path.read_text(encoding="utf-8").lower()
        for banned in ("jeanbtt", "jean-bernard", "brintet.jb"):
            assert banned not in text, f"{path} leaks a banned identity string"
