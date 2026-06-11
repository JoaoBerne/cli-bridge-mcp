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

import json
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


# Named role personas (V.2): a small curated set prepended to a delegate's task via `role=`.
# Curated SHORT on purpose (the council's anti-bloat note): perspective diversity decorrelates
# council errors (Du et al. 2305.14325, ReConcile 2309.13007) but plateaus fast — a 32-persona
# catalog is prompt theater, not signal. Each entry exists to catch a DISTINCT failure mode.
# Unknown role = no-op. Users add their own via CLI_BRIDGE_ROLES_FILE (see roles()).
ROLES = {
    "reviewer": "Act as a rigorous code reviewer. Find concrete bugs, edge cases and risks; be "
                "specific (file/line/why); no praise.",
    "security": "Act as a security auditor (OWASP-aware). Hunt injection, auth/access flaws, "
                "secrets, unsafe deserialization, SSRF, path traversal; rate severity.",
    "planner": "Act as a planner. Break the task into a numbered, dependency-ordered list of small "
               "verifiable steps; no code, just the plan.",
    "devil": "Act as devil's advocate. Argue the STRONGEST case AGAINST the proposal; surface "
             "failure modes and hidden assumptions before agreeing.",
    "architect": "Act as a software architect. Weigh 2-3 viable designs with explicit tradeoffs "
                 "(complexity, coupling, migration cost), then commit to ONE recommendation and "
                 "say what would change your mind.",
    "oracle": "Act as a test designer working ONLY from the stated requirements — deliberately "
              "ignore any implementation shown. Specify inputs, expected outputs and edge cases "
              "an implementation must satisfy; a test that mirrors the implementation is a "
              "failure.",
    "simplifier": "Act as a simplicity enforcer. Identify what can be DELETED or collapsed: "
                  "speculative abstractions, unused flexibility, dead code paths, over-general "
                  "interfaces. Propose the smallest design that still meets the stated need.",
}


def roles_file_status() -> dict:
    """Load CLI_BRIDGE_ROLES_FILE and report what happened — surfaced by `doctor` so a
    malformed file never fails SILENTLY into built-ins (the custom-lanes lesson). Keys:
    path, roles (the parsed dict), error ('' = ok), dropped (non-string entries),
    overrides (names that shadow a built-in). Read per call on purpose: the file is tiny
    next to a multi-second CLI spawn, and edits apply without a server restart."""
    path = os.environ.get("CLI_BRIDGE_ROLES_FILE", "").strip()
    out: dict = {"path": path, "roles": {}, "error": "", "dropped": [], "overrides": []}
    if not path:
        return out
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out
    if not isinstance(data, dict):
        out["error"] = "top level must be a JSON object {\"name\": \"persona text\"}"
        return out
    for k, v in data.items():
        if isinstance(k, str) and isinstance(v, str) and k.strip() and v.strip():
            name = k.strip().lower()
            out["roles"][name] = v.strip()
            if name in ROLES:
                out["overrides"].append(name)
        else:
            out["dropped"].append(str(k))
    return out


def roles() -> dict[str, str]:
    """All available roles: curated built-ins + the user's file. The file wins on a name
    clash, so a team can re-word a built-in without forking."""
    return {**ROLES, **roles_file_status()["roles"]}


def with_role(role: str, task: str) -> str:
    """Prepend a persona to the task. Three forms:
    - a registry name (built-in or roles-file) -> that persona;
    - free text WITH whitespace -> used verbatim as an inline persona. This is dynamic
      role assignment (arXiv 2601.17152): the HOST writes a role tailored to this exact
      task instead of picking from a fixed list — the host is the selector;
    - unknown single word -> no-op (a typo'd name must not silently become the persona).
    """
    raw = (role or "").strip()
    if not raw:
        return task
    persona = roles().get(raw.lower())
    if persona is None and any(ch.isspace() for ch in raw):
        persona = raw
    return f"[role] {persona}\n\n{task}" if persona else task


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
