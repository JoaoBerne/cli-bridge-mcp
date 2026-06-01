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


# ── ask_best: mode-aware single-lane selection ──────────────────────────────────────────
# Modes bias the ordering toward what the task needs. A mode may REQUEST paid/limited lanes,
# but the caller's cost policy (include_paid/profile) is still the ceiling — cost-safe by
# construction. Sorting stays deterministic; health/latency come from telemetry, not guesses.
MODES = ("fast", "cheap", "deep", "code", "review", "security")
_MODE_POLICY = {
    "fast":     {"paid": False, "limited": True,  "sort": "latency"},
    "cheap":    {"paid": False, "limited": False, "sort": "cost"},
    "deep":     {"paid": True,  "limited": True,  "sort": "capability"},
    "code":     {"paid": True,  "limited": True,  "sort": "capability"},
    "review":   {"paid": False, "limited": True,  "sort": "capability"},
    "security": {"paid": False, "limited": True,  "sort": "capability"},
}
_UNKNOWN_LATENCY_MS = 30000   # untried lanes sit between known-fast and known-slow


def _fail_bucket(fail_rate: float) -> int:
    return 0 if fail_rate < 0.34 else (1 if fail_rate < 0.67 else 2)


def _mode_key(lane: LaneSpec, cd: int, perf: dict, sort: str) -> tuple:
    cooled = 1 if cd > 0 else 0
    fb = _fail_bucket(perf.get("fail_rate", 0.0))
    cost = _COST_RANK.get(lane.cost_label, 3)
    prio = _priority(lane)
    if sort == "latency":
        return (cooled, fb, perf.get("avg_ms") or _UNKNOWN_LATENCY_MS, cost, prio, lane.key)
    if sort == "capability":
        has_effort = 0 if "effort" in lane.caps else 1   # effort-capable (deep thinkers) first
        return (cooled, has_effort, fb, cost, prio, lane.key)
    return (cooled, cost, fb, prio, lane.key)   # "cost"


def order_for_mode(lanes: list[LaneSpec], cooldown_of: Callable[[str], int],
                   perf_of: Callable[[str], dict], mode: str, include_paid: bool,
                   include_limited: bool | None = None) -> list[LaneSpec]:
    pol = _MODE_POLICY.get(mode, _MODE_POLICY["cheap"])
    if include_limited is None:
        include_limited = include_paid
    allow_paid = pol["paid"] and include_paid
    allow_limited = pol["limited"] and include_limited
    pool = [ln for ln in lanes
            if (allow_paid or not ln.is_paid) and (allow_limited or not ln.is_limited)]
    return sorted(pool, key=lambda ln: _mode_key(ln, cooldown_of(ln.key), perf_of(ln.key),
                                                  pol["sort"]))


def explain_mode(lanes: list[LaneSpec], cooldown_of: Callable[[str], int],
                 perf_of: Callable[[str], dict], mode: str, include_paid: bool) -> str:
    pol = _MODE_POLICY.get(mode, _MODE_POLICY["cheap"])
    ordered = order_for_mode(lanes, cooldown_of, perf_of, mode, include_paid)
    if not ordered:
        return f"No eligible lanes for mode '{mode}'."
    rows = []
    for i, ln in enumerate(ordered, 1):
        p = perf_of(ln.key)
        bits = [ln.cost_label]
        if cooldown_of(ln.key):
            bits.append(f"cooldown {cooldown_of(ln.key)}s")
        if p.get("runs"):
            bits.append(f"~{p['avg_ms']}ms, {int(p['fail_rate'] * 100)}% fail")
        rows.append(f"{i}. {ln.key} ({', '.join(bits)})")
    return (f"Mode '{mode}' (sort: {pol['sort']}) order — would try:\n" + "\n".join(rows))


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
