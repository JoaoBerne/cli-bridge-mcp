"""Configuration: env parsing, cost profile, timeouts, onboarding text.

Kept separate from server.py so the MCP surface stays thin and the same knobs are reusable
by the human CLI. Env-first: every knob is a CLI_BRIDGE_* variable, optionally filled in at
startup from a JSON config file (~/.config/cli-bridge/config.json — env always wins), which
is also where the host persists cost facts it learns via set_lane_cost (update_config_file).
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
    "cost_note": "COST_NOTE", "min_interval_s": "MIN_INTERVAL_S",
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
                        # '-' → '_': env names can't carry hyphens, and LaneSpec._env reads
                        # CLI_BRIDGE_MY_LANE_COST for a 'my-lane' key — must match it here or
                        # persisted settings for hyphenated custom lanes are silently lost.
                        env_lane = lane.upper().replace("-", "_")
                        out[f"CLI_BRIDGE_{env_lane}_{suffix}"] = (
                            "true" if fv is True else ("false" if fv is False else str(fv)))
    return out


# CLI_BRIDGE_* names that were ALREADY in the environment when the config file was applied —
# i.e. set by the MCP host's config / shell, not by the file. Those shadow the file on every
# restart (env wins), which set_lane_cost uses to warn that its persisted value won't stick.
ENV_PRESET_KEYS: set[str] = set()


def apply_file_config_to_env() -> int:
    """Fill any unset CLI_BRIDGE_* var from the JSON config file. Env wins (setdefault). Returns
    the number of keys applied. Best-effort: a missing/invalid file is silently ignored."""
    ENV_PRESET_KEYS.clear()
    ENV_PRESET_KEYS.update(k for k in os.environ if k.startswith("CLI_BRIDGE_"))
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


def update_config_file(lane_updates: dict) -> str:
    """Merge {lane: {field: value}} into the config file's `lanes` section and write it back —
    how the HOST persists cost facts it learns (set_lane_cost), so the policy evolves without
    anyone editing files. Creates the file/dir if absent; preserves everything else in the file.
    Returns the path written, or "" on failure (best-effort — caller reports, never raises)."""
    path = config_file_path()
    try:
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
        if not isinstance(cfg, dict):
            cfg = {}
    except (OSError, ValueError):
        cfg = {}
    lanes_cfg = cfg.get("lanes")
    if not isinstance(lanes_cfg, dict):
        lanes_cfg = cfg["lanes"] = {}
    for lane, fields in lane_updates.items():
        cur = lanes_cfg.get(lane)
        if not isinstance(cur, dict):
            cur = lanes_cfg[lane] = {}
        cur.update(fields)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
            fh.write("\n")
        return path
    except OSError:
        return ""


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


def _tool_set(var: str) -> set[str]:
    raw = os.environ.get(var, "").strip()
    return {t.strip().lower() for t in raw.split(",") if t.strip()}


def disabled_tools() -> set[str]:
    """Tool NAMES to hide from the listing (CLI_BRIDGE_DISABLED_TOOLS=debate,premortem,...).
    Trims the schema context every host pays per request — the 2026 consensus is 5-15 tools, with
    sharp degradation past ~20 (and ~33 here). Essential tools (doctor/setup) can't be hidden."""
    return _tool_set("CLI_BRIDGE_DISABLED_TOOLS")


def enabled_tools() -> set[str]:
    """Allowlist (CLI_BRIDGE_ENABLED_TOOLS=ask_best,ask_all,review_diff). When set, ONLY these
    (+ essentials + the ask_<lane> per installed lane if named) are exposed — a one-env 'lean
    mode'. Empty = expose everything not in the denylist."""
    return _tool_set("CLI_BRIDGE_ENABLED_TOOLS")


def lean() -> bool:
    """CLI_BRIDGE_LEAN=1 → expose only the curated 'core' surface (the daily-driver tools), the
    rest hidden behind this one opt-in. Honours an explicit ENABLED/DISABLED list if also set
    (that wins). Off by default — no host loses a tool unless it opts in."""
    return os.environ.get("CLI_BRIDGE_LEAN", "").strip().lower() in {"1", "true", "yes", "on"}


