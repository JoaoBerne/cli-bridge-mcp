"""CLI detection — only expose lanes whose binary actually exists on this machine."""
from __future__ import annotations

import shutil

from .lanes import LaneSpec


def is_installed(lane: LaneSpec) -> bool:
    return shutil.which(lane.bin) is not None


def installed_lanes(lanes: list[LaneSpec]) -> list[LaneSpec]:
    return [lane for lane in lanes if is_installed(lane)]
