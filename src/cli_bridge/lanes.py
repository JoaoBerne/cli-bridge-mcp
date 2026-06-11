"""Lane registry — one entry per AI CLI the bridge can consult.

A *lane* is pure data + a small argv builder. Adding a CLI = adding a LaneSpec, never
touching the server. Users can also add their own lanes at runtime via a JSON file
(CLI_BRIDGE_LANES_FILE) without forking the code — the headline feature over hardcoded
bridges.

Per-lane runtime overrides (so people configure to THEIR subscriptions, no code edits):
  CLI_BRIDGE_<KEY>_BIN      -> binary name/path (e.g. point `gemini` at Antigravity's `agy`)
  CLI_BRIDGE_<KEY>_MODEL    -> default model when the caller doesn't pass one
  CLI_BRIDGE_<KEY>_COST     -> "free", "limited", or "paid" — declare whether THIS lane costs YOU
                              money or scarce quota. Drives ask_all's default targets.
  CLI_BRIDGE_<KEY>_ENABLED  -> "false" to hide a lane even if its CLI is installed
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field

# GUI MCP hosts (Claude Desktop, Hermes Desktop, …) launch their servers with a minimal
# login PATH that misses Homebrew/npm/user bins — so a CLI that works fine in a terminal
# is "not installed" from inside the app. When plain PATH lookup fails, retry in the
# usual install dirs. Order: most specific (user) first.
_EXTRA_BIN_DIRS = (
    os.path.expanduser("~/.local/bin"),
    os.path.expanduser("~/.npm-global/bin"),
    os.path.expanduser("~/bin"),
    os.path.expanduser("~/.cargo/bin"),
    "/opt/homebrew/bin",
    "/usr/local/bin",
)


def which_path(cmd: str) -> str | None:
    """shutil.which plus the common install dirs above. Returns `cmd` unchanged when PATH
    already resolves it (keeps argv/display short), the absolute path when it's only found
    in a fallback dir, or None."""
    if shutil.which(cmd):
        return cmd
    if os.path.basename(cmd) == cmd:           # bare name only — don't remap explicit paths
        for d in _EXTRA_BIN_DIRS:
            # path= keeps shutil's own PATHEXT handling (`gemini` → gemini.exe/.cmd on
            # Windows); joining the path by hand skips that on Python < 3.12.
            found = shutil.which(cmd, path=d)
            if found:
                return found
    return None


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
    paid: bool = False                    # DEPRECATED shorthand for cost_default="paid"
    cost_default: str = "free"            # "free" | "limited" | "paid" (user-overridable via env)
    cost_note: str = ""                   # one-line SOURCED fact about what this lane really
                                          # costs (see docs/COSTS.md) — shown by doctor/setup so
                                          # the default is explainable, never presented as detected
    default_model: str = ""               # used when caller omits model (env-overridable)
    models_args: list[str] | None = None  # argv to list models, or None
    help_args: list[str] | None = None    # argv to print CLI help, or None
    version_args: tuple[str, ...] = ("--version",)   # argv to print the CLI's version (drift check)
    probe_flags: tuple[str, ...] = ()     # flags this lane EMITS that must still exist in the
                                          # CLI's --help; if one vanishes the invocation is broken
                                          # (doctor deep flags the drift before a silent failure)
    caps: frozenset[str] = field(default_factory=frozenset)        # {"model","effort","agent"}
    client_ids: frozenset[str] = field(default_factory=frozenset)  # MCP clientInfo.name == host
    bin_alts: tuple[str, ...] = ()        # fallback binaries if the default isn't on PATH
    sunset: str = ""                      # ISO date the lane's free service dies (vendor-announced).
                                          # Once passed: a 'free' default degrades to 'limited' and
                                          # bin resolution prefers bin_alts (the successor CLI).
    experimental: bool = False            # flags not verified live — caller is warned
    install_hint: str = ""                # shown by doctor when the CLI isn't installed
    note: str = ""
    # Some CLIs pick a model via an ENV var, not a flag (e.g. vibe reads VIBE_ACTIVE_MODEL). A
    # lane may supply extra env vars for the spawn via this builder; default = none.
    env_ask: Callable[..., dict] | None = None
    # Native session continuity for round-table turns (an optimization over transcript replay —
    # replay stays the cross-lane source of truth). Two modes:
    #   mint:    we generate the handle and hand it to the CLI ({"mode":"mint",
    #            "first":[...{sid}...], "resume":[...{sid}...]})
    #   capture: the CLI names its session in officially-flagged output ({"mode":"capture",
    #            "spawn":[flags...], "pattern": regex, "resume":[...{sid}...]})
    # Extra argv is inserted just before the task (the last argv element). None = replay only.
    native_session: dict | None = None

    def _env(self, suffix: str) -> str:
        # Env vars can't contain '-', but tool keys can; map so a 'my-lane' key still reads
        # CLI_BRIDGE_MY_LANE_COST. (Underscore is the only safe word separator in shells.)
        env_key = self.key.upper().replace("-", "_")
        return os.environ.get(f"CLI_BRIDGE_{env_key}_{suffix}", "").strip()

    def sunset_passed(self, today=None) -> bool:
        """True once the vendor-announced sunset date for this lane's free service is reached.
        `today` injectable for tests (same pattern as cost_facts_age_days)."""
        if not self.sunset:
            return False
        from datetime import date
        try:
            return (today or date.today()) >= date.fromisoformat(self.sunset)
        except ValueError:
            return False

    @property
    def bin(self) -> str:
        """Explicit override wins; else the default, or an installed alternative
        (so a `gemini` lane auto-uses `agy` when only Antigravity is installed). After a
        sunset the alternatives are preferred — the old binary may still be on PATH long
        after its service died, and trying it first would spawn a dead CLI forever."""
        override = self._env("BIN")
        if override:
            return override
        order = (self.bin_default, *self.bin_alts)
        if self.bin_alts and self.sunset_passed():
            order = (*self.bin_alts, self.bin_default)
        for cand in order:
            found = which_path(cand)
            if found:
                return found
        return self.bin_default

    @property
    def enabled(self) -> bool:
        return self._env("ENABLED").lower() not in {"0", "false", "no", "off"}

    @property
    def _cost(self) -> str:
        """Resolved cost tier: user's env override wins, else the lane's realistic default."""
        cost = self._env("COST").lower()
        if cost in {"paid", "credits", "$"}:
            return "paid"
        if cost in {"limited", "quota", "metered"}:
            return "limited"
        if cost in {"free", "0"}:
            return "free"
        default = "paid" if self.paid else self.cost_default
        if default == "free" and self.sunset_passed():
            return "limited"    # the free tier is dead — keep it out of default fan-out
        return default

    @property
    def cost_note_effective(self) -> str:
        """The note shown next to a lane's cost tier. A fact the HOST learned and persisted
        (set_lane_cost — from the user's own words or the host's fresher knowledge) wins over
        the shipped sourced default, so the displayed story evolves without a code change."""
        return self._env("COST_NOTE") or self.cost_note

    @property
    def cost_is_configured(self) -> bool:
        """True when the USER declared this lane's cost (env var, or the config file — which is
        applied to env at startup). False = we're using the sourced default, which describes a
        TYPICAL plan, not theirs. Display surfaces must say which one they're showing."""
        return bool(self._env("COST"))

    @property
    def min_interval_s(self) -> float:
        """Anti-burst pacing: minimum seconds between spawns of THIS lane (see runner.pace).
        0 = off (default — no behaviour change). Set it when a free tier rate-limits under
        back-to-back calls: CLI_BRIDGE_<LANE>_MIN_INTERVAL_S=2 (or `min_interval_s` in the
        config file)."""
        try:
            return max(0.0, float(self._env("MIN_INTERVAL_S") or 0))
        except ValueError:
            return 0.0

    @property
    def is_paid(self) -> bool:
        """Whether THIS lane costs the user money — they declare it per their plan."""
        return self._cost == "paid"

    @property
    def is_limited(self) -> bool:
        """Free money-wise but on scarce quota — kept out of broad fan-out by default."""
        return self._cost == "limited"

    @property
    def cost_label(self) -> str:
        return self._cost

    def model_for(self, model: str) -> str:
        explicit = (model or "").strip()
        if explicit:
            return explicit
        env_model = self._env("MODEL")
        if env_model:
            return env_model
        if self.key == "opencode":
            return _opencode_default_model(self.bin)
        if self.key == "ollama":
            return _current_ollama_model(self.bin)
        return self.default_model