def hide_host() -> bool:
    """CLI_BRIDGE_HIDE_HOST=1 → hide the caller's OWN lane (legacy behaviour: ask_<host> is then
    only reachable as an explicit-model SIBLING consult). Off by default — the host's own lane is
    a normal, visible tool you can call directly. It still never joins ask_all/ask_cascade fan-out
    (asking your own running model in a parallel council is redundant)."""
    return os.environ.get("CLI_BRIDGE_HIDE_HOST", "").strip().lower() in {"1", "true", "yes", "on"}


def build_disabled() -> bool:
    """CLI_BRIDGE_DISABLE_BUILD=1 forces every delegate to read-only (plan), even if a caller
    asks agent='build'. For shared/team machines where no delegate should edit files."""
    return os.environ.get("CLI_BRIDGE_DISABLE_BUILD", "").strip().lower() in {"1", "true", "yes", "on"}


def strip_nesting_env() -> bool:
    """CLI_BRIDGE_STRIP_NESTING_ENV=1 → when spawning a delegate CLI, drop the HOST's own
    session-marker env vars (CLAUDE_*/CODEX_* by default). Some CLIs refuse to run as a "nested
    session" when they see their own markers — the symptom is EMPTY output when cli-bridge runs
    INSIDE Claude Code / Codex and spawns `claude` / `codex`. Opt-in, default OFF (consistent with
    HIDE_HOST / LEAN — flip the default on after a real soak). This is a FUNCTION fix, NOT
    credential isolation: auth tokens are deliberately kept (see strip_nesting) so the child can
    still authenticate."""
    return os.environ.get("CLI_BRIDGE_STRIP_NESTING_ENV", "").strip().lower() in {"1", "true", "yes", "on"}


def strip_prefixes() -> tuple[str, ...]:
    """Env-var name prefixes removed from a delegate's spawn env when strip_nesting_env() is on.
    Default 'CLAUDE_,CODEX_' — extend for other hosts (e.g. CLI_BRIDGE_STRIP_PREFIXES="GEMINI_"
    for a Gemini host, "GITHUB_" for Copilot) without a code change."""
    raw = os.environ.get("CLI_BRIDGE_STRIP_PREFIXES", "").strip() or "CLAUDE_,CODEX_"
    return tuple(p.strip() for p in raw.split(",") if p.strip())


# Kept even when they match a strip prefix: the child still needs to find binaries (PATH/HOME/…)
# and AUTHENTICATE. The guard removes SESSION MARKERS that trigger a nested-session refusal, never
# credentials — so any *_TOKEN / *_API_KEY (e.g. CLAUDE_CODE_OAUTH_TOKEN) and the basics survive.
_NESTING_KEEP = frozenset({"PATH", "HOME", "SHELL", "LANG", "TERM"})


def strip_nesting(env: dict[str, str]) -> dict[str, str]:
    """Return a COPY of `env` with host session-marker vars removed (prefix-matched via
    strip_prefixes()), but auth tokens and the basics always kept. Pure — testable without
    spawning anything."""
    prefixes = strip_prefixes()
    out: dict[str, str] = {}
    for k, v in env.items():
        if k in _NESTING_KEEP or k.endswith("_TOKEN") or k.endswith("_API_KEY"):
            out[k] = v
        elif any(k.startswith(p) for p in prefixes):
            continue                                   # drop the session marker
        else:
            out[k] = v
    return out


def max_parallel() -> int:
    """Cap on simultaneous delegate spawns in a fan-out (ask_all). Default 6 — high enough that
    a normal free council never hits it, low enough that many custom lanes can't OOM a small
    machine or burst quota. Clamped 1..64."""
    return int_env("CLI_BRIDGE_MAX_PARALLEL", 6, 1, 64)


