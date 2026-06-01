"""CLI detection — only expose lanes whose binary actually exists on this machine."""
from __future__ import annotations

import shutil

from . import config
from .lanes import LaneSpec


def is_installed(lane: LaneSpec) -> bool:
    # Dry-run mode reports every lane installed so the whole tool is explorable with no CLIs.
    return True if config.mock() else shutil.which(lane.bin) is not None


def installed_lanes(lanes: list[LaneSpec]) -> list[LaneSpec]:
    """Lanes whose binary is on PATH AND that the user hasn't disabled via env."""
    return [lane for lane in lanes if lane.enabled and is_installed(lane)]