# ─────────────────────────── vendor family (cross-vendor jury) ───────────────────────────
# A model can't trustworthily review its OWN family's output (correlated blind spots). Derive the
# family from client_ids/key so new lanes need no manual upkeep; override with
# CLI_BRIDGE_FAMILY_OVERRIDES="lanekey:family,lanekey2:family2".
_FAMILY_BY_TOKEN = {
    "claude": "anthropic", "anthropic": "anthropic",
    "codex": "openai", "openai": "openai", "gpt": "openai",
    "gemini": "google", "antigravity": "google", "google": "google",
    "vibe": "mistral", "mistral": "mistral",
    "opencode": "opencode",
    "qwen": "qwen",
    "copilot": "github", "github-copilot": "github",
    "grok": "xai", "xai": "xai",
}


def _family_overrides() -> dict[str, str]:
    out: dict[str, str] = {}
    for part in os.environ.get("CLI_BRIDGE_FAMILY_OVERRIDES", "").split(","):
        if ":" in part:
            k, v = part.split(":", 1)
            if k.strip() and v.strip():
                out[k.strip().lower()] = v.strip().lower()
    return out


def family_of(lane: LaneSpec) -> str:
    """Vendor family (anthropic/openai/google/…). Env override wins; else matched from
    client_ids/key tokens; else the lane key (an unknown lane is its OWN family = isolated, the
    conservative default for the author!=reviewer rule)."""
    ov = _family_overrides()
    if lane.key.lower() in ov:
        return ov[lane.key.lower()]
    for tok in {lane.key.lower()} | {c.lower() for c in lane.client_ids}:
        for needle, fam in _FAMILY_BY_TOKEN.items():
            if needle in tok:
                return fam
    return lane.key.lower()


