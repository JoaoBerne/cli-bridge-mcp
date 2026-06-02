"""Configuration: env parsing, cost profile, timeouts, onboarding text.

Kept separate from server.py so the MCP surface stays thin and the same knobs are reusable
by the (future) human CLI. Everything is environment-driven — no config file, no machine
state — so the server behaves identically on any host once the user sets their env.
"""
from __future__ import annotations

import json
import os
import tempfile

# ── timeouts ──────────────────────────────────────────────────────────────────────────
DEFAULT_TIMEOUT_S = 120
MAX_TIMEOUT_S = 900
# ask_all keeps per-lane calls short so the whole fan-out returns before the MCP host's own
# tool-call deadline. For a slow/deep answer, call a single lane directly with a big timeout.
ASK_ALL_DEFAULT_TIMEOUT_S = 45
ASK_ALL_MAX_TIMEOUT_S = 60
ASK_ALL_SYNTH_TIMEOUT_S = 45


# ── optional JSON config file (a friendlier alternative to a wall of env vars) ──────────────
# Loaded ONCE at startup (server/CLI main) and used to fill in any CLI_BRIDGE_* var not already
# set in the environment — so the environment ALWAYS wins, and nothing is read at import (tests,
# which never call main(), are unaffected). Friendly schema:
#   {"profile":"max","terse":"lite","guard":"strict","max_parallel":6,"daily_credit_cap":5,
#    "lanes":{"gemini":{"cost":"free","model":"…","enabled":true,"credits_per_1k":0,"daily_limit":100}}}
# Top-level keys already named CLI_BRIDGE_* are passed through verbatim (escape hatch).
_TOP_KEYS = {
    "profile": "CLI_BRIDGE_PROFILE", "terse": "CLI_BRIDGE_TERSE", "guard": "CLI_BRIDGE_GUARD",
    "max_parallel": "CLI_BRIDGE_MAX_PARALLEL", "daily_credit_cap": "CLI_BRIDGE_DAILY_CREDIT_CAP",
    "cache_ttl_s": "CLI_BRIDGE_CACHE_TTL_S", "retries": "CLI_BRIDGE_RETRIES",
    "allow_lanes": "CLI_BRIDGE_ALLOW_LANES", "terse_min_chars": "CLI_BRIDGE_TERSE_MIN_CHARS",
}
_LANE_KEYS = {
    "cost": "COST", "model": "MODEL", "enabled": "ENABLED", "bin": "BIN",
    "credits_per_1k": "CREDITS_PER_1K", "daily_limit": "DAILY_LIMIT", "priority": "PRIORITY",
}


def config_file_path() -> str:
    return os.environ.get("CLI_BRIDGE_CONFIG_FILE", "").strip() \
        or os.path.join(os.path.expanduser("~"), ".config", "cli-bridge", "config.json")


def _flatten_config(cfg: dict) -> dict:
    out: dict[str, str] = {}
    if not isinstance(cfg, dict):
        return out
    for k, v in cfg.items():
        if k.startswith("CLI_BRIDGE_"):
            out[k] = str(v)
        elif k in _TOP_KEYS and not isinstance(v, (dict, list)):
            out[_TOP_KEYS[k]] = "true" if v is True else ("false" if v is False else str(v))
        elif k == "lanes" and isinstance(v, dict):
            for lane, fields in v.items():
                if not isinstance(fields, dict):
                    continue
                for fk, fv in fields.items():
                    suffix = _LANE_KEYS.get(fk)
                    if suffix:
                        out[f"CLI_BRIDGE_{lane.upper()}_{suffix}"] = (
                            "true" if fv is True else ("false" if fv is False else str(fv)))
    return out


def apply_file_config_to_env() -> int:
    """Fill any unset CLI_BRIDGE_* var from the JSON config file. Env wins (setdefault). Returns
    the number of keys applied. Best-effort: a missing/invalid file is silently ignored."""
    try:
        with open(config_file_path(), encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError):
        return 0
    applied = 0
    for env_name, value in _flatten_config(cfg).items():
        if env_name not in os.environ:
            os.environ[env_name] = value
            applied += 1
    return applied


def int_env(name: str, default: int, lo: int, hi: int) -> int:
    """Parse an int env var without ever crashing the server at import on a bad value."""
    try:
        return max(lo, min(int(os.environ.get(name, "").strip() or default), hi))
    except (TypeError, ValueError):
        return default


# Response cache: 0 = OFF (default). When >0, an identical delegate call (same lane, model,
# effort, agent, cwd, terse level, task) within this many seconds returns the stored answer
# instead of re-spawning the CLI — saves quota/credits on repeats. Opt-in because a cached
# answer can be stale. Stored in the local telemetry DB (needs telemetry on, the default).
CACHE_TTL_S = int_env("CLI_BRIDGE_CACHE_TTL_S", 0, 0, 31_536_000)  # max 1 year


