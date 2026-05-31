"""Configuration: env parsing, cost profile, timeouts, onboarding text.

Kept separate from server.py so the MCP surface stays thin and the same knobs are reusable
by the (future) human CLI. Everything is environment-driven — no config file, no machine
state — so the server behaves identically on any host once the user sets their env.
"""
from __future__ import annotations

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


def int_env(name: str, default: int, lo: int, hi: int) -> int:
    """Parse an int env var without ever crashing the server at import on a bad value."""
    try:
        return max(lo, min(int(os.environ.get(name, "").strip() or default), hi))
    except (TypeError, ValueError):
        return default


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