# ─────────────────────────────── built-in lane builders ───────────────────────────────

def _is_build(agent) -> bool:
    return (agent or "").strip().lower() == "build"


def _claude_ask(task, model, effort, agent, bin=""):
    # plan = read-only; build = acceptEdits (auto-applies file edits, no per-edit prompt).
    mode = "acceptEdits" if _is_build(agent) else "plan"
    cmd = ["--print", "--permission-mode", mode]
    if model:
        cmd += ["--model", model]
    return cmd + [task]


def _codex_ask(task, model, effort, agent, bin=""):
    # `codex exec` is non-interactive by design; the sandbox alone gates writes — read-only
    # for plan, workspace-write (edit files in the cwd) for build. No approval flag needed.
    sandbox = "workspace-write" if _is_build(agent) else "read-only"
    cmd = ["exec", "--sandbox", sandbox, "--skip-git-repo-check"]
    eff = {"minimal": "low", "low": "low", "medium": "medium",
           "high": "high", "max": "high"}.get(_effort(effort), "")
    if eff:
        cmd += ["-c", f"model_reasoning_effort={eff}"]
    if model:
        cmd += ["-m", model]
    return cmd + [task]


def _gemini_ask(task, model, effort, agent, bin=""):
    # Same lane serves Google `gemini` and Antigravity `agy` — they DIFFER: gemini takes -m
    # and auto-approves with --yolo; agy takes no -m and uses --dangerously-skip-permissions.
    # Now that the builder knows the bin, it emits the right flags for whichever is installed.
    is_agy = "agy" in (bin or "")
    cmd = []
    if model and not is_agy:
        cmd += ["-m", model]
    if _is_build(agent):
        cmd.append("--dangerously-skip-permissions" if is_agy else "--yolo")
    return cmd + ["-p", task]


def _mistral_ask(task, model, effort, agent, bin=""):
    # vibe: prompt before --agent; --trust skips the per-dir trust prompt. accept-edits agent
    # auto-applies edits for build; plan stays read-only. Model isn't a flag — see _mistral_env.
    ag = "accept-edits" if _is_build(agent) else "plan"
    return ["-p", task, "--agent", ag, "--trust"]


def _mistral_env(model, effort="", agent=""):
    # vibe has no --model flag; it reads the active model from VIBE_ACTIVE_MODEL. So a per-call
    # model= is honoured by setting that env for this spawn only (empty = vibe's own default).
    return {"VIBE_ACTIVE_MODEL": model.strip()} if (model or "").strip() else {}