def current_depth() -> int:
    """How deep this cli-bridge sits in a spawn tree. 0 = top-level (spawned by the human's host).
    A delegate cli-bridge spawns gets CLI_BRIDGE_DEPTH=current+1 in its env (runner injects it), so
    a delegate that itself re-enters the bridge sees a non-zero depth here."""
    raw = os.environ.get("CLI_BRIDGE_DEPTH", "0").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def max_depth() -> int:
    """Re-entry cap: a delegate at this depth or deeper may not spawn further delegates (fork-bomb
    guard). Default 1 = the top-level bridge delegates once; a spawned delegate cannot re-spawn."""
    return int_env("CLI_BRIDGE_MAX_DEPTH", 1, 0, 16)


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
# Per-file cap (chars) for files injected into a debate/consensus CONTEXT PACK (the grounding
# contract): same truncate-with-a-marker policy as review diffs.
CONTEXT_FILE_MAX_CHARS = int_env("CLI_BRIDGE_CONTEXT_FILE_MAX_CHARS", 16000, 500, 1_000_000)


# ── round-table conversations (multi-turn, multi-lane threads via transcript replay) ──────
def convo_max_chars() -> int:
    """Sliding-window cap (chars) on the history replayed before each conversation turn.
    ~4 chars/token, so 32000 ≈ 8k tokens — about two rounds of a 4-lane round-table, or
    ~8-16 turns one-on-one. Bounds per-turn token cost regardless of how long the thread
    grows (oldest turns are dropped, newest kept). Clamped 1000..1_000_000."""
    return int_env("CLI_BRIDGE_CONVO_MAX_CHARS", 32000, 1000, 1_000_000)


def convo_summary_enabled() -> bool:
    """Rolling summary: when a thread outgrows convo_max_chars(), the lane that just answered
    condenses the oldest turns into one summary turn instead of letting them fall off the
    replay window. Costs one extra (usually free) lane call when the threshold is crossed.
    CLI_BRIDGE_CONVO_SUMMARY=off to disable (old turns then just slide out, as before)."""
    return os.environ.get("CLI_BRIDGE_CONVO_SUMMARY", "").strip().lower() not in (
        "off", "false", "0", "no")


def convo_max_stored() -> int:
    """Keep at most this many conversations in the local DB (oldest pruned whole). Threads are
    session-scoped in spirit — no need to hoard old ones forever. Clamped 1..100000."""
    return int_env("CLI_BRIDGE_CONVO_MAX_STORED", 200, 1, 100_000)


def convo_log_dir() -> str:
    """If set, each conversation is also mirrored to a readable <id>.md transcript here (handy
    to re-read a round-table after a /compact). Empty = off (sqlite is the source of truth)."""
    return os.environ.get("CLI_BRIDGE_CONVO_LOG_DIR", "").strip()


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


def echo_task() -> bool:
    """CLI_BRIDGE_ECHO_TASK=off hides the '▶ lane — asked: …' header prepended to delegation
    results. On by default: when the user re-reads the conversation in their CLI, each answer
    shows WHO was asked WHAT without scrolling back to the tool-call arguments."""
    return os.environ.get("CLI_BRIDGE_ECHO_TASK", "").strip().lower() \
        not in {"0", "false", "off", "no"}


def show_trace() -> bool:
    """CLI_BRIDGE_TRACE_FOOTER=off hides the JSON trace footer in workflow reports
    (terminal-friendly; distinct from CLI_BRIDGE_TRACE_DIR, which dumps raw traces)."""
    return os.environ.get("CLI_BRIDGE_TRACE_FOOTER", "").strip().lower() \
        not in {"0", "false", "off", "no"}


