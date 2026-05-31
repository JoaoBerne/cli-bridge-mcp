"""Lane routing — deterministic ordering for fallback (cascade) and single best pick.

Pure functions over LaneSpec + live cooldown, so they're easy to test and explain. No I/O
here beyond reading each lane's cooldown via the telemetry callback passed in.

Ordering principle: prefer lanes that are cheap, healthy (not cooled), installed, and
higher-priority. `ask_cascade` walks this order until one succeeds; `ask_best` takes the top.
"""
from __future__ import annotations

import os
from typing import Callable

from .lanes import LaneSpec

# Lower = tried first. Cost is the dominant term; everything else breaks ties.
_COST_RANK = {"free": 0, "limited": 1, "paid": 2}


def _priority(lane: LaneSpec) -> int:
    """User can pin order with CLI_BRIDGE_<LANE>_PRIORITY (lower runs earlier). Default 50."""
    raw = lane._env("PRIORITY")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 50


def score(lane: LaneSpec, cooldown_s: int) -> tuple:
    """Sort key: (cooled?, cost_rank, priority, key). Cooled lanes sink to the bottom but
    are not removed (cascade may still try them if nothing else is left)."""
    return (1 if cooldown_s > 0 else 0, _COST_RANK.get(lane.cost_label, 3),
            _priority(lane), lane.key)


def order_lanes(lanes: list[LaneSpec], cooldown_of: Callable[[str], int],
                include_paid: bool, include_limited: bool | None = None) -> list[LaneSpec]:
    """Return lanes ordered for cascade. By default excludes paid (unless include_paid) and,
    in strict free mode, limited too. Cooled lanes are kept but ranked last."""
    if include_limited is None:
        include_limited = include_paid
    pool = []
    for ln in lanes:
        if ln.is_paid and not include_paid:
            continue
        if ln.is_limited and not include_limited:
            continue
        pool.append(ln)
    return sorted(pool, key=lambda ln: score(ln, cooldown_of(ln.key)))


def explain(lanes: list[LaneSpec], cooldown_of: Callable[[str], int],
            include_paid: bool, include_limited: bool | None = None) -> str:
    ordered = order_lanes(lanes, cooldown_of, include_paid, include_limited)
    if not ordered:
        return "No eligible lanes (all paid/limited excluded, or none installed)."
    rows = []
    for i, ln in enumerate(ordered, 1):
        cd = cooldown_of(ln.key)
        flags = [ln.cost_label]
        if cd:
            flags.append(f"cooldown {cd}s")
        if ln.experimental:
            flags.append("experimental")
        rows.append(f"{i}. {ln.key} ({', '.join(flags)})")
    return "Cascade order:\n" + "\n".join(rows)
