"""MCP prompt builders — the council's workflows as host-native slash commands.

Each `_p_*` returns a user message pointing the host at the matching cli-bridge tool, so
`review_diff`/`debate`/… surface in MCP hosts' prompt pickers. server.py's `@list_prompts`/
`@get_prompt` read the `_PROMPTS` registry built here. Pure string assembly.
"""
from __future__ import annotations

from mcp.types import PromptArgument


def _p_review_diff(a: dict) -> str:
    base = (a or {}).get("base", "").strip()
    against = f" against `{base}`" if base else ""
    return (f"Use the cli-bridge `review_diff` tool to review the git diff{against}, then "
            "summarize the merged findings grouped by severity.")


def _p_security_review(a: dict) -> str:
    base = (a or {}).get("base", "").strip()
    against = f" against `{base}`" if base else ""
    return (f"Use the cli-bridge `security_review` tool on the git diff{against}, then report "
            "the security findings by severity with remediations.")


def _p_debate(a: dict) -> str:
    q = (a or {}).get("question", "").strip()
    return (f"Use the cli-bridge `debate` tool to debate this question across models, then give "
            f"me the final conclusion:\n\n{q}" if q
            else "Use the cli-bridge `debate` tool to debate a question across models. Ask me "
                 "for the question if I didn't provide one.")


def _p_cost_setup(a: dict) -> str:
    return ("Call the cli-bridge `setup` tool, then walk me through choosing a cost profile "
            "(saver / balanced / max) and how to set it for my plan.")


def _p_premortem(a: dict) -> str:
    plan = (a or {}).get("plan", "").strip()
    return (f"Use the cli-bridge `premortem` tool on this plan, then give me the prioritized "
            f"risks and mitigations:\n\n{plan}" if plan
            else "Use the cli-bridge `premortem` tool to stress-test a plan. Ask me for the plan "
                 "if I didn't give one.")


def _p_test_plan(a: dict) -> str:
    base = (a or {}).get("base", "").strip()
    against = f" against `{base}`" if base else ""
    return (f"Use the cli-bridge `test_plan` tool on the git diff{against}, then give me the "
            "prioritized test cases to add.")


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
    "review_diff": {
        "description": "Multi-model code review of your current git diff.",
        "arguments": [PromptArgument(
            name="base", description="git ref/range to diff against (default HEAD)", required=False)],
        "build": _p_review_diff,
    },
    "security_review": {
        "description": "OWASP-aware multi-model security review of your git diff.",
        "arguments": [PromptArgument(
            name="base", description="git ref/range to diff against (default HEAD)", required=False)],
        "build": _p_security_review,
    },
    "debate": {
        "description": "Debate a question across several models, then a judge concludes.",
        "arguments": [PromptArgument(
            name="question", description="The question to debate", required=True)],
        "build": _p_debate,
    },
    "cost_setup": {
        "description": "Configure how cli-bridge spends paid credits/quota (cost profile).",
        "arguments": [],
        "build": _p_cost_setup,
    },
    "premortem": {
        "description": "Stress-test a plan across models before building it.",
        "arguments": [PromptArgument(
            name="plan", description="The plan/change to premortem", required=False)],
        "build": _p_premortem,
    },
    "test_plan": {
        "description": "Derive a prioritized test plan from your git diff across models.",
        "arguments": [PromptArgument(
            name="base", description="git ref/range to diff against (default HEAD)", required=False)],
        "build": _p_test_plan,
    },
    "apilookup": {
        "description": "Look up a library/API in CURRENT docs via a web-aware lane (beats a "
                       "stale training cutoff).",
        "arguments": [PromptArgument(
            name="query", description="library/API + what you need", required=False)],
        "build": _p_apilookup,
    },
}