# Crude token estimate: chars / CHARS_PER_TOKEN. Always surfaced as "estimated" — we never
# pretend to know a provider's real tokenization or pricing.
CHARS_PER_TOKEN = 4


def lane_env(lane_key: str, suffix: str) -> str:
    """Read a per-lane env var, e.g. lane_env('gpt','DAILY_LIMIT') -> CLI_BRIDGE_GPT_DAILY_LIMIT."""
    return os.environ.get(f"CLI_BRIDGE_{lane_key.upper()}_{suffix}", "").strip()


def lane_env_float(lane_key: str, suffix: str) -> float | None:
    try:
        return float(lane_env(lane_key, suffix))
    except ValueError:
        return None


def lane_env_int(lane_key: str, suffix: str) -> int | None:
    try:
        return int(lane_env(lane_key, suffix))
    except ValueError:
        return None


def daily_credit_cap() -> float:
    """Hard ceiling on ESTIMATED paid spend per UTC day. 0 = off (default). When >0, a paid lane
    is refused once today's estimated credits reach the cap — makes 'cost-safe' enforceable, not
    just reported."""
    try:
        return max(0.0, float(os.environ.get("CLI_BRIDGE_DAILY_CREDIT_CAP", "").strip() or 0))
    except ValueError:
        return 0.0


def allowed_lanes() -> set[str]:
    """Optional allowlist (CLI_BRIDGE_ALLOW_LANES=gemini,gpt). Empty = all. For locked-down /
    team setups: only these lane keys are exposed/usable."""
    raw = os.environ.get("CLI_BRIDGE_ALLOW_LANES", "").strip()
    return {p.strip() for p in raw.split(",") if p.strip()} if raw else set()


def build_disabled() -> bool:
    """CLI_BRIDGE_DISABLE_BUILD=1 forces every delegate to read-only (plan), even if a caller
    asks agent='build'. For shared/team machines where no delegate should edit files."""
    return os.environ.get("CLI_BRIDGE_DISABLE_BUILD", "").strip().lower() in {"1", "true", "yes", "on"}


def max_parallel() -> int:
    """Cap on simultaneous delegate spawns in a fan-out (ask_all). Default 6 — high enough that
    a normal free council never hits it, low enough that many custom lanes can't OOM a small
    machine or burst quota. Clamped 1..64."""
    return int_env("CLI_BRIDGE_MAX_PARALLEL", 6, 1, 64)


def mock() -> bool:
    """Dry-run mode: lanes are reported installed and return a canned answer WITHOUT spawning any
    CLI. Lets someone try cli-bridge (routing, fan-out, workflows) with zero CLIs installed."""
    return os.environ.get("CLI_BRIDGE_MOCK", "").strip().lower() in {"1", "true", "yes", "on"}


def retries() -> int:
    """How many times to retry a delegate on a TRANSIENT failure (default 1). Makes a flaky CLI
    'work the first time' from the caller's view. Quota/auth/not_found/timeout are never retried."""
    return int_env("CLI_BRIDGE_RETRIES", 1, 0, 5)


def trace_dir() -> str:
    """If set, every delegation writes a redacted JSON trace (argv, timing, output) here — a
    reproducible, ban-safe audit artifact. Empty = off."""
    return os.environ.get("CLI_BRIDGE_TRACE_DIR", "").strip()


def terse_min_chars() -> int:
    """Skip the terse preamble for tasks shorter than this many chars (0 = never skip, the
    default). A tiny task produces a tiny answer, so the preamble's fixed input overhead
    would outweigh the output it compresses. Read live (not a module constant) so it stays
    runtime-configurable, matching preamble.level()."""
    return int_env("CLI_BRIDGE_TERSE_MIN_CHARS", 0, 0, 100_000)


# review_diff is a deliberately heavier workflow (each reviewer reads a whole diff, then a
# merge pass). Reviewers run in parallel, so wall time ≈ slowest reviewer + merge — longer
# than ask_all on purpose. Per-stage default; clamped to MAX_TIMEOUT_S like a direct ask.
REVIEW_DEFAULT_TIMEOUT_S = int_env("CLI_BRIDGE_REVIEW_TIMEOUT_S", 180, 1, MAX_TIMEOUT_S)
# Largest diff (chars) fed into a review prompt; bigger diffs are truncated with a note so the
# prompt stays within model context instead of erroring or getting silently dropped.
REVIEW_DIFF_MAX_CHARS = int_env("CLI_BRIDGE_REVIEW_DIFF_MAX_CHARS", 60000, 2000, 1_000_000)


# ── subagent-style overflow ───────────────────────────────────────────────────────────
INLINE_MAX_CHARS = int_env("CLI_BRIDGE_INLINE_MAX_CHARS", 12000, 500, 1_000_000)
OVERFLOW_DIR = os.environ.get("CLI_BRIDGE_OVERFLOW_DIR", "").strip() \
    or os.path.join(tempfile.gettempdir(), "cli-bridge-overflow")

