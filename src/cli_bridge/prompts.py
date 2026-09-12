"""MCP prompt builders — host-native slash commands.

Each `_p_*` returns a user message pointing the host at the matching cli-bridge tool. server.py's
`@list_prompts`/`@get_prompt` read the `_PROMPTS` registry built here. Pure string assembly.
"""
from __future__ import annotations

from mcp.types import PromptArgument


def _p_apilookup(a: dict) -> str:
    q = (a or {}).get("query", "").strip()
    subject = q or "the library/API I name next"
    # A current-docs guard (prior art: workflow MCP servers' apilookup): forces a dated,
    # current-year lookup via a WEB-AWARE lane so a stale training cutoff can't answer. Zero
    # tool-surface cost — it's a prompt, not another tool.
    return (
        f"Look up CURRENT documentation for {subject} and answer from it, not from memory:\n"
        "1. First state today's date.\n"
        "2. Use a web-aware cli-bridge lane — `ask_gemini` (or `ask_grok`) — to fetch the "
        "CURRENT-YEAR official docs/changelog/release notes; do NOT trust your training cutoff.\n"
        "3. Give the answer with the version it applies to and link the source."
        + (f"\n\nQuery: {q}" if q else ""))


_PROMPTS: dict[str, dict] = {
    "apilookup": {
        "description": "Look up a library/API in CURRENT docs via a web-aware lane (beats a "
                       "stale training cutoff).",
        "arguments": [PromptArgument(
            name="query", description="library/API + what you need", required=False)],
        "build": _p_apilookup,
    },
}
