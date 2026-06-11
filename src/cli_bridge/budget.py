"""Spend guard — the single pre-spawn budget chokepoint.

Every delegate spawn goes through check_spawn(). Two independent gates, both opt-in:

1. Daily run limit (CLI_BRIDGE_<LANE>_DAILY_LIMIT, runs per UTC day).
   Enforced for EVERY lane with zero extra setup — no credit math needed. The simplest
   way to cap a quota'd or paid lane.
2. Daily credit cap (CLI_BRIDGE_DAILY_CREDIT_CAP, estimated credits per UTC day).
   Gates any lane whose spend is measurable as money: paid lanes, plus any lane the
   user rated with CLI_BRIDGE_<LANE>_CREDITS_PER_1K (a rated 'limited' lane spends
   credits too). Free, unrated lanes are never gated by the cap.

Token/credit figures are estimates (chars/4) — never presented as exact. Telemetry
being unavailable never blocks a spawn (the gates fail open, not closed: a broken
local sqlite must not take the council down). Full model: docs/BUDGET.md.
"""

from __future__ import annotations

from . import config, telemetry
from .lanes import LaneSpec


def check_spawn(lane: LaneSpec) -> str | None:
    """Return a human-readable block reason if this spawn must be refused, else None."""
    limit = config.lane_env_int(lane.key, "DAILY_LIMIT")
    if limit is not None and limit >= 0:
        runs = telemetry.lane_runs_today(lane.key)
        if runs >= limit:
            return (
                f"daily run limit reached for '{lane.key}' ({runs}/{limit} runs since UTC "
                f"midnight). Raise CLI_BRIDGE_{lane.key.upper()}_DAILY_LIMIT or wait for "
                "the UTC reset."
            )
    cap = config.daily_credit_cap()
    if cap > 0:
        rated = config.lane_env_float(lane.key, "CREDITS_PER_1K") is not None
        if lane.is_paid or rated:
            spent = telemetry.est_credits_today()
            if spent >= cap:
                return (
                    f"daily credit cap reached (~{spent}/{cap:g} est. credits today); lane "
                    f"'{lane.key}' refused because it spends credits. Raise "
                    "CLI_BRIDGE_DAILY_CREDIT_CAP or use a free, unrated lane."
                )
    return None
