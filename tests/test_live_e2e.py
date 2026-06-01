"""Opt-in LIVE end-to-end checks against real installed CLIs. Skipped by default — they need a
logged-in CLI and spend a little free quota. Enable with:

    CLI_BRIDGE_LIVE_E2E=1 pytest tests/test_live_e2e.py -q
"""
import asyncio
import os

import pytest

from cli_bridge import server

pytestmark = pytest.mark.skipif(
    os.environ.get("CLI_BRIDGE_LIVE_E2E") != "1",
    reason="set CLI_BRIDGE_LIVE_E2E=1 to run live tests (needs a logged-in CLI)")


def test_live_doctor_runs():
    _lanes, host = server._active_lanes()
    assert "health check" in server._doctor(host)


def test_live_ask_first_free_lane_responds():
    lanes, _ = server._active_lanes()
    free = [ln for ln in lanes if not ln.is_paid and not ln.is_limited]
    if not free:
        pytest.skip("no free installed lane to probe")
    res = asyncio.run(server._run_lane(
        free[0], {"task": "Reply with exactly: PONG", "timeout_s": 90}, terse=False))
    assert res.ok and "PONG" in res.output.upper()