def _opencode_ask(task, model, effort, agent, bin=""):
    ag = (agent or "plan").strip() or "plan"
    cmd = ["run", "--agent", ag, "-m", model]      # model always set (free default upstream)
    var = {"minimal": "minimal", "low": "minimal", "medium": "high",
           "high": "high", "max": "max"}.get(_effort(effort), "")
    if var:
        cmd += ["--variant", var]
    if ag != "plan":                                # only a write agent auto-approves
        cmd.append("--dangerously-skip-permissions")
    return cmd + [task]


def _qwen_ask(task, model, effort, agent, bin=""):  # Qwen Code is a gemini-cli fork (--yolo)
    cmd = []
    if model:
        cmd += ["-m", model]
    if _is_build(agent):
        cmd.append("--yolo")
    return cmd + ["-p", task]


def _copilot_ask(task, model, effort, agent, bin=""):  # GitHub Copilot CLI (best-effort flags)
    cmd = []
    if model:
        cmd += ["--model", model]
    if _is_build(agent):
        cmd.append("--allow-all-tools")
    return cmd + ["-p", task]


def _grok_ask(task, model, effort, agent, bin=""):  # xAI Grok CLI (experimental)
    # `-p` is the documented headless flag (xAI docs, June 2026). No hardcoded model: empty
    # model = the CLI's own default; `--model` is best-effort (unverified — `doctor deep`
    # checks the flags against `grok --help` and warns on drift rather than failing silently).
    # Build/write flag is unknown, so build falls back to default mode until verified live.
    cmd = []
    if model:
        cmd += ["--model", model]
    return cmd + ["-p", task]


def _ollama_ask(task, model, effort, agent, bin=""):  # local models via the ollama CLI
    # ollama has no effort/agent knobs and never edits files (read-only). `--hidethinking` is
    # REQUIRED: real ollama models are thinking models, so without it stdout carries the whole
    # chain of thought before the answer. It's a harmless no-op on a non-thinking model.
    return ["run", "--hidethinking", model, task]


def _ollama_env(model="", effort="", agent=""):
    # ollama writes ANSI cursor-control codes to STDOUT even when redirected to a file (it
    # rewrites the line for word-wrap), which corrupts the captured answer. NO_COLOR + a dumb
    # TERM make it emit the plain response. Applied to every ollama spawn via LaneSpec.env_ask.
    return {"NO_COLOR": "1", "TERM": "dumb"}


# opencode's bare default can resolve to a PAID model, so we pick a free one. The pick is
# DISCOVERED live and chosen by PATTERN, never by a hardcoded model id — the "best free" model
# churns and any pinned name eventually 404s (the whole reason this is dynamic). The seed below
# is a LAST RESORT used only if `opencode models` itself fails; override it with
# CLI_BRIDGE_OPENCODE_MODEL if it ever ages out before you update.
_OPENCODE_FREE_SEED = "opencode/deepseek-v4-flash-free"
_OPENCODE_MODELS_TIMEOUT_S = 5


def _opencode_default_model(bin_name: str) -> str:
    return _current_opencode_free_model(bin_name) or _OPENCODE_FREE_SEED


# TTL cache instead of @lru_cache: lru_cache would memoize a "no free model" result forever,
# so installing opencode (or a new free model appearing) after the first probe would never be
# picked up. A short TTL re-probes periodically; a positive result is cached longer.
_OPENCODE_MODEL_TTL_S = 300
_opencode_model_cache: dict[str, tuple[float, str]] = {}