# ── local state (telemetry / cooldown) ────────────────────────────────────────────────
def state_db_path() -> str:
    override = os.environ.get("CLI_BRIDGE_STATE_DB", "").strip()
    if override:
        return override
    base = os.environ.get("XDG_DATA_HOME", "").strip() \
        or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "cli-bridge", "state.sqlite")


def telemetry_enabled() -> bool:
    return os.environ.get("CLI_BRIDGE_TELEMETRY", "").strip().lower() not in {"0", "false", "off", "no"}


# Cooldown policy (seconds) after repeated failures of a given kind.
COOLDOWN_TIMEOUT_S = int_env("CLI_BRIDGE_COOLDOWN_TIMEOUT_S", 900, 0, 86_400)   # 15 min
COOLDOWN_QUOTA_S = int_env("CLI_BRIDGE_COOLDOWN_QUOTA_S", 3600, 0, 86_400)      # 1 h
COOLDOWN_AUTH_S = int_env("CLI_BRIDGE_COOLDOWN_AUTH_S", 1800, 0, 86_400)        # 30 min
COOLDOWN_TIMEOUT_THRESHOLD = 2   # consecutive timeouts before a lane is cooled


# ── cost profile ──────────────────────────────────────────────────────────────────────
# There is no universal "free is best" — someone on a big plan may want top models by
# default. Unset => balanced, but the server's instructions tell the host to ASK on first use.
#   saver    = free lanes only; never spend credits or scarce quota unless explicitly told.
#   balanced = free by default; limited/paid lanes need explicit include_paid.
#   max      = quality first; ask_all includes free, limited, and paid lanes.
VALID_PROFILES = ("saver", "balanced", "max")


def profile() -> str:
    p = os.environ.get("CLI_BRIDGE_PROFILE", "").strip().lower()
    return p if p in VALID_PROFILES else "balanced"


def profile_is_set() -> bool:
    return os.environ.get("CLI_BRIDGE_PROFILE", "").strip().lower() in VALID_PROFILES


def cost_config_is_set() -> bool:
    """The user expressed cost intent if they set a profile OR any per-lane COST."""
    if profile_is_set():
        return True
    return any(k.startswith("CLI_BRIDGE_") and k.endswith("_COST") and v.strip()
               for k, v in os.environ.items())


# ── onboarding text (shown via the MCP `instructions` + `setup` tool) ──────────────────
SETUP_TEXT = (
    "Help the user configure cli-bridge to THEIR situation. Don't impose a preset — every "
    "person's plans differ (one may have unlimited Gemini but metered opencode credits, "
    "another a tight GPT quota). Have a short conversation:\n\n"
    "1. Run `doctor` first to see which CLIs they actually have installed.\n"
    "2. For EACH installed lane, ask what it costs THEM and how freely to use it — e.g. "
    "\"is your opencode on paid credits or a flat plan?\", \"do you mind me spending GPT quota "
    "on big tasks?\". Listen to their actual answer; don't assume free=best.\n"
    "3. Translate their answers into config (env vars on the MCP server entry, or just honour "
    "them for this session):\n"
    "     CLI_BRIDGE_<LANE>_COST = free | limited | paid\n"
    "          free=use freely in ask_all; limited=scarce quota, direct calls OK but skip "
    "ask_all by default; paid=money/credits\n"
    "     CLI_BRIDGE_<LANE>_ENABLED = false       (hide a lane they don't want used)\n"
    "     CLI_BRIDGE_<LANE>_MODEL = <id>          (their preferred default model for a lane)\n"
    "     CLI_BRIDGE_PROFILE = saver|balanced|max (optional shorthand if they'd rather not "
    "go lane-by-lane: saver=free only, balanced=paid when it earns it, max=best by default)\n"
    "4. Confirm back what you understood. The user stays in control — this just sets your "
    "default behaviour so they don't have to repeat it each call."
)

INSTRUCTIONS = (
    "cli-bridge lets you consult other AI CLIs (Gemini, GPT, Mistral, opencode, …) as a "
    "council. Each lane spawns the official CLI (ban-safe, no key extraction), read-only by "
    "default.\n\n"
    "FIRST RUN — understand the user's cost situation: if their preferences aren't configured "
    "(no CLI_BRIDGE_PROFILE / per-lane COST set), call `setup` and have a brief conversation "
    "to learn what each CLI costs THEM and how freely to use it. Do NOT assume 'free is best' "
    "— someone on a big plan may want top models by default; someone on metered credits won't. "
    "Configure to their actual answer.\n\n"
    "Then: `ask_<lane>` for one model, `ask_all` to poll several in parallel, `ask_cascade` to "
    "auto-fall-back on failure, `doctor` to see what's installed and the current cost/quota "
    "stance."
)
