"""Terse response preamble for delegate prompts.

Why: a delegate's answer is read by the host AND counts as the delegate's own output
tokens. Compressing the FINAL answer (caveman-style) cuts both — the host ingests less
context, the CLI spends fewer output tokens — without touching the model's internal
reasoning. We say so explicitly: "reason fully, write the final answer terse."

Rules are the caveman skill's, embedded inline so any CLI applies them identically
(just saying "be caveman" is too vague — most CLIs don't know the skill). English on
purpose: these models are strongest in English, and it costs fewer tokens than French.

NOT applied to structured output (JSON workflows) — compressing those would break the
format. The server passes terse=False there.

Fixed overhead (measured, not estimated): the prepended instruction is constant text, so its
input cost is exactly known — `lite` is 156 chars (~39 tokens), `full` 462 (~115), `ultra`
299 (~74). That's the price per delegate call; the saving (smaller final answer) is model-
dependent and only outweighs the overhead once the answer is non-trivial. Hence
CLI_BRIDGE_TERSE_MIN_CHARS: skip the preamble on tiny tasks where it can't pay for itself.
"""
from __future__ import annotations

import os

from . import config

_LEVELS = ("off", "lite", "full", "ultra")

_RULES = {
    "lite": (
        "Reply in English, concise: cut filler, keep code, numbers and technical terms "
        "exact. Reason fully internally; trim only the final answer."
    ),
    "full": (
        "Reply in English, terse like a smart caveman — but reason FULLY internally first; "
        "only the FINAL answer is compressed.\n"
        "Drop: articles (a/an/the), filler (just/really/basically/actually), pleasantries, "
        "hedging. Fragments OK. Keep EXACT: numbers, units, identifiers, technical terms, "
        "negations, quoted errors. Leave code blocks, JSON and commands UNCHANGED.\n"
        "Exception: write any safety warning or irreversible-action caveat in normal full prose."
    ),
    "ultra": (
        "Reply in English, ultra-terse caveman. Reason FULLY internally; final answer "
        "maximally compressed — keywords/fragments only. Keep only: facts, numbers, "
        "identifiers, technical terms, negations, quoted errors. Code/JSON/commands "
        "unchanged. Safety/irreversible caveats in full prose."
    ),
}

_PREFIX = "[response style] "


def level() -> str:
    # Default 'lite': trims filler/pleasantries for real token savings but keeps full
    # sentences and never compresses reasoning — quality-safe for a broad audience. Power
    # users opt into 'full'/'ultra'; 'off' disables.
    v = os.environ.get("CLI_BRIDGE_TERSE", "").strip().lower()
    return v if v in _LEVELS else "lite"


def preamble(lvl: str | None = None) -> str:
    lvl = lvl or level()
    if lvl == "off":
        return ""
    return _PREFIX + _RULES[lvl] + "\n\n"


def apply(task: str, lvl: str | None = None) -> str:
    """Prepend the terse instruction to a prose task. No-op when level is off, or when the
    task is shorter than CLI_BRIDGE_TERSE_MIN_CHARS (a tiny task yields a tiny answer, so the
    preamble's fixed input overhead would cost more than the compression it buys)."""
    p = preamble(lvl)
    if not p:
        return task
    min_chars = config.terse_min_chars()
    if min_chars and len(task.strip()) < min_chars:
        return task
    return p + task