def _current_opencode_free_model(bin_name: str) -> str:
    import time
    now = time.time()
    hit = _opencode_model_cache.get(bin_name)
    if hit and now - hit[0] < _OPENCODE_MODEL_TTL_S:
        return hit[1]
    try:
        timeout = int(os.environ.get("CLI_BRIDGE_OPENCODE_MODELS_TIMEOUT", "").strip()
                      or _OPENCODE_MODELS_TIMEOUT_S)
    except ValueError:
        timeout = _OPENCODE_MODELS_TIMEOUT_S
    try:
        proc = subprocess.run([bin_name, "models"], capture_output=True, text=True,
                              timeout=max(1, timeout), check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""  # transient failure: don't cache, re-probe next call
    if proc.returncode != 0:
        return ""
    models = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    # Cost-safety: ONLY the `-free` Zen tier is $0. A bare `opencode/<model>` (Zen) bills
    # per-token at API cost, and `opencode-go/*` spends prepaid credits — neither is a safe
    # DEFAULT. So an empty model resolves only to a `-free` model, never silently to a paid one.
    # De-pinned + future-proof: pick by PATTERN (any `-free`), sorted for a stable choice — so a
    # retired free model is replaced by whatever `-free` model exists THEN, with no code change.
    free = sorted(m for m in models if m.startswith("opencode/") and m.endswith("-free"))
    result = free[0] if free else ""
    _opencode_model_cache[bin_name] = (now, result)
    return result


# ollama requires a model arg (`ollama run <model>`), so an empty model must resolve to one that
# is actually pulled. Mirror the opencode probe: DISCOVER live, never hardcode an id. A short TTL
# picks up a freshly `ollama pull`ed model; "" on failure re-probes next call.
_OLLAMA_MODEL_TTL_S = 300
_ollama_model_cache: dict[str, tuple[float, str]] = {}


def _current_ollama_model(bin_name: str) -> str:
    import time
    now = time.time()
    hit = _ollama_model_cache.get(bin_name)
    if hit and now - hit[0] < _OLLAMA_MODEL_TTL_S:
        return hit[1]
    try:
        proc = subprocess.run([bin_name, "list"], capture_output=True, text=True,
                              timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""  # transient failure: don't cache, re-probe next call
    if proc.returncode != 0:
        return ""
    rows = [line for line in proc.stdout.splitlines() if line.strip()]
    # The first row is the header (NAME ID SIZE MODIFIED). Skip it UNCONDITIONALLY rather than
    # matching the literal header text — ollama may localize or reorder columns. Take the first
    # column (model name) of the first model row.
    models = rows[1:]
    result = models[0].split()[0] if models else ""
    _ollama_model_cache[bin_name] = (now, result)
    return result


# Cost facts (cost_default / cost_note / docs/COSTS.md) were last verified against vendor
# pages on this date. This landscape churns in WEEKS (a free tier died in 48h in Apr 2026),
# so `doctor` warns when the snapshot goes stale instead of letting old facts pose as current.
COST_FACTS_VERIFIED = "2026-06-04"
_COST_FACTS_STALE_DAYS = 90


def cost_facts_age_days(today=None) -> int:
    """Days since the cost facts were verified. `today` injectable for tests."""
    from datetime import date
    if today is None:
        today = date.today()
    return (today - date.fromisoformat(COST_FACTS_VERIFIED)).days


def cost_facts_stale(today=None) -> bool:
    return cost_facts_age_days(today) > _COST_FACTS_STALE_DAYS


# Cost defaults are SOURCED from each vendor's published plans (docs/COSTS.md, verified
# June 2026) — they describe a TYPICAL plan, they are never detected from the user's account.
# Out-of-the-box `ask_all` builds a real free council and never burns subscription quota or
# money unasked. Subscription CLIs default to "limited" (direct asks still work; skipped by
# broad fan-out). The user overrides any of these per their own plan with
# CLI_BRIDGE_<LANE>_COST / _PROFILE=max.
BUILTIN_LANES: list[LaneSpec] = [
    LaneSpec("claude", "Claude (Claude Code CLI)", "claude", _claude_ask,
             cost_default="limited",
             cost_note="Pro/Max plans share ONE quota bucket across chat+Code; hard stop at the "
                       "limit (opt-in extra API credits exist). Official-CLI scripting is "
                       "ToS-permitted.",
             models_args=None, help_args=["--help"], caps=frozenset({"model", "agent"}),
             probe_flags=("--print", "--permission-mode"),
             client_ids=frozenset({"claude-code", "claude", "claude-desktop"}),
             install_hint="npm i -g @anthropic-ai/claude-code  (then `claude` to log in)",
             native_session={"mode": "mint",                       # verified live 2026-06-12
                             "first": ["--session-id", "{sid}"],
                             "resume": ["--resume", "{sid}"]},
             note="Anthropic. Strong all-round reasoning. model=claude-opus-4-6/claude-sonnet-4-6 "
                  "etc; agent='build' EDITS files (acceptEdits). Default plan = read-only."),
    LaneSpec("gpt", "GPT (OpenAI Codex CLI)", "codex", _codex_ask,
             cost_default="limited",
             cost_note="Codex is included on ALL ChatGPT plans (even Free) with plan-scaled "
                       "quotas from a shared agentic pool — many users have it at no extra cost.",
             help_args=["exec", "--help"], caps=frozenset({"model", "effort", "agent"}),
             probe_flags=("--sandbox", "-m"),
             client_ids=frozenset({"codex", "codex-mcp-client", "codex-cli"}),
             install_hint="npm i -g @openai/codex  (then `codex` to log in)",
             note="OpenAI. effort=high for hard reasoning, low/empty for quick; agent='build' "
                  "EDITS files (sandbox workspace-write). Default plan = read-only."),
    LaneSpec("gemini", "Gemini (Google Gemini CLI / Antigravity)", "gemini", _gemini_ask,
             cost_default="free",
             cost_note="⚠ Gemini CLI's free personal tier (60 req/min, 1000 req/day) ENDS "
                       "2026-06-18 (official sunset) — migrate to Antigravity (`agy`); this lane "
                       "falls back to `agy` automatically when installed.",
             help_args=["--help"], caps=frozenset({"model", "agent"}), bin_alts=("agy",),
             sunset="2026-06-18",   # free personal tier dies; past this, prefer agy + degrade cost
             probe_flags=("-p",),   # common to gemini & agy; -m differs by binary, so not probed
             client_ids=frozenset({"gemini-cli-mcp-client", "gemini", "antigravity"}),
             install_hint="npm i -g @google/gemini-cli  (free tier; then log in)",
             note="Google. Fast, broad, multimodal/web. Uses `gemini`, or falls back to `agy` "
                  "(Antigravity) if installed. agent='build' EDITS files (--yolo / agy "
                  "--dangerously-skip-permissions). Note: `agy` ignores model (uses its own)."),
    LaneSpec("mistral", "Mistral (Vibe CLI)", "vibe", _mistral_ask,
             cost_default="limited",
             cost_note="Conservative default — the free tier works but its quotas are unverified and "
                       "Mistral sells paid plans (docs/COSTS.md); set to free if you're on the free tier.",
             help_args=["--help"], caps=frozenset({"model", "agent"}), env_ask=_mistral_env,
             probe_flags=("-p", "--agent", "--trust"),
             client_ids=frozenset({"vibe", "mistral"}),
             install_hint="see Mistral Vibe CLI docs (`vibe`)",
             note="Mistral (Vibe CLI). Lightweight quick takes. model=<id> selects via "
                  "VIBE_ACTIVE_MODEL (e.g. a devstral coding model, if your vibe exposes it); "
                  "empty = vibe's default. agent='build' EDITS files. Default plan = read-only."),
    LaneSpec("opencode", "OpenCode (gateway to many models)", "opencode", _opencode_ask,
             cost_default="free", default_model=_OPENCODE_FREE_SEED,
             cost_note="'opencode/*-free' = $0 but the model may TRAIN on your prompts during "
                       "its free period; bare 'opencode/*' (Zen) bills per token; "
                       "'opencode-go/*' spends subscription credits ($10/mo plan with caps).",
             models_args=["models"], help_args=["run", "--help"],
             caps=frozenset({"model", "effort", "agent"}),
             probe_flags=("--agent", "-m"),
             client_ids=frozenset({"opencode"}),
             install_hint="curl -fsSL https://opencode.ai/install | bash",
             native_session={"mode": "capture",                    # verified live 2026-06-12
                             "spawn": ["--print-logs"],            # logs (stderr) name the session
                             "pattern": r"ses_[A-Za-z0-9]{10,}",
                             "resume": ["-s", "{sid}"]},
             note=("Gateway to deepseek/qwen/glm/kimi/minimax/... Empty model = a discovered "
                   "'opencode/*-free' model ($0, rate-limited; may train on your data during its "
                   "free period). PAID otherwise: a bare 'opencode/*' Zen model bills per-token "
                   "(API cost), 'opencode-go/*' spends prepaid credits — pass those only when the "
                   "task earns it. agent='build' EDITS files (default 'plan' is read-only).")),
    LaneSpec("qwen", "Qwen (Qwen Code CLI)", "qwen", _qwen_ask,
             cost_default="paid",
             cost_note="Free OAuth tier DISCONTINUED 2026-04-15 — needs a metered API key "
                       "(e.g. OpenRouter/BYOK). ⚠ Alibaba's Coding Plan ToS prohibits "
                       "non-interactive use, so that plan is NOT a valid path for cli-bridge.",
             help_args=["--help"], caps=frozenset({"model", "agent"}),
             probe_flags=("-p",),
             client_ids=frozenset({"qwen", "qwen-code"}),
             experimental=True,
             install_hint="npm i -g @qwen-code/qwen-code  (needs a metered API key since Apr 2026)",
             note="Alibaba Qwen. Large context, strong code. agent='build' EDITS files (--yolo). "
                  "Flags assume a gemini-cli fork."),
    LaneSpec("copilot", "GitHub Copilot CLI", "copilot", _copilot_ask,
             cost_default="limited",
             cost_note="Copilot billing moved to usage-based credits on 2026-06-01 — quota "
                       "exhaustion can meter, not hard-stop.",
             help_args=["--help"], caps=frozenset({"model", "agent"}),
             probe_flags=("-p",),
             client_ids=frozenset({"copilot", "github-copilot"}),
             experimental=True,
             install_hint="gh extension install github/gh-copilot  (subscription)",
             note="GitHub Copilot. agent='build' EDITS files (--allow-all-tools). Flags verified vs "
                  "GitHub docs 2026-06 (-p/--model/--allow-all-tools), not run live by the suite; if "
                  "your install is `gh copilot`, set CLI_BRIDGE_COPILOT_BIN and a custom lane."),
    LaneSpec("grok", "Grok (xAI CLI)", "grok", _grok_ask,
             cost_default="limited",
             cost_note="Requires a SuperGrok / X Premium+ subscription (no free CLI tier as of "
                       "June 2026); headless via `-p`.",
             help_args=["--help"], caps=frozenset({"model"}),
             probe_flags=("-p",),
             client_ids=frozenset({"grok", "grok-cli", "xai"}),
             experimental=True,
             install_hint="curl -fsSL https://x.ai/cli/install.sh | bash",
             note="xAI Grok. Fast, web-aware, strong reasoning. No model hardcoded (empty = the "
                  "CLI's own default; pass model=<id> to pick one). `--model` best-effort and "
                  "experimental — run `doctor deep` to check flags against `grok --help`."),
    LaneSpec("ollama", "Ollama (local models)", "ollama", _ollama_ask,
             cost_default="free",
             cost_note="local models — $0, on your machine, private/offline (no network calls).",
             models_args=["list"], help_args=["run", "--help"],
             caps=frozenset({"model"}), env_ask=_ollama_env,
             probe_flags=("--hidethinking",),
             client_ids=frozenset({"ollama"}),
             install_hint="macOS: brew install ollama · Linux: curl -fsSL "
                          "https://ollama.com/install.sh | sh ; then `ollama pull <model>`",
             note="Local via ollama. $0, private, offline. Read-only (no build). Empty model = the "
                  "first model from `ollama list`. Max decorrelation for the jury — but note a "
                  "local runtime of open weights still correlates with OTHER local runtimes of the "
                  "same weights; real jury diversity comes from distinct vendors."),
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
    def build(task, model, effort, agent, bin=""):
        out: list[str] = []
        if model_flag and model:
            out += [model_flag, model]
        for part in ask_tmpl:
            out.append(_expand(part, task, model))
        return out
    return build


# Last custom-lanes load status, so `doctor` can surface a broken file instead of staying silent.
# argv_secret_risk lists lanes whose template would expand a ${SECRET} into a credential-bearing
# argv part (visible in `ps` for the duration of the call) — doctor warns with the safe pattern.
LANES_LOAD_STATUS: dict = {"path": "", "loaded": 0, "skipped": 0, "error": "",
                           "argv_secret_risk": []}

# A template arg is argv-secret-risky when it BOTH expands an env var and looks like it carries a
# credential. The safe pattern keeps the secret out of argv entirely: curl ≥ 8.3's
#   --variable %MY_KEY --expand-header "Authorization: Bearer {{MY_KEY}}"
# imports the env var INSIDE curl — `ps` only ever shows the variable's NAME.
_CRED_HINT = __import__("re").compile(
    r"(?i)authorization|bearer|api[-_]?key|x-api-key|token|secret")


def argv_secret_risk(ask_tmpl: list[str]) -> bool:
    """True when this ask template would put an expanded ${ENV} secret into argv."""
    return any("${" in part and _CRED_HINT.search(part) for part in ask_tmpl)

_RESERVED_KEYS = {"all", "doctor", "setup"}


def _str_list(value) -> list[str] | None:
    """Accept only a real list of strings (a bare string would become a list of chars)."""
    if isinstance(value, list) and all(isinstance(p, str) for p in value) and value:
        return list(value)
    return None


def _valid_key(key: str) -> bool:
    return bool(key) and key not in _RESERVED_KEYS and key.replace("_", "").replace("-", "").isalnum()


def load_custom_lanes(path: str | None = None) -> list[LaneSpec]:
    path = path or os.environ.get("CLI_BRIDGE_LANES_FILE", "").strip()
    LANES_LOAD_STATUS.update({"path": path, "loaded": 0, "skipped": 0, "error": "",
                              "argv_secret_risk": []})
    if not path:
        return []
    if not os.path.isfile(path):
        LANES_LOAD_STATUS["error"] = "file not found"
        return []
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except OSError as e:
        LANES_LOAD_STATUS["error"] = f"cannot read file: {e}"
        return []
    except ValueError as e:
        LANES_LOAD_STATUS["error"] = f"invalid JSON: {e}"
        return []
    if not isinstance(data, list):
        LANES_LOAD_STATUS["error"] = "top-level JSON must be a list of lane objects"
        return []

    lanes: list[LaneSpec] = []
    skipped = 0
    for item in data:
        key = str(item.get("key", "")).strip() if isinstance(item, dict) else ""
        ask = _str_list(item.get("ask")) if isinstance(item, dict) else None
        if not isinstance(item, dict) or not _valid_key(key) or ask is None:
            skipped += 1
            continue
        # cost: explicit field, else legacy paid bool
        cost = str(item.get("cost", "")).strip().lower()
        if cost not in {"free", "limited", "paid"}:
            cost = "paid" if bool(item.get("paid", False)) else "free"
        model_flag = str(item.get("model_flag", "")).strip()
        # Derive the drift-check flags from the template itself: the model flag + any dash-args
        # in the ask template (e.g. a subcommand flag). So custom lanes get the same `doctor deep`
        # breakage warning as built-ins, with no extra config.
        probe = tuple(dict.fromkeys(
            ([model_flag] if model_flag else []) + [t for t in ask if t.startswith("-")]))
        if argv_secret_risk(ask):
            LANES_LOAD_STATUS["argv_secret_risk"].append(key)
        lanes.append(LaneSpec(
            key=key,
            display=str(item.get("display", key)),
            bin_default=str(item.get("bin", key)),
            build_ask=_template_builder(ask, model_flag),
            cost_default=cost,
            default_model=str(item.get("default_model", "")),
            models_args=_str_list(item.get("models")),
            help_args=_str_list(item.get("help")),
            probe_flags=probe,
            caps=frozenset({"model"}) if model_flag else frozenset(),
            client_ids=frozenset(c for c in item.get("client_ids", []) if isinstance(c, str)),
            experimental=bool(item.get("experimental", False)),
            install_hint=str(item.get("install_hint", "")),
            note=str(item.get("note", "user-defined lane")),
        ))
    LANES_LOAD_STATUS.update({"loaded": len(lanes), "skipped": skipped})
    return lanes


def is_paid_opencode_model(model: str) -> bool:
    """True when an opencode model id spends money/credits: `opencode-go/*` burns prepaid Go
    credits, and a bare `opencode/*` Zen model without the `-free` suffix bills per token. Used to
    catch a FREE-labeled opencode lane that's been pointed (via env/config) at a paid model — the
    cost-safety hole the council's challenge surfaced (a free tier can't bill, but a free *label*
    on a paid *model* can). Pure."""
    m = (model or "").strip()
    if m.startswith("opencode-go/"):
        return True
    return m.startswith("opencode/") and not m.endswith("-free")


def missing_flags(help_text: str, probe_flags) -> list[str]:
    """Which of a lane's required flags are ABSENT from its CLI help text — i.e. likely removed or
    renamed upstream, so the lane's invocation would break. Plain substring match (a flag like
    `-m` / `--sandbox` appears verbatim in help). Empty help or no probe_flags -> [] (can't tell,
    so never a false alarm). Pure + offline-testable; the live `--help` spawn lives in the server."""
    if not probe_flags or not help_text:
        return []
    return [f for f in probe_flags if f not in help_text]


def all_lanes() -> list[LaneSpec]:
    """Built-ins plus any user-defined lanes. A custom lane with an existing key overrides."""
    by_key = {lane.key: lane for lane in BUILTIN_LANES}
    for lane in load_custom_lanes():
        by_key[lane.key] = lane
    return list(by_key.values())