# Cooldown policy (seconds) after repeated failures of a given kind.
COOLDOWN_TIMEOUT_S = int_env("CLI_BRIDGE_COOLDOWN_TIMEOUT_S", 900, 0, 86_400)   # 15 min
COOLDOWN_QUOTA_S = int_env("CLI_BRIDGE_COOLDOWN_QUOTA_S", 3600, 0, 86_400)      # 1 h
COOLDOWN_AUTH_S = int_env("CLI_BRIDGE_COOLDOWN_AUTH_S", 1800, 0, 86_400)        # 30 min
COOLDOWN_TIMEOUT_THRESHOLD = 2   # consecutive timeouts before a lane is cooled
# An exit-0 run that returns NOTHING is, on a free tier, almost always SILENT quota/rate-limit
# exhaustion: the CLI prints no error, it just answers nothing (e.g. gemini/agy once the daily free
# quota is spent). After this many CONSECUTIVE empties the lane is cooled down so fan-out stops
# hammering a quota-dead lane; a one-off empty stays a soft per-call fall-through.
COOLDOWN_EMPTY_S = int_env("CLI_BRIDGE_COOLDOWN_EMPTY_S", 1800, 0, 86_400)       # 30 min (base)
COOLDOWN_EMPTY_THRESHOLD = 2     # consecutive empty (likely-quota) runs before a lane is cooled
# Each EXTRA empty past the threshold doubles the empty-cooldown (re-probing a quota-dead lane every
# 30 min is wasteful when the quota is a DAILY one). Capped so the lane is still re-probed within a
# day and recovers on its own (a single success resets the streak → back to the 30-min base). Never
# infinite: the cap bounds the wait, and the next probe after it always runs.
COOLDOWN_EMPTY_MAX_S = int_env("CLI_BRIDGE_COOLDOWN_EMPTY_MAX_S", 21_600, 0, 86_400)   # cap 6 h


# ── cost profile ──────────────────────────────────────────────────────────────────────
# There is no universal "free is best" — someone on a big plan may want top models by
# default. Unset => balanced, but the server's instructions tell the host to ASK on first use.
#   saver    = free-only fan-out, ENFORCED: include_paid is refused (a direct ask_<lane> call to
#              a paid lane is still allowed — that's the explicit case).
#   balanced = free by default; limited/paid lanes join fan-out only with explicit include_paid.
#   max      = quality first; ask_all includes free, limited, and paid lanes.
VALID_PROFILES = ("saver", "balanced", "max")


def include_paid_resolved(arg_value) -> bool:
    """One place for the include_paid decision, so 'saver' means the same thing everywhere:
    under saver the flag is refused (free-only fan-out, enforced); otherwise an explicit arg
    wins; otherwise only profile 'max' widens to limited/paid."""
    if profile() == "saver":
        return False
    if arg_value is not None:
        return bool(arg_value)
    return profile() == "max"


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
    "another a tight GPT quota). IMPORTANT: cli-bridge NEVER detects what a lane costs the "
    "user — the tiers it shows are sourced typical-plan defaults (docs/COSTS.md). Never "
    "present a default as a fact about their account, and never single out one lane as "
    "'paid' when its siblings have paid plans too. Have a short conversation:\n\n"
    "1. Run `doctor` first to see which CLIs they actually have installed.\n"
    "2. Open with ONE question: \"do you pay for these as flat subscriptions, metered "
    "API/credits, or a mix?\" — then, only where it differs per lane, refine: \"is your "
    "opencode on paid credits or a flat plan?\". Listen to their actual answer; don't "
    "assume free=best.\n"
    "3. Record their answers with `set_lane_cost(lane, cost, note)` — it applies immediately "
    "AND persists to the config file, so they never repeat this and the policy keeps up with "
    "reality without maintenance. (free=use freely in ask_all; limited=scarce quota, direct "
    "calls OK but skip ask_all by default; paid=money/credits.) Env vars remain the manual "
    "alternative / escape hatch:\n"
    "     CLI_BRIDGE_<LANE>_COST = free | limited | paid\n"
    "     CLI_BRIDGE_<LANE>_ENABLED = false       (hide a lane they don't want used)\n"
    "     CLI_BRIDGE_<LANE>_MODEL = <id>          (their preferred default model for a lane)\n"
    "     CLI_BRIDGE_PROFILE = saver|balanced|max (optional shorthand if they'd rather not "
    "go lane-by-lane: saver=free-only fan-out, include_paid refused (direct paid calls still "
    "work) · balanced=paid joins fan-out only when the caller passes include_paid · max=best "
    "by default)\n"
    "     CLI_BRIDGE_<LANE>_DAILY_LIMIT = <n>      (max runs/UTC day, ENFORCED at spawn for any "
    "lane — the simplest cap, no credit math needed)\n"
    "     CLI_BRIDGE_DAILY_CREDIT_CAP = <n>        (ceiling on ESTIMATED spend/day — gates paid "
    "lanes and any lane rated with CLI_BRIDGE_<LANE>_CREDITS_PER_1K; `doctor` warns when the "
    "cap can't enforce)\n"
    "4. Confirm back what you understood. The user stays in control — this just sets your "
    "default behaviour so they don't have to repeat it each call. Once set, spend confidently "
    "within it — but check `doctor` confirms the cap is enforceable before treating it as a "
    "safety net."
)

