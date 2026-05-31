"""Lane registry — one entry per AI CLI the bridge can consult.

A *lane* is pure data + a small argv builder. Adding a CLI = adding a LaneSpec, never
touching the server. Users can also add their own lanes at runtime via a JSON file
(CLI_BRIDGE_LANES_FILE) without forking the code — the headline feature over hardcoded
bridges.

Per-lane runtime overrides (so people configure to THEIR subscriptions, no code edits):
  CLI_BRIDGE_<KEY>_BIN      -> binary name/path (e.g. point `gemini` at Antigravity's `agy`)
  CLI_BRIDGE_<KEY>_MODEL    -> default model when the caller doesn't pass one
  CLI_BRIDGE_<KEY>_COST     -> "free" or "paid" — declare whether THIS lane costs YOU money
                              (depends on your plan). Drives ask_all's free-only default.
  CLI_BRIDGE_<KEY>_ENABLED  -> "false" to hide a lane even if its CLI is installed
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from typing import Callable

_EFFORT = {"": "", "minimal": "minimal", "low": "low", "medium": "medium",
           "high": "high", "max": "max"}


def _effort(value: str) -> str:
    return _EFFORT.get((value or "").strip().lower(), "")


@dataclass
class LaneSpec:
    key: str                              # tool id -> ask_<key>
    display: str                          # human name in tool descriptions
    bin_default: str                      # default binary (env-overridable)
    build_ask: Callable[..., list[str]]   # (task, model, effort, agent) -> argv after bin
    paid: bool = False                    # DEFAULT cost stance (user-overridable via env)
    default_model: str = ""               # used when caller omits model (env-overridable)
    models_args: list[str] | None = None  # argv to list models, or None
    help_args: list[str] | None = None    # argv to print CLI help, or None
    caps: frozenset[str] = field(default_factory=frozenset)        # {"model","effort","agent"}
    client_ids: frozenset[str] = field(default_factory=frozenset)  # MCP clientInfo.name == host
    bin_alts: tuple[str, ...] = ()        # fallback binaries if the default isn't on PATH
    experimental: bool = False            # flags not verified live — caller is warned
    note: str = ""

    def _env(self, suffix: str) -> str:
        return os.environ.get(f"CLI_BRIDGE_{self.key.upper()}_{suffix}", "").strip()

    @property
    def bin(self) -> str:
        """Explicit override wins; else the default, or an installed alternative
        (so a `gemini` lane auto-uses `agy` when only Antigravity is installed)."""
        override = self._env("BIN")
        if override:
            return override
        for cand in (self.bin_default, *self.bin_alts):
            if shutil.which(cand):
                return cand
        return self.bin_default

    @property
    def enabled(self) -> bool:
        return self._env("ENABLED").lower() not in {"0", "false", "no", "off"}

    @property
    def is_paid(self) -> bool:
        """Whether THIS lane costs the user money — they declare it per their plan."""
        cost = self._env("COST").lower()
        if cost in {"paid", "credits", "$"}:
            return True
        if cost in {"free", "0"}:
            return False
        return self.paid

    def model_for(self, model: str) -> str:
        return (model or "").strip() or self._env("MODEL") or self.default_model


# ─────────────────────────────── built-in lane builders ───────────────────────────────

def _claude_ask(task, model, effort, agent):
    cmd = ["--print", "--permission-mode", "plan"]
    if model:
        cmd += ["--model", model]
    return cmd + [task]


def _codex_ask(task, model, effort, agent):
    cmd = ["exec", "--sandbox", "read-only", "--skip-git-repo-check"]
    eff = {"minimal": "low", "low": "low", "medium": "medium",
           "high": "high", "max": "high"}.get(_effort(effort), "")
    if eff:
        cmd += ["-c", f"model_reasoning_effort={eff}"]
    if model:
        cmd += ["-m", model]
    return cmd + [task]


def _gemini_ask(task, model, effort, agent):
    # `gemini` accepts -m; Antigravity's `agy` does not (only -p). The builder doesn't know
    # which binary will run, so it emits -m only for a model; callers using agy should leave
    # model empty (its default is empty, so the common path stays -p only).
    cmd = []
    if model:
        cmd += ["-m", model]
    return cmd + ["-p", task]


def _mistral_ask(task, model, effort, agent):
    # vibe: prompt must come before --agent; --trust skips the per-dir trust prompt.
    return ["-p", task, "--agent", "plan", "--trust"]


def _opencode_ask(task, model, effort, agent):
    ag = (agent or "plan").strip() or "plan"
    cmd = ["run", "--agent", ag, "-m", model]      # model always set (free default upstream)
    var = {"minimal": "minimal", "low": "minimal", "medium": "high",
           "high": "high", "max": "max"}.get(_effort(effort), "")
    if var:
        cmd += ["--variant", var]
    if ag != "plan":                                # only a write agent auto-approves
        cmd.append("--dangerously-skip-permissions")
    return cmd + [task]


def _qwen_ask(task, model, effort, agent):         # Qwen Code is a gemini-cli fork
    cmd = []
    if model:
        cmd += ["-m", model]
    return cmd + ["-p", task]


def _copilot_ask(task, model, effort, agent):      # GitHub Copilot CLI (best-effort flags)
    cmd = []
    if model:
        cmd += ["--model", model]
    return cmd + ["-p", task]


# opencode's bare default resolves to a PAID model; force a free one unless the caller
# explicitly asks for a paid 'opencode-go/*'. Env-overridable.
_OPENCODE_FREE_DEFAULT = "opencode/deepseek-v4-flash-free"


BUILTIN_LANES: list[LaneSpec] = [
    LaneSpec("claude", "Claude (Claude Code CLI)", "claude", _claude_ask,
             models_args=None, help_args=["--help"], caps=frozenset({"model"}),
             client_ids=frozenset({"claude-code", "claude", "claude-desktop"}),
             note="Anthropic. Strong all-round reasoning. (--print --permission-mode plan, verified.)"),
    LaneSpec("gpt", "GPT (OpenAI Codex CLI)", "codex", _codex_ask,
             help_args=["exec", "--help"], caps=frozenset({"model", "effort"}),
             client_ids=frozenset({"codex", "codex-mcp-client", "codex-cli"}),
             note="OpenAI. effort=high for hard reasoning, low/empty for quick."),
    LaneSpec("gemini", "Gemini (Google Gemini CLI / Antigravity)", "gemini", _gemini_ask,
             help_args=["--help"], caps=frozenset({"model"}), bin_alts=("agy",),
             client_ids=frozenset({"gemini-cli-mcp-client", "gemini", "antigravity"}),
             note="Google. Fast, broad, multimodal/web. Uses `gemini`, or falls back to `agy` "
                  "(Antigravity) if that's what's installed."),
    LaneSpec("mistral", "Mistral (Vibe CLI)", "vibe", _mistral_ask,
             help_args=["--help"], caps=frozenset(),
             client_ids=frozenset({"vibe", "mistral"}),
             note="Mistral free tier. Lightweight quick takes."),
    LaneSpec("opencode", "OpenCode (gateway to many models)", "opencode", _opencode_ask,
             paid=True, default_model=_OPENCODE_FREE_DEFAULT,
             models_args=["models"], help_args=["run", "--help"],
             caps=frozenset({"model", "effort", "agent"}),
             client_ids=frozenset({"opencode"}),
             note=("Gateway to deepseek/qwen/glm/kimi/minimax/... Empty model = a FREE default "
                   "(never costs credits). Pass a paid 'opencode-go/*' model only when the task "
                   "earns it. agent='build' lets it EDIT files directly (default 'plan' is read-only).")),
    LaneSpec("qwen", "Qwen (Qwen Code CLI)", "qwen", _qwen_ask,
             help_args=["--help"], caps=frozenset({"model"}),
             client_ids=frozenset({"qwen", "qwen-code"}),
             experimental=True,
             note="Alibaba Qwen. Large context, strong code. (Flags assume a gemini-cli fork.)"),
    LaneSpec("copilot", "GitHub Copilot CLI", "copilot", _copilot_ask,
             help_args=["--help"], caps=frozenset({"model"}),
             client_ids=frozenset({"copilot", "github-copilot"}),
             experimental=True,
             note="GitHub Copilot. Flags unverified; if your install is `gh copilot`, set "
                  "CLI_BRIDGE_COPILOT_BIN and a custom lane instead."),
]


# ─────────────────────────────── user-defined lanes (no code) ───────────────────────────────

_ENV_REF = __import__("re").compile(r"\$\{([A-Z0-9_]+)\}")


def _expand(part: str, task: str, model: str) -> str:
    """Fill a template argument. Placeholders:
      {task}       -> the prompt, raw
      {task_json}  -> the prompt, JSON-escaped (for embedding in a JSON body, e.g. curl)
      {model}      -> the model id
      ${ENV_VAR}   -> value of that environment variable (e.g. an API key) — kept out of
                      the config file so users commit a template without leaking secrets
    """
    part = part.replace("{task_json}", json.dumps(task)[1:-1])  # escaped, no surrounding quotes
    part = part.replace("{task}", task).replace("{model}", model)
    return _ENV_REF.sub(lambda m: os.environ.get(m.group(1), ""), part)


def _template_builder(ask_tmpl: list[str], model_flag: str):
    """Build an argv builder from a JSON template. With a plain CLI use `{task}`/`{model}`
    + an optional model flag (`bin <sub> -m MODEL <task>`). To wrap your OWN API, set the
    binary to `curl` and use `{task_json}` + `${YOUR_API_KEY}` in the body/headers — the
    council calls your endpoint exactly like any other lane, ban-safe by the same logic
    (we just spawn curl)."""
    def build(task, model, effort, agent):
        out: list[str] = []
        if model_flag and model:
            out += [model_flag, model]
        for part in ask_tmpl:
            out.append(_expand(part, task, model))
        return out
    return build


def load_custom_lanes(path: str | None = None) -> list[LaneSpec]:
    path = path or os.environ.get("CLI_BRIDGE_LANES_FILE", "").strip()
    if not path or not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    lanes: list[LaneSpec] = []
    reserved = {"all", "doctor"}
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key", "")).strip()
        ask = item.get("ask")
        # ask must be a list of strings (a bare string would become a list of characters)
        if (not key or key in reserved or not key.replace("_", "").replace("-", "").isalnum()
                or not isinstance(ask, list) or not all(isinstance(p, str) for p in ask) or not ask):
            continue
        ask_tmpl = list(ask)
        model_flag = str(item.get("model_flag", "")).strip()
        lanes.append(LaneSpec(
            key=key,
            display=str(item.get("display", key)),
            bin_default=str(item.get("bin", key)),
            build_ask=_template_builder(ask_tmpl, model_flag),
            paid=bool(item.get("paid", False)),
            default_model=str(item.get("default_model", "")),
            models_args=list(item["models"]) if item.get("models") else None,
            help_args=list(item["help"]) if item.get("help") else None,
            caps=frozenset({"model"}) if model_flag else frozenset(),
            client_ids=frozenset(item.get("client_ids", [])),
            experimental=bool(item.get("experimental", False)),
            note=str(item.get("note", "user-defined lane")),
        ))
    return lanes


def all_lanes() -> list[LaneSpec]:
    """Built-ins plus any user-defined lanes. A custom lane with an existing key overrides."""
    by_key = {lane.key: lane for lane in BUILTIN_LANES}
    for lane in load_custom_lanes():
        by_key[lane.key] = lane
    return list(by_key.values())
