"""MCP resource payloads — read-only JSON views of cli-bridge's own state.

The data behind `cli-bridge://config` (`_config_snapshot`) and the resource catalog
(`_RESOURCES`). server.py's `@list_resources`/`@read_resource` wire these to URIs. Pure/local —
no delegate output here.
"""
from __future__ import annotations

from . import config, guards, preamble
from .detect import is_installed
from .lanes import all_lanes


def _config_snapshot(host: str) -> dict:
    return {
        "host": host or None,
        "profile": config.profile(),
        "profile_set": config.profile_is_set(),
        "guard": guards.level(),
        "terse": preamble.level(),
        "cache_ttl_s": config.CACHE_TTL_S,
        "lanes": [
            {"key": ln.key, "installed": is_installed(ln), "enabled": ln.enabled,
             "cost": ln.cost_label,
             "cost_source": "user" if ln.cost_is_configured else "default",
             "model": ln.model_for(""), "experimental": ln.experimental,
             "caps": sorted(ln.caps)}
            for ln in all_lanes()
        ],
    }


_RESOURCES = {
    "cli-bridge://config": ("Effective config", "Profile, guard, terse, and per-lane cost/model."),
    "cli-bridge://lane-stats": ("Lane health", "Per-lane runs/failures/cooldown (JSON)."),
    "cli-bridge://usage-summary": ("Usage summary", "Estimated tokens/credits by lane (JSON)."),
}