INSTRUCTIONS = (
    "cli-bridge lets you (any MCP host) consult a COUNCIL of other AI CLIs (Gemini, GPT, "
    "Mistral, opencode, …). Each lane spawns the official CLI — ban-safe, no API keys, no token "
    "extraction — read-only by default.\n\n"
    "WHAT YOU CAN DO:\n"
    "• `ask_<lane>` one model · `ask_all` poll several in parallel · `ask_best` mode="
    "fast|cheap|deep|code|review|security (let the router pick) · `ask_cascade` cheapest→"
    "strongest with auto-fallback.\n"
    "• LEARNS from you: after you judge a delegate's answer, `rate_lane` it 1–5 (with the mode). "
    "ask_best then prefers the lanes that actually win each task-type ON THIS MACHINE — a local "
    "signal that persists across sessions, not a guess.\n"
    "• SELF-MAINTAINING cost policy: whenever the user mentions what a lane costs THEM ('I'm on "
    "the Go plan', 'Codex is free on my account') or you know a vendor changed a tier, call "
    "`set_lane_cost(lane, cost, note)` — effective now, persisted to the config file. Don't wait "
    "for `setup`; one sentence from the user is enough to record.\n"
    "• ROUND-TABLE memory: pass conversation='new' to any `ask_<lane>`, then reuse the returned "
    "id — even on a DIFFERENT lane — for a multi-turn, multi-model thread that SURVIVES your "
    "context reset (/compact). `conversations_list` / `conversation_show` to recover and read.\n"
    "• Delegate REAL WORK safely: `ask_build_isolated` runs a build agent in a throwaway git "
    "worktree and returns a DIFF — your repo is never touched. Council tools advise; this one "
    "acts, safely.\n"
    "• `review_diff` / `security_review` / `debate` / `premortem` / `test_plan` for structured "
    "workflows. `doctor` to see what's installed.\n\n"
    "WHEN TO CONSULT: a hard or ambiguous problem, a second opinion before shipping, a domain a "
    "particular model is strong at, a debugging dead-end. WHEN NOT TO: trivial edits, simple "
    "library lookups, things you're already sure of — don't convene a council for one-liners.\n\n"
    "COST — spend with confidence, don't agonise: the user sets a profile (saver/balanced/max) "
    "and optional caps; operate freely within them. Two enforced caps: CLI_BRIDGE_<LANE>_"
    "DAILY_LIMIT (runs/day, any lane) and CLI_BRIDGE_DAILY_CREDIT_CAP (est. spend — needs "
    "CREDITS_PER_1K rates; `doctor` flags when it can't enforce). Cost "
    "tiers are sourced defaults (docs/COSTS.md), NEVER detected from the user's "
    "account — treat an unconfigured tier as a guess about a typical plan, not a fact about "
    "theirs. On FIRST use, if no profile/cost is set, call `setup` once — it lists what's "
    "installed and recommends a config to confirm — don't assume 'free is best' (someone on a "
    "big plan may want top models by default). Free lanes never cost anything; the user can "
    "say 'use the best on this one' or 'keep it cheap' per request."
)
